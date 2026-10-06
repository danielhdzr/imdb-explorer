"""
Carga un subconjunto de IMDb en una base PostgreSQL remota (p. ej. Neon free).

Los TSV oficiales se descargan de https://datasets.imdbws.com/ y se
procesan en streaming: nada se guarda en disco, cada fila filtrada va
directo a la base con COPY.

Uso:
    DATABASE_URL=postgresql://... python cargar_datos.py [--min-votos 200]

El script es idempotente: borra y vuelve a crear las tablas.
"""

import argparse
import gzip
import io
import json
import os
import ssl
import sys
import time
import urllib.request

import certifi
import psycopg

BASE_URL = "https://datasets.imdbws.com/"

# certifi evita fallos de certificado con el Python de python.org en macOS.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Categorías de title.principals que se guardan (las que muestra el detalle
# como reparto). Directores y guionistas salen de title.crew.
CATEGORIAS_REPARTO = {"actor", "actress", "self"}

ESQUEMA = """
DROP TABLE IF EXISTS title_principals, title_directors, title_writers,
                     people, titles CASCADE;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE titles (
    id              integer PRIMARY KEY,   -- tconst sin el prefijo 'tt'
    title_type      text NOT NULL,
    primary_title   text NOT NULL,
    original_title  text,                  -- NULL si es igual a primary_title
    start_year      smallint,
    end_year        smallint,
    runtime_minutes integer,
    genres          text[] NOT NULL DEFAULT '{}',
    average_rating  numeric(3,1) NOT NULL,
    num_votes       integer NOT NULL
);

CREATE TABLE people (
    id           integer PRIMARY KEY,      -- nconst sin el prefijo 'nm'
    primary_name text NOT NULL
);

CREATE TABLE title_directors (
    title_id  integer NOT NULL,
    person_id integer NOT NULL
);

CREATE TABLE title_writers (
    title_id  integer NOT NULL,
    person_id integer NOT NULL
);

CREATE TABLE title_principals (
    title_id   integer NOT NULL,
    ordering   smallint NOT NULL,
    person_id  integer NOT NULL,
    category   text NOT NULL,
    characters text
);
"""

# Los índices se crean después de cargar: es mucho más rápido que
# mantenerlos fila por fila durante el COPY.
INDICES = """
CREATE INDEX titles_primary_title_trgm ON titles USING gin (primary_title gin_trgm_ops);
CREATE INDEX titles_num_votes ON titles (num_votes DESC, id);
CREATE INDEX titles_genres ON titles USING gin (genres);
CREATE INDEX people_primary_name_trgm ON people USING gin (primary_name gin_trgm_ops);

ALTER TABLE title_directors ADD PRIMARY KEY (title_id, person_id);
CREATE INDEX title_directors_person ON title_directors (person_id);
ALTER TABLE title_writers ADD PRIMARY KEY (title_id, person_id);
ALTER TABLE title_principals ADD PRIMARY KEY (title_id, ordering);
CREATE INDEX title_principals_person ON title_principals (person_id);

ALTER TABLE title_directors  ADD FOREIGN KEY (title_id)  REFERENCES titles(id);
ALTER TABLE title_directors  ADD FOREIGN KEY (person_id) REFERENCES people(id);
ALTER TABLE title_writers    ADD FOREIGN KEY (title_id)  REFERENCES titles(id);
ALTER TABLE title_writers    ADD FOREIGN KEY (person_id) REFERENCES people(id);
ALTER TABLE title_principals ADD FOREIGN KEY (title_id)  REFERENCES titles(id);
ALTER TABLE title_principals ADD FOREIGN KEY (person_id) REFERENCES people(id);

ANALYZE;
"""


# ---------------------------------------------------------------------------
# Lectura en streaming de los TSV
# ---------------------------------------------------------------------------

def leer_tsv(nombre):
    """Itera las filas (listas de str, None para \\N) de un .tsv.gz remoto."""
    print(f"  descargando {nombre}...", flush=True)
    resp = urllib.request.urlopen(BASE_URL + nombre, context=SSL_CTX)
    texto = io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8")
    next(texto)  # encabezado
    for linea in texto:
        yield [None if c == r"\N" else c for c in linea.rstrip("\n").split("\t")]


def id_num(valor):
    """'tt0133093' -> 133093, 'nm0000206' -> 206."""
    return int(valor[2:])


def entero(valor):
    return int(valor) if valor is not None else None


def personajes(valor):
    """'["Neo","Thomas Anderson"]' -> 'Neo / Thomas Anderson'."""
    if not valor:
        return None
    try:
        return " / ".join(json.loads(valor)) or None
    except ValueError:
        return valor


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def cargar(conn, min_votos):
    with conn.cursor() as cur:
        cur.execute(ESQUEMA)

    print("1/5 ratings")
    ratings = {}
    for tconst, rating, votos in leer_tsv("title.ratings.tsv.gz"):
        if int(votos) >= min_votos:
            ratings[id_num(tconst)] = (rating, int(votos))
    print(f"    {len(ratings):,} títulos con >= {min_votos} votos")

    print("2/5 títulos")
    titulos = set()
    with conn.cursor() as cur, cur.copy(
        "COPY titles (id, title_type, primary_title, original_title, start_year,"
        " end_year, runtime_minutes, genres, average_rating, num_votes) FROM STDIN"
    ) as copy:
        for f in leer_tsv("title.basics.tsv.gz"):
            tid = id_num(f[0])
            # Los episodios sueltos de series ocupan mucho espacio y casi no
            # aportan a la búsqueda; las series en sí sí se cargan.
            if tid not in ratings or f[1] == "tvEpisode":
                continue
            rating, votos = ratings[tid]
            original = f[3] if f[3] != f[2] else None
            generos = f[8].split(",") if f[8] else []
            copy.write_row((
                tid, f[1], f[2], original, entero(f[5]), entero(f[6]),
                entero(f[7]), generos, rating, votos,
            ))
            titulos.add(tid)
    del ratings
    print(f"    {len(titulos):,} títulos cargados")

    personas = set()

    print("3/5 directores y guionistas")
    # Una conexión solo admite un COPY a la vez, así que se juntan en memoria
    # (son ~1M pares de enteros) y se copian después.
    crew = {"title_directors": [], "title_writers": []}
    for tconst, directores, guionistas in leer_tsv("title.crew.tsv.gz"):
        tid = id_num(tconst)
        if tid not in titulos:
            continue
        for tabla, lista in (("title_directors", directores),
                             ("title_writers", guionistas)):
            for nconst in set((lista or "").split(",")) - {""}:
                pid = id_num(nconst)
                crew[tabla].append((tid, pid))
                personas.add(pid)
    with conn.cursor() as cur:
        for tabla, filas in crew.items():
            with cur.copy(f"COPY {tabla} (title_id, person_id) FROM STDIN") as copy:
                for fila in filas:
                    copy.write_row(fila)
    del crew

    print("4/5 reparto (el archivo más grande, tarda unos minutos)")
    filas = 0
    with conn.cursor() as cur, cur.copy(
        "COPY title_principals (title_id, ordering, person_id, category, characters)"
        " FROM STDIN"
    ) as copy:
        for tconst, ordering, nconst, categoria, _job, chars in leer_tsv(
            "title.principals.tsv.gz"
        ):
            if categoria not in CATEGORIAS_REPARTO:
                continue
            tid = id_num(tconst)
            if tid not in titulos:
                continue
            pid = id_num(nconst)
            copy.write_row((tid, int(ordering), pid, categoria, personajes(chars)))
            personas.add(pid)
            filas += 1
    print(f"    {filas:,} filas de reparto")

    print("5/5 personas")
    cargadas = set()
    with conn.cursor() as cur, cur.copy(
        "COPY people (id, primary_name) FROM STDIN"
    ) as copy:
        for f in leer_tsv("name.basics.tsv.gz"):
            pid = id_num(f[0])
            if pid in personas and f[1]:
                copy.write_row((pid, f[1]))
                cargadas.add(pid)
    print(f"    {len(cargadas):,} personas")

    # IMDb a veces referencia personas que ya no están en name.basics; se
    # quitan para que las claves foráneas se puedan crear.
    huerfanas = list(personas - cargadas)
    if huerfanas:
        with conn.cursor() as cur:
            for tabla in ("title_directors", "title_writers", "title_principals"):
                cur.execute(
                    f"DELETE FROM {tabla} WHERE person_id = ANY(%s)", [huerfanas]
                )

    print("Creando índices y claves foráneas...")
    with conn.cursor() as cur:
        cur.execute(INDICES)
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        print(f"Listo. Tamaño de la base: {cur.fetchone()[0]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--min-votos", type=int, default=200,
        help="votos mínimos para incluir un título (default: 200, ~340 MB)",
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta la variable DATABASE_URL (ver .env.example).")

    inicio = time.time()
    with psycopg.connect(url) as conn:
        cargar(conn, args.min_votos)
    print(f"Tiempo total: {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
