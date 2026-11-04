"""Guarda la clave secreta CIFRADA en data/clave.json (nunca en texto plano).

Cómo se protege (DISENO.md §3):
- scrypt convierte la contraseña en una llave de 32 B. Es lento a propósito (~0,3 s y 128 MiB),
  así que probar millones de contraseñas contra un archivo robado sale muy caro.
- ChaCha20-Poly1305 cifra la clave y le agrega una etiqueta: si alguien cambia un byte del
  archivo (o la contraseña es otra), descifrar falla.
- AAD = versión + pubkey: esos datos van en claro, pero quedan "amarrados" a la etiqueta;
  si alguien los cambia, también falla.
- Los parámetros de scrypt se leen del archivo, para poder subirlos en el futuro sin romper
  archivos viejos.
- Escritura atómica: se escribe un .tmp y se reemplaza de una vez; si el programa se corta a
  mitad, nunca queda un clave.json a medias.
"""

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from nostr.claves import ClaveNostr

# CLAVE_JSON solo se usa en pruebas, para no tocar la clave real del usuario.
RUTA = Path(os.environ.get("CLAVE_JSON") or Path(__file__).resolve().parent / "data" / "clave.json")
VERSION = 1
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
# Topes al leer: un archivo manipulado no debe poder pedir gigas de memoria.
_N_MAX, _R_MAX, _P_MAX = 2**20, 16, 4


class ContrasenaIncorrecta(ValueError):
    """La contraseña no corresponde o el archivo fue alterado (no se pueden distinguir)."""


def existe(ruta: Path | None = None) -> bool:
    return (ruta or RUTA).exists()


def _aad(pubkey_hex: str) -> bytes:
    return f"nostr-signer:{VERSION}:{pubkey_hex}".encode()


def _derivar(contrasena: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    # maxmem explícito: scrypt usa 128·n·r bytes (128 MiB con los valores por defecto).
    return hashlib.scrypt(contrasena.encode("utf-8"), salt=sal, n=n, r=r, p=p,
                          maxmem=128 * n * r * p + 2**20, dklen=32)


def guardar(clave: ClaveNostr, contrasena: str, ruta: Path | None = None, n: int = SCRYPT_N) -> None:
    """`n` solo se baja en las pruebas, para que corran rápido."""
    ruta = ruta or RUTA
    sal, nonce = os.urandom(16), os.urandom(12)
    llave = _derivar(contrasena, sal, n, SCRYPT_R, SCRYPT_P)
    cifrado = ChaCha20Poly1305(llave).encrypt(nonce, clave.secreto_bytes(), _aad(clave.publica_hex))
    b64 = lambda b: base64.b64encode(b).decode()
    contenido = {
        "version": VERSION,
        "pubkey": clave.publica_hex,
        "kdf": {"nombre": "scrypt", "n": n, "r": SCRYPT_R, "p": SCRYPT_P, "sal": b64(sal)},
        "cifrado": {"nombre": "chacha20-poly1305", "nonce": b64(nonce), "texto": b64(cifrado)},
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(contenido, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


def leer(contrasena: str, ruta: Path | None = None) -> ClaveNostr:
    """Devuelve la clave. Lanza ContrasenaIncorrecta o ValueError (archivo con formato inválido)."""
    ruta = ruta or RUTA
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if datos["version"] != VERSION or datos["kdf"]["nombre"] != "scrypt":
            raise ValueError("versión de archivo no soportada")
        kdf, cif = datos["kdf"], datos["cifrado"]
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
        if not (2 <= n <= _N_MAX and n & (n - 1) == 0 and 1 <= r <= _R_MAX and 1 <= p <= _P_MAX):
            raise ValueError("parámetros de scrypt fuera de rango")
        sal = base64.b64decode(kdf["sal"], validate=True)
        nonce = base64.b64decode(cif["nonce"], validate=True)
        cifrado = base64.b64decode(cif["texto"], validate=True)
        pubkey_hex = str(datos["pubkey"])
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, ContrasenaIncorrecta):
            raise
        raise ValueError("data/clave.json tiene un formato inválido") from None

    llave = _derivar(contrasena, sal, n, r, p)
    try:
        secreto = ChaCha20Poly1305(llave).decrypt(nonce, cifrado, _aad(pubkey_hex))
    except (InvalidTag, ValueError):
        raise ContrasenaIncorrecta("contraseña incorrecta o archivo alterado") from None
    clave = ClaveNostr(secreto)
    if clave.publica_hex != pubkey_hex:  # defensa extra; con el AAD no debería pasar
        raise ContrasenaIncorrecta("contraseña incorrecta o archivo alterado")
    return clave
