# Mesa de diseño — 2. Seguridad y arquitectura Python

Entorno verificado: Python del `.venv`, `coincurve 21.0.0`, `cryptography 50.0.2`, `aiohttp 3.14.5`.
Script de pruebas (fuera del repo): `scratchpad\mesa\prueba_cripto.py`.
Leyenda: **[PROBADO]** = ejecutado y verificado aquí; **[NO PROBADO]** = diseño, falta verificar.

---

## 1. Archivo de clave `data/clave.json`

```json
{
  "version": 1,
  "kdf": {"nombre": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": "<b64 16 B>"},
  "cifrado": {"nombre": "chacha20poly1305", "nonce": "<b64 12 B>", "datos": "<b64 32 B + tag 16 B>"},
  "pubkey": "<hex x-only 32 B>"
}
```

- **scrypt n=2^17, r=8, p=1** (128 MiB, ~0,28 s en esta máquina) **[PROBADO]**. Tiempos medidos:
  2^15 0,07 s · 2^16 0,14 s · 2^17 0,28 s · 2^18 0,58 s. Se elige 2^17 (recomendación OWASP vigente es ≥ 2^17 con r=8);
  2^18 también cabe en el presupuesto de 1 s. Los parámetros se **leen del archivo**, así se pueden subir sin romper archivos viejos.
- **salt** 16 B y **nonce** 12 B con `os.urandom`, nuevos en cada guardado (nunca reutilizar nonce con la misma clave).
- **AAD** = `b"nostr-signer/clave/v1|" + pubkey_hex`. Así, si alguien edita `pubkey` o `version`, el descifrado falla
  (`InvalidTag`) **[PROBADO: AAD alterado → InvalidTag]**. Tras descifrar se verifica además que la pubkey derivada == `pubkey`.
- `pubkey` en claro permite mostrar "¿desbloquear la cuenta npub1…?" sin pedir contraseña (no es secreto).
- Escritura atómica: escribir `clave.json.tmp` y `os.replace()`. Contraseña mínima de 8 caracteres (validar en backend).

```python
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
k = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(contrasena.encode())  # objeto de un solo uso
datos = ChaCha20Poly1305(k).encrypt(nonce, secreto32, aad)   # devuelve ct||tag
secreto32 = ChaCha20Poly1305(k).decrypt(nonce, datos, aad)   # lanza cryptography.exceptions.InvalidTag
```

**Flujo**: al iniciar, si no existe `data/clave.json` la página ofrece "Generar" o "Pegar nsec" + contraseña (x2).
Si existe, pide solo la contraseña ("Desbloquear"). La clave queda en memoria del proceso mientras corre; nunca
vuelve al navegador. Contraseña incorrecta → mensaje genérico, con espera de ~1 s (scrypt ya la impone).
**Contraseña olvidada**: no hay recuperación (es la propiedad deseada). La UI ofrece "Olvidé la contraseña: borrar
la clave guardada y empezar de nuevo" (requiere confirmación; el usuario restaura con su nsec respaldado).
Correr scrypt con `await asyncio.to_thread(...)` para no bloquear el event loop (y el WebSocket del relay).

## 2. coincurve: ECDH sin hash y Schnorr

- `PrivateKey.ecdh(public_key)` **no tiene `hashfn`** en v21 (firma: `ecdh(self, public_key)`) y devuelve
  `sha256(punto comprimido)` **[PROBADO]**. Por eso **no sirve para NIP-44**.
- Coordenada X sin hashear **[PROBADO, vector oficial 1 de NIP-44 coincide]**:

```python
from coincurve import PrivateKey, PublicKey, PublicKeyXOnly
x_compartida = PublicKey(b"\x02" + pub_x_only).multiply(secreto32).format()[1:]   # 32 B
```
  (Anteponer `02` es correcto: el x de `k·P` no depende de la paridad de `P`. `multiply` usa
  `secp256k1_ec_pubkey_tweak_mul`, de tiempo constante.)
- Pubkey Nostr x-only: `PrivateKey(s).public_key.format()[1:]` == `PublicKeyXOnly.from_secret(s).format()` **[PROBADO]**.
- Firma BIP-340 **[PROBADO]**:
```python
sig = PrivateKey(s).sign_schnorr(id_evento_32B, os.urandom(32))   # 64 B; aux aleatorio recomendado
ok  = PublicKeyXOnly(pub_x).verify(sig, id_evento_32B)
```
  `sign_schnorr` firma el mensaje **tal cual** (no lo hashea): se le pasa el `id` (sha256 de la serialización NIP-01).
  El firmante **recalcula** el id; nunca confía en un `id` enviado por el cliente.

### NIP-44 v2 con `cryptography` **[PROBADO: conversation_key y payload del vector 1 idénticos; ida y vuelta OK]**

| Paso | Uso exacto |
|---|---|
| conversation_key = HKDF-Extract(salt="nip44-v2", IKM=x) | `hmac.HMAC(b"nip44-v2", hashes.SHA256())` + `update(x)` + `finalize()` (Extract = HMAC; la clase `HKDF` no expone solo Extract) |
| claves del mensaje | `HKDFExpand(algorithm=hashes.SHA256(), length=76, info=nonce32).derive(conversation_key)` → `[0:32]` chacha_key, `[32:44]` chacha_nonce, `[44:76]` hmac_key |
| cifrar | `Cipher(algorithms.ChaCha20(chacha_key, b"\0\0\0\0" + chacha_nonce), mode=None).encryptor()` — nonce de 16 B = contador 4 B LE (0) + nonce 12 B |
| MAC | `hmac.HMAC(hmac_key, hashes.SHA256())`, `update(nonce32 + ciphertext)`; al descifrar usar `.verify(mac)` (tiempo constante) **antes** de descifrar |
| payload | `base64(0x02 ‖ nonce32 ‖ ct ‖ mac)`; padding `u16 BE largo ‖ texto ‖ ceros` según `calc_padded_len` |

Validaciones al descifrar: no empieza con `#`; largo base64 entre 132 y 87472; versión 2; MAC; largo de
padding exacto; texto 1..65535 bytes. Usar `ChaCha20Poly1305` **solo** para el archivo de clave, nunca en NIP-44.
(Si el experto de protocolo confirma que SN necesita NIP-04, ese sería AES-256-CBC con `algorithms.AES` + `modes.CBC`;
**[NO PROBADO]**, ojalá evitable.)

## 3. Modelo de amenazas (app local, un usuario)

| Amenaza | Medida mínima |
|---|---|
| Otro equipo de la red usa la API | `web.run_app(host="127.0.0.1")`, nunca `0.0.0.0` |
| Otra web abierta en el navegador llama a `127.0.0.1` (CSRF) | Toda acción es `POST` JSON con cabecera `X-Token` (token aleatorio `secrets.token_urlsafe(32)` por arranque, inyectado en `index.html` al servirlo). Una cabecera propia fuerza preflight CORS que no respondemos → bloqueado. Además, si viene `Origin`, debe ser `http://127.0.0.1:PUERTO` o `http://localhost:PUERTO`. Comparar token con `hmac.compare_digest` |
| DNS rebinding (evil.com resuelve a 127.0.0.1) | Middleware que rechaza (403) si `Host` ∉ {`127.0.0.1:PUERTO`, `localhost:PUERTO`}. También en GET (el estado revela la npub y los pedidos) |
| Clickjacking / scripts externos | Cabeceras `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` en `/api/*`. Todo texto del evento se inserta con `textContent`, nunca `innerHTML` |
| Filtración de secretos | `nsec`, secreto hex, contraseña, conversation_key y **contenidos descifrados** nunca en logs. Se loguea solo `method`, `id` del pedido y pubkey del cliente abreviada. `repr()` de la clase de claves devuelve `<ClaveNostr npub1…>`. Log de aiohttp sin cuerpos |
| Cliente ajeno usa el bunker | `bunker://<pub>?relay=…&secret=<token_urlsafe(16)>`. `connect` exige `params[1] == secret` (compare_digest). El primer cliente válido queda como **único cliente autorizado**; el resto de métodos de otras pubkeys se ignoran/responden error. El secret se invalida tras usarse (botón "nuevo bunker" genera otro) |
| Firma no deseada | Cada `sign_event` va a la cola y requiere clic en "Aprobar". Se muestra `kind`, `content` (truncado), `tags` y `created_at`. Timeout de aprobación 120 s → respuesta `error: "rechazado"`. Máx. 5 pedidos pendientes |
| Mensajes enormes / malformados | Mensajes del relay > 128 KiB se descartan (`max_msg_size` en `ws_connect`). Payload NIP-44 con límites del estándar. JSON de RPC validado (tipos, `id` str, `params` lista). Eventos kind 24133 con `created_at` muy viejo (> 5 min) o `id` repetido se ignoran (anti-replay) y se verifica la firma del evento entrante |
| Caída del relay | Bucle de reconexión con backoff 1-2-4…30 s; al reconectar se re-suscribe con `since=ahora-10s`. Estado del relay visible en la UI |

**UI muestra**: npub, `bunker://` (con botón copiar), estado del relay, cliente conectado, pedidos pendientes e historial
breve. **No muestra**: contraseña, ni el nsec salvo **una vez al generarlo** (con "lo guardé" para continuar). No hay
"ver nsec" posterior (si se quiere, solo reingresando la contraseña; fuera de alcance).

## 4. Arquitectura de archivos

```
app.py                 aiohttp: rutas, middleware (Host/Origin/token/cabeceras), arranque y apagado
firmante.py            lógica NIP-46: suscripción al relay, despacho de métodos, cola de aprobaciones
relay.py               cliente WebSocket a un relay con reconexión, envío de EVENT y REQ
almacen.py             leer/escribir data/clave.json (scrypt + ChaCha20-Poly1305)
nostr/claves.py        generar clave, nsec/npub <-> bytes, pubkey x-only, firmar
nostr/bech32.py        bech32 (BIP-173) mínimo para nsec/npub
nostr/nip44.py         conversation_key, cifrar, descifrar (v2)
nostr/eventos.py       serializar NIP-01, calcular id, firmar y verificar eventos
static/index.html, app.css, app.js   página única (desbloquear / bunker / aprobaciones)
tests/test_bech32.py, test_nip44.py, test_eventos.py, test_almacen.py   pytest
tests/vectores/nip44.vectors.json    vectores oficiales (descargados una vez)
herramientas/sn_falso.py             cliente NIP-46 de prueba contra el relay real
```

**API local** (todo JSON, todo bajo `/api`, todo con `X-Token`):

| Ruta | Uso |
|---|---|
| `GET /api/estado` | `{fase: "sin_clave"|"bloqueado"|"listo", npub, bunker, relay: "conectado"|"reconectando", cliente, pendientes:[…]}` |
| `POST /api/crear` | `{contrasena, nsec?}` → si no hay nsec, genera; responde `{nsec}` **solo** si fue generado |
| `POST /api/desbloquear` | `{contrasena}` |
| `POST /api/responder` | `{id, aprobar: bool}` |
| `POST /api/olvidar` | borra `data/clave.json` (confirmación en UI) |

Sincronización: **polling** de `/api/estado` cada 1 s. Es lo más simple y robusto (sin reconexión de un segundo WS,
la página se recupera sola tras recargar). Pedido pendiente:
`{id: "<uuid corto local>", metodo: "sign_event", cliente: "npub1…", recibido: ts, expira: ts, evento: {kind, content, tags, created_at}}`.
En el backend es un `dict[id] -> (datos, asyncio.Future)`; `/api/responder` resuelve el Future y `firmante.py`
lo espera con `asyncio.wait_for(fut, 120)`.

## 5. Verificación por etapas

a. **bech32/claves** — pytest con los ejemplos de NIP-19 (npub/nsec ↔ hex) y ida/vuelta; nsec con checksum o HRP malo → error.
b. **NIP-44** — `test_nip44.py` recorre `valid.get_conversation_key`, `valid.encrypt_decrypt`, `valid.calc_padded_len`
   e `invalid.*` del JSON oficial (paulmillr/nip44). Ya hay prototipo que pasa el vector 1 **[PROBADO]**.
   Eventos: firmar + verificar con `PublicKeyXOnly.verify` e id recalculado. Almacén: guardar/leer, contraseña mala → error, AAD alterada → error.
c. **SN falso** — `herramientas/sn_falso.py <bunker://…>`: genera clave efímera, envía `connect` con secret, luego
   `get_public_key`, `ping` y `sign_event` (kind 22242 de prueba) por el relay real; verifica la firma devuelta.
   Casos negativos: secret incorrecto, segundo cliente distinto. **[NO PROBADO]**
d. **Aprobación** — con (c) corriendo: aprobar, rechazar y dejar expirar (timeout 120 s, se puede bajar por variable de entorno en pruebas). Probar `curl` con `Host: evil.com` y sin token → 403. **[NO PROBADO]**
e. **Real** — login en Stacker News pegando el `bunker://`. Anotar en README el relay y el resultado. **[NO PROBADO]**
