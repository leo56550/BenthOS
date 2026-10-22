from PyQt6 import QtWidgets, QtCore, QtGui
import json


class _CampaignLoadingOverlay(QtWidgets.QWidget):
    """Overlay plein-écran affiché pendant le chargement d'une campagne."""

    _SPINNER = ["◜ ", " ◝", " ◞", "◟ "]
    _BAR_STYLE = (
        "QProgressBar { background: #1a3a4a; border: none; border-radius: 2px; }"
        "QProgressBar::chunk { background: #5bb8f5; border-radius: 2px; }"
    )
    _BAR_TOTAL_STYLE = (
        "QProgressBar { background: #1a3a4a; border: none; border-radius: 2px; }"
        "QProgressBar::chunk { background: #3a9a6a; border-radius: 2px; }"
    )

    def __init__(self, parent: QtWidgets.QWidget):
        # Fenêtre top-level frameless — pas de parent Qt → contourne le rendu natif de QVideoWidget
        super().__init__(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Tool,
        )
        self._anchor = parent   # référence pour positionner et redimensionner
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)

        _lbl_css = "color: #d0e8f8; font-size: 12px; font-weight: bold; background: transparent; border: none;"
        _sub_css = "color: #7fb8e0; font-size: 11px; background: transparent; border: none;"

        # Carte centrale
        self._card = QtWidgets.QFrame(self)
        self._card.setFixedSize(360, 175)
        self._card.setStyleSheet(
            "QFrame { background-color: #0d1e2e; border: 1px solid #2778a2;"
            " border-radius: 12px; }"
        )
        card_layout = QtWidgets.QVBoxLayout(self._card)
        card_layout.setContentsMargins(24, 16, 24, 16)
        card_layout.setSpacing(6)

        self._lbl_icon = QtWidgets.QLabel(self._SPINNER[0])
        self._lbl_icon.setStyleSheet(
            "color: #5bb8f5; font-size: 24px; background: transparent; border: none;")
        self._lbl_icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._lbl_icon)

        self._lbl_msg = QtWidgets.QLabel("")
        self._lbl_msg.setStyleSheet(_lbl_css)
        self._lbl_msg.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._lbl_msg.setWordWrap(True)
        card_layout.addWidget(self._lbl_msg)

        # Barre 1 — progression dans la vidéo courante (bleu)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(5)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(self._BAR_STYLE)
        card_layout.addWidget(self._bar)

        # Barre 2 — progression totale vidéos (vert), masquée par défaut
        self._lbl_total = QtWidgets.QLabel("")
        self._lbl_total.setStyleSheet(_sub_css)
        self._lbl_total.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._lbl_total.hide()
        card_layout.addWidget(self._lbl_total)

        self._bar_total = QtWidgets.QProgressBar()
        self._bar_total.setRange(0, 0)
        self._bar_total.setFixedHeight(5)
        self._bar_total.setTextVisible(False)
        self._bar_total.setStyleSheet(self._BAR_TOTAL_STYLE)
        self._bar_total.hide()
        card_layout.addWidget(self._bar_total)

        self._fi = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(8, 16, 26, 215))
        p.end()
        self._card.move(
            (self.width()  - self._card.width())  // 2,
            (self.height() - self._card.height()) // 2,
        )

    def set_message(self, msg: str):
        self._lbl_msg.setText(msg)

    def set_progress(self, value: int, maximum: int):
        """Barre 1 (vidéo courante) — mode déterminé."""
        if maximum != self._bar.maximum():
            self._bar.setRange(0, maximum)
        self._bar.setValue(value)

    def set_total_progress(self, value: int, maximum: int, label: str = ""):
        """Barre 2 (progression totale) — affiche la barre verte et met à jour."""
        if not self._bar_total.isVisible():
            self._lbl_total.show()
            self._bar_total.show()
            self.update()  # force repaint pour re-centrer la carte
        if label:
            self._lbl_total.setText(label)
        if maximum != self._bar_total.maximum():
            self._bar_total.setRange(0, maximum)
        self._bar_total.setValue(value)

    def step(self, msg: str, value: int, maximum: int):
        """Met à jour message + barre 1 en un seul appel."""
        self.set_message(msg)
        self.set_progress(value, maximum)

    def _tick(self):
        self._fi = (self._fi + 1) % len(self._SPINNER)
        self._lbl_icon.setText(self._SPINNER[self._fi])

    def start(self):
        # Positionner sur la fenêtre principale en coordonnées globales
        tl = self._anchor.mapToGlobal(QtCore.QPoint(0, 0))
        self.setGeometry(tl.x(), tl.y(), self._anchor.width(), self._anchor.height())
        self._timer.start()
        self.show()
        self.raise_()
        QtWidgets.QApplication.processEvents()

    def stop(self):
        self._timer.stop()
        self.close()

from services.campaign_service import (get_campaign_json_data, get_video_json_path,
                                       get_working_video_json_path)
from services.video_service import check_stereo_status, get_system_name
from services.weather_service import WeatherWorker
from services.sound_service import get_sound_service
from views.dialogs.notes_dialog import NotesDialog
from controllers.accueil_controller import AccueilController
from views.widgets.progress_dashboard import AvancementPanel
from controllers.qualif_controller import QualifController, _get_point_name
from controllers.validation_controller import ValidationController
from controllers.evenements_controller import EvenementsController
from controllers.metadonnees_controller import MetadonneesController
from controllers.extraction_controller import ExtractionController
from controllers.apropos_controller import AProposController
from controllers.analyse_habitat_controller import AnalyseHabitatController
import os


class AppController(QtCore.QObject):
    """Orchestrates navigation, campaign lifecycle, and page controllers."""

    def __init__(self, window):
        """Instancie tous les controllers de page, connecte les signaux de navigation et les boutons workflow."""
        super().__init__()
        self.window = window
        self._current_campaign_name: str = ""
        self._current_derusher_name: str = ""
        self._current_campaign_mode: str = ""  # "MONO" | "STEREO" | ""
        self.working_dir: str = ""
        self._campaign_ready: bool = False
        self._campaign_qualified: bool = False  # True dès qu'au moins une vidéo a été qualifiée

        # Instantiate page controllers
        self.accueil_ctrl = AccueilController(
            window.page_accueil,
            self.handle_campaign_opening,
            recent_callback=self._open_recent_campaigns,
            open_video_callback=self._open_single_video,
        )
        self.qualif_ctrl = QualifController(
            window.page_qualification, parent=window,
            on_before_delete=self._release_file_in_all_players,
            on_qualification_changed=self._on_qualification_changed,
        )
        self._aruco_results: dict = {}
        self.validation_ctrl = ValidationController(
            window.page_validation, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
            on_qualification_changed=self._on_qualification_changed,
            get_aruco_result=self._aruco_results.get,
            on_detect_aruco=self._aruco_detect_single,
            on_detect_aruco_all=self._aruco_detect_all,
            on_detect_aruco_missing=self._aruco_detect_missing,
        )
        self.evenements_ctrl = EvenementsController(
            window.page_evenements, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
            on_events_changed=self._on_events_changed,
            on_export_started=window.show_export_progress,
            on_export_progress=window.update_export_progress,
            on_export_ended=window.hide_export_progress,
        )
        if hasattr(window, 'btn_stop_export'):
            window.btn_stop_export.clicked.connect(self.evenements_ctrl.stop_export)
        self.metadonnees_ctrl = MetadonneesController(
            window.page_metadonnees,
            self.qualif_ctrl.video_model,
            self.qualif_ctrl.trash_model,
            on_metadata_saved=self._on_metadata_saved,
            on_video_selected=self._on_meta_video_selected,
            on_open_map=self._open_map_from_metadonnees,
        )
        self.apropos_ctrl = AProposController(window.page_apropos)
        self.analyse_habitat_ctrl = AnalyseHabitatController(window.page_analyse_habitat)
        self.extraction_ctrl = ExtractionController(
            window.page_extraction, self.qualif_ctrl.video_model,
            on_video_focused=self._focus_map,
        )

        self.page_controllers = [
            self.accueil_ctrl, self.qualif_ctrl, self.validation_ctrl,
            self.evenements_ctrl, self.metadonnees_ctrl, self.apropos_ctrl, self.extraction_ctrl,
            self.analyse_habitat_ctrl,
        ]

        # Empêche le QStackedWidget de forcer une hauteur minimale basée sur ses pages,
        # ce qui poussait la barre de navigation du bas hors de l'écran.
        # Ignored vertical = contribution 0 au minimum du QMainWindowLayout.
        window.stackedWidget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Ignored)
        window.stackedWidget.setMinimumHeight(0)

        self._avancement_panel = AvancementPanel(window)
        if hasattr(window, 'btn_avancement'):
            window.btn_avancement.clicked.connect(
                lambda: self._avancement_panel.toggle(window.btn_avancement))

        self.qualif_ctrl.video_model.rowsInserted.connect(self.refresh_status_bar)
        self.qualif_ctrl.video_model.rowsRemoved.connect(self.refresh_status_bar)
        self.qualif_ctrl.video_model.rowsInserted.connect(self._refresh_dashboard)
        self.qualif_ctrl.video_model.rowsRemoved.connect(self._refresh_dashboard)

        # Carte : propager les clics sur les marqueurs vers tous les controllers
        bridge = self.qualif_ctrl.bridge
        bridge.videoSelected.connect(self.validation_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.evenements_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.metadonnees_ctrl.select_video_by_name)
        bridge.videoSelected.connect(self.extraction_ctrl.select_video_by_name)

        # Carte : déplacement de marqueur sans _temp.json (mode données historiques)
        self.qualif_ctrl._on_coords_updated = self._on_map_marker_coords_updated

        # Wire navigation actions
        window.actionAcceuil.triggered.connect(lambda: self.switch_page(window.page_accueil))
        window.actionQualification.triggered.connect(lambda: self.switch_page(window.page_qualification))
        window.actionValidation.triggered.connect(lambda: self.switch_page(window.page_validation))
        window.actionEvenements.triggered.connect(lambda: self.switch_page(window.page_evenements))
        window.actionMetadonnees.triggered.connect(lambda: self.switch_page(window.page_metadonnees))
        window.actionA_propos.triggered.connect(lambda: self.switch_page(window.page_apropos))
        window.actionExtraction.triggered.connect(lambda: self.switch_page(window.page_extraction))
        window.actionAnalyseHabitat.triggered.connect(lambda: self.switch_page(window.page_analyse_habitat))

        # Language buttons
        window.btn_lang_fr.clicked.connect(lambda: self.set_language("fr"))
        window.btn_lang_en.clicked.connect(lambda: self.set_language("en"))

        if hasattr(window, 'btn_notes'):
            window.btn_notes.clicked.connect(self._open_notes)

        if hasattr(window, 'btn_sftp'):
            window.btn_sftp.clicked.connect(self._open_sftp_dialog)

        if hasattr(window, 'btn_load_history'):
            window.btn_load_history.clicked.connect(self._load_historical_data)
            window.btn_load_history.customContextMenuRequested.connect(
                self._show_load_history_context_menu)

        if hasattr(window, 'btn_synthese_infostation'):
            window.btn_synthese_infostation.clicked.connect(
                self._generate_synthese_infostation)

        if hasattr(window, 'btn_generate_temp'):
            window.btn_generate_temp.setVisible(False)
            if hasattr(window, '_act_generate_temp'):
                window._act_generate_temp.setVisible(False)

        # Boutons QUALIFIER / VALIDER retirés : la navigation entre pages n'est plus
        # conditionnée à un clic explicite, seule une campagne chargée est nécessaire.
        btn_finir_qualif = window.findChild(QtWidgets.QPushButton, "btn_finir_qualif")
        if btn_finir_qualif:
            btn_finir_qualif.setVisible(False)
        btn_finir_validation = window.findChild(QtWidgets.QPushButton, "btn_finir_validation")
        if btn_finir_validation:
            btn_finir_validation.setVisible(False)

        # Button mapping for navigation highlight
        window.button_mapping = {
            window.page_accueil: window.actionAcceuil,
            window.page_qualification: window.actionQualification,
            window.page_validation: window.actionValidation,
            window.page_evenements: window.actionEvenements,
            window.page_metadonnees: window.actionMetadonnees,
            window.page_extraction: window.actionExtraction,
            window.page_apropos: window.actionA_propos,
            window.page_analyse_habitat: window.actionAnalyseHabitat,
        }

        self.lock_navigation(True)
        self.switch_page(window.page_accueil)
        # Synchronise la langue initiale (fenêtre démarre en FR, controllers en EN par défaut)
        self.set_language(window.current_language)

        # +/- pour accélérer/ralentir le player visible, sans dépendre du focus (cf. eventFilter)
        QtWidgets.QApplication.instance().installEventFilter(self)

    def _on_meta_video_selected(self, video_name: str, _video_path: str):  # noqa: ARG002
        """Ouvre le player détaché et focus la carte depuis la page Métadonnées."""
        # Synchronise le répertoire de travail vers qualif_ctrl pour que les popups
        # affichent le chemin relatif correct même si la carte a été construite avant.
        if self.working_dir and self.qualif_ctrl._working_dir != self.working_dir:
            self.qualif_ctrl._working_dir = self.working_dir
            self.qualif_ctrl.map_initialized = False
        extra_points = {}
        if self.qualif_ctrl.video_model.rowCount() == 0:
            extra_points = self.metadonnees_ctrl.collect_ft_table_coords(self.working_dir)
        self.qualif_ctrl.update_minimap(video_name, show_dialog=True, extra_points=extra_points)
        # Ouvre le player (bypass la garde selected_video_name)
        prev = self.qualif_ctrl.selected_video_name
        self.qualif_ctrl.selected_video_name = None
        self.qualif_ctrl.select_video_by_name(video_name)
        if self.qualif_ctrl.selected_video_name is None:
            # select_video_by_name n'a pas trouvé la vidéo, restaurer
            self.qualif_ctrl.selected_video_name = prev

    def _sync_all_to_working_dir(self, overlay_cb=None) -> None:
        """Copie les fichiers compagnon de toutes les vidéos dans le répertoire de travail.

        Seules les copies de travail sont modifiées — les JSON bruts ne sont jamais touchés.
        """
        if not self.working_dir or not self._campaign_ready:
            return

        model = self.qualif_ctrl.video_model
        video_paths = []
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if video_path:
                video_paths.append(video_path)

        n = len(video_paths)
        if overlay_cb and n:
            overlay_cb(self.translate(
                f"Synchronisation des données… (0/{n})",
                f"Syncing data… (0/{n})"), 0, n)

        if self._current_derusher_name:
            self._write_derusher_to_working_copies(
                video_paths, self._current_derusher_name, overlay_cb=overlay_cb)
        QtWidgets.QApplication.processEvents()


    def _persist_motor_events_for_all_videos(self, force: bool = False,
                                              overlay_cb=None) -> None:
        """Écrit (ou recalcule) les rotations moteur dans chaque _temp.json au chargement."""
        from services.motor_service import persist_motor_events_from_csv
        from services.campaign_service import get_temp_json_path
        import time as _time
        model = self.qualif_ctrl.video_model
        n = model.rowCount()
        total = 0
        print(f"[CAMPAGNE] Calcul des événements moteur pour {n} vidéo(s)…")
        t0 = _time.perf_counter()
        for row in range(n):
            item = model.item(row, 0)
            video_path = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if not video_path:
                continue
            if overlay_cb:
                name = os.path.basename(video_path)
                overlay_cb(self.translate(
                    f"Événements moteur {row+1}/{n} — {name}",
                    f"Motor events {row+1}/{n} — {name}"), row + 1, n)
            json_path = get_temp_json_path(video_path)
            if os.path.isfile(json_path):
                total += persist_motor_events_from_csv(video_path, json_path, force=force)
            QtWidgets.QApplication.processEvents()
        print(f"[CAMPAGNE] Événements moteur : {total} rotation(s) inscrite(s) "
              f"en {_time.perf_counter()-t0:.2f}s")

    def _write_derusher_to_working_copies(self, video_paths: list, derusher_name: str,
                                          overlay_cb=None) -> None:
        """Écrit le nom du dérusher dans les copies de travail des JSONs vidéo."""
        import json as _json
        n = len(video_paths)
        count = 0
        for i, video_path in enumerate(video_paths):
            if overlay_cb:
                name = os.path.basename(video_path)
                overlay_cb(self.translate(
                    f"Synchronisation {i+1}/{n} — {name}",
                    f"Syncing {i+1}/{n} — {name}"), i + 1, n)
            wjson = get_working_video_json_path(self.working_dir, video_path)
            if not os.path.isfile(wjson):
                QtWidgets.QApplication.processEvents()
                continue
            try:
                with open(wjson, 'r', encoding='utf-8') as f:
                    data = _json.load(f)
                vo = data.get("video_observation", {})
                if "derusher" in vo:
                    existing = (vo["derusher"].get("value") or "").strip()
                    new_val = derusher_name.strip()
                    if existing and existing != new_val:
                        if new_val not in [n.strip() for n in existing.split(",")]:
                            new_val = f"{existing}, {new_val}"
                        else:
                            new_val = existing
                    vo["derusher"]["value"] = new_val
                    with open(wjson, 'w', encoding='utf-8') as f:
                        _json.dump(data, f, indent=2, ensure_ascii=False)
                    count += 1
            except Exception as e:
                print(f"[DERUSHER] {wjson}: {e}")
            QtWidgets.QApplication.processEvents()
        print(f"[DERUSHER] '{derusher_name}' écrit dans {count} copies de travail.")

    def _open_working_dir(self):
        """Ouvre un sélecteur de dossier pour choisir le répertoire de travail IHM."""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            "Choisir le répertoire de travail (ex : 2026)",
            self.working_dir or "",
        )
        if not path:
            return
        self.working_dir = path
        # Propager aux controllers
        for ctrl in [self.qualif_ctrl, self.validation_ctrl, self.evenements_ctrl,
                     self.metadonnees_ctrl, self.extraction_ctrl]:
            if hasattr(ctrl, 'set_working_dir'):
                ctrl.set_working_dir(path)
        # Arrêter le clignotement, passer le bouton en vert
        self.accueil_ctrl.confirm_working_dir(path)
        # Déverrouiller la navigation maintenant que les deux conditions sont remplies
        if self._campaign_ready:
            self.lock_navigation(False)
        # Synchroniser tous les fichiers compagnon maintenant que le répertoire est connu
        self._sync_all_to_working_dir()

    def _on_metadata_saved(self, video_path: str = None):
        """Rafraîchit l'indicateur de complétion, le n° de point et la position du marqueur
        carte sans reconstruire toute la carte (un setLatLng JS suffit)."""
        import json as _json, math as _math
        from services.campaign_service import get_temp_json_path as _gtp
        vp = video_path or self.metadonnees_ctrl.current_video_path
        # Mise à jour légère du marqueur carte si la carte est ouverte
        if vp and getattr(self.qualif_ctrl, 'map_initialized', False) \
                and self.qualif_ctrl.map_dialog.isVisible():
            try:
                jp = _gtp(str(vp))
                if os.path.isfile(jp):
                    with open(jp, 'r', encoding='utf-8') as _f:
                        _d = _json.load(_f)
                    _obs = _d.get('video_observation', {})
                    _lat = (_obs.get('latitude') or {}).get('value')
                    _lon = (_obs.get('longitude') or {}).get('value')
                    if _lat is not None and _lon is not None:
                        _lf = float(str(_lat).replace(',', '.'))
                        _lo = float(str(_lon).replace(',', '.'))
                        if not (_math.isnan(_lf) or _math.isnan(_lo)):
                            _vname = os.path.basename(str(vp))
                            self.qualif_ctrl.update_single_marker_latlng_js(_vname, _lf, _lo)
            except Exception:
                pass
        if vp:
            self.qualif_ctrl.refresh_completion_color_for_video(vp)
            self._refresh_point_name_for_video(vp)

    def _on_map_marker_coords_updated(self, video_name: str, lat: float, lon: float):
        """Appelé quand un marqueur est déplacé sans _temp.json disponible (mode historique).

        Met à jour directement les cellules lat/lon du tableau infostation."""
        self.metadonnees_ctrl.update_ft_coords_by_name(video_name, lat, lon)

    def _refresh_point_name_for_video(self, video_path: str):
        """Recalcule le n° de point (UserRole+3) et le repropage sur le modèle vidéo partagé.

        Le n° de point est affiché via cette donnée sur plusieurs pages (ex: page Validation) ;
        sans ce refresh, une édition faite sur la page Métadonnées n'apparaissait qu'après avoir
        cliqué sur la vidéo (ce qui réécrivait UserRole+3 en passant).
        """
        new_val = _get_point_name(video_path, self.working_dir)
        for model in (self.qualif_ctrl.video_model, self.qualif_ctrl.trash_model):
            for row in range(model.rowCount()):
                item = model.item(row, 0)
                if item and str(item.data(QtCore.Qt.ItemDataRole.UserRole)) == str(video_path):
                    item.setData(new_val, QtCore.Qt.ItemDataRole.UserRole + 3)

    def _open_single_video(self):
        """Ouvre un fichier MP4 standalone dans un player complet, sans campagne."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            self.translate("Ouvrir une vidéo", "Open a video"),
            "",
            self.translate("Vidéos MP4 (*.mp4);;Tous les fichiers (*)", "MP4 videos (*.mp4);;All files (*)"),
        )
        if not path:
            return
        from views.dialogs.quick_video_dialog import QuickVideoDialog
        dlg = QuickVideoDialog(path, parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.show()

    def _generate_synthese_infostation(self):
        """Parcourt récursivement un dossier, lit tous les _temp.json et génère synthèse_infoStation.csv."""
        import os as _os
        import csv as _csv
        from datetime import datetime as _dt
        from PyQt6.QtWidgets import QFileDialog, QProgressDialog, QMessageBox, QApplication
        from PyQt6.QtCore import Qt
        from controllers.metadonnees_controller import _INFOSTATION_COLUMNS

        # 1. Choisir le dossier racine à scanner
        root_dir = QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le dossier racine à analyser", "Choose root folder to scan"),
            "",
        )
        if not root_dir:
            return

        # 2. Scanner récursivement tous les *_temp.json
        temp_jsons = []
        for dirpath, _, filenames in _os.walk(root_dir):
            for fn in sorted(filenames):
                if fn.endswith("_temp.json"):
                    temp_jsons.append(_os.path.join(dirpath, fn))

        if not temp_jsons:
            QMessageBox.warning(
                self.window,
                self.translate("Aucun fichier trouvé", "No file found"),
                self.translate(
                    f"Aucun _temp.json trouvé dans :\n{root_dir}",
                    f"No _temp.json found in:\n{root_dir}",
                ),
            )
            return

        # 3. Dériver le chemin vidéo depuis chaque _temp.json
        video_paths = []
        for jp in temp_jsons:
            stem = _os.path.basename(jp)[: -len("_temp.json")]
            video_paths.append(_os.path.join(_os.path.dirname(jp), stem + ".mp4"))

        # 4. Lire zone + année depuis chaque _temp.json pour le filtre
        import json as _json, re as _re
        meta_by_path: dict[str, dict] = {}
        for jp, vp in zip(temp_jsons, video_paths):
            zone, year = "", ""
            try:
                with open(jp, "r", encoding="utf-8") as _f:
                    _d = _json.load(_f)
                zone = str((_d.get("survey", {}).get("zone") or {}).get("value") or "").strip()
                date_raw = str((_d.get("survey", {}).get("date") or {}).get("value") or "").strip()
                m = _re.search(r"(20\d{2})", date_raw) or _re.search(r"(?<!\d)(20\d{2})(?!\d)", jp)
                year = m.group(1) if m else ""
            except Exception:
                pass
            meta_by_path[vp] = {"zone": zone, "year": year}

        all_zones = sorted({v["zone"] for v in meta_by_path.values() if v["zone"]})
        all_years = sorted({v["year"] for v in meta_by_path.values() if v["year"]})

        # 5. Dialog de filtrage par zone et année
        if all_zones or all_years:
            filter_dlg = QtWidgets.QDialog(self.window)
            filter_dlg.setWindowTitle(
                self.translate("Filtrer la synthèse", "Filter synthesis"))
            filter_dlg.setMinimumWidth(420)
            filter_dlg.setStyleSheet("""
                QDialog { background-color: #111820; }
                QLabel  { color: #b0c8d8; font-size: 12px;
                          font-family: 'Segoe UI', sans-serif; }
                QGroupBox { color: #7dd8f8; font-size: 12px; font-weight: bold;
                            border: 1px solid #1e3448; border-radius: 4px;
                            margin-top: 6px; padding-top: 8px;
                            font-family: 'Segoe UI', sans-serif; }
                QGroupBox::title { subcontrol-origin: margin; left: 8px; }
                QCheckBox { color: #b0c8d8; font-size: 11px;
                            font-family: 'Segoe UI', sans-serif; }
                QCheckBox::indicator:checked { background-color: #2778a2; }
                QPushButton {
                    background-color: #20415D; color: #F2BFB4;
                    border: 1px solid #2778A2; border-radius: 4px;
                    padding: 6px 14px; font-size: 12px;
                    font-family: 'Segoe UI', sans-serif;
                }
                QPushButton:hover { background-color: #2778A2; }
            """)
            flay = QtWidgets.QVBoxLayout(filter_dlg)
            flay.setContentsMargins(18, 14, 18, 14)
            flay.setSpacing(12)

            lbl_info = QtWidgets.QLabel(
                self.translate(
                    f"{len(temp_jsons)} observation(s) trouvée(s) — choisissez les filtres :",
                    f"{len(temp_jsons)} observation(s) found — choose filters:",
                )
            )
            flay.addWidget(lbl_info)

            zone_checks: dict[str, QtWidgets.QCheckBox] = {}
            if all_zones:
                grp_zone = QtWidgets.QGroupBox(self.translate("Zones", "Zones"))
                gz = QtWidgets.QVBoxLayout(grp_zone)
                gz.setSpacing(4)
                for z in all_zones:
                    cb = QtWidgets.QCheckBox(z)
                    cb.setChecked(True)
                    zone_checks[z] = cb
                    gz.addWidget(cb)
                flay.addWidget(grp_zone)

            year_checks: dict[str, QtWidgets.QCheckBox] = {}
            if all_years:
                grp_year = QtWidgets.QGroupBox(self.translate("Années", "Years"))
                gy = QtWidgets.QVBoxLayout(grp_year)
                gy.setSpacing(4)
                for y in all_years:
                    cb = QtWidgets.QCheckBox(y)
                    cb.setChecked(True)
                    year_checks[y] = cb
                    gy.addWidget(cb)
                flay.addWidget(grp_year)

            btn_row = QtWidgets.QHBoxLayout()
            btn_row.addStretch()
            btn_ok = QtWidgets.QPushButton(
                self.translate("Générer", "Generate"))
            btn_cancel = QtWidgets.QPushButton(
                self.translate("Annuler", "Cancel"))
            btn_ok.clicked.connect(filter_dlg.accept)
            btn_cancel.clicked.connect(filter_dlg.reject)
            btn_row.addWidget(btn_ok)
            btn_row.addWidget(btn_cancel)
            flay.addLayout(btn_row)

            if filter_dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return

            # Appliquer les filtres
            sel_zones = {z for z, cb in zone_checks.items() if cb.isChecked()}
            sel_years = {y for y, cb in year_checks.items() if cb.isChecked()}
            video_paths = [
                vp for vp in video_paths
                if (not sel_zones or meta_by_path[vp]["zone"] in sel_zones or not meta_by_path[vp]["zone"])
                and (not sel_years or meta_by_path[vp]["year"] in sel_years or not meta_by_path[vp]["year"])
            ]
            if not video_paths:
                QMessageBox.warning(
                    self.window,
                    self.translate("Aucune donnée", "No data"),
                    self.translate(
                        "Aucune observation ne correspond aux filtres sélectionnés.",
                        "No observation matches the selected filters.",
                    ),
                )
                return

        # 6. Trier par heure de station (réutilise la méthode existante)
        video_paths = self.metadonnees_ctrl._sort_paths_by_station_time(video_paths)

        # 7. Choisir le répertoire de sortie
        out_dir = QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le répertoire de sortie", "Choose output directory"),
            root_dir,
        )
        if not out_dir:
            return

        # 6. Écrire le CSV
        date_str = _dt.now().strftime("%Y%m%d")
        csv_path = _os.path.join(out_dir, f"{date_str}_synthese_infostation.csv")
        total = len(video_paths)

        progress = QProgressDialog(
            self.translate(
                f"Génération de la synthèse ({total} observations)…",
                f"Generating synthesis ({total} observations)…"),
            self.translate("Annuler", "Cancel"),
            0, total, self.window,
        )
        progress.setWindowTitle(
            self.translate("Synthèse infoStation", "infoStation Synthesis"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(420)
        progress.setStyleSheet("""
            QProgressDialog {
                background-color: #111820;
                color: #b0c8d8;
            }
            QLabel {
                color: #b0c8d8;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                padding: 4px 0px;
            }
            QProgressBar {
                background-color: #1a2e40;
                border: 1px solid #1e3448;
                border-radius: 4px;
                height: 18px;
                text-align: center;
                color: #ffffff;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #2778a2;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #20415D;
                color: #F2BFB4;
                border: 1px solid #2778A2;
                border-radius: 4px;
                padding: 5px 14px;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
        """)
        progress.setValue(0)
        QApplication.processEvents()

        errors: list[str] = []
        written = 0
        try:
            _os.makedirs(out_dir, exist_ok=True)
            # Collecter toutes les lignes pour pouvoir trier par codestation
            rows: list[list[str]] = []
            for i, vp in enumerate(video_paths):
                if progress.wasCanceled():
                    break
                progress.setValue(i)
                if i % 10 == 0:
                    QApplication.processEvents()
                try:
                    row_data = self.metadonnees_ctrl._build_infostation_row(
                        vp, for_csv=True)
                    rows.append(
                        [str(v).replace("\n", " | ").replace("\r", "")
                         for v in row_data])
                    written += 1
                except Exception as e:
                    errors.append(_os.path.basename(vp))
                    print(f"[SYNTHESE] {_os.path.basename(vp)}: {e}")

            # Trier par codestation (colonne 0), insensible à la casse
            rows.sort(key=lambda r: r[0].lower() if r else "")

            with open(csv_path, "w", newline="", encoding="cp1252", errors="replace") as f:
                writer = _csv.writer(f, delimiter=";", quoting=_csv.QUOTE_MINIMAL)
                writer.writerow(_INFOSTATION_COLUMNS)
                for row in rows:
                    writer.writerow(row)
        except Exception as e:
            QMessageBox.critical(
                self.window,
                self.translate("Erreur", "Error"),
                self.translate(f"Impossible d'écrire le fichier :\n{e}",
                               f"Cannot write file:\n{e}"),
            )
            return
        finally:
            progress.setValue(total)

        msg = self.translate(
            f"Synthèse générée — {written} observation(s) :\n{csv_path}",
            f"Synthesis generated — {written} observation(s):\n{csv_path}",
        )
        if errors:
            sample = "\n".join(errors[:10])
            suffix = f"\n…et {len(errors) - 10} autres" if len(errors) > 10 else ""
            msg += "\n\n" + self.translate(
                f"Erreurs ({len(errors)}) :\n{sample}{suffix}",
                f"Errors ({len(errors)}):\n{sample}{suffix}",
            )
        QMessageBox.information(
            self.window,
            self.translate("Synthèse terminée", "Synthesis complete"),
            msg,
        )

    def _open_notes(self):
        """Ouvre le bloc-notes de session pour la campagne courante."""
        dossier = getattr(self.qualif_ctrl, 'current_campaign_folder', None)
        if not dossier:
            return
        dlg = NotesDialog(dossier, parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.show()

    def _on_qualification_changed(self):
        """Appelé quand l'exploitabilité ou les propriétés campagne changent."""
        self.refresh_status_bar()
        self._refresh_dashboard()
        self.metadonnees_ctrl.refresh_feuille_terrain()
        self.metadonnees_ctrl._rebuild_ft_table()
        self.qualif_ctrl.refresh_map_marker_colors()
        self.evenements_ctrl.proxy_model.invalidateFilter()

    def _on_events_changed(self, *_):
        """Callback déclenché quand des événements sont ajoutés/supprimés/modifiés."""
        self.metadonnees_ctrl.refresh_feuille_terrain()
        self._refresh_dashboard()
        for ctrl in (self.evenements_ctrl, self.validation_ctrl):
            if hasattr(ctrl, '_refresh_sector_view_if_active'):
                ctrl._refresh_sector_view_if_active()
        if hasattr(self.qualif_ctrl, '_refresh_camera_views'):
            self.qualif_ctrl._refresh_camera_views()

    def _open_sftp_dialog(self):
        """Ouvre le hub KOSMOS Connexion (SFTP + planification déploiement)."""
        from views.dialogs.kosmos_connexion_dialog import KosmosConnexionDialog
        dlg = KosmosConnexionDialog(self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.exec()

    def _open_recent_campaigns(self):
        """Ouvre le dialog de sélection d'une campagne récente."""
        from views.dialogs.recent_campaigns_dialog import RecentCampaignsDialog
        dlg = RecentCampaignsDialog(parent=self.window, language=getattr(self.window, 'current_language', 'fr'))
        dlg.campaign_selected.connect(self._open_campaign_from_recent)
        dlg.exec()

    def _open_campaign_from_recent(self, campaign_folder: str, working_dir: str, derusher_name: str):
        """Ouvre une campagne depuis la liste des récents."""
        if not campaign_folder or not os.path.isdir(campaign_folder):
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Dossier introuvable", "Folder not found"),
                self.translate(
                    f"Le dossier de campagne n'existe plus :\n{campaign_folder}",
                    f"The campaign folder no longer exists:\n{campaign_folder}",
                ),
            )
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self.window,
            self.translate("Nom du dérusher", "Derusher name"),
            self.translate("Votre nom :", "Your name:"),
            text=derusher_name or "",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Nom requis", "Name required"),
                self.translate("Veuillez saisir un nom de dérusher.", "Please enter a derusher name."),
            )
            return

        self.handle_campaign_opening(
            name,
            campaign_folder=campaign_folder,
            working_dir=working_dir,
        )

    def _delete_temp_jsons(self):
        """Supprime tous les _temp.json d'un dossier choisi par l'utilisateur après confirmation."""
        start_dir = getattr(self.qualif_ctrl, 'current_campaign_folder', '') or self.working_dir or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le dossier", "Choose folder"),
            start_dir,
        )
        if not folder or not os.path.isdir(folder):
            return
        import glob as _glob
        temp_files = _glob.glob(os.path.join(folder, "**", "*_temp.json"), recursive=True)
        if not temp_files:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Aucun fichier", "No files"),
                self.translate("Aucun _temp.json trouvé dans le dossier de travail.",
                               "No _temp.json found in the working directory.")
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self.window,
            self.translate("Confirmer la suppression", "Confirm deletion"),
            self.translate(
                f"⚠️ Attention : vous allez perdre toutes vos métadonnées !\n\n"
                f"{len(temp_files)} fichier(s) _temp.json vont être supprimés.\n"
                f"Cette action est irréversible.\n\nContinuer ?",
                f"⚠️ Warning: you will lose all your metadata!\n\n"
                f"{len(temp_files)} _temp.json file(s) will be deleted.\n"
                f"This action cannot be undone.\n\nContinue?"
            ),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        errors = []
        for f in temp_files:
            try:
                os.remove(f)
            except Exception as e:
                errors.append(f"{os.path.basename(f)}: {e}")
        if errors:
            QtWidgets.QMessageBox.warning(
                self.window,
                self.translate("Erreurs", "Errors"),
                "\n".join(errors)
            )
        else:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Suppression terminée", "Deletion complete"),
                self.translate(f"{len(temp_files)} _temp.json supprimé(s).",
                               f"{len(temp_files)} _temp.json deleted.")
            )

        # Rafraîchir la page métadonnées pour refléter la suppression
        if hasattr(self.metadonnees_ctrl, '_rebuild_ft_table'):
            self.metadonnees_ctrl._rebuild_ft_table()

        # Vider la timeline de chaque page dont le temp.json vient d'être supprimé
        for ctrl_name, player_attr in [
            ('validation_ctrl', 'player'),
            ('evenements_ctrl', 'event_player'),
            ('extraction_ctrl', 'player'),
        ]:
            ctrl = getattr(self, ctrl_name, None)
            if not ctrl:
                continue
            ctrl_json = getattr(ctrl, 'current_json_path', None)
            if not ctrl_json or os.path.exists(ctrl_json):
                continue  # pas de vidéo chargée, ou le fichier existe encore
            player = getattr(ctrl, player_attr, None)
            if not player:
                continue
            tl = getattr(player, 'timeline', None)
            if tl is not None:
                tl.events = []
                tl.set_selected_event(None)
                tl.update()

    def _show_load_history_context_menu(self, pos):
        """Clic droit sur 'Données historiques' → supprimer les temp.json."""
        btn = self.window.btn_load_history
        menu = QtWidgets.QMenu(btn)
        action_del = menu.addAction(
            self.translate("Supprimer les temp.json", "Delete temp.json files"))
        if menu.exec(btn.mapToGlobal(pos)) == action_del:
            self._delete_temp_jsons()

    def _load_historical_data(self):
        """Ouvre un CSV/XLSX infostation, demande le dossier vidéo, génère les temp.json."""
        start_dir = getattr(self.qualif_ctrl, 'current_campaign_folder', '') or self.working_dir or ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.window,
            self.translate("Charger données historiques", "Load historical data"),
            start_dir,
            "Infostation (*.csv *.xlsx);;CSV (*.csv);;Excel (*.xlsx);;Tous les fichiers (*.*)",
        )
        if not path:
            return

        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.translate(
                "Choisir le dossier contenant les vidéos",
                "Choose the folder containing the videos",
            ),
            os.path.dirname(path),
        )
        if not folder:
            return

        self.switch_page(self.window.page_metadonnees)
        self.metadonnees_ctrl._csv_folder = folder
        self.metadonnees_ctrl.load_csv_into_table(path)
        self._last_infostation_folder = os.path.dirname(path)
        # Mode données historiques : Accueil + Métadonnées accessibles, reste verrouillé
        self.window.actionMetadonnees.setEnabled(True)
        self._auto_generate_temp_jsons(folder)

    def _auto_generate_temp_jsons(self, folder: str):
        """Vérifie les conflits temp.json puis génère selon le choix utilisateur."""
        existing = self.metadonnees_ctrl.count_existing_temp_jsons(folder)
        mode = 'overwrite'

        if existing > 0:
            dlg = QtWidgets.QDialog(self.window)
            dlg.setWindowTitle(self.translate("Temp.json existants", "Existing temp.json"))
            dlg.setMinimumWidth(500)
            dlg.setStyleSheet("""
                QDialog { background-color: #111820; }
                QLabel  { color: #b0c8d8; font-size: 12px;
                          font-family: 'Segoe UI', sans-serif; }
                QPushButton {
                    background-color: #20415D; color: #F2BFB4;
                    border: 1px solid #2778A2; border-radius: 4px;
                    padding: 6px 14px; font-size: 12px;
                    font-family: 'Segoe UI', sans-serif;
                }
                QPushButton:hover { background-color: #2778A2; }
                QPushButton#btn_danger {
                    background-color: #5c2020; border-color: #a24040;
                }
                QPushButton#btn_danger:hover { background-color: #a24040; }
            """)
            vlay = QtWidgets.QVBoxLayout(dlg)
            vlay.setContentsMargins(18, 18, 18, 14)
            vlay.setSpacing(14)
            lbl = QtWidgets.QLabel(self.translate(
                f"{existing} fichier(s) _temp.json existent déjà dans ce dossier.\n"
                "Que voulez-vous faire ?",
                f"{existing} _temp.json file(s) already exist in this folder.\n"
                "What would you like to do?",
            ))
            lbl.setWordWrap(True)
            vlay.addWidget(lbl)
            btn_row = QtWidgets.QHBoxLayout()
            btn_row.setSpacing(8)
            _choice = [None]
            btn_fill = QtWidgets.QPushButton(
                self.translate("Compléter les champs vides", "Fill empty fields only"))
            btn_fill.clicked.connect(lambda: (_choice.__setitem__(0, 'fill_empty'), dlg.accept()))
            btn_row.addWidget(btn_fill)
            btn_overwrite = QtWidgets.QPushButton(
                self.translate("Écraser tout", "Overwrite all"))
            btn_overwrite.setObjectName("btn_danger")
            btn_overwrite.clicked.connect(lambda: (_choice.__setitem__(0, 'overwrite'), dlg.accept()))
            btn_row.addWidget(btn_overwrite)
            btn_cancel = QtWidgets.QPushButton(self.translate("Annuler", "Cancel"))
            btn_cancel.clicked.connect(dlg.reject)
            btn_row.addWidget(btn_cancel)
            vlay.addLayout(btn_row)
            if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted or _choice[0] is None:
                return
            mode = _choice[0]

        generated, total, failures = self.metadonnees_ctrl.generate_temp_from_table(
            folder, mode=mode
        )
        # Affiche les données fusionnées (historiques + temp.json existants) :
        # - si une campagne est ouverte (video_model peuplé) → reconstruction complète avec tri
        # - sinon (import CSV seul) → mise à jour des cellules en place depuis les temp.json
        if self.metadonnees_ctrl.video_model.rowCount() > 0:
            print("[IMPORT HISTORIQUE] Reconstruction du tableau depuis les JSON…")
            self.metadonnees_ctrl._rebuild_ft_table()
            self.metadonnees_ctrl._apply_ft_table_json_bold()
            print("[IMPORT HISTORIQUE] Tableau reconstruit.")
        else:
            print("[IMPORT HISTORIQUE] Rafraîchissement des cellules depuis les JSON…")
            self.metadonnees_ctrl._refresh_table_cells_from_jsons()
            print("[IMPORT HISTORIQUE] Rafraîchissement terminé.")
        # Forcer le repaint de la liste vidéo (barres de complétion + codestation)
        if hasattr(self.validation_ctrl, 'video_tree') and self.validation_ctrl.video_tree:
            self.validation_ctrl.video_tree.viewport().update()
        # Forcer la reconstruction de la carte au prochain affichage
        # (les _temp.json viennent d'être générés/mis à jour avec les statuts d'exploitabilité)
        extra_points = {}
        if self.metadonnees_ctrl.video_model.rowCount() == 0:
            extra_points = self.metadonnees_ctrl.collect_ft_table_coords()
        self.qualif_ctrl.map_initialized = False
        if self.qualif_ctrl.map_dialog.isVisible():
            self.qualif_ctrl.update_minimap(
                self.qualif_ctrl.selected_video_name,
                extra_points=extra_points,
            )
        self._show_generate_result(generated, total, failures)

    def _show_generate_result(self, generated: int, total: int, failures: list):
        """Affiche le résultat de la génération des temp.json."""
        skipped = total - generated
        summary = self.translate(
            f"{generated} temp.json générés sur {total} ligne(s).",
            f"{generated} temp.json generated out of {total} row(s).",
        )
        if failures:
            detail_lines = "\n".join(
                f"• {name} → {reason}" for name, reason in failures
            )
            msg = QtWidgets.QMessageBox(self.window)
            msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            msg.setWindowTitle(
                self.translate("Génération terminée avec avertissements",
                               "Generation complete with warnings"))
            msg.setText(summary + self.translate(
                f"\n\n⚠️ {skipped} ligne(s) non traitée(s).",
                f"\n\n⚠️ {skipped} row(s) not processed.",
            ))
            msg.setDetailedText(detail_lines)
            msg.exec()
        else:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Génération terminée", "Generation complete"),
                summary,
            )

    def _generate_temp_jsons(self):
        """Génère les _temp.json dans un dossier choisi par l'utilisateur."""
        if self.metadonnees_ctrl._ft_table.rowCount() == 0:
            QtWidgets.QMessageBox.information(
                self.window,
                self.translate("Tableau vide", "Empty table"),
                self.translate(
                    "Chargez d'abord un fichier CSV via 'Données historiques'.",
                    "Please load a CSV file via 'Historical data' first.",
                ),
            )
            return

        start_dir = getattr(self, '_last_infostation_folder', '') or \
                    getattr(self.qualif_ctrl, 'current_campaign_folder', '') or \
                    self.working_dir or ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window,
            self.translate("Choisir le dossier contenant les vidéos",
                           "Choose the folder containing videos"),
            start_dir,
        )
        if not folder:
            return

        generated, total, failures = self.metadonnees_ctrl.generate_temp_from_table(folder)
        self.metadonnees_ctrl._apply_ft_table_json_bold()
        self._show_generate_result(generated, total, failures)

    # --- Language ---

    def translate(self, fr: str, en: str) -> str:
        """Retourne fr ou en selon la langue courante de la fenêtre."""
        lang = getattr(self.window, 'current_language', 'fr')
        return fr if lang == 'fr' else en

    def set_language(self, language: str):
        """Propage la langue à tous les controllers et met à jour les boutons workflow."""
        w = self.window
        if language not in w.translations:
            return
        w.current_language = language
        w.update_language_buttons(language)
        trans = w.translations[language]
        self._update_info_labels(trans)
        for ctrl in self.page_controllers:
            if hasattr(ctrl, 'set_language'):
                ctrl.set_language(language)
        self._avancement_panel.dashboard.set_language(language)
        self.refresh_status_bar()

    def _update_info_labels(self, trans: dict):
        """Rafraîchit les labels dérusher et campagne de la toolbar avec les traductions actuelles."""
        w = self.window
        if hasattr(w, 'derusher_label') and self._current_derusher_name:
            w.derusher_label.setText(
                trans.get('derusher_active', '{} est en train de derusher').format(self._current_derusher_name)
            )
        if hasattr(w, 'campaign_label'):
            if self._current_campaign_name:
                w.campaign_label.setText(
                    trans.get('campaign_open', '📁 {}').format(self._current_campaign_name)
                )
            else:
                w.campaign_label.setText("")
        if hasattr(w, '_campaign_mode_action'):
            mode = self._current_campaign_mode
            if mode:
                is_stereo = (mode == "STEREO")
                color = "#f0c040" if is_stereo else "#a0b8c8"
                border = "#c89a10" if is_stereo else "#607080"
                w.campaign_mode_label.setText(mode)
                w.campaign_mode_label.setStyleSheet(
                    f"color: {color}; font-weight: bold; font-family: 'Segoe UI', sans-serif;"
                    f" font-size: 10px; padding: 2px 6px; border: 1px solid {border};"
                    f" border-radius: 3px; letter-spacing: 0.5px;"
                )
                w._campaign_mode_action.setVisible(True)
            else:
                w._campaign_mode_action.setVisible(False)
        if self._current_campaign_name:
            w.setWindowTitle(f"KOSMOS IHM — {self._current_campaign_name}")

    # --- Campaign opening ---

    def handle_campaign_opening(self, nom_derusher: str,
                               campaign_folder: str = "", working_dir: str = ""):
        """Charge la campagne, propage le répertoire de travail et déverrouille la navigation."""
        w = self.window
        self._current_campaign_mode = ""
        self._current_derusher_name = nom_derusher
        self.lock_navigation(False)

        # ── Overlay de chargement ────────────────────────────────────────────
        _overlay = _CampaignLoadingOverlay(self.window)
        _overlay.set_message(self.translate(
            "Analyse des vidéos de la campagne…",
            "Scanning campaign videos…"))
        _overlay.start()

        import time as _time
        t0 = _time.perf_counter()

        def _step(msg: str, value: int, maximum: int):
            _overlay.step(msg, value, maximum)
            QtWidgets.QApplication.processEvents()

        try:
            # Étape 1 — Charger le dossier
            print(f"[CAMPAGNE] Ouverture : {campaign_folder or '(dialog)'}")
            if campaign_folder:
                self.qualif_ctrl.load_campaign_folder(campaign_folder, nom_derusher,
                                                      step_cb=_step)
            else:
                _overlay.stop()
                self.qualif_ctrl.open_system_explorer(nom_derusher)
                _overlay = _CampaignLoadingOverlay(self.window)
                _overlay.set_message(self.translate(
                    "Analyse des vidéos de la campagne…",
                    "Scanning campaign videos…"))
                _overlay.start()
                self.qualif_ctrl.load_campaign_folder(
                    self.qualif_ctrl.current_campaign_folder,
                    nom_derusher, step_cb=lambda m, v, n: (
                        _overlay.step(m, v, n),
                        QtWidgets.QApplication.processEvents(),
                    ))

            n_videos = self.qualif_ctrl.video_model.rowCount()
            print(f"[CAMPAGNE] {n_videos} vidéo(s) chargée(s) en {_time.perf_counter()-t0:.2f}s")

            _step(self.translate("Propagation des modèles…", "Propagating models…"), 0, 0)
            self._refresh_all_page_models()
            # Reconstruit le tableau infostation depuis les temp.json (incl. données propagées)
            if hasattr(self.metadonnees_ctrl, '_rebuild_ft_table'):
                self.metadonnees_ctrl._rebuild_ft_table()
            self._detect_campaign_mode()
            self.refresh_status_bar()
            self._refresh_dashboard()

            dossier = getattr(self.qualif_ctrl, 'current_campaign_folder', None)
            if not dossier:
                return

            if hasattr(self.window, 'btn_notes'):
                self.window.btn_notes.setEnabled(True)
            session = os.path.basename(os.path.normpath(dossier))
            parent = os.path.basename(os.path.dirname(os.path.normpath(dossier)))
            self._current_campaign_name = f"{parent} / {session}" if parent else session
            self._update_info_labels(w.translations.get(w.current_language, w.translations['fr']))
            get_sound_service().play("campaign_open")

            try:
                from services.recent_campaigns_service import add_recent_campaign
                add_recent_campaign(dossier, working_dir or self.working_dir,
                                    self._current_campaign_name, nom_derusher)
            except Exception:
                pass

            data_systeme = get_campaign_json_data(dossier, extract_system=True)
            data_complete = get_campaign_json_data(dossier, extract_system=False)

            # Répertoire de travail fourni par le dialog → propager immédiatement
            if working_dir:
                self.working_dir = working_dir
                for ctrl in [self.qualif_ctrl, self.validation_ctrl, self.evenements_ctrl,
                             self.metadonnees_ctrl, self.extraction_ctrl]:
                    if hasattr(ctrl, 'set_working_dir'):
                        ctrl.set_working_dir(working_dir)

            # Étape 2 — Rotations moteur
            self._campaign_ready = True
            self._persist_motor_events_for_all_videos(force=False, overlay_cb=_step)

            # Étape 3 — Sync répertoire de travail
            self._sync_all_to_working_dir(overlay_cb=_step)

            if data_systeme:
                if self.working_dir:
                    self.lock_navigation(False)
                self.metadonnees_ctrl.load_global_campaign_metadata(dossier)

                try:
                    lat = lon = None
                    if data_complete and "video_observation" in data_complete:
                        block = data_complete["video_observation"]
                        lat = block.get("latitude", {}).get("value")
                        lon = block.get("longitude", {}).get("value")

                    if lat is not None and lon is not None:
                        self.weather_thread = WeatherWorker(lat, lon)
                        self.weather_thread.weather_fetched.connect(self.metadonnees_ctrl.inject_weather_data)
                        self.weather_thread.start()
                    else:
                        self.metadonnees_ctrl.inject_weather_data({})
                except Exception as e:
                    print(f"[METEO] Error: {e}")
                    self.metadonnees_ctrl.inject_weather_data({})

                self.switch_page(w.page_qualification)
            else:
                has_videos = self.qualif_ctrl.video_model.rowCount() > 0
                if has_videos and self.working_dir:
                    self.lock_navigation(False)
                    self.switch_page(w.page_qualification)
                else:
                    self.lock_navigation(True)

            self._aruco_results.clear()

        finally:
            _overlay.stop()

    def _aruco_detect_single(self, video_path: str):
        """Détecte l'ardoise sur une seule vidéo (clic droit → Détecter Ardoise)."""
        import re as _re
        if _re.search(r'_\d+\.mp4$', os.path.basename(video_path), _re.IGNORECASE):
            print(f"[ARUCO] Segment ignoré (ardoise dans le primaire) : {os.path.basename(video_path)}")
            return
        from services.aruco_service import detect_aruco_in_video
        name = os.path.basename(video_path)
        _ov = _CampaignLoadingOverlay(self.window)
        _ov.set_message(self.translate(f"Détection QRcode — {name}…",
                                        f"QRcode detection — {name}…"))
        _ov.start()

        class _Worker(QtCore.QThread):
            done     = QtCore.pyqtSignal(object)
            progress = QtCore.pyqtSignal(int)

            def __init__(self, vp, parent=None):
                super().__init__(parent)
                self._vp = vp

            def run(self):
                result = detect_aruco_in_video(self._vp,
                                               progress_cb=lambda p: self.progress.emit(p))
                self.done.emit(result)

        worker = _Worker(video_path, self.window)

        def _on_done(result):
            self._aruco_results[video_path] = result
            _ov.stop()
            _vd = getattr(self.validation_ctrl, "_bar_delegate", None)
            if _vd and hasattr(_vd, "set_aruco_results"):
                _vd.set_aruco_results(self._aruco_results)
            self.validation_ctrl.reload_video_by_path(video_path)

        def _on_progress(pct):
            _ov.set_progress(pct, 100)

        worker.done.connect(_on_done)
        worker.progress.connect(_on_progress)
        worker.start()

    def _stop_validation_player(self):
        """Arrête le player de la page validation s'il est en lecture."""
        try:
            _p = self.validation_ctrl.player
            if _p is not None:
                _p.pause_all()
        except Exception:
            pass

    def _aruco_detect_all(self):
        """Détecte les ardoises sur toutes les vidéos (clic droit → Détecter toutes)."""
        import time as _time
        self._stop_validation_player()
        _ov = _CampaignLoadingOverlay(self.window)
        _ov.set_message(self.translate("Détection QRcode…", "QRcode detection…"))
        _ov.start()
        _last = [0.0]

        def _frame_cb(pct):
            now = _time.time()
            if now - _last[0] >= 0.05:
                _last[0] = now
                _ov.set_progress(pct, 100)
                QtWidgets.QApplication.processEvents()

        try:
            self._aruco_results.clear()
            self._run_aruco_scan_sync(
                lambda msg, v, n: (
                    _ov.set_message(msg),
                    _ov.set_total_progress(v, n,
                        self.translate(f"Vidéo {v} / {n}", f"Video {v} / {n}")),
                    QtWidgets.QApplication.processEvents()),
                frame_cb=_frame_cb)
        finally:
            _ov.stop()

    def _aruco_detect_missing(self):
        """Détecte les ardoises uniquement sur les vidéos sans codestation (conserve les résultats existants)."""
        import time as _time
        self._stop_validation_player()
        _ov = _CampaignLoadingOverlay(self.window)
        _ov.set_message(self.translate("Détection QRcode (sans codestations)…",
                                        "QRcode detection (missing codestations)…"))
        _ov.start()
        _last = [0.0]

        def _frame_cb(pct):
            now = _time.time()
            if now - _last[0] >= 0.05:
                _last[0] = now
                _ov.set_progress(pct, 100)
                QtWidgets.QApplication.processEvents()

        try:
            self._run_aruco_scan_sync(
                lambda msg, v, n: (
                    _ov.set_message(msg),
                    _ov.set_total_progress(v, n,
                        self.translate(f"Vidéo {v} / {n}", f"Video {v} / {n}")),
                    QtWidgets.QApplication.processEvents()),
                frame_cb=_frame_cb,
                skip_already_scanned=True)
        finally:
            _ov.stop()

    def _run_aruco_scan_sync(self, step_cb=None, frame_cb=None, skip_already_scanned: bool = False):
        """Détecte les ArUco de manière synchrone dans l'overlay d'ouverture.
        Ne scanne que les vidéos sans codestation dans leur _temp.json.
        skip_already_scanned=True : ignore aussi les vidéos déjà dans _aruco_results.
        step_cb(msg, value, maximum) — même signature que l'overlay _step."""
        import json as _json
        from services.campaign_service import get_temp_json_path as _gtp, compute_codestation
        from services.aruco_service import detect_aruco_in_video

        model = self.qualif_ctrl.video_model
        if model.rowCount() == 0:
            return

        # Collecter les vidéos sans codestation calculable
        all_videos: list[str] = []
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            if not item:
                continue
            vp = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if vp:
                all_videos.append(str(vp))

        import re as _re
        videos_to_scan: list[str] = []
        for vp in all_videos:
            # Ignorer les segments séquentiels (_01, _02...) : l'ardoise est dans le primaire
            if _re.search(r'_\d+\.mp4$', os.path.basename(vp), _re.IGNORECASE):
                continue
            jp = _gtp(vp)
            has_code = False
            if os.path.isfile(jp):
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        jd = _json.load(f)
                    obs_block = jd.get("video_observation", {})
                    stored = (obs_block.get("codeObs") or {}).get("value")
                    if stored and str(stored).strip():
                        has_code = True
                    else:
                        # Calcule et persiste si les champs source sont renseignés
                        code = compute_codestation(jd.get("survey", {}), obs_block)
                        if code and code.strip():
                            has_code = True
                            code_obs = obs_block.get("codeObs", {})
                            code_obs["value"] = code
                            obs_block["codeObs"] = code_obs
                            jd["video_observation"] = obs_block
                            with open(jp, "w", encoding="utf-8") as fw:
                                _json.dump(jd, fw, indent=4, ensure_ascii=False)
                except Exception as _e:
                    print(f"[ARUCO] ERREUR filtre {os.path.basename(vp)}: {_e}")
            if not has_code:
                if skip_already_scanned and vp in self._aruco_results:
                    continue
                videos_to_scan.append(vp)

        print(f"[ARUCO] Analyse : {len(all_videos)} vidéos, "
              f"{len(all_videos) - len(videos_to_scan)} déjà traitées, "
              f"{len(videos_to_scan)} à scanner.")

        total_all = len(all_videos)
        to_scan = len(videos_to_scan)
        already = total_all - to_scan

        if not videos_to_scan:
            print(f"[ARUCO] Toutes les vidéos ({total_all}) déjà traitées — scan ignoré.")
            if step_cb:
                step_cb(
                    self.translate(
                        f"QRcode : {total_all}/{total_all} vidéos déjà traitées",
                        f"QRcode : {total_all}/{total_all} videos already processed"),
                    total_all, total_all)
            return

        print(f"[ARUCO] Tentatives de scan sur {to_scan}/{total_all} vidéo(s) "
              f"({already} déjà traitées)…")

        found = 0
        for i, vp in enumerate(videos_to_scan):
            name = os.path.basename(vp)
            if step_cb:
                step_cb(
                    self.translate(
                        f"Scan QRcode : tentative {i + 1}/{to_scan} — {name}",
                        f"QRcode scan: attempt {i + 1}/{to_scan} — {name}"),
                    i + 1, to_scan)
            QtWidgets.QApplication.processEvents()

            result = detect_aruco_in_video(vp, progress_cb=frame_cb)
            if result:
                self._aruco_results[vp] = result
                found += 1

        total_found = found + already
        print(f"[ARUCO] Scan terminé : {total_found}/{total_all} QRcode(s) disponibles "
              f"({found} nouveau(x) détecté(s)).")
        # Mettre à jour le delegate de la page Validation pour afficher les scores dans la liste
        _vd = getattr(getattr(self, "validation_ctrl", None), "_bar_delegate", None)
        if _vd and hasattr(_vd, "set_aruco_results"):
            _vd.set_aruco_results(self._aruco_results)

        if step_cb:
            step_cb(
                self.translate(
                    f"QRcode : {total_found}/{total_all} détectés "
                    f"({to_scan} tentative(s))",
                    f"QRcode : {total_found}/{total_all} detected "
                    f"({to_scan} attempt(s))"),
                to_scan, to_scan)

    def _detect_campaign_mode(self):
        """Détermine le mode et les systèmes de la campagne en scannant toutes les vidéos."""
        model = self.qualif_ctrl.video_model
        if model.rowCount() == 0:
            self._current_campaign_mode = ""
            self._update_systems_label([])
            return
        stereo_count = 0
        total = 0
        systems_ordered: list[str] = []
        systems_seen: set[str] = set()
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            if not item:
                continue
            path = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not path:
                continue
            total += 1
            is_stereo, _ = check_stereo_status(str(path))
            if is_stereo:
                stereo_count += 1
            sys_name = get_system_name(str(path))
            if sys_name not in systems_seen:
                systems_seen.add(sys_name)
                systems_ordered.append(sys_name)
        if total == 0:
            self._current_campaign_mode = ""
        elif stereo_count == 0:
            self._current_campaign_mode = "MONO"
        elif stereo_count == total:
            self._current_campaign_mode = "STEREO"
        else:
            self._current_campaign_mode = "MIXTE"
        self._update_systems_label(systems_ordered)

    def _update_systems_label(self, systems: list[str]):
        """Met à jour le label systèmes dans la toolbar."""
        w = self.window
        if not hasattr(w, 'systems_label'):
            return
        if not systems:
            w._systems_action.setVisible(False)
            return
        n = len(systems)
        label = f"{n} système{'s' if n > 1 else ''} : {' · '.join(systems)}"
        w.systems_label.setText(label)
        w.systems_label.setStyleSheet(
            "color: #a0c8e0; font-family: 'Segoe UI', sans-serif;"
            " font-size: 10px; padding: 2px 8px; border: 1px solid #405870;"
            " border-radius: 3px; letter-spacing: 0.3px;"
        )
        w._systems_action.setVisible(True)

    def _refresh_all_page_models(self):
        """Recharge le VideoModel dans tous les controllers de page après ouverture de campagne."""
        updated_model = self.qualif_ctrl.video_model
        for ctrl, method in [
            (self.validation_ctrl, 'load_campaign_videos'),
            (self.evenements_ctrl, 'load_campaign_videos'),
            (self.metadonnees_ctrl, 'load_campaign_videos'),
            (self.extraction_ctrl, 'load_campaign_videos'),
        ]:
            if hasattr(ctrl, method):
                getattr(ctrl, method)(updated_model)
        QtCore.QTimer.singleShot(200, self.qualif_ctrl.initialize_tree_indicators)

    # --- Vérifications de contenu ---

    # --- Navigation ---

    def lock_navigation(self, locked: bool):
        """Active ou désactive les actions de navigation (verrouillé tant qu'aucune campagne n'est chargée)."""
        w = self.window
        w.actionQualification.setEnabled(not locked)
        w.actionExtraction.setEnabled(not locked)
        w.actionValidation.setEnabled(not locked)
        w.actionEvenements.setEnabled(not locked)
        w.actionMetadonnees.setEnabled(not locked)
        w.actionA_propos.setEnabled(not locked)

    def _release_file_in_all_players(self, path: str):
        """Libère le verrou Windows sur un fichier vidéo dans tous les players embarqués."""
        for player in [
            getattr(self.validation_ctrl, 'player', None),
            getattr(self.evenements_ctrl, 'event_player', None),
            getattr(self.extraction_ctrl, 'video_player', None),
        ]:
            if player is not None and hasattr(player, 'release_video_file'):
                player.release_video_file(path)

    def _stop_background_players(self, target_page):
        """Arrête les lecteurs de la page qu'on quitte pour éviter l'accumulation."""
        w = self.window
        current = w.stackedWidget.currentWidget()
        if current == target_page:
            return

    def switch_page(self, page):
        """Bascule vers page si le workflow le permet, arrête les lecteurs de la page courante."""
        w = self.window
        free_pages = [w.page_accueil, w.page_apropos, w.page_extraction, w.page_metadonnees,
                      w.page_analyse_habitat]

        self._stop_background_players(page)

        if page in free_pages:
            w.stackedWidget.setCurrentWidget(page)
            w.update_nav_highlight(page)
            if page == w.page_extraction:
                self.extraction_ctrl.refresh_video_list()
            if page == w.page_metadonnees:
                def _refresh_meta_layout(p=page):
                    if p.layout():
                        p.layout().activate()
                    p.updateGeometry()
                    p.update()
                QtCore.QTimer.singleShot(0, _refresh_meta_layout)
            self._focus_page_player(page)
            self._refresh_generate_temp_visibility(page)
            return

        if not w.actionQualification.isEnabled():
            return

        if page == w.page_extraction:
            self.extraction_ctrl.refresh_video_list()

        w.stackedWidget.setCurrentWidget(page)
        w.update_nav_highlight(page)

        self._focus_page_player(page)
        self._refresh_generate_temp_visibility(page)

    def _refresh_generate_temp_visibility(self, page=None):
        # Bouton supprimé — la génération est automatique à l'import (voir _load_historical_data)
        if hasattr(self.window, '_act_generate_temp'):
            self.window._act_generate_temp.setVisible(False)

    def _get_page_player(self, page):
        """Retourne le player embarqué (EmbeddedVideoPlayer) associé à *page*, ou None."""
        w = self.window
        player_map = {
            w.page_validation: (self.validation_ctrl, 'player'),
            w.page_evenements: (self.evenements_ctrl, 'event_player'),
            w.page_extraction: (self.extraction_ctrl, 'video_player'),
        }
        entry = player_map.get(page)
        if not entry:
            return None
        ctrl, attr = entry
        return getattr(ctrl, attr, None)

    def _focus_page_player(self, page):
        """Donne le focus clavier au player embarqué de la page, si présent."""
        player = self._get_page_player(page)
        if player is not None:
            # Délai non nul : à 0ms, le focus donné au bouton de nav cliqué (ou au
            # widget par défaut de la page) reprend parfois la main juste après.
            QtCore.QTimer.singleShot(80, player.setFocus)

    _SPEED_KEYS = {
        QtCore.Qt.Key.Key_Plus: +1, QtCore.Qt.Key.Key_Equal: +1,
        QtCore.Qt.Key.Key_Minus: -1, QtCore.Qt.Key.Key_Underscore: -1,
    }
    _TEXT_INPUT_TYPES = (
        QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
        QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox,
    )

    def eventFilter(self, obj, event):
        """Intercepte +/- au niveau application pour changer la vitesse du player de la
        page actuellement affichée, sans dépendre du focus précis d'un widget — ça marche
        dès l'arrivée sur la page, pas seulement après avoir cliqué dedans."""
        if event.type() == QtCore.QEvent.Type.KeyPress:
            direction = self._SPEED_KEYS.get(event.key())
            if direction is not None:
                focus_w = QtWidgets.QApplication.focusWidget()
                if not isinstance(focus_w, self._TEXT_INPUT_TYPES):
                    page = self.window.stackedWidget.currentWidget()
                    player = self._get_page_player(page)
                    if player is not None and hasattr(player, '_speed_step'):
                        player._speed_step(direction)
                        rate = player.player.playbackRate() or 1.0
                        rate_str = f"×{int(rate) if rate == int(rate) else rate}"
                        icon = "⬆" if direction > 0 else "⬇"
                        if hasattr(player, 'show_fs_osd'):
                            player.show_fs_osd(f"{icon}  {rate_str}")
                        return True
        return super().eventFilter(obj, event)

    def _focus_map(self, video_name: str):
        """Focalise la carte Leaflet sur la vidéo dont le nom est fourni."""
        self.qualif_ctrl.update_minimap(video_name)

    def _open_map_from_metadonnees(self, video_name: str = None):
        """Ouvre la carte de campagne (QDialog Leaflet) depuis la page Métadonnées."""
        # Toujours reconstruire la carte : les données (coords, extra_points) ont pu changer
        # depuis la dernière ouverture (import CSV, correction manuelle, etc.).
        if self.working_dir and self.qualif_ctrl._working_dir != self.working_dir:
            self.qualif_ctrl._working_dir = self.working_dir
        self.qualif_ctrl.map_initialized = False
        self.qualif_ctrl._map_has_gps = False
        extra_points = {}
        # En mode données historiques (video_model vide), alimenter la carte depuis le tableau CSV
        if self.qualif_ctrl.video_model.rowCount() == 0:
            wd = self.working_dir or getattr(self.metadonnees_ctrl, '_csv_folder', '') or ''
            extra_points = self.metadonnees_ctrl.collect_ft_table_coords(wd)
        print(f"[MAP] _open_map_from_metadonnees: video_model.rowCount={self.qualif_ctrl.video_model.rowCount()}, "
              f"extra_points={len(extra_points)}, working_dir={self.working_dir!r}, "
              f"csv_folder={getattr(self.metadonnees_ctrl,'_csv_folder','')!r}")
        self.qualif_ctrl.update_minimap(video_name, show_dialog=True, extra_points=extra_points)

    def _refresh_dashboard(self, *_):
        """Recalcule les donuts du panneau Avancement."""
        model = self.qualif_ctrl.video_model
        paths = [
            model.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            for row in range(model.rowCount())
            if model.item(row, 0) and model.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        ]
        trash_count = self.qualif_ctrl.trash_model.rowCount()
        self._avancement_panel.dashboard.refresh(paths, trash_count)
        if hasattr(self.window, 'btn_avancement'):
            self.window.btn_avancement.setEnabled(True)

    def refresh_status_bar(self, *_):
        """Recalcule et affiche les stats de campagne dans la barre de statut."""
        model = self.qualif_ctrl.video_model
        n = model.rowCount()
        total_sec = 0
        qualified = 0
        for row in range(n):
            dur_item = model.item(row, 1)
            if dur_item:
                parts = dur_item.text().split(":")
                if len(parts) == 2:
                    try:
                        total_sec += int(parts[0]) * 60 + int(parts[1])
                    except ValueError:
                        pass
            path_item = model.item(row, 0)
            if path_item:
                video_path = path_item.data(QtCore.Qt.ItemDataRole.UserRole)
                if video_path:
                    json_path = get_video_json_path(video_path)
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            val = data.get("video_observation", {}).get("exploitable", {}).get("value")
                            if val and str(val).strip():
                                qualified += 1
                        except Exception:
                            pass
        self.window.update_status_bar(n, total_sec, qualified)
