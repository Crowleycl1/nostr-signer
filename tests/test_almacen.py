"""Etapa b: almacén cifrado de la clave (data/clave.json)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import almacen
from nostr.claves import ClaveNostr

N_RAPIDO = 2**12  # en las pruebas se baja scrypt para que corran rápido (el n se lee del archivo)


class TestAlmacen(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.ruta = self.dir / "clave.json"
        self.clave = ClaveNostr.generar()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_guardar_y_leer_con_parametros_reales(self):
        almacen.guardar(self.clave, "contraseña-de-prueba", self.ruta)  # n = 2**17
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        self.assertEqual(datos["kdf"]["n"], 2**17)
        self.assertEqual(almacen.leer("contraseña-de-prueba", self.ruta).publica, self.clave.publica)

    def test_el_secreto_no_queda_en_claro(self):
        almacen.guardar(self.clave, "clave-prueba-1", self.ruta, n=N_RAPIDO)
        texto = self.ruta.read_text(encoding="utf-8")
        self.assertNotIn(self.clave.secreto_bytes().hex(), texto)
        self.assertNotIn(self.clave.nsec(), texto)
        self.assertFalse(self.ruta.with_suffix(".tmp").exists())

    def test_contrasena_mala(self):
        almacen.guardar(self.clave, "clave-prueba-1", self.ruta, n=N_RAPIDO)
        with self.assertRaises(almacen.ContrasenaIncorrecta):
            almacen.leer("otra-contraseña", self.ruta)

    def test_archivo_alterado(self):
        almacen.guardar(self.clave, "clave-prueba-1", self.ruta, n=N_RAPIDO)
        original = json.loads(self.ruta.read_text(encoding="utf-8"))

        # 1) cambiar la pubkey (va en claro, pero está amarrada por el AAD)
        datos = json.loads(json.dumps(original))
        datos["pubkey"] = ClaveNostr.generar().publica_hex
        self.ruta.write_text(json.dumps(datos), encoding="utf-8")
        with self.assertRaises(almacen.ContrasenaIncorrecta):
            almacen.leer("clave-prueba-1", self.ruta)

        # 2) cambiar un byte del texto cifrado
        datos = json.loads(json.dumps(original))
        t = datos["cifrado"]["texto"]
        datos["cifrado"]["texto"] = ("B" if t[0] != "B" else "C") + t[1:]
        self.ruta.write_text(json.dumps(datos), encoding="utf-8")
        with self.assertRaises(almacen.ContrasenaIncorrecta):
            almacen.leer("clave-prueba-1", self.ruta)

        # 3) parámetros de scrypt absurdos → formato inválido, sin intentar derivar
        datos = json.loads(json.dumps(original))
        datos["kdf"]["n"] = 2**30
        self.ruta.write_text(json.dumps(datos), encoding="utf-8")
        with self.assertRaises(ValueError):
            almacen.leer("clave-prueba-1", self.ruta)

        # 4) JSON roto
        self.ruta.write_text("{no es json", encoding="utf-8")
        with self.assertRaises(ValueError):
            almacen.leer("clave-prueba-1", self.ruta)


if __name__ == "__main__":
    unittest.main()
