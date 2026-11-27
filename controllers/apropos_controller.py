import os
import subprocess

from PyQt6 import QtWidgets, QtCore, QtGui
try:
    from PyQt6.QtSvgWidgets import QSvgWidget
    _HAS_SVG = True
except ImportError:
    _HAS_SVG = False

APP_VERSION = "1.0.0"

_CONTACT_EMAIL = "kosmos@imt-atlantique.fr"
_CONTACT_GITHUB = "https://github.com/leo56550/BenthOS"


def _get_last_update() -> str:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format:%d/%m/%Y"],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        date = r.stdout.strip()
        return date if date else "—"
    except Exception:
        return "—"

_FEATURES = [
    ("🗂", "Validation",      "Dérusher les vidéos, saisir l'ardoise, gérer l'exploitabilité",
                              "Review videos, enter board data, manage exploitability"),
    ("🎬", "Événements",      "Annoter les rotations moteur, animaux et images sur la timeline",
                              "Annotate motor rotations, animals and images on the timeline"),
    ("✅", "Qualification",   "Trier les vidéos à garder ou à jeter, vue secteur en miniatures",
                              "Sort videos to keep or discard, sector view with thumbnails"),
    ("🗺", "Carte",           "Visualiser les points GPS, cliquer pour sélectionner une vidéo",
                              "Visualize GPS points, click to select a video"),
    ("📊", "Avancement",      "Suivre la progression de la campagne et exporter des rapports",
                              "Track campaign progress and export reports"),
]

_TECH_STACK = [
    ("PyQt6",      "Interface graphique — widgets, signaux/slots, MVC",
                   "Graphical interface — widgets, signals/slots, MVC"),
    ("OpenCV",     "Lecture vidéo, extraction de frames, traitement d'image",
                   "Video reading, frame extraction, image processing"),
    ("Matplotlib", "Histogrammes, graphiques, export PDF",
                   "Histograms, charts, PDF export"),
    ("Folium",     "Carte interactive Leaflet (GPS tracks)",
                   "Interactive Leaflet map (GPS tracks)"),
    ("pandas",     "Lecture des fichiers CSV de télémétrie",
                   "Reading telemetry CSV files"),
    ("paramiko",   "Transfert SFTP depuis la carte SD KOSMOS",
                   "SFTP transfer from the KOSMOS SD card"),
    ("NumPy",      "Calculs vectorisés (histogramme, luminosité)",
                   "Vectorized computations (histogram, brightness)"),
]

_TEAM = [
    ("Léo Bultel",                          "Développement logiciel",         "Software development",
                                             "IMT Atlantique"),
    ("Équipe KOSMOS",                       "Conception système",             "System design",
                                             "IMT Atlantique"),
    ("Institut Mines-Télécom Atlantique",   "Partenaire scientifique",        "Scientific partner",
                                             "Brest, France"),
]

_BG       = "#0d1b2a"
_BG2      = "#0f2030"
_BG3      = "#152535"
_ACCENT   = "#2778A2"
_ACCENT2  = "#1a5070"
_SALMON   = "#F2BFB4"
_CYAN     = "#7ec8e3"
_TEXT     = "#d4e8f5"
_MUTED    = "#5a7a8a"
_SUBTLE   = "#a0c4d8"


class AProposController:
    """Contrôleur de la page À propos."""

    def __init__(self, widget: QtWidgets.QWidget, *args, **kwargs):
        self.widget = widget
        self.current_language = 'fr'
        self._build_ui()

    def translate(self, fr: str, en: str) -> str:
        return fr if self.current_language == 'fr' else en

    def set_language(self, language: str):
        self.current_language = language
        self._build_ui()

    # ── Construction ────────────────────────────────────────────────────────────

    def _build_ui(self):
        old = self.widget.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QtWidgets.QWidget().setLayout(old)

        root = QtWidgets.QVBoxLayout(self.widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QtWidgets.QWidget()
        container.setStyleSheet(f"background-color: {_BG};")
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll.setWidget(container)
        root.addWidget(scroll)

        layout.addWidget(self._hero_banner())
        layout.addWidget(self._features_section())
        layout.addWidget(self._tech_section())
        layout.addWidget(self._team_section())
        layout.addWidget(self._license_section())
        layout.addWidget(self._footer())

    # ── Hero ────────────────────────────────────────────────────────────────────

    def _hero_banner(self) -> QtWidgets.QWidget:
        banner = QtWidgets.QWidget()
        banner.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 #0a1520, stop:0.5 #10243a, stop:1 #0d1b2a);"
            f" border-bottom: 1px solid {_ACCENT2};"
        )
        banner.setMinimumHeight(220)

        outer = QtWidgets.QHBoxLayout(banner)
        outer.setContentsMargins(60, 40, 60, 40)
        outer.setSpacing(0)

        # ── Logo BenthOS (SVG) ───────────────────────────────────────────────
        benthos_svg = os.path.join(os.path.dirname(__file__), '..', 'img', 'logo_benthos.svg')
        if _HAS_SVG and os.path.isfile(benthos_svg):
            logo_widget = QSvgWidget(benthos_svg)
            logo_widget.setFixedSize(180, 180)
            logo_widget.setStyleSheet("background: transparent;")
            outer.addWidget(logo_widget)
        else:
            logo_lbl = QtWidgets.QLabel("B")
            logo_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            logo_lbl.setFixedSize(180, 180)
            logo_lbl.setStyleSheet(f"color: {_ACCENT}; font-size: 56px; font-weight: bold;")
            outer.addWidget(logo_lbl)

        outer.addSpacing(36)

        # Texte central
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(6)
        col.addStretch()

        t_app = QtWidgets.QLabel("BenthOS")
        t_app.setStyleSheet(
            f"color: {_SALMON}; font-size: 34px; font-weight: 900;"
            f" font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
            f" background: transparent; letter-spacing: 1px;"
        )

        t_sub = QtWidgets.QLabel(self.translate(
            "Interface de qualification et d'analyse des vidéos sous-marines KOSMOS",
            "Qualification and analysis interface for KOSMOS underwater videos",
        ))
        t_sub.setStyleSheet(
            f"color: {_CYAN}; font-size: 13px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        t_sub.setWordWrap(True)

        t_desc = QtWidgets.QLabel(self.translate(
            "Ouvrez une campagne, visionnez, annotez et exportez vos données terrain.",
            "Open a campaign, review, annotate and export your field data.",
        ))
        t_desc.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        t_desc.setWordWrap(True)

        # "by KOSMOS" avec logo BenthOS en bas à droite du texte
        by_row = QtWidgets.QHBoxLayout()
        by_row.setSpacing(6)
        benthos_small = os.path.join(os.path.dirname(__file__), '..', 'img', 'logo_benthos.svg')
        if _HAS_SVG and os.path.isfile(benthos_small):
            small_svg = QSvgWidget(benthos_small)
            small_svg.setFixedSize(20, 20)
            small_svg.setStyleSheet("background: transparent;")
            by_row.addWidget(small_svg)
        elif os.path.isfile(benthos_small):
            kosmos_lbl = QtWidgets.QLabel()
            pix = QtGui.QPixmap(benthos_small).scaled(
                20, 20,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            if not pix.isNull():
                kosmos_lbl.setPixmap(pix)
                kosmos_lbl.setFixedSize(20, 20)
                kosmos_lbl.setStyleSheet("background: transparent;")
                by_row.addWidget(kosmos_lbl)
        by_lbl = QtWidgets.QLabel("by KOSMOS")
        by_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        by_row.addWidget(by_lbl)
        by_row.addStretch()

        col.addWidget(t_app)
        col.addWidget(t_sub)
        col.addSpacing(6)
        col.addWidget(t_desc)
        col.addSpacing(10)
        col.addLayout(by_row)
        col.addStretch()

        outer.addLayout(col, stretch=1)
        outer.addSpacing(32)

        # Badges droite
        badges = QtWidgets.QVBoxLayout()
        badges.setSpacing(8)
        badges.addStretch()
        for label, value, color in [
            (self.translate("Version", "Version"), APP_VERSION, _SALMON),
            (self.translate("Mise à jour", "Last update"), _get_last_update(), _SUBTLE),
            ("Python", "3.11+", _CYAN),
            ("PyQt6", "6.x", _CYAN),
            (self.translate("Plateforme", "Platform"), "Windows", _SUBTLE),
        ]:
            badges.addWidget(self._pill(label, value, color))
        badges.addStretch()

        outer.addLayout(badges)
        return banner

    def _pill(self, label: str, value: str, color: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            f"background-color: {_BG3}; border: 1px solid {_ACCENT2};"
            f" border-radius: 6px;"
        )
        h = QtWidgets.QHBoxLayout(frame)
        h.setContentsMargins(12, 5, 12, 5)
        h.setSpacing(10)
        l1 = QtWidgets.QLabel(label)
        l1.setStyleSheet(f"color: {_MUTED}; font-size: 10px; background: transparent;")
        l2 = QtWidgets.QLabel(value)
        l2.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold; background: transparent;")
        h.addWidget(l1)
        h.addWidget(l2)
        return frame

    # ── Fonctionnalités ─────────────────────────────────────────────────────────

    def _features_section(self) -> QtWidgets.QWidget:
        section = QtWidgets.QWidget()
        section.setStyleSheet(f"background-color: {_BG};")
        outer = QtWidgets.QVBoxLayout(section)
        outer.setContentsMargins(60, 36, 60, 36)
        outer.setSpacing(16)

        outer.addWidget(self._section_title(
            self.translate("Fonctionnalités", "Features")
        ))

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(12)

        for i, (icon, name, desc_fr, desc_en) in enumerate(_FEATURES):
            card = self._feature_card(icon, name, self.translate(desc_fr, desc_en))
            grid.addWidget(card, i // 3, i % 3)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        outer.addLayout(grid)
        return section

    def _feature_card(self, icon: str, name: str, desc: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            f"background-color: {_BG2}; border: 1px solid #1e3448;"
            f" border-radius: 10px;"
        )
        frame.setMinimumHeight(100)
        v = QtWidgets.QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)

        h = QtWidgets.QHBoxLayout()
        h.setSpacing(10)
        lbl_icon = QtWidgets.QLabel(icon)
        lbl_icon.setStyleSheet(f"font-size: 20px; background: transparent; color: {_TEXT};")
        lbl_name = QtWidgets.QLabel(name)
        lbl_name.setStyleSheet(
            f"color: {_SALMON}; font-size: 13px; font-weight: bold;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        h.addWidget(lbl_icon)
        h.addWidget(lbl_name)
        h.addStretch()
        v.addLayout(h)

        lbl_desc = QtWidgets.QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        v.addWidget(lbl_desc)
        v.addStretch()
        return frame

    # ── Technologies ────────────────────────────────────────────────────────────

    def _tech_section(self) -> QtWidgets.QWidget:
        section = QtWidgets.QWidget()
        section.setStyleSheet(f"background-color: {_BG3}; border-top: 1px solid #1e3448; border-bottom: 1px solid #1e3448;")
        outer = QtWidgets.QVBoxLayout(section)
        outer.setContentsMargins(60, 36, 60, 36)
        outer.setSpacing(16)

        outer.addWidget(self._section_title("Technologies"))

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(10)

        for row, (lib, desc_fr, desc_en) in enumerate(_TECH_STACK):
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color: {_ACCENT}; font-size: 8px; background: transparent;")
            dot.setFixedWidth(16)
            dot.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)

            l_lib = QtWidgets.QLabel(lib)
            l_lib.setStyleSheet(
                f"color: {_CYAN}; font-weight: bold; font-size: 12px;"
                f" font-family: 'Segoe UI', sans-serif; background: transparent;"
            )
            l_lib.setFixedWidth(100)

            l_desc = QtWidgets.QLabel(self.translate(desc_fr, desc_en))
            l_desc.setStyleSheet(
                f"color: {_SUBTLE}; font-size: 11px;"
                f" font-family: 'Segoe UI', sans-serif; background: transparent;"
            )

            grid.addWidget(dot,   row, 0)
            grid.addWidget(l_lib, row, 1)
            grid.addWidget(l_desc, row, 2)

        grid.setColumnStretch(2, 1)
        outer.addLayout(grid)
        return section

    # ── Équipe ──────────────────────────────────────────────────────────────────

    def _team_section(self) -> QtWidgets.QWidget:
        section = QtWidgets.QWidget()
        section.setStyleSheet(f"background-color: {_BG};")
        outer = QtWidgets.QVBoxLayout(section)
        outer.setContentsMargins(60, 36, 60, 36)
        outer.setSpacing(16)

        outer.addWidget(self._section_title(
            self.translate("Équipe & Institution", "Team & Institution")
        ))

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(16)

        for name, role_fr, role_en, institution in _TEAM:
            cards.addWidget(self._team_card(name, self.translate(role_fr, role_en), institution))

        cards.addStretch()
        outer.addLayout(cards)
        return section

    def _team_card(self, name: str, role: str, institution: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setFixedWidth(240)
        frame.setStyleSheet(
            f"background-color: {_BG2}; border: 1px solid #1e3448; border-radius: 10px;"
        )
        v = QtWidgets.QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(4)

        avatar = QtWidgets.QLabel("👤")
        avatar.setStyleSheet(f"font-size: 26px; background: transparent; color: {_TEXT};")
        avatar.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        l_name = QtWidgets.QLabel(name)
        l_name.setWordWrap(True)
        l_name.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )

        l_role = QtWidgets.QLabel(role)
        l_role.setWordWrap(True)
        l_role.setStyleSheet(
            f"color: {_CYAN}; font-size: 11px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )

        l_inst = QtWidgets.QLabel(institution)
        l_inst.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )

        v.addWidget(avatar)
        v.addSpacing(4)
        v.addWidget(l_name)
        v.addWidget(l_role)
        v.addSpacing(4)
        v.addWidget(l_inst)
        v.addStretch()
        return frame

    # ── Licence & Contact ───────────────────────────────────────────────────────

    def _license_section(self) -> QtWidgets.QWidget:
        section = QtWidgets.QWidget()
        section.setStyleSheet(
            f"background-color: {_BG2}; border-top: 1px solid #1e3448;"
            f" border-bottom: 1px solid #1e3448;"
        )
        outer = QtWidgets.QVBoxLayout(section)
        outer.setContentsMargins(60, 36, 60, 36)
        outer.setSpacing(24)

        outer.addWidget(self._section_title(
            self.translate("Licence & Contact", "License & Contact")
        ))

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(40)

        # ── Badge CC-BY-NC-SA ────────────────────────────────────────────────
        lic_col = QtWidgets.QVBoxLayout()
        lic_col.setSpacing(10)

        # Logo CC-BY-NC-SA : 4 pastilles colorées
        badge_row = QtWidgets.QHBoxLayout()
        badge_row.setSpacing(4)
        badge_row.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        for text, bg, fg in [
            ("CC",  "#000000", "#ffffff"),
            ("BY",  "#ffb300", "#000000"),
            ("NC",  "#e53935", "#ffffff"),
            ("SA",  "#1e88e5", "#ffffff"),
        ]:
            pill = QtWidgets.QLabel(text)
            pill.setFixedSize(34, 22)
            pill.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            pill.setStyleSheet(
                f"background-color: {bg}; color: {fg};"
                f" font-size: 10px; font-weight: bold;"
                f" font-family: 'Segoe UI', sans-serif;"
                f" border-radius: 4px;"
            )
            badge_row.addWidget(pill)
        badge_row.addStretch()

        lic_title = QtWidgets.QLabel("CC BY-NC-SA 4.0")
        lic_title.setStyleSheet(
            f"color: {_SALMON}; font-size: 13px; font-weight: bold;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )

        lic_desc = QtWidgets.QLabel(self.translate(
            "Ce logiciel est distribué sous licence\n"
            "Creative Commons Attribution – Non Commercial – Share Alike 4.0.\n"
            "Utilisation libre à des fins non commerciales, avec attribution\n"
            "et redistribution sous la même licence.",
            "This software is distributed under the\n"
            "Creative Commons Attribution – Non Commercial – Share Alike 4.0 license.\n"
            "Free to use for non-commercial purposes, with attribution\n"
            "and redistribution under the same license.",
        ))
        lic_desc.setStyleSheet(
            f"color: {_SUBTLE}; font-size: 11px;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        lic_desc.setWordWrap(True)

        lic_col.addLayout(badge_row)
        lic_col.addWidget(lic_title)
        lic_col.addWidget(lic_desc)
        lic_col.addStretch()

        # ── Contact ──────────────────────────────────────────────────────────
        contact_col = QtWidgets.QVBoxLayout()
        contact_col.setSpacing(10)

        contact_title = QtWidgets.QLabel(self.translate("Contact", "Contact"))
        contact_title.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f" font-family: 'Segoe UI', sans-serif; background: transparent;"
        )

        for icon, label, value in [
            ("✉", self.translate("E-mail", "E-mail"), _CONTACT_EMAIL),
            ("⌂", "GitHub", _CONTACT_GITHUB),
        ]:
            item_row = QtWidgets.QHBoxLayout()
            item_row.setSpacing(8)
            lbl_icon = QtWidgets.QLabel(icon)
            lbl_icon.setStyleSheet(
                f"color: {_ACCENT}; font-size: 14px; background: transparent;"
            )
            lbl_icon.setFixedWidth(20)
            lbl_key = QtWidgets.QLabel(f"{label} :")
            lbl_key.setStyleSheet(
                f"color: {_MUTED}; font-size: 11px;"
                f" font-family: 'Segoe UI', sans-serif; background: transparent;"
            )
            lbl_key.setFixedWidth(60)
            lbl_val = QtWidgets.QLabel(value)
            lbl_val.setStyleSheet(
                f"color: {_CYAN}; font-size: 11px;"
                f" font-family: 'Segoe UI', sans-serif; background: transparent;"
            )
            lbl_val.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            item_row.addWidget(lbl_icon)
            item_row.addWidget(lbl_key)
            item_row.addWidget(lbl_val)
            item_row.addStretch()
            contact_col.addLayout(item_row)

        contact_col.insertWidget(0, contact_title)
        contact_col.addStretch()

        row.addLayout(lic_col, stretch=2)
        row.addLayout(contact_col, stretch=1)
        outer.addLayout(row)
        return section

    # ── Footer ──────────────────────────────────────────────────────────────────

    def _footer(self) -> QtWidgets.QWidget:
        footer = QtWidgets.QWidget()
        footer.setStyleSheet(
            f"background-color: #08131e; border-top: 1px solid #1e3448;"
        )
        h = QtWidgets.QHBoxLayout(footer)
        h.setContentsMargins(60, 16, 60, 16)
        h.setSpacing(0)

        lbl = QtWidgets.QLabel(
            "© 2026 Institut Mines-Télécom Atlantique — Projet KOSMOS"
        )
        lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
            f" background: transparent;"
        )

        lbl_v = QtWidgets.QLabel(f"v{APP_VERSION}")
        lbl_v.setStyleSheet(
            f"color: #2a4057; font-size: 10px; font-family: 'Segoe UI', sans-serif;"
            f" background: transparent;"
        )

        h.addWidget(lbl)
        h.addStretch()
        h.addWidget(lbl_v)
        return footer

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _section_title(self, text: str) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(
            f"color: {_SALMON}; font-size: 15px; font-weight: bold;"
            f" font-family: 'Segoe UI Black', 'Segoe UI', sans-serif;"
            f" background: transparent;"
        )
        v.addWidget(lbl)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setMaximumHeight(1)
        line.setStyleSheet(f"background-color: {_ACCENT}; border: none;")
        v.addWidget(line)
        return w
