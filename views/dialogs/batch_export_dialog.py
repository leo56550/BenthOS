from PyQt6 import QtWidgets, QtCore


class BatchExportDialog(QtWidgets.QDialog):
    """Dialogue d'export en batch : sélection des vidéos + options d'export identiques à ExportOptionsDialog."""

    def __init__(self, video_paths: list[str], parent=None, is_stereo: bool = False,
                 language: str = 'fr'):
        super().__init__(parent)
        self._video_paths = video_paths
        self.is_stereo = is_stereo
        self.current_language = language

        self.setModal(True)
        self.resize(440, 760)
        self.setWindowTitle(self.translate("Export en batch", "Batch Export"))

        self.setStyleSheet("""
            QDialog { background-color: #111820; color: #ffffff; }
            QLabel { color: #b0c8d8; font-family: "Segoe UI", sans-serif; }
            QGroupBox {
                border: 1px solid #2778A2; border-radius: 5px;
                margin-top: 18px; padding-top: 10px; color: #F2BFB4;
                font-family: "Segoe UI", sans-serif; font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 3px 8px; background-color: #2778A2; color: white;
                border-radius: 3px; font-size: 12px; font-weight: bold;
            }
            QCheckBox { color: #b0c8d8; spacing: 6px; font-family: "Segoe UI", sans-serif; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #2778A2; border-radius: 3px; background: #162433;
            }
            QCheckBox::indicator:checked { background-color: #2778A2; }
            QSpinBox {
                background-color: #162433; color: #F2BFB4;
                border: 1px solid #2a4057; border-radius: 3px; padding: 3px 6px;
                font-family: "Segoe UI", sans-serif;
            }
            QSpinBox:focus { border-color: #2778A2; }
            QPushButton {
                background-color: #20415D; color: white; font-weight: bold;
                border: 1px solid #2778A2; border-radius: 4px;
                padding: 6px 18px; font-size: 12px; font-family: "Segoe UI", sans-serif;
            }
            QPushButton:hover { background-color: #2778A2; }
            QPushButton:pressed { background-color: #152d42; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: #162433; width: 8px; margin: 0;
                border: 1px solid #2a4057; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2778A2; min-height: 20px; border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(12, 12, 12, 12)

        # ── Section vidéos ─────────────────────────────────────────────────
        self._videos_group = QtWidgets.QGroupBox("", self)
        vg_layout = QtWidgets.QVBoxLayout(self._videos_group)
        vg_layout.setSpacing(4)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_all = QtWidgets.QPushButton("", self)
        self._btn_all.setFixedHeight(24)
        self._btn_all.setStyleSheet(
            "QPushButton{font-size:10px;padding:2px 8px;background:#1a3a1a;"
            "color:#80e880;border:1px solid #2a8a2a;border-radius:3px;font-weight:bold;}"
            "QPushButton:hover{background:#2a7a2a;color:white;}")
        self._btn_none = QtWidgets.QPushButton("", self)
        self._btn_none.setFixedHeight(24)
        self._btn_none.setStyleSheet(
            "QPushButton{font-size:10px;padding:2px 8px;background:#3a1a1a;"
            "color:#e08080;border:1px solid #8a2a2a;border-radius:3px;font-weight:bold;}"
            "QPushButton:hover{background:#7a2a2a;color:white;}")
        self._btn_all.clicked.connect(self._check_all)
        self._btn_none.clicked.connect(self._uncheck_all)
        btn_row.addWidget(self._btn_all)
        btn_row.addWidget(self._btn_none)
        btn_row.addStretch()
        vg_layout.addLayout(btn_row)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        scroll.setMinimumHeight(80)
        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background:#0d1622;")
        inner_layout = QtWidgets.QVBoxLayout(inner)
        inner_layout.setSpacing(2)
        inner_layout.setContentsMargins(6, 4, 6, 4)

        self._checkboxes: list[tuple[QtWidgets.QCheckBox, str]] = []
        import os
        for vp in video_paths:
            name = os.path.basename(vp)
            cb = QtWidgets.QCheckBox(name, inner)
            cb.setChecked(True)
            inner_layout.addWidget(cb)
            self._checkboxes.append((cb, vp))

        inner_layout.addStretch()
        scroll.setWidget(inner)
        vg_layout.addWidget(scroll)
        root_layout.addWidget(self._videos_group)

        # ── Options d'export (identiques à ExportOptionsDialog) ────────────
        self.fps_group = QtWidgets.QGroupBox("", self)
        fps_layout = QtWidgets.QHBoxLayout(self.fps_group)
        self.fps_label = QtWidgets.QLabel("", self.fps_group)
        self.fps_spinbox = QtWidgets.QSpinBox(self.fps_group)
        self.fps_spinbox.setRange(1, 60)
        self.fps_spinbox.setValue(5)
        self.fps_spinbox.setSuffix(" fps")
        fps_layout.addWidget(self.fps_label)
        fps_layout.addWidget(self.fps_spinbox)
        root_layout.addWidget(self.fps_group)

        self.filters_group = QtWidgets.QGroupBox("", self)
        filters_layout = QtWidgets.QVBoxLayout(self.filters_group)
        self.check_he = QtWidgets.QCheckBox("", self.filters_group)
        self.check_dh = QtWidgets.QCheckBox("", self.filters_group)
        self.check_water = QtWidgets.QCheckBox("", self.filters_group)
        self.check_water.setEnabled(False)
        self.check_dh.toggled.connect(self.check_water.setEnabled)
        filters_layout.addWidget(self.check_he)
        filters_layout.addWidget(self.check_dh)
        filters_layout.addWidget(self.check_water)
        root_layout.addWidget(self.filters_group)

        self.chk_rectify = QtWidgets.QCheckBox("", self)
        self.chk_rectify.setEnabled(self.is_stereo)
        root_layout.addWidget(self.chk_rectify)

        self.chk_include_images = QtWidgets.QCheckBox("", self)
        self.chk_include_images.setChecked(True)
        self.chk_include_images.toggled.connect(self._on_include_images_toggled)
        root_layout.addWidget(self.chk_include_images)

        self.event_types_group = QtWidgets.QGroupBox("", self)
        et_layout = QtWidgets.QVBoxLayout(self.event_types_group)
        self.check_deployment = QtWidgets.QCheckBox("", self.event_types_group)
        self.check_deployment.setChecked(True)
        self.check_animal = QtWidgets.QCheckBox("", self.event_types_group)
        self.check_animal.setChecked(True)
        self.check_images_type = QtWidgets.QCheckBox("", self.event_types_group)
        self.check_images_type.setChecked(True)
        et_layout.addWidget(self.check_deployment)
        et_layout.addWidget(self.check_animal)
        et_layout.addWidget(self.check_images_type)
        root_layout.addWidget(self.event_types_group)

        self.range_group = QtWidgets.QGroupBox("", self)
        range_layout = QtWidgets.QVBoxLayout(self.range_group)
        self.radio_landing = QtWidgets.QRadioButton("", self.range_group)
        self.radio_landing.setChecked(True)
        self.radio_annotation = QtWidgets.QRadioButton("", self.range_group)
        range_layout.addWidget(self.radio_landing)
        range_layout.addWidget(self.radio_annotation)
        root_layout.addWidget(self.range_group)

        root_layout.addSpacing(8)

        # ── Boutons OK / Annuler ────────────────────────────────────────────
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            QtCore.Qt.Orientation.Horizontal, self,
        )
        self._export_btn = btn_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self._cancel_btn = btn_box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        root_layout.addWidget(btn_box)

        self._set_language(language)

    # ── helpers ────────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def _check_all(self):
        for cb, _ in self._checkboxes:
            cb.setChecked(True)

    def _uncheck_all(self):
        for cb, _ in self._checkboxes:
            cb.setChecked(False)

    def _on_include_images_toggled(self, checked: bool):
        self.fps_group.setEnabled(checked)
        self.filters_group.setEnabled(checked)
        self.chk_rectify.setEnabled(checked and self.is_stereo)

    def _on_accept(self):
        if not any(cb.isChecked() for cb, _ in self._checkboxes):
            QtWidgets.QMessageBox.warning(
                self,
                self.translate("Aucune vidéo sélectionnée", "No videos selected"),
                self.translate(
                    "Cochez au moins une vidéo avant de lancer l'export.",
                    "Please check at least one video before starting the export.",
                ),
            )
            return
        self.accept()

    def _set_language(self, language: str):
        self.current_language = language
        self.setWindowTitle(self.translate("Export en batch", "Batch Export"))
        self._videos_group.setTitle(
            self.translate("Vidéos à exporter", "Videos to export"))
        self._btn_all.setText(self.translate("Tout cocher", "Check all"))
        self._btn_none.setText(self.translate("Tout décocher", "Uncheck all"))
        self.fps_group.setTitle(
            self.translate("Configuration de la cadence (FPS)", "Framerate Configuration (FPS)"))
        self.fps_label.setText(
            self.translate("Images par seconde :", "Frames per second:"))
        self.filters_group.setTitle(
            self.translate("Filtres d'optimisation d'image", "Image Optimization Filters"))
        self.check_he.setText(
            self.translate("Égalisation d'histogramme (HE)", "Histogram Equalization (HE)"))
        self.check_dh.setText(
            self.translate("Suppression de la brume / flou (Dehaze)", "Haze / Blur Removal (Dehaze)"))
        self.check_water.setText(
            self.translate("Mode sous-marin (Option Dehaze)", "Underwater Mode (Dehaze Option)"))
        self.chk_rectify.setText(
            self.translate("Rectifier les images (Stéréo)", "Rectify images (Stereo)"))
        self.chk_rectify.setToolTip(self.translate(
            "Nécessite matrices.json et les fichiers .txt de synchro",
            "Requires matrices.json and the sync .txt files"))
        self.chk_include_images.setText(
            self.translate("Exporter le lot d'images", "Export image batch"))
        self.event_types_group.setTitle(
            self.translate("Types d'événements à exporter", "Event types to export"))
        self.check_deployment.setText(self.translate("Déploiement", "Deployment"))
        self.check_animal.setText(self.translate("Faune / Animal", "Fauna / Animal"))
        self.check_images_type.setText(
            self.translate("Images intéressantes", "Interesting Images"))
        self.range_group.setTitle(
            self.translate("Plage d'export", "Export range"))
        self.radio_landing.setText(
            self.translate("Atterrissage → Décollage", "Landing → Takeoff"))
        self.radio_annotation.setText(
            self.translate("Début annotation → Fin annotation", "Annotation start → Annotation end"))
        if self._export_btn:
            self._export_btn.setText(self.translate("Exporter", "Export"))
        if self._cancel_btn:
            self._cancel_btn.setText(self.translate("Annuler", "Cancel"))

    # ── résultats ──────────────────────────────────────────────────────────

    def get_selected_video_paths(self) -> list[str]:
        return [vp for cb, vp in self._checkboxes if cb.isChecked()]

    def get_processing_options(self) -> dict:
        selected_categories = [
            cat for cat, chk in [
                ("events_motor", self.check_deployment),
                ("events_animal", self.check_animal),
                ("events_interesting_images", self.check_images_type),
            ]
            if chk.isChecked()
        ]
        return {
            "target_fps": self.fps_spinbox.value(),
            "apply_he": self.check_he.isChecked(),
            "apply_dh": self.check_dh.isChecked(),
            "is_water": self.check_water.isEnabled() and self.check_water.isChecked(),
            "apply_rectify": self.chk_rectify.isEnabled() and self.chk_rectify.isChecked(),
            "include_images": self.chk_include_images.isChecked(),
            "event_categories": selected_categories,
            "export_range": "annotation" if self.radio_annotation.isChecked() else "landing_takeoff",
        }
