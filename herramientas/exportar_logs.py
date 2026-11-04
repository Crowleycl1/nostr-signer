"""Exporta las conversaciones con Claude Code a docs/ai-logs/ para la entrega.

Lee los transcripts que Claude Code guarda en
    ~/.claude/projects/<carpeta-del-proyecto>/*.jsonl          (sesiones)
    ~/.claude/projects/<...>/<sesion>/subagents/*.jsonl        (subagentes, ej. la mesa de expertos)
y escribe:
    docs/ai-logs/sesiones/NN_<fecha>_<id>.md     versión legible (prompts, respuestas, herramientas)
    docs/ai-logs/crudo/<id>.jsonl                copia fiel, redactada

Redacta SIEMPRE: nsec1..., ncryptsec1..., correos electrónicos.
Redacta además cada línea de `data/redactar.txt` (no se commitea: data/ está en .gitignore).
Ahí van, una por línea, contraseñas usadas en pruebas o cualquier texto que no deba publicarse.

Uso (al final, cuando ya no queden sesiones por agregar):
    .venv\\Scripts\\python herramientas\\exportar_logs.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "ai-logs"
MAX_RESULTADO = 2000  # caracteres de cada resultado de herramienta en la versión legible

PATRONES = [
    (re.compile(r"nsec1[02-9ac-hj-np-z]{20,}"), "nsec1[REDACTADO]"),
    (re.compile(r"ncryptsec1[02-9ac-hj-np-z]{20,}"), "ncryptsec1[REDACTADO]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[correo]"),
]
# correos que sí deben quedar (el destinatario de la entrega, autoría de Claude)
CORREOS_PERMITIDOS = {"seleccion@hacienda.gov.cl", "noreply@anthropic.com"}
RECORDATORIO = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def carpeta_transcripts() -> Path:
    # Claude Code nombra la carpeta con la ruta del proyecto: c:\Proyecto\x -> c--Proyecto-x
    nombre = re.sub(r"[^A-Za-z0-9]", "-", str(RAIZ))
    base = Path.home() / ".claude" / "projects"
    for cand in base.iterdir():
        if cand.name.lower() == nombre.lower():
            return cand
    sys.exit(f"No encontré {base / nombre}")


def cargar_extra() -> list[str]:
    f = RAIZ / "data" / "redactar.txt"
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def redactar(texto: str, extra: list[str]) -> str:
    for patron, reemplazo in PATRONES:
        texto = patron.sub(
            lambda m: m.group(0) if m.group(0).lower() in CORREOS_PERMITIDOS else reemplazo, texto
        )
    for s in extra:
        texto = texto.replace(s, "[REDACTADO]")
    return texto


def leer(ruta: Path) -> list[dict]:
    filas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            filas.append(json.loads(linea))
        except json.JSONDecodeError:
            pass
    return filas


def texto_resultado(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes = []
        for p in contenido:
            if p.get("type") == "text":
                partes.append(p.get("text", ""))
            else:
                partes.append(f"[{p.get('type')}]")
        return "\n".join(partes)
    return str(contenido)


def bloque(texto: str, lenguaje: str = "") -> str:
    # cerco más largo que cualquier ``` interno
    cerco = "`" * max(3, max((len(m) for m in re.findall(r"`+", texto)), default=0) + 1)
    return f"{cerco}{lenguaje}\n{texto}\n{cerco}"


def es_prompt(d: dict) -> bool:
    """True si la fila es un mensaje escrito por la persona (no un resultado de herramienta)."""
    c = (d.get("message") or {}).get("content")
    return d.get("type") == "user" and (isinstance(c, str) or any(p.get("type") == "text" for p in c or []))


def a_markdown(filas: list[dict], titulo: str, nivel: str = "#") -> str:
    out = [f"{nivel} {titulo}", ""]
    for d in filas:
        tipo, msg = d.get("type"), d.get("message") or {}
        if tipo not in ("user", "assistant") or d.get("isMeta"):
            continue
        hora = (d.get("timestamp") or "")[11:19]
        contenido = msg.get("content")
        if isinstance(contenido, str):
            contenido = [{"type": "text", "text": contenido}]
        for p in contenido or []:
            t = p.get("type")
            if t == "text":
                texto = RECORDATORIO.sub("", p.get("text", "")).strip()
                if not texto:
                    continue
                if tipo == "user":
                    out += [f"## 🧑 Usuario · {hora}", "", texto, ""]
                else:
                    out += [f"### 🤖 Claude · {hora}", "", texto, ""]
            elif t == "thinking" and p.get("thinking", "").strip():
                out += ["<details><summary>Razonamiento</summary>", "", p["thinking"].strip(), "", "</details>", ""]
            elif t == "tool_use":
                entrada = json.dumps(p.get("input"), ensure_ascii=False, indent=2)
                out += [f"<details><summary>🔧 {p.get('name')}</summary>", "", bloque(entrada, "json"), "", "</details>", ""]
            elif t == "tool_result":
                r = texto_resultado(p.get("content"))
                if len(r) > MAX_RESULTADO:
                    r = r[:MAX_RESULTADO] + f"\n… [recortado: {len(r)} caracteres en total, ver crudo/]"
                out += ["<details><summary>↳ resultado</summary>", "", bloque(r), "", "</details>", ""]
    return "\n".join(out)


def main() -> None:
    origen = carpeta_transcripts()
    extra = cargar_extra()
    for sub in ("sesiones", "crudo"):
        shutil.rmtree(SALIDA / sub, ignore_errors=True)
        (SALIDA / sub).mkdir(parents=True)

    sesiones = []
    for f in origen.glob("*.jsonl"):
        filas = leer(f)
        inicio = next((d["timestamp"] for d in filas if d.get("timestamp")), "")
        sesiones.append((inicio, f, filas))
    sesiones.sort()

    indice = ["# Registros de conversación con el agente de IA (Claude Code)", "",
              "Exportados con `herramientas/exportar_logs.py`. `sesiones/` es la versión legible;",
              "`crudo/` son los transcripts originales (JSONL). Se redactaron nsec, correos y contraseñas de prueba.",
              "", "| # | Inicio | Sesión | Mensajes del usuario | Archivo |", "|---|---|---|---|---|"]

    for n, (inicio, f, filas) in enumerate(sesiones, 1):
        sid = f.stem[:8]
        fecha = inicio[:16].replace("T", " ")
        titulo = next((d.get("aiTitle") or d.get("title") for d in reversed(filas)
                       if d.get("type") == "ai-title"), None) or sid
        nombre = f"{n:02d}_{inicio[:10]}_{sid}"
        md = a_markdown(filas, f"Sesión {n}: {titulo} ({fecha} UTC)")

        # subagentes de esta sesión
        for sa in sorted((origen / f.stem / "subagents").glob("*.jsonl")):
            meta = sa.with_suffix(".meta.json")
            desc = json.loads(meta.read_text(encoding="utf-8")).get("description", sa.stem) if meta.exists() else sa.stem
            md += "\n\n---\n\n" + a_markdown(leer(sa), f"Subagente: {desc}", "##")
            (SALIDA / "crudo" / f"{sid}_{sa.stem}.jsonl").write_text(
                redactar(sa.read_text(encoding="utf-8"), extra), encoding="utf-8")

        (SALIDA / "sesiones" / f"{nombre}.md").write_text(redactar(md, extra), encoding="utf-8")
        (SALIDA / "crudo" / f"{sid}.jsonl").write_text(redactar(f.read_text(encoding="utf-8"), extra), encoding="utf-8")
        n_user = sum(map(es_prompt, filas))
        indice.append(f"| {n} | {fecha} | {titulo} | {n_user} | [sesiones/{nombre}.md](sesiones/{nombre}.md) |")

    indice += ["", "La carpeta `mesa-diseno/` tiene las propuestas y revisiones de los 3 expertos (subagentes) tal como las escribieron."]
    (SALIDA / "README.md").write_text("\n".join(indice) + "\n", encoding="utf-8")
    print(f"{len(sesiones)} sesiones exportadas a {SALIDA}")


if __name__ == "__main__":
    main()
