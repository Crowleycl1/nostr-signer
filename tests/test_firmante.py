"""Etapa c: lógica del firmante NIP-46 sin red.

Se simula un cliente como NDK (NIP-04, connect ["", secret]) entregando eventos directo a
`Firmante.recibir` y capturando lo que el firmante "publicaría" en el relay.
"""

import asyncio
import json
import time
import unittest
from urllib.parse import parse_qs, urlparse

from firmante import (ERR_EXPIRADO, ERR_NO_AUTORIZADO, ERR_RECHAZADO, ERR_SECRET, ERR_SOLO_LOGIN,
                      Firmante, PedidoExpirado)
from nostr import nip04, nip44
from nostr.claves import ClaveNostr, verificar_firma
from nostr.eventos import calcular_id, firmar_evento


class Cliente:
    """Mini cliente NIP-46 (como NDK) para las pruebas."""

    def __init__(self, firmante: Firmante, publicados: list, usar_nip44=False):
        self.f, self.publicados, self.nip44 = firmante, publicados, usar_nip44
        self.clave = ClaveNostr.generar()
        self.remota = firmante.clave.publica
        self.n = 0

    def _evento(self, metodo, params, firmar_con=None):
        self.n += 1
        texto = json.dumps({"id": f"r{self.n}", "method": metodo, "params": params})
        if self.nip44:
            contenido = nip44.cifrar(texto, nip44.conversation_key(self.clave, self.remota))
        else:
            contenido = nip04.cifrar(self.clave, self.remota, texto)
        return firmar_evento(firmar_con or self.clave, 24133, contenido, [["p", self.remota.hex()]])

    async def pedir(self, metodo, params=(), espera=2.0):
        antes = len(self.publicados)
        ev = self._evento(metodo, list(params))
        id_pedido = f"r{self.n}"
        self.f.recibir(ev)
        fin = time.monotonic() + espera
        while time.monotonic() < fin:
            for ev in self.publicados[antes:]:
                if ["p", self.clave.publica_hex] in ev["tags"]:
                    r = self._leer(ev)
                    if r["id"] == id_pedido:  # como NDK: empareja la respuesta por id
                        return r
            await asyncio.sleep(0.01)
        return None

    def _leer(self, ev):
        c = ev["content"]
        self.ultimo_esquema = "nip04" if "?iv=" in c else "nip44"
        if self.ultimo_esquema == "nip04":
            return json.loads(nip04.descifrar(self.clave, self.remota, c))
        return json.loads(nip44.descifrar(c, nip44.conversation_key(self.clave, self.remota)))


def login(pubkey, sitio="https://stacker.news/api/auth/callback/nostr", kind=27235, tags=None):
    tags = tags if tags is not None else [["challenge", "abc123def456"], ["u", sitio], ["method", "GET"]]
    ev = {"kind": kind, "created_at": int(time.time()), "tags": tags,
          "content": "Stacker News Authentication", "pubkey": pubkey}
    ev["id"] = calcular_id(pubkey, ev["created_at"], kind, tags, ev["content"])
    return ev


class TestFirmante(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.publicados = []

        async def publicar(ev):
            self.publicados.append(ev)
            return True

        self.clave = ClaveNostr.generar()
        self.f = Firmante(self.clave, "wss://relay.ejemplo", publicar, tiempo_aprobacion=0.5)
        self.c = Cliente(self.f, self.publicados)

    def secret(self):
        return parse_qs(urlparse(self.f.bunker()).query)["secret"][0]

    async def conectar(self, c=None):
        c = c or self.c
        return await c.pedir("connect", ["", self.secret()])

    async def test_bunker_tiene_pubkey_relay_y_secret(self):
        u = urlparse(self.f.bunker())
        self.assertEqual((u.scheme, u.netloc), ("bunker", self.clave.publica_hex))
        self.assertEqual(parse_qs(u.query)["relay"], ["wss://relay.ejemplo"])

    async def test_connect_ack_y_rota_secret(self):
        antes = self.secret()
        r = await self.conectar()
        self.assertEqual(r, {"id": "r1", "result": "ack"})
        self.assertEqual(self.c.ultimo_esquema, "nip04")  # responde con el mismo esquema
        self.assertNotEqual(self.secret(), antes)
        self.assertTrue(self.f.enlace_nuevo)
        # el secret viejo ya no sirve para otro cliente
        otro = Cliente(self.f, self.publicados)
        r = await otro.pedir("connect", ["", antes])
        self.assertEqual(r["error"], ERR_SECRET)

    async def test_connect_idempotente(self):
        await self.conectar()
        r = await self.c.pedir("connect", ["", "cualquiera"])
        self.assertEqual(r["result"], "ack")

    async def test_secret_malo(self):
        r = await self.c.pedir("connect", ["", "secret-malo"])
        self.assertEqual(r["error"], ERR_SECRET)
        self.assertEqual(len(self.f.autorizados), 0)

    async def test_no_autorizado(self):
        r = await self.c.pedir("get_public_key")
        self.assertEqual(r["error"], ERR_NO_AUTORIZADO)

    async def test_get_public_key_y_ping(self):
        self.assertEqual((await self.c.pedir("ping"))["result"], "pong")
        await self.conectar()
        self.assertEqual((await self.c.pedir("get_public_key"))["result"], self.clave.publica_hex)

    async def test_nip44_responde_nip44(self):
        c = Cliente(self.f, self.publicados, usar_nip44=True)
        self.assertEqual((await self.conectar(c))["result"], "ack")
        self.assertEqual(c.ultimo_esquema, "nip44")

    async def test_metodo_no_soportado(self):
        await self.conectar()
        self.assertIn("error", await self.c.pedir("nip04_decrypt", ["x", "y"]))

    async def test_firma_aprobada(self):
        await self.conectar()
        ev = login(self.clave.publica_hex)
        tarea = asyncio.create_task(self.c.pedir("sign_event", [json.dumps(ev)]))
        await asyncio.sleep(0.05)
        p = self.f.estado()["pendiente"]
        self.assertEqual(p["sitio"], "stacker.news")
        # mientras espera aprobación, un ping se responde igual (regla 3)
        self.assertEqual((await self.c.pedir("ping"))["result"], "pong")
        self.f.responder(p["id"], True)
        r = await tarea
        firmado = json.loads(r["result"])
        self.assertEqual(firmado["id"], ev["id"])  # se respetan los campos tal cual
        self.assertTrue(verificar_firma(self.clave.publica, bytes.fromhex(ev["id"]), bytes.fromhex(firmado["sig"])))
        self.assertEqual(self.f.historial[0]["tipo"], "firmado")
        self.assertIsNone(self.f.pendiente)

    async def test_firma_rechazada(self):
        await self.conectar()
        tarea = asyncio.create_task(self.c.pedir("sign_event", [json.dumps(login(self.clave.publica_hex))]))
        await asyncio.sleep(0.05)
        self.f.responder(self.f.estado()["pendiente"]["id"], False)
        self.assertEqual((await tarea)["error"], ERR_RECHAZADO)
        with self.assertRaises(PedidoExpirado):  # responder dos veces no hace nada
            self.f.responder("x", True)

    async def test_firma_expira(self):
        await self.conectar()
        r = await self.c.pedir("sign_event", [json.dumps(login(self.clave.publica_hex))], espera=2)
        self.assertEqual(r["error"], ERR_EXPIRADO)
        self.assertEqual(self.f.historial[0]["tipo"], "expirado")

    async def test_bloqueados(self):
        await self.conectar()
        pk = self.clave.publica_hex
        casos = {
            "nota kind 1": login(pk, kind=1),
            "zap kind 9734": login(pk, kind=9734),
            "27235 sin u": login(pk, tags=[["challenge", "x"], ["method", "GET"]]),
            "27235 sin method": login(pk, tags=[["u", "https://a.b"]]),
            "u no es URL web": login(pk, sitio="javascript:alert(1)"),
        }
        for nombre, ev in casos.items():
            with self.subTest(nombre):
                r = await self.c.pedir("sign_event", [json.dumps(ev)])
                self.assertEqual(r["error"], ERR_SOLO_LOGIN)
                self.assertIsNone(self.f.pendiente)  # nunca llega a la página
        self.assertEqual(self.f.historial[0]["tipo"], "bloqueado")

    async def test_otro_sitio_y_avisos(self):
        await self.conectar()
        ev = login(self.clave.publica_hex, sitio="http://otro.ejemplo/login")
        ev["created_at"] -= 3600
        ev["id"] = calcular_id(ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"])
        tarea = asyncio.create_task(self.c.pedir("sign_event", [json.dumps(ev)]))
        await asyncio.sleep(0.05)
        p = self.f.estado()["pendiente"]
        self.assertEqual(p["sitio"], "otro.ejemplo")
        self.assertEqual(len(p["avisos"]), 2)  # sin https + hora desfasada
        self.f.responder(p["id"], False)
        await tarea

    async def test_pubkey_o_id_ajenos(self):
        await self.conectar()
        ev = login(ClaveNostr.generar().publica_hex)
        self.assertIn("error", await self.c.pedir("sign_event", [json.dumps(ev)]))
        ev = login(self.clave.publica_hex)
        ev["id"] = "00" * 32
        self.assertIn("error", await self.c.pedir("sign_event", [json.dumps(ev)]))

    async def test_eventos_invalidos_se_ignoran(self):
        # firma inválida: contenido cambiado después de firmar
        ev = self.c._evento("ping", [])
        ev["content"] = nip04.cifrar(self.c.clave, self.c.remota, '{"id":"x","method":"ping","params":[]}')
        self.f.recibir(ev)
        # repetido: el mismo evento dos veces → una sola respuesta
        bueno = self.c._evento("ping", [])
        self.f.recibir(bueno)
        self.f.recibir(bueno)
        # dirigido a otra clave
        otro = firmar_evento(self.c.clave, 24133, "x?iv=y", [["p", ClaveNostr.generar().publica_hex]])
        self.f.recibir(otro)
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.publicados), 1)

    async def test_historial_sin_contenidos(self):
        await self.conectar()
        await self.c.pedir("get_public_key")
        texto = json.dumps(list(self.f.historial))
        self.assertNotIn(self.secret(), texto)
        self.assertEqual([h["tipo"] for h in self.f.historial], ["clave_publica", "conectado"])


if __name__ == "__main__":
    unittest.main()
