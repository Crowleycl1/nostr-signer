"""Claves Nostr: generar, convertir a nsec/npub, firmar y acuerdo de clave (ECDH).

Conceptos en simple:
- Clave secreta: 32 bytes al azar. Quien la tenga "es" tú. Se muestra como nsec1….
- Clave pública: se deriva de la secreta. Se comparte. Se muestra como npub1….
  Nostr usa la versión "x-only" (BIP-340): solo la coordenada X del punto, 32 bytes.
- Firma Schnorr (BIP-340): prueba que el dueño de la clave secreta aprobó un mensaje.
- X compartida (ECDH): dos personas obtienen el MISMO secreto combinando su clave
  secreta con la pública del otro. Es la base del cifrado NIP-04 y NIP-44.
"""

import os

from coincurve import PrivateKey, PublicKey, PublicKeyXOnly

from nostr import bech32


class ClaveNostr:
    """Envoltorio de la clave secreta. Su repr NUNCA muestra el secreto (evita filtrarlo en logs)."""

    def __init__(self, secreto: bytes):
        if len(secreto) != 32:
            raise ValueError("la clave secreta debe tener 32 bytes")
        self._privada = PrivateKey(secreto)  # coincurve valida que esté en el rango de la curva
        self.publica: bytes = self._privada.public_key.format()[1:]  # x-only, 32 bytes

    # --- crear ---
    @classmethod
    def generar(cls) -> "ClaveNostr":
        return cls(PrivateKey().secret)

    @classmethod
    def desde_nsec(cls, nsec: str) -> "ClaveNostr":
        return cls(decodificar_nip19(nsec, "nsec"))

    # --- formatos ---
    @property
    def publica_hex(self) -> str:
        return self.publica.hex()

    @property
    def npub(self) -> str:
        return bech32.codificar("npub", self.publica)

    def nsec(self) -> str:
        """Método (no propiedad) a propósito: leer el secreto debe ser una acción explícita."""
        return bech32.codificar("nsec", self._privada.secret)

    def secreto_bytes(self) -> bytes:
        """Solo para guardarla cifrada (almacen.py). No usar en logs ni respuestas."""
        return self._privada.secret

    # --- operaciones ---
    def firmar(self, mensaje32: bytes) -> bytes:
        """Firma Schnorr BIP-340 de un mensaje de 32 bytes (el id del evento). Devuelve 64 bytes."""
        return self._privada.sign_schnorr(mensaje32, os.urandom(32))

    def x_compartida(self, publica_otro: bytes) -> bytes:
        """ECDH: coordenada X SIN hashear del punto secreto·Pública_otro.

        OJO: coincurve.PrivateKey.ecdh() devuelve sha256 del punto, que NO sirve para
        NIP-04 ni NIP-44. Por eso multiplicamos el punto a mano. Anteponemos 0x02 porque
        la pubkey Nostr es x-only; la X del resultado no depende de esa paridad.
        """
        punto = PublicKey(b"\x02" + publica_otro).multiply(self._privada.secret)
        return punto.format()[1:]

    def __repr__(self) -> str:
        return f"<ClaveNostr {self.npub[:12]}…>"

    __str__ = __repr__


def verificar_firma(publica: bytes, mensaje32: bytes, firma: bytes) -> bool:
    """Verifica una firma Schnorr BIP-340. Devuelve False ante cualquier dato inválido."""
    try:
        return PublicKeyXOnly(publica).verify(firma, mensaje32)
    except Exception:
        return False


def decodificar_nip19(texto: str, prefijo_esperado: str) -> bytes:
    """nsec1…/npub1… → 32 bytes, verificando el prefijo. Lanza ValueError si no es válido."""
    prefijo, datos = bech32.decodificar(texto)
    if prefijo != prefijo_esperado:
        raise ValueError(f"se esperaba un {prefijo_esperado}, llegó un {prefijo}")
    if len(datos) != 32:
        raise ValueError("largo inválido")
    return datos
