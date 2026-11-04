"""Cliente WebSocket a UN relay Nostr: conectar, suscribirse, publicar y reconectar.

En simple: el relay es un "cartero" público. Le decimos "avísame de todos los eventos kind 24133
dirigidos a mi clave" (REQ) y nos los reenvía apenas llegan. Para responder, le mandamos
["EVENT", evento] y él lo reparte.

Ojo (DISENO.md H10): los kind 24133 son EFÍMEROS, el relay no los guarda. Si no estamos
suscritos cuando Stacker News manda el `connect`, ese mensaje se pierde. Por eso la app muestra
el bunker:// solo cuando ya estamos suscritos (`suscrito`).
"""

import asyncio
import json
import logging
import os
import time
from typing import Callable

import aiohttp

log = logging.getLogger("relay")

RELAY_POR_DEFECTO = "wss://relay.damus.io"
ESPERAS = [1, 2, 5, 10]   # segundos entre reintentos (fijos, DISENO.md §4 regla 8)
ESPERAS_PUBLICAR = [5, 15]  # si el relay dice "rate-limited" al publicar (DISENO.md H14)
MAX_MENSAJE = 128 * 1024  # un relay malicioso no nos puede mandar mensajes gigantes
ID_SUSCRIPCION = "firmante"


def url_relay() -> str:
    return os.environ.get("NOSTR_RELAY", RELAY_POR_DEFECTO)


class Relay:
    def __init__(self, url: str, pubkey_hex: str, al_recibir: Callable[[dict], None],
                 al_cambiar: Callable[[], None] = lambda: None):
        self.url = url
        self.pubkey_hex = pubkey_hex
        self.al_recibir = al_recibir  # se llama con cada evento que llega
        self.al_cambiar = al_cambiar  # se llama cuando cambia el estado (para la página)
        self.estado = "desconectado"  # "conectado" | "reconectando" | "desconectado"
        self.reintento_en: int | None = None
        self.suscrito = asyncio.Event()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._tarea: asyncio.Task | None = None
        # Respuestas enviadas que aún no confirma el relay: id → (evento, reintentos hechos).
        self._sin_confirmar: dict[str, tuple[dict, int]] = {}

    def iniciar(self) -> None:
        self._tarea = asyncio.create_task(self._bucle())

    async def cerrar(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    def _cambiar(self, estado: str, reintento_en: int | None = None) -> None:
        self.estado, self.reintento_en = estado, reintento_en
        self.al_cambiar()

    async def publicar(self, evento: dict) -> bool:
        """Envía un evento. Si no hay conexión, se pierde (el cliente puede reintentar)."""
        return await self._enviar(evento, 0)

    async def _enviar(self, evento: dict, reintentos: int) -> bool:
        if self._ws is None or self._ws.closed:
            log.warning("sin conexión: no se pudo publicar la respuesta")
            return False
        self._sin_confirmar[evento["id"]] = (evento, reintentos)
        if len(self._sin_confirmar) > 100:  # cota: los relays que no mandan OK no la hacen crecer
            self._sin_confirmar.pop(next(iter(self._sin_confirmar)))
        await self._ws.send_str(json.dumps(["EVENT", evento]))
        return True

    async def _reintentar(self, evento: dict, reintentos: int) -> None:
        """H14: relay.damus.io descarta respuestas con 'rate-limited:' si hubo mucho tráfico.
        Si justo se pierde la firma, Stacker News esperaría para siempre (H8): reintentamos."""
        espera = ESPERAS_PUBLICAR[reintentos]
        log.info("el relay pidió bajar el ritmo: reintento en %d s", espera)
        await asyncio.sleep(espera)
        await self._enviar(evento, reintentos + 1)

    async def _bucle(self) -> None:
        intento = 0
        async with aiohttp.ClientSession() as sesion:
            while True:
                try:
                    async with sesion.ws_connect(self.url, max_msg_size=MAX_MENSAJE, heartbeat=30,
                                                 timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                        self._ws = ws
                        intento = 0
                        await self._suscribir(ws)
                        await self._leer(ws)
                    log.info("el relay cerró la conexión")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # red caída, DNS, TLS, mensaje gigante…
                    log.info("error de conexión con el relay: %s", type(e).__name__)
                finally:
                    self._ws = None
                    self.suscrito.clear()

                espera = ESPERAS[min(intento, len(ESPERAS) - 1)]
                intento += 1
                for falta in range(espera, 0, -1):  # cuenta regresiva visible en la página
                    self._cambiar("reconectando", falta)
                    await asyncio.sleep(1)
                self._cambiar("reconectando", 0)

    async def _suscribir(self, ws) -> None:
        # `since` = hace 30 s: tolera un reloj algo desfasado sin traer mensajes viejos.
        filtro = {"kinds": [24133], "#p": [self.pubkey_hex], "since": int(time.time()) - 30}
        await ws.send_str(json.dumps(["REQ", ID_SUSCRIPCION, filtro]))
        log.info("suscrito a %s", self.url)
        # Algunos relays no mandan EOSE si no hay nada guardado; damos la suscripción por activa
        # al enviarla (el relay la procesa en orden, antes de cualquier evento posterior).
        self.suscrito.set()
        self._cambiar("conectado")

    async def _leer(self, ws) -> None:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    break
                continue
            try:
                datos = json.loads(msg.data)
                tipo = datos[0]
            except (ValueError, IndexError, KeyError, TypeError):
                continue
            if tipo == "EVENT" and len(datos) >= 3 and isinstance(datos[2], dict):
                self.al_recibir(datos[2])
            elif tipo == "OK" and len(datos) >= 3:
                evento, reintentos = self._sin_confirmar.pop(str(datos[1]), (None, 0))
                motivo = str(datos[3] if len(datos) > 3 else "")
                if not datos[2]:
                    if evento and motivo.startswith("rate-limited") and reintentos < len(ESPERAS_PUBLICAR):
                        asyncio.create_task(self._reintentar(evento, reintentos))
                    else:
                        log.warning("el relay rechazó una respuesta: %s", motivo[:100])
            elif tipo == "NOTICE":
                log.info("aviso del relay: %s", str(datos[1:2])[:100])
            elif tipo == "CLOSED":
                log.warning("el relay cerró la suscripción: %s", str(datos[2:3])[:100])
            # "EOSE" y "AUTH" se ignoran (no usamos autenticación con el relay).
