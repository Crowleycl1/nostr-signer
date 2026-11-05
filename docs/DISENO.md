# Diseño — Firmante Nostr NIP-46 para Stacker News

> Documento de diseño consolidado. Sale de una "mesa de trabajo" de 3 expertos (protocolo, seguridad, UX/UI)
> que propusieron por separado y después se revisaron entre ellos. Las propuestas y revisiones originales
> están en [docs/ai-logs/mesa-diseno/](ai-logs/mesa-diseno/).
>
> **Para quien modifique este proyecto (humano o IA):** este documento es la fuente de verdad. Si cambias
> una decisión, actualiza esta página y el README.

Diagramas del flujo completo (incluida la página de Stacker News): [FLUJO.md](FLUJO.md).

Fecha: 2026-11-04 · Enunciado: "PRUEBA DE CONOCIMIENTOS TÉCNICOS - DEV" (Gob Digital / Hacienda).

---

## 1. Qué construimos (en simple)

Una app local (`python app.py` → http://localhost:8000) que **guarda tu clave secreta de Nostr cifrada** y
**firma por ti** cuando Stacker News lo pide, **solo si tú lo apruebas**.

Stacker News nunca ve tu clave. Le das un enlace `bunker://…`; SN te manda pedidos cifrados a través de un
**relay** (un servidor público que reenvía mensajes); nuestra app los recibe, te pregunta, firma y responde.

```
 Navegador (tú)          app.py (este proyecto)              relay.damus.io            Stacker News
 ─────────────          ──────────────────────              ──────────────            ────────────
 página localhost  ⇄  API local  ⇄  firmante NIP-46  ⇄  WebSocket (kind 24133)  ⇄  NDK en el navegador
                    (SSE + POST)      clave en memoria        mensajes cifrados
```

## 2. Hechos verificados (no supuestos)

Fuentes: specs `nostr-protocol/nips@master`, código de `stackernews/stacker.news@27938a6` (2026-11-03) y
`@nostr-dev-kit/ndk@2.12.2` (versión exacta del `package-lock.json` de SN).

| # | Hecho | Fuente |
|---|---|---|
| H1 | **SN cifra con NIP-04, no con NIP-44.** NDK parte con `encryptionType="nip04"` y solo cambia a NIP-44 si recibe una respuesta sin `?iv=`. | ndk `signers/nip46/rpc.ts:37,109-112,206` |
| H2 | `connect` debe responder **exactamente `"ack"`**. Devolver el secret (que la spec permite) rompe el login. | ndk `signers/nip46/index.ts:184-191` |
| H3 | `connect` llega con `params = ["", secret]`: el primer parámetro viene **vacío**. | ndk `index.ts:172-174` |
| H4 | Orden: `connect` → `get_public_key` → `sign_event`. | SN `components/nostr-auth.js:122-163` |
| H5 | Se firma un **kind 27235** (NIP-98), content `"Stacker News Authentication"`, tags `[["challenge",k1],["u",URL],["method","GET"]]`. El servidor de SN exige que `tags[0]` sea el challenge. | SN `nostr-auth.js:148-156`, `pages/api/auth/[...nextauth].js` |
| H6 | NDK solo usa el campo `sig` de la respuesta; conserva su propio id/pubkey/created_at. | ndk `index.ts:256-273` |
| H7 | NDK crea una **clave de cliente nueva en cada intento** de login y reenvía el mismo secret. | SN `nostr-auth.js:122`, ndk `index.ts:89-90,174` |
| H8 | No hay timeout: NDK espera indefinidamente; SN muestra una sugerencia a los 10 s. | SN `nostr-auth.js:101-106,138` |
| H9 | SN usa solo los relays del `bunker://`. | ndk `rpc.ts:46-63` |
| H10 | Los kinds 20000–29999 son **efímeros**: el relay no los guarda. Si no estamos suscritos cuando llega el `connect`, se pierde. | NIP-01 |
| H11 | `wss://relay.damus.io` hizo ida y vuelta de un 24133 en 0,38 s. `relay.nsec.app` no respondió (2026-11-04). | prueba propia |
| H12 | `coincurve.PrivateKey.ecdh()` devuelve sha256 del punto (no sirve). X sin hashear: `PublicKey(b"\x02"+x).multiply(sk).format()[1:]`. | probado en `.venv` |
| H13 | NIP-44: la conversation_key y el payload del vector oficial 1 coinciden con el prototipo. NIP-04: ida y vuelta OK. | probado en `.venv` |
| H14 | `relay.damus.io` **limita la tasa por IP**: tras varias pruebas seguidas respondió `OK false "rate-limited: you are noting too much"`, luego 503 al conectar y finalmente `"banned: too many rate-limit violations"` (temporal). Una respuesta descartada deja a SN esperando para siempre (H8). `nos.lol`, `relay.primal.net` y `offchain.pub` reenvían 24133 en 0,25–0,47 s. **Medida:** `relay.py` reintenta una publicación rechazada con `rate-limited` a los 5 y 15 s (no más: insistir agrava el bloqueo). | prueba propia, etapa c (2026-11-04) |

**La ambigüedad principal:** la spec NIP-46 dice "usar NIP-44", pero el cliente real (SN/NDK) usa NIP-04.
**Decisión:** implementar ambos y **responder con el mismo esquema en que llegó el pedido**
(`"?iv=" in content` → NIP-04; el `?` no existe en base64, así que la detección es inequívoca).

## 3. Decisiones y tradeoffs

| Tema | Decisión | Por qué / tradeoff |
|---|---|---|
| Clave en disco | `data/clave.json` cifrada: **scrypt** (n=2¹⁷, r=8, p=1, ~0,3 s) + **ChaCha20-Poly1305**, AAD = versión + pubkey | Robar el archivo no basta. Si olvidas la contraseña no hay recuperación (por diseño). Formato propio: NIP-49 usa XChaCha20, que `cryptography` no trae. |
| Clave del bunker | **La misma clave del usuario** | Lo más simple; la spec lo permite. Tradeoff: la pubkey del usuario es visible en el relay como firmante. |
| Relay | `wss://relay.damus.io`, configurable con la variable `NOSTR_RELAY` | Verificado hoy. Un solo relay (el enunciado no pide redundancia). Ojo con el límite de tasa de damus (H14): para pruebas repetidas, usar `NOSTR_RELAY=wss://nos.lol`. |
| Secret del bunker | Obligatorio. Se **rota tras cada `connect` válido**; la UI muestra el enlace nuevo | La spec lo pide (un solo uso). Tradeoff: para reintentar el login hay que copiar el enlace nuevo (H7). |
| Clientes autorizados | **Conjunto en memoria** de pubkeys que presentaron un secret válido | Un "cliente único" rompía el reintento/logout→login (H7). Se borra al cerrar la app. |
| Qué se puede firmar | **Solo inicios de sesión, en cualquier sitio**: kind 27235 (NIP-98, "login HTTP") con tags `u` (URL del sitio) y `method`. Cualquier otro kind → rechazo automático, sin mostrarlo (`KINDS_PERMITIDOS = {27235}`) | La app sirve para cualquier web que use login Nostr estándar, no solo para SN. La clave no puede firmar notas, perfiles ni zaps aunque hagas clic por error. Contra sitios falsos: la tarjeta muestra el sitio en grande y el usuario decide. **Supuesto:** otras webs usan 27235 para el login; si alguna usa otro kind, se agrega a la constante. |
| Aprobación | Manual, **un pedido pendiente a la vez**, expira a los **120 s** con error | Compatible con SN (H8). Más simple que una cola. |
| Sincronización página ↔ backend | **Server-Sent Events** (`GET /api/eventos`): el servidor empuja el estado solo cuando cambia; los clics van por `POST` | Pedido del usuario: nada de preguntar cada segundo. SSE es nativo (`EventSource`), se reconecta solo y no necesita librerías. Un WebSocket local sería bidireccional, pero no hace falta y es más código. |
| NIP-44 | Se implementa y se prueba con **todos** los vectores oficiales | La spec lo exige y cuesta ~15 min, aunque SN hoy use NIP-04. |
| Fuera de alcance | `nip04_encrypt/decrypt`, `nip44_*`, `get_relays`, `switch_relays`, flujo `nostrconnect://`, NIP-49, varios usuarios, varios relays, permisos finos, recuperar la contraseña, ver el nsec después del alta | El enunciado pide lo mínimo para el login de SN. |

## 4. Protocolo: mensajes exactos

`B` = nuestra pubkey (usuario = bunker). `C` = pubkey efímera de SN. Todo va dentro de eventos
`{"kind":24133,"pubkey":<emisor>,"tags":[["p",<receptor>]],"content":<cifrado>}`.

```
0. bunker → relay   ["REQ","s",{"kinds":[24133],"#p":["B"],"since":<ahora-30>}]   (ANTES de mostrar el bunker)
1. C → B (NIP-04)   {"id":"k3j9x","method":"connect","params":["","<secret>"]}
   B → C            {"id":"k3j9x","result":"ack"}                       → se rota el secret, C queda autorizado
2. C → B            {"id":"a8f2q","method":"get_public_key","params":[]}
   B → C            {"id":"a8f2q","result":"<B hex>"}
3. C → B            {"id":"z1m0p","method":"sign_event","params":["{\"kind\":27235,\"created_at\":…,\"tags\":[[\"challenge\",…],[\"u\",…],[\"method\",\"GET\"]],\"content\":\"Stacker News Authentication\",\"pubkey\":\"B\",\"id\":\"…\"}"]}
   (el usuario aprueba)
   B → C            {"id":"z1m0p","result":"<evento firmado en JSON>"}
   (rechaza/expira) {"id":"z1m0p","result":"","error":"rechazado por el usuario"}
4. ping             → {"result":"pong"}
5. otro método      → {"result":"","error":"método no soportado"}
```

**Reglas del firmante**
1. Por cada evento entrante: verificar `kind==24133`, tag `p` == B, **id y firma Schnorr** (antes de descifrar:
   NIP-04 no tiene MAC) y deduplicar por `id` (set acotado). Ignorar mensajes `AUTH` del relay.
2. Descifrar con el esquema detectado. Si falla, **no responder** y loguear solo "indescifrable de <pub corta>".
3. Cada pedido se atiende en su **propia tarea** (`asyncio.create_task`): una firma esperando aprobación no
   debe bloquear `get_public_key` ni `ping`.
4. `connect`: ignorar `params[0]`; comparar `params[1]` con el secret vigente usando `hmac.compare_digest`.
   Si `C` ya está autorizado, responder `"ack"` igual (idempotente).
5. `get_public_key` / `sign_event` de un cliente no autorizado → `error: "no autorizado"`.
6. `sign_event`: tomar `kind, created_at, tags, content` **tal cual** (sin reordenar tags), poner `pubkey=B`,
   recalcular el id (NIP-01: `json.dumps([0,pubkey,created_at,kind,tags,content], separators=(",",":"), ensure_ascii=False)`),
   firmar con `sign_schnorr(id, os.urandom(32))`. Error si el `pubkey` o el `id` que trae el pedido no coinciden
   con los nuestros. Validar tamaño (≤ 64 KiB, ≤ 50 tags, valores str).
7. **Filtro de login (bloquea):** si no es kind 27235, o le falta la tag `u` (URL http/https válida) o `method`
   (NIP-98 exige ambas) → `error: "solo se firman inicios de sesión"`, sin mostrarlo al usuario; queda en el
   historial como "Bloqueado". El **sitio** (host de `u`) se muestra en grande en la tarjeta para que el usuario lo
   revise. Avisos (no bloquean): `u` no es https; `created_at` a más de ±10 min.
8. Reconexión al relay con espera 1, 2, 5, 10 s (fija) y re-envío del `REQ`.

## 5. Seguridad local (app en tu computador)

| Riesgo | Medida |
|---|---|
| Otro equipo de la red | `host="127.0.0.1"`, nunca `0.0.0.0` |
| Otra web abierta llama a la API (CSRF) | Acciones solo por `POST` JSON con cabecera `X-Token` (aleatorio por arranque, comparado con `compare_digest`), y además revisión de `Origin` en los POST |
| DNS rebinding | Middleware: `Host` debe ser `localhost:PUERTO` o `127.0.0.1:PUERTO`; si no, 403 (también en GET) |
| Scripts inyectados / clickjacking | `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `nosniff`, `no-store` en `/api`. **Sin JS ni `style` inline**: el token va en `<meta name="token">`. Todo texto externo se pinta con `textContent` |
| Filtración de secretos | Nunca se loguea el nsec, la contraseña, el secret, las conversation keys ni los contenidos descifrados. Log = método, id del pedido y pubkey abreviada. `repr()` de la clave muestra solo la npub |
| nsec visible | Se muestra **una sola vez**, al generarla (respuesta de `POST /api/crear`), con una casilla "ya la respaldé". Campos con `autocomplete="off"` y `spellcheck="false"` |
| Mensajes enormes | `max_msg_size` = 128 KiB en el WebSocket |

## 6. Arquitectura de archivos

```
app.py                    servidor aiohttp: rutas, middleware de seguridad, arranque/apagado
firmante.py               lógica NIP-46: despacho de métodos, clientes autorizados, pedido pendiente, historial
relay.py                  cliente WebSocket a un relay: conectar, suscribir, publicar, reconectar
almacen.py                guardar/leer data/clave.json (scrypt + ChaCha20-Poly1305)
nostr/bech32.py           bech32 mínimo (BIP-173) para nsec/npub
nostr/claves.py           generar clave, nsec/npub ↔ bytes, pubkey x-only, X compartida (ECDH sin hash)
nostr/eventos.py          serializar NIP-01, calcular id, firmar y verificar
nostr/nip04.py            AES-256-CBC (lo que usa SN hoy)
nostr/nip44.py            NIP-44 v2 (lo que exige la spec)
static/index.html, app.css, app.js
tests/                    unittest (53): bech32, eventos, nip04, nip44 (vectores oficiales),
                          almacen, firmante y servidor
herramientas/sn_falso.py  cliente que IMITA a NDK (NIP-04, ["",secret], exige "ack", kind 27235, clave nueva por corrida)
```

### API local (JSON; errores con código estable, la página los traduce)

| Ruta | Qué hace |
|---|---|
| `GET /api/eventos?token=…` | **SSE**. Al conectar envía `event: estado` con el estado completo, y luego uno nuevo cada vez que algo cambia (`firmante` llama a `notificar()`, que pone el estado en la cola de cada página conectada). Latido `: ping` cada 15 s. El token va en la URL porque `EventSource` no permite cabeceras. Estado = `{fase: "sin_clave"\|"bloqueado"\|"listo", npub, bunker, relay: {url, estado: "conectado"\|"reconectando", reintento_en}, clientes, pendiente: {id, sitio, metodo_http, challenge_corto, created_at, avisos[], expira_en, evento} \| null, historial: [{ts, tipo, detalle}]}` (máx. 20, sin contenidos) |
| `POST /api/crear` | `{contrasena, nsec?}` → genera o importa; devuelve `{nsec}` **solo** si se generó |
| `POST /api/desbloquear` | `{contrasena}` |
| `POST /api/responder` | `{id, aprobar: true\|false}` |

Errores: `contrasena_incorrecta`, `contrasena_corta`, `nsec_invalido`, `ya_existe_clave`, `token_invalido`, `pedido_expirado`.
"Olvidé mi contraseña" no tiene endpoint: la página explica que hay que borrar `data/clave.json` e importar el nsec.

## 7. Interfaz (UX/UI)

**Identidad visual:** inspirada en el Kit Digital del Gobierno de Chile, **sin escudo, sin logo y sin decir que es un
sitio oficial**. Pie fijo: *"Aplicación independiente de prueba técnica. No es un sitio del Gobierno de Chile.
Estilo visual inspirado en el Kit Digital (kitdigital.gob.cl)."*

| Token | Valor | Fuente |
|---|---|---|
| Azul institucional | `#0f69b4` | Manual de Normas Gráficas 2026, p. 33; framework gob.cl `$brand-color-primary` |
| Rojo de la franja | `#e22c2c` | framework gob.cl `$brand-color-secondary` |
| Azul oscuro (cabecera) | `#001c41` | framework gob.cl `$brand-color-tertiary` |
| Texto / texto secundario | `#212529` / `#4a4a4a` | framework gob.cl |
| Éxito / Info / Error (texto sobre fondo) | `#204349/#d5e3e5` · `#145c68/#d1ecf1` · `#8c3d3d/#ffe0e0` | framework gob.cl `.alert-*` |
| Advertencia | texto `#212529` sobre `#fcf4d4` (el del framework no pasa AA) | cálculo de contraste |
| Tipografía | `"gobCL","Roboto",system-ui,"Segoe UI",Arial,sans-serif` (no se empaqueta; funciona offline) | manual + framework |

La franja superior es **bicolor** azul|rojo 50/50 (6 px) sobre la cabecera azul oscuro. No es tricolor.
Todos los pares de colores pasan WCAG AA. Texto base 18 px, botones de 48 px como mínimo, foco visible de 3 px,
`aria-live` para pedidos nuevos y todo operable con teclado.

**Estados de la página**

- **A · Primera vez:** "Configura tu identidad Nostr". Elegir *Crear una clave nueva* o *Ya tengo una clave (nsec)*,
  más contraseña ×2 (mínimo 8 caracteres). Aviso: "Nunca compartas tu nsec. Quien la tenga puede hacerse pasar por ti."
- **A2 · Respaldo (solo si se generó):** "Esta es la única vez que verás tu nsec. Guárdala en un gestor de contraseñas
  o en papel. No recargues esta página." Botón Copiar y casilla obligatoria "Ya guardé mi nsec".
- **B · Desbloquear:** contraseña. Mientras corre scrypt, el botón muestra "Desbloqueando…". Ayuda: "¿Olvidaste la
  contraseña? No se puede recuperar. Borra `data/clave.json` e importa tu nsec de nuevo."
- **C · Panel listo**
  - Estado del relay: "● Conectado a relay.damus.io" o "⟳ Reconectando… (reintento en 5 s)".
  - Tu npub (se puede compartir) con botón Copiar.
  - **Paso 1:** "Abre Stacker News" (enlace a la página de login de SN, `rel="noopener noreferrer"`).
  - **Paso 2:** "Copia este enlace y pégalo en el campo *Connect with token or NIP-05 address*; luego pulsa
    *Login with token or NIP-05*." Va el `bunker://…` con el botón [Copiar enlace]. El enlace se muestra solo cuando
    el relay está conectado.
  - **Paso 3:** "Vuelve a esta pestaña y aprueba. Si Stacker News muestra un aviso a los pocos segundos, es normal:
    está esperando tu aprobación."
  - Después de cada conexión: "Este enlace es nuevo. El anterior ya se usó. Si vuelves a iniciar sesión, copia este."
- **D · Tarjeta de pedido** (borde azul destacado; el foco va al **título**, nunca al botón Aprobar)
  ```
  Pedido de inicio de sesión en
  STACKER.NEWS                          (host de la tag u, en grande)
  Revisa que sea el sitio donde estás entrando. Si no lo reconoces, rechaza.
  Qué es:   Un "sello" que demuestra que eres dueño de esta clave.
            No publica nada, no gasta dinero y no entrega tu nsec.
  Cliente:  npub1abcd…wxyz · Hora: 18:04:12 · Quedan 1:45
  ▸ Detalles técnicos (kind 27235, challenge, JSON)
  [ Aprobar e iniciar sesión ]   [ Rechazar ]
  ```
- **E · Historial y confirmación:** "✓ Listo. Vuelve a la pestaña de Stacker News: ya deberías haber entrado."
  El historial muestra entradas como "Un cliente se conectó (la app donde pegaste el enlace)", "Le entregaste tu
  clave pública: es normal, no es secreta", "Firmaste el inicio de sesión", "Rechazado", "Expiró sin respuesta" y
  "Bloqueado: no es un inicio de sesión (kind N)". Los `ping` no aparecen.
- **Errores globales**
  - Si la API responde 403: "La app se reinició y esta página quedó desactualizada" con el botón [Recargar].
  - Si falla el `fetch`: "No hay conexión con el programa local. ¿Sigue abierta la ventana de app.py?"
  - Si el relay se cae: "Mientras no haya conexión, Stacker News no puede llegar a tu firmante. Espera 'Conectado'
    y vuelve a intentarlo en Stacker News."

**Detalles:**
- "Copiado ✓" durante 2 s; si el portapapeles falla, "Presiona Ctrl+C".
- El título de la pestaña cambia a "(1) Pedido pendiente".
- Cada evento SSE **no redibuja todo**: la página compara con el estado anterior para no perder el foco ni borrar
  lo escrito. La cuenta regresiva la lleva un reloj local a partir de `expira_en`.
- Si se corta el SSE, `EventSource` reintenta solo. Mientras tanto se muestra "Reconectando con el programa local…".
  Si el servidor responde 403 (token viejo porque `app.py` se reinició), aparece el aviso con [Recargar].
- Recortado por tiempo: sonido, animaciones, cola de varios pedidos, botón Bloquear.

## 8. Orden de implementación y verificación

| Etapa | Qué | Cómo se verifica |
|---|---|---|
| a | `bech32`, `claves`, `eventos` | unittest: ejemplos de NIP-19, ida y vuelta, firma + verificación, id recalculado |
| b | `nip04`, `nip44`, `almacen` | unittest: **todos** los vectores oficiales de NIP-44 (sha256 `269ed0f6…5040`), ida y vuelta de NIP-04, contraseña mala → error, archivo alterado → error |
| c | `relay`, `firmante` (`connect`, `get_public_key`, `ping`) | `herramientas/sn_falso.py` contra relay.damus.io |
| d | `app.py` + `static/` + `sign_event` con aprobación | `sn_falso` + aprobar / rechazar / dejar expirar; pedir kind 1 y kind 9734 → bloqueados sin llegar a la página; un 27235 para otro sitio → llega con ese sitio en grande; `curl` con `Host: evil.com` o sin token → 403 |
| e | Login real | Stacker News de punta a punta; se graba el GIF |

Etapa e (2026-11-04): login real en stacker.news OK con una clave de prueba. La NDK de producción aceptó `"ack"` y siguió el orden `connect` → `get_public_key` → `sign_event` 27235.
