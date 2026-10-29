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


_LANDING_KW  = ("atterrissage", "atterissage", "landing")
_TAKEOFF_KW  = ("décollage", "decollage", "takeoff")


def _has_landing_and_takeoff(obs: dict) -> bool:
    """Retourne True si le JSON contient à la fois un atterrissage et un décollage."""
    # Source principale : champs scalaires dédiés (boutons Atterrissage / Décollage)
    landing = str((obs.get("timecode_landing") or {}).get("value") or "").strip()
    takeoff = str((obs.get("timecode_takeoff") or {}).get("value") or "").strip()
    if landing and takeoff:
        return True

    has_l, has_t = bool(landing), bool(takeoff)

    # Repli : events_motor (format flat nouveau ou wrapper ancien)
    motor = obs.get("events_motor") or []
    if isinstance(motor, list):
        for item in motor:
            if not isinstance(item, dict):
                continue
            # Format flat (nouveau) : description_fr
            val = str(item.get("description_fr") or item.get("value", "")).strip().lower()
            if not has_l and any(kw in val for kw in _LANDING_KW):
                has_l = True
            if not has_t and any(kw in val for kw in _TAKEOFF_KW):
                has_t = True
            # Format wrapper (ancien) : sous-liste "values"
            for nested in item.get("values", []):
                if isinstance(nested, dict):
                    nval = str(nested.get("value", "")).strip().lower()
                    if not has_l and any(kw in nval for kw in _LANDING_KW):
                        has_l = True
                    if not has_t and any(kw in nval for kw in _TAKEOFF_KW):
                        has_t = True
            if has_l and has_t:
                return True

    return has_l and has_t


# ── Worker thread ─────────────────────────────────────────────────────────────

class _StatsWorker(QtCore.QThread):
    stats_ready = QtCore.pyqtSignal(dict)

    def __init__(self, video_paths: list, trash_count: int, parent=None):
        super().__init__(parent)
        self._paths = list(video_paths)
        self._trash_count = trash_count

    @staticmethod
    def _habitat_json_path(vp: str) -> str:
        stem   = os.path.splitext(os.path.basename(vp))[0]
        folder = os.path.dirname(os.path.normpath(vp))
        return os.path.join(folder, f"{stem}_habitat.json")

    def run(self):
        total = len(self._paths)
        ardoise = 0
        derushees = 0
        annotations = 0
        essential_filled = 0
        optional_filled  = 0
        expl_breakdown: dict[str, int] = {}
        habitat_done = 0
        habitat_detail: list[dict] = []   # [{code, n_sectors, done}]

        for vp in self._paths:
            vp_str = str(vp)
            temp = get_temp_json_path(vp_str)

            # ── Habitat ───────────────────────────────────────────────────────
            hab_path = self._habitat_json_path(vp_str)
            if os.path.isfile(hab_path):
                try:
                    with open(hab_path, 'r', encoding='utf-8') as f:
                        hab = json.load(f)
                    sectors = hab.get("sectors", [])
                    n_done  = sum(
                        1 for s in sectors
                        if any(v for v in s.values() if v and v != 0)
                    )
                    code = hab.get("meta", {}).get("codestation", "") or \
                           os.path.splitext(os.path.basename(vp_str))[0]
                    has_data = n_done > 0 or bool(
                        {k: v for k, v in hab.items()
                         if k not in ("meta", "sectors") and v}
                    )
                    if has_data:
                        habitat_done += 1
                    habitat_detail.append({
                        "code":     code,
                        "n_done":   n_done,
                        "n_total":  len(sectors) if sectors else 6,
                        "has_data": has_data,
                    })
                except Exception:
                    pass

            # ── Temp JSON ─────────────────────────────────────────────────────
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
            point_name_val = (
                str((obs.get("point_name")     or {}).get("value") or "").strip()
                or str((obs.get("station_number") or {}).get("value") or "").strip()
            )
            if point_name_val and expl_val and expl_val != "?":
                ardoise += 1

            if expl_val and expl_val != "?":
                key = expl_val.lower()
                expl_breakdown[key] = expl_breakdown.get(key, 0) + 1

            if _has_landing_and_takeoff(obs):
                derushees += 1

            debut_val = str((obs.get("timecode_debut") or {}).get("value") or "").strip()
            end_val   = str((obs.get("timecode_end")   or {}).get("value") or "").strip()
            if debut_val and end_val:
                annotations += 1

            sections = {"video_observation": obs, "survey": surv, "system": sys_}
            for section, field_key in _META_ESSENTIAL_FIELDS:
                if _is_filled(sections.get(section, {}).get(field_key)):
                    essential_filled += 1
            for section, field_key in _META_OPTIONAL_FIELDS:
                if _is_filled(sections.get(section, {}).get(field_key)):
                    optional_filled += 1

        analyse_eligible = sum(
            1 for k in expl_breakdown if k in {"oui", "yes", "habitat"}
            for _ in range(expl_breakdown[k])
        )

        self.stats_ready.emit({
            "total":             total,
            "trashed":           self._trash_count,
            "ardoise":           ardoise,
            "expl_breakdown":    expl_breakdown,
            "derushees":         derushees,
            "annotations":       annotations,
            "essential_filled":  essential_filled,
            "essential_total":   _N_ESSENTIAL * total,
            "optional_filled":   optional_filled,
            "optional_total":    _N_OPTIONAL  * total,
            "analyse_eligible":  analyse_eligible,
            "habitat_done":      habitat_done,
            "habitat_detail":    habitat_detail,
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

# Mode compact (incrusté dans la toolbar)
_RW_C = 5
_DS_C = 60
_W_C  = 80       # largeur du widget compact
_H_C  = 98       # hauteur du widget compact


def _ease_out_quart(t: float) -> float:
    return 1.0 - (1.0 - t) ** 4


# ── Donut générique (base commune) ────────────────────────────────────────────

class _DonutBase(QtWidgets.QWidget):
    """Base partagée : timer, elapsed, taille fixe."""

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self._compact = compact
        self._ds = _DS_C if compact else _DS
        self._rw = _RW_C if compact else _RW
        self._elapsed = QtCore.QElapsedTimer()
        self._elapsed.start()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._step)
        if compact:
            self.setFixedSize(_W_C, _H_C)
        else:
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

    def _paint_track(self, p: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Anneau de fond, très discret."""
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._rw,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect, 0, 360 * 16)

    def _paint_arc(self, p: QtGui.QPainter,
                   rect: QtCore.QRectF,
                   start_deg: float, span_deg: float,
                   color: QtGui.QColor) -> None:
        """Arc unique avec une légère lueur ambiante (discret, pas tape-à-l'œil)."""
        if abs(span_deg) < 0.3:
            return
        sq = int(start_deg * 16)
        sp = int(span_deg  * 16)

        gc = QtGui.QColor(color)
        gc.setAlpha(22)
        glow = self._rw + (8 if self._compact else 14)
        p.setPen(QtGui.QPen(gc, glow,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

        p.setPen(QtGui.QPen(color, self._rw,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

    def _paint_title(self, p: QtGui.QPainter, title: str, w: int, y: float) -> None:
        sz = 7 if self._compact else 8
        p.setFont(QtGui.QFont("Segoe UI", sz, QtGui.QFont.Weight.Medium))
        p.setPen(QtGui.QColor("#4a6e88"))
        p.drawText(QtCore.QRectF(0, y, w, 16),
                   QtCore.Qt.AlignmentFlag.AlignCenter, title.upper())


# ── Donut bi-couleur (Gardées / Jetées) ───────────────────────────────────────

class _DonutBiColor(_DonutBase):
    _C_KEPT    = QtGui.QColor("#34d399")   # emerald
    _C_TRASHED = QtGui.QColor("#f87171")   # rose

    def __init__(self, title: str, compact: bool = False, parent=None):
        super().__init__(compact=compact, parent=parent)
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

        ds = self._ds
        w, h = self.width(), self.height()
        cx, top = w // 2, 6 if self._compact else 10
        rect = QtCore.QRectF(cx - ds / 2, top, ds, ds)
        total = self._total or 1

        kept_full    = self._kept    / total * 360.0
        trashed_full = self._trashed / total * 360.0
        kept_drawn    = kept_full    * self._p
        trashed_drawn = trashed_full * self._p

        self._paint_track(p, rect)
        self._paint_arc(p, rect,  90.0,               -kept_drawn,    self._C_KEPT)
        self._paint_arc(p, rect,  90.0 - kept_drawn,  -trashed_drawn, self._C_TRASHED)

        cy = top + ds / 2.0
        big_sz  = 13 if self._compact else 22
        small_sz = 8 if self._compact else 12

        p.setFont(QtGui.QFont("Segoe UI", big_sz, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_KEPT)
        p.drawText(QtCore.QRectF(cx - ds/2, cy - (18 if self._compact else 30), ds,
                                 big_sz + 4),
                   QtCore.Qt.AlignmentFlag.AlignCenter, str(self._kept))

        p.setFont(QtGui.QFont("Segoe UI", small_sz, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_TRASHED)
        p.drawText(QtCore.QRectF(cx - ds/2, cy + (2 if self._compact else 2), ds, small_sz + 4),
                   QtCore.Qt.AlignmentFlag.AlignCenter, str(self._trashed))

        leg_sz = 6 if self._compact else 7
        frag = QtGui.QFont("Segoe UI", leg_sz)
        p.setFont(frag)
        y_leg = top + ds + 4
        p.setPen(self._C_KEPT)
        p.drawText(QtCore.QRectF(0, y_leg, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {self._kept}" if self._compact else f"● Gardées  {self._kept}")
        p.setPen(self._C_TRASHED)
        p.drawText(QtCore.QRectF(0, y_leg + 12, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {self._trashed}" if self._compact else f"● Jetées  {self._trashed}")

        self._paint_title(p, self._title, w, y_leg + (26 if self._compact else 30))
        p.end()


# ── Donut mono-couleur ────────────────────────────────────────────────────────

class _DonutCard(_DonutBase):
    double_clicked = QtCore.pyqtSignal()

    def __init__(self, title: str, color: str, compact: bool = False, parent=None):
        super().__init__(compact=compact, parent=parent)
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

        ds = self._ds
        w = self.width()
        cx, top = w // 2, 6 if self._compact else 10
        rect = QtCore.QRectF(cx - ds / 2, top, ds, ds)
        cy   = top + ds / 2.0

        self._paint_track(p, rect)
        self._paint_arc(p, rect, 90.0, -self._angle, self._color)

        pct = int(self._value / self._total * 100) if self._total > 0 else 0
        big_sz = 13 if self._compact else 20

        p.setFont(QtGui.QFont("Segoe UI", big_sz, QtGui.QFont.Weight.Bold))
        p.setPen(QtGui.QColor("#dff0fa"))
        p.drawText(QtCore.QRectF(cx - ds/2, cy - (16 if self._compact else 24), ds,
                                 big_sz + 4),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct}%")

        if not self._compact:
            p.setFont(QtGui.QFont("Segoe UI", 7))
            p.setPen(QtGui.QColor("#2e4a5e"))
            p.drawText(QtCore.QRectF(cx - ds/2, cy + 5, ds, 14),
                       QtCore.Qt.AlignmentFlag.AlignCenter,
                       f"{self._value} / {self._total}")

        self._paint_title(p, self._title, w, top + ds + (4 if self._compact else 10))
        p.end()


# ── Donut métadonnées : anneaux concentriques ─────────────────────────────────
# Anneau extérieur (vert)  = essentiels   — chaque arc = % de complétion indépendant
# Anneau intérieur (bleu)  = optionnels

class _DonutMetaSplit(_DonutBase):
    _C_ESSENTIAL = QtGui.QColor("#5DBB63")
    _C_OPTIONAL  = QtGui.QColor("#60a5fa")

    def __init__(self, title: str, compact: bool = False, parent=None):
        super().__init__(compact=compact, parent=parent)
        self._title      = title
        self._ess_filled = 0
        self._ess_total  = 1
        self._opt_filled = 0
        self._opt_total  = 1
        self._p          = 0.0
        # diamètre intérieur proportionnel au mode
        self._ds_in = 40 if compact else 74
        self._rw_in = 3 if compact else 6

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
        glow = self._rw_in + (6 if self._compact else 10)
        p.setPen(QtGui.QPen(gc, glow,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)
        p.setPen(QtGui.QPen(color, self._rw_in,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        ds = self._ds
        w = self.width()
        cx, top = w // 2, 6 if self._compact else 10
        cy = top + ds / 2.0

        rect_out = QtCore.QRectF(cx - ds / 2, top, ds, ds)
        ds_in    = self._ds_in
        rect_in  = QtCore.QRectF(cx - ds_in / 2, top + (ds - ds_in) / 2, ds_in, ds_in)

        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._rw,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_out, 0, 360 * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._rw_in,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_in, 0, 360 * 16)

        ess_angle = self._ess_filled / self._ess_total * 360.0 * self._p
        opt_angle = self._opt_filled / self._opt_total * 360.0 * self._p

        self._paint_arc(p, rect_out, 90.0, -ess_angle, self._C_ESSENTIAL)
        self._paint_inner_arc(p, rect_in, 90.0, -opt_angle, self._C_OPTIONAL)

        pct_ess = int(self._ess_filled / self._ess_total * 100)
        pct_opt = int(self._opt_filled / self._opt_total * 100)
        big_sz  = 10 if self._compact else 15

        p.setFont(QtGui.QFont("Segoe UI", big_sz, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_ESSENTIAL)
        p.drawText(QtCore.QRectF(cx - ds_in / 2, cy - (14 if self._compact else 20),
                                 ds_in, big_sz + 4),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct_ess}%")

        y_leg = top + ds + 4
        leg_sz = 6 if self._compact else 7
        p.setFont(QtGui.QFont("Segoe UI", leg_sz, QtGui.QFont.Weight.Bold))

        p.setPen(self._C_ESSENTIAL)
        p.drawText(QtCore.QRectF(0, y_leg, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {pct_ess}%" if self._compact else f"● Essentielles  {pct_ess}%")

        p.setPen(self._C_OPTIONAL)
        p.drawText(QtCore.QRectF(0, y_leg + 12, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {pct_opt}%" if self._compact else f"● Optionnelles  {pct_opt}%")

        self._paint_title(p, self._title, w, y_leg + (26 if self._compact else 30))
        p.end()


# ── Donut Dérushé : anneaux concentriques ────────────────────────────────────
# Anneau extérieur (violet)  = Atterrissage / Décollage
# Anneau intérieur (rose)    = Début annotation / Fin annotation

class _DonutDerushSplit(_DonutBase):
    _C_LAND  = QtGui.QColor("#a78bfa")   # violet
    _C_ANNO  = QtGui.QColor("#f0abfc")   # rose/violet

    def __init__(self, title: str, compact: bool = False, parent=None):
        super().__init__(compact=compact, parent=parent)
        self._title    = title
        self._land_val = 0
        self._anno_val = 0
        self._total    = 1
        self._p        = 0.0
        self._ds_in = 40 if compact else 74
        self._rw_in = 3 if compact else 6

    def set_data(self, land: int, anno: int, total: int, delay_ms: int = 0):
        self._land_val = land
        self._anno_val = anno
        self._total    = max(total, 1)
        self._p        = 0.0
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
        glow = self._rw_in + (6 if self._compact else 10)
        p.setPen(QtGui.QPen(gc, glow,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)
        p.setPen(QtGui.QPen(color, self._rw_in,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, sq, sp)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        ds = self._ds
        w = self.width()
        cx, top = w // 2, 6 if self._compact else 10
        cy = top + ds / 2.0

        rect_out = QtCore.QRectF(cx - ds / 2, top, ds, ds)
        ds_in    = self._ds_in
        rect_in  = QtCore.QRectF(cx - ds_in / 2, top + (ds - ds_in) / 2, ds_in, ds_in)

        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._rw,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_out, 0, 360 * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#111f2d"), self._rw_in,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_in, 0, 360 * 16)

        land_angle = self._land_val / self._total * 360.0 * self._p
        anno_angle = self._anno_val / self._total * 360.0 * self._p

        self._paint_arc(p, rect_out, 90.0, -land_angle, self._C_LAND)
        self._paint_inner_arc(p, rect_in, 90.0, -anno_angle, self._C_ANNO)

        pct_land = int(self._land_val / self._total * 100)
        pct_anno = int(self._anno_val / self._total * 100)
        big_sz   = 10 if self._compact else 15

        p.setFont(QtGui.QFont("Segoe UI", big_sz, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_LAND)
        p.drawText(QtCore.QRectF(cx - ds_in / 2, cy - (14 if self._compact else 20),
                                 ds_in, big_sz + 4),
                   QtCore.Qt.AlignmentFlag.AlignCenter, f"{pct_land}%")

        y_leg = top + ds + 4
        leg_sz = 6 if self._compact else 7
        p.setFont(QtGui.QFont("Segoe UI", leg_sz, QtGui.QFont.Weight.Bold))

        p.setPen(self._C_LAND)
        p.drawText(QtCore.QRectF(0, y_leg, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {pct_land}%" if self._compact else f"● Att./Déc.  {pct_land}%")

        p.setPen(self._C_ANNO)
        p.drawText(QtCore.QRectF(0, y_leg + 12, w, 12),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"● {pct_anno}%" if self._compact else f"● Déb./Fin ann.  {pct_anno}%")

        self._paint_title(p, self._title, w, y_leg + (26 if self._compact else 30))
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
    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self._compact = compact
        self._worker: _StatsWorker | None = None
        self._expl_breakdown: dict[str, int] = {}
        self._setup_ui()

    def _setup_ui(self):
        c = self._compact
        root = QtWidgets.QVBoxLayout(self)
        m = 2 if c else 8
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(2 if c else 4)

        # Stack principal : spinner (0) ou onglets (1)
        self._stack = QtWidgets.QStackedWidget()
        root.addWidget(self._stack)

        # Page 0 — spinner
        spinner_page = QtWidgets.QWidget()
        sp = QtWidgets.QVBoxLayout(spinner_page)
        sp.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._spinner = _Spinner()
        sp.addWidget(self._spinner, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        if not c:
            lbl = QtWidgets.QLabel("Calcul en cours…")
            lbl.setStyleSheet("color: #2e4a5e; font-size: 10px;")
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            sp.addWidget(lbl)
        self._stack.addWidget(spinner_page)

        # Page 1 — tous les donuts côte à côte
        self._card_kept    = _DonutBiColor("Qualification", compact=c)
        self._card_ardoise = _DonutCard("Validation", "#fbbf24", compact=c)
        self._card_meta    = _DonutMetaSplit("Métadonnées", compact=c)
        self._card_derush  = _DonutDerushSplit("Évènements", compact=c)
        self._card_habitat = _DonutCard("Habitat", "#34d399", compact=c)

        self._card_ardoise.double_clicked.connect(self._show_expl_popup)
        self._card_ardoise.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._card_ardoise.setToolTip(
            "Double-cliquer pour voir la répartition par statut d'exploitabilité")

        cards_page = QtWidgets.QWidget()
        cards_lay = QtWidgets.QHBoxLayout(cards_page)
        cards_lay.setContentsMargins(12, 8, 12, 8)
        cards_lay.setSpacing(0)
        cards_lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        for i, card in enumerate([
            self._card_kept, self._card_ardoise, self._card_meta,
            self._card_derush, self._card_habitat,
        ]):
            if i > 0:
                cards_lay.addWidget(_VSep())
            cards_lay.addWidget(card, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self._stack.addWidget(cards_page)

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
        kept = total - stats["trashed"]

        self._card_kept.set_data(kept, stats["trashed"],                               delay_ms=0)
        self._card_ardoise.set_data(stats["ardoise"],   total,                         delay_ms=160)
        self._card_meta.set_data(
            stats["essential_filled"], max(stats["essential_total"], 1),
            stats["optional_filled"],  max(stats["optional_total"],  1),
            delay_ms=320)
        self._card_derush.set_data(stats["derushees"], stats["annotations"], total,    delay_ms=480)
        self._card_habitat.set_data(0, max(total, 1),                                  delay_ms=640)

        self._stack.setCurrentIndex(1)

    def _show_expl_popup(self):
        self._expl_popup = _ExploitabilityPopup(self._expl_breakdown, None)
        self._expl_popup.show()

    def set_language(self, lang: str):
        if lang == 'en':
            self._card_kept._title    = "Qualification"
            self._card_ardoise._title = "Validation"
            self._card_ardoise.setToolTip("Double-click to see breakdown by exploitability status")
            self._card_meta._title    = "Metadata"
            self._card_derush._title  = "Events"
            self._card_habitat._title = "Habitat"
        else:
            self._card_kept._title    = "Qualification"
            self._card_ardoise._title = "Validation"
            self._card_ardoise.setToolTip(
                "Double-cliquer pour voir la répartition par statut d'exploitabilité")
            self._card_meta._title    = "Métadonnées"
            self._card_derush._title  = "Évènements"
            self._card_habitat._title = "Habitat"
        for card in (self._card_kept, self._card_ardoise,
                     self._card_meta, self._card_derush, self._card_habitat):
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
        self.setFixedWidth(800)

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


# ── Donut mini pour la toolbar (auto-contenu, pas de spinner) ─────────────────

_MINI_D  = 34   # diamètre anneau
_MINI_RW = 4    # épaisseur anneau
_MINI_W  = 58   # largeur widget
_MINI_H  = 42   # hauteur widget


class _HabitatPopup(QtWidgets.QDialog):
    """Popup de détail de l'avancement Analyse Habitat par station."""

    def __init__(self, detail: list[dict], done: int, total: int, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Avancement Analyse Habitat")
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog { background-color: #0e1d2c; }
            QLabel  { color: #c8e0f0; background: transparent; border: none; }
        """)
        self._build(detail, done, total)
        self.adjustSize()

    def _build(self, detail: list[dict], done: int, total: int):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)

        # En-tête
        pct = int(done / total * 100) if total else 0
        hdr = QtWidgets.QLabel(f"Stations traitées : {done} / {total}  ({pct} %)")
        hdr.setStyleSheet("font-size: 13px; font-weight: bold; color: #34d399;")
        lay.addWidget(hdr)

        if not detail:
            lay.addWidget(QtWidgets.QLabel("Aucune donnée habitat trouvée."))
            return

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("border: 1px solid #1a3048; margin: 4px 0;")
        lay.addWidget(sep)

        for row in detail:
            code    = row["code"] or "—"
            n_done  = row["n_done"]
            n_total = row["n_total"]
            has_d   = row["has_data"]

            line = QtWidgets.QWidget()
            line.setStyleSheet("background: transparent;")
            hl = QtWidgets.QHBoxLayout(line)
            hl.setContentsMargins(0, 2, 0, 2)
            hl.setSpacing(8)

            dot = QtWidgets.QLabel("✓" if has_d else "○")
            dot.setStyleSheet(
                f"color: {'#34d399' if has_d else '#2e4a5e'}; font-size: 12px;")
            hl.addWidget(dot)

            lbl_code = QtWidgets.QLabel(code)
            lbl_code.setStyleSheet(
                f"font-size: 11px; color: {'#c8e0f0' if has_d else '#3a5468'};")
            hl.addWidget(lbl_code, 1)

            if n_done > 0:
                lbl_sec = QtWidgets.QLabel(f"{n_done}/{n_total} secteurs")
                lbl_sec.setStyleSheet("font-size: 10px; color: #7aa8c0;")
                hl.addWidget(lbl_sec)

            lay.addWidget(line)


class _MiniRingDual(QtWidgets.QWidget):
    """Deux anneaux concentriques mini : essentiel (ext.) + optionnel (int.)."""

    _C_ESS = QtGui.QColor("#5DBB63")
    _C_OPT = QtGui.QColor("#60a5fa")
    _D_IN  = 20   # diamètre anneau intérieur
    _RW_IN = 3

    def __init__(self, tip: str, parent=None):
        super().__init__(parent)
        self._pct_ess = 0
        self._pct_opt = 0
        self._p       = 0.0
        self._elapsed = QtCore.QElapsedTimer()
        self._elapsed.start()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._step)
        self.setFixedSize(_MINI_W, _MINI_H)
        self.setToolTip(tip)

    def set_data(self, pct_ess: int, pct_opt: int, delay_ms: int = 0):
        self._pct_ess = max(0, min(100, pct_ess))
        self._pct_opt = max(0, min(100, pct_opt))
        self._p = 0.0
        if delay_ms > 0:
            QtCore.QTimer.singleShot(delay_ms, self._start)
        else:
            self._start()

    def _start(self):
        self._elapsed.restart()
        self._timer.start(16)

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
        cx  = w // 2
        top = (h - _MINI_D) // 2

        rect_out = QtCore.QRectF(cx - _MINI_D / 2, top, _MINI_D, _MINI_D)
        rect_in  = QtCore.QRectF(cx - self._D_IN / 2,
                                 top + (_MINI_D - self._D_IN) / 2,
                                 self._D_IN, self._D_IN)

        # Tracks
        p.setPen(QtGui.QPen(QtGui.QColor("#1e3a52"), _MINI_RW,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_out, 0, 360 * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#1e3a52"), self._RW_IN,
                            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect_in, 0, 360 * 16)

        # Arcs
        a_ess = self._pct_ess / 100 * 360.0 * self._p
        a_opt = self._pct_opt / 100 * 360.0 * self._p
        if a_ess > 0.3:
            p.setPen(QtGui.QPen(self._C_ESS, _MINI_RW,
                                QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
            p.drawArc(rect_out, int(90 * 16), int(-a_ess * 16))
        if a_opt > 0.3:
            p.setPen(QtGui.QPen(self._C_OPT, self._RW_IN,
                                QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
            p.drawArc(rect_in, int(90 * 16), int(-a_opt * 16))

        # Pourcentage essentiel au centre
        p.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Weight.Bold))
        p.setPen(self._C_ESS)
        p.drawText(rect_in, QtCore.Qt.AlignmentFlag.AlignCenter, f"{self._pct_ess}%")
        p.end()


class _MiniRing(QtWidgets.QWidget):
    """Petit anneau de progression pour la toolbar : juste le ring + un pourcentage."""

    double_clicked = QtCore.pyqtSignal()

    def __init__(self, color: str, tip: str, parent=None):
        super().__init__(parent)
        self._color  = QtGui.QColor(color)
        self._pct    = 0
        self._p_anim = 0.0
        self._elapsed = QtCore.QElapsedTimer()
        self._elapsed.start()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._step)
        self.setFixedSize(_MINI_W, _MINI_H)
        self.setToolTip(tip)

    def set_pct(self, pct: int, delay_ms: int = 0):
        self._pct    = max(0, min(100, pct))
        self._p_anim = 0.0
        if delay_ms > 0:
            QtCore.QTimer.singleShot(delay_ms, self._start)
        else:
            self._start()

    def _start(self):
        self._elapsed.restart()
        self._timer.start(16)

    def _step(self):
        t = min(self._elapsed.elapsed() / _ANIM_DURATION_MS, 1.0)
        self._p_anim = _ease_out_quart(t)
        self.update()
        if t >= 1.0:
            self._p_anim = 1.0
            self._timer.stop()

    def mouseDoubleClickEvent(self, _event):
        self.double_clicked.emit()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        cx   = w // 2
        top  = (h - _MINI_D) // 2
        rect = QtCore.QRectF(cx - _MINI_D / 2, top, _MINI_D, _MINI_D)

        p.setPen(QtGui.QPen(QtGui.QColor("#1e3a52"), _MINI_RW,
                            QtCore.Qt.PenStyle.SolidLine,
                            QtCore.Qt.PenCapStyle.FlatCap))
        p.drawArc(rect, 0, 360 * 16)

        angle = self._pct / 100 * 360.0 * self._p_anim
        if angle > 0.3:
            p.setPen(QtGui.QPen(self._color, _MINI_RW,
                                QtCore.Qt.PenStyle.SolidLine,
                                QtCore.Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, int(90 * 16), int(-angle * 16))

        p.setFont(QtGui.QFont("Segoe UI", 7, QtGui.QFont.Weight.Bold))
        p.setPen(QtGui.QColor("#c8e0f0"))
        p.drawText(QtCore.QRectF(cx - _MINI_D / 2, top, _MINI_D, _MINI_D),
                   QtCore.Qt.AlignmentFlag.AlignCenter,
                   f"{self._pct}%")
        p.end()


class ProgressToolbarStrip(QtWidgets.QWidget):
    """Bande de 5 mini-donuts à incruster dans la toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _StatsWorker | None = None
        self._expl_breakdown: dict[str, int] = {}
        self._habitat_detail: list[dict] = []
        self._habitat_done = 0
        self._stats: dict = {}

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(10)

        self._r_kept    = _MiniRing("#34d399", "Qualification")
        self._r_ardoise = _MiniRing("#fbbf24", "Validation")
        self._r_meta    = _MiniRingDual("Métadonnées")
        self._r_derush  = _MiniRing("#a78bfa", "Évènements")
        self._r_habitat = _MiniRing("#34d399", "Habitat")

        self._r_habitat.double_clicked.connect(self._show_habitat_popup)
        self._r_habitat.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        _pairs = [
            ("Qualif.",  "#34d399", self._r_kept),
            ("Valid.",   "#fbbf24", self._r_ardoise),
            ("Méta.",    "#5DBB63", self._r_meta),
            ("Évènts.", "#a78bfa", self._r_derush),
            ("Habitat",  "#34d399", self._r_habitat),
        ]
        for title, color, ring in _pairs:
            lbl = QtWidgets.QLabel(title)
            lbl.setStyleSheet(
                f"color: {color}; font-size: 9px; font-weight: bold;"
                " background: transparent; border: none;")
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight |
                             QtCore.Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(lbl)
            lay.addWidget(ring)

        self.setFixedHeight(_MINI_H + 6)

    def refresh(self, video_paths: list, trash_count: int):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(200)
        self._worker = _StatsWorker(video_paths, trash_count, self)
        self._worker.stats_ready.connect(self._on_stats_ready)
        self._worker.start()

    def _on_stats_ready(self, stats: dict):
        self._stats = stats
        self._expl_breakdown = stats.get("expl_breakdown", {})
        total  = stats["total"] or 1
        kept   = total - stats["trashed"]
        ess_f  = stats["essential_filled"]
        ess_t  = max(stats["essential_total"], 1)
        opt_f  = stats["optional_filled"]
        opt_t  = max(stats["optional_total"], 1)
        land   = stats["derushees"]
        anno   = stats["annotations"]

        self._r_kept.set_pct(int(kept / total * 100), delay_ms=0)
        self._r_kept.setToolTip(
            f"Qualification\nGardées : {kept} / {total} ({int(kept/total*100)}%)\n"
            f"Jetées : {stats['trashed']}")

        self._r_ardoise.set_pct(int(stats["ardoise"] / total * 100), delay_ms=100)
        _expl_lines = []
        _order = ["oui", "yes", "habitat", "communication", "non", "no"]
        _labels = {"oui": "Oui", "yes": "Oui", "non": "Non", "no": "Non",
                   "habitat": "Habitat", "communication": "Communication"}
        for _k in sorted(self._expl_breakdown,
                         key=lambda k: (_order.index(k) if k in _order else 99, k)):
            _n = self._expl_breakdown[_k]
            _pct_k = int(_n / total * 100)
            _expl_lines.append(f"  {_labels.get(_k, _k.capitalize())} : {_n} ({_pct_k}%)")
        _expl_block = "\n".join(_expl_lines) if _expl_lines else "  —"
        self._r_ardoise.setToolTip(
            f"Validation\nArdoise renseignée : {stats['ardoise']} / {total} "
            f"({int(stats['ardoise']/total*100)}%)\n"
            f"Répartition exploitabilité :\n{_expl_block}")

        self._r_meta.set_data(int(ess_f / ess_t * 100), int(opt_f / opt_t * 100), delay_ms=200)
        self._r_meta.setToolTip(
            f"Métadonnées\n● Essentielles : {ess_f} / {ess_t} ({int(ess_f/ess_t*100)}%)\n"
            f"● Optionnelles : {opt_f} / {opt_t} ({int(opt_f/opt_t*100)}%)")

        self._r_derush.set_pct(int(land / total * 100), delay_ms=300)
        self._r_derush.setToolTip(
            f"Évènements\nAtt./Déc. : {land} / {total} ({int(land/total*100)}%)\n"
            f"Début/Fin ann. : {anno} / {total} ({int(anno/total*100)}%)")

        self._habitat_done   = stats.get("habitat_done", 0)
        self._habitat_detail = stats.get("habitat_detail", [])
        hab_pct = int(self._habitat_done / total * 100)
        self._r_habitat.set_pct(hab_pct, delay_ms=400)
        self._r_habitat.setToolTip(
            f"Analyse Habitat\nStations traitées : {self._habitat_done} / {total} ({hab_pct}%)\n"
            f"Double-cliquer pour le détail par station")

    def _show_expl_popup(self):
        self._expl_popup = _ExploitabilityPopup(self._expl_breakdown, None)
        self._expl_popup.show()

    def _show_habitat_popup(self):
        total = self._stats.get("total", 0) or len(self._habitat_detail) or 1
        self._hab_popup = _HabitatPopup(
            self._habitat_detail, self._habitat_done, total, None)
        self._hab_popup.show()

    def set_language(self, lang: str):
        if lang == 'en':
            self._r_kept.setToolTip("Qualification")
            self._r_ardoise.setToolTip("Validation")
            self._r_meta.setToolTip("Metadata")
            self._r_derush.setToolTip("Events (landing/takeoff + annotations)")
            self._r_habitat.setToolTip("Habitat — double-click for details")
        else:
            self._r_kept.setToolTip("Qualification")
            self._r_ardoise.setToolTip("Validation")
            self._r_meta.setToolTip("Métadonnées")
            self._r_derush.setToolTip("Évènements (att./déc. + annotations)")
            self._r_habitat.setToolTip("Habitat — double-cliquer pour le détail")
        # Après chargement, les tooltips seront regénérés par _on_stats_ready
