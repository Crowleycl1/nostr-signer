"""Etapa b: cifrado NIP-04 y NIP-44 (todos los vectores oficiales).

Los vectores se descargaron una vez de
https://raw.githubusercontent.com/paulmillr/nip44/main/nip44.vectors.json
y se fija su sha256 para asegurar que nadie los cambió.
"""

import hashlib
import json
import unittest
from pathlib import Path

from nostr import nip04, nip44
from nostr.claves import ClaveNostr

VECTORES = Path(__file__).parent / "vectores" / "nip44.vectors.json"
SHA256_VECTORES = "269ed0f69e4c192512cc779e78c555090cebc7c785b609e338a62afc3ce25040"


def _cargar():
    crudo = VECTORES.read_bytes()
    assert hashlib.sha256(crudo).hexdigest() == SHA256_VECTORES, "los vectores NIP-44 fueron alterados"
    return json.loads(crudo.decode("utf-8"))["v2"]


V = _cargar()
VALIDOS, INVALIDOS = V["valid"], V["invalid"]


class TestNip44Validos(unittest.TestCase):
    def test_sha256_de_los_vectores(self):
        self.assertEqual(hashlib.sha256(VECTORES.read_bytes()).hexdigest(), SHA256_VECTORES)

    def test_conversation_key(self):
        for i, v in enumerate(VALIDOS["get_conversation_key"]):
            with self.subTest(i=i):
                clave = ClaveNostr(bytes.fromhex(v["sec1"]))
                self.assertEqual(nip44.conversation_key(clave, bytes.fromhex(v["pub2"])).hex(),
                                 v["conversation_key"])

    def test_llaves_de_mensaje(self):
        ckey = bytes.fromhex(VALIDOS["get_message_keys"]["conversation_key"])
        for i, v in enumerate(VALIDOS["get_message_keys"]["keys"]):
            with self.subTest(i=i):
                k, n, h = nip44.llaves_mensaje(ckey, bytes.fromhex(v["nonce"]))
                self.assertEqual((k.hex(), n.hex(), h.hex()),
                                 (v["chacha_key"], v["chacha_nonce"], v["hmac_key"]))

    def test_largo_con_relleno(self):
        for largo, esperado in VALIDOS["calc_padded_len"]:
            with self.subTest(largo=largo):
                self.assertEqual(nip44.largo_con_relleno(largo), esperado)

    def test_cifrar_descifrar(self):
        for i, v in enumerate(VALIDOS["encrypt_decrypt"]):
            with self.subTest(i=i):
                c1, c2 = ClaveNostr(bytes.fromhex(v["sec1"])), ClaveNostr(bytes.fromhex(v["sec2"]))
                ckey = nip44.conversation_key(c1, c2.publica)
                self.assertEqual(ckey.hex(), v["conversation_key"])
                # simetría: el otro lado obtiene la misma conversation_key
                self.assertEqual(nip44.conversation_key(c2, c1.publica), ckey)
                payload = nip44.cifrar(v["plaintext"], ckey, bytes.fromhex(v["nonce"]))
                self.assertEqual(payload, v["payload"])
                self.assertEqual(nip44.descifrar(payload, ckey), v["plaintext"])

    def test_mensajes_largos(self):
        for i, v in enumerate(VALIDOS["encrypt_decrypt_long_msg"]):
            with self.subTest(i=i):
                texto = v["pattern"] * v["repeat"]
                self.assertEqual(hashlib.sha256(texto.encode()).hexdigest(), v["plaintext_sha256"])
                ckey = bytes.fromhex(v["conversation_key"])
                payload = nip44.cifrar(texto, ckey, bytes.fromhex(v["nonce"]))
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), v["payload_sha256"])
                self.assertEqual(nip44.descifrar(payload, ckey), texto)


class TestNip44Invalidos(unittest.TestCase):
    def test_largos_de_mensaje_invalidos(self):
        ckey = bytes(32)
        for largo in INVALIDOS["encrypt_msg_lengths"]:
            with self.subTest(largo=largo), self.assertRaises(ValueError):
                nip44.cifrar("a" * largo, ckey)

    def test_conversation_key_invalida(self):
        for v in INVALIDOS["get_conversation_key"]:
            with self.subTest(nota=v["note"]), self.assertRaises(ValueError):
                nip44.conversation_key(ClaveNostr(bytes.fromhex(v["sec1"])), bytes.fromhex(v["pub2"]))

    def test_descifrar_invalido(self):
        for v in INVALIDOS["decrypt"]:
            with self.subTest(nota=v["note"]), self.assertRaises(ValueError):
                nip44.descifrar(v["payload"], bytes.fromhex(v["conversation_key"]))


class TestNip04(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.tercero = ClaveNostr.generar(), ClaveNostr.generar(), ClaveNostr.generar()

    def test_ida_y_vuelta(self):
        cifrado = nip04.cifrar(self.a, self.b.publica, '{"id":"1","method":"ping","params":[]}')
        self.assertIn("?iv=", cifrado)
        self.assertEqual(nip04.descifrar(self.b, self.a.publica, cifrado),
                         '{"id":"1","method":"ping","params":[]}')

    def test_unicode(self):
        texto = "Hola ñandú 🤙 — ¿firmas?"
        self.assertEqual(nip04.descifrar(self.b, self.a.publica, nip04.cifrar(self.a, self.b.publica, texto)),
                         texto)

    def test_un_tercero_no_descifra(self):
        texto = "solo para b" * 3
        cifrado = nip04.cifrar(self.a, self.b.publica, texto)
        # Con otra clave la llave AES es distinta: casi siempre el relleno sale inválido (ValueError);
        # NIP-04 no tiene MAC, así que en raras ocasiones "descifra" basura. Nunca el texto real.
        try:
            self.assertNotEqual(nip04.descifrar(self.tercero, self.a.publica, cifrado), texto)
        except ValueError:
            pass

    def test_formatos_invalidos(self):
        for malo in ["", "abc", "abc?iv=", "%%%?iv=AAAAAAAAAAAAAAAAAAAAAA==", "QUJD?iv=QUJD"]:
            with self.subTest(malo=malo), self.assertRaises(ValueError):
                nip04.descifrar(self.b, self.a.publica, malo)


if __name__ == "__main__":
    unittest.main()
