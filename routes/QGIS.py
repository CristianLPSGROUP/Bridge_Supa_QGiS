from fastapi import APIRouter, Depends, HTTPException
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
    max_zoom_out: float = 100000  # Escala máxima permitida (menor número = más zoom in)


class FeatureModel(BaseModel):
    geometry: Dict[str, Any]
    properties: Dict[str, Any]


class LayerQueryRequest(BaseModel):
    extents: Extents


class LayerUploadRequest(BaseModel):
    layer_name: str
    features: List[FeatureModel]


### Routes
@router.post("/get_layer")
async def get_layers(request: LayerQueryRequest, auth_data = Depends(get_authenticated_supabase_client)):
    """
    Lee la geometría cargada en la tabla "QGIS" de Postgres
    filtrada por los extents del mapa del usuario
    """
    supabase, user_id = auth_data
    extents = request.extents

    # Validar zoom level - evitar queries cuando está muy alejado
    if extents.zoom and extents.zoom > extents.max_zoom_out:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Zoom level too far out",
                "message": f"Por favor, acércate más. Escala actual: {extents.zoom}, máxima permitida: {extents.max_zoom_out}",
                "current_zoom": extents.zoom,
                "max_allowed": extents.max_zoom_out
            }
        )

    try:
        # Extraer el SRID del CRS (ej: "EPSG:4326" -> 4326)
        srid = int(extents.crs.split(":")[-1])

        # función RPC de PostgreSQL para query espacial
        response = supabase.rpc(
            "get_geometries_in_extent",
            {
                "x_min": extents.xMin,
                "x_max": extents.xMax,
                "y_min": extents.yMin,
                "y_max": extents.yMax,
                "srid": srid,
                "user_id": str(user_id)
            }
        ).execute()

        data = response.data if response.data else []

        return {
            "success": True,
            "features": data,
            "extent": extents.dict()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar geometrías: {str(e)}")


@router.post("/upload_geometries")
async def upload_geometries(request: LayerUploadRequest, auth_data = Depends(get_authenticated_supabase_client)):
    """
    Sube geometrías a la tabla QGIS de Postgres usando RPC function
    - id: auto-generado por la base de datos
    - created_at: timestamp automático
    - created_by: del usuario autenticado
    - Usa ST_GeomFromGeoJSON para convertir correctamente el GeoJSON a PostGIS geometry
    """
    supabase, user_id = auth_data

    if not request.features:
        raise HTTPException(status_code=400, detail="No se proporcionaron features para subir")

    try:
        inserted_count = 0
        duplicate_count = 0
        errors = []

        for feature in request.features:
            try:
                # Usar RPC function para insertar correctamente con PostGIS
                response = supabase.rpc(
                    "insert_geometry",
                    {
                        "geom_json": feature.geometry,
                        "user_id": str(user_id)
                    }
                ).execute()

                if response.data:
                    # The RPC function now returns a JSON object with success info
                    result = response.data if isinstance(response.data, dict) else response.data[0]

                    if result.get("success"):
                        if result.get("duplicate"):
                            duplicate_count += 1
                        else:
                            inserted_count += 1
                    else:
                        # RPC function returned an error
                        errors.append({
                            "error": result.get("error", "Unknown error"),
                            "geometry_type": feature.geometry.get("type", "unknown")
                        })

            except Exception as feat_error:
                errors.append({
                    "error": str(feat_error),
                    "geometry_type": feature.geometry.get("type", "unknown")
                })
                continue

        return {
            "success": True,
            "message": f"Procesado correctamente",
            "inserted": inserted_count,
            "duplicates": duplicate_count,
            "errors": errors if errors else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir geometrías: {str(e)}")
