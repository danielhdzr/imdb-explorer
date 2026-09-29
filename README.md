# IMDb Explorer

Sitio web para consultar una base completa de IMDb (~250M filas en total)
con filtros por título, tipo, género, director, actor/actriz, rating
mínimo y rango de años. Proyecto de portafolio: backend en FastAPI con
SQL dinámico sobre PostgreSQL, frontend en HTML/JS plano, todo empaquetado
en Docker.

## Qué hace

- Búsqueda de títulos con coincidencia parcial por nombre.
- Filtros combinables: tipo de título, género, director, actor/actriz,
  rating mínimo, rango de años.
- Resultados paginados.
- Vista de detalle por título: sinopsis básica, reparto principal,
  director(es) y guionista(s).

## Stack

| Capa        | Tecnología                                       |
|-------------|---------------------------------------------------|
| Backend     | FastAPI (Python), consultas SQL dinámicas          |
| Driver DB   | psycopg 3 + psycopg_pool (pool de conexiones)      |
| Base        | PostgreSQL 17                                      |
| Frontend    | HTML + CSS + JavaScript vanilla                    |
| Empaquetado | Docker / docker-compose (servicios `db` y `web`)   |

## Cómo levantarlo

Requiere Docker y Docker Compose.

```bash
git clone https://github.com/danielhdzr/imdb-explorer.git
cd imdb-explorer
cp .env.example .env
docker compose up -d --build
```

El sitio queda en **http://localhost:8000**.

> **Nota sobre los datos**: este repositorio no incluye el volcado de la
> base (pesa varios GB) porque supera los límites de GitHub. La base nace
> vacía al levantar los contenedores. Los datos provienen de los datasets
> públicos de IMDb (`title.basics`, `title.ratings`, `name.basics`, etc.)
> cargados con `COPY` y luego normalizados — el proceso completo de carga
> y las mejoras de estructura (arreglos, tablas normalizadas, índices,
> claves foráneas) están documentados en [DOCUMENTACION.md](DOCUMENTACION.md).

## Documentación técnica

Esquema de la base, diseño de los endpoints, cómo se arman las consultas
con filtros dinámicos, y las decisiones de diseño del proyecto están en
[DOCUMENTACION.md](DOCUMENTACION.md).

## Estructura del proyecto

```
imdb-explorer/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── main.py              # API FastAPI + montaje del frontend estático
├── requirements.txt
└── static/
    ├── index.html
    ├── style.css
    └── app.js
```
