"""Chequeo final antes de publicar el repositorio. No modifica nada.

Uso:
    .venv\\Scripts\\python herramientas\\revisar_entrega.py

Revisa que:
  1. data/, *.key y .env no estén en git (ni en el índice ni en el historial).
  2. Ningún archivo que se va a publicar contenga nsec1/ncryptsec1, correos personales
     ni los textos de data/redactar.txt.
  3. Existan README (con instalación, supuestos y tradeoffs), logs de IA y la demo.
  4. Los tests pasen.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NSEC = re.compile(r"n(?:crypt)?sec1[02-9ac-hj-np-z]{20,}")
CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CORREOS_OK = {"seleccion@hacienda.gov.cl", "noreply@anthropic.com"}
# ejemplos públicos que pueden aparecer en tests (vectores de NIP-19)
NSEC_OK = {"nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"}
PROHIBIDOS = re.compile(r"(^|/)(data/|\.env$|[^/]*\.key$)")

fallas: list[str] = []
avisos: list[str] = []


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8").stdout


def publicables() -> list[str]:
    # lo que está en git + lo nuevo que no está ignorado = lo que terminaría en el repo
    return sorted(set(git("ls-files").splitlines()) | set(git("ls-files", "--others", "--exclude-standard").splitlines()))


def extra() -> list[str]:
    f = RAIZ / "data" / "redactar.txt"
    return [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def main() -> None:
    archivos = publicables()

    # 1. archivos prohibidos
    for a in archivos:
        if PROHIBIDOS.search(a):
            fallas.append(f"archivo secreto a publicar: {a}")
    historial = git("log", "--all", "--name-only", "--format=")
    for a in set(historial.splitlines()):
        if a and PROHIBIDOS.search(a):
            fallas.append(f"archivo secreto en el HISTORIAL de git: {a} (hay que reescribir el historial)")

    # 2. contenido
    secretos = extra()
    for a in archivos:
        p = RAIZ / a
        if not p.is_file() or p.stat().st_size > 20_000_000:
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binarios (gif, png)
        for m in set(NSEC.findall(t)) - NSEC_OK:
            fallas.append(f"{a}: contiene {m[:12]}…")
        for m in {c for c in CORREO.findall(t) if c.lower() not in CORREOS_OK}:
            avisos.append(f"{a}: correo {m} (¿debe ser público?)")
        for s in secretos:
            if s in t:
                fallas.append(f"{a}: contiene un texto de data/redactar.txt")

    # 3. piezas de la entrega
    readme = RAIZ / "README.md"
    if not readme.exists():
        fallas.append("falta README.md")
    else:
        r = readme.read_text(encoding="utf-8").lower()
        for palabra in ("instala", "supuesto", "tradeoff"):
            if palabra not in r:
                fallas.append(f"README.md no menciona '{palabra}…'")
    if not list((RAIZ / "docs" / "ai-logs" / "sesiones").glob("*.md")):
        fallas.append("faltan los logs: corre herramientas/exportar_logs.py")
    demos = [p for p in (RAIZ / "docs").glob("demo*") if p.suffix.lower() in (".gif", ".mp4", ".webm")]
    if not demos:
        fallas.append("falta la demo: docs/demo.gif (o .mp4)")
    for d in demos:
        mb = d.stat().st_size / 1e6
        if mb > 10:
            avisos.append(f"{d.name} pesa {mb:.1f} MB; GitHub no la muestra inline si pasa de 10 MB")
        if readme.exists() and f"docs/{d.name}" not in readme.read_text(encoding="utf-8"):
            avisos.append(f"el README no enlaza docs/{d.name}")

    # 4. tests
    if (RAIZ / "tests").is_dir():
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            fallas.append("las pruebas fallan:\n" + r.stderr[-1500:])  # unittest escribe en stderr

    for a in avisos:
        print("AVISO ", a)
    for f in fallas:
        print("FALLA ", f)
    print("\nOK: listo para publicar." if not fallas else f"\n{len(fallas)} falla(s). No publicar todavía.")
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()
