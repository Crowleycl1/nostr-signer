"""Cifrado NIP-04 (el que usa Stacker News hoy, ver DISENO.md H1).

En simple: ambas partes calculan la misma "X compartida" (ECDH) y la usan como clave
AES-256 en modo CBC. El mensaje viaja como  base64(cifrado) + "?iv=" + base64(iv).

NIP-04 está "deprecado" porque no tiene MAC (nadie verifica que el texto cifrado no fue
alterado). Por eso el firmante verifica la FIRMA del evento antes de descifrar: así sabemos
que el contenido lo escribió quien dice ser.

Referencia: https://github.com/nostr-protocol/nips/blob/master/04.md
"""

import base64
import binascii
import os

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from nostr.claves import ClaveNostr

_ERROR = "mensaje NIP-04 inválido"  # un solo mensaje genérico: no damos pistas a un atacante


def cifrar(clave: ClaveNostr, publica_otro: bytes, texto: str) -> str:
    llave = clave.x_compartida(publica_otro)  # 32 bytes SIN hashear: eso dice la spec
    iv = os.urandom(16)
    relleno = padding.PKCS7(128).padder()
    datos = relleno.update(texto.encode("utf-8")) + relleno.finalize()
    cifrador = Cipher(algorithms.AES(llave), modes.CBC(iv)).encryptor()
    cifrado = cifrador.update(datos) + cifrador.finalize()
    return base64.b64encode(cifrado).decode() + "?iv=" + base64.b64encode(iv).decode()


def descifrar(clave: ClaveNostr, publica_otro: bytes, contenido: str) -> str:
    """Lanza ValueError genérico ante cualquier problema (formato, largo, relleno, UTF-8)."""
    try:
        parte_cifrada, parte_iv = contenido.split("?iv=")
        cifrado = base64.b64decode(parte_cifrada, validate=True)
        iv = base64.b64decode(parte_iv, validate=True)
        if len(iv) != 16 or len(cifrado) == 0 or len(cifrado) % 16 != 0:
            raise ValueError(_ERROR)
        llave = clave.x_compartida(publica_otro)
        descifrador = Cipher(algorithms.AES(llave), modes.CBC(iv)).decryptor()
        datos = descifrador.update(cifrado) + descifrador.finalize()
        quitar = padding.PKCS7(128).unpadder()
        return (quitar.update(datos) + quitar.finalize()).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError, AttributeError, TypeError):
        raise ValueError(_ERROR) from None
