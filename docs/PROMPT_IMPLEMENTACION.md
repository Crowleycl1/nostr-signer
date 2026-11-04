# Prompt de implementación (etapas b → e)

> Prompt para que un agente de IA (Claude Code u otro) termine el proyecto a partir del diseño aprobado.
> Se guarda en el repo como parte del registro de prompting de la prueba técnica.

---

Eres el desarrollador del proyecto `nostr-signer` (C:\Proyecto\nostr-signer): un firmante remoto Nostr
NIP-46 ("bunker") en Python para iniciar sesión en Stacker News. El diseño ya está aprobado; tu trabajo es
implementarlo y verificarlo, no rediseñarlo.

## Lee primero (en este orden)
1. `CLAUDE.md`: alcance, librerías y reglas.
2. `docs/DISENO.md`: **fuente de verdad**. Contiene los hechos verificados (H1–H13), las decisiones, el protocolo
   exacto, la seguridad, la arquitectura, la API, la UI y el orden de verificación.
3. `docs/FLUJO.md`: diagramas del flujo completo.
4. `docs/ai-logs/mesa-diseno/`: solo si necesitas el detalle o la fuente de alguna decisión (rutas y líneas de SN y NDK).

## Estado actual
- **Etapa a: lista.** `nostr/bech32.py`, `nostr/claves.py`, `nostr/eventos.py` y `tests/test_claves_eventos.py`
  (12 pruebas que pasan). No los reescribas: úsalos.
- Entorno: `.venv` con Python 3.12, `aiohttp`, `coincurve` y `cryptography`. Pruebas con **unittest**
  (`.venv\Scripts\python -m unittest -v`). **No agregues dependencias.**

## Reglas (no negociables)
- Todo en español: código, comentarios, mensajes de la UI y README. Simple antes que genérico; comenta el *por qué*.
- **Nunca** loguees, imprimas ni devuelvas el nsec, la contraseña, el secret del bunker, las conversation keys ni
  los contenidos descifrados. Usa siempre claves de prueba generadas; **nunca pidas al usuario su nsec real**
  (este chat se publica).
- **No hagas commits ni push.** Git lo maneja el usuario (ver la regla global en `~/.claude/CLAUDE.md`).
- Los experimentos van al scratchpad, no al repo. `data/` nunca se versiona.
- Si algo del diseño resulta incorrecto al implementarlo, **detente, explícalo y propone el cambio** antes de
  desviarte. Si cambias una decisión, actualiza `docs/DISENO.md`.
- Al terminar cada etapa: corre **todas** las pruebas, reporta el resultado real (salida incluida si falla) y
  explica en 3–5 líneas sencillas qué se hizo. El usuario está aprendiendo Nostr.

## Etapa b: cifrado y almacén
- `nostr/nip04.py`: AES-256-CBC + PKCS7. La clave es `x_compartida` sin hashear y el formato es `b64(ct)?iv=b64(iv)`.
  Valida largos al descifrar; ante cualquier error lanza un `ValueError` genérico.
- `nostr/nip44.py`: NIP-44 v2 completo (conversation_key, padding, ChaCha20 con nonce de 16 B =
  `b"\0"*4 + chacha_nonce`, HMAC verificado en tiempo constante **antes** de descifrar, validaciones de largo y versión).
- `almacen.py`: `data/clave.json` con scrypt (n=2¹⁷, r=8, p=1) + ChaCha20-Poly1305, AAD = versión + pubkey,
  escritura atómica (`.tmp` + `os.replace`) y parámetros leídos desde el archivo.
- Pruebas:
  - Descarga una vez `https://raw.githubusercontent.com/paulmillr/nip44/main/nip44.vectors.json` a
    `tests/vectores/` y **verifica su sha256** = `269ed0f69e4c192512cc779e78c555090cebc7c785b609e338a62afc3ce25040`.
  - Recorre **todos** los casos válidos (`get_conversation_key`, `encrypt_decrypt`, `calc_padded_len`) y los inválidos.
  - NIP-04: ida y vuelta, unicode y un tercero que no descifra.
  - Almacén: guardar y leer, contraseña mala → error, archivo alterado → error.

## Etapa c: relay + firmante (sin UI)
- `relay.py`: un relay (`NOSTR_RELAY`, por defecto `wss://relay.damus.io`), REQ
  `{"kinds":[24133],"#p":[B],"since":ahora-30}`, `max_msg_size` de 128 KiB, reconexión 1/2/5/10 s con re-REQ,
  y estado observable (conectado / reconectando).
- `firmante.py`: reglas 1–8 de la sección 4 de DISENO.md, en especial:
  - verificar el evento **antes** de descifrar;
  - `"?iv="` → responder con NIP-04, si no → con NIP-44;
  - `connect` responde `"ack"`, ignora `params[0]`, usa `compare_digest` y rota el secret;
  - conjunto de clientes autorizados;
  - una tarea por pedido;
  - filtro de login: kind 27235 con tags `u` y `method`, todo lo demás se bloquea;
  - un pendiente a la vez, que expira a los 120 s (configurable para las pruebas);
  - historial sin contenidos;
  - `notificar()` para el SSE.
- `herramientas/sn_falso.py`: **imita a NDK 2.12.2**, no a la spec. Clave de cliente nueva en cada corrida,
  `connect` en NIP-04 con `["", secret]`, exige `"ack"`, luego `get_public_key` y luego `sign_event` 27235 con
  `challenge`/`u`/`method`, y verifica la firma con su propio id. Opciones para probar kind 1, kind 9734 y un
  secret malo.
- Verificación contra el relay real: `connect` y `get_public_key` responden bien; secret malo → error; kind 1 y
  9734 → bloqueados.

## Etapa d: servidor web + UI con aprobación
- `app.py`: aiohttp en `127.0.0.1` (puerto `PUERTO`, por defecto 8000) y un solo event loop. Middleware:
  - Host en lista blanca → 403;
  - POST con `X-Token` + `Origin`;
  - cabeceras CSP, `nosniff` y `no-store`.

  El token se inyecta en `<meta name="token">`. Rutas: `GET /api/eventos` (SSE, token en la query, latido de 15 s)
  y `POST /api/crear`, `/api/desbloquear`, `/api/responder`, con códigos de error estables. scrypt corre en
  `asyncio.to_thread`. El bunker se muestra **solo después** de la suscripción al relay. Al arrancar se imprime
  "Abre http://localhost:8000".
- `static/index.html`, `app.css`, `app.js`: estados A, A2, B, C, D y E y los textos exactos de la sección 7 de
  DISENO.md. Colores y franja del Kit Digital, sin escudo ni logo, con el pie de "app independiente". Texto base
  de 18 px y AA. Sin JS ni `style` inline, solo `textContent`. SSE sin redibujar todo. Foco en el título de la
  tarjeta, nunca en Aprobar. "(1) Pedido pendiente" en el título de la pestaña. Cuenta regresiva local.
  "Copiado ✓" con alternativa Ctrl+C.
- Verificación: `sn_falso` + aprobar, rechazar y dejar expirar (con timeout corto). `curl` con `Host: evil.com`,
  sin token o con Origin ajeno → 403. Revisa que en los logs de consola no aparezcan secretos (búscalos con grep).

## Etapa e: prueba real (con el usuario)
- **Detente y pide al usuario** que haga el login real en
  https://stacker.news/signup?callbackUrl=https%3A%2F%2Fstacker.news%2F&type=nostr con una **clave de prueba**,
  guiándolo paso a paso. Si falla, diagnostica con logs (sin secretos) y corrige.
- Anota el resultado en el README: fecha, relay y si la NDK de producción se comportó como la 2.12.2.

## Cierre
- `README.md` breve en español:
  - qué es (2 líneas);
  - requisitos;
  - instalación (`python -m venv .venv`, `pip install -r requirements.txt`);
  - cómo correrlo y cómo correr las pruebas;
  - cómo usarlo con Stacker News (3 pasos);
  - **supuestos**;
  - **tradeoffs** (tabla de DISENO.md §3);
  - **la ambigüedad NIP-04 vs NIP-44** (H1) y cómo se resolvió;
  - **qué quedó fuera**;
  - enlaces a `docs/DISENO.md`, `docs/FLUJO.md` y `docs/ai-logs/`.
- Actualiza `CLAUDE.md` con el comando de pruebas.
- Prepara la exportación de los chats a `docs/ai-logs/` (Markdown legible) y busca `nsec1` en todo lo que se vaya a
  publicar. Única excepción: el ejemplo público de NIP-19 `nsec1vl029…` que usan las pruebas.
- Recuerda al usuario: grabar el GIF con la clave de prueba (la pantalla A2 muestra el nsec) y, al terminar,
  **quitar su cuenta de git del equipo** (regla global).
- Informe final: qué funciona (con evidencia), qué no se pudo verificar y qué decisiones cambiaron.
