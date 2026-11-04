# Revisión cruzada — experto en protocolo (sobre 2_seguridad.md y 3_ux.md)

Las referencias de fuente son las de `1_protocolo.md`: SN es `stacker.news@27938a6` y NDK es la 2.12.2 (`src/`). Agregué las NIP-98 y NIP-42 (master).

## Hallazgos

1. **[Bloqueante] NIP-04 no es "ojalá evitable"** (seg §2, líneas 77-78). NDK 2.12.2 cifra el primer `connect` con NIP-04 (`signers/nip46/rpc.ts:37` y `206`). Sin NIP-04 el login no parte.
   **Cambio:** agregar `nostr/nip04.py` (AES-256-CBC + PKCS7, clave = `shared_x` sin hashear, formato `b64(ct)?iv=b64(iv)`) y su test de ida y vuelta. El despacho detecta `'?iv=' in content` y responde con el mismo esquema. El helper `x_compartida` de seguridad §2 sirve igual para los dos esquemas.

2. **[Importante] El secret de un solo uso y el "único cliente autorizado" rompen el reintento y el segundo login** (seg §3, línea 89). SN crea un `Nostr()` nuevo en cada intento (`components/nostr-auth.js:122`). NDK genera una clave de cliente nueva cada vez (`signers/nip46/index.ts:89-90`) y reenvía el mismo secret del token (`index.ts:174`). Casos que fallan:
   - (a) El usuario rechaza la firma o expira y vuelve a pulsar "Login": cliente nuevo + secret ya usado → error.
   - (b) Logout y login de nuevo.
   - (c) "Add account".

   Hoy todos exigen apretar "nuevo bunker" y volver a copiar el token.
   **Cambio:**
   - Al aceptar un `connect`, **rotar el secret automáticamente**, que es lo que dice la spec (46.md:48). La UI muestra el `bunker://` nuevo enseguida (el polling ya lo trae) con el aviso "Si necesitas reintentar en Stacker News, copia el enlace de nuevo".
   - Cambiar "cliente único" por un **conjunto de clientes autorizados** (pubkeys que presentaron un secret válido), en memoria.
   - Un `connect` repetido del mismo cliente ya autorizado responde `"ack"` sin volver a pedir el secret; esto es idempotente ante reenvíos.
   - Dejarlo anotado en el README. Alternativa aún más simple, si el tiempo aprieta: secret fijo por sesión. La protección real es la aprobación manual de cada firma; anotarlo como tradeoff.

3. **[Importante] La respuesta a `connect` debe ser exactamente `"ack"`, y `params[0]` llega `""`.** Ninguno de los dos documentos lo dice. Si se devuelve el secret (lo permite la spec), NDK rechaza el login (`index.ts:184-191`). Si se valida `params[0] == nuestra pubkey`, se rechaza a SN (`index.ts:172`).
   **Cambio:** que seguridad §3 y `firmante.py` lo dejen explícito: `connect` valida solo `params[1]`.

4. **[Importante] El timeout de 120 s es compatible.** NDK no tiene timeout (espera sin límite). El servidor de SN no valida la antigüedad de `created_at` (`nostrEventAuth` en `pages/api/auth/[...nextauth].js`). NIP-98 solo sugiere una ventana de 60 s (98.md:42), pero SN no la aplica, y el `created_at` lo fija SN al pedir la firma. Al expirar, responder `error` es correcto: NDK rechaza la promesa (`index.ts:266-270`) y SN muestra el error en vez de quedarse colgado.
   **Cambio:** mantener los 120 s. Mostrar una cuenta regresiva en la tarjeta. Si el usuario aprueba después de expirar, no se envía nada.

5. **[Importante] El despacho no debe bloquear al lector del relay.** `asyncio.wait_for(fut, 120)` (seg §4) dentro del bucle que lee el WebSocket congelaría `get_public_key`, `ping` y los demás pedidos durante 120 s.
   **Cambio:** cada request se atiende en su propia `asyncio.create_task(...)` y el bucle lector solo encola o despacha.

6. **[Importante] Firmar sin tocar los campos y validar el id.** NDK solo usa `sig` y conserva su propio `id`, `pubkey` y `created_at` (`index.ts:256-273`). SN exige además `tags[0] == ["challenge", k1]`.
   **Cambio:** en `eventos.py`:
   - tomar `kind, created_at, tags, content` tal cual, sin reordenar ni normalizar;
   - poner `pubkey = la nuestra` y recalcular el id;
   - si el request trae un `pubkey` distinto del nuestro, o un `id` distinto del recalculado, responder `error`, porque esa firma no le serviría a NDK.

   Esto completa seg §2 ("nunca confía en un id enviado").

7. **[Importante] Corregir la tabla de kinds** (UX §3D, línea 146). **22242 es la autenticación ante relays (NIP-42, 42.md:41)** y **no es el login de SN**. Tabla propuesta:
   - **27235** → "Inicio de sesión en Stacker News" (NIP-98 HTTP Auth; `nostr-auth.js:148-156`)
   - 22242 → "Autenticación ante un relay"
   - 1 → "Nota pública"
   - 0 → "Perfil"
   - otro → "Tipo N (desconocido)", con advertencia

   **Tarjeta para el kind 27235:**
   - Sitio: host de la tag `u`. Si no es `stacker.news`, mostrar la advertencia "El sitio no es stacker.news".
   - Método: tag `method` (GET).
   - Código de desafío: `challenge`, abreviado (8 caracteres…4 caracteres).
   - Contenido: "Stacker News Authentication".
   - Hora: `created_at`.
   - Propósito: "Demostrar que eres dueño de esta npub para entrar a Stacker News. No publica nada."

8. **[Importante] El bunker no sabe que el cliente es Stacker News.** NDK 2.12.2 no manda metadata en `connect` (`index.ts:172-174`). Por eso los títulos "Stacker News quiere firmar esto" y "Stacker News se conectó" (UX §3D y §3E) afirman algo que no podemos saber. Quien tenga el token podría hacerse pasar por SN.
   **Cambio:**
   - título "Solicitud de firma";
   - una línea "Cliente: npub1abcd…wxyz (conectado 18:04)";
   - deducir el sitio solo de la tag `u`;
   - en el historial, "Un cliente se conectó".

9. **[Importante] El "SN falso" debe imitar a NDK, no a la spec** (seg §5c).
   **Cambio:** que `herramientas/sn_falso.py`:
   - mande `connect` **en NIP-04** con `params ["", secret]`;
   - exija `result == "ack"`;
   - después pida `get_public_key`;
   - después pida `sign_event` de un **kind 27235** con tags `challenge`, `u` y `method`;
   - verifique la firma con el id calculado por él mismo;
   - use una clave de cliente **nueva en cada corrida**, para cubrir el hallazgo 2.

   Agregar un caso que responda en NIP-44 y siga en NIP-44, para la conmutación de `rpc.ts:109-112`.

10. **[Menor] Eventos efímeros y `since`.** El `since=ahora-10s` y el anti-replay de 5 min (seg §3) son coherentes: los 24133 no se guardan (01.md:98). **Cambio:** abrir el WS y enviar el REQ **antes** de mostrar el `bunker://` en la UI, y mostrar el token solo cuando el relay esté "conectado". Si el relay está caído, el `connect` se pierde y SN queda esperando sin timeout.

11. **[Menor] Relay.** En la UI usar `wss://relay.damus.io` (round-trip de 24133 verificado). `relay.nsec.app` no respondía. Dejarlo configurable con una variable de entorno. El token lleva un solo `relay=`.

12. **[Menor] Textos de SN** (UX §3C, paso 2). El campo real dice "Connect with token or NIP-05 address" y el botón "Login with token or NIP-05" (`nostr-auth.js:223` y `231`). **Cambio:** "pégalo en el campo 'Connect with token or NIP-05 address' y pulsa 'Login with token or NIP-05'".

13. **[Menor] Lo que sobra para ~3 h.** Recortar o dejar como opcional:
   - el beep de WebAudio;
   - la animación `@keyframes`;
   - el contador "Pedido 1 de N" (SN pide una firma a la vez; basta mostrar el más antiguo);
   - el límite de 5 pendientes (con 1–2 basta);
   - la variante `role=log` del historial (una lista simple sirve);
   - el AAD con versión, que se puede mantener, pero sin más pruebas que la ya hecha.

   Prioridad de tests: vectores NIP-44, round-trip NIP-04, id/firma NIP-01, `sn_falso`.

14. **[Menor] Lo que falta.**
   - El método desconocido responde `{"id":..,"result":"","error":"método no soportado"}`.
   - Deduplicar los eventos entrantes por `event.id`.
   - Verificar la firma de cada evento entrante (ya está en seg §3).
   - Ignorar los mensajes `AUTH` del relay: damus no lo exige hoy.
   - En el log, a lo más `method` e `id`, nunca `params` de `sign_event` (seg §3 ya lo dice).
