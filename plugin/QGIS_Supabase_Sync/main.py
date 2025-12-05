import requests
import urllib.request
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from PyQt5.QtCore import QVariant
from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsProject,
    QgsField,
    QgsRasterLayer,
    QgsWkbTypes,
)
import json


class QgisSupabaseSyncPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.capas_api = []
        self.layer = None  # <<< IMPORTANTE

    def initGui(self):
        self.action_load = QAction("Cargar capa desde API", self.iface.mainWindow())
        self.action_load.triggered.connect(self.cargar_capa)
        self.iface.addToolBarIcon(self.action_load)

        self.action_save = QAction("Enviar cambios a API", self.iface.mainWindow())
        self.action_save.triggered.connect(self.guardar_cambios)
        self.iface.addToolBarIcon(self.action_save)

    def unload(self):
        self.iface.removeToolBarIcon(self.action_load)
        self.iface.removeToolBarIcon(self.action_save)

    def qvariant_to_python(self, value):
        from qgis.PyQt.QtCore import QVariant

        if isinstance(value, QVariant):
            value = value.value()  # extrae el valor real

        # Asegurarse de que sea un tipo JSON serializable
        if isinstance(value, (int, float, str, bool)) or value is None:
            return value
        return str(value)  # para cualquier tipo complejo, convertir a string

    def serialize_feature(self, feature):
        """
        Serializa una feature de QGIS a dict JSON.
        """
        geom = None
        try:
            geom = json.loads(feature.geometry().asJson())
        except Exception:
            geom = None

        props = {}
        for field in feature.fields():
            val = feature.attribute(field.name())
            props[field.name()] = self.qvariant_to_python(val)

        # ID de la feature, nuevo si es negativo
        feat_id = feature.id()
        if feat_id is None or feat_id < 0:
            feat_id = f"new_{feature.id()}"

        # Nombre por defecto
        if "name" not in props or not props["name"]:
            props["name"] = "NULL"

        return {"id": feat_id, "geometry": geom, "properties": props}

    def serialize_layer(self, layer):
        """
        Serializa toda la capa a un dict con layer_name y features.
        Solo capas vectoriales.
        """
        if not isinstance(layer, QgsVectorLayer):
            return None

        layer_data = {"layer_name": layer.name(), "features": []}

        for feat in layer.getFeatures():
            feat_dict = self.serialize_feature(feat)
            if feat_dict["geometry"] is None:
                continue
            layer_data["features"].append(feat_dict)

        if not layer_data["features"]:
            return None

        return layer_data

    def feature_to_dict(self, feature):
        """
        Convierte un QgsFeature en un dict totalmente serializable a JSON,
        incluyendo su ID para poder actualizar en servidor.
        """
        from qgis.PyQt.QtCore import QVariant

        def qvariant_to_python(value):

            if isinstance(value, QVariant):
                value = value.value()

            if isinstance(value, (int, float, str, bool)) or value is None:
                return value

            return str(value)

        # --- GEOMETRÍA ---
        geom = None
        try:
            geom = json.loads(feature.geometry().asJson())
        except Exception:
            geom = None

        # --- PROPIEDADES ---
        props = {}
        for field in feature.fields():
            val = feature.attribute(field.name())
            props[field.name()] = qvariant_to_python(val)

        return {
            "id": feature.id(),  # <<<< --- NECESARIO PARA ACTUALIZAR ---
            "geometry": geom,
            "properties": props,
        }

    # ================================================================
    #                          CARGAR CAPAS
    # ================================================================
    def agregar_mapa_base(self):
        url = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        layer = QgsRasterLayer(url, "OpenStreetMap", "wms")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)

    def cargar_capa(self):

        # Importar aquí para evitar error al iniciar QGIS
        from qgis.core import QgsJsonUtils

        url = "http://127.0.0.1:5000/layer"

        try:
            response = requests.get(url)
            response.raise_for_status()
        except Exception as e:
            self.iface.messageBar().pushCritical("Error", f"No se pudo conectar: {e}")
            return

        data = response.json()

        self.agregar_mapa_base()

        self.capas_api = []
        self.layer = None

        # for layer_name, layer_data in data.items():
        #   if "features" not in layer_data:
        #      continue
        for layer_data in data:  # data es una lista
            layer_name = layer_data.get("layer_name", "LayerSinNombre")
            features = layer_data.get("features", [])
            # features = layer_data["features"]
            if not features:
                continue

            geom_type = features[0]["geometry"]["type"]

            if geom_type in ["Point", "MultiPoint"]:
                qgis_geom_type = "Point"
            elif geom_type in ["LineString", "MultiLineString"]:
                qgis_geom_type = "LineString"
            elif geom_type in ["Polygon", "MultiPolygon"]:
                qgis_geom_type = "Polygon"
            else:
                qgis_geom_type = "Unknown"

            mem_layer = QgsVectorLayer(
                f"{qgis_geom_type}?crs=EPSG:4326", layer_name, "memory"
            )
            prov = mem_layer.dataProvider()

            all_keys = sorted({key for f in features for key in f["properties"].keys()})

            prov.addAttributes([QgsField(key, QVariant.String) for key in all_keys])
            mem_layer.updateFields()

            feats = []
            for feat in features:
                f = QgsFeature()

                geom = QgsJsonUtils.geometryFromGeoJson(json.dumps(feat["geometry"]))
                f.setGeometry(geom)

                attr_list = [feat["properties"].get(key, "") for key in all_keys]
                f.setAttributes(attr_list)

                feats.append(f)

            prov.addFeatures(feats)
            mem_layer.updateExtents()

            QgsProject.instance().addMapLayer(mem_layer)
            self.capas_api.append(mem_layer)

            if self.layer is None:
                self.layer = mem_layer

        self.iface.messageBar().pushSuccess("OK", "Capas cargadas correctamente")

    # ================================================================
    #                          GUARDAR CAMBIOS
    # ================================================================

    def guardar_cambios(self):
        if not self.capas_api:
            QMessageBox.warning(None, "Error", "Primero carga una capa desde la API.")
            return

        try:
            payload = []

            # Todas las capas visibles en QGIS
            project_layers = list(QgsProject.instance().mapLayers().values())

            for layer in project_layers:
                # --- FILTRAR SOLO CAPAS VECTORIALES ---
                if not isinstance(layer, QgsVectorLayer):
                    print(f"Ignorando capa no vectorial: {layer.name()}")
                    continue

                # Ignorar capas sin geometría válida
                if (
                    QgsWkbTypes.geometryType(layer.wkbType())
                    == QgsWkbTypes.UnknownGeometry
                ):
                    print(f"Ignorando capa sin geometría válida: {layer.name()}")
                    continue

                # Serializar la capa completa
                layer_data = self.serialize_layer(layer)
                # if layer_data["features"]:
                #    payload.append(layer_data)

                # Recorrer cada feature
                # for feat in layer.getFeatures():
                #    feat_dict = self.feature_to_dict(feat)

                # Si la geometría es None, saltar
                #    if feat_dict["geometry"] is None:
                #        continue

                # Si QGIS asigna ID negativo o None → es nueva
                #    if feat_dict["id"] is None or feat_dict["id"] < 0:
                #        feat_dict["id"] = f"new_{feat.id()}"

                # Si no hay propiedad "name"
                #    if (
                #        "name" not in feat_dict["properties"]
                #        or not feat_dict["properties"]["name"]
                #    ):
                #        feat_dict["properties"]["name"] = "NULL"

                #   layer_data["features"].append(feat_dict)

                # Solo agregar capas con elementos
                # if layer_data["features"]:
                #    payload.append(layer_data)
                layer_data = self.serialize_layer(layer)
                payload.append(layer_data)

            json_data = json.dumps(payload, ensure_ascii=False, indent=2)

            json_text = json.dumps(json_data, indent=4, ensure_ascii=False)

            # QMessageBox.information(None, "=== JSON FINAL ENVIADO ===", json_text)

            req = urllib.request.Request(
                url="http://127.0.0.1:5000/sync",
                data=json_data.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req):
                QMessageBox.information(None, "Éxito", "Cambios enviados a la API.")

        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error al enviar: {str(e)}")
