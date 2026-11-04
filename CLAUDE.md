# nostr-signer — prueba técnica (Hacienda / Gob Digital)

Firmante remoto Nostr (NIP-46, "bunker") mínimo, para iniciar sesión en Stacker News.

## Alcance
- Backend: Python 3.12 + aiohttp (servidor web local + cliente WebSocket al relay, un solo event loop).
- Frontend: HTML/CSS/JS plano en `static/`, sin frameworks.
- Cripto: `coincurve` (secp256k1, Schnorr BIP-340, ECDH) y `cryptography` (ChaCha20, HKDF, HMAC) para NIP-44.
- El usuario genera o pega su `nsec`; la app muestra el `bunker://` para pegar en Stacker News
  y le pide aprobar cada `sign_event`.

## Reglas
- Idioma: español (código, comentarios, README).
- La clave secreta nunca se loguea ni se commitea (`data/` está en `.gitignore`).
- Implementar solo lo que necesita el login de Stacker News: `connect`, `get_public_key`, `sign_event`, `ping`.
- Supuestos y tradeoffs se anotan en el README a medida que se deciden.

## Ojo
- `coincurve.PrivateKey.ecdh()` devuelve sha256 del punto; NIP-44 necesita la coordenada X SIN hashear.

## Referencias
- NIP-46: https://github.com/nostr-protocol/nips/blob/master/46.md
- NIP-44: https://github.com/nostr-protocol/nips/blob/master/44.md
- Login SN: https://stacker.news/signup?callbackUrl=https%3A%2F%2Fstacker.news%2F&type=nostr

## Correr
    .venv\Scripts\python app.py

## Pruebas
    .venv\Scripts\python -m unittest -v
    .venv\Scripts\python herramientas\sn_falso.py "bunker://..."   (cliente que imita a Stacker News)
