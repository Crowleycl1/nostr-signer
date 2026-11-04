"""Eventos Nostr (NIP-01): calcular el id, firmar y verificar.

Un evento es un JSON con: pubkey, created_at, kind, tags, content, id y sig.
- id  = sha256 de una serialización exacta: [0, pubkey, created_at, kind, tags, content]
        en JSON compacto (sin espacios) y UTF-8 sin escapar.
- sig = firma Schnorr del id con la clave secreta.

Referencia: https://github.com/nostr-protocol/nips/blob/master/01.md
"""

import hashlib
import json
import time

from nostr.claves import ClaveNostr, verificar_firma


def serializar(pubkey_hex: str, created_at: int, kind: int, tags: list, content: str) -> bytes:
    """Serialización NIP-01. `ensure_ascii=False` y separadores compactos dan el mismo
    resultado que JSON.stringify de JavaScript (lo que usa Stacker News para verificar)."""
    datos = [0, pubkey_hex, created_at, kind, tags, content]
    return json.dumps(datos, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def calcular_id(pubkey_hex: str, created_at: int, kind: int, tags: list, content: str) -> str:
    return hashlib.sha256(serializar(pubkey_hex, created_at, kind, tags, content)).hexdigest()


def firmar_evento(clave: ClaveNostr, kind: int, content: str, tags: list,
                  created_at: int | None = None) -> dict:
    """Crea un evento completo y firmado. Los campos se usan TAL CUAL (no se reordenan tags)."""
    if created_at is None:
        created_at = int(time.time())
    pubkey = clave.publica_hex
    id_hex = calcular_id(pubkey, created_at, kind, tags, content)
    return {
        "id": id_hex,
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": clave.firmar(bytes.fromhex(id_hex)).hex(),
    }


def verificar_evento(evento: dict) -> bool:
    """True si el id corresponde al contenido y la firma es válida. Nunca lanza excepción."""
    try:
        id_calculado = calcular_id(evento["pubkey"], evento["created_at"], evento["kind"],
                                   evento["tags"], evento["content"])
        if id_calculado != evento["id"]:
            return False
        return verificar_firma(bytes.fromhex(evento["pubkey"]), bytes.fromhex(evento["id"]),
                               bytes.fromhex(evento["sig"]))
    except (KeyError, TypeError, ValueError):
        return False
