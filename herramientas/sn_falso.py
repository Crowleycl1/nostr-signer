"""Cliente de prueba que IMITA a Stacker News (NDK 2.12.2), no a la spec.

Hace lo mismo que la página de login de SN (DISENO.md H1–H7):
  - crea una clave de cliente NUEVA en cada corrida (H7);
  - cifra con NIP-04 (H1);
  - connect con params ["", secret] (H3) y exige la respuesta exacta "ack" (H2);
  - get_public_key y luego sign_event de un kind 27235 con challenge/u/method (H5);
  - de la respuesta usa solo `sig` y la verifica con SU PROPIO id (H6).

Uso (pega el bunker:// que muestra la app; las comillas son necesarias por el '&'):
    .venv\\Scripts\\python herramientas\\sn_falso.py "bunker://..."
    ... --kind 1                     # pedir firmar una nota → debe quedar bloqueado
    ... --kind 9734                  # pedir firmar un zap   → debe quedar bloqueado
    ... --secret-malo                # connect con otro secret → error
    ... --sitio https://otro.ejemplo/login   # login para otro sitio
    ... --nip44                      # usar NIP-44 en vez de NIP-04 (lo que pide la spec)
    ... --sin-firma                  # solo connect + get_public_key

Código de salida: 0 = firmado (o conectado con --sin-firma), 2 = el firmante respondió un error,
1 = falla de protocolo o tiempo agotado.
"""

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nostr import nip04, nip44  # noqa: E402
from nostr.claves import ClaveNostr, verificar_firma  # noqa: E402
from nostr.eventos import calcular_id, firmar_evento  # noqa: E402

SN_URL = "https://stacker.news/api/auth/callback/nostr"


class ErrorFirmante(Exception):
    pass


class ClienteNdk:
    def __init__(self, bunker: str, usar_nip44: bool):
        partes = urlparse(bunker)
        if partes.scheme != "bunker":
            raise SystemExit("el enlace debe empezar con bunker://")
        self.remota = partes.netloc
        q = parse_qs(partes.query)
        self.relay = q["relay"][0]
        self.secret = q.get("secret", [""])[0]
        self.clave = ClaveNostr.generar()  # clave de cliente nueva en cada corrida (H7)
        self.usar_nip44 = usar_nip44
        self.ws = None
        self.respuestas: dict[str, asyncio.Future] = {}

    def _cifrar(self, texto: str) -> str:
        pub = bytes.fromhex(self.remota)
        if self.usar_nip44:
            return nip44.cifrar(texto, nip44.conversation_key(self.clave, pub))
        return nip04.cifrar(self.clave, pub, texto)

    def _descifrar(self, contenido: str) -> str:
        pub = bytes.fromhex(self.remota)
        if "?iv=" in contenido:
            return nip04.descifrar(self.clave, pub, contenido)
        return nip44.descifrar(contenido, nip44.conversation_key(self.clave, pub))

    async def _leer(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            datos = json.loads(msg.data)
            if datos[0] == "OK" and not datos[2] or datos[0] in ("NOTICE", "CLOSED"):
                print(f"  (relay: {datos})")  # p. ej. límite de tasa: ayuda a diagnosticar
            if datos[0] == "EVENT" and datos[2].get("pubkey") == self.remota:
                try:
                    resp = json.loads(self._descifrar(datos[2]["content"]))
                except ValueError:
                    print("  (respuesta indescifrable)")
                    continue
                fut = self.respuestas.get(resp.get("id"))
                if fut and not fut.done():
                    fut.set_result(resp)

    async def pedir(self, metodo: str, params: list, espera: float):
        id_ = secrets.token_hex(4)
        texto = json.dumps({"id": id_, "method": metodo, "params": params})
        ev = firmar_evento(self.clave, 24133, self._cifrar(texto), [["p", self.remota]])
        self.respuestas[id_] = asyncio.get_running_loop().create_future()
        await self.ws.send_str(json.dumps(["EVENT", ev]))
        try:
            resp = await asyncio.wait_for(self.respuestas[id_], espera)
        except asyncio.TimeoutError:
            raise SystemExit(f"  ✗ {metodo}: sin respuesta en {espera:.0f} s") from None
        if resp.get("error"):
            raise ErrorFirmante(resp["error"])
        return resp["result"]


def plantilla(kind: int, sitio: str, pubkey: str) -> dict:
    if kind == 27235:
        tags = [["challenge", secrets.token_hex(16)], ["u", sitio], ["method", "GET"]]
        content = "Stacker News Authentication"
    elif kind == 9734:  # pedido de zap (gastaría sats): debe quedar bloqueado
        tags = [["p", pubkey], ["amount", "21000"], ["relays", "wss://relay.damus.io"]]
        content = ""
    else:  # kind 1 = nota pública: debe quedar bloqueado
        tags, content = [], "Esta nota no debería firmarse"
    ev = {"kind": kind, "created_at": int(time.time()), "tags": tags, "content": content, "pubkey": pubkey}
    ev["id"] = calcular_id(pubkey, ev["created_at"], kind, tags, content)
    return ev


async def principal(a) -> int:
    c = ClienteNdk(a.bunker, a.nip44)
    print(f"Cliente efímero {c.clave.publica_hex[:8]}… → firmante {c.remota[:8]}… vía {c.relay}"
          f" ({'NIP-44' if a.nip44 else 'NIP-04'})")
    async with aiohttp.ClientSession() as s, s.ws_connect(c.relay, max_msg_size=128 * 1024) as ws:
        c.ws = ws
        filtro = {"kinds": [24133], "#p": [c.clave.publica_hex], "since": int(time.time()) - 10}
        await ws.send_str(json.dumps(["REQ", "sn", filtro]))
        lector = asyncio.create_task(c._leer())
        try:
            secret = "secret-equivocado" if a.secret_malo else c.secret
            t = time.monotonic()
            r = await c.pedir("connect", ["", secret], 20)  # H3: primer parámetro vacío
            if r != "ack":  # H2
                print(f"  ✗ connect respondió {r!r} en vez de 'ack' (NDK rechazaría el login)")
                return 1
            print(f"  ✓ connect → ack ({time.monotonic() - t:.2f} s)")

            pub = await c.pedir("get_public_key", [], 20)
            if pub != c.remota:
                print("  ✗ get_public_key devolvió otra clave")
                return 1
            print(f"  ✓ get_public_key → {pub[:8]}…")
            if a.sin_firma:
                return 0

            ev = plantilla(a.kind, a.sitio, pub)
            print(f"  … sign_event kind {a.kind} para {a.sitio if a.kind == 27235 else '-'}"
                  " (si es un login, apruébalo en la página)")
            r = await c.pedir("sign_event", [json.dumps(ev)], a.espera)
            firmado = json.loads(r)
            # H6: NDK solo toma `sig` y lo verifica con SU id
            if not verificar_firma(bytes.fromhex(pub), bytes.fromhex(ev["id"]), bytes.fromhex(firmado["sig"])):
                print("  ✗ la firma NO es válida para el id del cliente")
                return 1
            print(f"  ✓ sign_event → firma válida para el id {ev['id'][:8]}…")
            return 0
        except ErrorFirmante as e:
            print(f"  ✗ el firmante respondió error: «{e}»")
            return 2
        finally:
            lector.cancel()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no siempre muestra ✓/✗
    p = argparse.ArgumentParser(description="Imita el login Nostr de Stacker News (NDK 2.12.2)")
    p.add_argument("bunker")
    p.add_argument("--kind", type=int, default=27235, choices=[27235, 1, 9734])
    p.add_argument("--sitio", default=SN_URL)
    p.add_argument("--secret-malo", action="store_true")
    p.add_argument("--nip44", action="store_true")
    p.add_argument("--sin-firma", action="store_true")
    p.add_argument("--espera", type=float, default=200, help="segundos a esperar la firma")
    sys.exit(asyncio.run(principal(p.parse_args())))
