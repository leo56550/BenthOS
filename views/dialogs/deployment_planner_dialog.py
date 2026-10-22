"""Dialog de planification de deploiement — carte Leaflet interactive + liste de waypoints."""

import csv
import json
import os
import sys
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

from services.campaign_service import find_campaign_gps_points


def _resource(rel: str) -> str:
    """Chemin absolu d'un asset — compatible dev et PyInstaller (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.normpath(os.path.join(base, rel))


_MAP_HTML_PATH = _resource("assets/planner_map.html")

# ── Bridge Python <-> JS ─────────────────────────────────────────────────────

class _PlanBridge(QtCore.QObject):
    pointAdded = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot(str)
    def onPointAdded(self, payload: str):
        self.pointAdded.emit(payload)

# ── Styles ────────────────────────────────────────────────────────────────────

_STYLE = """
QDialog { background-color: #111820; font-family: 'Segoe UI', sans-serif; }
QLabel  { color: #7ec8e3; font-size: 11px; border: none; }
QLineEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QLineEdit:focus { border-color: #2778A2; }
QDateEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QDateEdit::drop-down { border: none; width: 18px; }
QDateEdit:focus { border-color: #2778A2; }
QListWidget {
    background-color: #0d1a27; color: #F2BFB4;
    border: 1px solid #1e3448; border-radius: 4px;
    font-size: 11px; outline: none;
}
QListWidget::item { padding: 7px 10px; border-bottom: 1px solid #1a2a38; }
QListWidget::item:selected { background-color: #20415D; color: #fff; }
QPushButton {
    background-color: #20415D; color: white; font-weight: bold;
    border: 1px solid #2778A2; border-radius: 4px;
    padding: 6px 14px; font-size: 11px;
}
QPushButton:hover { background-color: #2778A2; }
QPushButton#btn_delete { background-color: #3a1010; color: #e57373; border-color: #7a2020; }
QPushButton#btn_delete:hover { background-color: #7a2020; color: #fff; }
QPushButton#btn_clear  { background-color: #2a1a10; color: #e6a06e; border-color: #7a4010; }
QPushButton#btn_clear:hover  { background-color: #7a4010; color: #fff; }
QFrame#sep { border: none; border-top: 1px solid #1e3448; max-height: 1px; }
"""

def _lbl(text: str) -> QtWidgets.QLabel:
    l = QtWidgets.QLabel(text)
    l.setStyleSheet("color: #7ec8e3; font-size: 10px; border: none;")
    return l

def _sep() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setObjectName("sep")
    f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    return f

# ── Dialog ────────────────────────────────────────────────────────────────────

class DeploymentPlannerDialog(QtWidgets.QDialog):
    """Dialog de planification : carte Leaflet + liste de waypoints nommables."""

    def __init__(self, parent=None, language: str = 'fr'):
        super().__init__(parent)
        self.current_language = language
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.setWindowTitle(self.translate("Planification de deploiement", "Deployment planning"))
        self.setModal(True)
        self.resize(1150, 700)
        self.setStyleSheet(_STYLE)

        self._points: list[dict] = []
        self._updating_name   = False
        self._undo_stack: list[list[dict]] = []
        self._batch_importing = False          # True pendant loadImportedPoints
        self._name_edit_undo_pushed  = False   # évite push à chaque frappe
        self._date_edit_undo_pushed  = False

        self._bridge  = _PlanBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("planBridge", self._bridge)
        self._bridge.pointAdded.connect(self._on_point_added)

        self._build_ui()

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    # ── Undo ─────────────────────────────────────────────────────────────────

    def _push_undo_state(self):
        import copy
        self._undo_stack.append(copy.deepcopy(self._points))

    def _undo(self):
        if not self._undo_stack:
            return
        self._points = self._undo_stack.pop()
        self._map_view.page().runJavaScript(
            f"rebuildMarkers({json.dumps(self._points)});"
        )
        self._edit_name.clear()
        self._edit_name.setEnabled(False)
        self._refresh_list()

    def keyPressEvent(self, event):
        if (event.key() == QtCore.Qt.Key.Key_Z
                and event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier):
            self._undo()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Barre titre
        header = QtWidgets.QWidget()
        header.setStyleSheet("background-color: #0d1520; border-bottom: 1px solid #1e3448;")
        header.setFixedHeight(44)
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl_title = QtWidgets.QLabel(self.translate("Planification de deploiement", "Deployment planning"))
        lbl_title.setStyleSheet("color: #F2BFB4; font-size: 14px; font-weight: bold; border: none;")
        hl.addWidget(lbl_title)
        hl.addStretch()
        hl.addWidget(QtWidgets.QLabel(self.translate(
            "Cliquez sur la carte pour poser un waypoint", "Click on the map to place a waypoint"
        )))
        root.addWidget(header)

        # Corps
        body = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        body.setHandleWidth(2)
        body.setStyleSheet("QSplitter::handle { background: #1e3448; }")

        # Carte
        self._map_view = QWebEngineView()
        # Autoriser le fichier local à charger des ressources distantes (Leaflet CDN)
        # et des ressources QRC (qwebchannel.js)
        s = self._map_view.page().settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._map_view.page().setWebChannel(self._channel)
        self._map_view.setUrl(QtCore.QUrl.fromLocalFile(_MAP_HTML_PATH))
        body.addWidget(self._map_view)

        # ── Panneau droit ─────────────────────────────────────────────────
        right = QtWidgets.QWidget()
        right.setStyleSheet("background-color: #0d1520;")
        right.setMinimumWidth(250)
        right.setMaximumWidth(340)
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(14, 14, 14, 14)
        rl.setSpacing(8)

        # Date de deploiement
        rl.addWidget(_lbl(self.translate("Date de deploiement", "Deployment date")))
        self._date_edit = QtWidgets.QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QtCore.QDate.currentDate())
        self._date_edit.setDisplayFormat("dd/MM/yyyy")
        rl.addWidget(self._date_edit)

        rl.addWidget(_sep())

        # Chargement infoStation
        lbl_info = QtWidgets.QLabel(self.translate("Infostation de référence", "Reference infostation"))
        lbl_info.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 12px; border: none;")
        rl.addWidget(lbl_info)

        btn_load_info = QtWidgets.QPushButton(self.translate("CHARGER infostation", "LOAD infostation"))
        btn_load_info.setStyleSheet(
            "QPushButton { background-color: #1a3010; color: #e68c14;"
            " border: 1px solid #e68c14; border-radius: 4px;"
            " padding: 6px 14px; font-size: 11px; font-weight: bold; }"
            " QPushButton:hover { background-color: #e68c14; color: #fff; }"
        )
        btn_load_info.clicked.connect(self._load_infostation)
        rl.addWidget(btn_load_info)

        btn_compare_campaign = QtWidgets.QPushButton(
            self.translate("Charger campagne", "LOAD campaign"))
        btn_compare_campaign.setStyleSheet(
            "QPushButton { background-color: #2a1a3a; color: #b98ce6;"
            " border: 1px solid #9B59B6; border-radius: 4px;"
            " padding: 6px 14px; font-size: 11px; font-weight: bold; }"
            " QPushButton:hover { background-color: #9B59B6; color: #fff; }"
        )
        btn_compare_campaign.clicked.connect(self._compare_with_campaign)
        rl.addWidget(btn_compare_campaign)

        self._lbl_infostation_info = QtWidgets.QLabel("")
        self._lbl_infostation_info.setWordWrap(True)
        self._lbl_infostation_info.setStyleSheet(
            "color: #7ec8e3; font-size: 10px; border: none; font-style: italic;")
        rl.addWidget(self._lbl_infostation_info)

        rl.addWidget(_sep())

        # Liste waypoints
        lbl_wp = QtWidgets.QLabel("Waypoints")
        lbl_wp.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 12px; border: none;")
        rl.addWidget(lbl_wp)

        self._list = QtWidgets.QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        rl.addWidget(self._list, stretch=1)

        # Edition du nom du point selectionne
        self._edit_name_lbl = _lbl(self.translate("Nom du point selectionne", "Selected point name"))
        rl.addWidget(self._edit_name_lbl)
        self._edit_name = QtWidgets.QLineEdit()
        self._edit_name.setPlaceholderText(self.translate("Nom du waypoint...", "Waypoint name..."))
        self._edit_name.setEnabled(False)
        self._edit_name.textEdited.connect(self._on_name_edited)
        rl.addWidget(self._edit_name)

        self._edit_point_date_lbl = _lbl(self.translate("Date du point", "Point date"))
        rl.addWidget(self._edit_point_date_lbl)
        self._edit_point_date = QtWidgets.QDateEdit()
        self._edit_point_date.setCalendarPopup(True)
        self._edit_point_date.setDisplayFormat("dd/MM/yyyy")
        self._edit_point_date.setDate(QtCore.QDate.currentDate())
        self._edit_point_date.setEnabled(False)
        self._edit_point_date.dateChanged.connect(self._on_point_date_changed)
        rl.addWidget(self._edit_point_date)

        rl.addWidget(_sep())

        # ── Ajout par coordonnées ─────────────────────────────────────────
        lbl_coords = QtWidgets.QLabel(self.translate(
            "Ajouter un point par coordonnées", "Add point by coordinates"))
        lbl_coords.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 11px; border: none;")
        rl.addWidget(lbl_coords)

        coords_row = QtWidgets.QHBoxLayout()
        coords_row.setSpacing(4)
        self._edit_lat = QtWidgets.QLineEdit()
        self._edit_lat.setPlaceholderText("Lat (ex: 47.5)")
        self._edit_lng = QtWidgets.QLineEdit()
        self._edit_lng.setPlaceholderText("Lng (ex: -3.5)")
        coords_row.addWidget(self._edit_lat)
        coords_row.addWidget(self._edit_lng)
        rl.addLayout(coords_row)

        self._edit_coord_name = QtWidgets.QLineEdit()
        self._edit_coord_name.setPlaceholderText(
            self.translate("Nom du point (optionnel)", "Point name (optional)"))
        rl.addWidget(self._edit_coord_name)

        btn_add_coords = QtWidgets.QPushButton(
            self.translate("Ajouter ce point", "Add this point"))
        btn_add_coords.clicked.connect(self._add_point_by_coords)
        rl.addWidget(btn_add_coords)

        rl.addWidget(_sep())

        btn_clr = QtWidgets.QPushButton(self.translate("Tout effacer", "Clear all"))
        btn_clr.setObjectName("btn_clear")
        btn_clr.clicked.connect(self._clear_all)
        rl.addWidget(btn_clr)

        rl.addWidget(_sep())

        btn_send = QtWidgets.QPushButton(self.translate("Envoyer vers KOSMOS", "Send to KOSMOS"))
        btn_send.setStyleSheet(
            "QPushButton { background-color: #1a3a1a; color: #4CAF50;"
            " border: 1px solid #4CAF50; border-radius: 4px;"
            " padding: 6px 14px; font-size: 11px; font-weight: bold; }"
            " QPushButton:hover { background-color: #4CAF50; color: #fff; }"
        )
        btn_send.clicked.connect(self._send_to_kosmos)
        rl.addWidget(btn_send)


        body.addWidget(right)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        root.addWidget(body, stretch=1)

        # Pied de page
        footer = QtWidgets.QWidget()
        footer.setStyleSheet("background-color: #0d1520; border-top: 1px solid #1e3448;")
        footer.setFixedHeight(44)
        fl = QtWidgets.QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        self._lbl_count = QtWidgets.QLabel("0 waypoint(s)")
        self._lbl_count.setStyleSheet("color: #556677; font-size: 10px; border: none;")
        fl.addWidget(self._lbl_count)
        fl.addStretch()
        btn_close = QtWidgets.QPushButton(self.translate("Fermer", "Close"))
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.reject)
        fl.addWidget(btn_close)
        root.addWidget(footer)

    # ── Infostation ──────────────────────────────────────────────────────────

    def _load_infostation(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, self.translate("Charger des fichiers infoStation", "Load infoStation file(s)"), "",
            self.translate(
                "Infostation (*.csv *.CSV *.xlsx *.xls *.txt);;Tous les fichiers (*)",
                "Infostation (*.csv *.CSV *.xlsx *.xls *.txt);;All files (*)",
            )
        )
        if not paths:
            return

        all_points = []
        campaign_name = ""
        year = ""

        for path in paths:
            try:
                rows = []
                ext = os.path.splitext(path)[1].lower()
                if ext in ('.xlsx', '.xls'):
                    try:
                        import openpyxl as _opxl
                        wb = _opxl.load_workbook(path, data_only=True)
                        ws = wb.active
                        hdrs = [str(c.value or '').strip()
                                for c in next(ws.iter_rows(min_row=1, max_row=1))]
                        for row_vals in ws.iter_rows(min_row=2, values_only=True):
                            rows.append({hdrs[i]: (str(v) if v is not None else '')
                                         for i, v in enumerate(row_vals)})
                    except Exception as xe:
                        raise RuntimeError(f"Impossible de lire le fichier Excel : {xe}")
                else:
                    for enc in ("cp1252", "utf-8-sig", "utf-8", "latin-1"):
                        try:
                            with open(path, newline='', encoding=enc) as f:
                                sample = f.read(4096)
                            delim = ';' if sample.count(';') >= sample.count(',') else ','
                            with open(path, newline='', encoding=enc) as f:
                                reader = csv.DictReader(f, delimiter=delim)
                                rows = list(reader)
                            if rows:
                                break
                        except (UnicodeDecodeError, Exception):
                            rows = []

                # Index insensible à la casse/espaces, robuste aux clés None
                def _get(row, *keys):
                    row_low = {str(k).strip().lower(): v
                               for k, v in row.items() if k is not None}
                    for k in keys:
                        v = row_low.get(k.lower().strip(), "")
                        if v:
                            return str(v).strip()
                    return ""

                for row in rows:
                    try:
                        lat = float(_get(row, "Latitude").replace(",", "."))
                        lng = float(_get(row, "Longitude").replace(",", "."))
                    except (ValueError, TypeError):
                        continue

                    code = _get(row, "Codestation")
                    nom  = _get(row, "Nom du point", "Nom du point GPS", "Point")
                    date = _get(row, "Date")

                    if not campaign_name:
                        campaign_name = _get(row, "Nom campagne", "Campagne")
                    if not year and date:
                        parts = date.split("/")
                        if len(parts) == 3 and len(parts[2]) == 4:
                            year = parts[2]

                    all_points.append({
                        "lat": lat, "lng": lng,
                        "code": code, "nom": nom or code, "date": date,
                    })

            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, self.translate("Erreur", "Error"),
                    self.translate(f"Impossible de lire :\n{path}\n{e}",
                                   f"Unable to read:\n{path}\n{e}")
                )

        if not all_points:
            QtWidgets.QMessageBox.warning(
                self, self.translate("Aucun point", "No points"),
                self.translate(
                    "Aucun point avec coordonnées valides trouvé dans les fichiers sélectionnés.",
                    "No point with valid coordinates found in the selected files."
                ))
            return

        # Ajouter comme vrais waypoints (marqueurs bleus numérotés, dans la liste)
        self._push_undo_state()
        self._batch_importing = True
        self._map_view.page().runJavaScript(
            f"loadImportedPoints({json.dumps(all_points)});"
        )
        QtCore.QTimer.singleShot(1500, lambda: setattr(self, '_batch_importing', False))

        # Auto-remplir la mission et l'année
        if year:
            try:
                d = self._date_edit.date()
                self._date_edit.setDate(QtCore.QDate(int(year), d.month(), d.day()))
            except Exception:
                pass

        # Info label
        n_files = len(paths)
        info = self.translate(
            f"{len(all_points)} point(s) ajouté(s) depuis {n_files} fichier(s)",
            f"{len(all_points)} point(s) added from {n_files} file(s)",
        )
        if campaign_name:
            info += self.translate(f"\nCampagne : {campaign_name}", f"\nCampaign: {campaign_name}")
        if year:
            info += self.translate(f"  —  Année : {year}", f"  —  Year: {year}")
        self._lbl_infostation_info.setText(info)

    def _clear_infostation(self):
        self._map_view.page().runJavaScript("clearInfostationMarkers();")
        self._lbl_infostation_info.setText("")

    def _compare_with_campaign(self):
        """Choisit un dossier de campagne et affiche ses points GPS (issus des _temp.json
        de chaque vidéo) sur la carte, avec les mêmes marqueurs que "CHARGER infostation" —
        pour comparer visuellement les points prévus (posés à la main) aux points réellement
        filmés."""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.translate("Choisir un dossier de campagne", "Choose a campaign folder")
        )
        if not folder:
            return

        points = find_campaign_gps_points(folder)
        if not points:
            QtWidgets.QMessageBox.warning(
                self, self.translate("Aucun point", "No points"),
                self.translate(
                    "Aucune vidéo avec coordonnées GPS trouvée dans ce dossier de campagne.",
                    "No video with GPS coordinates found in this campaign folder."
                ))
            return

        self._push_undo_state()
        self._batch_importing = True
        self._map_view.page().runJavaScript(
            f"loadImportedPoints({json.dumps(points)});"
        )
        QtCore.QTimer.singleShot(1500, lambda: setattr(self, '_batch_importing', False))

        info = self.translate(
            f"{len(points)} point(s) de campagne ajouté(s) aux waypoints",
            f"{len(points)} campaign point(s) added to waypoints"
        )
        info += self.translate(f"\nDossier : {os.path.basename(folder)}",
                               f"\nFolder: {os.path.basename(folder)}")
        self._lbl_infostation_info.setText(info)

    # ── Gestion des points ────────────────────────────────────────────────────

    @staticmethod
    def _parse_point_date(raw: str, fallback: QtCore.QDate) -> str:
        """Normalise une date vers yyyy-MM-dd.
        Accepte : YYYYMMDD, YYMMDD, DD/MM/YYYY, yyyy-MM-dd."""
        if raw:
            s = raw.strip()
            # DD/MM/YYYY
            parts = s.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            # yyyy-MM-dd
            if len(s) == 10 and s[4] == "-":
                return s
            # YYYYMMDD ou YYMMDD (chiffres seuls)
            digits = "".join(c for c in s if c.isdigit())
            if len(digits) == 8:
                return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
            if len(digits) == 6:
                return f"20{digits[:2]}-{digits[2:4]}-{digits[4:6]}"
        return fallback.toString("yyyy-MM-dd")

    def _add_point_by_coords(self):
        """Ajoute un waypoint depuis les champs lat/lng saisis manuellement."""
        try:
            lat = float(self._edit_lat.text().strip().replace(",", "."))
            lng = float(self._edit_lng.text().strip().replace(",", "."))
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self,
                self.translate("Coordonnées invalides", "Invalid coordinates"),
                self.translate(
                    "Veuillez saisir une latitude et une longitude numériques.",
                    "Please enter numeric latitude and longitude values.",
                ),
            )
            return
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            QtWidgets.QMessageBox.warning(
                self,
                self.translate("Coordonnées hors limites", "Out-of-range coordinates"),
                self.translate(
                    "Latitude [-90 ; 90]  —  Longitude [-180 ; 180].",
                    "Latitude [-90 ; 90]  —  Longitude [-180 ; 180].",
                ),
            )
            return
        name = self._edit_coord_name.text().strip()
        safe_name = name.replace("'", "\\'") if name else ""
        self._map_view.page().runJavaScript(
            f"addWaypointAtCoords({lat}, {lng}, '{safe_name}');"
        )
        self._edit_lat.clear()
        self._edit_lng.clear()
        self._edit_coord_name.clear()

    def _on_point_added(self, payload: str):
        try:
            data = json.loads(payload)
        except Exception:
            return
        if not self._batch_importing:
            self._push_undo_state()
        date_iso = self._parse_point_date(data.get("date", ""), self._date_edit.date())
        self._points.append({
            "label":   data.get("label", f"Point {len(self._points)+1}"),
            "lat":     float(data["lat"]),
            "lng":     float(data["lng"]),
            "date":    date_iso,
            "source":  data.get("source", "manual"),
            "iconTxt": data.get("iconTxt", ""),
        })
        self._refresh_list()
        # Selectionner le nouveau point
        self._list.setCurrentRow(len(self._points) - 1)

    def _refresh_list(self):
        current = self._list.currentRow()
        self._list.clear()
        for i, p in enumerate(self._points):
            item = QtWidgets.QListWidgetItem(
                f"  {i+1}.  {p['label']}\n"
                f"       {p['lat']:.6f},  {p['lng']:.6f}"
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        n = len(self._points)
        self._lbl_count.setText(f"{n} waypoint{'s' if n != 1 else ''}")
        if 0 <= current < self._list.count():
            self._list.setCurrentRow(current)

    def _on_selection_changed(self, row: int):
        self._name_edit_undo_pushed = False
        self._date_edit_undo_pushed = False
        if row < 0 or row >= len(self._points):
            self._edit_name.setEnabled(False)
            self._edit_name.clear()
            self._edit_point_date.setEnabled(False)
            return
        self._edit_name.setEnabled(True)
        self._updating_name = True
        self._edit_name.setText(self._points[row]["label"])
        self._updating_name = False
        # Date du point
        self._edit_point_date.setEnabled(True)
        date_str = self._points[row].get("date", "")
        qdate = QtCore.QDate.fromString(date_str, "yyyy-MM-dd")
        if not qdate.isValid():
            qdate = self._date_edit.date()
        self._edit_point_date.blockSignals(True)
        self._edit_point_date.setDate(qdate)
        self._edit_point_date.blockSignals(False)

    def _on_point_date_changed(self, qdate: QtCore.QDate):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._points):
            return
        if not self._date_edit_undo_pushed:
            self._push_undo_state()
            self._date_edit_undo_pushed = True
        self._points[row]["date"] = qdate.toString("yyyy-MM-dd")

    def _on_name_edited(self, text: str):
        if self._updating_name:
            return
        row = self._list.currentRow()
        if row < 0 or row >= len(self._points):
            return
        if not self._name_edit_undo_pushed:
            self._push_undo_state()
            self._name_edit_undo_pushed = True
        name = text.strip() or f"Point {row+1}"
        self._points[row]["label"] = name
        # Mettre a jour le marqueur JS
        safe = name.replace("'", "\\'")
        self._map_view.page().runJavaScript(f"updateMarkerLabel({row}, '{safe}');")
        # Mettre a jour l'item de la liste sans perdre le focus
        item = self._list.item(row)
        if item:
            item.setText(
                f"  {row+1}.  {name}\n"
                f"       {self._points[row]['lat']:.6f},  {self._points[row]['lng']:.6f}"
            )

    def _delete_selected(self):
        sel = self._list.selectedItems()
        if not sel:
            return
        idx = sel[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._map_view.page().runJavaScript(f"removeMarkerByIndex({idx});")
        del self._points[idx]
        self._edit_name.clear()
        self._edit_name.setEnabled(False)
        self._refresh_list()

    def _clear_all(self):
        if not self._points:
            return
        reply = QtWidgets.QMessageBox.question(
            self, self.translate("Confirmer", "Confirm"),
            self.translate("Effacer tous les waypoints ?", "Clear all waypoints?"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._push_undo_state()
        self._map_view.page().runJavaScript("clearAllMarkers();")
        self._points.clear()
        self._edit_name.clear()
        self._edit_name.setEnabled(False)
        self._refresh_list()

    # ── JSON payload (partagé entre export et envoi SFTP) ────────────────────

    def _build_json_bytes(self) -> bytes:
        payload = {
            "mission":          None,
            "date_deploiement": self._date_edit.date().toString("yyyy-MM-dd"),
            "waypoints": [
                {
                    "index":     i + 1,
                    "label":     p["label"],
                    "latitude":  round(p["lat"], 6),
                    "longitude": round(p["lng"], 6),
                    "date":      p.get("date", ""),
                }
                for i, p in enumerate(self._points)
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    # ── Export JSON local ─────────────────────────────────────────────────────

    def _export_json(self):
        if not self._points:
            QtWidgets.QMessageBox.information(
                self, "Export", self.translate("Aucun waypoint à exporter.", "No waypoint to export.")
            )
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, self.translate("Exporter le plan de deploiement", "Export the deployment plan"),
            f"deploiement_{self._date_edit.date().toString('yyyyMMdd')}.json",
            "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, 'wb') as f:
                f.write(self._build_json_bytes())
            QtWidgets.QMessageBox.information(
                self, self.translate("Export réussi", "Export successful"),
                self.translate(
                    f"{len(self._points)} waypoints exportés vers :\n{path}",
                    f"{len(self._points)} waypoints exported to:\n{path}"
                )
            )
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, self.translate("Erreur export", "Export error"), str(e))

    # ── Envoi SFTP vers KOSMOS ────────────────────────────────────────────────

    def _send_to_kosmos(self):
        if not self._points:
            QtWidgets.QMessageBox.information(
                self, self.translate("Envoi", "Send"),
                self.translate("Aucun waypoint à envoyer.", "No waypoint to send.")
            )
            return
        # Récupérer la bbox visible Leaflet avant d'ouvrir le dialog
        json_bytes = self._build_json_bytes()
        date_str   = self._date_edit.date().toString("yyyyMMdd")
        self._map_view.page().runJavaScript(
            "JSON.stringify(map.getBounds());",
            lambda result: self._open_deploy_dialog(result, json_bytes, date_str)
        )

    def _open_deploy_dialog(self, bounds_json: str, json_bytes: bytes, date_str: str):
        viewport_bounds = None
        try:
            b = json.loads(bounds_json or "{}")
            sw = b.get("_southWest", {})
            ne = b.get("_northEast", {})
            if sw and ne:
                viewport_bounds = {
                    "lat_min": sw["lat"], "lat_max": ne["lat"],
                    "lng_min": sw["lng"], "lng_max": ne["lng"],
                }
        except Exception:
            pass
        dlg = _SftpDeployDialog(
            json_bytes=json_bytes,
            date_str=date_str,
            waypoints=self._points,
            viewport_bounds=viewport_bounds,
            parent=self,
            language=self.current_language,
        )
        dlg.exec()




# ── Style commun ─────────────────────────────────────────────────────────────

_SFTP_STYLE = """
QDialog { background-color: #111820; font-family: 'Segoe UI', sans-serif; }
QLabel  { color: #7ec8e3; font-size: 11px; border: none; }
QLineEdit {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 4px 7px; font-size: 11px;
}
QLineEdit:focus { border-color: #2778A2; }
QSpinBox {
    background-color: #162433; color: #F2BFB4;
    border: 1px solid #2a4057; border-radius: 3px;
    padding: 3px 6px; font-size: 11px;
}
QPushButton {
    background-color: #20415D; color: white; font-weight: bold;
    border: 1px solid #2778A2; border-radius: 4px;
    padding: 6px 16px; font-size: 11px;
}
QPushButton:hover { background-color: #2778A2; }
QPushButton:disabled { background-color: #1a2030; color: #555; border-color: #333; }
QProgressBar {
    border: 1px solid #2778A2; border-radius: 3px;
    background-color: #0d1520; height: 10px; text-align: center;
}
QProgressBar::chunk { background-color: #4CAF50; border-radius: 2px; }
QTextEdit {
    background-color: #0a1218; color: #a0b8c8;
    border: 1px solid #1e3448; border-radius: 3px;
    font-family: Consolas, monospace; font-size: 10px;
}
"""


class _SftpDeployDialog(QtWidgets.QDialog):
    """Envoie le JSON de waypoints + toutes les tuiles OSM visibles vers le KOSMOS."""

    def __init__(self, json_bytes, date_str, waypoints, viewport_bounds=None,
                 parent=None, language='fr'):
        super().__init__(parent)
        self.current_language  = language
        self._json_bytes       = json_bytes
        self._date_str         = date_str
        self._waypoints        = waypoints
        self._viewport_bounds  = viewport_bounds
        self._worker           = None

        self.setWindowTitle(self.translate("Envoyer vers KOSMOS", "Send to KOSMOS"))
        self.setModal(True)
        self.resize(520, 560)
        self.setStyleSheet(_SFTP_STYLE)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        def _row(label, widget):
            r = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFixedWidth(130)
            r.addWidget(lbl)
            r.addWidget(widget)
            root.addLayout(r)

        # ── Connexion SFTP ────────────────────────────────────────────────
        lbl_sftp = QtWidgets.QLabel("SFTP")
        lbl_sftp.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 12px; border: none;")
        root.addWidget(lbl_sftp)

        self._ip   = QtWidgets.QLineEdit("192.168.10.2")
        self._port = QtWidgets.QLineEdit("22")
        self._port.setFixedWidth(55)
        self._user = QtWidgets.QLineEdit("kosmos")
        self._pwd  = QtWidgets.QLineEdit("kosmos")
        self._pwd.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._remote_deploy_dir = QtWidgets.QLineEdit("/home/kosmos/deployments")

        _row(self.translate("Adresse IP :", "IP Address:"), self._ip)
        _row(self.translate("Port :", "Port:"), self._port)
        _row(self.translate("Utilisateur :", "User:"), self._user)
        _row(self.translate("Mot de passe :", "Password:"), self._pwd)
        _row(self.translate("Dossier :", "Folder:"), self._remote_deploy_dir)

        lbl_struct = QtWidgets.QLabel(
            self.translate("  → JSON + tiles/sat/ + tiles/seamark/", "  → JSON + tiles/sat/ + tiles/seamark/"))
        lbl_struct.setStyleSheet("color: #556677; font-size: 10px; border: none; font-style: italic;")
        root.addWidget(lbl_struct)

        # ── Niveaux de zoom ───────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #1e3448; max-height: 1px;")
        root.addWidget(sep)

        lbl_zoom = QtWidgets.QLabel(self.translate("Niveaux de zoom des tuiles", "Tile zoom levels"))
        lbl_zoom.setStyleSheet("color: #F2BFB4; font-weight: bold; font-size: 11px; border: none;")
        root.addWidget(lbl_zoom)

        zoom_row = QtWidgets.QHBoxLayout()
        zoom_row.addWidget(QtWidgets.QLabel(self.translate("De z=", "From z=")))
        self._z_min = QtWidgets.QSpinBox()
        self._z_min.setRange(0, 19); self._z_min.setValue(8); self._z_min.setFixedWidth(55)
        zoom_row.addWidget(self._z_min)
        zoom_row.addWidget(QtWidgets.QLabel(self.translate("  a z=", "  to z=")))
        self._z_max = QtWidgets.QSpinBox()
        self._z_max.setRange(0, 19); self._z_max.setValue(16); self._z_max.setFixedWidth(55)
        zoom_row.addWidget(self._z_max)
        zoom_row.addStretch()
        root.addLayout(zoom_row)

        self._lbl_estimate = QtWidgets.QLabel("")
        self._lbl_estimate.setStyleSheet("color: #7ec8e3; font-size: 10px; border: none;")
        root.addWidget(self._lbl_estimate)
        self._z_min.valueChanged.connect(self._update_estimate)
        self._z_max.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        # ── Log ───────────────────────────────────────────────────────────
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep2.setStyleSheet("border: none; border-top: 1px solid #1e3448; max-height: 1px;")
        root.addWidget(sep2)

        self._log_edit = QtWidgets.QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setFixedHeight(130)
        root.addWidget(self._log_edit)

        # ── Progression ───────────────────────────────────────────────────
        self._progress = QtWidgets.QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ── Boutons ───────────────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QtWidgets.QPushButton(self.translate("Annuler", "Cancel"))
        self._btn_cancel.clicked.connect(self._cancel)
        self._btn_send = QtWidgets.QPushButton(self.translate("Envoyer", "Send"))
        self._btn_send.setStyleSheet(
            "QPushButton { background-color: #1a3a1a; color: #4CAF50;"
            " border: 1px solid #4CAF50; border-radius: 4px; padding: 6px 20px; font-weight: bold; }"
            " QPushButton:hover { background-color: #4CAF50; color: #fff; }"
            " QPushButton:disabled { background-color: #1a2030; color: #555; border-color: #333; }"
        )
        self._btn_send.clicked.connect(self._do_send)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_send)
        root.addLayout(btn_row)

    def translate(self, fr, en):
        return fr if self.current_language == 'fr' else en

    def _get_tiles(self):
        from services.sftp_service import compute_tiles
        z_min = self._z_min.value()
        z_max = max(z_min, self._z_max.value())
        if self._viewport_bounds:
            b = self._viewport_bounds
            pts = [{"lat": b["lat_min"], "lng": b["lng_min"]},
                   {"lat": b["lat_max"], "lng": b["lng_max"]}]
            return compute_tiles(pts, z_min, z_max, margin_km=0)
        return compute_tiles(self._waypoints or [], z_min, z_max, margin_km=5.0)

    def _update_estimate(self):
        try:
            n = len(self._get_tiles()) * 2  # sat + seamark
            mb = n * 30 / 1024
            self._lbl_estimate.setText(
                self.translate(f"~{n} tuile(s) (sat+seamark), ~{mb:.0f} MB", f"~{n} tile(s) (sat+seamark), ~{mb:.0f} MB")
            )
        except Exception:
            self._lbl_estimate.setText("")

    def _append_log(self, msg: str):
        self._log_edit.append(msg)
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _do_send(self):
        from services.sftp_service import DeployWorker
        tiles = self._get_tiles()
        ip         = self._ip.text().strip()
        port       = int(self._port.text().strip() or "22")
        user       = self._user.text().strip()
        password   = self._pwd.text()
        deploy_dir = self._remote_deploy_dir.text().strip().rstrip('/')
        tiles_dir  = f"{deploy_dir}/tiles"
        filename   = f"deploiement_{self._date_str}.json"
        json_path  = f"{deploy_dir}/{filename}"

        self._btn_send.setEnabled(False)
        self._progress.setRange(0, max(1, len(tiles)))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._log_edit.clear()

        self._worker = DeployWorker(
            ip=ip, port=port, user=user, password=password,
            json_bytes=self._json_bytes, json_remote_path=json_path,
            tiles=tiles, remote_tiles_dir=tiles_dir,
        )
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(lambda done, total: self._progress.setValue(done))
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self):
        self._progress.setValue(self._progress.maximum())
        self._progress.setVisible(False)
        self._btn_send.setText(self.translate("Fermer", "Close"))
        self._btn_send.setEnabled(True)
        self._btn_send.clicked.disconnect()
        self._btn_send.clicked.connect(self.accept)

    def _on_error(self, msg: str):
        self._append_log(f"ERREUR : {msg}")
        self._progress.setVisible(False)
        self._btn_send.setEnabled(True)

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(2000)
        self.reject()
