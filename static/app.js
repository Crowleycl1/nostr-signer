// Página del firmante. Recibe el estado por SSE (/api/eventos) y manda los clics por POST.
// Reglas (DISENO.md §5 y §7): todo texto externo se pinta con textContent (nunca innerHTML),
// no se redibuja todo en cada evento (para no perder el foco ni lo escrito) y el foco nunca va
// al botón Aprobar.
"use strict";

const TOKEN = document.querySelector('meta[name="token"]').content;
const TITULO = "Firmante Nostr";
const $ = (id) => document.getElementById(id);

const ERRORES = {
  contrasena_incorrecta: "La contraseña no es correcta.",
  contrasena_corta: "La contraseña debe tener al menos 8 caracteres.",
  contrasenas_distintas: "Las contraseñas no coinciden.",
  nsec_vacio: "Pega tu nsec.",
  nsec_invalido: "Esa clave no es un nsec válido. Revisa que empiece con nsec1 y que esté completa.",
  ya_existe_clave: "Ya hay una clave guardada. Recarga la página para desbloquearla.",
  sin_clave: "No hay una clave guardada. Recarga la página.",
  archivo_invalido: "El archivo data/clave.json está dañado. Bórralo e importa tu nsec de nuevo.",
  pedido_expirado: "Este pedido ya no está pendiente: expiró o ya se respondió.",
  token_invalido: "La app se reinició y esta página quedó desactualizada.",
  sin_conexion: "No hay conexión con el programa local. ¿Sigue abierta la ventana de app.py?",
};

const HISTORIAL = {
  conectado: () => "Un cliente se conectó (la app donde pegaste el enlace)",
  clave_publica: () => "Le entregaste tu clave pública: es normal, no es secreta",
  firmado: (d) => `Firmaste el inicio de sesión en ${d}`,
  rechazado: (d) => `Rechazado: inicio de sesión en ${d}`,
  expirado: (d) => `Expiró sin respuesta: inicio de sesión en ${d}`,
  bloqueado: (d) => `Bloqueado: no es un inicio de sesión (kind ${d})`,
};

let ultimo = null;              // último estado recibido
let faseVisible = null;         // "a" | "a2" | "b" | "c"
let respaldoPendiente = false;  // true mientras se muestra la nsec recién generada (A2)
let pedidoActual = null;        // { id, vence } de la tarjeta visible
let reloj = null;
let historialPintado = "";
let fuente = null;

// ---------- utilidades ----------
function texto(id, valor) {
  const el = $(id);
  if (el.textContent !== valor) el.textContent = valor; // solo si cambió: no molesta al lector de pantalla
}

function mostrarError(el, codigo) {
  el.textContent = ERRORES[codigo] || "Ocurrió un error inesperado.";
  el.hidden = false;
}

function avisoGlobal(codigo) {
  const caja = $("aviso-global");
  if (!codigo) { caja.hidden = true; return; }
  if (!caja.hidden && caja.dataset.codigo === "token_invalido") return; // ese aviso manda
  caja.dataset.codigo = codigo;
  texto("aviso-global-texto", codigo === "reconectando"
    ? "Reconectando con el programa local…" : ERRORES[codigo]);
  $("btn-recargar").hidden = codigo !== "token_invalido";
  caja.hidden = false;
}

async function api(ruta, datos) {
  let r;
  try {
    r = await fetch(ruta, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": TOKEN },
      body: JSON.stringify(datos),
    });
  } catch {
    avisoGlobal("sin_conexion");
    throw new Error("sin_conexion");
  }
  let cuerpo = {};
  try { cuerpo = await r.json(); } catch { /* respuesta sin JSON */ }
  if (r.status === 403) avisoGlobal("token_invalido");
  if (!r.ok) throw new Error(cuerpo.error || "desconocido");
  return cuerpo;
}

// ---------- SSE ----------
function conectar() {
  fuente = new EventSource("/api/eventos?token=" + encodeURIComponent(TOKEN));
  fuente.addEventListener("estado", (ev) => {
    if ($("aviso-global").dataset.codigo !== "token_invalido") avisoGlobal(null);
    ultimo = JSON.parse(ev.data);
    pintar(ultimo);
  });
  fuente.onerror = () => {
    if (fuente.readyState === EventSource.CLOSED) {
      // EventSource no reintenta si el servidor respondió con error: vemos si fue un 403 (token viejo).
      fuente.close();
      revisarServidor();
    } else {
      avisoGlobal("reconectando"); // se cortó: EventSource reintenta solo
    }
  };
}

async function revisarServidor() {
  const corte = new AbortController();
  try {
    const r = await fetch("/api/eventos?token=" + encodeURIComponent(TOKEN), { signal: corte.signal });
    corte.abort();
    if (r.status === 403) { avisoGlobal("token_invalido"); return; }
  } catch {
    avisoGlobal("sin_conexion");
  }
  setTimeout(conectar, 3000);
}

// ---------- pintar el estado ----------
function pintar(e) {
  $("cargando").hidden = true;
  const fase = respaldoPendiente ? "a2" : { sin_clave: "a", bloqueado: "b", listo: "c" }[e.fase];
  cambiarFase(fase);
  if (fase !== "c") return;
  pintarRelay(e.relay);
  texto("npub", e.npub || "");
  pintarBunker(e.bunker);
  $("enlace-nuevo").hidden = !e.enlace_nuevo;
  pintarPedido(e.pendiente);
  pintarHistorial(e.historial);
  $("listo").hidden = Boolean(e.pendiente) || !(e.historial[0] && e.historial[0].tipo === "firmado");
}

function cambiarFase(fase) {
  if (fase === faseVisible) return;
  faseVisible = fase;
  for (const f of ["a", "a2", "b", "c"]) $("estado-" + f).hidden = f !== fase;
  $("titulo-" + fase).focus();
}

function pintarRelay(relay) {
  if (!relay) return;
  const host = new URL(relay.url).host;
  const el = $("relay-estado");
  const ok = relay.estado === "conectado";
  const msj = ok ? `● Conectado a ${host}`
    : `⟳ Reconectando con ${host}…` + (relay.reintento_en ? ` (reintento en ${relay.reintento_en} s)` : "");
  texto("relay-estado", msj);
  el.className = "relay " + (ok ? "relay-ok" : "relay-mal");
  $("relay-caido").hidden = ok;
}

function pintarBunker(bunker) {
  $("bunker").hidden = !bunker;
  $("btn-copiar-bunker").hidden = !bunker;
  $("bunker-espera").hidden = Boolean(bunker);
  texto("bunker", bunker || "");
}

function pintarPedido(p) {
  const zona = $("zona-pedido");
  if (!p) {
    if (pedidoActual) {
      pedidoActual = null;
      clearInterval(reloj);
      zona.replaceChildren();
      document.title = TITULO;
      $("titulo-c").focus(); // el foco no se pierde al desaparecer la tarjeta
    }
    return;
  }
  if (pedidoActual && pedidoActual.id === p.id) return; // misma tarjeta: no se toca
  // La cuenta regresiva la lleva un reloj local a partir de expira_en (segundos que quedan).
  pedidoActual = { id: p.id, vence: Date.now() + p.expira_en * 1000 };

  const nodo = $("plantilla-pedido").content.cloneNode(true);
  const campo = (n) => nodo.querySelector(`[data-campo="${n}"]`);
  campo("sitio").textContent = p.sitio;
  for (const aviso of p.avisos) {
    const li = document.createElement("li");
    li.textContent = aviso;
    campo("avisos").append(li);
  }
  campo("cliente").textContent = p.cliente;
  campo("hora").textContent = new Date(p.created_at * 1000).toLocaleTimeString("es-CL");
  campo("kind").textContent = String(p.evento.kind);
  campo("metodo").textContent = p.metodo_http || "";
  campo("challenge").textContent = p.challenge_corto;
  campo("json").textContent = JSON.stringify(p.evento, null, 2);
  const error = campo("error");
  const botones = nodo.querySelectorAll("[data-accion]");
  for (const b of botones) {
    b.addEventListener("click", async () => {
      botones.forEach((x) => { x.disabled = true; });
      try {
        await api("/api/responder", { id: p.id, aprobar: b.dataset.accion === "aprobar" });
      } catch (err) {
        mostrarError(error, err.message);
        botones.forEach((x) => { x.disabled = false; });
      }
    });
  }
  zona.replaceChildren(nodo);
  document.title = "(1) Pedido pendiente";
  $("titulo-pedido").focus(); // al título, NUNCA al botón Aprobar (evita aprobar con un Enter distraído)
  clearInterval(reloj);
  contar();
  reloj = setInterval(contar, 1000);
}

function contar() {
  if (!pedidoActual) return;
  const s = Math.max(0, Math.round((pedidoActual.vence - Date.now()) / 1000));
  const el = document.querySelector('#zona-pedido [data-campo="quedan"]');
  if (el) el.textContent = `Quedan ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function pintarHistorial(historial) {
  const clave = JSON.stringify(historial);
  if (clave === historialPintado) return;
  historialPintado = clave;
  const lista = $("historial");
  lista.replaceChildren(...historial.map((h) => {
    const li = document.createElement("li");
    const hora = document.createElement("span");
    hora.className = "hora";
    hora.textContent = new Date(h.ts * 1000).toLocaleTimeString("es-CL") + " · ";
    const describir = HISTORIAL[h.tipo] || (() => h.tipo);
    li.append(hora, describir(h.detalle));
    return li;
  }));
  $("historial-vacio").hidden = historial.length > 0;
}

// ---------- formularios ----------
function alSalirConNsec(ev) { ev.preventDefault(); ev.returnValue = ""; }

$("form-crear").addEventListener("change", () => {
  $("campo-nsec").hidden = $("form-crear").modo.value !== "importar";
});

$("form-crear").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const err = $("error-a");
  err.hidden = true;
  const importar = f.modo.value === "importar";
  const c1 = $("contrasena1").value;
  const nsec = $("nsec").value.trim();
  if (importar && !nsec) return mostrarError(err, "nsec_vacio");
  if (c1.length < 8) return mostrarError(err, "contrasena_corta");
  if (c1 !== $("contrasena2").value) return mostrarError(err, "contrasenas_distintas");
  const boton = $("btn-crear");
  boton.disabled = true;
  boton.textContent = "Guardando…";
  try {
    const r = await api("/api/crear", importar ? { contrasena: c1, nsec } : { contrasena: c1 });
    f.reset();
    $("campo-nsec").hidden = true;
    if (r.nsec) { // solo si se generó: mostrarla UNA vez para respaldarla (A2)
      respaldoPendiente = true;
      $("nsec-mostrada").textContent = r.nsec;
      window.addEventListener("beforeunload", alSalirConNsec);
      cambiarFase("a2");
    }
  } catch (e) {
    mostrarError(err, e.message);
  } finally {
    boton.disabled = false;
    boton.textContent = "Guardar y continuar";
  }
});

$("respaldada").addEventListener("change", (ev) => {
  $("btn-respaldada").disabled = !ev.target.checked;
});

$("btn-respaldada").addEventListener("click", () => {
  respaldoPendiente = false;
  $("nsec-mostrada").textContent = ""; // se borra de la página
  $("respaldada").checked = false;
  window.removeEventListener("beforeunload", alSalirConNsec);
  if (ultimo) pintar(ultimo);
});

$("form-desbloquear").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("error-b");
  err.hidden = true;
  const boton = $("btn-desbloquear");
  boton.disabled = true;
  boton.textContent = "Desbloqueando…";
  try {
    await api("/api/desbloquear", { contrasena: $("contrasena").value });
    $("contrasena").value = "";
  } catch (e) {
    mostrarError(err, e.message);
    $("contrasena").select();
  } finally {
    boton.disabled = false;
    boton.textContent = "Desbloquear";
  }
});

$("btn-recargar").addEventListener("click", () => location.reload());

// ---------- copiar ----------
for (const boton of document.querySelectorAll("[data-copiar]")) {
  boton.addEventListener("click", async () => {
    const origen = $(boton.dataset.copiar);
    const aviso = boton.parentElement.querySelector(".copiado");
    try {
      await navigator.clipboard.writeText(origen.textContent);
      aviso.textContent = "Copiado ✓";
    } catch {
      // sin permiso de portapapeles: dejamos el texto seleccionado para copiarlo a mano
      const rango = document.createRange();
      rango.selectNodeContents(origen);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(rango);
      aviso.textContent = "Presiona Ctrl+C";
    }
    clearTimeout(aviso.temporizador);
    const dura = aviso.textContent === "Copiado ✓" ? 2000 : 8000; // "Ctrl+C" necesita más tiempo
    aviso.temporizador = setTimeout(() => { aviso.textContent = ""; }, dura);
  });
}

conectar();
