"""
IMDb Explorer — backend FastAPI (Versión Original Restaurada)
"""

import os
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Conexión a la base de datos
# ---------------------------------------------------------------------------

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "imdb"),
}
if os.environ.get("DB_USER"):
    DB_CONFIG["user"] = os.environ["DB_USER"]
if os.environ.get("DB_PASSWORD"):
    DB_CONFIG["password"] = os.environ["DB_PASSWORD"]

# Construimos el string de conexión para Psycopg 3
conn_str = f"host={DB_CONFIG['host']} port={DB_CONFIG['port']} dbname={DB_CONFIG['dbname']}"
if "user" in DB_CONFIG:
    conn_str += f" user={DB_CONFIG['user']}"
if "password" in DB_CONFIG:
    conn_str += f" password={DB_CONFIG['password']}"

pool = ConnectionPool(conninfo=conn_str, min_size=1, max_size=10)


@contextmanager
def get_cursor():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------

GENEROS = [
    "Action", "Adult", "Adventure", "Animation", "Biography", "Comedy",
    "Crime", "Documentary", "Drama", "Family", "Fantasy", "Film-Noir",
    "Game-Show", "History", "Horror", "Music", "Musical", "Mystery",
    "News", "Reality-TV", "Romance", "Sci-Fi", "Short", "Sport",
    "Talk-Show", "Thriller", "War", "Western",
]

TIPOS_TITULO = [
    "movie", "short", "tvSeries", "tvEpisode", "tvMovie", "tvMiniSeries",
    "tvSpecial", "tvShort", "video", "videoGame",
]

PAGE_SIZE = 20

app = FastAPI(title="IMDb Explorer")


# ---------------------------------------------------------------------------
# Construcción dinámica de la consulta (Original)
# ---------------------------------------------------------------------------

def construir_filtros(
    titulo, tipo, genero, director, actor, rating_min, year_min, year_max
):
    joins = []
    condiciones = []
    params = []

    if titulo:
        condiciones.append(sql.SQL("tb.primary_title ILIKE %s"))
        params.append(f"%{titulo}%")

    if tipo:
        condiciones.append(sql.SQL("tb.title_type = %s"))
        params.append(tipo)

    if genero:
        condiciones.append(
            sql.SQL(
                "EXISTS (SELECT 1 FROM unnest(tb.genres) g WHERE g ILIKE %s)"
            )
        )
        params.append(genero)

    if rating_min is not None:
        condiciones.append(sql.SQL("tr.average_rating >= %s"))
        params.append(rating_min)

    if year_min is not None:
        condiciones.append(sql.SQL("tb.start_year >= %s"))
        params.append(year_min)

    if year_max is not None:
        condiciones.append(sql.SQL("tb.start_year <= %s"))
        params.append(year_max)

    if director:
        joins.append(
            sql.SQL(
                "JOIN title_directors td ON td.tconst = tb.tconst "
                "JOIN name_basics nd ON nd.nconst = td.nconst"
            )
        )
        condiciones.append(sql.SQL("nd.primary_name ILIKE %s"))
        params.append(f"%{director}%")

    if actor:
        joins.append(
            sql.SQL(
                "JOIN title_principals tp ON tp.tconst = tb.tconst "
                "AND tp.category IN ('actor', 'actress') "
                "JOIN name_basics na ON na.nconst = tp.nconst"
            )
        )
        condiciones.append(sql.SQL("na.primary_name ILIKE %s"))
        params.append(f"%{actor}%")

    return joins, condiciones, params


def buscar_tconsts(filtros_joins, condiciones, params, page, page_size):
    joins_sql = sql.SQL(" ").join(filtros_joins)
    where_sql = (
        sql.SQL(" AND ").join(condiciones) if condiciones else sql.SQL("TRUE")
    )

    query = sql.SQL(
        """
        SELECT DISTINCT tb.tconst
        FROM title_basics tb
        LEFT JOIN title_ratings tr ON tr.tconst = tb.tconst
        {joins}
        WHERE {where}
        ORDER BY tb.tconst
        LIMIT %s OFFSET %s
        """
    ).format(joins=joins_sql, where=where_sql)

    with get_cursor() as cur:
        cur.execute(query, params + [page_size, (page - 1) * page_size])
        filas = cur.fetchall()

    return [f[0] for f in filas]


def contar_total(filtros_joins, condiciones, params):
    joins_sql = sql.SQL(" ").join(filtros_joins)
    where_sql = (
        sql.SQL(" AND ").join(condiciones) if condiciones else sql.SQL("TRUE")
    )

    query = sql.SQL(
        """
        SELECT COUNT(DISTINCT tb.tconst)
        FROM title_basics tb
        LEFT JOIN title_ratings tr ON tr.tconst = tb.tconst
        {joins}
        WHERE {where}
        """
    ).format(joins=joins_sql, where=where_sql)

    with get_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()[0]


def obtener_detalle_lista(tconsts):
    if not tconsts:
        return []

    query = sql.SQL(
        """
        SELECT
            tb.tconst,
            tb.primary_title,
            tb.title_type,
            tb.start_year,
            tb.genres,
            tr.average_rating,
            tr.num_votes,
            COALESCE(
                array_agg(DISTINCT nd.primary_name)
                    FILTER (WHERE nd.primary_name IS NOT NULL),
                '{{}}'
            ) AS directores
        FROM title_basics tb
        LEFT JOIN title_ratings tr ON tr.tconst = tb.tconst
        LEFT JOIN title_directors td ON td.tconst = tb.tconst
        LEFT JOIN name_basics nd ON nd.nconst = td.nconst
        WHERE tb.tconst = ANY(%s)
        GROUP BY tb.tconst, tb.primary_title, tb.title_type, tb.start_year,
                 tb.genres, tr.average_rating, tr.num_votes
        """
    )

    with get_cursor() as cur:
        cur.execute(query, [tconsts])
        filas = cur.fetchall()

    por_id = {f[0]: f for f in filas}
    resultado = []
    for tconst in tconsts:
        f = por_id.get(tconst)
        if not f:
            continue
        resultado.append(
            {
                "tconst": f[0],
                "titulo": f[1],
                "tipo": f[2],
                "anio": f[3],
                "generos": f[4] or [],
                "rating": float(f[5]) if f[5] is not None else None,
                "votos": f[6],
                "directores": f[7],
            }
        )
    return resultado


@app.get("/api/generos")
def listar_generos():
    return GENEROS


@app.get("/api/tipos")
def listar_tipos():
    return TIPOS_TITULO


@app.get("/api/peliculas")
def buscar_peliculas(
    titulo: Optional[str] = None,
    tipo: Optional[str] = None,
    genero: Optional[str] = None,
    director: Optional[str] = None,
    actor: Optional[str] = None,
    rating_min: Optional[float] = Query(None, ge=0, le=10),
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    page: int = Query(1, ge=1),
):
    joins, condiciones, params = construir_filtros(
        titulo, tipo, genero, director, actor, rating_min, year_min, year_max
    )

    total = contar_total(joins, condiciones, params)
    tconsts = buscar_tconsts(joins, condiciones, params, page, PAGE_SIZE)
    resultados = obtener_detalle_lista(tconsts)

    return {
        "resultados": resultados,
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
    }


@app.get("/api/pelicula/{tconst}")
def detalle_pelicula(tconst: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT tb.tconst, tb.primary_title, tb.original_title,
                   tb.title_type, tb.start_year, tb.end_year,
                   tb.runtime_minutes, tb.genres,
                   tr.average_rating, tr.num_votes
            FROM title_basics tb
            LEFT JOIN title_ratings tr ON tr.tconst = tb.tconst
            WHERE tb.tconst = %s
            """,
            [tconst],
        )
        base = cur.fetchone()
        if not base:
            raise HTTPException(status_code=404, detail="Título no encontrado")

        cur.execute(
            """
            SELECT nb.primary_name
            FROM title_directors td
            JOIN name_basics nb ON nb.nconst = td.nconst
            WHERE td.tconst = %s
            """,
            [tconst],
        )
        directores = [r[0] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT nb.primary_name
            FROM title_writers tw
            JOIN name_basics nb ON nb.nconst = tw.nconst
            WHERE tw.tconst = %s
            """,
            [tconst],
        )
        guionistas = [r[0] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT nb.primary_name, tp.category, tp.job, tp.characters
            FROM title_principals tp
            JOIN name_basics nb ON nb.nconst = tp.nconst
            WHERE tp.tconst = %s
            ORDER BY tp.ordering
            """,
            [tconst],
        )
        reparto = [
            {
                "nombre": r[0],
                "categoria": r[1],
                "job": r[2],
                "personaje": r[3],
            }
            for r in cur.fetchall()
        ]

    return {
        "tconst": base[0],
        "titulo": base[1],
        "titulo_original": base[2],
        "tipo": base[3],
        "anio_inicio": base[4],
        "anio_fin": base[5],
        "duracion_min": base[6],
        "generos": base[7] or [],
        "rating": float(base[8]) if base[8] is not None else None,
        "votos": base[9],
        "directores": directores,
        "guionistas": guionistas,
        "reparto": reparto,
    }


# Frontend estático — va al final para que las rutas /api/* tengan prioridad
app.mount("/", StaticFiles(directory="static", html=True), name="static")
