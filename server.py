# server.py
import os
from fastapi import FastAPI
from datetime import datetime
from pydantic import BaseModel
from typing import List, Dict, Any
import json
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional


BBDD_FOLDER = "BBDD"

os.makedirs(BBDD_FOLDER, exist_ok=True)


# =====================================================
#                 MODELOS DE DATOS
# =====================================================
class FeatureModel(BaseModel):
    id: Optional[int] = None
    geometry: Dict[str, Any]
    properties: Dict[str, Any]


class LayerModel(BaseModel):
    layer_name: str
    features: List[FeatureModel]


# =====================================================
#                 CONFIGURACIÓN FASTAPI
# =====================================================
app = FastAPI(title="Servidor QGIS-Supabase Sync")

# Habilitar CORS para que QGIS pueda hacer POST desde localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Solo para pruebas, en producción restringir dominios
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
#                 ENDPOINTS
# =====================================================
@app.get("/layer")
async def get_layers():
    """
    Devuelve las capas cargadas (puedes leer de un fichero)
    """
    try:
        with open("BBDD\layers_20251205_125842.json", "r", encoding="utf-8") as f:
            # with open("layers.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}  # Si no existe el fichero aún, devolver vacío
    return data


@app.post("/sync")
async def sync(layers: List[LayerModel]):
    """
    Recibe la lista de capas y features editadas desde QGIS
    y las guarda en un fichero JSON.
    """
    # Convertir a dict simple para poder escribir JSON
    output = []
    for layer in layers:
        layer_dict = {"layer_name": layer.layer_name, "features": []}
        for feat in layer.features:
            feat_dict = {
                "id": feat.id,
                "geometry": feat.geometry,
                "properties": feat.properties,
            }
            layer_dict["features"].append(feat_dict)
        output.append(layer_dict)

    # Guardar fichero en JSON individual
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"layers_{timestamp}.json"
    filepath = os.path.join(BBDD_FOLDER, filename)

    # Guardar en fichero JSON
    # with open("layers.json", "w", encoding="utf-8") as f:
    #    json.dump(output, f, ensure_ascii=False, indent=2)

    # Guardar en fichero JSON
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Guardado fichero: {filepath}")
    return {"status": "ok", "message": f"{len(output)} capas guardadas correctamente."}
