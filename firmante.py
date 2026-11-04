"""Lógica NIP-46 ("bunker"): recibe pedidos cifrados, decide y responde.

Flujo con Stacker News (DISENO.md §4):
  1. connect        → "ack" si el secret coincide; el cliente queda autorizado y el secret se rota.
  2. get_public_key → nuestra pubkey (no es secreta).
  3. sign_event     → solo inicios de sesión (kind 27235). Espera que el usuario apruebe en la página.
  ping              → "pong".

Este módulo no sabe nada de la web: la app le pasa una función `publicar` (para mandar respuestas
al relay) y se entera de los cambios con `al_cambiar` (que empuja el estado a la página por SSE).
"""

import asyncio
import hmac
import json
import logging
import secrets
import time
from collections import OrderedDict, deque
from typing import Awaitable, Callable
from urllib.parse import quote, urlparse

from nostr import nip04, nip44
from nostr.claves import ClaveNostr
from nostr.eventos import calcular_id, firmar_evento, verificar_evento

log = logging.getLogger("firmante")

KIND_NIP46 = 24133
KINDS_PERMITIDOS = {27235}  # NIP-98 "login HTTP". Para otro sitio con otro kind de login, agrégalo aquí.
TIEMPO_APROBACION = 120     # segundos
MAX_EVENTO = 64 * 1024
MAX_TAGS = 50
MAX_VISTOS = 2000
MAX_HISTORIAL = 20
DESFASE_AVISO = 600         # ±10 min en created_at → aviso (no bloquea)

ERR_NO_AUTORIZADO = "no autorizado"
ERR_SECRET = "secret inválido"
ERR_SOLO_LOGIN = "solo se firman inicios de sesión"
ERR_RECHAZADO = "rechazado por el usuario"
ERR_EXPIRADO = "expiró sin respuesta"
ERR_OCUPADO = "ya hay un pedido pendiente"
ERR_METODO = "método no soportado"
ERR_EVENTO = "evento inválido"


def corta(pub_hex: str) -> str:
    """Pubkey abreviada para logs e historial (nunca da información secreta)."""
    return f"{pub_hex[:8]}…{pub_hex[-4:]}"


class PedidoExpirado(Exception):
    """El usuario respondió a un pedido que ya no está pendiente."""


class Firmante:
    def __init__(self, clave: ClaveNostr, relay_url: str,
                 publicar: Callable[[dict], Awaitable[bool]],
                 al_cambiar: Callable[[], None] = lambda: None,
                 tiempo_aprobacion: float = TIEMPO_APROBACION):
        self.clave = clave
        self.relay_url = relay_url
        self.publicar = publicar
        self.al_cambiar = al_cambiar
        self.tiempo_aprobacion = tiempo_aprobacion
        self._secret = secrets.token_hex(16)
        self.autorizados: set[str] = set()        # pubkeys de clientes que mostraron un secret válido
        self._vistos: OrderedDict[str, None] = OrderedDict()  # ids ya procesados (el relay puede repetir)
        self.historial: deque[dict] = deque(maxlen=MAX_HISTORIAL)
        self.pendiente: dict | None = None
        self._futuro: asyncio.Future | None = None
        self.enlace_nuevo = False                 # True después de un connect (el enlace cambió)
        self._tareas: set[asyncio.Task] = set()

    # ---------- lo que ve la página ----------
    def bunker(self) -> str:
        return (f"bunker://{self.clave.publica_hex}?relay={quote(self.relay_url, safe='')}"
                f"&secret={self._secret}")

    def estado(self) -> dict:
        p = self.pendiente
        pendiente = None
        if p:
            pendiente = {k: p[k] for k in ("id", "sitio", "metodo_http", "challenge_corto", "created_at",
                                            "avisos", "evento", "cliente")}
            pendiente["expira_en"] = max(0, round(p["vence"] - time.monotonic()))
        return {"bunker": self.bunker(), "clientes": len(self.autorizados), "enlace_nuevo": self.enlace_nuevo,
                "pendiente": pendiente, "historial": list(self.historial)}

    def notificar(self) -> None:
        self.al_cambiar()

    def _anotar(self, tipo: str, detalle: str = "") -> None:
        self.historial.appendleft({"ts": int(time.time()), "tipo": tipo, "detalle": detalle})
        self.notificar()

    # ---------- entrada desde el relay ----------
    def recibir(self, ev: dict) -> None:
        """Regla 1: validar todo ANTES de descifrar (NIP-04 no tiene MAC; la firma prueba el autor)."""
        try:
            if ev.get("kind") != KIND_NIP46:
                return
            if ["p", self.clave.publica_hex] not in [t[:2] for t in ev.get("tags", []) if isinstance(t, list)]:
                return
            id_ = ev.get("id")
            if not isinstance(id_, str) or id_ in self._vistos:
                return
            if not verificar_evento(ev):
                log.info("evento con firma inválida, ignorado")
                return
        except Exception:
            return
        self._vistos[id_] = None
        if len(self._vistos) > MAX_VISTOS:
            self._vistos.popitem(last=False)
        # Regla 3: cada pedido en su propia tarea, así una firma esperando aprobación no bloquea un ping.
        tarea = asyncio.create_task(self._atender(ev))
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    async def _atender(self, ev: dict) -> None:
        cliente = ev["pubkey"]
        usa_nip04 = "?iv=" in ev["content"]  # el '?' no existe en base64: detección inequívoca (H1)
        try:
            if usa_nip04:
                texto = nip04.descifrar(self.clave, bytes.fromhex(cliente), ev["content"])
            else:
                texto = nip44.descifrar(ev["content"], nip44.conversation_key(self.clave, bytes.fromhex(cliente)))
            pedido = json.loads(texto)
            id_pedido, metodo, params = pedido["id"], pedido["method"], pedido.get("params", [])
            if not isinstance(id_pedido, str) or not isinstance(metodo, str) or not isinstance(params, list):
                raise ValueError
        except Exception:
            # Regla 2: no respondemos (podría ser basura o un ataque) y no logueamos el contenido.
            log.info("mensaje indescifrable de %s", corta(cliente))
            return

        log.info("pedido %s id=%s de %s (%s)", metodo, id_pedido[:12], corta(cliente),
                 "NIP-04" if usa_nip04 else "NIP-44")
        try:
            resultado, error = await self._despachar(cliente, metodo, params)
        except Exception:
            log.exception("error interno atendiendo %s", metodo)
            resultado, error = "", "error interno"

        respuesta = {"id": id_pedido, "result": resultado}
        if error:
            respuesta["error"] = error
            log.info("respuesta id=%s: error «%s»", id_pedido[:12], error)
        else:
            log.info("respuesta id=%s: ok", id_pedido[:12])
        texto = json.dumps(respuesta, ensure_ascii=False)
        # Responder con el MISMO esquema con que llegó: NDK cambia a NIP-44 si ve una respuesta sin "?iv=".
        if usa_nip04:
            contenido = nip04.cifrar(self.clave, bytes.fromhex(cliente), texto)
        else:
            contenido = nip44.cifrar(texto, nip44.conversation_key(self.clave, bytes.fromhex(cliente)))
        evento = firmar_evento(self.clave, KIND_NIP46, contenido, [["p", cliente]])
        await self.publicar(evento)

    async def _despachar(self, cliente: str, metodo: str, params: list) -> tuple[str, str | None]:
        if metodo == "ping":
            return "pong", None
        if metodo == "connect":
            return self._connect(cliente, params)
        if metodo in ("get_public_key", "sign_event") and cliente not in self.autorizados:
            return "", ERR_NO_AUTORIZADO
        if metodo == "get_public_key":
            self._anotar("clave_publica")
            return self.clave.publica_hex, None
        if metodo == "sign_event":
            return await self._sign_event(cliente, params)
        return "", ERR_METODO

    # ---------- métodos ----------
    def _connect(self, cliente: str, params: list) -> tuple[str, str | None]:
        """Regla 4: params = ["", secret] en NDK (H3); params[0] se ignora. Respuesta EXACTA "ack" (H2)."""
        if cliente in self.autorizados:
            return "ack", None  # idempotente
        secret = params[1] if len(params) > 1 and isinstance(params[1], str) else ""
        if not hmac.compare_digest(secret.encode(), self._secret.encode()):
            log.info("connect con secret inválido de %s", corta(cliente))
            return "", ERR_SECRET
        self.autorizados.add(cliente)
        self._secret = secrets.token_hex(16)  # un solo uso: el enlace mostrado cambia
        self.enlace_nuevo = True
        self._anotar("conectado", corta(cliente))
        return "ack", None

    async def _sign_event(self, cliente: str, params: list) -> tuple[str, str | None]:
        plantilla, error = self._validar_evento(params)
        if error:
            return "", error
        if not self._es_login(plantilla):
            self._anotar("bloqueado", str(plantilla["kind"]))
            return "", ERR_SOLO_LOGIN
        if self.pendiente is not None:
            return "", ERR_OCUPADO

        tags = plantilla["tags"]
        u = self._tag(tags, "u")
        avisos = []
        if urlparse(u).scheme != "https":
            avisos.append("El sitio no usa https.")
        if abs(plantilla["created_at"] - time.time()) > DESFASE_AVISO:
            avisos.append("La hora del pedido no coincide con la de tu computador.")
        challenge = self._tag(tags, "challenge") or ""
        self.pendiente = {
            "id": secrets.token_hex(8),
            "sitio": urlparse(u).hostname or "",
            "metodo_http": self._tag(tags, "method"),
            "challenge_corto": (challenge[:8] + "…") if len(challenge) > 8 else challenge,
            "created_at": plantilla["created_at"],
            "avisos": avisos,
            "evento": {k: plantilla[k] for k in ("kind", "created_at", "tags", "content")},
            "cliente": corta(cliente),
            "vence": time.monotonic() + self.tiempo_aprobacion,
        }
        self._futuro = asyncio.get_running_loop().create_future()
        sitio = self.pendiente["sitio"]
        log.info("pedido de firma pendiente para %s", sitio)
        self.notificar()
        try:
            aprobado = await asyncio.wait_for(asyncio.shield(self._futuro), self.tiempo_aprobacion)
        except asyncio.TimeoutError:
            aprobado = None
        finally:
            self.pendiente, self._futuro = None, None

        if aprobado is None:
            self._anotar("expirado", sitio)
            return "", ERR_EXPIRADO
        if not aprobado:
            self._anotar("rechazado", sitio)
            return "", ERR_RECHAZADO
        firmado = firmar_evento(self.clave, plantilla["kind"], plantilla["content"], tags, plantilla["created_at"])
        self._anotar("firmado", sitio)
        return json.dumps(firmado, separators=(",", ":"), ensure_ascii=False), None

    def responder(self, id_pendiente: str, aprobar: bool) -> None:
        """La página llama esto. Lanza PedidoExpirado si el pedido ya no está."""
        if (self.pendiente is None or self._futuro is None or self._futuro.done()
                or not hmac.compare_digest(self.pendiente["id"], str(id_pendiente))):
            raise PedidoExpirado()
        self._futuro.set_result(bool(aprobar))

    # ---------- validaciones ----------
    def _validar_evento(self, params: list) -> tuple[dict | None, str | None]:
        """Regla 6: tomar kind, created_at, tags y content tal cual, y revisar tipos y tamaños."""
        if not params or not isinstance(params[0], str) or len(params[0].encode()) > MAX_EVENTO:
            return None, ERR_EVENTO
        try:
            ev = json.loads(params[0])
            kind, created_at, tags, content = ev["kind"], ev["created_at"], ev["tags"], ev["content"]
        except (ValueError, KeyError, TypeError):
            return None, ERR_EVENTO
        if (type(kind) is not int or type(created_at) is not int or not isinstance(content, str)
                or not isinstance(tags, list) or len(tags) > MAX_TAGS
                or not all(isinstance(t, list) and all(isinstance(x, str) for x in t) for t in tags)):
            return None, ERR_EVENTO
        mia = self.clave.publica_hex
        if ev.get("pubkey") not in (None, "", mia):
            return None, "el evento es de otra clave"
        if ev.get("id") not in (None, "") and ev["id"] != calcular_id(mia, created_at, kind, tags, content):
            return None, "el id del evento no coincide"
        return {"kind": kind, "created_at": created_at, "tags": tags, "content": content}, None

    @staticmethod
    def _tag(tags: list, nombre: str) -> str | None:
        for t in tags:
            if len(t) >= 2 and t[0] == nombre:
                return t[1]
        return None

    def _es_login(self, ev: dict) -> bool:
        """Regla 7: kind 27235 con tag u (URL http/https con host) y tag method (NIP-98 exige ambas)."""
        if ev["kind"] not in KINDS_PERMITIDOS:
            return False
        u, metodo = self._tag(ev["tags"], "u"), self._tag(ev["tags"], "method")
        if not u or not metodo:
            return False
        try:
            partes = urlparse(u)
        except ValueError:
            return False
        return partes.scheme in ("http", "https") and bool(partes.hostname)
