"""
IMDb Explorer — backend FastAPI
"""

import os
from contextlib import contextmanager
from typing import Optional

from psycopg import sql
from psycopg_pool import ConnectionPool
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Conexión a la base de datos
# ---------------------------------------------------------------------------

# Cadena de conexión completa, p. ej. la que da Neon:
# postgresql://usuario:clave@ep-xxxx.region.aws.neon.tech/imdb?sslmode=require
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/imdb")

# check_connection descarta conexiones que el servidor cerró mientras
# estaban ociosas (Neon suspende la base tras unos minutos sin uso).
pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=5,
    max_idle=120,
    check=ConnectionPool.check_connection,
    open=False,
)


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

# tvEpisode no se carga en la base (ver cargar_datos.py).
TIPOS_TITULO = [
    "movie", "short", "tvSeries", "tvMovie", "tvMiniSeries",
    "tvSpecial", "tvShort", "video", "videoGame",
]

PAGE_SIZE = 20

app = FastAPI(title="IMDb Explorer")


@app.on_event("startup")
def abrir_pool():
    pool.open()


@app.on_event("shutdown")
def cerrar_pool():
    pool.close()


def tconst(title_id):
    return f"tt{title_id:07d}"


def title_id(tconst_str):
    """'tt0133093' -> 133093; None si el formato no es válido."""
    if tconst_str.startswith("tt") and tconst_str[2:].isdigit():
        return int(tconst_str[2:])
    return None


def patron_ilike(texto):
    """Coincidencia parcial, escapando los comodines que escriba el usuario."""
    texto = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{texto}%"


# ---------------------------------------------------------------------------
# Construcción dinámica de la consulta
# ---------------------------------------------------------------------------

def construir_filtros(
    titulo, tipo, genero, director, actor, rating_min, year_min, year_max
):
    condiciones = []
    params = []

    if titulo:
        # Usa el índice de trigramas titles_primary_title_trgm.
        condiciones.append(sql.SQL("t.primary_title ILIKE %s"))
        params.append(patron_ilike(titulo))

    if tipo:
        condiciones.append(sql.SQL("t.title_type = %s"))
        params.append(tipo)

    if genero:
        # Normaliza mayúsculas contra el catálogo para que @> use el índice GIN.
        genero = next((g for g in GENEROS if g.lower() == genero.lower()), genero)
        condiciones.append(sql.SQL("t.genres @> ARRAY[%s]::text[]"))
        params.append(genero)

    if rating_min is not None:
        condiciones.append(sql.SQL("t.average_rating >= %s"))
        params.append(rating_min)

    if year_min is not None:
        condiciones.append(sql.SQL("t.start_year >= %s"))
        params.append(year_min)

    if year_max is not None:
        condiciones.append(sql.SQL("t.start_year <= %s"))
        params.append(year_max)

    # Director y actor como semi-join (IN) en vez de JOIN + DISTINCT: primero
    # se encuentran las personas por trigramas y luego sus títulos por índice.
    if director:
        condiciones.append(sql.SQL(
            "t.id IN (SELECT d.title_id FROM people p"
            " JOIN title_directors d ON d.person_id = p.id"
            " WHERE p.primary_name ILIKE %s)"
        ))
        params.append(patron_ilike(director))

    if actor:
        condiciones.append(sql.SQL(
            "t.id IN (SELECT tp.title_id FROM people p"
            " JOIN title_principals tp ON tp.person_id = p.id"
            " WHERE tp.category IN ('actor', 'actress')"
            " AND p.primary_name ILIKE %s)"
        ))
        params.append(patron_ilike(actor))

    where = sql.SQL(" AND ").join(condiciones) if condiciones else sql.SQL("TRUE")
    return where, params


def buscar(where, params, page):
    """Página de resultados + total + directores, en una sola consulta."""
    query = sql.SQL(
        """
        WITH pagina AS (
            SELECT t.id, t.primary_title, t.title_type, t.start_year,
                   t.genres, t.average_rating, t.num_votes,
                   count(*) OVER () AS total
            FROM titles t
            WHERE {where}
            ORDER BY t.num_votes DESC, t.id
            LIMIT %s OFFSET %s
        )
        SELECT pg.id, pg.primary_title, pg.title_type, pg.start_year,
               pg.genres, pg.average_rating, pg.num_votes, pg.total,
               ARRAY(
                   SELECT p.primary_name
                   FROM title_directors d JOIN people p ON p.id = d.person_id
                   WHERE d.title_id = pg.id
                   ORDER BY p.primary_name
               ) AS directores
        FROM pagina pg
        ORDER BY pg.num_votes DESC, pg.id
        """
    ).format(where=where)

    with get_cursor() as cur:
        cur.execute(query, params + [PAGE_SIZE, (page - 1) * PAGE_SIZE])
        filas = cur.fetchall()

        if filas:
            total = filas[0][7]
        elif page > 1:
            # Página fuera de rango: el total no viene en ninguna fila.
            cur.execute(
                sql.SQL("SELECT count(*) FROM titles t WHERE {where}").format(
                    where=where
                ),
                params,
            )
            total = cur.fetchone()[0]
        else:
            total = 0

    resultados = [
        {
            "tconst": tconst(f[0]),
            "titulo": f[1],
            "tipo": f[2],
            "anio": f[3],
            "generos": f[4] or [],
            "rating": float(f[5]) if f[5] is not None else None,
            "votos": f[6],
            "directores": f[8],
        }
        for f in filas
    ]
    return resultados, total


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
    where, params = construir_filtros(
        titulo, tipo, genero, director, actor, rating_min, year_min, year_max
    )
    resultados, total = buscar(where, params, page)

    return {
        "resultados": resultados,
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
    }


@app.get("/api/pelicula/{tconst_str}")
def detalle_pelicula(tconst_str: str):
    tid = title_id(tconst_str)
    if tid is None:
        raise HTTPException(status_code=404, detail="Título no encontrado")

    # Todo el detalle en una consulta: con la base en la nube, cada ida y
    # vuelta extra cuesta decenas de milisegundos.
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.primary_title, t.original_title, t.title_type,
                   t.start_year, t.end_year, t.runtime_minutes, t.genres,
                   t.average_rating, t.num_votes,
                   ARRAY(SELECT p.primary_name FROM title_directors d
                         JOIN people p ON p.id = d.person_id
                         WHERE d.title_id = t.id ORDER BY p.primary_name),
                   ARRAY(SELECT p.primary_name FROM title_writers w
                         JOIN people p ON p.id = w.person_id
                         WHERE w.title_id = t.id ORDER BY p.primary_name),
                   COALESCE((
                       SELECT json_agg(json_build_object(
                                  'nombre', p.primary_name,
                                  'categoria', tp.category,
                                  'personaje', tp.characters)
                              ORDER BY tp.ordering)
                       FROM title_principals tp
                       JOIN people p ON p.id = tp.person_id
                       WHERE tp.title_id = t.id
                   ), '[]')
            FROM titles t
            WHERE t.id = %s
            """,
            [tid],
        )
        f = cur.fetchone()

    if not f:
        raise HTTPException(status_code=404, detail="Título no encontrado")

    return {
        "tconst": tconst(tid),
        "titulo": f[0],
        "titulo_original": f[1] or f[0],
        "tipo": f[2],
        "anio_inicio": f[3],
        "anio_fin": f[4],
        "duracion_min": f[5],
        "generos": f[6] or [],
        "rating": float(f[7]) if f[7] is not None else None,
        "votos": f[8],
        "directores": f[9],
        "guionistas": f[10],
        "reparto": f[11],
    }


# Frontend estático — va al final para que las rutas /api/* tengan prioridad
app.mount("/", StaticFiles(directory="static", html=True), name="static")
