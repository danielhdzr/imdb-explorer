# IMDb Explorer

Sitio web para consultar IMDb con filtros por título, tipo, género,
director, actor/actriz, rating mínimo y rango de años. Proyecto de
portafolio: backend en FastAPI con SQL dinámico sobre PostgreSQL,
frontend en HTML/JS plano, todo empaquetado en Docker.

## Qué hace

- Búsqueda de títulos con coincidencia parcial por nombre.
- Filtros combinables: tipo de título, género, director, actor/actriz,
  rating mínimo, rango de años.
- Resultados paginados (20 por página), ordenados por popularidad
  (número de votos).
- Vista de detalle por título: datos básicos, reparto principal,
  director(es) y guionista(s).

## Stack

| Capa       | Tecnología                                   |
|------------|-----------------------------------------------|
| Backend    | FastAPI (Python), consultas SQL dinámicas     |
| Driver DB  | psycopg 3 + psycopg_pool (pool de conexiones) |
| Base       | PostgreSQL en Neon (plan gratuito)            |
| Frontend   | HTML + CSS + JavaScript vanilla               |
| Empaquetado| Docker / docker-compose (servicio `web`)      |

## Origen de los datos

Los datos vienen de los datasets públicos de IMDb
(<https://datasets.imdbws.com/>). `cargar_datos.py` los descarga en
streaming, filtra cada fila al vuelo y la manda a la base con `COPY`:
**nada se escribe en disco local**.

### Por qué un subconjunto

La base completa (~250M filas, ~27 GB con índices) no cabe en ningún plan
gratuito de Postgres administrado. Para caber en los 0.5 GB de Neon:

- Solo títulos con **≥ 200 votos** (~170k). Cubre prácticamente todo lo
  que alguien buscaría; el resto son títulos casi sin actividad.
- Sin **episodios sueltos de series** (`tvEpisode`). Las series sí están.
- Sin `title_akas` ni `title_episode`, que el sitio no usaba.
- Del reparto solo se guardan `actor`, `actress` y `self`; directores y
  guionistas salen de `title.crew`.
- Personas: solo las que aparecen en algún título cargado, y solo su
  nombre.
- IDs como `integer` (`tt0133093` → `133093`) en vez de texto: ocupan
  menos y comparan más rápido. La API los sigue exponiendo como `tt…`.

Resultado: ~340 MB con índices. El umbral se puede cambiar con
`python cargar_datos.py --min-votos N`.

### Esquema

```
titles            (id, title_type, primary_title, original_title,
                    start_year, end_year, runtime_minutes, genres[],
                    average_rating, num_votes)
people            (id, primary_name)
title_directors   (title_id, person_id)
title_writers     (title_id, person_id)
title_principals  (title_id, ordering, person_id, category, characters)
```

El rating y los votos van dentro de `titles` (antes eran una tabla
aparte): todos los títulos cargados tienen rating, y así ordenar y
filtrar por ellos no requiere un `JOIN`.

Índices:

- `titles.primary_title` y `people.primary_name`: GIN de trigramas
  (`pg_trgm`), para que `ILIKE '%texto%'` no recorra la tabla completa.
- `titles.genres`: GIN, usado por `genres @> ARRAY['Drama']`.
- `titles (num_votes DESC, id)`: el orden por defecto de los resultados.
- `person_id` en `title_directors` y `title_principals`: para ir de una
  persona a sus títulos.

## Cómo se arma la búsqueda

Cada búsqueda es **una sola consulta** a la base (importante con la base
en la nube, donde cada ida y vuelta cuesta decenas de milisegundos):

```sql
WITH pagina AS (
    SELECT t.*, count(*) OVER () AS total
    FROM titles t
    WHERE <filtros>
    ORDER BY t.num_votes DESC, t.id
    LIMIT 20 OFFSET ...
)
SELECT pagina.*, ARRAY(<directores del título>) FROM pagina
```

- `count(*) OVER ()` trae el total junto con la página, sin una segunda
  consulta de conteo.
- Los directores se buscan solo para las 20 filas de la página.
- Los filtros se agregan solo si vienen llenos. Director y actor son
  semi-joins (`t.id IN (SELECT ... WHERE primary_name ILIKE ...)`) en vez
  de `JOIN` + `DISTINCT`: primero se encuentran las personas con el índice
  de trigramas y luego sus títulos por índice.
- El texto del usuario se escapa (`%`, `_`) antes del `ILIKE`.

El detalle de un título también es una sola consulta (antes eran cuatro),
con directores, guionistas y reparto como subconsultas.

En el frontend, una búsqueda nueva cancela la anterior
(`AbortController`) para que una respuesta lenta no pise a una más
reciente, y se muestra el tiempo que tardó cada búsqueda.

## Estructura del proyecto

```
proyecto_app_imdb/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── cargar_datos.py      # carga IMDb → Postgres en streaming
├── main.py              # API FastAPI + montaje del frontend estático
├── requirements.txt
└── static/
    ├── index.html
    ├── style.css
    └── app.js
```

## Endpoints

| Método | Ruta                    | Descripción                              |
|--------|-------------------------|-------------------------------------------|
| GET    | `/api/generos`          | Catálogo fijo de géneros de IMDb          |
| GET    | `/api/tipos`             | Catálogo fijo de tipos de título          |
| GET    | `/api/peliculas`         | Búsqueda con filtros + paginación         |
| GET    | `/api/pelicula/{tconst}` | Detalle completo de un título             |

Parámetros de `/api/peliculas`: `titulo`, `tipo`, `genero`, `director`,
`actor`, `rating_min`, `year_min`, `year_max`, `page`.

## Cómo correrlo

Ver la sección *Cómo levantarlo* del [README](README.md). En resumen:
crear un proyecto gratuito en Neon, poner su cadena de conexión en
`DATABASE_URL` dentro de `.env`, correr `cargar_datos.py` una vez y
levantar la app con `docker compose up -d --build`.

## Decisiones de diseño

- **Base en la nube, subconjunto de datos**: la base completa ocupaba
  ~27 GB en disco local. Se movió a Neon (gratuito) cargando solo lo que
  el sitio usa y los títulos con suficiente actividad.
- **Carga en streaming**: el script lee los `.tsv.gz` directo de IMDb y
  los inserta con `COPY`, sin archivos intermedios. Es idempotente: se
  puede volver a correr para actualizar los datos.
- **Frontend sin framework**: HTML/JS plano servido por la misma app de
  FastAPI, para mantener el proyecto simple.

## Posibles próximos pasos

- Desplegar la app (Render/Fly.io gratuitos) apuntando a la misma base.
- Correr `cargar_datos.py` periódicamente (IMDb actualiza los datasets a
  diario).
