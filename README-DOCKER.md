# IMDb Explorer — todo en Docker

Este documento reemplaza al README anterior para la parte de arranque; el
resto (estructura del proyecto, filtros, etc.) sigue igual.

Ahora la app y Postgres corren como dos servicios de `docker-compose`:
`web` (FastAPI) y `db` (PostgreSQL 17, vacío al inicio).

## 1. Construir y levantar los contenedores

```bash
cd "proyecto imdb"   # donde ya tienes Dockerfile, docker-compose.yml, main.py, static/
docker compose up -d --build
```

Esto levanta `db` (Postgres vacío, expuesto en el puerto **5433** del host
para no chocar con tu Postgres.app en 5432) y `web` (FastAPI en el puerto
**8000**). Si entras a http://localhost:8000 ahora mismo, la app carga
pero sin datos — falta migrarlos.

## 2. Migrar tu base actual al contenedor

Tu Postgres.app sigue teniendo los datos completos en el puerto 5432. Los
pasamos al contenedor con `pg_dump` + `pg_restore`, corridos **desde tu
Mac** (no dentro de Docker), apuntando el restore al puerto 5433 que
expone el contenedor.

```bash
# 1) Volcado de tu base local (ajusta tu_usuario al que usas en Postico/psql)
pg_dump -h localhost -p 5432 -U tu_usuario -d imdb -Fc -f imdb.dump

# 2) Restaurar ese volcado dentro del contenedor
pg_restore -h localhost -p 5433 -U imdb -d imdb --no-owner -j 4 imdb.dump
```

Notas:
- `-Fc` genera un formato "custom" que permite restaurar en paralelo
  (`-j 4` usa 4 procesos — ajústalo a los núcleos de tu Mac).
- `--no-owner` evita conflictos porque el rol dentro del contenedor
  (`imdb`) no es el mismo que tu usuario local.
- Con ~102M filas en `title_principals` y ~59M en `title_akas`, este
  paso puede tardar bastantes minutos y usar varios GB de espacio en
  disco para el archivo `imdb.dump`. Es normal — no lo interrumpas.
- Cuando termine, `pg_restore` te puede mostrar algunas advertencias de
  permisos (`ERROR: must be owner of...`) si algo no quedó cubierto por
  `--no-owner`; mientras el conteo de filas cuadre, no son bloqueantes.

## 3. Verificar

```bash
docker exec -it $(docker compose ps -q db) psql -U imdb -d imdb -c "SELECT count(*) FROM title_basics;"
```

Si el número coincide con tu base original (~12.8M), quedó bien. Después
recarga http://localhost:8000 y prueba una búsqueda.

## 4. Recrear el índice de trigramas dentro del contenedor

El `pg_dump`/`pg_restore` sí se lleva los índices existentes, así que si
ya lo habías creado en tu base local, no necesitas repetirlo. Si no lo
tenías, créalo ahora dentro del contenedor:

```bash
docker exec -it $(docker compose ps -q db) psql -U imdb -d imdb -c \
  "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE INDEX IF NOT EXISTS name_basics_primary_name_trgm ON name_basics USING gin (primary_name gin_trgm_ops);"
```

## Comandos útiles

```bash
docker compose logs -f web      # logs de la app
docker compose down             # detener (los datos persisten en el volumen)
docker compose down -v          # detener y BORRAR también los datos
```
