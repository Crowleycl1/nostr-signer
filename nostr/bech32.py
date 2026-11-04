"""Codificación bech32 (BIP-173), la que usa NIP-19 para nsec1… y npub1….

En simple: convierte bytes en texto legible con un prefijo ("npub", "nsec") y un
checksum de 6 caracteres al final. Si alguien copia mal una letra, el checksum no
cuadra y lo detectamos.

Referencias:
- BIP-173: https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki
- NIP-19:  https://github.com/nostr-protocol/nips/blob/master/19.md
"""

# Alfabeto de 32 caracteres de bech32 (sin 1, b, i, o para evitar confusiones).
ALFABETO = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GENERADOR = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]


def _polymod(valores: list[int]) -> int:
    """Cálculo del checksum (BCH) definido en BIP-173."""
    chk = 1
    for v in valores:
        tope = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= _GENERADOR[i] if ((tope >> i) & 1) else 0
    return chk


def _expandir_hrp(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertir_bits(datos: bytes | list[int], desde: int, hacia: int, rellenar: bool) -> list[int]:
    """Reagrupa bits: de bytes (8 bits) a grupos de 5 bits, o al revés."""
    acc, bits, salida = 0, 0, []
    maximo = (1 << hacia) - 1
    for valor in datos:
        if valor < 0 or valor >> desde:
            raise ValueError("valor fuera de rango")
        acc = (acc << desde) | valor
        bits += desde
        while bits >= hacia:
            bits -= hacia
            salida.append((acc >> bits) & maximo)
    if rellenar:
        if bits:
            salida.append((acc << (hacia - bits)) & maximo)
    elif bits >= desde or ((acc << (hacia - bits)) & maximo):
        raise ValueError("relleno inválido")
    return salida


def codificar(hrp: str, datos: bytes) -> str:
    """Bytes → texto bech32. Ejemplo: codificar("npub", pubkey_32_bytes) → "npub1…"."""
    valores = _convertir_bits(datos, 8, 5, rellenar=True)
    polimod = _polymod(_expandir_hrp(hrp) + valores + [0] * 6) ^ 1
    checksum = [(polimod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(ALFABETO[v] for v in valores + checksum)


def decodificar(texto: str) -> tuple[str, bytes]:
    """Texto bech32 → (prefijo, bytes). Lanza ValueError si el texto no es válido."""
    texto = texto.strip()
    if texto.lower() != texto and texto.upper() != texto:
        raise ValueError("mezcla de mayúsculas y minúsculas")
    texto = texto.lower()
    pos = texto.rfind("1")
    if pos < 1 or pos + 7 > len(texto):
        raise ValueError("falta el separador '1' o el checksum")
    hrp, resto = texto[:pos], texto[pos + 1 :]
    if any(c not in ALFABETO for c in resto):
        raise ValueError("carácter no permitido")
    valores = [ALFABETO.index(c) for c in resto]
    if _polymod(_expandir_hrp(hrp) + valores) != 1:
        raise ValueError("checksum inválido (¿se copió mal alguna letra?)")
    return hrp, bytes(_convertir_bits(valores[:-6], 5, 8, rellenar=False))
