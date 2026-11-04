"""Etapa d: servidor web (seguridad local y API), sin red: el relay se reemplaza por uno falso."""

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase

import almacen
import app as servidor

HOST = f"localhost:{servidor.PUERTO}"
ORIGEN = f"http://{HOST}"


class RelayFalso:
    """Se comporta como conectado y suscrito, sin abrir ningún WebSocket."""

    def __init__(self, url, pubkey_hex, al_recibir, al_cambiar=lambda: None):
        self.url, self.estado, self.reintento_en = url, "conectado", None
        self.suscrito = asyncio.Event()
        self.suscrito.set()
        self.publicados = []

    def iniciar(self):
        pass

    async def publicar(self, ev):
        self.publicados.append(ev)
        return True

    async def cerrar(self):
        pass


class TestApp(AioHTTPTestCase):
    async def get_application(self):
        self.dir = Path(tempfile.mkdtemp())
        self.parches = [mock.patch.object(almacen, "RUTA", self.dir / "clave.json"),
                        mock.patch.object(servidor, "Relay", RelayFalso)]
        for p in self.parches:
            p.start()
        return servidor.crear_app()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    @property
    def token(self):
        return self.app[servidor.ESTADO].token

    async def post(self, ruta, datos, token=None, origen=ORIGEN):
        cab = {"Host": HOST, "X-Token": token if token is not None else self.token}
        if origen:
            cab["Origin"] = origen
        r = await self.client.post(ruta, data=json.dumps(datos), headers=cab)
        return r.status, await r.json(content_type=None)

    async def leer_sse(self):
        r = await self.client.get(f"/api/eventos?token={self.token}", headers={"Host": HOST})
        self.assertEqual(r.status, 200)
        linea = b""
        while not linea.startswith(b"data: "):
            linea = await r.content.readline()
        r.close()
        return json.loads(linea[6:])

    # ---- seguridad ----
    async def test_host_ajeno_403(self):
        for ruta in ("/", "/app.js", f"/api/eventos?token={self.token}"):
            r = await self.client.get(ruta, headers={"Host": "evil.com"})
            self.assertEqual(r.status, 403, ruta)

    async def test_pagina_con_token_y_cabeceras(self):
        r = await self.client.get("/", headers={"Host": HOST})
        self.assertEqual(r.status, 200)
        html = await r.text()
        self.assertIn(f'<meta name="token" content="{self.token}">', html)
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        # sin JS ni estilos inline (la CSP los bloquearía igual)
        self.assertNotIn("style=", html)
        self.assertNotIn("onclick", html)
        self.assertNotRegex(html, r"<script>")

    async def test_post_sin_token_u_origen_ajeno_403(self):
        self.assertEqual(await self.post("/api/crear", {"contrasena": "x" * 8}, token=""),
                         (403, {"error": "token_invalido"}))
        self.assertEqual((await self.post("/api/crear", {"contrasena": "x" * 8}, origen="https://evil.com"))[0], 403)
        self.assertEqual((await self.post("/api/crear", {"contrasena": "x" * 8}, origen=None))[0], 403)
        self.assertFalse(almacen.existe())

    async def test_sse_sin_token_403(self):
        r = await self.client.get("/api/eventos?token=malo", headers={"Host": HOST})
        self.assertEqual(r.status, 403)

    # ---- flujo ----
    async def test_crear_desbloquear_y_estado(self):
        self.assertEqual((await self.leer_sse())["fase"], "sin_clave")
        self.assertEqual(await self.post("/api/crear", {"contrasena": "corta"}), (400, {"error": "contrasena_corta"}))
        self.assertEqual(await self.post("/api/crear", {"contrasena": "x" * 8, "nsec": "nsec1malo"}),
                         (400, {"error": "nsec_invalido"}))
        status, r = await self.post("/api/crear", {"contrasena": "contraseña-prueba"})
        self.assertEqual(status, 200)
        self.assertTrue(r["nsec"].startswith("nsec1"))  # se generó: se muestra una vez
        self.assertEqual((await self.post("/api/crear", {"contrasena": "x" * 8}))[1], {"error": "ya_existe_clave"})

        e = await self.leer_sse()
        self.assertEqual(e["fase"], "listo")
        self.assertTrue(e["bunker"].startswith("bunker://"))
        self.assertTrue(e["npub"].startswith("npub1"))
        self.assertNotIn("nsec1", json.dumps(e))  # el estado nunca lleva la clave secreta

        # simula un reinicio: nueva app en memoria, misma clave en disco
        est = self.app[servidor.ESTADO]
        est.clave = est.firmante = est.relay = None
        self.assertEqual((await self.leer_sse())["fase"], "bloqueado")
        self.assertEqual(await self.post("/api/desbloquear", {"contrasena": "otra-cosa"}),
                         (400, {"error": "contrasena_incorrecta"}))
        self.assertEqual(await self.post("/api/desbloquear", {"contrasena": "contraseña-prueba"}), (200, {"ok": True}))

    async def test_importar_no_devuelve_nsec(self):
        nsec = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"  # ejemplo público NIP-19
        status, r = await self.post("/api/crear", {"contrasena": "contraseña-prueba", "nsec": nsec})
        self.assertEqual((status, r), (200, {"ok": True}))

    async def test_responder_sin_pedido(self):
        await self.post("/api/crear", {"contrasena": "contraseña-prueba"})
        self.assertEqual(await self.post("/api/responder", {"id": "x", "aprobar": True}),
                         (409, {"error": "pedido_expirado"}))

    async def test_json_invalido(self):
        r = await self.client.post("/api/crear", data="{no", headers={"Host": HOST, "X-Token": self.token,
                                                                      "Origin": ORIGEN})
        self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
