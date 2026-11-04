"""Servidor local: la página (static/) + la API + el firmante, en un solo event loop.

Correr:  .venv\\Scripts\\python app.py      → abre http://localhost:8000

Seguridad local (DISENO.md §5):
- Solo escucha en 127.0.0.1 (otro equipo de la red no puede entrar).
- Host en lista blanca → frena el "DNS rebinding" (una web maliciosa que se hace pasar por localhost).
- Los POST exigen la cabecera X-Token (aleatoria en cada arranque) y un Origin local → frena el CSRF
  (que otra pestaña abierta llame a la API).
- CSP sin scripts ni estilos inline, nosniff y no-store.
"""

import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
from pathlib import Path

from aiohttp import web

import almacen
from firmante import Firmante, PedidoExpirado
from nostr.claves import ClaveNostr
from relay import Relay, url_relay

PUERTO = int(os.environ.get("PUERTO", "8000"))
ESTATICOS = Path(__file__).resolve().parent / "static"
LATIDO = 15  # segundos entre "ping" del SSE (mantiene viva la conexión)
MIN_CONTRASENA = 8

log = logging.getLogger("app")


class Estado:
    """Todo lo que vive mientras corre la app. La clave está solo en memoria."""

    def __init__(self, tiempo_aprobacion: float | None = None):
        self.token = secrets.token_urlsafe(32)
        self.clave: ClaveNostr | None = None
        self.firmante: Firmante | None = None
        self.relay: Relay | None = None
        self.paginas: set[asyncio.Event] = set()  # una señal por página conectada al SSE
        self.tiempo_aprobacion = tiempo_aprobacion
        self.ocupado = asyncio.Lock()  # crear/desbloquear no deben correr dos veces a la vez
        self.cerrando = False

    def fase(self) -> str:
        if self.clave:
            return "listo"
        return "bloqueado" if almacen.existe() else "sin_clave"

    def foto(self) -> dict:
        """El estado completo que se manda a la página (nunca incluye secretos salvo el bunker)."""
        datos = {"fase": self.fase(), "npub": None, "bunker": None, "relay": None,
                 "clientes": 0, "enlace_nuevo": False, "pendiente": None, "historial": []}
        if self.clave and self.firmante and self.relay:
            datos.update(self.firmante.estado())
            datos["npub"] = self.clave.npub
            datos["relay"] = {"url": self.relay.url, "estado": self.relay.estado,
                              "reintento_en": self.relay.reintento_en}
            # H10: el enlace se muestra solo si ya estamos suscritos; si no, el connect se perdería.
            if not (self.relay.estado == "conectado" and self.relay.suscrito.is_set()):
                datos["bunker"] = None
        return datos

    def notificar(self) -> None:
        for senal in self.paginas:
            senal.set()

    async def activar(self, clave: ClaveNostr) -> None:
        self.clave = clave
        url = url_relay()
        self.firmante = Firmante(clave, url, lambda ev: self.relay.publicar(ev), self.notificar,
                                 **({"tiempo_aprobacion": self.tiempo_aprobacion} if self.tiempo_aprobacion else {}))
        self.relay = Relay(url, clave.publica_hex, self.firmante.recibir, self.notificar)
        self.relay.iniciar()
        log.info("firmante activo para %s…", clave.npub[:16])
        self.notificar()


ESTADO = web.AppKey("estado", Estado)


# ---------- respuestas ----------
def error(codigo: str, status: int = 400) -> web.Response:
    return web.json_response({"error": codigo}, status=status)


async def leer_json(pedido: web.Request) -> dict:
    try:
        datos = await pedido.json()
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "json_invalido"}), content_type="application/json")
    if not isinstance(datos, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "json_invalido"}), content_type="application/json")
    return datos


# ---------- middleware de seguridad ----------
HOSTS = {f"localhost:{PUERTO}", f"127.0.0.1:{PUERTO}"}
ORIGENES = {f"http://{h}" for h in HOSTS}
CABECERAS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # la página lleva el token: que el navegador no la guarde
}


@web.middleware
async def seguridad(pedido: web.Request, handler):
    if pedido.host not in HOSTS:  # DNS rebinding
        return web.Response(status=403, text="Host no permitido")
    if pedido.method == "POST":
        token = pedido.headers.get("X-Token", "")
        origen = pedido.headers.get("Origin", "")
        if not hmac.compare_digest(token.encode(), pedido.app[ESTADO].token.encode()) or origen not in ORIGENES:
            return error("token_invalido", 403)
    try:
        respuesta = await handler(pedido)
    except web.HTTPException as e:
        respuesta = e
    if not respuesta.prepared:  # el SSE ya mandó sus cabeceras al prepararse
        respuesta.headers.update(CABECERAS)
    return respuesta


# ---------- rutas ----------
async def pagina(pedido: web.Request) -> web.Response:
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{TOKEN}}", pedido.app[ESTADO].token)  # token en <meta>, sin JS inline
    return web.Response(text=html, content_type="text/html")


def archivo(nombre: str, tipo: str):
    async def manejador(_pedido):
        return web.Response(body=(ESTATICOS / nombre).read_bytes(), content_type=tipo, charset="utf-8")
    return manejador


async def eventos(pedido: web.Request) -> web.StreamResponse:
    """SSE: manda el estado al conectar y cada vez que algo cambia. Latido cada 15 s."""
    est: Estado = pedido.app[ESTADO]
    if not hmac.compare_digest(pedido.query.get("token", "").encode(), est.token.encode()):
        return error("token_invalido", 403)
    respuesta = web.StreamResponse(headers={"Content-Type": "text/event-stream", **CABECERAS})
    await respuesta.prepare(pedido)
    senal = asyncio.Event()
    senal.set()  # para mandar el estado completo apenas se conecta
    est.paginas.add(senal)
    try:
        while not est.cerrando:
            try:
                await asyncio.wait_for(senal.wait(), LATIDO)
            except asyncio.TimeoutError:
                await respuesta.write(b": ping\n\n")  # latido: nada cambió
                continue
            senal.clear()  # varios cambios seguidos se juntan en un solo envío
            if est.cerrando:
                break
            datos = json.dumps(est.foto(), ensure_ascii=False)
            await respuesta.write(f"event: estado\ndata: {datos}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass  # la pestaña se cerró
    finally:
        est.paginas.discard(senal)
    return respuesta


async def crear(pedido: web.Request) -> web.Response:
    est: Estado = pedido.app[ESTADO]
    datos = await leer_json(pedido)
    contrasena = datos.get("contrasena")
    nsec = datos.get("nsec")
    async with est.ocupado:
        if est.clave or almacen.existe():
            return error("ya_existe_clave", 409)
        if not isinstance(contrasena, str) or len(contrasena) < MIN_CONTRASENA:
            return error("contrasena_corta")
        if nsec:
            try:
                clave = ClaveNostr.desde_nsec(str(nsec))
            except Exception:
                return error("nsec_invalido")
        else:
            clave = ClaveNostr.generar()
        await asyncio.to_thread(almacen.guardar, clave, contrasena)  # scrypt tarda ~0,3 s
        await est.activar(clave)
    # El nsec se devuelve UNA sola vez y solo si lo generamos nosotros (para respaldarlo).
    return web.json_response({"ok": True, **({} if nsec else {"nsec": clave.nsec()})})


async def desbloquear(pedido: web.Request) -> web.Response:
    est: Estado = pedido.app[ESTADO]
    datos = await leer_json(pedido)
    contrasena = datos.get("contrasena")
    async with est.ocupado:
        if est.clave:
            return web.json_response({"ok": True})
        if not almacen.existe():
            return error("sin_clave", 409)
        if not isinstance(contrasena, str):
            return error("contrasena_incorrecta")
        try:
            clave = await asyncio.to_thread(almacen.leer, contrasena)
        except almacen.ContrasenaIncorrecta:
            log.info("intento de desbloqueo con contraseña incorrecta")
            return error("contrasena_incorrecta")
        except ValueError:
            return error("archivo_invalido", 500)
        await est.activar(clave)
    return web.json_response({"ok": True})


async def responder(pedido: web.Request) -> web.Response:
    est: Estado = pedido.app[ESTADO]
    datos = await leer_json(pedido)
    if not est.firmante:
        return error("pedido_expirado", 409)
    try:
        est.firmante.responder(str(datos.get("id", "")), datos.get("aprobar") is True)
    except PedidoExpirado:
        return error("pedido_expirado", 409)
    return web.json_response({"ok": True})


async def al_apagar(app: web.Application) -> None:
    est: Estado = app[ESTADO]
    est.cerrando = True
    for senal in est.paginas:  # despierta los SSE para que terminen
        senal.set()


async def al_cerrar(app: web.Application) -> None:
    est: Estado = app[ESTADO]
    if est.relay:
        await est.relay.cerrar()


def crear_app(tiempo_aprobacion: float | None = None) -> web.Application:
    app = web.Application(middlewares=[seguridad], client_max_size=64 * 1024)
    app[ESTADO] = Estado(tiempo_aprobacion)
    app.router.add_get("/", pagina)
    app.router.add_get("/app.css", archivo("app.css", "text/css"))
    app.router.add_get("/app.js", archivo("app.js", "text/javascript"))
    app.router.add_get("/api/eventos", eventos)
    app.router.add_post("/api/crear", crear)
    app.router.add_post("/api/desbloquear", desbloquear)
    app.router.add_post("/api/responder", responder)
    app.on_shutdown.append(al_apagar)
    app.on_cleanup.append(al_cerrar)
    return app


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-8s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout)
    # Variable solo para pruebas: acorta los 120 s de aprobación (ej. TIEMPO_APROBACION=10).
    tiempo = float(os.environ["TIEMPO_APROBACION"]) if os.environ.get("TIEMPO_APROBACION") else None
    print(f"Abre http://localhost:{PUERTO}", flush=True)
    # access_log=None: el log de accesos de aiohttp mostraría la URL del SSE, que lleva el token.
    web.run_app(crear_app(tiempo), host="127.0.0.1", port=PUERTO, access_log=None, print=None,
                shutdown_timeout=2)


if __name__ == "__main__":
    main()
