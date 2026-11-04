# 3 · Propuesta UX/UI — nostr-signer

Leyenda: **[V]** = verificado con fuente (cita) · **[P]** = propuesta mía.

## 0. Advertencia de identidad (obligatoria)

App independiente "inspirada en" el Kit Digital / Framework gob.cl. **Sin escudo, sin isologo "Gobierno de Chile", sin "gob.cl" en el título** ni nada que la haga pasar por un servicio público. Pie fijo en la página:
> "Aplicación independiente de prueba técnica. No es un sitio del Gobierno de Chile. Estilo visual inspirado en el Kit Digital (kitdigital.gob.cl)."

El manual exige aplicar el isologo solo desde el original del Kit Digital [V: Manual de Normas Gráficas 2026, p. 34]. Por eso no lo usamos.

## 1. Identidad visual

Fuentes:
- **F1** = Manual de Normas Gráficas 2026 (`kitdigital.gob.cl/archivos/2026/ManualNormasGraficas2026.pdf`, p. 33).
- **F2** = Framework `@gobdigital-cl/gob.cl` v3.0.10 (npm), `src/scss/abstracts/_variables.scss`.
- **F3** = el mismo paquete, `dist/css/gob.cl.css`.

| Rol | HEX | Fuente |
|---|---|---|
| Azul institucional (Pantone 293 C, RGB 15 105 180) | `#0f69b4` | [V] F1 y F2 `$brand-color-primary` |
| Rojo institucional (Pantone 185 C, RGB 235 60 70) | `#eb3c46` | [V] F1 |
| Rojo de la franja web | `#e22c2c` | [V] F2 `$brand-color-secondary` |
| Azul oscuro (terciario) | `#001c41` | [V] F2 `$brand-color-tertiary` |
| Azul primario de botones del framework | `#006fb3` | [V] F2 `$primary`, F3 `.btn-primary` |
| Texto del body | `#212529` | [V] F3 `body{color}` |
| Gris de texto secundario | `#4a4a4a` | [V] F2 `$gray-a` |
| Fondo claro / borde | `#f8f9fa` / `#dee2e6` | [V] F2 `$gray-100` / `$gray-300` |
| Éxito (texto/fondo) | `#204349` / `#d5e3e5` | [V] F3 `.alert-success` (base `$green #2d717c`) |
| Info | `#145c68` / `#d1ecf1` | [V] F3 `.alert-info` |
| Advertencia | fondo `#fcf4d4` | [V] F3 `.alert-warning` (pero ver contraste abajo) |
| Error | `#8c3d3d` / `#ffe0e0` | [V] F3 `.alert-danger` |

**La franja** [V F3]: `.line::after` mide 5 px de alto y usa `linear-gradient(to right, #0f69b4 0 50%, #e22c2c 50% 100%)`. Es **bicolor azul/rojo 50/50**, no tricolor. [P] La pondremos de 6 px en el borde superior de la cabecera, sobre una banda `#001c41` con el nombre de la app en blanco.

**Tipografía**: la oficial es **gobCL** [V F1, índice "Tipografía gobCL", p. 39; el Kit Digital la ofrece como `Tipografia-gobCL.zip`]. El framework web usa `"Roboto", sans-serif` y `"Roboto Slab"` para los acentos [V F2 `$primary-font`, `$accent-font`]. No pude leer la "Tipografía alternativa" (p. 40): esas páginas son imágenes. [P] **No la empaquetamos**, por la licencia y por el tiempo. Pila con fallback del sistema, funciona offline:
`font-family: "gobCL", "Roboto", system-ui, "Segoe UI", Arial, sans-serif;`
Si el usuario tiene gobCL o Roboto instaladas, se usan. Si no, entra Segoe UI en Windows.

**Bordes**: el framework usa `$border-radius: 0` [V F2]. [P] Usamos 4 px solo en las tarjetas (`$card-detail-border-radius: .25rem`, [V F2]) y 0 en los botones, para mantener su estilo recto.

### Contraste (WCAG 2.x, calculado con la fórmula de luminancia relativa) [V cálculo propio]

| Par (texto / fondo) | Razón | AA texto normal (4.5) |
|---|---|---|
| blanco / `#0f69b4` (botón primario) | 5.68 | Sí |
| blanco / `#001c41` (cabecera) | 16.9 | Sí |
| blanco / `#e22c2c` (botón peligro) | 4.54 | Sí, por poco |
| blanco / `#eb3c46` (rojo manual) | 3.99 | **No**: solo para decorar |
| blanco / `#fe6565` (`.btn-danger` del framework) | 2.89 | **No**: no usar |
| `#212529` / blanco | 15.43 | Sí |
| `#4a4a4a` / blanco (ayudas) | 8.86 | Sí |
| `#0f69b4` / blanco (enlaces) | 5.68 | Sí |
| `#204349` / `#d5e3e5` (éxito) | 8.13 | Sí |
| `#145c68` / `#d1ecf1` (info) | 6.15 | Sí |
| `#8c3d3d` / `#ffe0e0` (error) | 5.96 | Sí |
| `#86701d` / `#fcf4d4` (warning del framework) | 4.38 | **No** → [P] usar texto `#212529` (13.98) |
| `#6c757d` / blanco | 4.69 | Sí (mínimo para texto tenue) |
| `#8a8a8a` / blanco (placeholder del framework) | 3.45 | **No** → [P] no usar placeholders como ayuda |
| foco `#0f69b4` / blanco (no textual, ≥ 3) | 5.68 | Sí |
| foco `#ffbf47` / `#001c41` (sobre cabecera) | 10.3 | Sí |

## 2. Accesibilidad [P]
- `<html lang="es">`, un solo `<h1>` por estado, `<main>` y un enlace "Saltar al contenido".
- Texto base de **18 px** (`1.125rem`), interlineado 1.5, y 20 px para valores clave (npub, bunker). Botones de **48 px** de alto como mínimo y padding de 12×24.
- Foco siempre visible: `:focus-visible { outline: 3px solid var(--foco); outline-offset: 3px }`. El framework solo pone un `box-shadow` al 25 % [V F3], que es poco visible.
- Todo se maneja con Tab, Enter y Espacio. No hay atajos de una tecla: así no se aprueba nada por accidente.
- Pedido nuevo: hay una región `aria-live="assertive"` oculta que anuncia "Nuevo pedido de firma de Stacker News". El foco va al `<h2 tabindex="-1">` de la tarjeta, **nunca al botón Aprobar**: un Enter distraído no debe firmar.
- El historial es `role="log"` con `aria-live="polite"`. El estado del relay es `role="status"`.
- Los estados no dependen solo del color: cada uno lleva texto y un ícono de texto (●, ⟳, ✓, ✕).
- Los errores van debajo del campo con `aria-describedby` y `aria-invalid="true"`, y el foco vuelve al campo.
- `prefers-reduced-motion`: sin animación de entrada, solo el borde destacado.

## 3. Wireframes y textos exactos

Cabecera común (todos los estados):
```
████████████████████████▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓   ← franja 6px azul|rojo
 Firmante Nostr  ·  para iniciar sesión en Stacker News      (fondo #001c41)
```

**(A) Crear o importar clave**: primera vez
```
 h1  Configura tu identidad Nostr
 p   Tu identidad Nostr es un par de claves. La clave secreta (nsec) se queda
     en este computador, cifrada con tu contraseña.
 ( ) Crear una clave nueva          (•) Ya tengo una clave (nsec)
     ┌─ Pega tu nsec ─────────────────────────┐ [Mostrar]
     │ nsec1…                                  │
     └─────────────────────────────────────────┘
     Ayuda: Empieza con "nsec1". Solo se guarda en este equipo.
 Contraseña               [__________] [Mostrar]
 Repite la contraseña     [__________]
     Ayuda: Mínimo 8 caracteres. Si la olvidas, no se puede recuperar.
 ⚠ Nunca compartas tu nsec. Quien la tenga puede hacerse pasar por ti.
 [ Guardar y continuar ]  (primario)
```
Errores: "Eso no parece un nsec válido. Debe empezar con nsec1 y no tener espacios." · "Las contraseñas no coinciden." · "La contraseña debe tener al menos 8 caracteres."

**A2. Respaldo** (solo si se generó la clave; se muestra una sola vez)
```
 h1  Respalda tu clave secreta
 ⚠ (aviso advertencia) Esta es la única vez que verás tu nsec. Cópiala en un
   lugar seguro (gestor de contraseñas o papel). Si la pierdes, pierdes la cuenta.
 ┌ nsec1qq…………………………………… ┐  [Copiar]
 [✓] Ya guardé mi nsec en un lugar seguro
 [ Continuar ]  (deshabilitado hasta marcar la casilla)
```

**(B) Desbloquear**
```
 h1  Desbloquea tu firmante
 p   Tu clave está guardada cifrada en este equipo.
 Contraseña  [__________] [Mostrar]
 [ Desbloquear ]
```
Error: "Contraseña incorrecta. Inténtalo de nuevo." Tip: "¿Olvidaste la contraseña? Sin ella no se puede descifrar la clave. Puedes borrar `data/` e importar tu nsec de nuevo."

**(C) Panel conectado**
```
 h1  Tu firmante está listo
 Estado del relay:  ● Conectado a wss://relay…    | ⟳ Reconectando…  (status)
 Tu identidad pública (npub)          ← se puede compartir
 ┌ npub1…  ┐ [Copiar]
 ── Cómo iniciar sesión en Stacker News ──
 ① Paso 1: Abre la página de ingreso de Stacker News.
    [Abrir Stacker News ↗]  (enlace a /signup?…&type=nostr, nueva pestaña)
 ② Paso 2: Copia este enlace y pégalo en Stacker News, en "Login with Nostr" → bunker.
    ┌ bunker://<pubkey>?relay=…&secret=… ┐ [Copiar enlace]
 ③ Paso 3: Vuelve a esta pestaña. Cuando Stacker News pida una firma, apruébala aquí.
 ℹ Nunca compartas tu nsec; el enlace bunker sí se puede pegar en Stacker News.
   No lo publiques: sirve para conectarse a tu firmante.
 [Bloquear]  (secundario: borra la clave de la memoria)
```

**(D) Tarjeta de pedido de firma**: aparece arriba de (C), con borde izquierdo azul de 6 px y fondo `#d1ecf1`
```
 h2  Stacker News quiere firmar esto
 Tipo:      Inicio de sesión (kind 22242)     ← nombre legible + número
 Propósito: Demostrar que eres dueño de tu npub para entrar a Stacker News.
 Contenido: (vacío)  | "texto…" (truncado a 280 caracteres)
 Hora:      hoy 18:04:12
 ▸ Ver evento completo (JSON)      (<details>)
 [ Aprobar y firmar ] (primario)   [ Rechazar ] (secundario)
```
- [P] Tabla de tipos (a confirmar con el experto en protocolo): 22242 → "Inicio de sesión"; 27235 → "Autorización HTTP"; 1 → "Nota pública"; 0 → "Perfil". Para cualquier otro tipo: "Tipo N (desconocido)" y un aviso de advertencia: "Este tipo de evento no es habitual para iniciar sesión. Si no lo esperabas, recházalo."
- Si llegan varios, se muestran en cola: "Pedido 1 de 2".

**(E) Historial y confirmación**
```
 ✓ (aviso éxito, role=status) Listo, vuelve a Stacker News.
 h2  Actividad reciente
  18:04:12  ✓ Firmaste: Inicio de sesión
  18:04:05  ● Stacker News pidió tu clave pública (respondido automáticamente)
  18:04:03  ● Stacker News se conectó
  18:03:10  ✕ Rechazaste: Nota pública
  ·  ping: "Stacker News verificó la conexión"
```
Errores globales: "Se perdió la conexión con el relay. Reintentando…" · "No se pudo enviar la firma. Vuelve a intentarlo en Stacker News." · "Se perdió la conexión con el servidor local. ¿Sigue corriendo app.py?"

## 4. Tokens CSS y componentes [P] (valores HEX [V] según §1)
```css
:root{
  --azul:#0f69b4; --azul-osc:#001c41; --rojo:#e22c2c;
  --texto:#212529; --texto-2:#4a4a4a; --fondo:#fff; --fondo-2:#f8f9fa; --borde:#dee2e6;
  --ok-t:#204349; --ok-f:#d5e3e5; --info-t:#145c68; --info-f:#d1ecf1;
  --warn-t:#212529; --warn-f:#fcf4d4; --err-t:#8c3d3d; --err-f:#ffe0e0;
  --foco:#0f69b4; --foco-osc:#ffbf47;
  --fuente:"gobCL","Roboto",system-ui,"Segoe UI",Arial,sans-serif;
  --mono:Consolas,"Liberation Mono",monospace;
  --t-base:1.125rem; --t-h1:2rem; --t-h2:1.5rem; --esp:1rem; --radio:4px; --ancho:44rem;
}
```
Componentes (un `app.css` de unas 150 líneas):
- `.cabecera`: fondo `--azul-osc`, con `::before` de 6 px y `linear-gradient(90deg,var(--azul) 50%,var(--rojo) 50%)`.
- `.tarjeta`: borde `--borde`, `--radio` y padding de 1.5 rem. `.tarjeta--pedido` lleva borde izquierdo de 6 px `--azul` y fondo `--info-f`.
- `.btn`: alto mínimo de 48 px y radio 0. `.btn--primario` (azul con texto blanco), `.btn--secundario` (blanco con borde y texto azul) y `.btn--peligro` (`--rojo` con texto blanco, solo para acciones destructivas).
- `.aviso--ok|info|warn|err`: borde izquierdo de 4 px y un ícono de texto.
- `.paso`: un círculo numerado azul de 2 rem más el texto. `.campo-copia` combina un input `readonly` en mono con el botón Copiar.
- `.estado`: punto de color más el texto ("Conectado" / "Reconectando…").

## 5. Microinteracciones (sin dependencias) [P]
- **Copiar**: usa `navigator.clipboard.writeText` (localhost cuenta como contexto seguro). El botón cambia a "Copiado ✓" durante 2 s y se anuncia por `aria-live`. Si falla, se selecciona el texto del input y aparece "Presiona Ctrl+C para copiar".
- **Pedido nuevo**: la tarjeta entra con un `@keyframes` de 300 ms (opacidad y desplazamiento de 8 px) y un borde destacado. El foco va al título.
- **Pestaña**: `document.title = "(1) Pedido pendiente · Firmante Nostr"` mientras haya pedidos, y se restaura al resolverlos. Así se ve aunque el usuario esté en la pestaña de Stacker News.
- **Sonido opcional**: casilla "Avisar con sonido" que hace un beep de WebAudio (oscilador de 880 Hz, 150 ms), sin archivos. El contexto de audio se activa con el clic de "Desbloquear", por la política de autoplay.
- **Relay**: el punto pasa de verde a ámbar con "Reconectando…". No hay modales.
