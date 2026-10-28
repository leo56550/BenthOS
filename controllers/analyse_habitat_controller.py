"""Contrôleur de la page Analyse Habitat."""

from __future__ import annotations
import json
import os
import re as _re
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6 import QtWidgets, QtCore, QtGui

import cv2
import numpy as np
from services.image_service import (
    extract_frame_at_time,
    process_image_he,
    calculate_water_light,
    process_image_dehaze,
)
from services.campaign_service import resolve_video_json_path
from services.motor_service import find_video_csv
from views.widgets.embedded_player import EmbeddedVideoPlayer

# ── Schéma du formulaire ──────────────────────────────────────────────────────
# (section_name, note, [(field_key, label, type)])
# types: "score15" | "score13" | "percent" | "presence" | "count" | "total"
_SCHEMA: list[tuple[str, str, list]] = [
    ("Topo et complexité", "codage 1–5, obligatoire", [
        ("topographie",  "Topographie",  "score15"),
        ("complexite",   "Complexité",   "score15"),
    ]),
    ("Recouvrement visible", "% de la surface totale observée", [
        ("sable",               "Sable",                         "percent"),
        ("vase",                "Vase",                          "percent"),
        ("debris_petits",       "Débris, petits blocs (<30cm)",  "percent"),
        ("moyens_blocs",        "Moyens blocs (30cm–1m)",        "percent"),
        ("gros_blocs",          "Gros blocs et roche (>1m)",     "percent"),
        ("dalle",               "Dalle",                         "percent"),
        ("bioconstruit",        "Bioconstruit",                  "percent"),
        ("haploops",            "Haploops",                      "percent"),
        ("maerl",               "Maerl",                         "percent"),
        ("algues_snv",          "Algues / substrat non-visible", "percent"),
        ("herbier_snv",         "Herbier / substrat non-visible","percent"),
        ("total_recouvrement",  "TOTAL",                         "total"),
    ]),
    ("Herbier ou Algues sur substrat visible", "% de la surface totale observée", [
        ("algues_sv",   "Algues sur substrat visible",  "percent"),
        ("herbier_sv",  "Herbier sur substrat visible", "percent"),
    ]),
    ("Recouvrement Herbier", "somme à 100 % par secteur", [
        ("total_herbier",      "Total herbier",             "percent"),
        ("herbier_court",      "Herbier court (<20cm)",     "percent"),
        ("herbier_haut",       "Herbier haut (>20cm)",      "percent"),
        ("herbier_dense",      "Herbier dense",             "percent"),
        ("herbier_semi_dense", "Herbier semi-dense",        "percent"),
        ("herbier_clairseme",  "Herbier clairsemé (<25%)",  "percent"),
        ("matte_morte",        "Matte morte",               "percent"),
        ("epib_herbier",       "Épibiontes herbier",        "score13"),
    ]),
    ("Recouvrement Algues", "somme à 100 % par secteur", [
        ("alg_brunes_nid",  "Algues brunes non ID",          "percent"),
        ("alg_brunes_lam",  "Algues brunes – Laminariales",  "percent"),
        ("alg_fucus",       "Algues brunes – Fucus",         "percent"),
        ("alg_sargasses",   "Algues brunes – Sargasses",     "percent"),
        ("alg_halidrys",    "Algues brunes – Halidrys",      "percent"),
        ("alg_vertes",      "Algues vertes",                 "percent"),
        ("alg_rouges",      "Algues rouges",                 "percent"),
        ("total_algues",    "TOTAL algues",                  "total"),
        ("epib_algues",     "Épibiontes algues",             "score13"),
    ]),
    ("Présence Algues", "0 ou 1, obligatoire", [
        ("laminaria_sp",     "Laminaria sp.",           "presence"),
        ("laminaria_hyp",    "Laminaria hyperborea",    "presence"),
        ("laminaria_dig",    "Laminaria digitata",      "presence"),
        ("laminaria_och",    "Laminaria ochroleuca",    "presence"),
        ("himanthalia",      "Himanthalia elongata",    "presence"),
        ("saccharina",       "Saccharina latissima",    "presence"),
        ("sacchorhiza",      "Sacchorhiza polyschides", "presence"),
        ("undaria",          "Undaria pinnatifida",     "presence"),
        ("cystoseira",       "Cystoseira",              "presence"),
        ("padina",           "Padina",                  "presence"),
        ("ulva",             "Ulva spp.",               "presence"),
        ("codium",           "Codium spp.",             "presence"),
        ("chondrus",         "Chondrus crispus",        "presence"),
        ("palmaria",         "Palmaria palmata",        "presence"),
        ("solieria",         "Solieria chordalis",      "presence"),
        ("corallines",       "Corallines",              "presence"),
    ]),
    ("Invertébrés remarquables", "nombre d'individus par secteur", [
        ("huitres",       "Huîtres",            "count"),
        ("moules",        "Moules",             "count"),
        ("eponge",        "Éponge",             "count"),
        ("oursin",        "Oursin",             "count"),
        ("holothurie",    "Holothurie",         "count"),
        ("crabe",         "Crabe",              "count"),
        ("ormeau",        "Ormeau",             "count"),
        ("gorgone",       "Gorgone",            "count"),
        ("etoile_mer",    "Étoile de mer",      "count"),
        ("anemone",       "Anémone",            "count"),
        ("ascidie",       "Ascidie",            "count"),
        ("coquille_stj",  "Coquille St-Jacques","count"),
        ("autres_crust",  "Autres crustacés",   "count"),
        ("autres_coq",    "Autres coquillages", "count"),
    ]),
    ("Anthropisation", "", [
        ("etat_sante",   "Etat de santé herbier/algues",  "score13_sante"),
        ("engins_peche", "Engins de pêche",               "presence"),
        ("macrochets",   "Macrodéchets",                  "presence"),
    ]),
]

# Champs sources de chaque total auto-calculé
_TOTAL_SOURCES: dict[str, list[str]] = {
    "total_recouvrement": [
        "sable","vase","debris_petits","moyens_blocs","gros_blocs","dalle",
        "bioconstruit","haploops","maerl","algues_snv","herbier_snv",
    ],
    "total_algues": [
        "alg_brunes_nid","alg_brunes_lam","alg_fucus","alg_sargasses",
        "alg_halidrys","alg_vertes","alg_rouges",
    ],
}

# Encodage JSON par section de _SCHEMA :
#   "flat"  → chaque champ est ajouté directement dans le dict secteur
#   "dict"  → champs regroupés dans un sous-dict (clé = 2e élément)
#   "list"  → liste des clés dont la valeur == 1 (presence)
#   "dict_count" → dict {clé: valeur} pour les comptages (invertébrés)
_JSON_SECTION: dict[str, tuple[str, str | None]] = {
    "Topo et complexité":                        ("flat",        None),
    "Recouvrement visible":                      ("dict",        "recouvrement_visible"),
    "Herbier ou Algues sur substrat visible":    ("flat",        None),
    "Recouvrement Herbier":                      ("dict",        "recouvrement_herbier"),
    "Recouvrement Algues":                       ("dict",        "recouvrement_algues"),
    "Présence Algues":                           ("list",        "presence_algues"),
    "Invertébrés remarquables":                  ("dict_count",  "invertebres"),
    "Anthropisation":                            ("flat",        None),
}

# Ordre exact + mapping clé→label Excel pour l'export XLSX (ref: Masque saisie CC 2022)
_XLSX_LAYOUT: list[tuple[str, list]] = [
    ("Topo et complexité", [
        ("topographie",       "Topographie (1-5)"),
        ("complexite",        "Complexité (1-5)"),
    ]),
    ("Recouvrement visible", [
        ("sable",              "Sable"),
        ("vase",               "Vase"),
        ("debris_petits",      "Débris, petits blocs (<30cm)"),
        ("moyens_blocs",       "Moyens blocs (30cm<l<1m)"),
        ("gros_blocs",         "Gros blocs et roche (>1m)"),
        ("dalle",              "Dalle"),
        ("bioconstruit",       "Bioconstruit"),
        ("haploops",           "Haploops"),
        ("maerl",              "Maerl"),
        ("algues_snv",         "Algues sur substrat non-visible"),
        ("herbier_snv",        "Herbier sur substrat non-visible"),
        ("total_recouvrement", "Total du recouvrement"),
    ]),
    ("Herbier ou Algues sur substrat visible", [
        ("algues_sv",   "Algues sur substrat visible"),
        ("herbier_sv",  "Herbier sur substrat visible"),
    ]),
    ("Recouvrement Herbier", [
        ("total_herbier",      "Total herbier"),
        ("herbier_court",      "Herbier court (<20cm)"),
        ("herbier_haut",       "Herbier haut (>20cm)"),
        ("herbier_dense",      "Herbier dense (sable non visible)"),
        ("herbier_semi_dense", "Herbier semi-dense"),
        ("herbier_clairseme",  "Herbier clairsemé (<25%)"),
        ("matte_morte",        "Matte morte"),
    ]),
    ("Recouvrement par épibiontes", [
        ("epib_algues",   "Algues"),
        ("epib_herbier",  "Herbier"),
    ]),
    ("Recouvrement Algues", [
        ("alg_brunes_nid", "Algues brunes non ID"),
        ("alg_brunes_lam", "Algues brunes - Laminariales"),
        ("alg_fucus",      "Algues brunes à Fucales - Fucus"),
        ("alg_sargasses",  "Algues brunes - Fucales - Sargasses"),
        ("alg_halidrys",   "Algues brunes - Fucales - Halidrys"),
        ("alg_vertes",     "Algues vertes"),
        ("alg_rouges",     "Algues rouges"),
        ("total_algues",   "Total algues"),
    ]),
    ("Présence Algues", [
        ("laminaria_sp",    "Laminaria sp."),
        ("laminaria_hyp",   "Laminaria hyperborea"),
        ("laminaria_dig",   "Laminaria digitata"),
        ("laminaria_och",   "Laminaria ochroleuca"),
        ("himanthalia",     "Himanthalia elongata"),
        ("saccharina",      "Saccharina latissima"),
        ("sacchorhiza",     "Sacchorhiza polyschides"),
        ("undaria",         "Undaria pinnatifida"),
        ("cystoseira",      "Cystoseira"),
        ("padina",          "Padina"),
        ("ulva",            "Ulva spp."),
        ("codium",          "Codium spp."),
        ("chondrus",        "Chondrus crispus"),
        ("palmaria",        "Palmaria palmata"),
        ("solieria",        "Solieria chordalis"),
        ("corallines",      "Corallines"),
    ]),
    ("Invertébrés remarquables", [
        ("huitres",      "Huîtres"),
        ("moules",       "Moules"),
        ("eponge",       "Eponge"),
        ("oursin",       "Oursin"),
        ("holothurie",   "Holothurie"),
        ("crabe",        "Crabe"),
        ("ormeau",       "Ormeau"),
        ("gorgone",      "Gorgone"),
        ("etoile_mer",   "Etoile de mer"),
        ("anemone",      "Anémone"),
        ("ascidie",      "Ascidie"),
        ("coquille_stj", "Coquille St-Jacques"),
        ("autres_crust", "Autres crustacés"),
        ("autres_coq",   "Autres coquillages"),
    ]),
    ("Anthropisation", [
        ("etat_sante",   "Etat de santé herbier et algues"),
        ("engins_peche", "Engins de pêche"),
        ("macrochets",   "Macrodéchets"),
    ]),
    ("Captures écran", []),
]

_COL_W   = 72   # largeur d'un secteur (plus large pour la flèche combobox)
_LABEL_W = 240  # largeur de la colonne label
_THUMB_H = 90   # hauteur des thumbnails dans la barre d'en-tête
_HEADER_H = _THUMB_H + 28  # hauteur totale de la barre d'en-tête

# Types de recouvrement visible (même ordre que dans _SCHEMA)
_RECOUVREMENT_TYPES: list[tuple[str, str]] = [
    ("sable",         "Sable"),
    ("vase",          "Vase"),
    ("debris_petits", "Débris, petits blocs (<30cm)"),
    ("moyens_blocs",  "Moyens blocs (30cm–1m)"),
    ("gros_blocs",    "Gros blocs et roche (>1m)"),
    ("dalle",         "Dalle"),
    ("bioconstruit",  "Bioconstruit"),
    ("haploops",      "Haploops"),
    ("maerl",         "Maerl"),
    ("algues_snv",    "Algues / substrat non-visible"),
    ("herbier_snv",   "Herbier / substrat non-visible"),
]

# Mots-clés non-rotation à exclure des events_motor
_NON_ROTATION = {"atterrissage", "atterissage", "décollage", "decollage",
                 "landing", "takeoff", "debut_analyse", "fin_analyse",
                 "analysis_start", "analysis_end"}

# Dictionnaire de traduction FR→EN
_EN: dict[str, str] = {
    # Titres de sections
    "Topo et complexité":                    "Topo and complexity",
    "Recouvrement visible":                  "Visible coverage",
    "Herbier ou Algues sur substrat visible": "Seagrass or Algae on visible substrate",
    "Recouvrement Herbier":                  "Seagrass coverage",
    "Recouvrement par épibiontes":           "Epibiont coverage",
    "Recouvrement Algues":                   "Algae coverage",
    "Présence Algues":                       "Algae presence",
    "Invertébrés remarquables":              "Notable invertebrates",
    "Anthropisation":                        "Anthropization",
    # Notes de sections
    "codage 1–5, obligatoire":               "score 1–5, mandatory",
    "% de la surface totale observée":       "% of total observed surface",
    "somme à 100 % par secteur":             "sum to 100% per sector",
    "1=non, 2=un peu, 3=beaucoup":           "1=no, 2=a little, 3=a lot",
    "nombre d'individus par secteur":        "number of individuals per sector",
    "0 ou 1, obligatoire":                   "0 or 1, mandatory",
    # Labels de champs
    "Topographie":                  "Topography",
    "Complexité":                   "Complexity",
    "Débris, petits blocs (<30cm)": "Debris, small blocks (<30cm)",
    "Moyens blocs (30cm–1m)":       "Medium blocks (30cm–1m)",
    "Gros blocs et roche (>1m)":    "Large blocks and rock (>1m)",
    "Algues / substrat non-visible":  "Algae / non-visible substrate",
    "Herbier / substrat non-visible": "Seagrass / non-visible substrate",
    "Algues sur substrat visible":  "Algae on visible substrate",
    "Herbier sur substrat visible": "Seagrass on visible substrate",
    "Total herbier":                "Total seagrass",
    "Herbier court (<20cm)":        "Short seagrass (<20cm)",
    "Herbier haut (>20cm)":         "Tall seagrass (>20cm)",
    "Herbier dense":                "Dense seagrass",
    "Herbier semi-dense":           "Semi-dense seagrass",
    "Herbier clairsemé (<25%)":     "Sparse seagrass (<25%)",
    "Matte morte":                  "Dead mat",
    "Algues brunes non ID":         "Brown algae unidentified",
    "Algues brunes – Laminariales": "Brown algae – Laminariales",
    "Algues brunes – Fucus":        "Brown algae – Fucus",
    "Algues brunes – Sargasses":    "Brown algae – Sargassum",
    "Algues brunes – Halidrys":     "Brown algae – Halidrys",
    "Algues vertes":                "Green algae",
    "Algues rouges":                "Red algae",
    "TOTAL algues":                 "TOTAL algae",
    "Huîtres":                      "Oysters",
    "Moules":                       "Mussels",
    "Éponge":                       "Sponge",
    "Oursin":                       "Sea urchin",
    "Holothurie":                   "Sea cucumber",
    "Crabe":                        "Crab",
    "Ormeau":                       "Abalone",
    "Gorgone":                      "Gorgonian",
    "Étoile de mer":                "Starfish",
    "Anémone":                      "Anemone",
    "Ascidie":                      "Tunicate",
    "Coquille St-Jacques":          "Scallop",
    "Autres crustacés":             "Other crustaceans",
    "Autres coquillages":           "Other shellfish",
    "Etat de santé herbier/algues": "Seagrass/algae health status",
    "Engins de pêche":              "Fishing gear",
    "Macrodéchets":                 "Macrodetritus",
    # Panneau analyse vidéo
    "Analyseur poisson":            "Fish annotator",
    "Analyseur habitat":            "Habitat annotator",
    "Substrat":                     "Substrate",
    "Visibilité (m)":               "Visibility (m)",
    "Distance analysable (m)":      "Analysable distance (m)",
    # Labels UI
    "Analyse vidéo":                "Video analysis",
    "Sélectionnez une station dans la liste": "Select a station from the list",
    # Widget cascade
    "Total :":                      "Total:",
    "+ Ajouter un substrat":        "+ Add substrate",
}


# ── Worker extraction de frames ───────────────────────────────────────────────

class _FrameWorker(QtCore.QThread):
    frame_ready = QtCore.pyqtSignal(int, object)  # (sector_idx, ndarray|None)

    def __init__(self, tasks: list, parent=None):
        super().__init__(parent)
        self._tasks = tasks  # [(sector_idx, video_path, timestamp_s)]

    def run(self):
        def _extract(task):
            idx, vpath, ts = task
            frame = extract_frame_at_time(vpath, ts)
            return idx, frame

        with ThreadPoolExecutor(max_workers=min(4, len(self._tasks) or 1)) as pool:
            futures = {pool.submit(_extract, t): t for t in self._tasks}
            for fut in as_completed(futures):
                if self.isInterruptionRequested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    idx, frame = fut.result()
                    self.frame_ready.emit(idx, frame)
                except Exception:
                    pass


# ── Fenêtre flottante avec lecteur vidéo complet ─────────────────────────────

class _SectorVideoWindow(QtWidgets.QWidget):
    """Fenêtre détachable contenant l'EmbeddedVideoPlayer restreint à la plage du secteur."""

    def __init__(self, video_path: str, clip_start_ms: int, clip_end_ms: int,
                 title: str = "", parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setWindowTitle(title)
        self.setStyleSheet("background:#0b1421;")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1100, 720)

        self._clip_start = clip_start_ms
        self._clip_end   = clip_end_ms
        self._video_path = video_path

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.player = EmbeddedVideoPlayer(parent=self)
        self.player.scroll_area_timeline.setVisible(False)
        lay.addWidget(self.player)

        QtCore.QTimer.singleShot(150, self._load)

    def _load(self):
        p = self.player
        start, end = self._clip_start, self._clip_end
        clip_dur = end - start

        # ── Tous les patches AVANT le chargement vidéo ──────────────────────
        # jump_time_offset : boutons ±5s ±10s et raccourcis ← → (invoqués via lambda)
        def _clamped_jump(ms: int):
            target = max(start, min(p.player.position() + ms, end))
            p.player.setPosition(target)
            if p.is_stereo:
                p.player_R.setPosition(target)
            if p.left_display.currentIndex() == 1:
                QtCore.QTimer.singleShot(80, lambda: p._step_frame_overlay(target))
        p.jump_time_offset = _clamped_jump

        # _step_frame : Shift+← →, image par image (invoqué via lambda → patchable)
        def _clamped_step(direction: int):
            fps = p.video_fps
            if not fps or fps <= 0:
                return
            frame_ms = max(1, int(1000 / fps))
            target = max(start, min(p.player.position() + direction * frame_ms, end))
            p.player.setPosition(target)
            if p.is_stereo:
                p.player_R.setPosition(target)
            if p.left_display.currentIndex() == 1:
                QtCore.QTimer.singleShot(50, lambda: p._step_frame_overlay(target))
        p._step_frame = _clamped_step

        # btn_goto_start : connecté directement à la méthode liée → reconnecter
        try:
            p.btn_goto_start.clicked.disconnect()
        except Exception:
            pass
        p.btn_goto_start.clicked.connect(lambda: p.player.setPosition(start))
        p.btn_goto_start.setToolTip("Retour au début du secteur")

        # Label de temps : affiche la position et la durée relatives au secteur
        def _sector_time_label(pos_ms: int, _total_ms: int):
            rel_ms = max(0, pos_ms - start)
            pos_s  = rel_ms // 1000
            dur_s  = clip_dur // 1000
            p.lbl_top_time.setText(
                f"{pos_s // 60:02d}:{pos_s % 60:02d} / {dur_s // 60:02d}:{dur_s % 60:02d}"
            )
        p.update_top_time_label = _sector_time_label

        # Timer 100ms : filet de sécurité couvrant tout chemin non intercepté
        self._clip_timer = QtCore.QTimer(self)
        self._clip_timer.setInterval(100)
        self._clip_timer.timeout.connect(self._poll_bounds)
        self._clip_timer.start()

        # ── Chargement de la vidéo ───────────────────────────────────────────
        p.load_video_and_events(
            self._video_path, [],
            is_stereo=False,
            start_position_ms=self._clip_start,
        )
        csv_tel = find_video_csv(self._video_path)
        if os.path.isfile(csv_tel):
            p.load_dynamic_metadata(csv_tel)

    def _poll_bounds(self):
        try:
            pos = self.player.player.position()
        except RuntimeError:
            return
        if pos < self._clip_start:
            self.player.player.setPosition(self._clip_start)
        elif pos > self._clip_end:
            self.player.player.pause()
            self.player.player.setPosition(self._clip_end)

    def closeEvent(self, event):
        if hasattr(self, '_clip_timer'):
            self._clip_timer.stop()
        super().closeEvent(event)


# ── Widgets du formulaire ─────────────────────────────────────────────────────

_COMBO_SS_BASE = (
    "QComboBox {{ background:{bg}; color:#c8e0f0;"
    " border:1px solid {bd}; border-radius:3px;"
    " font-size:11px; padding:1px 4px; }}"
    "QComboBox:focus {{ border-color:#2778a2; }}"
    "QComboBox::drop-down {{ border:none; width:16px; }}"
    "QComboBox::down-arrow {{ image:none; width:0; }}"
    "QComboBox QAbstractItemView {{"
    " background:#0d1e2e; color:#c8e0f0; border:1px solid #2778a2;"
    " selection-background-color:#1a3a54; font-size:11px; }}"
)

_BG_FILLED  = "#0d2a18"   # vert foncé quand rempli
_BD_FILLED  = "#1a6634"   # bordure verte
_BD_EMPTY   = "#1e3448"   # bordure par défaut

# Listes de (label affiché, valeur entière) pour chaque type
_COMBO_ITEMS: dict[str, list[tuple[str, int]]] = {
    "score15": [("—", 0), ("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5)],
    "score13": [("—", 0), ("1 – non", 1), ("2 – peu", 2), ("3 – bcp", 3)],
    "score13_sante": [("—", 0), ("1 – non impacté", 1), ("2 – moyen", 2), ("3 – très impacté", 3)],
    "percent": [(f"{v} %", v) for v in range(0, 101, 5)],
    "count":   ([(str(v), v) for v in range(0, 21)]
                + [("25", 25), ("30", 30), ("40", 40), ("50", 50),
                   ("75", 75), ("100", 100)]),
}


class _SectorComboBox(QtWidgets.QComboBox):
    """ComboBox compact pour la saisie par secteur."""

    def __init__(self, ftype: str, bg_empty: str = "#0d1e2e", parent=None):
        super().__init__(parent)
        self._ftype    = ftype
        self._bg_empty = bg_empty
        self._values: list[int] = []
        for label, val in _COMBO_ITEMS.get(ftype, [("—", 0)]):
            self.addItem(label)
            self._values.append(val)
        self.setFixedWidth(_COL_W)
        self._apply_color()
        self.currentIndexChanged.connect(lambda _: self._apply_color())

    def _apply_color(self):
        filled = self.currentIndex() > 0
        bg = _BG_FILLED  if filled else self._bg_empty
        bd = _BD_FILLED  if filled else _BD_EMPTY
        self.setStyleSheet(_COMBO_SS_BASE.format(bg=bg, bd=bd))

    def get_value(self) -> int:
        idx = self.currentIndex()
        return self._values[idx] if 0 <= idx < len(self._values) else 0

    def set_value(self, v: int):
        if v in self._values:
            self.setCurrentIndex(self._values.index(v))
        else:
            closest = min(range(len(self._values)),
                          key=lambda i: abs(self._values[i] - v))
            self.setCurrentIndex(closest)

    def wheelEvent(self, e):
        e.ignore()


class _TotalLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__("—", parent)
        self.setFixedWidth(_COL_W)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "color:#f0c040; font-weight:bold; font-size:11px;"
            " background:#12253a; border:1px solid #2a3e50; border-radius:3px;"
            " padding:2px;"
        )


class _PresenceCheckBox(QtWidgets.QCheckBox):
    def __init__(self, bg_empty: str = "#0d1e2e", parent=None):
        super().__init__(parent)
        self._bg_empty = bg_empty
        self.setFixedWidth(_COL_W)
        self._apply_color()
        self.stateChanged.connect(lambda _: self._apply_color())

    def _apply_color(self):
        bg = _BG_FILLED if self.isChecked() else self._bg_empty
        bd = _BD_FILLED if self.isChecked() else _BD_EMPTY
        self.setStyleSheet(
            f"QCheckBox {{ color:#c8e0f0; background:{bg};"
            f" border:1px solid {bd}; border-radius:3px; padding:2px; }}"
            "QCheckBox::indicator { width:14px; height:14px; border:1px solid #2778a2;"
            " border-radius:3px; background:#0d1e2e; }"
            "QCheckBox::indicator:checked { background:#2778a2; }"
        )

    def wheelEvent(self, e):
        e.ignore()


class _CollapsibleSection(QtWidgets.QWidget):
    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(parent)
        self._collapsed = False
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(0)

        self._btn = QtWidgets.QToolButton()
        self._btn.setText(f"  ▼  {title}")
        self._btn.setCheckable(True)
        self._btn.setChecked(True)
        self._btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._btn.setStyleSheet(
            "QToolButton { background:#1a3a54; color:#7ec8e3;"
            " font-weight:bold; font-size:11px; font-family:'Segoe UI',sans-serif;"
            " border:none; border-radius:4px; padding:5px 8px;"
            " text-align:left; }"
            "QToolButton:hover { background:#20415d; }"
        )
        if note:
            self._btn.setToolTip(note)
        outer.addWidget(self._btn)

        self._content = QtWidgets.QWidget()
        self._content.setStyleSheet("background:#0b1825;")
        outer.addWidget(self._content)

        self._btn.clicked.connect(lambda _: self._toggle())

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        txt = self._btn.text()
        self._btn.setText(txt.replace("▼", arrow).replace("▶", arrow))

    def set_layout(self, layout):
        self._content.setLayout(layout)

    def set_locked(self, locked: bool):
        """Grise et désactive la section (contenu non accessible)."""
        self._btn.setEnabled(not locked)
        self._content.setVisible(not locked)
        if locked:
            self._btn.setStyleSheet(
                "QToolButton { background:#111f2e; color:#445566;"
                " font-weight:bold; font-size:11px; font-family:'Segoe UI',sans-serif;"
                " border:none; border-radius:4px; padding:5px 8px; text-align:left; }"
            )
            self._collapsed = True
        else:
            self._btn.setStyleSheet(
                "QToolButton { background:#1a3a54; color:#7ec8e3;"
                " font-weight:bold; font-size:11px; font-family:'Segoe UI',sans-serif;"
                " border:none; border-radius:4px; padding:5px 8px; text-align:left; }"
                "QToolButton:hover { background:#20415d; }"
            )
            self._collapsed = False
            self._content.setVisible(True)

    def retranslate(self, title: str, note: str = ""):
        arrow = "▶" if self._collapsed else "▼"
        self._btn.setText(f"  {arrow}  {title}")
        if note:
            self._btn.setToolTip(note)


# ── Canvas image zoomable/panable ────────────────────────────────────────────

class _TimelineSlider(QtWidgets.QWidget):
    """Slider horizontal avec timecode flottant au-dessus du curseur."""

    sliderPressed  = QtCore.pyqtSignal()
    sliderReleased = QtCore.pyqtSignal()
    sliderMoved    = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lbl = QtWidgets.QLabel("", self)
        self._lbl.setStyleSheet(
            "background: rgba(18,52,80,220); color: #7ec8e3;"
            " font-size: 8pt; padding: 1px 5px; border-radius: 3px;"
        )
        self._lbl.hide()

        self._slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._slider.setRange(0, 1000)
        self._slider.sliderPressed.connect(self.sliderPressed)
        self._slider.sliderReleased.connect(self.sliderReleased)
        self._slider.sliderMoved.connect(self.sliderMoved)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addSpacing(18)  # espace réservé pour le label flottant
        lay.addWidget(self._slider)
        self.setFixedHeight(18 + 14)

    # ── API ──────────────────────────────────────────────────────────────────

    def setRange(self, a, b):   self._slider.setRange(a, b)
    def setValue(self, v):      self._slider.setValue(v); self._move_label()
    def value(self):            return self._slider.value()
    def blockSignals(self, b):  self._slider.blockSignals(b)
    def setStyleSheet(self, s): self._slider.setStyleSheet(s)

    def set_time_text(self, text: str):
        if not text:
            self._lbl.hide()
            return
        self._lbl.setText(text)
        self._lbl.adjustSize()
        self._move_label()
        self._lbl.show()

    def _move_label(self):
        opt = QtWidgets.QStyleOptionSlider()
        self._slider.initStyleOption(opt)
        hr = self._slider.style().subControlRect(
            QtWidgets.QStyle.ComplexControl.CC_Slider, opt,
            QtWidgets.QStyle.SubControl.SC_SliderHandle, self._slider)
        # convertir les coordonnées du slider vers ce widget
        cx = self._slider.mapTo(self, hr.center()).x()
        lw = self._lbl.width()
        x = max(0, min(cx - lw // 2, self.width() - lw))
        self._lbl.move(x, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._move_label()


class _ImageCanvas(QtWidgets.QWidget):
    """Zone d'affichage image zoomable (molette) et panable (clic-glisser)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QtGui.QPixmap | None = None
        self._zoom = 1.0
        self._offset = QtCore.QPointF(0.0, 0.0)
        self._last_mouse: QtCore.QPointF | None = None
        self.setStyleSheet("background:#0b1520;")
        self.setMinimumHeight(100)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

    def set_pixmap(self, pixmap: QtGui.QPixmap | None, reset: bool = True):
        self._pixmap = pixmap
        if reset:
            self._zoom = 1.0
            self._offset = QtCore.QPointF(0.0, 0.0)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#0b1520"))
        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QtGui.QColor("#2a4057"))
            painter.setFont(QtGui.QFont("Segoe UI", 12))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "—")
            return
        pw = self._pixmap.width() * self._zoom
        ph = self._pixmap.height() * self._zoom
        x = (self.width() - pw) / 2.0 + self._offset.x()
        y = (self.height() - ph) / 2.0 + self._offset.y()
        painter.drawPixmap(
            QtCore.QRectF(x, y, pw, ph),
            self._pixmap,
            QtCore.QRectF(self._pixmap.rect()),
        )

    def wheelEvent(self, event):
        if self._pixmap is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        old_zoom = self._zoom
        new_zoom = max(0.1, min(10.0, old_zoom * factor))
        if new_zoom == old_zoom:
            return
        pos = event.position()
        mx, my = pos.x(), pos.y()
        pw = self._pixmap.width() * old_zoom
        ph = self._pixmap.height() * old_zoom
        img_x = (self.width() - pw) / 2.0 + self._offset.x()
        img_y = (self.height() - ph) / 2.0 + self._offset.y()
        ix = (mx - img_x) / old_zoom
        iy = (my - img_y) / old_zoom
        new_pw = self._pixmap.width() * new_zoom
        new_ph = self._pixmap.height() * new_zoom
        self._offset = QtCore.QPointF(
            mx - ix * new_zoom - (self.width() - new_pw) / 2.0,
            my - iy * new_zoom - (self.height() - new_ph) / 2.0,
        )
        self._zoom = new_zoom
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._last_mouse = event.position()

    def mouseMoveEvent(self, event):
        if (self._last_mouse is not None
                and event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self._offset += event.position() - self._last_mouse
            self._last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self._last_mouse = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.zoom_fit()

    def zoom_in(self):
        self._zoom = min(10.0, self._zoom * 1.25)
        self.update()

    def zoom_out(self):
        self._zoom = max(0.1, self._zoom / 1.25)
        self.update()

    def zoom_fit(self):
        self._zoom = 1.0
        self._offset = QtCore.QPointF(0.0, 0.0)
        self.update()


# ── Viewer secteur : image + corrections + lecture vidéo ─────────────────────

class _SectorViewerWidget(QtWidgets.QWidget):
    """Afficheur secteur : image fixe + corrections HE/DH + lecture vidéo simple."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path: str | None = None
        self._fps = 25.0
        self._clip_start_ms = 0
        self._clip_end_ms = 0
        self._pos_ms = 0
        self._raw_frame: np.ndarray | None = None  # BGR
        self._apply_he = False
        self._apply_dh = False
        self._cap = None  # cv2.VideoCapture ouvert pendant la lecture

        self._play_timer = QtCore.QTimer(self)
        self._play_timer.timeout.connect(self._advance_frame)

        self._build_ui()
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(160)

    def _build_ui(self):
        vlay = QtWidgets.QVBoxLayout(self)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        self._canvas = _ImageCanvas(self)
        vlay.addWidget(self._canvas, 1)

        # Timeline / scrubber avec timecode au-dessus du curseur
        self._timeline = _TimelineSlider()
        self._timeline.setRange(0, 1000)
        self._timeline.setValue(0)
        self._timeline.setStyleSheet(
            "QSlider::groove:horizontal {"
            "  height:4px; background:#1a3448; border-radius:2px; margin:0 4px; }"
            "QSlider::sub-page:horizontal {"
            "  background:#2778a2; border-radius:2px; }"
            "QSlider::handle:horizontal {"
            "  width:10px; height:10px; margin:-3px 0;"
            "  background:#7ec8e3; border-radius:5px; }"
        )
        self._timeline.sliderPressed.connect(self._on_timeline_pressed)
        self._timeline.sliderReleased.connect(self._on_timeline_released)
        self._timeline.sliderMoved.connect(self._on_timeline_moved)
        self._timeline_dragging = False
        vlay.addWidget(self._timeline)

        ctrl = QtWidgets.QWidget()
        ctrl.setFixedHeight(34)
        ctrl.setStyleSheet("background:#0d1825; border-top:1px solid #1e3448;")
        cly = QtWidgets.QHBoxLayout(ctrl)
        cly.setContentsMargins(8, 3, 8, 3)
        cly.setSpacing(5)

        _ss = (
            "QPushButton { background:#1a2a3a; color:#7ec8e3;"
            " border:1px solid #2a4057; border-radius:3px;"
            " font-size:11px; padding:1px 7px; min-height:20px; }"
            "QPushButton:checked { background:#2778a2; color:#fff;"
            " border-color:#2778a2; }"
            "QPushButton:hover:!checked { background:#243848; }"
        )

        def _sep():
            s = QtWidgets.QFrame()
            s.setFrameShape(QtWidgets.QFrame.Shape.VLine)
            s.setStyleSheet("color:#1e3448;")
            s.setFixedWidth(1)
            return s

        self._btn_play = QtWidgets.QPushButton("▶")
        self._btn_play.setCheckable(True)
        self._btn_play.setFixedWidth(30)
        self._btn_play.setStyleSheet(_ss)
        self._btn_play.toggled.connect(self._on_play_toggled)
        cly.addWidget(self._btn_play)

        cly.addWidget(_sep())

        self._btn_he = QtWidgets.QPushButton("HE")
        self._btn_he.setCheckable(True)
        self._btn_he.setFixedWidth(34)
        self._btn_he.setStyleSheet(_ss)
        self._btn_he.toggled.connect(self._on_he_toggled)
        cly.addWidget(self._btn_he)

        self._btn_dh = QtWidgets.QPushButton("DH")
        self._btn_dh.setCheckable(True)
        self._btn_dh.setFixedWidth(34)
        self._btn_dh.setStyleSheet(_ss)
        self._btn_dh.toggled.connect(self._on_dh_toggled)
        cly.addWidget(self._btn_dh)

        cly.addWidget(_sep())

        for sym, slot in (("+", self._canvas.zoom_in),
                          ("−", self._canvas.zoom_out),
                          ("⊡", self._canvas.zoom_fit)):
            b = QtWidgets.QPushButton(sym)
            b.setFixedWidth(26)
            b.setStyleSheet(_ss)
            b.clicked.connect(slot)
            cly.addWidget(b)

        cly.addStretch()

        self._lbl_time = QtWidgets.QLabel("—")
        self._lbl_time.setStyleSheet(
            "color:#5a8090; font-size:11px; background:transparent;")
        cly.addWidget(self._lbl_time)

        vlay.addWidget(ctrl)

        # ── Barre navigation : ⏮  -5s -1s +1s +5s  |  x1 x2 x5 ──
        nav = QtWidgets.QWidget()
        nav.setFixedHeight(30)
        nav.setStyleSheet("background:#0d1825; border-top:1px solid #1a2e42;")
        nly = QtWidgets.QHBoxLayout(nav)
        nly.setContentsMargins(8, 2, 8, 2)
        nly.setSpacing(4)

        self._playback_rate = 1.0

        self._btn_goto_start = QtWidgets.QPushButton("⏮")
        self._btn_goto_start.setFixedWidth(28)
        self._btn_goto_start.setToolTip("Début du clip")
        self._btn_goto_start.setStyleSheet(_ss)
        self._btn_goto_start.clicked.connect(self._goto_clip_start)
        nly.addWidget(self._btn_goto_start)

        nly.addWidget(_sep())

        for label, ms in (("-5s", -5000), ("-1s", -1000), ("+1s", 1000), ("+5s", 5000)):
            b = QtWidgets.QPushButton(label)
            b.setFixedWidth(34)
            b.setStyleSheet(_ss)
            b.clicked.connect(lambda _=False, d=ms: self._jump(d))
            nly.addWidget(b)

        nly.addWidget(_sep())
        nly.addStretch()

        self._speed_btns: list[QtWidgets.QPushButton] = []
        for label, rate in (("x1", 1.0), ("x2", 2.0), ("x5", 5.0)):
            b = QtWidgets.QPushButton(label)
            b.setCheckable(True)
            b.setFixedWidth(30)
            b.setStyleSheet(_ss)
            b.clicked.connect(lambda _=False, r=rate: self._set_speed(r))
            nly.addWidget(b)
            self._speed_btns.append(b)
        self._speed_btns[0].setChecked(True)

        vlay.addWidget(nav)

    # ── API publique ──────────────────────────────────────────────────────────

    def load_sector(self, video_path: str,
                    clip_start_ms: int, clip_end_ms: int,
                    mid_ms: int | None = None):
        self._stop_playback()
        self._video_path = video_path
        self._clip_start_ms = clip_start_ms
        self._clip_end_ms = clip_end_ms
        cap_tmp = cv2.VideoCapture(video_path)
        fps = cap_tmp.get(cv2.CAP_PROP_FPS)
        cap_tmp.release()
        self._fps = fps if fps > 0 else 25.0
        # Curseur toujours à 0 (début du clip) ; mid_ms sert uniquement aux vignettes
        self._pos_ms = clip_start_ms
        self._read_and_show()

    def clear(self):
        self._stop_playback()
        self._video_path = None
        self._raw_frame = None
        self._canvas.set_pixmap(None)
        self._lbl_time.setText("—")
        self._timeline.set_time_text("")
        self._timeline.blockSignals(True)
        self._timeline.setValue(0)
        self._timeline.blockSignals(False)

    def show_frame_rgb(self, frame_rgb: np.ndarray):
        """Affiche une frame RGB (retournée par extract_frame_at_time)."""
        self._stop_playback()
        self._raw_frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        self._show_corrected()

    # ── Lecture ───────────────────────────────────────────────────────────────

    def _read_and_show(self):
        if not self._video_path:
            return
        frame_num = round(self._pos_ms * self._fps / 1000.0)
        cap = cv2.VideoCapture(self._video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        cap.release()
        if ret:
            self._raw_frame = frame
            self._show_corrected()

    def _show_corrected(self):
        if self._raw_frame is None:
            return
        frame = self._raw_frame.copy()
        if self._apply_he:
            frame = process_image_he(frame)
        if self._apply_dh:
            try:
                vec = calculate_water_light(frame)
                frame = process_image_dehaze(frame, vec, is_water=True)
            except Exception:
                pass
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QtGui.QImage(
            rgb.data, w, h, 3 * w,
            QtGui.QImage.Format.Format_RGB888,
        ).copy()
        self._canvas.set_pixmap(QtGui.QPixmap.fromImage(qimg), reset=False)
        s = max(0, self._pos_ms - self._clip_start_ms) // 1000
        time_str = f"{s // 60:02d}:{s % 60:02d}"
        self._lbl_time.setText(time_str)
        self._timeline.set_time_text(time_str)
        # Sync timeline (ne pas modifier si l'utilisateur est en train de glisser)
        if not self._timeline_dragging:
            dur = max(1, self._clip_end_ms - self._clip_start_ms)
            pos = max(0, min(1000, int((self._pos_ms - self._clip_start_ms) * 1000 / dur)))
            self._timeline.blockSignals(True)
            self._timeline.setValue(pos)
            self._timeline.blockSignals(False)

    def _on_timeline_pressed(self):
        self._timeline_dragging = True
        if self._play_timer.isActive():
            self._play_timer.stop()

    def _on_timeline_released(self):
        self._timeline_dragging = False
        dur = max(1, self._clip_end_ms - self._clip_start_ms)
        self._pos_ms = self._clip_start_ms + int(self._timeline.value() * dur / 1000)
        self._read_and_show()
        if self._btn_play.isChecked():
            # Reprendre la lecture depuis la nouvelle position
            if self._cap is not None:
                self._cap.release()
            self._cap = cv2.VideoCapture(self._video_path)
            frame_num = round(self._pos_ms * self._fps / 1000.0)
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            self._play_timer.start(max(16, int(1000.0 / self._fps)))

    def _on_timeline_moved(self, value: int):
        if not self._video_path:
            return
        dur = max(1, self._clip_end_ms - self._clip_start_ms)
        seek_ms = self._clip_start_ms + int(value * dur / 1000)
        frame_num = round(seek_ms * self._fps / 1000.0)
        cap = cv2.VideoCapture(self._video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        cap.release()
        if ret:
            self._raw_frame = frame
            self._pos_ms = seek_ms
            self._show_corrected()

    def _advance_frame(self):
        if self._cap is None or not self._cap.isOpened():
            self._stop_playback()
            return
        ret, frame = self._cap.read()
        if not ret:
            self._stop_playback()
            return
        ms = int(self._cap.get(cv2.CAP_PROP_POS_MSEC))
        if ms > self._clip_end_ms:
            self._stop_playback()
            return
        self._pos_ms = ms
        self._raw_frame = frame
        self._show_corrected()

    def _stop_playback(self):
        self._play_timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._btn_play.blockSignals(True)
        self._btn_play.setChecked(False)
        self._btn_play.setText("▶")
        self._btn_play.blockSignals(False)

    def _on_play_toggled(self, checked: bool):
        if checked:
            if not self._video_path:
                self._btn_play.setChecked(False)
                return
            self._cap = cv2.VideoCapture(self._video_path)
            frame_num = round(self._pos_ms * self._fps / 1000.0)
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            interval = max(8, int(1000.0 / (self._fps * self._playback_rate)))
            self._play_timer.start(interval)
            self._btn_play.setText("⏸")
        else:
            self._stop_playback()

    def _on_he_toggled(self, checked: bool):
        self._apply_he = checked
        self._show_corrected()

    def _on_dh_toggled(self, checked: bool):
        self._apply_dh = checked
        self._show_corrected()

    def _goto_clip_start(self):
        self._stop_playback()
        self._pos_ms = self._clip_start_ms
        self._read_and_show()

    def _jump(self, delta_ms: int):
        """Déplace la position de delta_ms en restant dans les bornes du clip."""
        new_pos = max(self._clip_start_ms,
                      min(self._pos_ms + delta_ms, self._clip_end_ms))
        self._pos_ms = new_pos
        if self._play_timer.isActive():
            # En lecture : seek le cap ouvert
            if self._cap is not None:
                frame_num = round(new_pos * self._fps / 1000.0)
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        else:
            self._read_and_show()

    def _step_frame(self, n: int):
        """Avance ou recule de n frames exactes (pause uniquement)."""
        if self._play_timer.isActive():
            return
        if self._fps <= 0:
            return
        frame_ms = max(1, int(1000.0 / self._fps))
        self._jump(n * frame_ms)

    def _set_speed(self, rate: float):
        self._playback_rate = rate
        for i, (_, r) in enumerate((("x1", 1.0), ("x2", 2.0), ("x5", 5.0))):
            self._speed_btns[i].setChecked(r == rate)
        if self._play_timer.isActive():
            interval = max(8, int(1000.0 / (self._fps * rate)))
            self._play_timer.setInterval(interval)

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()
        shift = bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
        ctrl  = bool(mods & QtCore.Qt.KeyboardModifier.ControlModifier)
        if key == QtCore.Qt.Key.Key_Space:
            self._btn_play.setChecked(not self._btn_play.isChecked())
        elif key == QtCore.Qt.Key.Key_Right:
            if shift:
                self._step_frame(+1)
            elif ctrl:
                self._step_frame(+10)
            else:
                self._jump(+5000)
        elif key == QtCore.Qt.Key.Key_Left:
            if shift:
                self._step_frame(-1)
            elif ctrl:
                self._step_frame(-10)
            else:
                self._jump(-5000)
        else:
            super().keyPressEvent(event)


# ── Widget cascade recouvrement ───────────────────────────────────────────────

class _RecouvrementCascade(QtWidgets.QWidget):
    """Saisie en cascade des types de recouvrement jusqu'à 100 %."""

    data_changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._loading = False
        self._language = 'fr'
        self.setStyleSheet("background:transparent;")
        self._build_ui()

    def _build_ui(self):
        self._vlay = QtWidgets.QVBoxLayout(self)
        self._vlay.setContentsMargins(8, 6, 8, 6)
        self._vlay.setSpacing(3)

        self._rows_widget = QtWidgets.QWidget()
        self._rows_widget.setStyleSheet("background:transparent;")
        self._rows_vlay = QtWidgets.QVBoxLayout(self._rows_widget)
        self._rows_vlay.setContentsMargins(0, 0, 0, 0)
        self._rows_vlay.setSpacing(3)
        self._vlay.addWidget(self._rows_widget)

        total_row = QtWidgets.QWidget()
        total_row.setStyleSheet("background:transparent;")
        tlay = QtWidgets.QHBoxLayout(total_row)
        tlay.setContentsMargins(0, 4, 0, 4)
        tlay.setSpacing(0)
        self._total_lbl = QtWidgets.QLabel("Total : 0 %")
        self._total_lbl.setObjectName("cascade_total")
        self._total_lbl.setStyleSheet(
            "color:#f0c040; font-weight:bold; font-size:11px; background:transparent;")
        tlay.addWidget(self._total_lbl)
        tlay.addStretch()
        self._vlay.addWidget(total_row)

        self._btn_add = QtWidgets.QPushButton("+ Ajouter un substrat")
        self._btn_add.setStyleSheet(
            "QPushButton { background:#162433; color:#7ec8e3;"
            " border:1px solid #2a4057; border-radius:3px;"
            " font-size:11px; padding:3px 10px; }"
            "QPushButton:hover { background:#1e3448; }"
        )
        self._btn_add.clicked.connect(lambda: self._add_row())
        self._vlay.addWidget(self._btn_add)

    def _add_row(self, key: str = "", pct: int = 0):
        row_w = QtWidgets.QWidget()
        row_w.setStyleSheet("background:transparent;")
        rlay = QtWidgets.QHBoxLayout(row_w)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(6)

        _css = _COMBO_SS_BASE.format(bg="#0d1e2e", bd="#1e3448")

        key_cb = QtWidgets.QComboBox()
        key_cb.setStyleSheet(_css)
        for k, label in _RECOUVREMENT_TYPES:
            key_cb.addItem(label, k)
        if key:
            idx = next((i for i, (k, _) in enumerate(_RECOUVREMENT_TYPES) if k == key), 0)
            key_cb.setCurrentIndex(idx)
        key_cb.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        key_cb.setMinimumWidth(160)
        rlay.addWidget(key_cb, 1)

        pct_cb = QtWidgets.QComboBox()
        pct_cb.setStyleSheet(_css)
        for v in range(0, 101, 5):
            pct_cb.addItem(f"{v} %", v)
        if pct > 0:
            idx_p = pct // 5
            pct_cb.setCurrentIndex(min(idx_p, pct_cb.count() - 1))
        pct_cb.setFixedWidth(70)
        rlay.addWidget(pct_cb)

        btn_del = QtWidgets.QPushButton("×")
        btn_del.setFixedSize(22, 22)
        btn_del.setStyleSheet(
            "QPushButton { background:#1a2030; color:#e05050;"
            " border:1px solid #2a1525; border-radius:3px; font-size:13px; }"
            "QPushButton:hover { background:#2a1525; }"
        )
        row_info = {"widget": row_w, "key_cb": key_cb, "pct_cb": pct_cb}
        btn_del.clicked.connect(lambda: self._remove_row(row_info))
        rlay.addWidget(btn_del)

        self._rows.append(row_info)
        self._rows_vlay.addWidget(row_w)

        key_cb.currentIndexChanged.connect(lambda _: self._on_row_changed())
        pct_cb.currentIndexChanged.connect(lambda _: self._on_row_changed())

        if not self._loading:
            self._on_row_changed()

    def _remove_row(self, row_info: dict):
        row_info["widget"].setParent(None)
        row_info["widget"].deleteLater()
        if row_info in self._rows:
            self._rows.remove(row_info)
        self._on_row_changed()

    def _on_row_changed(self):
        total = sum((ri["pct_cb"].currentData() or 0) for ri in self._rows)
        color = "#4ade80" if total == 100 else "#e05050" if total > 100 else "#f0c040"
        prefix = "Total:" if getattr(self, '_language', 'fr') == 'en' else "Total :"
        self._total_lbl.setText(f"{prefix} {total} %")
        self._total_lbl.setStyleSheet(
            f"color:{color}; font-weight:bold; font-size:11px; background:transparent;")
        self._btn_add.setVisible(total < 100)
        if not self._loading:
            self.data_changed.emit()

    def get_data(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for ri in self._rows:
            k = ri["key_cb"].currentData()
            v = ri["pct_cb"].currentData() or 0
            if k and v > 0:
                result[k] = result.get(k, 0) + v
        return result

    def set_language(self, language: str):
        self._language = language
        self._on_row_changed()
        self._btn_add.setText(
            "+ Add substrate" if language == 'en' else "+ Ajouter un substrat"
        )

    def set_data(self, data: dict[str, int]):
        self._loading = True
        for ri in list(self._rows):
            ri["widget"].setParent(None)
            ri["widget"].deleteLater()
        self._rows.clear()
        for k, v in data.items():
            if v > 0:
                self._add_row(k, v)
        if not self._rows:
            self._add_row()
        self._loading = False
        self._on_row_changed()


# ── Widget cascade présence (algues / invertébrés) ────────────────────────────

class _PresenceCascade(QtWidgets.QWidget):
    """Sélection d'items par présence : liste de lignes [Nom ×], bouton + Ajouter."""

    data_changed = QtCore.pyqtSignal()

    def __init__(self, items: list[tuple[str, str]], add_label: str = "+ Ajouter",
                 show_count: bool = False, parent=None):
        super().__init__(parent)
        self._items = items          # [(key, label), ...]
        self._add_label = add_label
        self._show_count = show_count
        self._rows: list[dict] = []  # [{"key": str, "widget": QWidget, "spin"?: QSpinBox}, ...]
        self._loading = False
        self._language = 'fr'

        _css = (
            "QComboBox { background:#0d1825; color:#c0d8e8; border:1px solid #2a4057;"
            " border-radius:3px; padding:2px 4px; font-size:11px; min-height:22px; }"
            "QComboBox::drop-down { border:none; }"
            "QComboBox QAbstractItemView { background:#0d1825; color:#c0d8e8;"
            " selection-background-color:#20415d; }"
        )

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        self._rows_vlay = QtWidgets.QVBoxLayout()
        self._rows_vlay.setSpacing(3)
        outer.addLayout(self._rows_vlay)

        self._btn_add = QtWidgets.QPushButton(add_label)
        self._btn_add.setStyleSheet(
            "QPushButton { background:#0a1e2d; color:#7ec8e3; border:1px solid #2778a2;"
            " border-radius:3px; font-size:10px; padding:3px 8px; }"
            "QPushButton:hover { background:#1a3a52; }"
        )
        self._btn_add.clicked.connect(self._add_row)
        outer.addWidget(self._btn_add, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        self._css = _css

    def _available_keys(self) -> list[tuple[str, str]]:
        used = {r["key"] for r in self._rows}
        return [(k, l) for k, l in self._items if k not in used]

    def _add_row(self, key: str = "", label_override: str = ""):
        avail = self._available_keys()
        if key:
            avail_keys = [k for k, _ in avail]
            if key not in avail_keys:
                # already present or unknown — skip silently
                return
        elif not avail:
            return

        row_w = QtWidgets.QWidget()
        row_w.setStyleSheet("background:#0b1421;")
        rlay = QtWidgets.QHBoxLayout(row_w)
        rlay.setContentsMargins(2, 1, 2, 1)
        rlay.setSpacing(4)

        cb = QtWidgets.QComboBox()
        cb.setStyleSheet(self._css)
        cb.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                         QtWidgets.QSizePolicy.Policy.Fixed)
        for k, lbl in self._items:
            cb.addItem(lbl, k)

        chosen_key = key if key else (avail[0][0] if avail else "")
        idx = cb.findData(chosen_key)
        if idx >= 0:
            cb.setCurrentIndex(idx)

        btn_del = QtWidgets.QPushButton("×")
        btn_del.setFixedSize(20, 20)
        btn_del.setStyleSheet(
            "QPushButton { background:#1a2030; color:#e05050;"
            " border:1px solid #2a1525; border-radius:3px; font-size:12px; }"
            "QPushButton:hover { background:#2a1525; }"
        )

        spin = None
        if self._show_count:
            spin = QtWidgets.QSpinBox()
            spin.setRange(1, 9999)
            spin.setValue(1)
            spin.setFixedWidth(58)
            spin.setStyleSheet(
                "QSpinBox { background:#0d1825; color:#c0d8e8; border:1px solid #2a4057;"
                " border-radius:3px; padding:1px 3px; font-size:11px; }"
            )

        row_info = {"key": chosen_key, "combo": cb, "spin": spin, "widget": row_w}
        self._rows.append(row_info)
        self._rows_vlay.addWidget(row_w)
        rlay.addWidget(cb, 1)
        if spin is not None:
            rlay.addWidget(spin)
        rlay.addWidget(btn_del)

        btn_del.clicked.connect(lambda: self._remove_row(row_info))
        cb.currentIndexChanged.connect(
            lambda _, ri=row_info: self._on_cb_changed(ri))
        if spin is not None:
            spin.valueChanged.connect(lambda _, ri=row_info: self._on_cb_changed(ri))

        self._update_add_btn()
        if not self._loading:
            self.data_changed.emit()

    def _remove_row(self, row_info: dict):
        row_info["widget"].setParent(None)
        row_info["widget"].deleteLater()
        if row_info in self._rows:
            self._rows.remove(row_info)
        self._update_add_btn()
        if not self._loading:
            self.data_changed.emit()

    def _on_cb_changed(self, row_info: dict):
        row_info["key"] = row_info["combo"].currentData() or ""
        if not self._loading:
            self.data_changed.emit()

    def _update_add_btn(self):
        self._btn_add.setVisible(bool(self._available_keys()))

    def get_data(self) -> dict[str, int]:
        """Retourne {key: count} (count=1 si pas de spinbox)."""
        result = {}
        for r in self._rows:
            k = r["combo"].currentData()
            if k:
                count = r["spin"].value() if r.get("spin") else 1
                result[k] = count
        return result

    def set_data(self, data: dict[str, int]):
        """Charge depuis {key: count}; n'ajoute que les clés avec valeur > 0."""
        self._loading = True
        for ri in list(self._rows):
            ri["widget"].setParent(None)
            ri["widget"].deleteLater()
        self._rows.clear()
        for k, v in data.items():
            if v:
                self._add_row(key=k)
                if self._show_count and self._rows:
                    spin = self._rows[-1].get("spin")
                    if spin is not None:
                        spin.setValue(int(v))
        self._update_add_btn()
        self._loading = False

    def set_language(self, language: str):
        self._language = language


# ── Contrôleur principal ──────────────────────────────────────────────────────

class AnalyseHabitatController(QtCore.QObject):
    """Contrôleur de la page Analyse Habitat."""

    def __init__(self, page: QtWidgets.QWidget):
        super().__init__()
        self._page = page
        self._language = 'fr'
        self._data: dict[str, dict[str, list]] = {}
        self._current_video: str | None = None
        self._video_model = None
        self._updating = False
        self._av_widgets: dict[str, QtWidgets.QLineEdit] = {}

        # Secteur courant
        self._current_sector_idx: int = 0
        self._sector_btn_list: list[QtWidgets.QFrame] = []
        self._sv_widgets: dict[str, QtWidgets.QWidget] = {}
        self._sv_recouvrement: _RecouvrementCascade | None = None
        self._sector_viewer: _SectorViewerWidget | None = None
        self._section_rec_herbier: _CollapsibleSection | None = None
        self._section_rec_algues: _CollapsibleSection | None = None
        self._section_presence_algues: _CollapsibleSection | None = None
        self._sv_presence_algues: _PresenceCascade | None = None
        self._sv_inverts: _PresenceCascade | None = None

        # Timestamps / thumbnails secteurs
        self._sector_mid_ts: list[float | None] = [None] * 6
        self._sector_bounds: list[tuple[int, int] | None] = [None] * 6
        self._sector_pixmaps: list[QtGui.QPixmap | None] = [None] * 6
        self._sector_photo_labels: list[QtWidgets.QLabel] = []
        self._sector_worker: _FrameWorker | None = None

        # Translation refs
        self._tr_label_refs: list[tuple[QtWidgets.QLabel, str]] = []
        self._section_widgets: list[tuple[_CollapsibleSection, str, str]] = []

        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._page.setStyleSheet("background-color:#0b1421;")
        root = QtWidgets.QHBoxLayout(self._page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background:#1e3448; width:2px; }")
        root.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([280, 900])

    def _build_left_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(360)
        panel.setStyleSheet("background:#111f2e;")
        vlay = QtWidgets.QVBoxLayout(panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        header = QtWidgets.QLabel("  Stations")
        header.setStyleSheet(
            "background:#0d1e2e; color:#7ec8e3; font-weight:bold;"
            " font-size:11px; font-family:'Segoe UI',sans-serif;"
            " padding:8px 12px; border-bottom:1px solid #1e3448;"
        )
        header.setFixedHeight(32)
        self._header_label = header
        vlay.addWidget(header)

        self._list = QtWidgets.QListWidget()
        self._list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._list.setStyleSheet(
            "QListWidget { background:#111f2e; color:#a0c8e0; border:none;"
            " font-family:'Segoe UI',sans-serif; font-size:14px; }"
            "QListWidget::item { padding:7px 12px; border-bottom:1px solid #1a2e40; }"
            "QListWidget::item:selected { background:#20415d; color:#ffffff; }"
            "QListWidget::item:hover { background:#162438; }"
        )
        self._list.currentRowChanged.connect(self._on_row_changed)

        # ── Splitter vertical : liste ↕ panneau Analyse vidéo ─────────────
        self._left_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self._left_splitter.setStyleSheet(
            "QSplitter::handle { background:#1e3448; height:5px; }"
            "QSplitter::handle:hover { background:#2778a2; }"
        )
        self._left_splitter.addWidget(self._list)
        self._left_splitter.addWidget(self._build_analysis_panel_compact())
        self._left_splitter.setSizes([200, 160])
        self._left_splitter.setCollapsible(0, False)
        self._left_splitter.setCollapsible(1, False)
        vlay.addWidget(self._left_splitter, 1)

        return panel

    def _build_analysis_panel_compact(self) -> QtWidgets.QWidget:
        """Panneau 'Analyse vidéo' compact placé en bas du panneau gauche."""
        outer = QtWidgets.QWidget()
        outer.setStyleSheet("background:#0d1825; border-top:1px solid #1e3448;")
        outer_lay = QtWidgets.QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # Bouton repliable
        self._av_toggle_btn = QtWidgets.QToolButton()
        self._av_toggle_btn.setText("  ▶  Analyse vidéo")
        self._av_toggle_btn.setCheckable(True)
        self._av_toggle_btn.setChecked(False)
        self._av_toggle_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._av_toggle_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed)
        self._av_toggle_btn.setStyleSheet(
            "QToolButton { background:#0d1825; color:#7ec8e3;"
            " font-weight:bold; font-size:11px;"
            " font-family:'Segoe UI',sans-serif;"
            " border:none; padding:7px 12px; text-align:left; }"
            "QToolButton:checked { color:#aee8ff; }")
        outer_lay.addWidget(self._av_toggle_btn)

        # Contenu (caché par défaut)
        self._av_panel_content = QtWidgets.QWidget()
        self._av_panel_content.setStyleSheet("background:#0d1825;")
        self._av_panel_content.setVisible(False)
        content_lay = QtWidgets.QVBoxLayout(self._av_panel_content)
        content_lay.setContentsMargins(10, 4, 10, 10)
        content_lay.setSpacing(5)

        _lbl_s = ("color:#7ec8e3; font-size:11px;"
                  " font-family:'Segoe UI',sans-serif; background:transparent;")
        _inp_s = ("QLineEdit { background:#162433; color:#F2BFB4;"
                  " border:1px solid #2a4057; border-radius:4px;"
                  " padding:3px 6px; font-size:11px; }"
                  "QLineEdit:focus { border-color:#2778a2; }")

        def _lbl(text):
            w = QtWidgets.QLabel(text)
            w.setStyleSheet(_lbl_s)
            self._tr_label_refs.append((w, text))
            return w

        def _inp(key, placeholder=""):
            w = QtWidgets.QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setStyleSheet(_inp_s)
            w.setMinimumHeight(24)
            print(f"[HABITAT DEBUG] création widget _inp pour {key!r}")
            def _on_edit_finished(k=key, wi=w):
                print(f"[HABITAT DEBUG] editingFinished → {k!r} = {wi.text()!r}")
                self._save_av_field(k, wi.text())
            def _on_text_edited(text, k=key):
                print(f"[HABITAT DEBUG] textEdited → {k!r} = {text!r}")
            w.editingFinished.connect(_on_edit_finished)
            w.textEdited.connect(_on_text_edited)
            self._av_widgets[key] = w
            return w

        rows = [
            ("Analyseur poisson",     "fish_annotator",         "Jean Dupont"),
            ("Analyseur habitat",     "habitat_annotator",      "Marie Martin"),
            ("Substrat",              "substrat",               "Sable, Roche…"),
            ("Visibilité (m)",        "estimated_visibility",   "ex : 5"),
        ]
        for label, key, ph in rows:
            content_lay.addWidget(_lbl(label))
            content_lay.addWidget(_inp(key, ph))

        # Distance min/max
        content_lay.addWidget(_lbl("Distance analysable (m)"))
        dist_row = QtWidgets.QWidget()
        dist_row.setStyleSheet("background:transparent;")
        dist_lay = QtWidgets.QHBoxLayout(dist_row)
        dist_lay.setContentsMargins(0, 0, 0, 0)
        dist_lay.setSpacing(6)
        dist_lay.addWidget(_lbl("min"))
        dist_lay.addWidget(_inp("distance_min", "0"))
        dist_lay.addWidget(_lbl("max"))
        dist_lay.addWidget(_inp("distance_max", "5"))
        dist_lay.addStretch()
        content_lay.addWidget(dist_row)

        # ── Bouton export CSV masque saisie ───────────────────────────────
        self._btn_export_csv = QtWidgets.QPushButton()
        self._btn_export_csv.setText(
            "Générer masque saisie (XLSX)" if self._language == 'fr' else "Generate entry template (XLSX)"
        )
        self._btn_export_csv.setStyleSheet(
            "QPushButton { background:#0d2a3e; color:#7ec8e3; border:1px solid #2778a2;"
            " border-radius:4px; font-size:10px; font-family:'Segoe UI',sans-serif;"
            " padding:5px 10px; margin:6px 0px; }"
            "QPushButton:hover { background:#1a3a52; }"
            "QPushButton:pressed { background:#0a1e2d; }"
        )
        self._btn_export_csv.clicked.connect(self._export_saisie_csv)
        self._btn_export_csv.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._btn_export_csv.customContextMenuRequested.connect(
            self._on_export_csv_context_menu)
        content_lay.addWidget(self._btn_export_csv)

        outer_lay.addWidget(self._av_panel_content)

        def _toggle(checked):
            self._av_panel_content.setVisible(checked)
            self._av_toggle_btn.setText(
                f"  {'▼' if checked else '▶'}  {self._tr('Analyse vidéo')}")

        self._av_toggle_btn.toggled.connect(_toggle)
        return outer

    def _build_right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("background:#0b1421;")
        hlay = QtWidgets.QHBoxLayout(panel)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Colonne gauche : viewer image (s'étend pour remplir l'espace) ──
        left_col = QtWidgets.QWidget()
        left_col.setStyleSheet("background:#0b1421;")
        left_vlay = QtWidgets.QVBoxLayout(left_col)
        left_vlay.setContentsMargins(0, 0, 0, 0)
        left_vlay.setSpacing(0)

        self._sector_viewer = _SectorViewerWidget()
        left_vlay.addWidget(self._sector_viewer, 1)  # stretch = 1 → remplit tout

        self._no_sel_label = QtWidgets.QLabel("Sélectionnez une station dans la liste")
        self._no_sel_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._no_sel_label.setStyleSheet(
            "color:#3a5568; font-size:14px; font-family:'Segoe UI',sans-serif;")
        left_vlay.addWidget(self._no_sel_label)

        self._lock_label = QtWidgets.QLabel(
            "⚠  Atterrissage + Décollage\n"
            "ou\n"
            "Début + Fin annotation\n\n"
            "requis dans la page Évènements\n"
            "avant de saisir l'analyse habitat."
        )
        self._lock_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._lock_label.setStyleSheet(
            "color:#f0a030; font-size:13px; font-family:'Segoe UI',sans-serif;"
            " line-height:160%;")
        self._lock_label.setWordWrap(True)
        self._lock_label.setVisible(False)
        left_vlay.addWidget(self._lock_label)

        hlay.addWidget(left_col, 1)  # stretch = 1 → prend toute la largeur disponible

        # ── Séparateur vertical ──
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        sep.setStyleSheet("color:#1a3a54;")
        hlay.addWidget(sep)

        # ── Colonne droite fixe : sélecteur S1-S6 + formulaire ──
        right_col = QtWidgets.QWidget()
        right_col.setFixedWidth(340)
        right_col.setStyleSheet("background:#0d1825;")
        right_vlay = QtWidgets.QVBoxLayout(right_col)
        right_vlay.setContentsMargins(0, 0, 0, 0)
        right_vlay.setSpacing(0)

        # Sélecteur de secteur (S1..S6 avec thumbnails) — tout en haut à droite
        self._sector_selector = self._build_sector_selector()
        right_vlay.addWidget(self._sector_selector)

        # Formulaire mono-secteur (scrollable) — en dessous du sélecteur
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background:#0d1825; }"
            "QScrollBar:vertical { background:#0d1e2e; width:8px; border-radius:4px; }"
            "QScrollBar::handle:vertical { background:#2778a2; border-radius:4px; }"
        )
        self._form_container = QtWidgets.QWidget()
        self._form_container.setStyleSheet("background:#0d1825;")
        form_lay = QtWidgets.QVBoxLayout(self._form_container)
        form_lay.setContentsMargins(8, 4, 8, 16)
        form_lay.setSpacing(0)

        self._sv_widgets.clear()
        self._build_single_sector_form(form_lay)
        form_lay.addStretch()

        scroll.setWidget(self._form_container)
        right_vlay.addWidget(scroll, 1)

        hlay.addWidget(right_col)

        self._sector_selector.setVisible(False)
        self._sector_viewer.setVisible(False)
        scroll.setVisible(False)
        self._scroll = scroll
        return panel

    def _build_sector_selector(self) -> QtWidgets.QWidget:
        """Barre de sélection de secteur (S1..S6 avec thumbnails)."""
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(_HEADER_H)
        bar.setStyleSheet("background:#0d1825; border-bottom:2px solid #1a3a54;")
        hlay = QtWidgets.QHBoxLayout(bar)
        hlay.setContentsMargins(8, 6, 8, 6)
        hlay.setSpacing(6)

        self._sector_btn_list = []
        self._sector_photo_labels = []
        self._sector_num_labels: list[QtWidgets.QLabel] = []

        for i in range(6):
            cell = QtWidgets.QFrame()
            cell.setFixedSize(_COL_W, _HEADER_H - 12)
            cell.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

            cell_lay = QtWidgets.QVBoxLayout(cell)
            cell_lay.setContentsMargins(2, 2, 2, 2)
            cell_lay.setSpacing(2)

            thumb = QtWidgets.QLabel("⏳")
            thumb.setFixedSize(_COL_W - 4, _THUMB_H - 4)
            thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet(
                "color:#405060; font-size:16px; background:#0b1520;"
                " border-radius:3px; border:none;")
            cell_lay.addWidget(thumb)
            self._sector_photo_labels.append(thumb)

            lbl = QtWidgets.QLabel(f"S{i + 1}")
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "color:#2778a2; font-weight:bold; font-size:11px;"
                " font-family:'Segoe UI',sans-serif;"
                " background:transparent; border:none;")
            cell_lay.addWidget(lbl)
            self._sector_num_labels.append(lbl)

            cell.mousePressEvent = lambda e, idx=i: self._on_sector_clicked(idx)
            self._sector_btn_list.append(cell)
            hlay.addWidget(cell)

        hlay.addStretch()
        self._highlight_sector(0)
        return bar

    def _highlight_sector(self, idx: int):
        _sel = (
            "QFrame { background:#163050; border-radius:4px;"
            " border:2px solid #2778a2; }"
        )
        _unsel = (
            "QFrame { background:#111f2e; border-radius:4px;"
            " border:1px solid #1e3448; }"
            "QFrame:hover { border-color:#2778a2; background:#162030; }"
        )
        for i, cell in enumerate(self._sector_btn_list):
            cell.setStyleSheet(_sel if i == idx else _unsel)

    def _build_single_sector_form(self, parent_lay: QtWidgets.QVBoxLayout):
        """Construit le formulaire de saisie pour un secteur à la fois."""
        row_bg_even = "#0d1825"
        row_bg_odd  = "#0b1421"

        for section_name, note, fields in _SCHEMA:
            section = _CollapsibleSection(section_name, note)
            self._section_widgets.append((section, section_name, note))
            if section_name == "Recouvrement Herbier":
                self._section_rec_herbier = section
            elif section_name == "Recouvrement Algues":
                self._section_rec_algues = section
            elif section_name == "Présence Algues":
                self._section_presence_algues = section

            if section_name == "Recouvrement visible":
                inner = QtWidgets.QVBoxLayout()
                inner.setContentsMargins(4, 4, 4, 4)
                inner.setSpacing(4)
                self._sv_recouvrement = _RecouvrementCascade()
                self._sv_recouvrement.data_changed.connect(
                    self._sv_on_recouvrement_changed)
                inner.addWidget(self._sv_recouvrement)
                section.set_layout(inner)

            elif section_name == "Présence Algues":
                inner = QtWidgets.QVBoxLayout()
                inner.setContentsMargins(4, 4, 4, 4)
                inner.setSpacing(4)
                items = [(fkey, flabel) for fkey, flabel, _ in fields]
                add_lbl = _EN.get("+ Ajouter une algue", "+ Ajouter une algue") \
                    if self._language == 'en' else "+ Ajouter une algue"
                self._sv_presence_algues = _PresenceCascade(
                    items, add_label="+ Ajouter une algue", show_count=False)
                self._sv_presence_algues.data_changed.connect(
                    self._sv_on_presence_algues_changed)
                inner.addWidget(self._sv_presence_algues)
                section.set_layout(inner)

            elif section_name == "Invertébrés remarquables":
                inner = QtWidgets.QVBoxLayout()
                inner.setContentsMargins(4, 4, 4, 4)
                inner.setSpacing(4)
                items = [(fkey, flabel) for fkey, flabel, _ in fields]
                self._sv_inverts = _PresenceCascade(
                    items, add_label="+ Ajouter un invertébré", show_count=True)
                self._sv_inverts.data_changed.connect(
                    self._sv_on_inverts_changed)
                inner.addWidget(self._sv_inverts)
                section.set_layout(inner)

            else:
                grid = QtWidgets.QGridLayout()
                grid.setContentsMargins(4, 4, 4, 4)
                grid.setHorizontalSpacing(10)
                grid.setVerticalSpacing(2)
                grid.setColumnMinimumWidth(0, _LABEL_W)
                grid.setColumnMinimumWidth(1, _COL_W)
                grid.setColumnStretch(2, 1)

                for row_idx, (fkey, flabel, ftype) in enumerate(fields):
                    bg = row_bg_even if row_idx % 2 == 0 else row_bg_odd

                    lbl = QtWidgets.QLabel(flabel)
                    lbl.setFixedWidth(_LABEL_W)
                    if ftype == "total":
                        lbl.setStyleSheet(
                            f"color:#f0c040; font-size:11px; font-weight:bold;"
                            f" font-family:'Segoe UI',sans-serif;"
                            f" background:#12253a; padding:3px 4px; border-radius:2px;")
                    else:
                        lbl.setStyleSheet(
                            f"color:#a0b8c8; font-size:11px;"
                            f" font-family:'Segoe UI',sans-serif;"
                            f" background:{bg}; padding:3px 4px; border-radius:2px;")
                    self._tr_label_refs.append((lbl, flabel))
                    grid.addWidget(lbl, row_idx, 0)

                    if ftype == "total":
                        w = _TotalLabel()
                    elif ftype == "presence":
                        w = _PresenceCheckBox(bg_empty=bg)
                        w.stateChanged.connect(
                            lambda v, k=fkey: self._sv_on_changed(k, int(bool(v))))
                    else:
                        w = _SectorComboBox(ftype, bg_empty=bg)
                        w.currentIndexChanged.connect(
                            lambda _, k=fkey, wb=w: self._sv_on_changed(k, wb.get_value()))

                    self._sv_widgets[fkey] = w
                    grid.addWidget(w, row_idx, 1)

                section.set_layout(grid)

            parent_lay.addWidget(section)

    # ── Gestion secteur courant ───────────────────────────────────────────────

    def _initial_ms_for_sector(self, idx: int) -> int | None:
        """Retourne le ms de la frame initiale : atterrissage pour S1, milieu du clip sinon."""
        bounds = self._sector_bounds[idx] if idx < len(self._sector_bounds) else None
        if bounds is None:
            return None
        clip_start = bounds[0]
        # La logique atterrissage ne s'applique qu'à S1 (idx==0) :
        # pour S2-S6, landing_ms < clip_start → on tomberait au début du clip (rotation)
        if idx == 0 and self._landing_ms is not None:
            lms = self._landing_ms
            if clip_start <= lms <= bounds[1]:
                return lms
            if lms < clip_start:
                return clip_start
        mid_ts = self._sector_mid_ts[idx] if idx < len(self._sector_mid_ts) else None
        return int(mid_ts * 1000) if mid_ts is not None else None

    def _switch_sector(self, idx: int):
        """Change le secteur affiché dans le viewer et recharge le formulaire."""
        self._current_sector_idx = idx
        self._highlight_sector(idx)
        if self._current_video and self._sector_viewer is not None:
            bounds = self._sector_bounds[idx] if idx < len(self._sector_bounds) else None
            if bounds:
                self._sector_viewer.load_sector(
                    self._current_video, bounds[0], bounds[1],
                    mid_ms=self._initial_ms_for_sector(idx),
                )
            else:
                pixmap = self._sector_pixmaps[idx] if idx < len(self._sector_pixmaps) else None
                if pixmap:
                    self._sector_viewer._canvas.set_pixmap(pixmap)
                else:
                    self._sector_viewer.clear()
        self._sv_reload_form()

    def _sv_reload_form(self):
        """Recharge les widgets du formulaire mono-secteur depuis _data."""
        self._updating = True
        try:
            if not self._current_video:
                return
            d = self._data.get(self._current_video, {})
            s = self._current_sector_idx

            for fkey, w in self._sv_widgets.items():
                values = d.get(fkey, [0] * 6)
                v = values[s] if s < len(values) else 0
                if isinstance(w, _SectorComboBox):
                    w.set_value(v or 0)
                elif isinstance(w, _PresenceCheckBox):
                    w.setChecked(bool(v))

            if self._sv_recouvrement is not None:
                rec_data: dict[str, int] = {}
                for k, _ in _RECOUVREMENT_TYPES:
                    vals = d.get(k, [0] * 6)
                    v = vals[s] if s < len(vals) else 0
                    if v:
                        rec_data[k] = v
                self._sv_recouvrement.set_data(rec_data)

            if self._sv_presence_algues is not None:
                algues_data: dict[str, int] = {}
                for sname, _, fields in _SCHEMA:
                    if sname != "Présence Algues":
                        continue
                    for fkey, _, _ in fields:
                        v = (d.get(fkey, [0] * 6))[s] if s < len(d.get(fkey, [0] * 6)) else 0
                        if v:
                            algues_data[fkey] = v
                self._sv_presence_algues.set_data(algues_data)

            if self._sv_inverts is not None:
                inverts_data: dict[str, int] = {}
                for sname, _, fields in _SCHEMA:
                    if sname != "Invertébrés remarquables":
                        continue
                    for fkey, _, _ in fields:
                        vals = d.get(fkey, [0] * 6)
                        v = vals[s] if s < len(vals) else 0
                        if v:
                            inverts_data[fkey] = v
                self._sv_inverts.set_data(inverts_data)
        finally:
            self._updating = False
        self._sv_refresh_totals()
        self._sv_update_badges()
        self._sv_update_conditional_sections()

    def _sv_on_changed(self, field_key: str, value):
        if self._updating or not self._current_video:
            return
        d = self._data.setdefault(self._current_video, {})
        row = d.setdefault(field_key, [0] * 6)
        row[self._current_sector_idx] = value
        self._sv_refresh_totals()
        self._sv_update_badges()
        self._sv_update_conditional_sections()
        self._persist_habitat(self._current_video)

    def _sv_on_recouvrement_changed(self):
        if self._updating or not self._current_video or self._sv_recouvrement is None:
            return
        cascade_data = self._sv_recouvrement.get_data()
        d = self._data.setdefault(self._current_video, {})
        for k, _ in _RECOUVREMENT_TYPES:
            row = d.setdefault(k, [0] * 6)
            row[self._current_sector_idx] = cascade_data.get(k, 0)
        self._sv_refresh_totals()
        self._sv_update_badges()
        self._sv_update_conditional_sections()
        self._persist_habitat(self._current_video)

    def _sv_on_presence_algues_changed(self):
        if self._updating or not self._current_video or self._sv_presence_algues is None:
            return
        cascade_data = self._sv_presence_algues.get_data()
        d = self._data.setdefault(self._current_video, {})
        s = self._current_sector_idx
        for section_name, _, fields in _SCHEMA:
            if section_name != "Présence Algues":
                continue
            for fkey, _, _ in fields:
                row = d.setdefault(fkey, [0] * 6)
                row[s] = cascade_data.get(fkey, 0)
        self._sv_update_badges()
        self._persist_habitat(self._current_video)

    def _sv_on_inverts_changed(self):
        if self._updating or not self._current_video or self._sv_inverts is None:
            return
        cascade_data = self._sv_inverts.get_data()
        d = self._data.setdefault(self._current_video, {})
        s = self._current_sector_idx
        for section_name, _, fields in _SCHEMA:
            if section_name != "Invertébrés remarquables":
                continue
            for fkey, _, _ in fields:
                row = d.setdefault(fkey, [0] * 6)
                row[s] = cascade_data.get(fkey, 0)
        self._sv_update_badges()
        self._persist_habitat(self._current_video)

    # ── Persistance habitat.json ──────────────────────────────────────────────

    @staticmethod
    def _habitat_json_path(video_path: str) -> str:
        stem = os.path.splitext(os.path.basename(video_path))[0]
        folder = os.path.dirname(os.path.normpath(video_path))
        return os.path.join(folder, f"{stem}_habitat.json")

    def _load_habitat_json(self, video_path: str):
        """Charge les données habitat depuis {stem}_habitat.json (nouveau format) vers _data plat."""
        path = self._habitat_json_path(video_path)
        if not os.path.isfile(path):
            print(f"[HABITAT] Pas de fichier existant : {path}")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as e:
            print(f"[HABITAT] Erreur chargement {path}: {e}")
            return

        # Compatibilité ancien format plat (migration transparente)
        if "sectors" not in doc:
            self._data[video_path] = doc
            print(f"[HABITAT] Chargé (ancien format, {len(doc)} clés) ← {path}")
            return

        flat: dict[str, list] = {}
        _AUTO = set(_TOTAL_SOURCES.keys())

        for sector_obj in doc.get("sectors", []):
            s = sector_obj.get("index", 1) - 1  # 0-based
            if not (0 <= s < 6):
                continue

            for sec_name, enc_type, json_key in (
                (n, t, k) for n, (t, k) in _JSON_SECTION.items()
            ):
                # Récupère les clés de champs pour cette section depuis _SCHEMA
                fields_for_sec = next(
                    (flds for sn, _, flds in _SCHEMA if sn == sec_name), []
                )

                if enc_type == "flat":
                    for fkey, _, _ in fields_for_sec:
                        if fkey in _AUTO:
                            continue
                        v = sector_obj.get(fkey, 0)
                        if v:
                            flat.setdefault(fkey, [0] * 6)[s] = v

                elif enc_type == "dict":
                    sub = sector_obj.get(json_key, {})
                    for fkey, _, _ in fields_for_sec:
                        if fkey in _AUTO:
                            continue
                        v = sub.get(fkey, 0)
                        if v:
                            flat.setdefault(fkey, [0] * 6)[s] = v

                elif enc_type == "list":
                    present = set(sector_obj.get(json_key, []))
                    for fkey, _, _ in fields_for_sec:
                        if fkey in present:
                            flat.setdefault(fkey, [0] * 6)[s] = 1

                elif enc_type == "dict_count":
                    sub = sector_obj.get(json_key, {})
                    for fkey, _, _ in fields_for_sec:
                        v = sub.get(fkey, 0)
                        if v:
                            flat.setdefault(fkey, [0] * 6)[s] = v

        self._data[video_path] = flat
        n_sectors = len(doc.get("sectors", []))
        print(f"[HABITAT] Chargé ({n_sectors} secteurs, {len(flat)} champs) ← {path}")

    def _persist_habitat(self, video_path: str):
        """Écrit les données habitat dans {stem}_habitat.json (nouveau format structuré)."""
        path = self._habitat_json_path(video_path)
        is_new = not os.path.isfile(path)
        d = self._data.get(video_path, {})
        _AUTO = set(_TOTAL_SOURCES.keys())

        # ── meta : codestation + champs Analyse vidéo depuis _temp.json ──────
        meta: dict = {"codestation": _get_codestation(video_path) or ""}
        try:
            stem   = os.path.splitext(os.path.basename(video_path))[0]
            folder = os.path.dirname(os.path.normpath(video_path))
            tmp_path = os.path.join(folder, f"{stem}_temp.json")
            with open(tmp_path, 'r', encoding='utf-8') as f:
                tmp = json.load(f)
            vob = tmp.get("video_observation", {})
            for key in ("fish_annotator", "habitat_annotator", "substrat",
                        "estimated_visibility", "distance_min", "distance_max"):
                entry = vob.get(key)
                val = entry.get("value", "") if isinstance(entry, dict) else (entry or "")
                if val not in (None, ""):
                    meta[key] = val
        except Exception:
            pass

        # ── sectors ───────────────────────────────────────────────────────────
        sectors = []
        for s in range(6):
            sec: dict = {"index": s + 1}

            for sec_name, (enc_type, json_key) in _JSON_SECTION.items():
                fields_for_sec = next(
                    (flds for sn, _, flds in _SCHEMA if sn == sec_name), []
                )

                if enc_type == "flat":
                    for fkey, _, _ in fields_for_sec:
                        if fkey in _AUTO:
                            continue
                        vals = d.get(fkey, [0] * 6)
                        v = vals[s] if s < len(vals) else 0
                        if v:
                            sec[fkey] = v

                elif enc_type in ("dict", "dict_count"):
                    sub: dict = {}
                    for fkey, _, _ in fields_for_sec:
                        if fkey in _AUTO:
                            continue
                        vals = d.get(fkey, [0] * 6)
                        v = vals[s] if s < len(vals) else 0
                        if v:
                            sub[fkey] = v
                    if sub:
                        sec[json_key] = sub

                elif enc_type == "list":
                    present = [
                        fkey for fkey, _, _ in fields_for_sec
                        if (d.get(fkey, [0] * 6)[s] if s < len(d.get(fkey, [0] * 6)) else 0)
                    ]
                    if present:
                        sec[json_key] = present

            sectors.append(sec)

        doc = {"meta": meta, "sectors": sectors}
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            if is_new:
                print(f"[HABITAT] Fichier créé → {path}")
            else:
                n_filled = sum(1 for sec in sectors if len(sec) > 1)
                print(f"[HABITAT] Sauvegardé ({n_filled} secteurs renseignés) → {path}")
        except Exception as e:
            print(f"[HABITAT] Erreur sauvegarde {path}: {e}")

    def ensure_habitat_jsons(self):
        """Crée (si absent) un habitat.json pour chaque vidéo exploitable (oui/habitat)."""
        if not self._video_model:
            return
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            vpath_str = str(vpath)
            expl = _get_exploitability_value(vpath_str)
            if expl not in {"oui", "habitat"}:
                continue
            path = self._habitat_json_path(vpath_str)
            if not os.path.isfile(path):
                self._persist_habitat(vpath_str)

    def _sv_update_conditional_sections(self):
        """Verrouille Recouvrement Herbier / Algues si le substrat correspondant est absent."""
        if not self._current_video:
            return
        d = self._data.get(self._current_video, {})
        s = self._current_sector_idx

        def _val(key):
            v = d.get(key, [0] * 6)
            return v[s] if s < len(v) else 0

        has_herbier = bool(_val("herbier_snv") or _val("herbier_sv"))
        has_algues  = bool(_val("algues_snv")  or _val("algues_sv"))

        if self._section_rec_herbier is not None:
            self._section_rec_herbier.set_locked(not has_herbier)
        if self._section_rec_algues is not None:
            self._section_rec_algues.set_locked(not has_algues)
        if self._section_presence_algues is not None:
            self._section_presence_algues.set_locked(not has_algues)

    def _sv_sector_is_complete(self, sector_idx: int) -> bool:
        """Retourne True si topo, complexité et recouvrement (=100%) sont renseignés."""
        if not self._current_video:
            return False
        d = self._data.get(self._current_video, {})
        s = sector_idx
        topo = (d.get("topographie") or [0] * 6)[s]
        compl = (d.get("complexite") or [0] * 6)[s]
        if not topo or not compl:
            return False
        total_rec = sum(
            (d.get(k) or [0] * 6)[s]
            for k, _ in _RECOUVREMENT_TYPES
        )
        return total_rec == 100

    def _sv_update_badges(self):
        """Met à jour la couleur des labels S1-S6 selon la complétion de chaque secteur."""
        for i, lbl in enumerate(self._sector_num_labels):
            if self._sv_sector_is_complete(i):
                lbl.setStyleSheet(
                    "color:#22c55e; font-weight:bold; font-size:11px;"
                    " font-family:'Segoe UI',sans-serif;"
                    " background:transparent; border:none;")
            else:
                lbl.setStyleSheet(
                    "color:#2778a2; font-weight:bold; font-size:11px;"
                    " font-family:'Segoe UI',sans-serif;"
                    " background:transparent; border:none;")

    def _sv_refresh_totals(self):
        if not self._current_video:
            return
        d = self._data.get(self._current_video, {})
        s = self._current_sector_idx
        for total_key, sources in _TOTAL_SOURCES.items():
            w = self._sv_widgets.get(total_key)
            if not isinstance(w, _TotalLabel):
                continue
            total = sum((d.get(src, [0] * 6)[s] or 0) for src in sources)
            color = "#e05050" if total > 100 else "#f0c040"
            w.setText(str(total))
            w.setStyleSheet(
                f"color:{color}; font-weight:bold; font-size:11px;"
                " background:#12253a; border:1px solid #2a3e50;"
                " border-radius:3px; padding:2px;"
            )

    def _build_analysis_panel(self) -> QtWidgets.QWidget:
        """Panneau 'Analyse vidéo' fixe — valeurs partagées entre toutes les vidéos."""
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("background:#0d1825; border-bottom:2px solid #1a3a54;")

        vlay = QtWidgets.QVBoxLayout(panel)
        vlay.setContentsMargins(12, 10, 12, 10)
        vlay.setSpacing(8)

        title = QtWidgets.QLabel("Analyse vidéo")
        title.setStyleSheet(
            "color:#7ec8e3; font-size:13px; font-weight:bold;"
            " font-family:'Segoe UI',sans-serif; background:transparent;")
        vlay.addWidget(title)

        grid = QtWidgets.QWidget()
        grid.setStyleSheet("background:transparent;")
        gl = QtWidgets.QGridLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(6)
        gl.setColumnStretch(1, 1)
        gl.setColumnStretch(3, 1)

        _lbl_s = ("color:#7ec8e3; font-size:12px;"
                  " font-family:'Segoe UI',sans-serif; background:transparent;")
        _inp_s = ("QLineEdit { background:#162433; color:#F2BFB4;"
                  " border:1px solid #2a4057; border-radius:4px;"
                  " padding:4px 8px; font-size:12px; }"
                  "QLineEdit:focus { border-color:#2778a2; }")

        def _lbl(text):
            w = QtWidgets.QLabel(text)
            w.setStyleSheet(_lbl_s)
            return w

        def _inp(key, placeholder=""):
            w = QtWidgets.QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setStyleSheet(_inp_s)
            w.setMinimumHeight(26)
            w.editingFinished.connect(lambda k=key, wi=w: self._save_av_field(k, wi.text()))
            self._av_widgets[key] = w
            return w

        # Ligne 0 : analyseur poisson | analyseur habitat
        gl.addWidget(_lbl("Analyseur poisson"),  0, 0)
        gl.addWidget(_inp("fish_annotator",   "ex : Jean Dupont"),   0, 1)
        gl.addWidget(_lbl("Analyseur habitat"), 0, 2)
        gl.addWidget(_inp("habitat_annotator", "ex : Marie Martin"), 0, 3)

        # Ligne 1 : substrat | visibilité
        gl.addWidget(_lbl("Substrat"),      1, 0)
        gl.addWidget(_inp("substrat",       "ex : Sable, Roche…"), 1, 1)
        gl.addWidget(_lbl("Visibilité (m)"), 1, 2)
        gl.addWidget(_inp("estimated_visibility", "ex : 5"),        1, 3)

        # Ligne 2 : distance analysable min/max
        gl.addWidget(_lbl("Distance analysable (m)"), 2, 0)
        dist_w = QtWidgets.QWidget()
        dist_w.setStyleSheet("background:transparent;")
        dist_row = QtWidgets.QHBoxLayout(dist_w)
        dist_row.setContentsMargins(0, 0, 0, 0)
        dist_row.setSpacing(6)
        dist_row.addWidget(_lbl("min"))
        dist_row.addWidget(_inp("distance_min", "0"))
        dist_row.addWidget(_lbl("max"))
        dist_row.addWidget(_inp("distance_max", "5"))
        dist_row.addStretch()
        gl.addWidget(dist_w, 2, 1, 1, 3)

        vlay.addWidget(grid)
        return panel

    def _save_av_field(self, field_key: str, value: str):
        """Sauvegarde field_key dans le JSON de TOUTES les vidéos du modèle."""
        print(f"[HABITAT] _save_av_field appelé : {field_key} = {value!r}")
        if not self._video_model:
            print(f"[HABITAT] _save_av_field : pas de video_model, abandon")
            return
        print(f"[HABITAT] _save_av_field : {self._video_model.rowCount()} vidéo(s) dans le modèle")
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            json_path = _find_json(str(vpath))
            if not json_path or not os.path.isfile(json_path):
                print(f"[HABITAT] _save_av_field : JSON introuvable pour {os.path.basename(str(vpath))!r} (json_path={json_path!r})")
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                vob = data.setdefault("video_observation", {})
                entry = vob.get(field_key)
                if isinstance(entry, dict):
                    entry["value"] = value or None
                else:
                    vob[field_key] = {"value": value or None}
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                print(f"[HABITAT] Analyse vidéo : {field_key} = {value!r} → {os.path.basename(json_path)}")
            except Exception as e:
                print(f"[ANALYSE-HABITAT] _save_av_field {field_key}: {e}")

    def _load_av_fields(self, video_path: str | None = None):
        """Lit les champs Analyse vidéo depuis le JSON de la vidéo courante (ou première dispo)."""
        if not self._av_widgets:
            return
        vpath = video_path or self._current_video
        if not vpath:
            return
        json_path = _find_json(vpath)
        if not json_path or not os.path.isfile(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return
        vob = data.get("video_observation", {})
        for key, widget in self._av_widgets.items():
            entry = vob.get(key, {})
            val = entry.get("value", "") if isinstance(entry, dict) else (entry or "")
            widget.blockSignals(True)
            widget.setText(str(val) if val is not None else "")
            widget.blockSignals(False)

    # ── Rotation moteur → timestamps secteurs ─────────────────────────────────

    @staticmethod
    def _tc_to_ms(tc: str) -> int | None:
        """Convertit 'MM:SS' ou 'HH:MM:SS' en millisecondes, None si invalide."""
        try:
            parts = [int(p) for p in tc.strip().split(':')]
            if len(parts) == 2:
                return (parts[0] * 60 + parts[1]) * 1000
            if len(parts) == 3:
                return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000
        except (ValueError, AttributeError):
            pass
        return None

    def _load_rotation_timestamps(self, video_path: str):
        """Extrait les 6 timestamps de milieu de secteur depuis le JSON de la vidéo."""
        self._sector_mid_ts = [None] * 6
        self._sector_bounds = [None] * 6
        self._sector_pixmaps = [None] * 6
        self._landing_ms: int | None = None  # timecode atterrissage pour cadrage initial

        # Réinitialise les thumbnails
        for lbl in self._sector_photo_labels:
            lbl.setText("⏳")
            lbl.setPixmap(QtGui.QPixmap())
            lbl.setStyleSheet(
                "color:#405060; font-size:16px; background:#0b1520;"
                " border-radius:3px; border:none;")

        try:
            json_path = _find_json(video_path)
            if not json_path or not os.path.isfile(json_path):
                return
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Timecode atterrissage → frame initiale de S1
            vobs = data.get("video_observation", {})
            landing_tc = str((vobs.get("timecode_landing") or {}).get("value") or "").strip()
            if landing_tc:
                self._landing_ms = self._tc_to_ms(landing_tc)
            raw = data.get("video_observation", {}).get("events_motor") or []

            events = []
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                desc = entry.get("description_fr", "")
                if desc.strip().lower() in _NON_ROTATION:
                    continue
                ms = int(entry.get("start_ms") or 0)
                fn = int(entry.get("frame_number") or 0)
                if ms == 0 and fn == 0:
                    continue
                if ms == 0 and fn:
                    ms = int((fn / 25.0) * 1000)
                m = _re.search(r'\((\d+)°\)', desc)
                angle = int(m.group(1)) if m else 0
                events.append({"ts": ms / 1000.0, "angle": angle})

            if not events:
                return

            events.sort(key=lambda e: e["ts"])
            # On ne prend que le premier groupe de 6
            group = events[:6]
            ts_list = [e["ts"] for e in group]

            if len(ts_list) >= 2:
                avg_interval = (ts_list[-1] - ts_list[0]) / (len(ts_list) - 1)
            else:
                avg_interval = 6.0

            for idx, ts in enumerate(ts_list):
                if idx + 1 < len(ts_list):
                    end_ts = ts_list[idx + 1]
                    mid = (ts + end_ts) / 2.0
                else:
                    end_ts = ts + avg_interval
                    mid = ts + avg_interval / 2.0
                self._sector_mid_ts[idx] = mid
                self._sector_bounds[idx] = (int(ts * 1000), int(end_ts * 1000))

        except Exception as e:
            print(f"[ANALYSE-HABITAT] _load_rotation_timestamps: {e}")

    def _start_frame_extraction(self, video_path: str):
        """Lance l'extraction des frames de milieu de secteur en arrière-plan."""
        if self._sector_worker and self._sector_worker.isRunning():
            self._sector_worker.requestInterruption()
            self._sector_worker.wait(300)

        tasks = [
            (i, video_path, ts)
            for i, ts in enumerate(self._sector_mid_ts)
            if ts is not None
        ]
        if not tasks:
            return

        self._sector_worker = _FrameWorker(tasks)
        self._sector_worker.frame_ready.connect(self._on_frame_ready)
        self._sector_worker.start()

    def _on_frame_ready(self, sector_idx: int, frame_data):
        """Appelé quand une frame est extraite — met à jour le thumbnail et le viewer."""
        if frame_data is None or sector_idx >= len(self._sector_photo_labels):
            return
        h_f, w_f, ch = frame_data.shape
        q_img = QtGui.QImage(
            frame_data.tobytes(), w_f, h_f, ch * w_f,
            QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(q_img)
        self._sector_pixmaps[sector_idx] = pixmap

        lbl = self._sector_photo_labels[sector_idx]
        thumb_w = lbl.width() or (_COL_W - 4)
        thumb_h = lbl.height() or (_THUMB_H - 4)
        scaled = pixmap.scaled(
            thumb_w, thumb_h,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        lbl.setText("")
        lbl.setPixmap(scaled)
        lbl.setStyleSheet("background:#0b1520; border-radius:3px; border:none;")

        # Si c'est le secteur courant et pas encore chargé via cv2, afficher la frame
        if (sector_idx == self._current_sector_idx
                and self._sector_viewer is not None
                and self._sector_viewer._video_path is None):
            self._sector_viewer.show_frame_rgb(frame_data)

    def _on_sector_clicked(self, sector_idx: int):
        """Change le secteur courant (viewer + formulaire)."""
        self._switch_sector(sector_idx)

    # ── Données formulaire ────────────────────────────────────────────────────

    def _load_station(self, video_path: str):
        pass  # les données sont en mémoire dans _data ; _sv_reload_form fait le travail

    def _clear_form(self):
        self._updating = True
        for w in self._sv_widgets.values():
            if isinstance(w, _SectorComboBox):
                w.setCurrentIndex(0)
            elif isinstance(w, _PresenceCheckBox):
                w.setChecked(False)
            elif isinstance(w, _TotalLabel):
                w.setText("—")
        if self._sv_recouvrement is not None:
            self._sv_recouvrement.set_data({})
        self._updating = False

    # ── Navigation ────────────────────────────────────────────────────────────

    @staticmethod
    def _video_has_bounds(video_path: str) -> bool:
        """Retourne True si le JSON de la vidéo contient atterrissage+décollage OU début+fin annotation."""
        try:
            json_path = _find_json(video_path)
            if not json_path or not os.path.isfile(json_path):
                return False
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            vobs = data.get("video_observation", {})

            # Option 1 : timecode_landing + timecode_takeoff
            landing = str((vobs.get("timecode_landing") or {}).get("value") or "").strip()
            takeoff = str((vobs.get("timecode_takeoff") or {}).get("value") or "").strip()
            if landing and takeoff:
                return True

            # Option 2 : début annotation + fin annotation dans events_motor
            _ANNOT_START_KW = ("début annotation", "debut annotation",
                               "annotation start", "debut_analyse", "analysis_start")
            _ANNOT_END_KW   = ("fin annotation", "annotation end",
                               "fin_analyse", "analysis_end")
            has_start = has_end = False
            for item in (vobs.get("events_motor") or []):
                if not isinstance(item, dict):
                    continue
                val = str(item.get("description_fr") or item.get("value", "")).strip().lower()
                if not has_start and any(kw in val for kw in _ANNOT_START_KW):
                    has_start = True
                if not has_end and any(kw in val for kw in _ANNOT_END_KW):
                    has_end = True
                if has_start and has_end:
                    return True
        except Exception:
            pass
        return False

    def _on_row_changed(self, row: int):
        if row < 0:
            self._current_video = None
            self._sector_selector.setVisible(False)
            self._sector_viewer.setVisible(False)
            self._scroll.setVisible(False)
            self._no_sel_label.setVisible(True)
            self._lock_label.setVisible(False)
            return
        list_item = self._list.item(row)
        vpath = list_item.data(QtCore.Qt.ItemDataRole.UserRole) if list_item else None
        if not vpath:
            return
        self._current_video = str(vpath)
        self._no_sel_label.setVisible(False)

        # Vérification prérequis : atterrissage/décollage ou début/fin annotation
        if not self._video_has_bounds(self._current_video):
            self._sector_selector.setVisible(False)
            self._sector_viewer.setVisible(False)
            self._scroll.setVisible(False)
            self._lock_label.setVisible(True)
            return

        self._lock_label.setVisible(False)
        self._sector_selector.setVisible(True)
        self._sector_viewer.setVisible(True)
        self._scroll.setVisible(True)
        self._load_av_fields(self._current_video)
        self._load_habitat_json(self._current_video)
        self._load_rotation_timestamps(self._current_video)
        self._start_frame_extraction(self._current_video)
        # Afficher secteur 0 par défaut
        self._current_sector_idx = 0
        self._highlight_sector(0)
        self._sv_reload_form()
        bounds = self._sector_bounds[0] if self._sector_bounds else None
        if bounds:
            self._sector_viewer.load_sector(
                self._current_video, bounds[0], bounds[1],
                mid_ms=self._initial_ms_for_sector(0),
            )
        else:
            self._sector_viewer.clear()

    # ── API publique ──────────────────────────────────────────────────────────

    def load_campaign_videos(self, model):
        self._video_model = model
        self._rebuild_list()
        model.rowsInserted.connect(self._rebuild_list)
        model.rowsRemoved.connect(self._rebuild_list)
        # Pré-charger les champs Analyse vidéo depuis la première vidéo disponible
        for row in range(model.rowCount()):
            item = model.item(row, 0)
            vp = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if vp and _find_json(str(vp)):
                self._load_av_fields(str(vp))
                break

    def _mask_csv_exists(self, vpath: str) -> bool:
        code = _get_codestation(vpath) or os.path.splitext(os.path.basename(vpath))[0]
        safe = "".join(c for c in code if c.isalnum() or c in "-_")
        folder = os.path.dirname(os.path.normpath(vpath))
        return os.path.isfile(os.path.join(folder, f"{safe}_masque_saisie.xlsx"))

    def _refresh_mask_indicators(self):
        """Met à jour le ✓ sur les items de la liste sans reconstruire toute la liste."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            # Texte de base = tout avant le suffixe ✓
            base = item.text().split("  ✓")[0]
            has_mask = self._mask_csv_exists(str(vpath))
            item.setText(base + ("  ✓ Masque généré" if has_mask else ""))
            font = item.font()
            font.setItalic(has_mask)
            item.setFont(font)
            item.setToolTip("Masque de saisie CSV déjà généré dans ce dossier" if has_mask else "")

    def _rebuild_list(self, *_):
        self._list.blockSignals(True)
        self._list.clear()
        if not self._video_model:
            self._list.blockSignals(False)
            return

        entries: list[tuple[str, str, str, str]] = []
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            vpath_str = str(vpath)
            expl = _get_exploitability_value(vpath_str)
            if expl not in {"oui", "habitat"}:
                continue
            code = _get_codestation(vpath_str)
            display = code or item.text() or "—"
            entries.append((display.lower(), display, vpath_str, expl))

        # Tri alphabétique par codestation
        entries.sort(key=lambda e: e[0])

        for _, display, vpath_str, expl in entries:
            has_mask = self._mask_csv_exists(vpath_str)
            text = display + ("  ✓ Masque généré" if has_mask else "")
            list_item = QtWidgets.QListWidgetItem(text)
            list_item.setData(QtCore.Qt.ItemDataRole.UserRole, vpath_str)
            if expl == "oui":
                list_item.setForeground(QtGui.QBrush(QtGui.QColor("#4ade80")))
            else:
                list_item.setForeground(QtGui.QBrush(QtGui.QColor("#fb923c")))
            if has_mask:
                font = list_item.font()
                font.setItalic(True)
                list_item.setFont(font)
                list_item.setToolTip("Masque de saisie CSV déjà généré dans ce dossier")
            self._list.addItem(list_item)

        self._list.blockSignals(False)

    def select_video_by_name(self, name: str):
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                self._list.setCurrentRow(i)
                return

    def _tr(self, fr: str) -> str:
        """Traduit un texte FR→EN si la langue courante est 'en'."""
        if self._language == 'en':
            return _EN.get(fr, fr)
        return fr

    def _retranslate_ui(self):
        """Met à jour tous les textes de l'UI selon self._language."""
        tr = self._tr
        # En-tête de la liste
        if hasattr(self, '_header_label'):
            self._header_label.setText("  Stations")
        # Bouton toggle Analyse vidéo
        is_open = self._av_toggle_btn.isChecked()
        arrow = "▼" if is_open else "▶"
        self._av_toggle_btn.setText(f"  {arrow}  {tr('Analyse vidéo')}")
        # Label sélection
        self._no_sel_label.setText(tr("Sélectionnez une station dans la liste"))
        # Label verrou
        if self._language == 'en':
            self._lock_label.setText(
                "⚠  Landing + Takeoff\nor\nStart + End annotation\n\n"
                "required in the Events page\nbefore entering habitat analysis."
            )
        else:
            self._lock_label.setText(
                "⚠  Atterrissage + Décollage\nou\nDébut + Fin annotation\n\n"
                "requis dans la page Évènements\navant de saisir l'analyse habitat."
            )
        # Labels génériques (champs formulaire + panneau analyse vidéo)
        for lbl, fr_text in self._tr_label_refs:
            lbl.setText(tr(fr_text))
        # Titres de sections du formulaire
        for section, fr_title, fr_note in self._section_widgets:
            section.retranslate(tr(fr_title), tr(fr_note) if fr_note else "")
        # Widget cascade recouvrement
        if self._sv_recouvrement is not None:
            self._sv_recouvrement.set_language(self._language)

    def set_language(self, language: str):
        self._language = language
        self._retranslate_ui()
        if hasattr(self, '_btn_export_csv'):
            self._btn_export_csv.setText(
                "Générer masque saisie (XLSX)" if language == 'fr' else "Generate entry template (XLSX)"
            )

    # ── Export XLSX masque saisie ─────────────────────────────────────────────

    def _write_xlsx_station(self, ws, code: str, vpath: str,
                             start_row: int, write_header: bool,
                             progress_cb=None) -> int:
        """Écrit une station dans la feuille ws à partir de start_row.
        Retourne la première ligne libre après cette station."""
        from openpyxl.styles import PatternFill, Font, Alignment

        FILL_HDR  = PatternFill("solid", fgColor="93CDDD")
        FILL_SEC  = PatternFill("solid", fgColor="DEE6EF")
        FONT_BOLD = Font(bold=True)
        ALIGN_CTR = Alignment(horizontal="center", vertical="center",
                               wrap_text=False)

        row = start_row
        if write_header:
            for c, h in enumerate(["Nom du point", "Couches", "Caractéristiques",
                                    "1", "2", "3", "4", "5", "6", "Commentaire"], 1):
                cell = ws.cell(row=row, column=c, value=h)
                cell.fill = FILL_HDR
                cell.font = FONT_BOLD
                cell.alignment = ALIGN_CTR
            row += 1

        d = self._data.get(vpath, {})
        data_start = row
        steps = 0

        for section_name, fields in _XLSX_LAYOUT:
            if not fields:
                cell_b = ws.cell(row=row, column=2, value=section_name)
                cell_b.fill = FILL_SEC
                cell_b.font = FONT_BOLD
                row += 1
                steps += 1
                if progress_cb:
                    progress_cb(steps)
                continue

            for field_idx, (fkey, excel_label) in enumerate(fields):
                cell_b = ws.cell(row=row, column=2)
                if field_idx == 0:
                    cell_b.value = section_name
                    cell_b.fill = FILL_SEC
                    cell_b.font = FONT_BOLD

                ws.cell(row=row, column=3, value=excel_label)

                vals = d.get(fkey)
                for s in range(6):
                    v = (vals[s] if vals and s < len(vals) else None)
                    ws.cell(row=row, column=4 + s, value=v if v else None)

                row += 1
                steps += 1
                if progress_cb:
                    progress_cb(steps)

        if row > data_start:
            cell_a = ws.cell(row=data_start, column=1)
            cell_a.value = code
            cell_a.font = FONT_BOLD
            cell_a.alignment = ALIGN_CTR
            if row - 1 > data_start:
                ws.merge_cells(
                    start_row=data_start, start_column=1,
                    end_row=row - 1, end_column=1,
                )

        return row

    def _export_saisie_csv(self):
        """Génère le masque saisie XLSX de la station courante directement dans son dossier."""
        try:
            import openpyxl
        except ImportError:
            QtWidgets.QMessageBox.critical(self._page, "Erreur",
                                           "openpyxl non installé (pip install openpyxl).")
            return

        if not self._current_video:
            QtWidgets.QMessageBox.warning(
                self._page,
                "Aucune station sélectionnée" if self._language == 'fr' else "No station selected",
                "Sélectionnez une station dans la liste." if self._language == 'fr'
                else "Select a station from the list.",
            )
            return

        vpath = self._current_video
        code = _get_codestation(vpath) or os.path.splitext(os.path.basename(vpath))[0]
        folder = os.path.dirname(os.path.normpath(vpath))
        safe_code = "".join(c for c in code if c.isalnum() or c in "-_")
        out_path = os.path.join(folder, f"{safe_code}_masque_saisie.xlsx")

        if os.path.isfile(out_path):
            reply = QtWidgets.QMessageBox.question(
                self._page,
                "Fichier existant" if self._language == 'fr' else "File already exists",
                (f"Le fichier existe déjà :\n{out_path}\n\nÉcraser ?"
                 if self._language == 'fr'
                 else f"File already exists:\n{out_path}\n\nOverwrite?"),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        total_steps = sum(max(len(fields), 1) for _, fields in _XLSX_LAYOUT)

        progress = QtWidgets.QProgressDialog(
            f"Génération : {code}" if self._language == 'fr' else f"Generating: {code}",
            None, 0, total_steps, self._page,
        )
        progress.setWindowTitle("Export XLSX")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QtWidgets.QApplication.processEvents()

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Analyses Habitat"
            ws.column_dimensions["A"].width = 18
            ws.column_dimensions["B"].width = 36
            ws.column_dimensions["C"].width = 46
            for col in ["D", "E", "F", "G", "H", "I"]:
                ws.column_dimensions[col].width = 8
            ws.column_dimensions["J"].width = 22

            def _step(s):
                progress.setValue(s)
                QtWidgets.QApplication.processEvents()

            self._write_xlsx_station(ws, code, vpath, 1, True, _step)
            wb.save(out_path)
            progress.setValue(total_steps)
            progress.close()
            print(f"[HABITAT] Masque saisie → {out_path}")
            self._refresh_mask_indicators()
            QtWidgets.QMessageBox.information(
                self._page,
                "Export réussi" if self._language == 'fr' else "Export successful",
                f"Fichier enregistré :\n{out_path}",
            )
        except Exception as exc:
            progress.close()
            QtWidgets.QMessageBox.critical(
                self._page,
                "Erreur" if self._language == 'fr' else "Error",
                str(exc),
            )

    def _on_export_csv_context_menu(self, pos):
        menu = QtWidgets.QMenu(self._btn_export_csv)
        lbl = ("Générer tous les masques de saisie (un par station)"
               if self._language == 'fr'
               else "Generate all entry templates (one per station)")
        action = menu.addAction(lbl)
        chosen = menu.exec(self._btn_export_csv.mapToGlobal(pos))
        if chosen is action:
            self._export_all_saisie_csv()

    def _export_all_saisie_csv(self):
        """Génère un XLSX par station dans son dossier (2 barres de progression)."""
        try:
            import openpyxl
        except ImportError:
            QtWidgets.QMessageBox.critical(self._page, "Erreur",
                                           "openpyxl non installé (pip install openpyxl).")
            return

        if not self._video_model:
            return

        entries: list[tuple[str, str]] = []
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
            if not vpath:
                continue
            if _get_exploitability_value(vpath) not in {"oui", "habitat"}:
                continue
            code = _get_codestation(vpath) or item.text() or os.path.splitext(os.path.basename(vpath))[0]
            entries.append((code, vpath))
        entries.sort(key=lambda e: e[0].lower())

        if not entries:
            QtWidgets.QMessageBox.information(
                self._page,
                "Aucune station" if self._language == 'fr' else "No station",
                "Aucune vidéo exploitable trouvée." if self._language == 'fr' else "No exploitable video found.",
            )
            return

        total_steps = sum(max(len(fields), 1) for _, fields in _XLSX_LAYOUT)

        # Confirmation si des fichiers existent déjà
        existing = []
        for code, vpath in entries:
            safe_code = "".join(c for c in code if c.isalnum() or c in "-_")
            p = os.path.join(os.path.dirname(os.path.normpath(vpath)),
                             f"{safe_code}_masque_saisie.xlsx")
            if os.path.isfile(p):
                existing.append(code)
        if existing:
            names = "\n".join(f"  • {c}" for c in existing[:10])
            if len(existing) > 10:
                names += f"\n  … et {len(existing) - 10} autre(s)"
            reply = QtWidgets.QMessageBox.question(
                self._page,
                "Fichiers existants" if self._language == 'fr' else "Files already exist",
                (f"{len(existing)} fichier(s) existent déjà :\n{names}\n\nÉcraser tout ?"
                 if self._language == 'fr'
                 else f"{len(existing)} file(s) already exist:\n{names}\n\nOverwrite all?"),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        # ── Dialogue avec 2 barres ────────────────────────────────────────
        dlg = QtWidgets.QDialog(self._page)
        dlg.setWindowTitle("Export XLSX – toutes les stations" if self._language == 'fr'
                           else "XLSX Export – all stations")
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setFixedWidth(420)
        dlg_lay = QtWidgets.QVBoxLayout(dlg)
        dlg_lay.setSpacing(8)
        dlg_lay.setContentsMargins(16, 16, 16, 16)

        _ss_lbl = "color:#a0c8e0; font-size:11px; font-family:'Segoe UI',sans-serif;"
        _ss_bar = ("QProgressBar { background:#0d1e2e; border:1px solid #2778a2;"
                   " border-radius:4px; height:18px; text-align:center; color:#7ec8e3; }"
                   "QProgressBar::chunk { background:#2778a2; border-radius:3px; }")

        lbl_global = QtWidgets.QLabel(f"Station 0 / {len(entries)}")
        lbl_global.setStyleSheet(_ss_lbl)
        bar_global = QtWidgets.QProgressBar()
        bar_global.setRange(0, len(entries))
        bar_global.setValue(0)
        bar_global.setStyleSheet(_ss_bar)

        lbl_local = QtWidgets.QLabel("Ligne 0 / " + str(total_steps))
        lbl_local.setStyleSheet(_ss_lbl)
        bar_local = QtWidgets.QProgressBar()
        bar_local.setRange(0, total_steps)
        bar_local.setValue(0)
        bar_local.setStyleSheet(_ss_bar)

        dlg_lay.addWidget(lbl_global)
        dlg_lay.addWidget(bar_global)
        dlg_lay.addSpacing(4)
        dlg_lay.addWidget(lbl_local)
        dlg_lay.addWidget(bar_local)
        dlg.show()
        QtWidgets.QApplication.processEvents()

        created: list[str] = []
        errors: list[str] = []

        for i, (code, vpath) in enumerate(entries):
            lbl_global.setText(f"Station {i + 1} / {len(entries)} : {code}")
            bar_global.setValue(i)
            bar_local.setValue(0)
            lbl_local.setText(f"Ligne 0 / {total_steps}")
            QtWidgets.QApplication.processEvents()

            folder = os.path.dirname(os.path.normpath(vpath))
            safe_code = "".join(c for c in code if c.isalnum() or c in "-_")
            out_path = os.path.join(folder, f"{safe_code}_masque_saisie.xlsx")
            try:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Analyses Habitat"
                ws.column_dimensions["A"].width = 18
                ws.column_dimensions["B"].width = 36
                ws.column_dimensions["C"].width = 46
                for col in ["D", "E", "F", "G", "H", "I"]:
                    ws.column_dimensions[col].width = 8
                ws.column_dimensions["J"].width = 22

                def _step(s, _lbl=lbl_local, _bar=bar_local):
                    _lbl.setText(f"Ligne {s} / {total_steps}")
                    _bar.setValue(s)
                    QtWidgets.QApplication.processEvents()

                self._write_xlsx_station(ws, code, vpath, 1, True, _step)
                wb.save(out_path)
                bar_local.setValue(total_steps)
                created.append(out_path)
                print(f"[HABITAT] Masque saisie → {out_path}")
            except Exception as exc:
                errors.append(f"{code}: {exc}")

        bar_global.setValue(len(entries))
        QtWidgets.QApplication.processEvents()
        dlg.close()
        self._refresh_mask_indicators()

        msg = (f"{len(created)} fichier(s) créé(s)." if self._language == 'fr'
               else f"{len(created)} file(s) created.")
        if errors:
            msg += "\n\nErreurs :\n" + "\n".join(errors)
        QtWidgets.QMessageBox.information(
            self._page,
            "Export terminé" if self._language == 'fr' else "Export done",
            msg,
        )


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _get_exploitability_value(video_path: str) -> str:
    """Retourne la valeur brute d'exploitabilité ('oui', 'habitat', ...) ou ''."""
    try:
        stem   = os.path.splitext(os.path.basename(video_path))[0]
        folder = os.path.dirname(os.path.normpath(video_path))
        json_path = os.path.join(folder, f"{stem}_temp.json")
        if not os.path.isfile(json_path):
            return ""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        expl = data.get("video_observation", {}).get("exploitable", {})
        val  = expl.get("value", "") if isinstance(expl, dict) else str(expl or "")
        return str(val).strip().lower()
    except Exception:
        return ""


def _is_habitat_exploitable(video_path: str) -> bool:
    """Vrai si la vidéo a un statut d'exploitabilité 'oui' ou 'habitat'."""
    try:
        stem      = os.path.splitext(os.path.basename(video_path))[0]
        folder    = os.path.dirname(os.path.normpath(video_path))
        json_path = os.path.join(folder, f"{stem}_temp.json")
        if not os.path.isfile(json_path):
            return False
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        expl = data.get("video_observation", {}).get("exploitable", {})
        val  = expl.get("value", "") if isinstance(expl, dict) else str(expl or "")
        result = str(val).strip().lower() in {"oui", "habitat"}
        print(f"[ANALYSE-HABITAT] {os.path.basename(video_path)} → exploitable={val!r} → {result}")
        return result
    except Exception as e:
        print(f"[ANALYSE-HABITAT] _is_habitat_exploitable erreur pour {video_path}: {e}")
        return False


def _get_codestation(video_path: str) -> str:
    """Retourne le codestation de la vidéo depuis son _temp.json, '' si absent."""
    try:
        from services.campaign_service import compute_codestation
        json_path = _find_json(video_path)
        if not json_path or not os.path.isfile(json_path):
            return ""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        survey = data.get("survey", {})
        obs    = data.get("video_observation", {})
        return compute_codestation(survey, obs)
    except Exception:
        return ""


def _find_json(video_path: str) -> str | None:
    """Retourne le chemin du _temp.json d'une vidéo, ou None."""
    try:
        from services.campaign_service import get_temp_json_path
        return get_temp_json_path(video_path)
    except Exception:
        pass
    try:
        stem = os.path.splitext(video_path)[0]
        candidate = stem + "_temp.json"
        return candidate if os.path.isfile(candidate) else None
    except Exception:
        return None
