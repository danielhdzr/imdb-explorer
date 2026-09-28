let paginaActual = 1;

const form = document.getElementById("filtros");
const tbody = document.querySelector("#resultados tbody");
const estado = document.getElementById("estado");
const paginacion = document.getElementById("paginacion");

const modalFondo = document.getElementById("modal-fondo");
const modalContenido = document.getElementById("modal-contenido");

// --- Carga inicial de catálogos (géneros y tipos) --------------------------

async function cargarCatalogos() {
  const [generos, tipos] = await Promise.all([
    fetch("/api/generos").then(r => r.json()),
    fetch("/api/tipos").then(r => r.json()),
  ]);

  const selGenero = document.getElementById("genero");
  generos.forEach(g => {
    const opt = document.createElement("option");
    opt.value = g;
    opt.textContent = g;
    selGenero.appendChild(opt);
  });

  const selTipo = document.getElementById("tipo");
  tipos.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    selTipo.appendChild(opt);
  });
}

// --- Búsqueda ---------------------------------------------------------------

function leerFiltros() {
  const params = new URLSearchParams();
  const campos = ["titulo", "tipo", "genero", "director", "actor", "rating_min", "year_min", "year_max"];
  campos.forEach(id => {
    const valor = document.getElementById(id).value.trim();
    if (valor) params.set(id, valor);
  });
  params.set("page", paginaActual);
  return params;
}


async function buscar() {
  estado.textContent = "Buscando...";
  tbody.innerHTML = "";

  const params = leerFiltros();
  const resp = await fetch(`/api/peliculas?${params.toString()}`);

  if (!resp.ok) {
    estado.textContent = "Ocurrió un error al buscar.";
    return;
  }

  const data = await resp.json();
  estado.textContent = `${data.total.toLocaleString()} resultado(s)`;

  data.resultados.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(r.titulo)}</td>
      <td>${r.anio ?? "—"}</td>
      <td>${r.tipo ?? "—"}</td>
      <td>${(r.generos || []).join(", ") || "—"}</td>
      <td>${r.rating ?? "—"}</td>
      <td>${(r.directores || []).join(", ") || "—"}</td>
    `;
    tr.addEventListener("click", () => verDetalle(r.tconst));
    tbody.appendChild(tr);
  });

  renderPaginacion(data.page, data.total_pages);
}

function renderPaginacion(page, totalPages) {
  paginacion.innerHTML = "";

  const btnAnterior = document.createElement("button");
  btnAnterior.textContent = "← Anterior";
  btnAnterior.disabled = page <= 1;
  btnAnterior.addEventListener("click", () => {
    paginaActual = page - 1;
    buscar();
  });

  const span = document.createElement("span");
  span.textContent = `Página ${page} de ${totalPages}`;

  const btnSiguiente = document.createElement("button");
  btnSiguiente.textContent = "Siguiente →";
  btnSiguiente.disabled = page >= totalPages;
  btnSiguiente.addEventListener("click", () => {
    paginaActual = page + 1;
    buscar();
  });

  paginacion.append(btnAnterior, span, btnSiguiente);
}

// --- Detalle (modal) ---------------------------------------------------------

async function verDetalle(tconst) {
  const resp = await fetch(`/api/pelicula/${tconst}`);
  if (!resp.ok) return;
  const d = await resp.json();

  const reparto = (d.reparto || [])
    .slice(0, 15)
    .map(p => `${escapeHtml(p.nombre)}${p.personaje ? ` — ${escapeHtml(p.personaje)}` : ""}`)
    .join("<br>");

  modalContenido.innerHTML = `
    <h2>${escapeHtml(d.titulo)} ${d.anio_inicio ? `(${d.anio_inicio})` : ""}</h2>
    ${d.titulo_original && d.titulo_original !== d.titulo ? `<p class="etiqueta">Título original: ${escapeHtml(d.titulo_original)}</p>` : ""}

    <div class="seccion">
      <span class="etiqueta">Tipo:</span> ${d.tipo ?? "—"} &nbsp;·&nbsp;
      <span class="etiqueta">Duración:</span> ${d.duracion_min ? d.duracion_min + " min" : "—"} &nbsp;·&nbsp;
      <span class="etiqueta">Rating:</span> ${d.rating ?? "—"} (${(d.votos ?? 0).toLocaleString()} votos)
    </div>

    <div class="seccion">
      <span class="etiqueta">Géneros:</span> ${(d.generos || []).join(", ") || "—"}
    </div>

    <div class="seccion">
      <span class="etiqueta">Director(es):</span> ${(d.directores || []).join(", ") || "—"}
    </div>

    <div class="seccion">
      <span class="etiqueta">Guionista(s):</span> ${(d.guionistas || []).join(", ") || "—"}
    </div>

    <div class="seccion">
      <span class="etiqueta">Reparto principal:</span><br>${reparto || "—"}
    </div>
  `;

  modalFondo.classList.remove("oculto");
}

document.getElementById("cerrar-modal").addEventListener("click", () => {
  modalFondo.classList.add("oculto");
});
modalFondo.addEventListener("click", (e) => {
  if (e.target === modalFondo) modalFondo.classList.add("oculto");
});

// --- Utilidad ----------------------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// --- Init ----------------------------------------------------------------------

form.addEventListener("submit", (e) => {
  e.preventDefault();
  paginaActual = 1;
  buscar();
});

cargarCatalogos().then(buscar);
