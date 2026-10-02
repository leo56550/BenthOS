"""Dashboard d'avancement du dérushage — 4 donuts animés + spinner de chargement."""

import os
import json
import math

from PyQt6 import QtWidgets, QtCore, QtGui

from services.campaign_service import get_temp_json_path


# ── Métadonnées : champs essentiels vs optionnels ─────────────────────────────

# Essentiels : bloquants pour la qualité des données livrées
_META_ESSENTIAL_FIELDS: list[tuple[str, str]] = [
    ("survey",            "zone"),
    ("survey",            "type"),
    ("system",            "type_system"),
    ("video_observation", "latitude"),
    ("video_observation", "longitude"),
    ("survey",            "date"),
    ("video_observation", "time"),
    ("video_observation", "point_name"),
    ("survey",            "region"),
    ("video_observation", "depth"),
    ("video_observation", "video_path"),       # dossier datawork
    ("video_observation", "video_number"),     # nom de la vidéo
    ("video_observation", "exploitable"),
    ("survey",            "boat_name"),
    ("survey",            "pilot_name"),
    ("survey",            "crew_names"),
    ("survey",            "partners"),
]

# Optionnels : utiles mais non bloquants
_META_OPTIONAL_FIELDS: list[tuple[str, str]] = [
    ("video_observation", "habitat"),
    ("video_observation", "estimated_visibility"),
    ("video_observation", "tide"),
    ("video_observation", "moon"),
    ("video_observation", "weather"),
    ("video_observation", "wind"),
    ("video_observation", "seaState"),
    ("video_observation", "site"),
    ("video_observation", "gps_waypoint"),
]

_N_ESSENTIAL = len(_META_ESSENTIAL_FIELDS)
_N_OPTIONAL  = len(_META_OPTIONAL_FIELDS)


def _is_filled(val) -> bool:
    if val is None:
        return False
    if isinstance(val, dict):
        val = val.get("value")
    s = str(val or "").strip()
    return bool(s) and s not in ("?", "None", "null")


# ── Worker thread ─────────────────────────────────────────────────────────────

class _StatsWorker(QtCore.QThread):
    stats_ready = QtCore.pyqtSignal(dict)

    def __init__(self, video_paths: list, trash_count: int, parent=None):
        super().__init__(parent)
        self._paths = list(video_paths)
        self._trash_count = trash_count

    def run(self):
        total = len(self._paths)
        ardoise = 0
        derushees = 0
        essential_filled = 0
        optional_filled  = 0
        expl_breakdown: dict[str, int] = {}

        for vp in self._paths:
            temp = get_temp_json_path(str(vp))
            if not os.path.isfile(temp):
                continue
            try:
                with open(temp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue

            obs  = data.get("video_observation", {})
            surv = data.get("survey", {})
            sys_ = data.get("system", {})

            expl = obs.get("exploitable", {})
            expl_val = expl.get("value", "") if isinstance(expl, dict) else str(expl or "")
            expl_val = str(expl_val or "").strip()
            code_obs_val = str((obs.get("codeObs") or {}).get("value") or "").strip()
            if code_obs_val and expl_val and expl_val != "?":
                ardoise += 1

            if expl_val and expl_val != "?":
                key = expl_val.lower()
                expl_breakdown[key] = expl_breakdown.get(key, 0) + 1

            has_events = False
            motor = obs.get("events_motor")
            if isinstance(motor, list) and motor:
                has_events = True
            if not has_events:
                for key_ev in ("events_animal", "events_interesting_images"):
                    block = obs.get(key_ev)
                    if isinstance(block, list) and block:
                        vals = block[0].get("values") if isinstance(block[0], dict) else None
                        if vals:
                            has_events = True
                            break
            if has_events:
                derushees += 1

            sections = {"video_observation": obs, "survey": surv, "system": sys_}
            for section, field_key in _META_ESSENTIAL_FIELDS:
                if _is_filled(sections.get(section, {}).get(field_key)):
                    essential_filled += 1
            for section, field_key in _META_OPTIONAL_FIELDS:
                if _is_filled(sections.get(section, {}).get(field_key)):
                    optional_filled += 1

        self.stats_ready.emit({
            "total":             total,
            "trashed":           self._trash_count,
            "ardoise":           ardoise,
            "expl_breakdown":    expl_breakdown,
            "derushees":         derushees,
            "essential_filled":  essential_filled,
            "essential_total":   _N_ESSENTIAL * total,
            "optional_filled":   optional_filled,
            "optional_total":    _N_OPTIONAL  * total,
        })


# ── Popup détail exploitabilité ───────────────────────────────────────────────

_EXPL_COLORS = {
    "oui": "#34d399", "yes": "#34d399",
    "non": "#f87171", "no":  "#f87171",
    "habitat":       "#fbbf24",
    "communication": "#60a5fa",
}
_EXPL_DEFAULT_COLOR = "#6a8fa8"
_EXPL_LABELS = {
    "oui": "Oui", "yes": "Oui",
    "non": "Non", "no":  "Non",
    "habitat":       "Habitat",
    "communication": "Communication",
}


class _MiniBar(QtWidgets.QProgressBar):
    """Petite barre de progression stylisée."""
    def __init__(self, pct: int, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(5)
        self.setMinimumWidth(160)
        self.setMinimum(0)
        self.setMaximum(100)
        self.setValue(max(0, min(100, pct)))
        self.setTextVisible(False)
        self.setStyleSheet(f"""
            QProgressBar {{
                background-color: #162535;
                border-radius: 2px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """)


class _ExploitabilityPopup(QtWidgets.QDialog):
    def __init__(self, breakdown: dict[str, int], parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Répartition exploitabilité")
        self.setMinimumWidth(280)
        self.setStyleSheet("""
            QDialog { background-color: #0e1d2c; }
            QLabel  { color: #c8e0f0; background: transparent; border: none; }
        """)
        self._build(breakdown)
        self.adjustSize()

    def _build(self, breakdown: dict[str, int]):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        if not breakdown:
            lbl = QtWidgets.QLabel("Aucun statut renseigné")
            lbl.setStyleSheet("color: #3a5468; font-size: 12px;")
            layout.addWidget(lbl)
            return

        _order = ["oui", "yes", "habitat", "communication", "non", "no"]
        sorted_items = sorted(
            breakdown.items(),
            key=lambda kv: (_order.index(kv[0]) if kv[0] in _order else 99, kv[0])
        )
        total = sum(breakdown.values())

        for val, count in sorted_items:
            color_hex  = _EXPL_COLORS.get(val, _EXPL_DEFAULT_COLOR)
            label_text = _EXPL_LABELS.get(val, val.capitalize())
            pct        = int(count / total * 100) if total else 0

            block = QtWidgets.QWidget()
            block.setStyleSheet("background: transparent;")
            bl = QtWidgets.QVBoxLayout(block)
            bl.setContentsMargins(0, 4, 0, 2)
            bl.setSpacing(5)

            text_row = QtWidgets.QWidget()
            text_row.setStyleSheet("background: transparent;")
            hl = QtWidgets.QHBoxLayout(text_row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(9)

            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color: {color_hex}; font-size: 13px;")
            hl.addWidget(dot)

            lbl_status = QtWidgets.QLabel(label_text)
            lbl_status.setStyleSheet("font-size: 12px;")
            hl.addWidget(lbl_status, 1)

            lbl_count = QtWidgets.QLabel(f"{count}")
            lbl_count.setStyleSheet(
                f"color: {color_hex}; font-size: 13px; font-weight: bold;")
            hl.addWidget(lbl_count)

            lbl_pct = QtWidgets.QLabel(f"{pct} %")
            lbl_pct.setStyleSheet("color: #7aa8c0; font-size: 11px; min-width: 38px;")
            lbl_pct.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight |
                                  QtCore.Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(lbl_pct)

            bl.addWidget(text_row)
            bl.addWidget(_MiniBar(pct, color_hex))
            layout.addWidget(block)


# ── Constantes visuelles ──────────────────────────────────────────────────────

_ANIM_DURATION_MS = 850
_RW = 8          # épaisseur de l'anneau (thin = moderne)
_DS = 108        # diamètre de l'anneau


def _ease_out_quart(t: float) -> float:
    return 1.0 - (1.0 - t) ** 4


# ── Donut générique (base commune) ────────────────────────────────────────────

class _DonutBase(QtWidgets.QWidget):
    """Base partagée : timer, elapsed, taille fixe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._elapsed = QtCore.QElapsedTimer()
        self._elapsed.start()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._step)
        self.setFixedSize(148, 190)

    def _start_anim(self, delay_ms: int = 0):
        self._timer.stop()
        if delay_ms > 0:
            QtCore.QTimer.singleShot(delay_ms, self.__do_start)
        else:
            self.__do_start()

    def __do_start(self):
        self._elapsed.restart()
        self._timer.start(16)

    def _step(self):  # à surcharger
        pass

    # ── Primitives de rendu ────────────────────────────────────────────────

    @staticmethod
    def _paint_track(p: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Anneau de fond, très discret."""
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), _RW,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect, 0, 360 * 16)

    @staticmethod
    def _paint_arc(p: QtGui.QPainter,
                   rect: QtCore.QRectF,
                   start_deg: float, span_deg: float,
                   color: QtGui.QColor) -> None:
        """Arc unique avec une légère lueur ambiante (discret, pas tape-à-l'œil)."""
        if abs(span_deg) < 0.3:
            return
        sq = int(start_deg * 16)
        sp = int(span_deg  * 16)

        # Lueur ambiante — une seule couche, très transparente
        gc = QtGui.QColor(color)
        gc.setAlpha(22)
        p.setPen(QtGui.QPen(gc, _RW + 14,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

        # Arc principal
        p.setPen(QtGui.QPen(color, _RW,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

    @staticmethod
    def _paint_title(p: QtGui.QPainter, title: str, w: int, y: float) -> None:
        p.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.Weight.Medium))
        p.setPen(QtGui.QColor("#4a6e88"))
        p.drawText(QtCore.QRectF(0, y, w, 18),
                   QtCore.Qt.AlignmentFlag.AlignCenter, title.upper())


# ── Donut bi-couleur (Gardées / Jetées) ───────────────────────────────────────

class _DonutBiColor(_DonutBase):
    _C_KEPT    = QtGui.QColor("#34d399")   # emerald
    _C_TRASHED = QtGui.QColor("#f87171")   # rose

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title   = title
        self._kept    = 0
        self._trashed = 0
        self._total   = 0
        self._p       = 0.0   # animation progress 0→1

    def set_data(self, kept: int, trashed: int, delay_ms: int = 0):
        self._kept    = kept
        self._trashed = trashed
        self._total   = kept + trashed
        self._p       = 0.0
        self.update()
        self._start_anim(delay_ms)

    def _step(self):
        t = min(self._elapsed.elapsed() / _ANIM_DURATION_MS, 1.0)
        self._p = _ease_out_quart(t)
        self.update()
        if t >= 1.0:
            self._p = 1.0
            self._timer.stop()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        cx, top = w // 2, 10
        rect = QtCore.QRectF(cx - _DS / 2, top, _DS, _DS)
        total = self._total or 1

        kept_full    = self._kept    / total * 360.0
        trashed_full = self._trashed / total * 360.0
        kept_drawn    = kept_full    * self._p
        trashed_drawn = trashed_full * self._p

        self._paint_track(p, rect)
        self._paint_arc(p, rect,  90.0,               -kept_drawn,    self._C_KEPT)
        self._paint_arc(p, rect,  90.0 - kept_drawn,  -trashed_drawn, self._C_TRASHED)

        # Centre : % gardées (métrique principale)
        pct = int(self._kept / total * 100) if total > 0 else 0
        cy  = top + _DS / 2.0

        p.setFont(QtGui.QFont("Segoe UI", 19, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_KEPT)
        p.drawText(QtCore.QRectF(cx - _DS/2, cy - 23, _DS, 26),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct}%")

        # Sous-ligne : kept · trashed en couleur
        frag = QtGui.QFont("Segoe UI", 7)
        p.setFont(frag)
        label = f"{self._kept} gard.  ·  {self._trashed} jet."
        p.setPen(QtGui.QColor("#2e4a5e"))
        p.drawText(QtCore.QRectF(cx - _DS/2, cy + 5, _DS, 14),
                   QtCore.Qt.AlignmentFlag.AlignCenter, label)

        self._paint_title(p, self._title, w, top + _DS + 10)
        p.end()


# ── Donut mono-couleur ────────────────────────────────────────────────────────

class _DonutCard(_DonutBase):
    double_clicked = QtCore.pyqtSignal()

    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        self._title  = title
        self._color  = QtGui.QColor(color)
        self._value  = 0
        self._total  = 0
        self._target = 0.0
        self._angle  = 0.0

    def set_data(self, value: int, total: int, delay_ms: int = 0):
        self._value  = value
        self._total  = total
        self._target = (value / total * 360.0) if total > 0 else 0.0
        self._angle  = 0.0
        self.update()
        self._start_anim(delay_ms)

    def _step(self):
        t = min(self._elapsed.elapsed() / _ANIM_DURATION_MS, 1.0)
        self._angle = self._target * _ease_out_quart(t)
        self.update()
        if t >= 1.0:
            self._angle = self._target
            self._timer.stop()

    def mouseDoubleClickEvent(self, _event):
        self.double_clicked.emit()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        cx, top = w // 2, 10
        rect = QtCore.QRectF(cx - _DS / 2, top, _DS, _DS)
        cy   = top + _DS / 2.0

        self._paint_track(p, rect)
        self._paint_arc(p, rect, 90.0, -self._angle, self._color)

        # Pourcentage centré dans le trou
        pct = int(self._value / self._total * 100) if self._total > 0 else 0

        p.setFont(QtGui.QFont("Segoe UI", 20, QtGui.QFont.Weight.Bold))
        p.setPen(QtGui.QColor("#dff0fa"))
        p.drawText(QtCore.QRectF(cx - _DS/2, cy - 24, _DS, 26),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct}%")

        p.setFont(QtGui.QFont("Segoe UI", 7))
        p.setPen(QtGui.QColor("#2e4a5e"))
        p.drawText(QtCore.QRectF(cx - _DS/2, cy + 5, _DS, 14),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"{self._value} / {self._total}")

        self._paint_title(p, self._title, w, top + _DS + 10)
        p.end()


# ── Donut métadonnées : anneaux concentriques ─────────────────────────────────
# Anneau extérieur (vert)  = essentiels   — chaque arc = % de complétion indépendant
# Anneau intérieur (bleu)  = optionnels

class _DonutMetaSplit(_DonutBase):
    _C_ESSENTIAL = QtGui.QColor("#5DBB63")
    _C_OPTIONAL  = QtGui.QColor("#60a5fa")
    _DS_IN = 74     # diamètre anneau intérieur
    _RW_IN = 6      # épaisseur anneau intérieur

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title      = title
        self._ess_filled = 0
        self._ess_total  = 1
        self._opt_filled = 0
        self._opt_total  = 1
        self._p          = 0.0

    def set_data(self, ess_filled: int, ess_total: int,
                 opt_filled: int, opt_total: int, delay_ms: int = 0):
        self._ess_filled = ess_filled
        self._ess_total  = max(ess_total, 1)
        self._opt_filled = opt_filled
        self._opt_total  = max(opt_total, 1)
        self._p          = 0.0
        self.update()
        self._start_anim(delay_ms)

    def _step(self):
        t = min(self._elapsed.elapsed() / _ANIM_DURATION_MS, 1.0)
        self._p = _ease_out_quart(t)
        self.update()
        if t >= 1.0:
            self._p = 1.0
            self._timer.stop()

    def _paint_inner_arc(self, p: QtGui.QPainter, rect: QtCore.QRectF,
                         start_deg: float, span_deg: float, color: QtGui.QColor):
        if abs(span_deg) < 0.3:
            return
        sq, sp = int(start_deg * 16), int(span_deg * 16)
        gc = QtGui.QColor(color)
        gc.setAlpha(22)
        p.setPen(QtGui.QPen(gc, self._RW_IN + 10,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)
        p.setPen(QtGui.QPen(color, self._RW_IN,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        cx, top = w // 2, 10
        cy = top + _DS / 2.0

        rect_out = QtCore.QRectF(cx - _DS / 2, top, _DS, _DS)
        ds_in    = self._DS_IN
        rect_in  = QtCore.QRectF(cx - ds_in / 2,
                                  top + (_DS - ds_in) / 2,
                                  ds_in, ds_in)

        # Tracks (fond des deux anneaux)
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), _RW,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_out, 0, 360 * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._RW_IN,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_in, 0, 360 * 16)

        # Arcs animés (chacun en % de son propre total)
        ess_angle = self._ess_filled / self._ess_total * 360.0 * self._p
        opt_angle = self._opt_filled / self._opt_total * 360.0 * self._p

        self._paint_arc(p, rect_out, 90.0, -ess_angle, self._C_ESSENTIAL)
        self._paint_inner_arc(p, rect_in,  90.0, -opt_angle, self._C_OPTIONAL)

        # Centre : % essentiels
        pct_ess = int(self._ess_filled / self._ess_total * 100)
        pct_opt = int(self._opt_filled / self._opt_total * 100)

        p.setFont(QtGui.QFont("Segoe UI", 15, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_ESSENTIAL)
        p.drawText(QtCore.QRectF(cx - ds_in / 2, cy - 20, ds_in, 22),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct_ess}%")

        # Légende deux lignes : Essentielles / Optionnelles
        y_leg = top + _DS + 6
        p.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Weight.Bold))

        p.setPen(self._C_ESSENTIAL)
        p.drawText(QtCore.QRectF(0, y_leg, w, 13),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● Essentielles  {pct_ess}%")

        p.setPen(self._C_OPTIONAL)
        p.drawText(QtCore.QRectF(0, y_leg + 14, w, 13),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● Optionnelles  {pct_opt}%")

        self._paint_title(p, self._title, w, y_leg + 30)
        p.end()


# ── Spinner ───────────────────────────────────────────────────────────────────

class _Spinner(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(44, 44)

    def start(self): self._timer.start(25)
    def stop(self):  self._timer.stop()

    def _tick(self):
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(4, 4, 36, 36)

        # Track
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), 5,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect, 0, 360 * 16)

        # Arc animé
        p.setPen(QtGui.QPen(QtGui.QColor("#60a5fa"), 5,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, self._angle * 16, 250 * 16)
        p.end()


# ── Séparateur vertical ────────────────────────────────────────────────────────

class _VSep(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(1)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.fillRect(0, 20, 1, self.height() - 40, QtGui.QColor("#162535"))
        p.end()


# ── Dashboard widget ──────────────────────────────────────────────────────────

class ProgressDashboardWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _StatsWorker | None = None
        self._expl_breakdown: dict[str, int] = {}
        self._setup_ui()

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)

        # En-tête
        self._title_lbl = QtWidgets.QLabel("Avancement de la campagne")
        self._title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet(
            "color: #3a607c; font-size: 9px; font-weight: bold; letter-spacing: 1.8px;")
        root.addWidget(self._title_lbl)

        # Stack
        self._stack = QtWidgets.QStackedWidget()
        self._stack.setFixedHeight(182)
        root.addWidget(self._stack)

        # Page 0 — spinner
        spinner_page = QtWidgets.QWidget()
        sp = QtWidgets.QVBoxLayout(spinner_page)
        sp.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._spinner = _Spinner()
        sp.addWidget(self._spinner, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl = QtWidgets.QLabel("Calcul en cours…")
        lbl.setStyleSheet("color: #2e4a5e; font-size: 10px;")
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        sp.addWidget(lbl)
        self._stack.addWidget(spinner_page)

        # Page 1 — donuts
        donuts_page = QtWidgets.QWidget()
        dl = QtWidgets.QHBoxLayout(donuts_page)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)

        self._card_kept    = _DonutBiColor("Gardées / Jetées")
        self._card_ardoise = _DonutCard("Validation", "#fbbf24")
        self._card_meta    = _DonutMetaSplit("Métadonnées")
        self._card_derush  = _DonutCard("Dérushées",   "#a78bfa")

        self._card_ardoise.double_clicked.connect(self._show_expl_popup)
        self._card_ardoise.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._card_ardoise.setToolTip(
            "Double-cliquer pour voir la répartition par statut d'exploitabilité")

        for i, card in enumerate((self._card_kept, self._card_ardoise,
                                   self._card_meta, self._card_derush)):
            dl.addWidget(card, 1)
            if i < 3:
                dl.addWidget(_VSep())

        self._stack.addWidget(donuts_page)

    def refresh(self, video_paths: list, trash_count: int):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(200)
        self._stack.setCurrentIndex(0)
        self._spinner.start()
        self._worker = _StatsWorker(video_paths, trash_count, self)
        self._worker.stats_ready.connect(self._on_stats_ready)
        self._worker.start()

    def _on_stats_ready(self, stats: dict):
        self._spinner.stop()
        self._expl_breakdown = stats.get("expl_breakdown", {})
        total = stats["total"]

        # Entrée en cascade
        self._card_kept.set_data(total, stats["trashed"],                              delay_ms=0)
        self._card_ardoise.set_data(stats["ardoise"],   total,                         delay_ms=160)
        self._card_meta.set_data(
            stats["essential_filled"], max(stats["essential_total"], 1),
            stats["optional_filled"],  max(stats["optional_total"],  1),
            delay_ms=320)
        self._card_derush.set_data(stats["derushees"],  total,                         delay_ms=480)

        self._stack.setCurrentIndex(1)

    def _show_expl_popup(self):
        self._expl_popup = _ExploitabilityPopup(self._expl_breakdown, None)
        self._expl_popup.show()

    def set_language(self, lang: str):
        if lang == 'en':
            self._card_kept._title    = "Kept / Trashed"
            self._card_ardoise._title = "Validation"
            self._card_ardoise.setToolTip("Double-click to see breakdown by exploitability status")
            self._card_meta._title    = "Metadata"
            self._card_derush._title  = "Processed"
            self._title_lbl.setText("Campaign progress")
        else:
            self._card_kept._title    = "Gardées / Jetées"
            self._card_ardoise._title = "Validation"
            self._card_ardoise.setToolTip(
                "Double-cliquer pour voir la répartition par statut d'exploitabilité")
            self._card_meta._title    = "Métadonnées"
            self._card_derush._title  = "Dérushées"
            self._title_lbl.setText("Avancement de la campagne")
        self._card_meta.update()
        for card in (self._card_kept, self._card_ardoise,
                     self._card_meta, self._card_derush):
            card.update()


# ── Dialogue d'avancement (non-modal, reste ouvert hors focus) ────────────────

class AvancementPanel(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window |
            QtCore.Qt.WindowType.WindowTitleHint |
            QtCore.Qt.WindowType.WindowCloseButtonHint |
            QtCore.Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("Avancement de la campagne")
        self.setStyleSheet("""
            QDialog {
                background-color: #0c1b29;
                border: 1px solid #1a3048;
            }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard = ProgressDashboardWidget(self)
        layout.addWidget(self.dashboard)
        self.setFixedWidth(660)

    def show_below(self, anchor_widget: QtWidgets.QWidget):
        gp = anchor_widget.mapToGlobal(QtCore.QPoint(0, anchor_widget.height()))
        x  = gp.x() + anchor_widget.width() // 2 - self.width() // 2
        y  = gp.y()
        sc = anchor_widget.screen()
        if sc:
            sg = sc.availableGeometry()
            x = max(sg.left(), min(x, sg.right() - self.width()))
            y = min(y, sg.bottom() - self.sizeHint().height())
        self.move(x, y)
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle(self, anchor_widget: QtWidgets.QWidget):
        if self.isVisible():
            self.hide()
        else:
            self.show_below(anchor_widget)
