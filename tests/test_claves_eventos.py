"""Etapa a: bech32, claves y eventos.

Correr:  .venv\\Scripts\\python -m unittest -v
"""

import unittest

from nostr import bech32
from nostr.claves import ClaveNostr, decodificar_nip19, verificar_firma
from nostr.eventos import calcular_id, firmar_evento, serializar, verificar_evento


class TestNip19(unittest.TestCase):
    """Ejemplos oficiales de NIP-19 (https://github.com/nostr-protocol/nips/blob/master/19.md)."""

    def test_npub_ejemplo_oficial(self):
        npub = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
        hex_ = "7e7e9c42a91bfef19fa929e5fda1b72e0ebc1a4c1141673e2794234d86addf4e"
        self.assertEqual(decodificar_nip19(npub, "npub").hex(), hex_)
        self.assertEqual(bech32.codificar("npub", bytes.fromhex(hex_)), npub)

    def test_nsec_ejemplo_oficial(self):
        nsec = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
        hex_ = "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"
        self.assertEqual(decodificar_nip19(nsec, "nsec").hex(), hex_)
        self.assertEqual(ClaveNostr.desde_nsec(nsec).nsec(), nsec)

    def test_letra_mal_copiada_se_detecta(self):
        malo = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptq"  # última letra cambiada
        with self.assertRaises(ValueError):
            decodificar_nip19(malo, "npub")

    def test_prefijo_equivocado(self):
        npub = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
        with self.assertRaises(ValueError):
            ClaveNostr.desde_nsec(npub)  # pegar un npub donde va un nsec debe fallar

    def test_espacios_alrededor_se_toleran(self):
        nsec = "  nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5\n"
        self.assertEqual(len(decodificar_nip19(nsec, "nsec")), 32)


class TestClaves(unittest.TestCase):

    def test_generar_y_volver_desde_nsec(self):
        c = ClaveNostr.generar()
        c2 = ClaveNostr.desde_nsec(c.nsec())
        self.assertEqual(c.publica, c2.publica)
        self.assertTrue(c.npub.startswith("npub1"))
        self.assertEqual(len(c.publica), 32)

    def test_repr_no_filtra_el_secreto(self):
        c = ClaveNostr.generar()
        self.assertNotIn(c.nsec(), repr(c))
        self.assertNotIn(c.secreto_bytes().hex(), repr(c))
        self.assertNotIn("nsec", repr(c))

    def test_firma_schnorr(self):
        c = ClaveNostr.generar()
        msg = bytes(range(32))
        firma = c.firmar(msg)
        self.assertTrue(verificar_firma(c.publica, msg, firma))
        self.assertFalse(verificar_firma(c.publica, bytes(32), firma))
        self.assertFalse(verificar_firma(ClaveNostr.generar().publica, msg, firma))

    def test_x_compartida_es_simetrica(self):
        """ECDH: A con la pública de B da lo mismo que B con la pública de A."""
        a, b = ClaveNostr.generar(), ClaveNostr.generar()
        self.assertEqual(a.x_compartida(b.publica), b.x_compartida(a.publica))
        self.assertEqual(len(a.x_compartida(b.publica)), 32)


class TestEventos(unittest.TestCase):

    def test_serializacion_compacta_y_utf8(self):
        s = serializar("ab", 1, 1, [["t", "ñ"]], 'hola "mundo"\nñandú')
        self.assertEqual(s.decode("utf-8"),
                         '[0,"ab",1,1,[["t","ñ"]],"hola \\"mundo\\"\\nñandú"]')

    def test_firmar_y_verificar_login_como_stacker_news(self):
        c = ClaveNostr.generar()
        tags = [["challenge", "k1-de-prueba"], ["u", "https://stacker.news"], ["method", "GET"]]
        ev = firmar_evento(c, 27235, "Stacker News Authentication", tags, created_at=1793750400)
        self.assertTrue(verificar_evento(ev))
        self.assertEqual(ev["tags"][0][0], "challenge")  # SN exige el challenge primero
        self.assertEqual(ev["id"], calcular_id(c.publica_hex, 1793750400, 27235, tags,
                                               "Stacker News Authentication"))

    def test_evento_alterado_no_verifica(self):
        ev = firmar_evento(ClaveNostr.generar(), 1, "original", [])
        ev_mod = dict(ev, content="modificado")
        self.assertFalse(verificar_evento(ev_mod))
        self.assertFalse(verificar_evento({"basura": True}))


if __name__ == "__main__":
    unittest.main()
