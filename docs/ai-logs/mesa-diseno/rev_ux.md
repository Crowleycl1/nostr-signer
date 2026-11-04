# Revisión cruzada UX/UI (ronda 2)

Reviso 1_protocolo.md y 2_seguridad.md contra mi 3_ux.md. Severidades: **B** = bloqueante, **I** = importante, **m** = menor.

## Hallazgos

**1. [B] La CSP `default-src 'self'` bloquea el token si va en un `<script>` inline.**
Seguridad dice "token inyectado en `index.html`". Si se inyecta como `<script>window.TOKEN=…</script>`, la propia CSP lo bloquea y la página queda muerta sin ningún error visible.
→ Cambio: inyectarlo como `<meta name="token" content="…">` y leerlo en `app.js` con `document.querySelector('meta[name=token]').content`. Tampoco se puede usar `style="…"` ni `onclick=` inline: todo va con clases en `app.css` y con `addEventListener`.

**2. [B] Con un secret de un solo uso y un cliente único, el usuario no puede volver a iniciar sesión.**
NDK crea una clave de cliente nueva en cada intento. Si el primer intento falla, expira o el usuario cierra sesión en SN, el siguiente `connect` llega con otra pubkey y el secret ya está usado. El login falla sin explicación y la única salida sería reiniciar `app.py`.
→ Cambio de backend: después de un `connect` válido, **rotar el secret automáticamente** y que el nuevo `bunker://` aparezca de inmediato en `/api/estado`. Un `connect` con el secret nuevo **reemplaza** al cliente anterior: gana el último. Agregar `POST /api/nuevo_bunker` para rotarlo a mano.
→ Texto en el paso 2, después del primer uso: «Este enlace es nuevo. El anterior ya se usó y no sirve otra vez. Si vuelves a iniciar sesión (otro navegador, o después de cerrar sesión), copia este.» Al reemplazar, el historial dice: «Se conectó una app nueva y reemplazó a la anterior.»

**3. [I] La tarjeta D debe describir el kind 27235 real.**
El 22242 de mi propuesta y del `sn_falso.py` está mal: debe ser 27235. La tarjeta muestra el dominio que sale de la tag `u`.
```
 h2  stacker.news quiere que inicies sesión
 Qué es:   Un "sello" que demuestra que eres dueño de esta clave.
           No publica nada, no gasta dinero y no entrega tu nsec.
           Solo abre tu sesión en Stacker News esta vez.
 Sitio:    https://stacker.news          (tag u)
 Hora:     hoy 18:04:12 · Quedan 1:45 para responder
 ▸ Detalles técnicos (kind 27235, challenge, JSON completo)
 [ Aprobar e iniciar sesión ]   [ Rechazar ]
```
Se reconoce como login cuando `kind == 27235`, `content == "Stacker News Authentication"` y la tag `method` es `GET`. Para cualquier otro caso (otro kind, o una `u` que no sea `https://stacker.news`), el título pasa a ser «Una app pide firmar un evento tipo N», con el aviso «Esto no es un inicio de sesión normal. Si no lo esperabas, recházalo.» y el contenido truncado. El challenge va solo en Detalles, porque es ruido para quien está aprendiendo.

**4. [I] La expiración de 120 s choca con NDK, que espera sin límite.**
Cuando expira, SN recibe un error y el usuario no sabe por qué. Además, SN muestra una sugerencia a los 10 s, mucho antes.
→ Mientras haya pedido, la tarjeta muestra la cuenta regresiva «Quedan 1:45 para responder». Se actualiza con el polling y se anuncia por lector de pantalla **solo** a los 30 s, no cada segundo.
→ Al expirar, el historial dice: «Expiró sin respuesta (2 min). Vuelve a Stacker News, pide entrar de nuevo y copia el enlace bunker nuevo.» Esto depende del hallazgo 2.
→ Nuevo paso 3: «Paso 3: cuando pegues el enlace, vuelve a esta pestaña y aprueba. Stacker News esperará; si allí aparece un aviso a los pocos segundos, es normal, solo vuelve aquí.»

**5. [I] Faltan campos en `GET /api/estado` para dibujar la UI.**
Hay que agregar:
- `historial: [{ts, tipo: "conectado"|"clave_publica"|"ping"|"firmado"|"rechazado"|"expirado"|"reemplazado", detalle}]`, con un máximo de unas 20 entradas;
- `relay_url`;
- `relay_reintento_en` (en segundos);
- `bunker_usado: bool`;
- `cliente_desde` (ts);
- y, en cada pendiente, `expira_en` en **segundos restantes** en vez de un ts absoluto, para no depender del reloj del navegador.

Las respuestas de error de los POST deben llevar códigos estables (`{"error":"contrasena_incorrecta"|"contrasena_corta"|"nsec_invalido"|"ya_existe_clave"}`) que la UI traduce a texto. El backend no debería mandar frases.

**6. [I] El polling cada 1 s alcanza, pero solo si no re-dibuja todo.**
La latencia de 1 s es irrelevante frente a una aprobación humana, porque SN espera. El riesgo es otro: re-renderizar el DOM completo cada segundo hace perder el foco, borra lo escrito en la contraseña y hace que el lector de pantalla repita contenido.
→ Cambio: comparar con el estado anterior. Solo se crea la tarjeta cuando aparece un `id` pendiente nuevo, solo se agregan las entradas nuevas al historial y solo se toca el texto del relay si cambió. En las fases `sin_clave` y `bloqueado` no hace falta polling. Nota: si la pestaña queda oculta varios minutos, Chrome frena los timers a ~1/min, así que el título «(1) Pedido pendiente» puede tardar. Se acepta y se anota en el README.

**7. [I] Errores visibles de token, Host u Origin, y del servidor caído.**
El token es nuevo en cada arranque. Si se reinicia `app.py` con la pestaña abierta, todo responde 403 y el polling falla en silencio.
- 403 → aviso de error: «La app se reinició y esta página quedó desactualizada.» con el botón [Recargar página].
- `fetch` falla (red) → «No hay conexión con el programa local. ¿Sigue abierta la ventana de app.py? Reintentando…».
- Host rechazado: el usuario no ve la página. Que `app.py` imprima al arrancar «Abre http://localhost:8000». El README usa la misma URL.

**8. [I] Relay caído o reconectando.**
Estado en la cabecera del panel, con `role="status"`:
- «● Conectado a relay.damus.io»;
- «⟳ Reconectando con relay.damus.io… (reintento en 8 s)».

Si hay reconexión, va un aviso de advertencia: «Mientras no haya conexión, Stacker News no puede llegar a tu firmante. Si estabas iniciando sesión, espera "Conectado" y vuelve a intentarlo en Stacker News.» Los 24133 son efímeros, así que lo enviado durante la caída se pierde. Durante la reconexión no se oculta el bunker, pero el botón Copiar sigue activo, con el aviso.

**9. [I] Contraseña olvidada.**
En (B), un enlace secundario lleva a «Olvidé mi contraseña» y de ahí a un `confirm()` nativo, que es accesible y no requiere código extra:
«Esto borra la clave guardada en este equipo. No hay forma de recuperarla sin la contraseña. Solo podrás volver a usar tu cuenta si tienes tu nsec respaldado; si no, en Stacker News serás un usuario nuevo. ¿Borrar la clave?»
Después se pasa a (A) con la opción «Ya tengo una clave» preseleccionada. Error de desbloqueo: «Contraseña incorrecta.» Mientras corre scrypt (unos 0,3 s), el botón muestra «Desbloqueando…» y queda deshabilitado.

**10. [m] «Stacker News se conectó» es un supuesto.**
NDK no envía metadata en `connect` (`params = ["", secret]`), así que no sabemos que es SN. Como el usuario solo le dio el enlace a SN, el texto puede ser: «Se conectó la app donde pegaste el enlace (Stacker News).» `get_public_key` → «Le entregaste tu clave pública (npub). Esto es normal y no es secreto.» `ping` → no va al historial, para no llenarlo de ruido.

**11. [m] Confirmación (E).**
Tras aprobar un 27235: «✓ Listo. Vuelve a la pestaña de Stacker News: ya deberías haber entrado.» Tras rechazar: «Rechazaste el pedido. Stacker News no inició sesión.»

## Recortes a mi propia propuesta (~3 h)
- **Fuera:** el sonido WebAudio y su casilla. Basta el título de pestaña «(1) Pedido pendiente».
- **Fuera:** el botón «Bloquear», la animación `@keyframes` (queda solo el borde destacado), la cola «Pedido 1 de 2» (SN pide una firma por login; una lista simple sirve), el enlace «Saltar al contenido» (hay muy poco contenido) y la tabla de kinds (solo «login 27235» o «desconocido»).
- **Queda:** franja y tokens, texto de 18 px, foco visible, `aria-live` y foco en el título de la tarjeta, Copiar con «Copiado ✓», respaldo del nsec una sola vez, pasos 1-3, tarjeta D, historial, y los avisos de relay y de error de los hallazgos 7 y 8.
- **Para seguridad:** el máximo de 5 pendientes no necesita UI; si hay más, se rechazan en silencio con un error RPC.
