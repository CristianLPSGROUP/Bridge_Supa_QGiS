import requests
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QDialog, QVBoxLayout, QLineEdit, QLabel, QPushButton
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

    def get_credentials(self):
        return {
            "email": self.email_input.text(),
            "password": self.password_input.text()
        }


class QgisSupabaseSyncPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.capas_api = []
        self.layer = None  # <<< IMPORTANTE
        self.access_token = None
        self.refresh_token = None

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

        # Set canvas to EPSG:4326 (WGS84 - standard GPS coordinates)
        from qgis.core import QgsCoordinateReferenceSystem
        canvas = self.iface.mapCanvas()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        canvas.setDestinationCrs(target_crs)

        # Add OpenStreetMap base layer by default
        self.agregar_mapa_base()

    def unload(self):
        self.iface.removeToolBarIcon(self.action_login)
        self.iface.removeToolBarIcon(self.action_load)
        self.iface.removeToolBarIcon(self.action_save)

    def login(self):
        """Show login dialog and authenticate with Supabase"""
        dialog = LoginDialog(self.iface.mainWindow())

        if dialog.exec_():
            creds = dialog.get_credentials()

            if not creds["email"] or not creds["password"]:
                QMessageBox.warning(None, "Error", "Por favor ingresa email y contraseña")
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
                user_id = data.get("user_id", "")

                self.iface.messageBar().pushSuccess("Login", f"Autenticado correctamente (User: {user_id})")

            except requests.exceptions.HTTPError as e:
                if response.status_code == 401:
                    QMessageBox.warning(None, "Error", "Email o contraseña incorrectos")
                else:
                    QMessageBox.critical(None, "Error", f"Error HTTP: {e}")
            except Exception as e:
                QMessageBox.critical(None, "Error", f"No se pudo conectar al servidor: {e}")

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
        No incluye id, created_at, o created_by (manejados por la API/DB)
        """
        geom = None
        try:
            geom = json.loads(feature.geometry().asJson())
        except Exception:
            geom = None

        props = {}
        for field in feature.fields():
            # Ignorar campos manejados por la base de datos
            if field.name() in ["id", "created_at", "created_by"]:
                continue

            val = feature.attribute(field.name())
            props[field.name()] = self.qvariant_to_python(val)

        return {"geometry": geom, "properties": props}

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

    # ================================================================
    #                          CARGAR CAPAS
    # ================================================================
    def agregar_mapa_base(self):
        """Add OpenStreetMap base layer if it doesn't exist already"""
        # Check if OpenStreetMap layer already exists
        existing_layers = QgsProject.instance().mapLayersByName("OpenStreetMap")
        if existing_layers:
            return  # Layer already exists, don't add duplicate

        url = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        layer = QgsRasterLayer(url, "OpenStreetMap", "wms")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)

    def cargar_capa(self):
        
        self.agregar_mapa_base()
        
        # Check if user is logged in
        if not self.access_token:
            QMessageBox.warning(None, "Error", "Debes iniciar sesión primero")
            return

        # Importar aquí para evitar error al iniciar QGIS
        from qgis.core import QgsJsonUtils, QgsCoordinateReferenceSystem

        # Force canvas to EPSG:4326 (WGS84 - standard GPS coordinates)
        canvas = self.iface.mapCanvas()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        canvas.setDestinationCrs(target_crs)

        # Obtener los extents del mapa actual (now in EPSG:4326)
        extent = canvas.extent()
        scale = canvas.scale()

        # Preparar el payload con los extents
        payload = {
            "extents": {
                "xMin": extent.xMinimum(),
                "xMax": extent.xMaximum(),
                "yMin": extent.yMinimum(),
                "yMax": extent.yMaximum(),
                "crs": "EPSG:4326",
                "zoom": scale,
                "max_zoom_out": 100000  # Ajusta este valor según necesites
            }
        }

        url = "http://127.0.0.1:8000/api/qgis/get_layer"

        # Prepare cookies with both tokens
        cookies = {}
        if self.access_token:
            cookies["access_token"] = self.access_token
        if self.refresh_token:
            cookies["refresh_token"] = self.refresh_token

        try:
            response = requests.post(url, json=payload, cookies=cookies)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                # Try to refresh token and retry
                if self.refresh_access_token():
                    cookies["access_token"] = self.access_token
                    cookies["refresh_token"] = self.refresh_token
                    try:
                        response = requests.post(url, json=payload, cookies=cookies)
                        response.raise_for_status()
                    except Exception as retry_error:
                        self.iface.messageBar().pushCritical("Error", "Sesión expirada. Por favor inicia sesión de nuevo")
                        return
                else:
                    self.iface.messageBar().pushCritical("Error", "Sesión expirada. Por favor inicia sesión de nuevo")
                    return
            elif response.status_code == 400:
                error_data = response.json()
                detail = error_data.get("detail", {})
                message = detail.get("message", "Por favor acércate más al mapa")
                self.iface.messageBar().pushWarning("Zoom muy alejado", message)
                return
            else:
                self.iface.messageBar().pushCritical("Error", f"Error HTTP: {e}")
                return
        except Exception as e:
            self.iface.messageBar().pushCritical("Error", f"No se pudo conectar: {e}")
            return

        response_data = response.json()
        features = response_data.get("features", [])

        if not features:
            self.iface.messageBar().pushInfo("Info", "No hay geometrías en esta área")
            return


        self.capas_api = []
        self.layer = None

        # Agrupar features por tipo de geometría
        features_by_type = {}
        for feat in features:
            geom = feat.get("geometry")
            if not geom:
                continue

            geom_type = geom.get("type", "Unknown")
            if geom_type not in features_by_type:
                features_by_type[geom_type] = []

            # Convertir formato de BD a formato esperado
            features_by_type[geom_type].append({
                "id": feat.get("id"),
                "geometry": geom,
                "properties": {
                    "id": feat.get("id"),
                    "created_at": feat.get("created_at"),
                    "created_by": feat.get("created_by")
                }
            })

        # Crear una capa por cada tipo de geometría
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

            mem_layer = QgsVectorLayer(
                f"{qgis_geom_type}?crs=EPSG:4326", layer_name, "memory"
            )
            prov = mem_layer.dataProvider()

            all_keys = sorted({key for f in feature_list for key in f["properties"].keys()})

            # Use the non-deprecated QgsField constructor (only name and type)
            prov.addAttributes([QgsField(key, QVariant.String) for key in all_keys])
            mem_layer.updateFields()

            feats = []
            for feat in feature_list:
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
        # Check if user is logged in
        if not self.access_token:
            QMessageBox.warning(None, "Error", "Debes iniciar sesión primero")
            return

        # Check if there are any vector layers in the project
        project_layers = list(QgsProject.instance().mapLayers().values())
        vector_layers = [layer for layer in project_layers if isinstance(layer, QgsVectorLayer)]

        if not vector_layers:
            QMessageBox.warning(None, "Error", "No hay capas vectoriales para subir.")
            return

        try:
            total_uploaded = 0
            duplicate_count = 0
            upload_errors = []

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

                if not layer_data or not layer_data.get("features"):
                    print(f"Capa sin features válidas: {layer.name()}")
                    continue

                # Preparar cookies para autenticación
                cookies = {}
                if self.access_token:
                    cookies["access_token"] = self.access_token
                if self.refresh_token:
                    cookies["refresh_token"] = self.refresh_token

                # URL del nuevo endpoint
                url = "http://127.0.0.1:8000/api/qgis/upload_geometries"

                try:
                    # Enviar la capa al servidor
                    response = requests.post(url, json=layer_data, cookies=cookies)
                    response.raise_for_status()

                    result = response.json()
                    total_uploaded += result.get("inserted", 0)
                    duplicate_count += result.get("duplicates", 0)

                    if result.get("errors"):
                        upload_errors.extend(result["errors"])

                except requests.exceptions.HTTPError as e:
                    if response.status_code == 401:
                        # Try to refresh token and retry
                        if self.refresh_access_token():
                            cookies["access_token"] = self.access_token
                            cookies["refresh_token"] = self.refresh_token
                            try:
                                response = requests.post(url, json=layer_data, cookies=cookies)
                                response.raise_for_status()

                                result = response.json()
                                total_uploaded += result.get("inserted", 0)
                                duplicate_count += result.get("duplicates", 0)

                                if result.get("errors"):
                                    upload_errors.extend(result["errors"])
                            except Exception:
                                QMessageBox.critical(None, "Error", "Sesión expirada. Por favor inicia sesión de nuevo")
                                return
                        else:
                            QMessageBox.critical(None, "Error", "Sesión expirada. Por favor inicia sesión de nuevo")
                            return
                    else:
                        upload_errors.append(f"Error en capa {layer.name()}: {str(e)}")
                        continue

            # Mostrar resumen de la operación
            message = f"Geometrías insertadas: {total_uploaded}"
            if duplicate_count > 0:
                message += f"\nDuplicadas (ignoradas): {duplicate_count}"
            if upload_errors:
                message += f"\n\nErrores encontrados: {len(upload_errors)}"

            QMessageBox.information(None, "Éxito", message)

        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error al enviar: {str(e)}")
