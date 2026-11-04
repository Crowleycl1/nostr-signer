"""Cifrado NIP-44 versión 2 (el que exige la spec NIP-46).

Pasos en simple:
1. conversation_key = HKDF-extract(sal="nip44-v2", X compartida). Es la misma para ambos lados.
2. Por cada mensaje se elige un nonce al azar (32 B) y de ahí se derivan 3 llaves:
   chacha_key (32), chacha_nonce (12) y hmac_key (32)  ← HKDF-expand(conversation_key, nonce, 76).
3. El texto se "rellena" a un largo estándar (oculta el largo real) y se cifra con ChaCha20.
4. Se agrega un HMAC-SHA256 sobre nonce + cifrado: si alguien altera un bit, el HMAC no cuadra.
5. payload = base64( 0x02 | nonce | cifrado | mac ).

Referencia: https://github.com/nostr-protocol/nips/blob/master/44.md
Vectores oficiales: tests/vectores/nip44.vectors.json (se prueban todos).
"""

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

from nostr.claves import ClaveNostr

VERSION = 2
MIN_TEXTO, MAX_TEXTO = 1, 65535


def conversation_key(clave: ClaveNostr, publica_otro: bytes) -> bytes:
    """HKDF-extract = HMAC-SHA256(sal, X compartida). Lanza ValueError si la pública no es válida."""
    try:
        x = clave.x_compartida(publica_otro)
    except Exception:
        raise ValueError("clave pública inválida") from None
    return hmac.new(b"nip44-v2", x, hashlib.sha256).digest()


def llaves_mensaje(ckey: bytes, nonce: bytes) -> tuple[bytes, bytes, bytes]:
    if len(ckey) != 32 or len(nonce) != 32:
        raise ValueError("largo de llave o nonce inválido")
    salida = HKDFExpand(algorithm=hashes.SHA256(), length=76, info=nonce).derive(ckey)
    return salida[0:32], salida[32:44], salida[44:76]


def largo_con_relleno(largo: int) -> int:
    """calc_padded_len de la spec: bloques de 32 hasta 256 B; después, octavos de la potencia de 2."""
    if largo <= 32:
        return 32
    siguiente_potencia = 1 << (largo - 1).bit_length()
    trozo = 32 if siguiente_potencia <= 256 else siguiente_potencia // 8
    return trozo * ((largo - 1) // trozo + 1)


def _rellenar(texto: str) -> bytes:
    datos = texto.encode("utf-8")
    if not MIN_TEXTO <= len(datos) <= MAX_TEXTO:
        raise ValueError("largo de mensaje inválido")
    return len(datos).to_bytes(2, "big") + datos + b"\x00" * (largo_con_relleno(len(datos)) - len(datos))


def _quitar_relleno(relleno: bytes) -> str:
    largo = int.from_bytes(relleno[0:2], "big")
    datos = relleno[2:2 + largo]
    if largo == 0 or len(datos) != largo or len(relleno) != 2 + largo_con_relleno(largo):
        raise ValueError("relleno inválido")
    return datos.decode("utf-8")


def _chacha20(llave: bytes, nonce12: bytes, datos: bytes) -> bytes:
    # cryptography pide un nonce de 16 B = contador de 4 B (little endian, parte en 0) + nonce de 12 B.
    cifrador = Cipher(algorithms.ChaCha20(llave, b"\x00" * 4 + nonce12), mode=None).encryptor()
    return cifrador.update(datos) + cifrador.finalize()


def _hmac_aad(llave: bytes, nonce: bytes, cifrado: bytes) -> bytes:
    return hmac.new(llave, nonce + cifrado, hashlib.sha256).digest()


def cifrar(texto: str, ckey: bytes, nonce: bytes | None = None) -> str:
    """`nonce` solo se pasa en las pruebas (vectores). En uso normal es aleatorio."""
    if nonce is None:
        nonce = os.urandom(32)
    chacha_key, chacha_nonce, hmac_key = llaves_mensaje(ckey, nonce)
    cifrado = _chacha20(chacha_key, chacha_nonce, _rellenar(texto))
    mac = _hmac_aad(hmac_key, nonce, cifrado)
    return base64.b64encode(bytes([VERSION]) + nonce + cifrado + mac).decode()


def descifrar(payload: str, ckey: bytes) -> str:
    """Valida versión y largos, verifica el HMAC en tiempo constante ANTES de descifrar.
    Lanza ValueError ante cualquier problema."""
    if not payload or payload[0] == "#":
        raise ValueError("versión de cifrado desconocida")
    if not 132 <= len(payload) <= 87472:
        raise ValueError("largo de payload inválido")
    try:
        datos = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("base64 inválido") from None
    if not 99 <= len(datos) <= 65603:
        raise ValueError("largo de datos inválido")
    if datos[0] != VERSION:
        raise ValueError("versión de cifrado desconocida")
    nonce, cifrado, mac = datos[1:33], datos[33:-32], datos[-32:]
    chacha_key, chacha_nonce, hmac_key = llaves_mensaje(ckey, nonce)
    if not hmac.compare_digest(_hmac_aad(hmac_key, nonce, cifrado), mac):
        raise ValueError("MAC inválido")
    try:
        return _quitar_relleno(_chacha20(chacha_key, chacha_nonce, cifrado))
    except UnicodeDecodeError:
        raise ValueError("texto inválido") from None
