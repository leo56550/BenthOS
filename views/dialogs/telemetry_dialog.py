import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

_MISSING_STYLE = (
    "color: #5a7a8a; font-size: 11px; font-style: italic;"
    " font-family: 'Segoe UI', sans-serif;"
)

# Hauteur compacte quand les données sont manquantes
_COMPACT_H = 36


class _TimeAxis(pg.AxisItem):
    """Axe X pyqtgraph qui affiche les secondes au format MM:SS."""
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            try:
                total_s = int(round(float(v)))
                sign = "-" if total_s < 0 else ""
                total_s = abs(total_s)
                m, s = divmod(total_s, 60)
                out.append(f"{sign}{m:02d}:{s:02d}")
            except (TypeError, ValueError):
                out.append("")
        return out


_LUX_RGB_COLS = {
    'RLux': ('#ff4040', 'R'),
    'GLux': ('#40dd70', 'G'),
    'BLux': ('#4090ff', 'B'),
}


class TelemetryDialog(QtWidgets.QDialog):
    """Dialogue d'analyse télémétrie : graphes pyqtgraph (température, profondeur, exposition, RGB lux)."""

    time_clicked = QtCore.pyqtSignal(float)  # secondes depuis le début de la vidéo

    _METRIC_TRANSLATIONS = {
        "température":  ("Température (°C)",       "Temperature (°C)"),
        "profondeur":   ("Profondeur (m)",          "Depth (m)"),
        "ExpTime":      ("Temps d'exposition (ms)", "Exposure Time (ms)"),
        "lux_rgb":      ("Luminosité RGB (Lux)",   "RGB Luminosity (Lux)"),
    }

    def __init__(self, parent=None):
        """Initialise les graphes pyqtgraph et les curseurs dynamiques pour chaque métrique."""
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.current_language = 'fr'
        self.setWindowTitle("Analyse Télémétrie")
        self.resize(900, 800)

        pg.setConfigOptions(antialias=False, useOpenGL=True)

        self.full_df = None
        self.plots        = {}   # key → PlotDataItem
        self.stacks       = {}   # key → QStackedWidget
        self.plot_widgets = {}   # key → PlotWidget (for title updates)
        self.missing_labels = {} # key → QLabel (for "données manquantes" text updates)
        self._lux_rgb_curves = {}  # col → PlotDataItem (RLux, GLux, BLux)

        self._x_data_min    = 0.0
        self._x_data_max    = 1.0
        self._master_vb     = None
        self._scroll_busy   = False
        self._cursor_lines  = {}   # key → pg.InfiniteLine

        self.metrics = {
            "température":  ("Température (°C)",       "#ff4d4d"),
            "profondeur":   ("Profondeur (m)",          "#4dff88"),
            "ExpTime":      ("Temps d'exposition (ms)", "#4da6ff"),
        }

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Splitter H : graphes temporels (gauche) | profil T°/profondeur (droite)
        self._h_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self._h_splitter.setStyleSheet(
            "QSplitter::handle { background: #1e3448; width: 4px; }"
            "QSplitter::handle:hover { background: #2778a2; }"
        )
        main_layout.addWidget(self._h_splitter, stretch=1)

        # Panneau gauche — graphes temporels
        left_w = QtWidgets.QWidget()
        left_lay = QtWidgets.QVBoxLayout(left_w)
        left_lay.setSpacing(4)
        left_lay.setContentsMargins(0, 0, 0, 0)
        self._h_splitter.addWidget(left_w)

        # Panneau droit — profil T°/profondeur
        right_w = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right_w)
        right_lay.setSpacing(4)
        right_lay.setContentsMargins(0, 0, 0, 0)
        self._h_splitter.addWidget(right_w)
        self._h_splitter.setSizes([650, 250])
        self._h_splitter.setCollapsible(1, False)

        _profile_title = "Profil T°/Profondeur" if True else "T°/Depth Profile"
        self._profile_title_fr = "Profil T°/Profondeur"
        self._profile_title_en = "T°/Depth Profile"
        self._pw_profile = pg.PlotWidget(title=_profile_title)
        self._pw_profile.setBackground('#111820')
        self._pw_profile.showGrid(x=True, y=True, alpha=0.3)
        self._pw_profile.invertY(True)
        self._pw_profile.showAxis('top')
        self._pw_profile.hideAxis('bottom')
        self._pw_profile.setLabel('top',  'Température (°C)', color='#ff4d4d', size='10pt')
        self._pw_profile.setLabel('left', 'Profondeur (m)',   color='#4dff88', size='10pt')
        self._pw_profile.getAxis('top').setPen(pg.mkPen('#ff4d4d'))
        self._pw_profile.getAxis('left').setPen(pg.mkPen('#4dff88'))
        self._profile_curve = self._pw_profile.plot(
            pen=pg.mkPen('#ff7840', width=1.5),
        )
        self._profile_cursor_dot = pg.ScatterPlotItem(
            size=10, symbol='o',
            brush=pg.mkBrush('#00d4ff'),
            pen=pg.mkPen('#ffffff', width=1),
        )
        self._pw_profile.addItem(self._profile_cursor_dot)
        self._profile_t_arr: "np.ndarray | None" = None
        self._profile_d_arr: "np.ndarray | None" = None
        self._profile_x_arr: "np.ndarray | None" = None  # Delta (temps)
        self._profile_last_idx: int = -1
        self._pending_cursor_t: float = 0.0
        self._cursor_timer = QtCore.QTimer(self)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._tick_cursors)
        right_lay.addWidget(self._pw_profile, stretch=1)

        # Alias : les graphes temporels s'ajoutent dans left_lay
        _time_lay = left_lay

        for key, (label, color) in self.metrics.items():
            # ── Stack : page 0 = graph  |  page 1 = compact "manquant" ──
            stack = QtWidgets.QStackedWidget()

            # --- Graphe ---
            pw = pg.PlotWidget(title=label, axisItems={'bottom': _TimeAxis(orientation='bottom')})
            self.plot_widgets[key] = pw
            pw.setBackground('#111820')
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.setMouseEnabled(x=True, y=True)
            if key == "profondeur":
                pw.invertY(True)
            show_label = (len(self._cursor_lines) == 0)  # label uniquement sur le 1er graphe
            cursor_line = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen('#00d4ff', width=1.5),
                label='00:00' if show_label else None,
                labelOpts={'position': 0.96, 'color': '#00d4ff',
                           'fill': pg.mkBrush(13, 24, 32, 210)} if show_label else {},
            )
            pw.addItem(cursor_line)
            self._cursor_lines[key] = cursor_line
            curve = pw.plot(pen=pg.mkPen(color, width=1.5))
            pw.scene().sigMouseClicked.connect(
                lambda evt, _pw=pw: self._on_graph_clicked(evt, _pw))

            # --- Bandeau "données manquantes" (très compact) ---
            missing_w = QtWidgets.QWidget()
            missing_w.setStyleSheet("background-color: #111820;")
            missing_w.setFixedHeight(_COMPACT_H)
            row = QtWidgets.QHBoxLayout(missing_w)
            row.setContentsMargins(12, 4, 12, 4)
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px; border: none;")
            lbl = QtWidgets.QLabel(f"{label} — données manquantes")
            lbl.setStyleSheet(_MISSING_STYLE)
            self.missing_labels[key] = lbl
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()

            stack.addWidget(pw)        # index 0
            stack.addWidget(missing_w) # index 1

            self.plots[key]  = curve
            self.stacks[key] = stack
            _time_lay.addWidget(stack, stretch=3)

        # ── Graphe RGB Lux (3 courbes sur un même PlotWidget) ────────────────
        _lux_label = "Luminosité RGB (Lux)"
        pw_lux = pg.PlotWidget(title=_lux_label, axisItems={'bottom': _TimeAxis(orientation='bottom')})
        self.plot_widgets["lux_rgb"] = pw_lux
        pw_lux.setBackground('#111820')
        pw_lux.showGrid(x=True, y=True, alpha=0.3)
        pw_lux.setMouseEnabled(x=True, y=True)
        cursor_line_lux = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen('#00d4ff', width=1.5))
        pw_lux.addItem(cursor_line_lux)
        self._cursor_lines["lux_rgb"] = cursor_line_lux

        legend = pw_lux.addLegend(offset=(10, 10))
        legend.setLabelTextColor('w')

        for col, (color, name) in _LUX_RGB_COLS.items():
            self._lux_rgb_curves[col] = pw_lux.plot(
                pen=pg.mkPen(color, width=1.5), name=name
            )

        pw_lux.scene().sigMouseClicked.connect(
            lambda evt, _pw=pw_lux: self._on_graph_clicked(evt, _pw))

        stack_lux = QtWidgets.QStackedWidget()
        missing_lux = QtWidgets.QWidget()
        missing_lux.setStyleSheet("background-color: #111820;")
        missing_lux.setFixedHeight(_COMPACT_H)
        row_lux = QtWidgets.QHBoxLayout(missing_lux)
        row_lux.setContentsMargins(12, 4, 12, 4)
        dot_lux = QtWidgets.QLabel("● ● ●")
        dot_lux.setStyleSheet("color: #a060a0; font-size: 10px; border: none;")
        lbl_lux = QtWidgets.QLabel(f"{_lux_label} — données manquantes")
        lbl_lux.setStyleSheet(_MISSING_STYLE)
        self.missing_labels["lux_rgb"] = lbl_lux
        row_lux.addWidget(dot_lux)
        row_lux.addWidget(lbl_lux)
        row_lux.addStretch()

        stack_lux.addWidget(pw_lux)
        stack_lux.addWidget(missing_lux)
        self.stacks["lux_rgb"] = stack_lux
        _time_lay.addWidget(stack_lux, stretch=3)

        # ── Bouton Réinitialiser ─────────────────────────────────────────────
        self._btn_reset = QtWidgets.QPushButton("RÉINITIALISER")
        self._btn_reset.setFixedHeight(28)
        self._btn_reset.setStyleSheet(
            "QPushButton { background: #1a3a50; color: #7ec8e3; border: 1px solid #2778A2;"
            " border-radius: 4px; font-size: 11px; font-family: 'Segoe UI'; padding: 0 12px; }"
            "QPushButton:hover { background: #2778A2; color: #ffffff; }"
            "QPushButton:pressed { background: #1a5070; }"
        )
        self._btn_reset.clicked.connect(self._reset_all_views)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._btn_reset)
        _time_lay.addLayout(btn_row)

        # ── Scrollbar horizontal (navigation dans le temps) ──────────────────
        self._hscroll = QtWidgets.QScrollBar(QtCore.Qt.Orientation.Horizontal)
        self._hscroll.setRange(0, 0)
        self._hscroll.setEnabled(False)
        self._hscroll.setSingleStep(1)
        self._hscroll.setStyleSheet(
            "QScrollBar:horizontal { background: #0d1520; height: 14px; border: none;"
            " border-top: 1px solid #1e2d3d; }"
            "QScrollBar::handle:horizontal { background: #2778A2; border-radius: 6px;"
            " min-width: 28px; }"
            "QScrollBar::handle:horizontal:hover { background: #3a9ad4; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal"
            " { width: 0; border: none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal"
            " { background: none; }"
        )
        self._hscroll.valueChanged.connect(self._on_hscroll)
        _time_lay.addWidget(self._hscroll)

    # ── Language ──────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        """Retourne la chaîne fr ou en selon la langue active."""
        return fr if self.current_language == 'fr' else en

    def _init_scroll_links(self, x_min: float, x_max: float):
        """Lie les axes X de tous les graphes visibles et branche le scrollbar."""
        self._x_data_min = x_min
        self._x_data_max = x_max

        # Lier tous les PlotWidgets au maître (température en premier s'il est visible)
        first_pw = None
        for key in ["température", "profondeur", "ExpTime", "lux_rgb"]:
            pw = self.plot_widgets.get(key)
            if pw is None:
                continue
            if first_pw is None:
                first_pw = pw
                self._master_vb = pw.getViewBox()
            else:
                pw.setXLink(first_pw)

        if self._master_vb is None:
            return

        try:
            self._master_vb.sigXRangeChanged.disconnect(self._on_vb_range_changed)
        except TypeError:
            pass
        self._master_vb.sigXRangeChanged.connect(self._on_vb_range_changed)

        # Vue initiale : plage complète (données + durée vidéo) dès l'ouverture
        self._master_vb.setXRange(x_min, x_max, padding=0.02)
        for pw in self.plot_widgets.values():
            pw.getViewBox().enableAutoRange(axis='y')
        self._hscroll.setRange(0, 0)
        self._hscroll.setEnabled(False)

    def _on_vb_range_changed(self, vb, x_range):
        """Met à jour le scrollbar quand le ViewBox maître est zoomé/pané."""
        if self._scroll_busy:
            return
        x_start, x_end = x_range
        view_span = x_end - x_start
        total_span = self._x_data_max - self._x_data_min
        max_scroll = max(0.0, total_span - view_span)

        if max_scroll <= 0:
            self._scroll_busy = True
            self._hscroll.setRange(0, 0)
            self._hscroll.setEnabled(False)
            self._scroll_busy = False
            return

        scale = 100  # précision : centisecondes
        max_val  = int(max_scroll * scale)
        page     = max(1, int(view_span * scale))
        pos      = max(0.0, x_start - self._x_data_min)
        pos_val  = max(0, min(int(pos * scale), max_val))

        self._scroll_busy = True
        self._hscroll.setRange(0, max_val)
        self._hscroll.setPageStep(page)
        self._hscroll.setSingleStep(max(1, page // 20))
        self._hscroll.setValue(pos_val)
        self._hscroll.setEnabled(True)
        self._scroll_busy = False

    def _on_hscroll(self, value: int):
        """Positionne le ViewBox maître (et tous les graphes liés) selon le scrollbar."""
        if self._scroll_busy or self._master_vb is None:
            return
        scale = 100
        x_start = self._x_data_min + value / scale
        vr = self._master_vb.viewRange()
        view_span = vr[0][1] - vr[0][0]
        x_end = x_start + view_span
        self._scroll_busy = True
        self._master_vb.setXRange(x_start, x_end, padding=0)
        self._scroll_busy = False

    def _reset_all_views(self):
        """Remet tous les graphes visibles sur la plage exacte des données."""
        if self._master_vb is not None and hasattr(self, '_x_data_min'):
            self._master_vb.setXRange(self._x_data_min, self._x_data_max, padding=0.02)
            for pw in self.plot_widgets.values():
                pw.getViewBox().enableAutoRange(axis='y')
        else:
            for pw in self.plot_widgets.values():
                pw.enableAutoRange()
                pw.autoRange()
        self._hscroll.setRange(0, 0)
        self._hscroll.setEnabled(False)
        _pvb = self._pw_profile.getViewBox()
        _pvb.enableAutoRange()
        _pvb.autoRange()
        _pvb.disableAutoRange()

    def showEvent(self, event):
        super().showEvent(event)
        self._cursor_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._cursor_timer.stop()

    def set_language(self, language: str):
        """Met à jour la langue, le titre et les libellés des métriques."""
        self.current_language = language
        self.setWindowTitle(self.translate("Analyse Télémétrie", "Telemetry Analysis"))
        self._btn_reset.setText(self.translate("RÉINITIALISER", "RESET VIEW"))
        self._pw_profile.setTitle(
            self.translate(self._profile_title_fr, self._profile_title_en))
        self._pw_profile.setLabel('top',
            self.translate('Température (°C)', 'Temperature (°C)'),
            color='#ff4d4d', size='10pt')
        self._pw_profile.setLabel('left',
            self.translate('Profondeur (m)', 'Depth (m)'),
            color='#4dff88', size='10pt')
        missing_suffix = self.translate("données manquantes", "missing data")
        for key, (fr_label, en_label) in self._METRIC_TRANSLATIONS.items():
            label = fr_label if language == 'fr' else en_label
            if key in self.plot_widgets:
                self.plot_widgets[key].setTitle(label)
            if key in self.missing_labels:
                self.missing_labels[key].setText(f"{label} — {missing_suffix}")

    # ── Chargement des données (une seule fois) ───────────────────────────

    def update_data(self, df, video_duration_s: float = 0.0):
        """Charge le DataFrame de télémétrie et trace les courbes (ou affiche 'manquant')."""
        self._video_duration_s = video_duration_s
        if df is None or df.empty:
            for key, stack in self.stacks.items():
                self._show_missing(key, stack)
            return

        self.full_df = df
        x_data = self.full_df['Delta'].values

        # Métriques simples (une courbe par graphe)
        for key, curve in self.plots.items():
            stack = self.stacks[key]
            if key not in self.full_df.columns:
                self._show_missing(key, stack)
                continue

            try:
                y_data = self.full_df[key].values.astype(float)
            except (ValueError, TypeError):
                self._show_missing(key, stack)
                continue

            valid = y_data[~np.isnan(y_data)]
            if len(valid) == 0 or (valid != 0).sum() == 0:
                self._show_missing(key, stack)
            else:
                curve.setData(x_data, y_data)
                self._show_graph(key, stack)

        # Graphe RGB Lux (3 courbes sur un même axe)
        any_lux = False
        for col, curve in self._lux_rgb_curves.items():
            if col not in self.full_df.columns:
                curve.setData([], [])
                continue
            try:
                y = self.full_df[col].values.astype(float)
            except (ValueError, TypeError):
                curve.setData([], [])
                continue
            valid = y[~np.isnan(y)]
            if len(valid) > 0 and (valid != 0).sum() > 0:
                curve.setData(x_data, y)
                any_lux = True
            else:
                curve.setData([], [])

        if any_lux:
            self._show_graph("lux_rgb", self.stacks["lux_rgb"])
        else:
            self._show_missing("lux_rgb", self.stacks["lux_rgb"])

        x_max = float(x_data.max())
        if self._video_duration_s > x_max:
            x_max = self._video_duration_s
        self._init_scroll_links(float(x_data.min()), x_max)

        # ── Profil T°/profondeur ─────────────────────────────────────────────
        has_temp  = "température" in self.full_df.columns
        has_depth = "profondeur"  in self.full_df.columns
        if has_temp and has_depth:
            try:
                t_arr = self.full_df["température"].values.astype(float)
                d_arr = self.full_df["profondeur"].values.astype(float)
                x_arr = self.full_df["Delta"].values.astype(float)
                mask  = ~(np.isnan(t_arr) | np.isnan(d_arr))
                self._profile_curve.setData(t_arr[mask], d_arr[mask])
                self._profile_t_arr = t_arr
                self._profile_d_arr = d_arr
                self._profile_x_arr = x_arr
                self._profile_last_idx = -1
                vb = self._pw_profile.getViewBox()
                vb.enableAutoRange()
                vb.autoRange()
                vb.disableAutoRange()
            except Exception:
                self._profile_curve.setData([], [])
                self._profile_t_arr = self._profile_d_arr = self._profile_x_arr = None
        else:
            self._profile_curve.setData([], [])
            self._profile_t_arr = self._profile_d_arr = self._profile_x_arr = None

    def _show_missing(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page 'données manquantes' (bandeau compact)."""
        stack.setCurrentIndex(1)
        stack.setMaximumHeight(_COMPACT_H)

    def _show_graph(self, key: str, stack: QtWidgets.QStackedWidget):
        """Bascule le stack sur la page graphe et restaure la hauteur maximale."""
        stack.setCurrentIndex(0)
        stack.setMaximumHeight(16777215)

    def set_cursor(self, t_s: float):
        """Stocke le temps — la mise à jour graphique est cadencée par _cursor_timer."""
        self._pending_cursor_t = t_s

    def _tick_cursors(self):
        """Cadence les mises à jour curseur — appelé par timer."""
        t_s = self._pending_cursor_t

        # Lignes verticales — bloquer les repaints individuels, un seul repaint groupé
        mm = int(t_s) // 60
        ss = int(t_s) % 60
        time_str = f"{mm:02d}:{ss:02d}"
        for pw in self.plot_widgets.values():
            pw.setUpdatesEnabled(False)
        try:
            for line in self._cursor_lines.values():
                line.setPos(t_s)
                lbl = getattr(line, 'label', None)
                if lbl is not None:
                    lbl.setText(time_str)
        finally:
            for pw in self.plot_widgets.values():
                pw.setUpdatesEnabled(True)

        # Point sur le profil T°/profondeur
        if (self._profile_x_arr is not None
                and self._profile_t_arr is not None
                and self._profile_d_arr is not None
                and len(self._profile_x_arr) > 0):
            idx = int(np.searchsorted(self._profile_x_arr, t_s, side='left'))
            idx = min(idx, len(self._profile_x_arr) - 1)
            if idx != self._profile_last_idx:
                self._profile_last_idx = idx
                temp_val  = self._profile_t_arr[idx]
                depth_val = self._profile_d_arr[idx]
                if not (np.isnan(temp_val) or np.isnan(depth_val)):
                    self._profile_cursor_dot.setData([temp_val], [depth_val])
                else:
                    self._profile_cursor_dot.setData([], [])

    def _on_graph_clicked(self, event, pw):
        """Émet time_clicked (en secondes) quand l'utilisateur clique sur un graphe."""
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = pw.getViewBox()
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(event.scenePos())
        t = mouse_point.x()
        if self.full_df is not None and 'Delta' in self.full_df.columns:
            t_max = float(self.full_df['Delta'].max())
            t = max(0.0, min(t, t_max))
        else:
            t = max(0.0, t)
        self.time_clicked.emit(t)

