# QGIS Supabase Sync – Resumen del Proyecto

Este proyecto implementa un sistema de sincronización bidireccional entre QGIS y una base de datos en Supabase (PostgreSQL/PostGIS) mediante una API desarrollada en FastAPI.
Permite cargar capas desde Supabase, editarlas en QGIS y enviar nuevamente los cambios al servidor manteniendo un formato uniforme y controlado.

## Funcionalidad Principal
✔ 1. Descarga de capas desde Supabase

El plugin solicita al servidor la información de la capa.

La API devuelve un JSON normalizado con:

Tipo de geometría (Point, LineString, Polygon, incluyendo Multi-*)

Atributos de cada feature

Geometría en formato GeoJSON

El plugin detecta automáticamente el tipo de geometría y genera la capa correcta en QGIS.

✔ 2. Subida de cambios desde QGIS a Supabase

El plugin serializa cada feature utilizando:

serialize_geometry() → Convierte geometría QGIS → GeoJSON seguro

serialize_attributes() → Convierte atributos QGIS → tipos Python/JSON válidos
(corrigiendo problemas con QVariant)

serialize_feature() → Construye la estructura uniforme del feature

Se envía al servidor un JSON limpio, estándar y consistente.

✔ 3. Gestión automática de geometrías

El plugin identifica correctamente:

GeoJSON	QGIS
Point / MultiPoint	Point
LineString / MultiLineString	LineString
Polygon / MultiPolygon	Polygon

Esto garantiza que las capas se crean con el tipo correcto independientemente del origen.

Para arrancar el server 

```sh
python -m uvicorn server:app --reload --host 127.0.0.1 --port 5000
```

Ruta donde alojar el contenido de la carpeta plugin

```sh
C:\Users\usuario\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins
```

----

### CAMBIOS: 
- Entorno: 
    - creados archivos de UV, para instalar dependencias: uv sync

    - Creado fichero Supabase con datos de migración
