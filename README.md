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

### Funcionalidades en SUPABASE
- Función para recoger los proyectos en base al usuario logueado  <<get_projects_by_user>>

 select
        p.id as project_id,
        p.name as project_name
    from public.user_companies uc
    join public.projects p
        on p.company_id = uc.company_id
    where
        uc.user_id = p_user_id
        and p.deleted_at is null;

- Función que recoge poligonos en base a coordenadas
<<get_geometries_in_extent>>

BEGIN
    RETURN QUERY
    SELECT
        q.id,
        ST_AsGeoJSON(q.geometry)::jsonb as geometry,
        q.created_at,
        q.created_by
    FROM public."QGIS" q
    WHERE q.created_by = user_id
    AND ST_Intersects(
        q.geometry,
        ST_MakeEnvelope(x_min, y_min, x_max, y_max, srid)
    );
END;

- Función que recoge las geometrias en GEOJSON unicamente para comprobar datos en FASTAPI
<<get_all_qgis_geometries>>

begin
    return query
    select
        q.id,
        ST_AsGeoJSON(q.geometry)::jsonb as geometry,
        q.created_at,
        q.created_by
    from public."QGIS" q;
end;

- Función que inserta geometrias en supabase
<<insert_geometry>>

declare
    geom geometry;
    new_id bigint;
begin
    -- Convertir GeoJSON a PostGIS geometry (SRID 4326)
    geom := ST_SetSRID(
        ST_GeomFromGeoJSON(geom_json::text),
        4326
    );

    -- Insertar geometría
    insert into public."QGIS"(geometry, created_by, project_id)
    values (geom, user_id, project_id)
    on conflict (geometry) do nothing
    returning id into new_id;

 if new_id is null then
        return jsonb_build_object('success', true, 'code', 'OK_DUPLICATE');
    else
        return jsonb_build_object('success', true, 'code', 'OK_INSERT', 'id', new_id);
    end if;

exception
    when others then
        return jsonb_build_object(
            'success', false,
            'code', 'ERROR_GENERIC',
            'error', sqlerrm,
            'sqlstate', sqlstate
        );
end;

