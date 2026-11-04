# Flujo completo: iniciar sesión en Stacker News con el firmante

> Los diagramas están en [Mermaid](https://mermaid.js.org/): GitHub y VS Code los dibujan automáticamente
> (en VS Code: vista previa de Markdown, `Ctrl+Shift+V`). El detalle técnico de cada paso está en [DISENO.md](DISENO.md).

## 1. Diagrama de secuencia (de punta a punta)

Participantes:
- **Tú**: la persona usuaria.
- **Página local**: http://localhost:8000.
- **Firmante**: `app.py` + `firmante.py`, con la clave en memoria.
- **Relay**: `wss://relay.damus.io`, que solo reenvía mensajes cifrados.
- **Stacker News (web)**: la página de SN en tu navegador, que usa la librería NDK.
- **Servidor SN**: el backend de stacker.news.

```mermaid
%%{init: {"theme":"dark","themeVariables":{"fontSize":"18px","signalTextColor":"#ffffff","signalColor":"#9fd0ff","actorBkg":"#0f69b4","actorBorder":"#9fd0ff","actorTextColor":"#ffffff","actorLineColor":"#9fd0ff","noteBkgColor":"#fcf4d4","noteTextColor":"#001c41","noteBorderColor":"#ffbf47","labelBoxBkgColor":"#0f69b4","labelBoxBorderColor":"#9fd0ff","labelTextColor":"#ffffff","loopTextColor":"#ffffff","sequenceNumberColor":"#001c41"},"sequence":{"messageFontSize":18,"actorFontSize":18,"noteFontSize":18,"wrap":true,"width":230}}}%%
sequenceDiagram
    autonumber
    actor U as Usuario
    participant P as Pagina local
    participant F as Firmante app.py
    participant R as Relay damus
    participant W as Stacker News web
    participant S as Servidor SN

    Note over U,S: FASE 1 - Preparar el firmante
    U->>F: python app.py
    U->>P: Abre localhost 8000
    P->>F: Abre canal de avisos SSE
    alt Primera vez
        U->>P: Crea clave nueva o pega su nsec, y define contraseña
        P->>F: POST api crear
        F->>F: Cifra la clave con scrypt y ChaCha20-Poly1305 y la guarda en data
        F-->>P: nsec una sola vez para respaldarla, solo si se generó
    else Ya tenía clave
        U->>P: Escribe la contraseña
        P->>F: POST api desbloquear
        F->>F: Descifra la clave y la deja en memoria
    end
    F->>R: Se conecta y se suscribe a mensajes kind 24133 para su clave
    R-->>F: Suscripción activa
    F-->>P: Aviso SSE con npub y enlace bunker

    Note over U,S: FASE 2 - Conectar Stacker News con el firmante
    U->>W: Abre la página de login Nostr de SN
    U->>P: Copia el enlace bunker
    U->>W: Lo pega en Connect with token y pulsa Login
    W->>S: Pide un desafío de login
    S-->>W: challenge k1 de un solo uso
    W->>W: NDK crea una clave de cliente temporal
    W->>R: connect con el secret, cifrado NIP-04
    R->>F: Reenvía
    F->>F: Verifica firma, descifra y compara el secret
    F->>R: ack, cifrado NIP-04
    R->>W: Reenvía
    F->>F: Autoriza al cliente y cambia el secret
    F-->>P: Aviso SSE - un cliente se conectó, enlace bunker nuevo
    W->>R: get_public_key
    R->>F: Reenvía
    F->>R: Clave pública, no es secreta
    R->>W: Reenvía

    Note over U,S: FASE 3 - Firmar el inicio de sesión con tu aprobación
    W->>R: sign_event kind 27235 con challenge, sitio y método GET
    R->>F: Reenvía
    F->>F: Revisa que sea un login kind 27235, si no lo bloquea
    F-->>P: Aviso SSE - pedido pendiente, expira en 2 min
    P->>U: Tarjeta Pedido de inicio de sesión en STACKER.NEWS
    Note over W: SN espera sin límite. A los 10 s muestra una sugerencia, es normal
    alt Apruebas
        U->>P: Clic en Aprobar e iniciar sesión
        P->>F: POST api responder, aprobar
        F->>F: Recalcula el id del evento y lo firma con Schnorr
        F->>R: Evento firmado, cifrado NIP-04
        R->>W: Reenvía
        W->>S: Inicia sesión con el evento firmado
        S->>S: Verifica la firma con tu npub y su challenge
        S-->>W: Sesión iniciada
        W-->>U: Ya estás dentro de Stacker News
        F-->>P: Aviso SSE - Listo, vuelve a Stacker News
    else Rechazas o pasan 2 minutos
        U->>P: Clic en Rechazar o no hace nada
        P->>F: POST api responder, rechazar
        F->>R: error rechazado por el usuario
        R->>W: Reenvía
        W-->>U: SN muestra error de login
        F-->>P: Aviso SSE - historial Rechazado
    end
```

## 2. Qué revisa el firmante con cada mensaje que llega

```mermaid
flowchart TD
    A["Llega un evento kind 24133<br/>desde el relay"] --> B{"¿Va dirigido a mi clave,<br/>id y firma válidos,<br/>no repetido?"}
    B -- No --> X1["Se ignora en silencio"]
    B -- Sí --> C{"¿El contenido trae '?iv='?"}
    C -- Sí --> D1["Descifrar con NIP-04<br/>(lo que usa Stacker News hoy)"]
    C -- No --> D2["Descifrar con NIP-44<br/>(lo que pide la spec)"]
    D1 --> E{"¿Se pudo descifrar?"}
    D2 --> E
    E -- No --> X1
    E -- Sí --> M{"¿Qué método pide?"}

    M -- connect --> K{"¿El secret coincide?"}
    K -- Sí --> K1["Responder 'ack'<br/>autorizar cliente<br/>cambiar el secret"]
    K -- No --> XE["Responder error"]

    M -- ping --> PG["Responder 'pong'"]

    M -- "get_public_key / sign_event" --> AU{"¿Cliente autorizado?"}
    AU -- No --> XE
    AU -- "Sí, get_public_key" --> GP["Responder la clave pública"]
    AU -- "Sí, sign_event" --> L{"¿Es un login?<br/>kind 27235 con tags u y method"}
    L -- No --> XB["Bloqueado automáticamente<br/>(notas, perfil, zaps, etc.)<br/>se anota en el historial"]
    L -- Sí --> T["Tarjeta en la página<br/>con el SITIO en grande"]
    T --> Q{"¿Qué decides?<br/>(máximo 2 minutos)"}
    Q -- Aprobar --> OK["Firmar y responder<br/>con el evento firmado"]
    Q -- "Rechazar o expira" --> XE

    M -- otro --> XE2["Responder error:<br/>método no soportado"]

    K1 --> RESP["Respuesta cifrada con el<br/>mismo esquema del pedido<br/>y enviada al relay"]
    PG --> RESP
    GP --> RESP
    OK --> RESP
    XE --> RESP
    XB --> RESP
    XE2 --> RESP
```

## 3. Glosario rápido

| Término | Qué es |
|---|---|
| **nsec / npub** | Tu clave secreta y tu clave pública, en formato legible. La npub se puede compartir; la nsec, nunca. |
| **Relay** | Servidor público que reenvía mensajes. Solo ve mensajes cifrados. |
| **bunker://** | Enlace que le dice a una app dónde está tu firmante (tu npub, el relay y un secret). |
| **kind 24133** | Tipo de evento que transporta los mensajes NIP-46 entre la app y el firmante. |
| **kind 27235** | Tipo de evento de login HTTP (NIP-98). Es lo único que este firmante acepta firmar. |
| **challenge** | Código de un solo uso que inventa Stacker News. Evita que una firma vieja sirva para entrar de nuevo. |
| **NIP-04 / NIP-44** | Dos formas de cifrar los mensajes. SN usa NIP-04 hoy; la spec pide NIP-44. Soportamos las dos. |
| **SSE** | Canal por el que el programa local avisa a la página de las novedades, sin preguntar a cada rato. |
