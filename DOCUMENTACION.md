# IMDb Explorer

Sitio web para consultar una base local de IMDb con filtros por título,
tipo, género, director, actor/actriz, rating mínimo y rango de años.
Proyecto de portafolio: backend en FastAPI con SQL dinámico sobre
PostgreSQL, frontend en HTML/JS plano, todo empaquetado en Docker.

## Qué hace

- Búsqueda de títulos con coincidencia parcial por nombre.
- Filtros combinables: tipo de título, género, director, actor/actriz,
  rating mínimo, rango de años.
- Resultados paginados (20 por página).
- Vista de detalle por título: sinopsis básica, reparto principal,
  director(es) y guionista(s).

## Stack

| Capa       | Tecnología                                   |
|------------|-----------------------------------------------|
| Backend    | FastAPI (Python), consultas SQL dinámicas     |
| Driver DB  | psycopg 3 + psycopg_pool (pool de conexiones) |
| Base       | PostgreSQL 17                                 |
| Frontend   | HTML + CSS + JavaScript vanilla               |
| Empaquetado| Docker / docker-compose (servicios `db` y `web`) |

## Origen de los datos

La base viene de los datasets públicos de IMDb (`title.basics`,
`title.ratings`, `name.basics`, `title.principals`, `title.akas`, etc.),
cargados con `COPY` directo desde los TSV oficiales. Sobre esos datos se
aplicaron varias mejoras de estructura antes de construir el sitio:

- `genres` convertido de texto plano a arreglo (`text[]`) con índice GIN.
- `directors` y `writers` normalizados en tablas propias
  (`title_directors`, `title_writers`) en vez de listas embebidas.
- Claves primarias y 10 claves foráneas entre las 8 tablas finales.
- Índice de trigramas (`pg_trgm`) sobre `name_basics.primary_name` para
  que las búsquedas por nombre de director/actor no tengan que escanear
  completa una tabla de ~15.6M de personas.

### Esquema relevante

```
title_basics      (tconst, title_type, primary_title, original_title,
                    is_adult, start_year, end_year, runtime_minutes, genres[])
title_ratings     (tconst, average_rating, num_votes)
title_directors   (tconst, nconst)
title_writers     (tconst, nconst)
title_principals  (tconst, ordering, nconst, category, job, characters)
name_basics       (nconst, primary_name, birth_year, death_year,
                    primary_profession, known_for_titles)
title_akas        (títulos alternativos por región/idioma)
```

Tamaño aproximado de las tablas más grandes: `title_principals` ~101.9M
filas, `title_akas` ~59.5M, `name_basics` ~15.6M, `title_basics` ~12.8M.

## Cómo arman los filtros la consulta

En vez de un único query gigante siempre con todos los `JOIN`, el backend
arma la consulta en dos pasos:

1. **Búsqueda de IDs**: un `SELECT DISTINCT tconst` que solo agrega los
   `JOIN` que hacen falta según qué filtros vengan llenos (por ejemplo,
   si no se filtra por actor, nunca se toca `title_principals`). Ya
   viene paginado con `LIMIT`/`OFFSET`.
2. **Detalle de esa página**: con el puñado de IDs resultante (máximo 20),
   un segundo query trae título, año, géneros, rating y directores vía
   `array_agg`, evitando duplicados de un `GROUP BY` sobre tablas enormes.

El filtro de director/actor hace `ILIKE` sobre `name_basics.primary_name`
(por eso el índice de trigramas es importante para el rendimiento). El
filtro de género usa `EXISTS (SELECT 1 FROM unnest(genres) ...)` para
comparar contra el arreglo sin depender de mayúsculas/minúsculas exactas.

## Estructura del proyecto

```
proyecto_app_imdb/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
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

Todo el stack (app + base) vive en `docker-compose.yml`, con dos
servicios: `db` (Postgres 17, puerto 5433 hacia el host) y `web`
(FastAPI, puerto 8000).

```bash
cd proyecto_app_imdb
docker compose up -d --build
```

La base nace vacía dentro del contenedor — los datos se migran una sola
vez desde el Postgres local con `pg_dump` / `pg_restore`:

```bash
# Volcado de la base local (Postgres.app, puerto 5432)
pg_dump -h localhost -p 5432 -U <tu_usuario> -d imdb -Fc -f imdb.dump

# Restauración dentro del contenedor (puerto 5433)
pg_restore -h localhost -p 5433 -U imdb -d imdb --no-owner -j 4 imdb.dump
```

Con los contenedores arriba y los datos migrados, el sitio queda en
**http://localhost:8000**.

## Decisiones de diseño

- **Todo en local, sin hosting**: por el tamaño de la base (varios GB,
  ~250M filas en total entre las tablas grandes), no cabía en los tiers
  gratuitos de Postgres administrado (Supabase, Neon, Railway), así que
  se descartó el despliegue y el proyecto corre completo en la Mac.
- **Frontend sin framework**: HTML/JS plano servido por la misma app de
  FastAPI, para mantener el proyecto simple y con una sola pieza que
  levantar.
- **Dos pasos en vez de un solo query con GROUP BY**: se evitó agrupar
  sobre tablas de cientos de millones de filas; el filtrado (con los
  JOIN condicionales) y el detalle de la página se separaron para que
  cada consulta toque solo lo necesario.

## Posibles próximos pasos

- Mostrar títulos alternativos (`title_akas`) en la vista de detalle.
- Cachear el conteo total de resultados si la paginación se siente
  lenta con filtros muy amplios (por ejemplo, solo género).
- Capturas de pantalla o un GIF corto del sitio para el portafolio.
