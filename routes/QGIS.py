from urllib import response
from fastapi import APIRouter, Depends, HTTPException
import json
from supabase_auth.errors import AuthApiError
from .utils.limiter import limiter
from .utils.supabase_manager import supabase_client, get_authenticated_supabase_client
import asyncio
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Dict, Any
from typing import Optional

load_dotenv()

router = APIRouter(prefix="/api/qgis", tags=["QGIS"])


### Models
class Extents(BaseModel):
    xMin: float
    xMax: float
    yMin: float
    yMax: float
    crs: str = "EPSG:4326"
    zoom: Optional[float] = None
    max_zoom_out: float = (
        1000000000  # Escala máxima permitida (menor número = más zoom in)
    )


class FeatureModel(BaseModel):
    geometry: Dict[str, Any]
    properties: Dict[str, Any]


class LayerQueryRequest(BaseModel):
    extents: Extents


class LayerUploadRequest(BaseModel):
    layer_name: str
    features: List[FeatureModel]


### Routes


@router.get("/qgis_all")
async def get_all_qgis():
    """
    Devuelve todos los registros de QGIS con geometría deserializada.
    """
    try:
        response = supabase_client.rpc("get_all_qgis_geometries").execute()
        data = response.data if response.data else []
        return {"success": True, "features": data}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error al consultar geometrías: {str(e)}"
        )


@router.post("/get_layer_simple")
async def get_layers(auth_data=Depends(get_authenticated_supabase_client)):
    """
    Lee la geometría cargada en la tabla "QGIS" de Postgres
    """
    supabase, user_id = auth_data

    try:
        # Usar select con ST_AsGeoJSON para obtener geometría como GeoJSON
        response = supabase.rpc(
            "get_qgis_geojson"  # optional: could create an RPC function in Postgres
        ).execute()

        # Si no se usa RPC, entonces se puede hacer un select normal
        # response = supabase.table("QGIS").select("*").execute()

        data = response.data if response.data else []
        print("GeoJSON recibido:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # Generar un GeoJSON-like response
        features = [
            {
                "type": "Feature",
                "geometry": json.loads(row["geometry"]) if row["geometry"] else None,
                "properties": {k: v for k, v in row.items() if k != "geometry"},
            }
            for row in data
        ]

        # Calcular extent (bounding box) opcionalmente
        # extent = supabase.rpc("get_qgis_extent").execute().data

        return {
            "success": True,
            "type": "FeatureCollection",
            "features": features,
            "extent": None,  # o usar extent si se calcula
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error al consultar geometrías: {str(e)}"
        )


import traceback


@router.post("/get_layer")
async def get_layers(
    request: LayerQueryRequest,
    auth_data=Depends(get_authenticated_supabase_client),
):
    supabase, user_id = auth_data
    extents = request.extents
    print(extents)

    if extents.zoom and extents.zoom > extents.max_zoom_out:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Zoom level too far out",
                "message": f"Por favor, acércate más. Escala actual: {extents.zoom}, máxima permitida: {extents.max_zoom_out}",
                "current_zoom": extents.zoom,
                "max_allowed": extents.max_zoom_out,
            },
        )

    try:
        srid = int(extents.crs.split(":")[-1])

        response = await asyncio.to_thread(
            lambda: supabase.rpc(
                "get_geometries_in_extent",
                {
                    "x_min": extents.xMin,
                    "x_max": extents.xMax,
                    "y_min": extents.yMin,
                    "y_max": extents.yMax,
                    "srid": srid,
                    "user_id": str(user_id),
                },
            ).execute()
        )

        # Normalizar data
        if response.data is None:
            data = []
        elif isinstance(response.data, dict):
            data = [response.data]
        else:
            data = response.data

        print("|----------------------------------------------------|")
        print("RPC raw response:", response)
        print("RPC data:", data)

        return {"success": True, "features": data, "extent": extents.dict()}

    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        print("TRACEBACK ERROR:", tb)
        raise HTTPException(
            status_code=500, detail=f"Error al consultar geometrías: {str(e)}"
        )


@router.post("/upload_geometries")
async def upload_geometries(
    request: LayerUploadRequest, auth_data=Depends(get_authenticated_supabase_client)
):
    """
    Sube geometrías a la tabla QGIS de Postgres usando RPC function
    - id: auto-generado por la base de datos
    - created_at: timestamp automático
    - created_by: del usuario autenticado
    - Usa ST_GeomFromGeoJSON para convertir correctamente el GeoJSON a PostGIS geometry
    """
    supabase, user_id = auth_data

    if not request.features:
        raise HTTPException(
            status_code=400, detail="No se proporcionaron features para subir"
        )

    try:
        inserted_count = 0
        duplicate_count = 0
        errors = []

        print(f"Subiendo {len(request.features)} features para el usuario {user_id}")
        for feature in request.features:
            try:
                print(f"Subiendo feature con geometría: {feature.geometry}")

                print(f"Geom JSON string: {feature.geometry}")
                # Usar RPC function para insertar correctamente con PostGIS
                response = await asyncio.to_thread(
                    lambda: supabase.rpc(
                        "insert_geometry",
                        {"geom_json": feature.geometry, "user_id": str(user_id)},
                    ).execute()
                )
                print("|----------------------------------------------------|")
                print("RPC raw response:", response)
                print("RPC data:", response.data)
                print("RPC error:", response.error)

                if response.data:
                    result = (
                        response.data
                        if isinstance(response.data, dict)
                        else response.data[0]
                    )

                    if result.get("success"):
                        code = result.get("code")
                        if code == "OK_INSERT":
                            inserted_count += 1
                        elif code == "OK_DUPLICATE":
                            duplicate_count += 1
                    else:
                        errors.append(
                            {
                                "error": result.get("message", "Unknown error"),
                                "geometry_type": feature.geometry.get(
                                    "type", "unknown"
                                ),
                                "code": result.get("code", "ERROR_GENERIC"),
                            }
                        )
            except Exception as feat_error:

                errors.append(
                    {
                        "error": str(feat_error),
                        "geometry_type": feature.geometry.get("type", "unknown"),
                    }
                )
                continue

        return {
            "success": True,
            "message": f"Procesado correctamente",
            "inserted": inserted_count,
            "duplicates": duplicate_count,
            "errors": errors if errors else None,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error al subir geometrías: {str(e)}"
        )
