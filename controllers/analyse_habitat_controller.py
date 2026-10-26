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
    ("Herbier ou Algues sur substrat visible", "", [
        ("algues_sv",   "Algues sur substrat visible",  "presence"),
        ("herbier_sv",  "Herbier sur substrat visible", "presence"),
    ]),
    ("Recouvrement Herbier", "somme à 100 % par secteur", [
        ("total_herbier",      "Total herbier",             "percent"),
        ("herbier_court",      "Herbier court (<20cm)",     "percent"),
        ("herbier_haut",       "Herbier haut (>20cm)",      "percent"),
        ("herbier_dense",      "Herbier dense",             "percent"),
        ("herbier_semi_dense", "Herbier semi-dense",        "percent"),
        ("herbier_clairseme",  "Herbier clairsemé (<25%)",  "percent"),
        ("matte_morte",        "Matte morte",               "percent"),
    ]),
    ("Recouvrement par épibiontes", "1=non, 2=un peu, 3=beaucoup", [
        ("epib_algues",   "Algues",   "score13"),
        ("epib_herbier",  "Herbier",  "score13"),
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
        ("etat_sante",   "Etat de santé herbier/algues",  "score13"),
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

        self._btn.clicked.connect(self._toggle)

    def _toggle(self):
        self._collapsed = not self._content.isVisible()
        self._content.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        txt = self._btn.text()
        self._btn.setText(txt.replace("▼", arrow).replace("▶", arrow))

    def set_layout(self, layout):
        self._content.setLayout(layout)


# ── Canvas image zoomable/panable ────────────────────────────────────────────

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
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._zoom = max(0.1, min(10.0, self._zoom * factor))
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
        self._pos_ms = mid_ms if mid_ms is not None else (clip_start_ms + clip_end_ms) // 2
        self._read_and_show()

    def clear(self):
        self._stop_playback()
        self._video_path = None
        self._raw_frame = None
        self._canvas.set_pixmap(None)
        self._lbl_time.setText("—")

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
        s = self._pos_ms // 1000
        self._lbl_time.setText(f"{s // 60:02d}:{s % 60:02d}")

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
            interval = max(16, int(1000.0 / self._fps))
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

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            self._btn_play.setChecked(not self._btn_play.isChecked())
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
        self._total_lbl.setText(f"Total : {total} %")
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

        # Timestamps / thumbnails secteurs
        self._sector_mid_ts: list[float | None] = [None] * 6
        self._sector_bounds: list[tuple[int, int] | None] = [None] * 6
        self._sector_pixmaps: list[QtGui.QPixmap | None] = [None] * 6
        self._sector_photo_labels: list[QtWidgets.QLabel] = []
        self._sector_worker: _FrameWorker | None = None

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
        vlay.addWidget(header)

        self._list = QtWidgets.QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background:#111f2e; color:#a0c8e0; border:none;"
            " font-family:'Segoe UI',sans-serif; font-size:11px; }"
            "QListWidget::item { padding:5px 10px; border-bottom:1px solid #1a2e40; }"
            "QListWidget::item:selected { background:#20415d; color:#ffffff; }"
            "QListWidget::item:hover { background:#162438; }"
        )
        self._list.currentRowChanged.connect(self._on_row_changed)
        vlay.addWidget(self._list, 1)

        # ── Panneau Analyse vidéo replié par défaut ────────────────────────
        vlay.addWidget(self._build_analysis_panel_compact())
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
            return w

        def _inp(key, placeholder=""):
            w = QtWidgets.QLineEdit()
            w.setPlaceholderText(placeholder)
            w.setStyleSheet(_inp_s)
            w.setMinimumHeight(24)
            w.editingFinished.connect(lambda k=key, wi=w: self._save_av_field(k, wi.text()))
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

        outer_lay.addWidget(self._av_panel_content)

        def _toggle(checked):
            self._av_panel_content.setVisible(checked)
            self._av_toggle_btn.setText(
                f"  {'▼' if checked else '▶'}  Analyse vidéo")

        self._av_toggle_btn.toggled.connect(_toggle)
        return outer

    def _build_right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setStyleSheet("background:#0b1421;")
        vlay = QtWidgets.QVBoxLayout(panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # 1. Sélecteur de secteur (S1..S6 avec thumbnails)
        self._sector_selector = self._build_sector_selector()
        vlay.addWidget(self._sector_selector)

        # 2. Viewer image (image + corrections + lecture)
        self._sector_viewer = _SectorViewerWidget()
        self._sector_viewer.setFixedHeight(250)
        vlay.addWidget(self._sector_viewer)

        # 3. Formulaire mono-secteur (scrollable)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background:#0b1421; }"
            "QScrollBar:vertical { background:#0d1e2e; width:8px; border-radius:4px; }"
            "QScrollBar::handle:vertical { background:#2778a2; border-radius:4px; }"
        )
        self._form_container = QtWidgets.QWidget()
        self._form_container.setStyleSheet("background:#0b1421;")
        form_lay = QtWidgets.QVBoxLayout(self._form_container)
        form_lay.setContentsMargins(8, 4, 8, 16)
        form_lay.setSpacing(0)

        self._sv_widgets.clear()
        self._build_single_sector_form(form_lay)
        form_lay.addStretch()

        scroll.setWidget(self._form_container)
        vlay.addWidget(scroll, 1)

        self._no_sel_label = QtWidgets.QLabel(
            "Sélectionnez une station dans la liste")
        self._no_sel_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._no_sel_label.setStyleSheet(
            "color:#3a5568; font-size:14px; font-family:'Segoe UI',sans-serif;")
        vlay.addWidget(self._no_sel_label)

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

            if section_name == "Recouvrement visible":
                inner = QtWidgets.QVBoxLayout()
                inner.setContentsMargins(4, 4, 4, 4)
                inner.setSpacing(4)
                self._sv_recouvrement = _RecouvrementCascade()
                self._sv_recouvrement.data_changed.connect(
                    self._sv_on_recouvrement_changed)
                inner.addWidget(self._sv_recouvrement)
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

    def _switch_sector(self, idx: int):
        """Change le secteur affiché dans le viewer et recharge le formulaire."""
        self._current_sector_idx = idx
        self._highlight_sector(idx)
        if self._current_video and self._sector_viewer is not None:
            bounds = self._sector_bounds[idx] if idx < len(self._sector_bounds) else None
            mid_ts = self._sector_mid_ts[idx] if idx < len(self._sector_mid_ts) else None
            if bounds:
                self._sector_viewer.load_sector(
                    self._current_video, bounds[0], bounds[1],
                    mid_ms=int(mid_ts * 1000) if mid_ts is not None else None,
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
        finally:
            self._updating = False
        self._sv_refresh_totals()

    def _sv_on_changed(self, field_key: str, value):
        if self._updating or not self._current_video:
            return
        d = self._data.setdefault(self._current_video, {})
        row = d.setdefault(field_key, [0] * 6)
        row[self._current_sector_idx] = value
        self._sv_refresh_totals()

    def _sv_on_recouvrement_changed(self):
        if self._updating or not self._current_video or self._sv_recouvrement is None:
            return
        cascade_data = self._sv_recouvrement.get_data()
        d = self._data.setdefault(self._current_video, {})
        for k, _ in _RECOUVREMENT_TYPES:
            row = d.setdefault(k, [0] * 6)
            row[self._current_sector_idx] = cascade_data.get(k, 0)
        self._sv_refresh_totals()

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
        if not self._video_model:
            return
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            json_path = _find_json(str(vpath))
            if not json_path or not os.path.isfile(json_path):
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

    def _load_rotation_timestamps(self, video_path: str):
        """Extrait les 6 timestamps de milieu de secteur depuis le JSON de la vidéo."""
        self._sector_mid_ts = [None] * 6
        self._sector_bounds = [None] * 6
        self._sector_pixmaps = [None] * 6

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

    def _on_row_changed(self, row: int):
        if row < 0:
            self._current_video = None
            self._sector_selector.setVisible(False)
            self._sector_viewer.setVisible(False)
            self._scroll.setVisible(False)
            self._no_sel_label.setVisible(True)
            return
        list_item = self._list.item(row)
        vpath = list_item.data(QtCore.Qt.ItemDataRole.UserRole) if list_item else None
        if not vpath:
            return
        self._current_video = str(vpath)
        self._sector_selector.setVisible(True)
        self._sector_viewer.setVisible(True)
        self._scroll.setVisible(True)
        self._no_sel_label.setVisible(False)
        self._load_av_fields(self._current_video)
        self._load_rotation_timestamps(self._current_video)
        self._start_frame_extraction(self._current_video)
        # Afficher secteur 0 par défaut
        self._current_sector_idx = 0
        self._highlight_sector(0)
        self._sv_reload_form()
        bounds = self._sector_bounds[0] if self._sector_bounds else None
        if bounds:
            mid_ts = self._sector_mid_ts[0]
            self._sector_viewer.load_sector(
                self._current_video, bounds[0], bounds[1],
                mid_ms=int(mid_ts * 1000) if mid_ts is not None else None,
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

    def _rebuild_list(self, *_):
        self._list.blockSignals(True)
        self._list.clear()
        if not self._video_model:
            self._list.blockSignals(False)
            return
        for row in range(self._video_model.rowCount()):
            item = self._video_model.item(row, 0)
            if not item:
                continue
            vpath = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if not vpath:
                continue
            vpath_str = str(vpath)
            if not _is_habitat_exploitable(vpath_str):
                continue
            code = _get_codestation(vpath_str)
            display = code or item.text() or "—"
            list_item = QtWidgets.QListWidgetItem(display)
            list_item.setData(QtCore.Qt.ItemDataRole.UserRole, vpath_str)
            if code:
                list_item.setForeground(QtGui.QBrush(QtGui.QColor("#4ade80")))  # vert
            else:
                list_item.setForeground(QtGui.QBrush(QtGui.QColor("#fb923c")))  # orange
            self._list.addItem(list_item)
        self._list.blockSignals(False)

    def select_video_by_name(self, name: str):
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                self._list.setCurrentRow(i)
                return

    def set_language(self, language: str):
        self._language = language


# ── Utilitaires ───────────────────────────────────────────────────────────────

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
