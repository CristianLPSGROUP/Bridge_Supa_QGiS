from cProfile import label

# from pyexpat import features

# from tkinter import dialog
# from urllib import response
import requests
from qgis.PyQt.QtWidgets import (
    QAction,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
)

from PyQt5.QtCore import QVariant

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsFeature,
    QgsProject,
    QgsField,
    QgsRasterLayer,
    QgsWkbTypes,
)
import json


class ConfirmDialog(QDialog):
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirmar Acción")
        self.setModal(True)

        layout = QVBoxLayout()

        layout.addWidget(QLabel(message))

        self.yes_button = QPushButton("Sí")
        self.yes_button.clicked.connect(self.accept)
        layout.addWidget(self.yes_button)

        self.no_button = QPushButton("No")
        self.no_button.clicked.connect(self.reject)
        layout.addWidget(self.no_button)

        self.setLayout(layout)


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Login - Supabase")
        self.setModal(True)

        layout = QVBoxLayout()

        # Email field
        layout.addWidget(QLabel("Email:"))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("usuario@ejemplo.com")
        layout.addWidget(self.email_input)

        # Password field
        layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("********")
        layout.addWidget(self.password_input)

        # Login button
        self.login_button = QPushButton("Iniciar Sesión")
        self.login_button.clicked.connect(self.accept)
        layout.addWidget(self.login_button)

        self.setLayout(layout)
        self.user_id = None
        self.projects = []
        self.selected_project_id = None

    def get_credentials(self):
        return {
            "email": self.email_input.text(),
            "password": self.password_input.text(),
        }


class QgisUtils:
    @staticmethod
    def establecer_crs_4326():
        """
        Establece automáticamente el CRS del proyecto a EPSG:4326
        """
        crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
        QgsProject.instance().setCrs(crs_4326)

    @staticmethod
    def agregar_mapa_base():
        """
        Agrega la capa OpenStreetMap solo si no existe ya en el proyecto
        """
        # Revisar si ya existe una capa llamada "OpenStreetMap"
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "OpenStreetMap":
                return  # Ya existe, no hacer nada

        url = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        layer = QgsRasterLayer(url, "OpenStreetMap", "wms")
        if layer.isValid():
            # Reproyectar a EPSG:4326
            crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
            layer.setCrs(crs_4326)
            QgsProject.instance().addMapLayer(layer)

    @staticmethod
    def limpiar_capas_api(capas_api):
        """
        Elimina del proyecto todas las capas cuyos IDs están en capas_api
        """
        project = QgsProject.instance()

        for layer_id in capas_api:
            layer = project.mapLayer(layer_id)
            if layer:  # solo elimina si la capa existe
                project.removeMapLayer(layer_id)

        capas_api.clear()


class QgisSupabaseSyncPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.capas_api = []
        self.layer = None  # <<< IMPORTANTE
        self.access_token = None
        self.refresh_token = None
        self.user_id = None
        # --- PROYECTOS ---
        self.projects = []
        self.selected_project_id = None

    def initGui(self):
        self.action_login = QAction("Login - Supabase", self.iface.mainWindow())
        self.action_login.triggered.connect(self.login)
        self.iface.addToolBarIcon(self.action_login)

        self.action_load = QAction("Cargar capa desde API", self.iface.mainWindow())
        self.action_load.triggered.connect(self.cargar_capa)
        self.iface.addToolBarIcon(self.action_load)

        self.action_save = QAction("Enviar cambios a API", self.iface.mainWindow())
        self.action_save.triggered.connect(self.guardar_cambios)
        self.iface.addToolBarIcon(self.action_save)

    def unload(self):
        self.iface.removeToolBarIcon(self.action_login)
        self.iface.removeToolBarIcon(self.action_load)
        self.iface.removeToolBarIcon(self.action_save)

    def confirm_action(self, message):
        dialog = ConfirmDialog(message, self.iface.mainWindow())
        return dialog.exec_() == QDialog.Accepted

    def mostrar_selector_proyectos(self):
        from qgis.PyQt.QtWidgets import QComboBox

        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Seleccionar proyecto")

        layout = QVBoxLayout()
        label = QLabel("Selecciona el proyecto activo:")
        combo = QComboBox()

        combo.addItem("Selecciona un proyecto", None)

        for p in self.projects:
            combo.addItem(p["project_name"], p["project_id"])
        btn = QPushButton("Aceptar")

        def aceptar():
            project_id = combo.currentData()
            if project_id is None:
                QMessageBox.warning(None, "Error", "Debes seleccionar un proyecto")
                return

            self.selected_project_id = project_id
            dialog.accept()

            self.iface.messageBar().pushSuccess(
                "Proyecto activo", f"Proyecto seleccionado (ID: {project_id})"
            )

        btn.clicked.connect(aceptar)

        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addWidget(btn)

        dialog.setLayout(layout)
        dialog.exec_()

    def login(self):
        QgisUtils.establecer_crs_4326()
        """Show login dialog and authenticate with Supabase"""
        dialog = LoginDialog(self.iface.mainWindow())

        if dialog.exec_():
            creds = dialog.get_credentials()

            if not creds["email"] or not creds["password"]:
                QMessageBox.warning(
                    None, "Error", "Por favor ingresa email y contraseña"
                )
                return

            try:
                # Make login request to API
                url = "http://127.0.0.1:8000/api/auth/login"
                response = requests.post(url, json=creds)
                response.raise_for_status()

                # Extract tokens from cookies
                if "access_token" in response.cookies:
                    self.access_token = response.cookies["access_token"]
                if "refresh_token" in response.cookies:
                    self.refresh_token = response.cookies["refresh_token"]

                data = response.json()

                self.user_id = data.get("user_id")
                self.projects = data.get("projects", [])
                self.selected_project_id = None

                # --- MOSTRAR SELECTOR DE PROYECTOS ---
                if not self.projects:
                    QMessageBox.warning(
                        None, "Sin proyectos", "No tienes proyectos asignados"
                    )
                    return

                self.iface.messageBar().pushSuccess(
                    "Login", f"Autenticado correctamente (User: {self.user_id})"
                )

                QgisUtils.agregar_mapa_base()
                # self.agregar_mapa_base()
                self.mostrar_selector_proyectos()

            except requests.exceptions.HTTPError as e:
                if response.status_code == 401:
                    QMessageBox.warning(None, "Error", "Email o contraseña incorrectos")
                else:
                    QMessageBox.critical(None, "Error", f"Error HTTP: {e}")
            except Exception as e:
                QMessageBox.critical(
                    None, "Error", f"No se pudo conectar al servidor: {e}"
                )

    def refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        if not self.refresh_token:
            return False

        try:
            url = "http://127.0.0.1:8000/api/auth/refresh"
            cookies = {"refresh_token": self.refresh_token}
            response = requests.post(url, cookies=cookies)
            response.raise_for_status()

            # Extract new tokens from cookies
            if "access_token" in response.cookies:
                self.access_token = response.cookies["access_token"]
            if "refresh_token" in response.cookies:
                self.refresh_token = response.cookies["refresh_token"]

            return True
        except Exception as e:
            print(f"Token refresh failed: {e}")
            return False

    def qvariant_to_python(self, value):
        # Esta función convierte QVariant a tipos nativos de Python
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
        PRESERVA el ID original.
        """
        geom = json.loads(feature.geometry().asJson())
        props = {
            field.name(): self.qvariant_to_python(feature.attribute(field.name()))
            for field in feature.fields()
        }
        feature_id = props.get("id")  # aquí preservamos el id original
        return {"geometry": geom, "properties": props, "id": feature_id}

    def serialize_layer(self, layer):
        """
        Serializa toda la capa a un dict con layer_name y features.
        Solo capas vectoriales.
        PRESERVA el ID original si existe.
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

    # ================================================================
    #                          CARGAR CAPAS
    # ================================================================

    def cargar_capa(self):
        QgisUtils.establecer_crs_4326()

        # Limpiar capas existentes de manera segura
        if hasattr(self, "capas_api") and self.capas_api:
            if not self.confirm_action(
                "Se eliminarán las capas actuales. ¿Deseas continuar?"
            ):
                return
        QgisUtils.limpiar_capas_api(self.capas_api)
        self.layer = None

        # Verificar login
        if not self.access_token:
            QMessageBox.warning(None, "Error", "Debes iniciar sesión primero")
            return

        # verificar proyecto seleccionado
        if not self.selected_project_id:
            QMessageBox.warning(
                None, "Error", "Debes seleccionar un proyecto antes de cargar capas"
            )
            return

        from qgis.core import (
            QgsJsonUtils,
            QgsCoordinateTransform,
            QgsCoordinateReferenceSystem,
        )

        # Obtener extents del mapa actual y transformarlos a EPSG:4326
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        scale = canvas.scale()
        source_crs = canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(
            source_crs, target_crs, QgsProject.instance()
        )
        extent_4326 = transform.transformBoundingBox(extent)

        payload = {
            "project_id": self.selected_project_id,
            "extents": {
                "xMin": extent_4326.xMinimum(),
                "xMax": extent_4326.xMaximum(),
                "yMin": extent_4326.yMinimum(),
                "yMax": extent_4326.yMaximum(),
                "crs": "EPSG:4326",
                "zoom": scale,
                "max_zoom_out": 1e9,
            },
        }

        url = "http://127.0.0.1:8000/api/qgis/get_layer"
        cookies = {}
        if self.access_token:
            cookies["access_token"] = self.access_token
        if self.refresh_token:
            cookies["refresh_token"] = self.refresh_token

        try:
            response = requests.post(url, json=payload, cookies=cookies)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.iface.messageBar().pushCritical("Error", f"No se pudo conectar: {e}")
            return

        response_data = response.json()
        features = response_data.get("features", [])
        if not features:
            self.iface.messageBar().pushInfo("Info", "No hay geometrías en esta área")
            return

        QgisUtils.agregar_mapa_base()

        # Inicializar lista de IDs de capas
        self.capas_api = []
        self.layer = None

        # Agrupar features por tipo de geometría
        features_by_type = {}
        for feat in features:
            geom = feat.get("geometry")
            if not geom:
                continue
            geom_type = geom.get("type", "Unknown")
            features_by_type.setdefault(geom_type, []).append(feat)

        # Crear capa por tipo de geometría
        for geom_type, feature_list in features_by_type.items():
            layer_name = f"QGIS_{geom_type}"
            if geom_type in ["Point", "MultiPoint"]:
                qgis_geom_type = "Point"
            elif geom_type in ["LineString", "MultiLineString"]:
                qgis_geom_type = "LineString"
            elif geom_type in ["Polygon", "MultiPolygon"]:
                qgis_geom_type = "Polygon"
            else:
                qgis_geom_type = "Unknown"
            # --- Crear capa de memoria ---
            mem_layer = QgsVectorLayer(
                f"{qgis_geom_type}?crs=EPSG:4326", layer_name, "memory"
            )
            prov = mem_layer.dataProvider()

            # Recolectar todos los atributos, asegurando que 'id' esté presente
            all_keys = sorted(
                set("id").union(
                    {
                        key
                        for f in feature_list
                        for key in f.get("properties", {}).keys()
                    }
                )
            )
            prov.addAttributes([QgsField(key, QVariant.String) for key in all_keys])
            mem_layer.updateFields()

            feats = []
            for feat in feature_list:
                f = QgsFeature()
                # Geometría
                geom_obj = QgsJsonUtils.geometryFromGeoJson(
                    json.dumps(feat.get("geometry"))
                )
                f.setGeometry(geom_obj)
                # Atributos, incluyendo id de BD
                attr_list = [
                    (
                        feat.get("properties", {}).get(key, "")
                        if key != "id"
                        else str(feat.get("id", ""))
                    )
                    for key in all_keys
                ]
                f.setAttributes(attr_list)
                feats.append(f)

            prov.addFeatures(feats)
            mem_layer.updateExtents()

            QgsProject.instance().addMapLayer(mem_layer)
            self.capas_api.append(mem_layer.id())

            if self.layer is None:
                self.layer = mem_layer

        self.iface.messageBar().pushSuccess("OK", "Capas cargadas correctamente")

    # ================================================================
    #                          GUARDAR CAMBIOS
    # ================================================================

    def guardar_cambios(self):
        # Verificar que el usuario esté logueado
        if not self.access_token:
            QMessageBox.warning(None, "Error", "Debes iniciar sesión primero")
            return

        try:
            # Recolectar todas las capas vectoriales con geometría
            layers_to_upload = [
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if isinstance(layer, QgsVectorLayer)
                and QgsWkbTypes.geometryType(layer.wkbType())
                != QgsWkbTypes.UnknownGeometry
                and layer.featureCount() > 0
            ]

            if not layers_to_upload:
                QMessageBox.information(
                    None, "Info", "No hay capas vectoriales con geometrías para enviar."
                )
                return

            # Preparar cookies
            cookies = {}
            if self.access_token:
                cookies["access_token"] = self.access_token
            if self.refresh_token:
                cookies["refresh_token"] = self.refresh_token

            url = "http://127.0.0.1:8000/api/qgis/upload_geometries"

            total_inserted = 0

            for layer in layers_to_upload:
                layer_data = self.serialize_layer(layer)
                if not layer_data or not layer_data.get("features"):
                    continue

                payload = {
                    "project_id": self.selected_project_id,  # <- aquí va el project_id seleccionado
                    "features": layer_data["features"],
                }

                try:
                    response = requests.post(url, json=payload, cookies=cookies)
                    response.raise_for_status()
                    result = response.json()
                    total_inserted += result.get("inserted", 0)
                except requests.exceptions.HTTPError as e:
                    # Intentar refrescar token en caso de 401
                    if response.status_code == 401 and self.refresh_access_token():
                        cookies["access_token"] = self.access_token
                        cookies["refresh_token"] = self.refresh_token
                        response = requests.post(url, json=layer_data, cookies=cookies)
                        response.raise_for_status()
                        result = response.json()
                        total_inserted += result.get("inserted", 0)
                    else:
                        QMessageBox.critical(
                            None,
                            "Error",
                            f"No se pudo enviar la capa {layer.name()}: {e}",
                        )
                        continue

            # Mostrar el mensaje directamente desde el servidor
            if total_inserted == 0:
                QMessageBox.information(None, "Info", "No hay nuevos cambios")
            else:
                QMessageBox.information(
                    None, "Éxito", "Se grabaron los datos correctamente"
                )

        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error al enviar: {str(e)}")
