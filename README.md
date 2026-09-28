# IMDb Explorer

Sitio web local para consultar tu base de IMDb en PostgreSQL, con filtros
por título, tipo, género, director, actor/actriz, rating mínimo y rango de
años. Backend en FastAPI (consulta SQL dinámica) + frontend en HTML/JS
vanilla servido por la misma app.

## 1. Instalar dependencias

Desde la carpeta del proyecto:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Configurar la conexión a la base

Por defecto la app se conecta a `localhost:5432`, base `imdb`, usando tu
usuario del sistema (igual que psql sin especificar `-U`) y sin password —
que es como la tienes con Postgres.app.

Si tu conexión es distinta, define variables de entorno antes de correr
la app, por ejemplo:

```bash
export DB_USER=tu_usuario
export DB_PASSWORD=tu_password   # solo si le pusiste una
```

## 3. Levantar el servidor

```bash
uvicorn main:app --reload
```

Abre **http://localhost:8000** en el navegador.

## Notas de rendimiento

- Las búsquedas por director/actor usan `ILIKE` sobre `name_basics`
  (~15.6M filas). Para que respondan rápido, te conviene un índice de
  trigramas:

  ```sql
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE INDEX IF NOT EXISTS name_basics_primary_name_trgm
      ON name_basics USING gin (primary_name gin_trgm_ops);
  ```

  Sin este índice, filtrar por nombre de actor/director puede tardar
  varios segundos en tablas de este tamaño (`title_principals` tiene
  ~102M filas).

- El filtro de género usa el índice GIN que ya tienes sobre `genres`.

## Estructura

```
imdb-explorer/
├── main.py           # API FastAPI + montaje del frontend estático
├── requirements.txt
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

## Próximos pasos posibles

- Agregar títulos alternativos (`title_akas`) al detalle.
- Cachear el conteo total (`COUNT`) si notas que la paginación se siente
  lenta con filtros muy amplios (ej. solo género, sin nada más).
