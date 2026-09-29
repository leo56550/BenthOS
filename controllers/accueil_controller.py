from PyQt6 import QtWidgets, QtCore
from controllers.campagne_dialog import CampagneDialog

_BTN_STYLE_MAIN = """
QPushButton {
    background-color: #2778a2;
    color: white;
    font-weight: bold;
    border-radius: 4px;
    padding: 6px 15px;
    font-size: 12px;
    border: none;
}
QPushButton:hover { background-color: #3290C2; }
"""

_BTN_STYLE_SECONDARY = """
QPushButton {
    background-color: #162433;
    color: #a0c4d8;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
    border: 1px solid #1e3448;
    border-radius: 4px;
    padding: 4px 14px;
    min-width: 160px;
}
QPushButton:hover { background-color: #1e3448; }
"""


class AccueilController:
    """Contrôleur de la page Accueil — ouvre le dialog unifié de campagne."""

    def __init__(self, page_widget, open_campaign_callback,
                 recent_callback=None, open_video_callback=None):
        self.widget = page_widget
        self.open_campaign_callback = open_campaign_callback
        self.current_language = 'fr'
        self._last_campaign: str = ""
        self._last_working_dir: str = ""

        self.btn_open = self.widget.findChild(QtWidgets.QPushButton, "btn_ouvrir_campagne")
        if self.btn_open:
            self.btn_open.clicked.connect(self.open_campaign_dialog)

        # ── Boutons secondaires ajoutés dynamiquement sous le bouton principal ──
        self.btn_recent: QtWidgets.QPushButton | None = None
        self.btn_video: QtWidgets.QPushButton | None = None
        self._add_secondary_buttons(recent_callback, open_video_callback)

        self.set_language(self.current_language)

    def _add_secondary_buttons(self, recent_callback, open_video_callback):
        """Insère 'Campagnes récentes' et 'Ouvrir vidéo' juste après btn_ouvrir_campagne."""
        if self.btn_open is None:
            return
        frame = self.widget.findChild(QtWidgets.QFrame, "frame")
        vbox = frame.layout() if frame else None
        if vbox is None:
            return

        # Trouver la position du bouton principal dans le layout
        btn_idx = -1
        for i in range(vbox.count()):
            item = vbox.itemAt(i)
            if item and item.widget() is self.btn_open:
                btn_idx = i
                break
        if btn_idx == -1:
            return

        # Créer les boutons secondaires
        self.btn_recent = QtWidgets.QPushButton("Campagnes récentes")
        self.btn_recent.setObjectName("btn_recent_campaigns_accueil")
        self.btn_recent.setStyleSheet(_BTN_STYLE_SECONDARY)
        self.btn_recent.setMaximumWidth(220)
        if recent_callback:
            self.btn_recent.clicked.connect(recent_callback)

        self.btn_video = QtWidgets.QPushButton("Ouvrir vidéo")
        self.btn_video.setObjectName("btn_open_video_accueil")
        self.btn_video.setStyleSheet(_BTN_STYLE_SECONDARY)
        self.btn_video.setMaximumWidth(220)
        if open_video_callback:
            self.btn_video.clicked.connect(open_video_callback)

        # Insérer après btn_ouvrir_campagne (indices btn_idx+1, btn_idx+2)
        vbox.insertWidget(btn_idx + 1, self.btn_recent, 0,
                          QtCore.Qt.AlignmentFlag.AlignHCenter)
        vbox.insertWidget(btn_idx + 2, self.btn_video, 0,
                          QtCore.Qt.AlignmentFlag.AlignHCenter)

    # ── Language ────────────────────────────────────────────────────────────

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        if self.btn_open:
            self.btn_open.setText(self.translate("Ouvrir campagne", "Open campaign"))
        if self.btn_recent:
            self.btn_recent.setText(
                self.translate("Campagnes récentes", "Recent campaigns"))
        if self.btn_video:
            self.btn_video.setText(self.translate("Ouvrir vidéo", "Open video"))

    # ── Dialog ──────────────────────────────────────────────────────────────

    def open_campaign_dialog(self):
        """Ouvre le dialog unifié (dérusher + dossier campagne + répertoire de travail)."""
        dlg = CampagneDialog(
            parent=self.widget,
            language=self.current_language,
            last_campaign=self._last_campaign,
            last_working_dir=self._last_working_dir,
        )
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        self._last_campaign = dlg.campaign_folder
        self._last_working_dir = dlg.working_dir
        self.open_campaign_callback(dlg.derusher_name, dlg.campaign_folder, dlg.working_dir)

    # ── Compat stubs (appelés depuis app_controller) ────────────────────────

    def show_working_dir_button(self):
        """Obsolète — conservé pour compatibilité."""

    def confirm_working_dir(self, path: str):
        """Obsolète — conservé pour compatibilité."""
