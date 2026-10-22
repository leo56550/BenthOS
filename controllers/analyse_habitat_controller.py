from PyQt6 import QtWidgets, QtCore


class AnalyseHabitatController(QtCore.QObject):
    """Contrôleur de la page Analyse Habitat (squelette)."""

    def __init__(self, page: QtWidgets.QWidget):
        super().__init__()
        self._page = page
        self._language = 'fr'
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self._page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        self._lbl = QtWidgets.QLabel(self._tr("Analyse Habitat", "Habitat Analysis"))
        self._lbl.setStyleSheet(
            "color: #7ec8e3; font-size: 22px; font-weight: bold;"
            " font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
        )
        self._lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._lbl)

        placeholder = QtWidgets.QLabel(
            self._tr("Page en cours de développement.", "Page under development."))
        placeholder.setStyleSheet(
            "color: #4a7090; font-size: 14px;"
            " font-family: 'Segoe UI', sans-serif;"
        )
        layout.addWidget(placeholder)
        layout.addStretch()

        self._page.setStyleSheet("background-color: #0d1e2e;")

    def _tr(self, fr: str, en: str) -> str:
        return fr if self._language == 'fr' else en

    def set_language(self, language: str):
        self._language = language
        self._lbl.setText(self._tr("Analyse Habitat", "Habitat Analysis"))
