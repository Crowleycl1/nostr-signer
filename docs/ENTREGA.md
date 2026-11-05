# Entrega: qué se envía y cómo

> Guía interna para armar la entrega rápido una vez que la app funcione. Sale del enunciado
> ("PRUEBA DE CONOCIMIENTOS TÉCNICOS - DEV", §4.3 y §4.4).

## Qué pide el enunciado

| Se pide | Dónde queda | Estado |
|---|---|---|
| Link a un **repositorio público** | GitHub | ☐ |
| Implementación | `app.py`, `firmante.py`, `nostr/`, `static/`… | ☐ |
| **README breve**: instalación, supuestos y tradeoffs | `README.md` (detalle en `docs/DISENO.md`) | ☐ |
| **Registros de conversación** con el agente de IA | `docs/ai-logs/` | ☐ |
| Demo del login en SN **de punta a punta** (§4.2) | `docs/demo.gif` enlazado en el README | ☐ |
| Envío por correo a `seleccion@hacienda.gov.cl` | dentro de los 4 días corridos | ☐ |

Qué se evalúa (§4.4): que el flujo funcione, cómo se maneja la ambigüedad, cómo se acota el alcance, claridad
del código, **prompting** y fundamentación. Por eso el README parte con la demo y sigue con las decisiones, y los
logs se pueden leer sin herramientas.

## Pasos el día de la entrega (~30 min)

1. **Tests en verde**: `.venv\Scripts\python -m unittest -v`
2. **Grabar la demo** (ver más abajo) y guardarla como `docs/demo.gif`.
3. **Completar el README** desde el esqueleto de abajo. Los supuestos y tradeoffs ya están en `docs/DISENO.md` §2–3.
4. **Cerrar las sesiones de Claude Code** y exportar los logs:
   `.venv\Scripts\python herramientas\exportar_logs.py`
   `data/redactar.txt` ya existe con la contraseña de la demo; agrega ahí, una por línea,
   cualquier otra que hayas usado. Esos textos se redactan y el archivo no se publica.
   ⚠️ **Solo se exportan las sesiones abiertas sobre `C:\Proyecto\nostr-signer`.** Lo que se
   converse desde otra carpeta (por ejemplo el proyecto del juego) queda en otro transcript y
   no entra en los logs de la entrega, aunque se haya trabajado en este repo.
5. **Revisar los logs a ojo**: abre `docs/ai-logs/sesiones/*.md` y busca cualquier cosa que no quieras publicar.
6. **Chequeo automático**: `.venv\Scripts\python herramientas\revisar_entrega.py` → debe decir `OK`.
7. **Probar desde un clon limpio** (otra carpeta): `git clone …`, crear venv, `pip install -r requirements.txt`,
   `python app.py`. Si funciona ahí, funciona para quien evalúa.
8. **Publicar** (ver más abajo) y abrir el repo en una ventana de incógnito para confirmar que es público y que el GIF se ve.
9. **Enviar el correo.**

## La demo

- **Grabar con Win+Alt+R** (Xbox Game Bar, ya viene en Windows; deja un MP4 en
  `%USERPROFILE%\Videos\Captures`). Después, el GIF con ffmpeg, que ya está instalado:

      powershell -ExecutionPolicy Bypass -File herramientas\gif.ps1 -Entrada "$env:USERPROFILE\Videos\Captures\<archivo>.mp4" -Desde 2 -Duracion 45

  Escribe `docs/demo.gif`, avisa cuánto pesa y, si pasa de 10 MB, dice con qué parámetros repetir.
  (ScreenToGif sirve igual pero hay que instalarlo: `winget install NickeManarin.ScreenToGif`.)
- **La clave de prueba ya está creada**: `data/credenciales-demo.txt` tiene el `nsec`, el `npub` y la
  contraseña para desbloquear. No es la identidad Nostr real de nadie y `data/` no se publica. La cuenta
  de Stacker News **se crea sola** en el primer login con ese `nsec`: la demo misma la crea.
- **Que el nsec no salga en pantalla.** Graba desde "Desbloquear" (con la clave ya creada) o difumina la pantalla de respaldo.
- Guion (~40 s, una ventana del navegador con dos pestañas, ancho ~1280 px):
  1. Terminal: `python app.py` → "Abre http://localhost:8000".
  2. Pestaña local: desbloquear → panel "Conectado a relay.damus.io" → **Copiar enlace**.
  3. Pestaña SN (página de login con Nostr): pegar el `bunker://` → *Login with token or NIP-05*.
  4. Pestaña local: aparece la tarjeta "Pedido de inicio de sesión" (stacker.news, kind 27235) → **Aprobar**.
  5. Pestaña SN: ya se inició sesión (se ve el usuario arriba a la derecha).
- Tamaño menor a 10 MB (GitHub no muestra inline un GIF más grande): ~10 fps y 1280 px de ancho bastan.

## Esqueleto del README

```markdown
# nostr-signer: firmante remoto Nostr (NIP-46) para iniciar sesión en Stacker News

![Demo: login en Stacker News aprobando la firma](docs/demo.gif)

Qué es, en 3 líneas: guardas tu nsec cifrada, la app te da un `bunker://`, lo pegas en Stacker News y apruebas la firma.

## Instalación y uso
Requisitos: Python 3.12, Windows/Linux/macOS.
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt      (Linux/macOS: .venv/bin/pip)
    .venv\Scripts\python app.py
Abre http://localhost:8000 → crea o importa una clave → copia el bunker:// → pégalo en
https://stacker.news/signup?callbackUrl=https%3A%2F%2Fstacker.news%2F&type=nostr → aprueba.
Variable opcional: NOSTR_RELAY (por defecto wss://relay.damus.io).
Tests: .venv\Scripts\python -m unittest -v

## Supuestos
(los 4-6 más importantes, de DISENO.md §2: SN usa NIP-04, "ack", params ["", secret], kind 27235, un solo usuario local…)

## Tradeoffs
(tabla corta de DISENO.md §3: clave cifrada con scrypt, misma clave para el bunker, solo kind 27235, polling, un relay…)

## Fuera de alcance
(lista de DISENO.md §3)

## Cómo se trabajó con IA
Claude Code (Claude Opus 5.5). Primero una "mesa" de 3 subagentes expertos (protocolo, seguridad, UX)
propuso y se revisó en cruz → docs/DISENO.md. Después se implementó por etapas, con verificación en cada una.
Registros completos: docs/ai-logs/ (versión legible en sesiones/, transcripts originales en crudo/).

## Estructura
(árbol de DISENO.md §6)
```

## Publicar en GitHub

Hecho el 04-11-2026. El repositorio público es
**https://github.com/Crowleycl1/nostr-signer** (cuenta `Crowleycl1`).

La identidad de git del repo quedó así, para que los commits queden atribuidos al autor sin
exponer el Gmail:

    git config user.name "Felipe Álamos Núñez"
    git config user.email "63745838+Crowleycl1@users.noreply.github.com"

Ese alias lo muestra GitHub en *Settings → Emails* al marcar *Keep my email addresses private*:
oculta tu Gmail y los commits siguen atribuidos a tu cuenta. El `63745838` sale de
`https://api.github.com/users/Crowleycl1` → campo `id`. Los 7 commits anteriores, que se habían
hecho con el Gmail, se reescribieron con `git filter-branch --env-filter` antes del primer push.

1. *New repository* → nombre `nostr-signer`, **Public**, sin README ni .gitignore (ya los tenemos).
2. Después:

       git add -A
       git status                       # revisa que no aparezcan data/ ni .venv/
       git commit -m "…"
       git branch -M main
       git remote add origin https://github.com/Crowleycl1/nostr-signer.git
       git push -u origin main

Los commits van por etapa (diseño, cripto, relay/firmante, UI, entrega): el historial también muestra cómo se trabajó.

## Borrador del correo

> **Para:** seleccion@hacienda.gov.cl
> **Asunto:** Prueba técnica DEV – Felipe Álamos Núñez – firmante NIP-46
>
> Estimados:
>
> Envío mi prueba técnica: un firmante remoto Nostr (NIP-46) en Python que permite
> iniciar sesión en Stacker News sin entregarle la clave privada al sitio.
>
> Repositorio público (en mi cuenta Crowleycl1): https://github.com/Crowleycl1/nostr-signer
>
> Para facilitar la revisión:
>
> - El flujo funcionando de principio a fin: es el GIF que abre el README; la grabación
>   original completa está en evidencia/.
> - Instalación, supuestos y tradeoffs: en el README.
> - La ambigüedad principal y cómo la resolví: la sección "NIP-04 vs NIP-44" del README
>   explica la decisión y su fundamento. Lo que dejé deliberadamente fuera de alcance
>   está en "Qué quedó fuera".
> - Registros de conversación con el agente de IA (Claude Code): en docs/ai-logs/, con
>   una versión legible en sesiones/ y, en mesa-diseno/, las propuestas y revisiones
>   cruzadas de los tres subagentes expertos con los que acoté el diseño.
> - Decisiones de diseño: docs/DISENO.md.
>
> Quedo atento a cualquier consulta.
>
> Saludos cordiales,
> Felipe Álamos Núñez
