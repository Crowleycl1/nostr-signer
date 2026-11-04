# Mesa de diseño — 1. Protocolo Nostr (NIP-46 / NIP-44 / Stacker News)

Fuentes descargadas el 2026-11-04: `nips@master` (46.md, 44.md, 04.md, 01.md), `stackernews/stacker.news@27938a6` (2026-11-03), tarball `@nostr-dev-kit/ndk-2.12.2` (es la versión exacta del `package-lock.json` de SN, línea 6003).

## 1. Hechos verificados (con fuente)

**NIP-46**
- Token: `bunker://<remote-signer-pubkey-hex>?relay=<wss://...>&relay=...&secret=<opcional>` (46.md:45). El secret es de un solo uso: "SHOULD ignore new attempts ... with old secret" (46.md:48).
- Request y response son eventos `kind 24133`: el request lleva `tags [["p", remote-signer-pubkey]]` y el response lleva `[["p", client-pubkey]]` (46.md:69-78 y 137-148). El contenido es JSON `{id, method, params:[strings]}` / `{id, result, error?}` (46.md:82-88 y 152-158).
- `connect` recibe `[<remote-signer-pubkey>, <secret?>, <perms?>, <metadata?>]` y devuelve `"ack"` **o** el secret. `sign_event` recibe `[json(evento sin firmar)]` y devuelve `json_stringified(evento firmado)`. `ping` devuelve `"pong"` y `get_public_key` devuelve la pubkey hex (46.md:100-103).
- Los errores van en el campo `error` del response: su presencia indica el error. Un método desconocido "MUST be replied with an error" (46.md:162-164).
- La spec exige NIP-44 (46.md:80 y 150).
- La spec permite que la remote-signer-pubkey sea igual a la user-pubkey (46.md:23 y el ejemplo de 46.md:168-169).

**Stacker News (cliente)**
- `components/nostr-auth.js:122-163`: `createAuth()` → k1; `NDKNip46Signer(token)`; `blockUntilReady()`; luego firma este evento: `kind 27235`, `content "Stacker News Authentication"`, `tags [["challenge",k1],["u",NEXT_PUBLIC_URL],["method","GET"]]`, y `signIn('nostr', {event})`.
- `lib/nostr.js:197-201`: un parche cambia `bunker://` por `http://` antes de parsear la URL. `lib/nostr.js:42`: `clientName:'stacker.news'`, pero 27235 es efímero, así que NDK no agrega la tag `client` (ndk `src/events/index.ts:547-563`).
- Servidor `pages/api/auth/[...nextauth].js` (líneas 241-270 del archivo): recalcula `sha256(JSON.stringify([0,pubkey,created_at,kind,tags,content]))`, verifica Schnorr y **exige que `tags[0]` sea `["challenge", k1]`** (exactamente 2 elementos). Después borra el k1 (anti-replay, línea 207).
- No hay timeout: NDK espera sin límite y SN solo muestra una sugerencia a los 10 s (`nostr-auth.js:101-106` y 138).
- SN no agrega relays propios para NIP-46: usa solo los `relay=` del token (ndk `signers/nip46/rpc.ts:46-63`).

**NDK 2.12.2, lo que importa** (`src/signers/nip46/index.ts` y `rpc.ts`)
- **Cifrado por defecto: NIP-04.** `encryptionType = "nip04"` (rpc.ts:37). Todos los requests se cifran con ese valor (rpc.ts:206). Cambia a nip44 solo cuando llega un response sin `?iv=` (rpc.ts:109-112). Si falla el descifrado, prueba con el otro esquema (rpc.ts:119-129). **Conclusión: el primer `connect` llega cifrado con NIP-04.**
- Parámetros de connect: `[userPubkey ?? "", secret?]` (index.ts:172-174). `userPubkey` sale del parámetro `pubkey=` del token (index.ts:101). Como nuestro token no lo lleva, **`params[0]` llega como `""`**, no como nuestra pubkey.
- **Exige `result === "ack"`.** Si se devuelve el secret, el login se rechaza (index.ts:184-191).
- Después del ack llama a `get_public_key` y usa `response.result` sin revisar `error` (index.ts:198-213).
- `sign()` manda `[JSON.stringify(rawEvent)]`, que incluye `pubkey` e `id` ya calculados por NDK, y **solo usa `json.sig` del response** (index.ts:256-273 y events/index.ts:429-441). NDK conserva su propio id, created_at y pubkey.
- Suscripción del cliente: `{kinds:[24133], "#p":[client-pubkey]}`, sin `since` (index.ts:132-135). El id del request es `Math.random().toString(36).substring(7)` (rpc.ts:182).
- Los relays del token reciben una `authPolicy` NIP-42 signIn (rpc.ts:60).

**NIP-44 v2** (44.md:68-99 y 233-282)
1. `shared_x` = coordenada X de `a·B`, **sin hashear** (44.md:71-72 y 160). `conversation_key = HKDF-extract(sha256, IKM=shared_x, salt=b"nip44-v2")`.
2. `nonce` = 32 bytes aleatorios. `HKDF-expand(PRK=conversation_key, info=nonce, L=76)` → `chacha_key[0:32]`, `chacha_nonce[32:44]` y `hmac_key[44:76]`.
3. Padding: prefijo u16 BE con el largo, luego el texto y luego ceros hasta `calc_padded_len` (mínimo 32; potencias de 2, en chunks de 32 o de next_pow/8). Desde 65536 bytes el prefijo es de 6 bytes, pero no nos aplica.
4. ChaCha20 (RFC 8439) con contador 0. `mac = HMAC-SHA256(hmac_key, nonce || ciphertext)`.
5. `base64(0x02 || nonce || ciphertext || mac)` con padding. Al descifrar: si empieza con `#` → versión no soportada; se exigen al menos 132 caracteres y 99 bytes; la MAC se compara en tiempo constante.
- Vectores: `https://raw.githubusercontent.com/paulmillr/nip44/main/nip44.vectors.json`. El sha256 que da la spec (44.md:303) es `269ed0f69e4c192512cc779e78c555090cebc7c785b609e338a62afc3ce25040`, y **coincide con el archivo descargado hoy**.

**NIP-04** (04.md:13 y 19-45): AES-256-CBC (PKCS7). La clave es `shared_x` sin hashear y el IV es de 16 bytes aleatorios. Formato: `base64(ct) + "?iv=" + base64(iv)`. La spec la marca como deprecada, pero NDK 2.12.2 la usa.

**NIP-01** (01.md:19-55): `id = sha256(utf8(json([0,pubkey,created_at,kind,tags,content])))` sin espacios. En `content` se escapan solo `\n \" \\ \r \t \b \f`. `sig` es Schnorr BIP-340 sobre los 32 bytes del id. Los kinds 20000-29999 son efímeros y el relay no los guarda (01.md:98).

**Relays** (prueba propia, script en `scratchpad/scripts/roundtrip.py`): REQ `#p` propio + EVENT 24133 firmado → eco recibido.
- `wss://relay.damus.io`: OK, 0,38 s. `wss://relay.primal.net`: OK, 0,35 s. `wss://nos.lol`: OK, 1,09 s.
- `wss://relay.nsec.app`: el DNS resuelve (65.109.67.137), pero **la conexión TCP/443 hace timeout** (también con curl). Puede ser la red local o una caída: no lo pude confirmar.

## 2. Flujo exacto SN ↔ bunker (contenido descifrado)

Sea `B` la pubkey del bunker (= usuario) y `C` la pubkey efímera de SN. Todos los eventos son `{"kind":24133,"pubkey":<emisor>,"tags":[["p",<receptor>]],"content":<cifrado>,...}`.

0. El bunker se suscribe: `["REQ","sub",{"kinds":[24133],"#p":["B"],"since":<ahora-10>}]`.
1. SN → bunker (**NIP-04**): `{"id":"k3j9x","method":"connect","params":["","<secret>"]}`
   Bunker → SN: `{"id":"k3j9x","result":"ack"}`
2. SN → bunker: `{"id":"a8f2q","method":"get_public_key","params":[]}` → `{"id":"a8f2q","result":"B"}`
3. SN → bunker:
   `{"id":"z1m0p","method":"sign_event","params":["{\"created_at\":1793750400,\"content\":\"Stacker News Authentication\",\"tags\":[[\"challenge\",\"<k1>\"],[\"u\",\"https://stacker.news\"],[\"method\",\"GET\"]],\"kind\":27235,\"pubkey\":\"B\",\"id\":\"<hex>\"}"]}`
   Si el usuario aprueba: `{"id":"z1m0p","result":"{\"id\":\"<hex>\",\"pubkey\":\"B\",\"created_at\":1793750400,\"kind\":27235,\"tags\":[...],\"content\":\"Stacker News Authentication\",\"sig\":\"<128 hex>\"}"}`
   Si rechaza: `{"id":"z1m0p","result":"","error":"usuario rechazó la firma"}`
4. `ping` (SN no lo usa en el login): `{"id":"..","method":"ping","params":[]}` → `{"id":"..","result":"pong"}`.
5. Método desconocido: `{"id":"..","result":"","error":"método no soportado: <m>"}`.

## 3. Supuestos sin verificar
- Que `NEXT_PUBLIC_URL` en producción sea `https://stacker.news`. El `.env.development` dice `http://localhost:3000`. No afecta: firmamos lo que llegue.
- Que el JS desplegado en stacker.news use la misma NDK 2.12.2 que el repo, y que SN no tenga un timeout en otra capa (por ejemplo en el k1). No encontré expiración del k1 en `pubkeyAuth`.
- El estado real de `relay.nsec.app`.
- Si damus, nos.lol o primal exigen NIP-42 a los eventos 24133 en el futuro. Hoy no lo exigen.

## 4. Recomendaciones mínimas
1. **Implementar el descifrado NIP-04 y el NIP-44 y responder con el mismo esquema del request** (`'?iv=' in content` → NIP-04). Sin NIP-04, el login con SN **no funciona**. NIP-04 son unas 10 líneas con `cryptography` (AES-CBC + PKCS7).
2. Responder `connect` siempre con `"ack"`. Ignorar `params[0]`, que puede venir vacío. Si el token lleva secret, validar `params[1]`, y al acertar registrar `C` como cliente autorizado y rotar el secret. Rechazar `sign_event` y `get_public_key` de un `C` no autorizado.
3. En `sign_event`: tomar del parámetro **solo** `kind, created_at, tags, content` sin modificarlos (ni reordenar tags). Poner `pubkey=B`, recalcular el id con `json.dumps([0,...], separators=(',',':'), ensure_ascii=False)` y firmar con `sign_schnorr`. Opcional: si el `id` que trae el request difiere del nuestro, devolver error, porque significa que el sig no le serviría a NDK.
4. Usar un solo relay: **`wss://relay.damus.io`** (verificado hoy). Dejarlo configurable y anotar `nos.lol` como alternativa. Mantener abierta la conexión WS, reconectar con backoff y re-enviar el REQ. Deduplicar por `event.id`.
5. Verificar id y firma de cada evento entrante antes de descifrarlo. Validar también `kind==24133`, que el `p` sea `B` y que no esté duplicado.
6. Tests: los vectores oficiales de NIP-44 (`get_conversation_key`, `encrypt_decrypt`, `calc_padded_len`) más un round-trip de NIP-04.

## 5. Riesgos y trampas
- **NIP-04 por defecto en NDK 2.12.2**, aunque la spec diga NIP-44. Es la trampa principal.
- **Devolver el secret en `connect`** (lo permite la spec) rompe el login con NDK: este exige `"ack"`.
- `coincurve.ecdh()` hashea. Usar `PublicKey(b'\x02'+B).multiply(sk).format()[1:33]`. Aplica a NIP-04 y a NIP-44.
- `cryptography`: el `ChaCha20` recibe un nonce de **16 bytes** = contador LE de 4 bytes + nonce de 12. Pasar `b'\x00'*4 + chacha_nonce`.
- Las pubkeys de Nostr son x-only (32 bytes). Para ECDH hay que anteponer `0x02`.
- Los eventos 24133 son efímeros: si el bunker no está suscrito cuando SN manda `connect`, el mensaje se pierde. Hay que arrancar el WS antes de mostrar el token. Si el `since` es demasiado estricto y hay desfase de reloj, se pierden eventos: usar un margen.
- Si el secret es de un solo uso y SN reintenta tras un fallo, `connect` falla. Hay que mostrar un token nuevo en la UI (SN ya sugiere "fresh token").
- La serialización del id debe ser idéntica a `JSON.stringify`. Con `ensure_ascii=False` y separadores compactos, Python coincide para todo texto normal; los surrogates sueltos son un caso borde despreciable.
- No loguear el `content` descifrado de `sign_event` junto con la clave, y nunca loguear el nsec.
