# Revisión cruzada: seguridad y arquitectura

Revisé `1_protocolo.md` y `3_ux.md` con el dato nuevo: SN/NDK 2.12.2 cifra con NIP-04 y exige `"ack"`.
Script nuevo, fuera del repo: `scratchpad\mesa\prueba_nip04.py`.
**[PROBADO]** = ejecutado y verificado aquí; **[NO PROBADO]** = falta verificar.

## NIP-04 con `cryptography` **[PROBADO: ida y vuelta A→B, unicode, un tercero no descifra]**

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
clave = PublicKey(b"\x02" + pub_x).multiply(secreto).format()[1:]      # X sin hashear, igual que en NIP-44
iv = os.urandom(16)
p = padding.PKCS7(128).padder(); datos = p.update(texto.encode()) + p.finalize()
e = Cipher(algorithms.AES(clave), modes.CBC(iv)).encryptor(); ct = e.update(datos) + e.finalize()
contenido = b64(ct) + "?iv=" + b64(iv)
# descifrar: partition("?iv="), b64decode(validate=True), exigir len(iv)==16 y len(ct)%16==0 y >0,
#            decryptor + PKCS7(128).unpadder(); cualquier excepción → ValueError genérico
```
Solo probé la ida y vuelta: **no lo comparé con un vector externo** (nostr-tools). Igual hay buen respaldo: la
conversación con SN usa el mismo `shared_x` que NIP-44, y ese ya coincide con el vector oficial. La prueba de
interoperabilidad real es la etapa (c/e).

## Hallazgos

1. **[Bloqueante] NIP-04 obligatorio y respuesta con el mismo esquema.** Se acepta lo que propone protocolo.
   Cambio: crear `nostr/nip04.py` (cifrar y descifrar, unas 25 líneas) y que `firmante.py` haga
   `esquema = "nip04" if "?iv=" in content else "nip44"` para responder con el mismo esquema. Mi plan pasa NIP-04 de
   "no probado, ojalá evitable" a **núcleo**.
   *Riesgo de detectar por "?iv="*: es inequívoco, porque `?` no pertenece al alfabeto base64 estándar
   **[PROBADO]**, así que un payload NIP-44 nunca lo contiene. Si NIP-04 falla, **no** se prueba con NIP-44 ni al revés
   (eso solo agrega superficie de ataque). Se descarta en silencio.

2. **[Importante] NIP-04 no tiene MAC (CBC maleable, oráculo de padding).** Mitigación barata, ya prevista en el
   punto 5 de protocolo: **verificar id y firma Schnorr del evento 24133 antes de descifrar**. Un atacante no puede
   enviar un texto cifrado modificado "como C" sin la clave de C, y con su propia clave obtiene otra `shared_x`.
   Cambio: ante un descifrado fallido, **no responder nada** (sin mensaje de error distinguible) y loguear solo
   "contenido indescifrable de <pub corta>".

3. **[Importante] `connect` y rotación del secret frente a los reintentos de SN.** NDK crea una clave de cliente
   efímera en cada intento. Si el secret es de un solo uso, un segundo intento necesita un `bunker://` nuevo.
   Cambio: cuando llega un `connect` con el secret vigente → responder `"ack"`, fijar `cliente_autorizado = C`,
   **rotar el secret** y mostrar el nuevo bunker en la UI (C se actualiza solo). Con un secret inválido o usado →
   `error`. Se ignora `params[0]`, que llega `""`. `get_public_key`, `sign_event` y `ping` de una pubkey distinta de
   `cliente_autorizado` → `error: "no autorizado"`. Hay que **exigir siempre secret** (nunca un bunker sin secret).

4. **[Importante] Validación de `sign_event` sin romper el login.**
   - **Lista blanca: solo `kind 27235`** (es lo que firma SN, según `nostr-auth.js`). Cualquier otro kind →
     error automático `"kind no permitido"`, sin mostrarlo para aprobación. Así la clave real del usuario no puede
     firmar notas, perfiles ni zaps aunque el usuario haga clic por error. Es una regla documentada en el README y
     una constante `KINDS_PERMITIDOS = {27235}` fácil de ampliar.
   - `tags[0][0] == "challenge"` y content `"Stacker News Authentication"`: si no se cumplen, igual se puede aprobar,
     pero con un **aviso visible** (sin bloquear).
   - Tag `u`: mostrar el **host** en la tarjeta. Si no es `stacker.news` → aviso de advertencia
     ("Este pedido es para <host>, no para stacker.news"). **No bloquear**: en desarrollo, NEXT_PUBLIC_URL es localhost.
   - `pubkey` del parámetro: si viene y ≠ B → error. `created_at` fuera de ±10 min → aviso.
   - Si el `id` del parámetro ≠ el id que recalculamos → error (la firma no le serviría a NDK; acepto lo que propone
     protocolo).
   - Tamaño: params[0] ≤ 64 KiB, tags ≤ 50, todos los valores de las tags deben ser str.

5. **[Importante] La UX nombra mal los kinds y atribuye el pedido a "Stacker News".** La tabla de UX dice que
   22242 es "Inicio de sesión". El login de SN es **27235**, y 22242 es AUTH de relay (NIP-42). Además, el bunker no
   sabe quién es C: solo tiene una pubkey. Cambio: tarjeta con el título "Pedido de firma de inicio de sesión", la
   línea "Para: stacker.news" (sale de la tag `u`) y "Cliente: npub1… (abreviado)". Se borran las filas 22242, 1 y 0
   y el texto de "Tipo N (desconocido)", porque esos pedidos ya no llegan a la UI (hallazgo 4). En el historial dirá
   "Rechazado automáticamente: kind N no permitido".

6. **[Importante] La CSP propuesta rompe el token inline y los `style=""`.** Con `default-src 'self'`, un
   `<script>` inline con el token no corre. Cambio: el servidor reemplaza `{{TOKEN}}` en
   `<meta name="token" content="{{TOKEN}}">` y `app.js` lo lee con `document.querySelector`. Sin JS ni atributos
   `style` inline: todo va en `app.css` y las animaciones se hacen con clases.

7. **[Importante] La API no cubría todos los estados de la UX.** Así queda ajustada:

   | Estado UX | Cómo se obtiene |
   |---|---|
   | A | `estado.fase == "sin_clave"` |
   | A2 | solo en el frontend: lo muestra la respuesta de `POST /api/crear` cuando trae `nsec` (no vuelve en `/api/estado`). Si se recarga la página, no reaparece |
   | B | `fase == "bloqueado"` + `POST /api/desbloquear` |
   | C | `fase == "listo"`, `npub`, `bunker`, `relay`, `cliente` |
   | D | `pendientes[]` (máximo 1 a la vez es suficiente para SN; el resto se rechaza con "ocupado") |
   | E | **nuevo** `historial[]` (los últimos 20): `{ts, tipo: "conexion"|"pubkey"|"firma"|"rechazo"|"error", detalle}` **sin content ni tags** |
   | Bloquear | **nuevo** `POST /api/bloquear`: borra la clave de la memoria, vacía los pendientes (responde error a SN) y deja de responder RPC |
   | Servidor caído | el `fetch` del polling falla, y el JS muestra el aviso de UX |

   Riesgo de A2: si la página se recarga antes de respaldar, se pierde el nsec. Para mitigarlo, el texto de A2 lo
   advierte ("no recargues esta página"). Lo acepto como tradeoff y lo anoto en el README.

8. **[Menor] Pequeñas filtraciones en la UX.**
   - Campos: `autocomplete="off"` y `spellcheck="false"` en el nsec, y `autocomplete="new-password"` /
     `"current-password"` en las contraseñas, para que el navegador no guarde el nsec en el autocompletado.
   - Copiar el nsec en A2 lo deja en el portapapeles (y en el historial Win+V). Agregar la línea "borra el
     portapapeles después".
   - El `bunker://` contiene el secret: está bien mostrarlo, pero el aviso de UX ("No lo publiques") se queda.
     El secret no va al historial ni a los logs.
   - Enlace "Abrir Stacker News": `rel="noopener noreferrer"`.
   - En el "Ver evento completo (JSON)" se usa `textContent` dentro de `<pre>`, nunca `innerHTML`.
   - La pista de B "borra `data/`" está bien, y con ella **sobra** `POST /api/olvidar` (ver punto 10).

9. **[Menor] Detalles de protocolo.** Deduplicar por `event.id` con un set acotado (~500). Usar `since = ahora - 30 s`
   por el desfase de reloj (entre 10 s y 30 s da igual). Que el WS esté suscrito **antes** de mostrar el bunker en la
   UI (`relay` debe estar `"conectado"`; si no, la UI muestra el bunker atenuado). El relay por defecto es
   `wss://relay.damus.io`, configurable por la variable de entorno `NOSTR_RELAY`. Los errores al responder van con
   `result: ""` + `error`.

10. **[Menor] Lo que sobra para unas 3 horas.**
    - Se quita: sonido WebAudio, animación `@keyframes`, cola "Pedido 1 de N", `POST /api/olvidar`, tabla de kinds,
      ver el nsec después del alta, atajos de teclado y empaquetar fuentes.
    - Se simplifica: la reconexión pasa a un backoff fijo (1, 2, 5, 10 s), y alcanza con verificar el Host (además,
      el Origin solo en POST).
    - Se mantiene, aunque SN no lo use: NIP-44 (el prototipo ya pasa el vector; implementarlo y correr sus tests
      cuesta unos 15 min, y la spec lo exige), `ping` y CSP (una línea).
    - Prioridad de implementación: claves/bech32 → eventos/firma → NIP-04 → relay + firmante → API + UI mínima → NIP-44 → pulido visual.
