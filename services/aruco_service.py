import os
import logging

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

_LOG = logging.getLogger(__name__)

# Dictionnaires ArUco testés dans l'ordre le plus courant pour les ardoises terrain
_ARUCO_DICT_IDS = [
    cv2.aruco.DICT_4X4_100,
    cv2.aruco.DICT_4X4_50,
    cv2.aruco.DICT_5X5_100,
    cv2.aruco.DICT_6X6_250,
    cv2.aruco.DICT_4X4_1000,
]

# Largeur cible pour la détection — les marqueurs ArUco sont détectables même en basse résolution.
# Réduire à 480px sur une vidéo 1080p → ~10× moins de pixels à analyser.
_DETECT_WIDTH = 640


def _make_detectors():
    """Crée les détecteurs ArUco avec les paramètres par défaut OpenCV."""
    params = cv2.aruco.DetectorParameters()
    return [
        (d, cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(d), params))
        for d in _ARUCO_DICT_IDS
    ]


def detect_aruco_in_video(video_path: str,
                           max_scan_seconds: float = 60.0,
                           step_frames: int = 25) -> dict | None:
    """Scanne les premières max_scan_seconds d'une vidéo à la recherche d'un marker ArUco.

    Optimisations :
    - cap.grab() pour sauter les frames sans les décoder
    - resize à _DETECT_WIDTH avec INTER_AREA (meilleur rendu pour downscale)
    - paramètres détecteur permissifs pour images dégradées

    Retourne {"frame_ms", "frame_number", "marker_ids", "dict_id"} au premier marker trouvé,
    ou None si aucun marker n'est détecté.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _LOG.warning("[ARUCO] Impossible d'ouvrir : %s", os.path.basename(video_path))
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames = min(total_frames, int(max_scan_seconds * fps))

    detectors = _make_detectors()

    _LOG.info(
        "[ARUCO] Début scan %-30s | %d frames max (pas=%d, %.1f fps)",
        os.path.basename(video_path), max_frames, step_frames, fps,
    )

    frame_num = 0
    while frame_num < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        # INTER_AREA = meilleur algorithme pour réduire (préserve les bords nets)
        h, w = frame.shape[:2]
        if w > _DETECT_WIDTH:
            scale = _DETECT_WIDTH / w
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for dict_id, detector in detectors:
            corners, ids, _ = detector.detectMarkers(gray)
            if ids is not None and len(ids) > 0:
                ms = int((frame_num / fps) * 1000)
                result = {
                    "frame_number": frame_num,
                    "frame_ms": ms,
                    "marker_ids": ids.flatten().tolist(),
                    "dict_id": dict_id,
                }
                _LOG.info(
                    "[ARUCO] ✓ %-30s | marker(s) %s à frame %d (%d ms)",
                    os.path.basename(video_path), result["marker_ids"], frame_num, ms,
                )
                cap.release()
                return result

        # Sauter les (step_frames - 1) frames suivantes sans les décoder
        skipped = 0
        while skipped < step_frames - 1:
            if not cap.grab():
                break
            skipped += 1

        frame_num += step_frames

    cap.release()
    _LOG.info(
        "[ARUCO] ✗ %-30s | aucun marker dans les %.0f premières secondes",
        os.path.basename(video_path), max_scan_seconds,
    )
    return None


class ArucoWorker(QThread):
    """Thread background : détecte les markers ArUco dans toutes les vidéos d'une campagne."""

    video_scanned = pyqtSignal(str, object)   # (video_path, result | None)
    scan_complete = pyqtSignal(int, int)       # (found_count, total_count)

    def __init__(self, video_paths: list, parent=None):
        super().__init__(parent)
        self._video_paths = list(video_paths)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        total = len(self._video_paths)
        found = 0
        _LOG.info("[ARUCO] Lancement scan de %d vidéo(s)", total)
        print(f"[ARUCO] Lancement scan de {total} vidéo(s)…")

        for vp in self._video_paths:
            if self._abort:
                _LOG.info("[ARUCO] Scan interrompu par abort()")
                print("[ARUCO] Scan interrompu")
                break
            result = detect_aruco_in_video(vp)
            self.video_scanned.emit(vp, result)
            if result:
                found += 1
                print(
                    f"[ARUCO] ✓ {os.path.basename(vp)} "
                    f"→ marker(s) {result['marker_ids']} à {result['frame_ms']} ms"
                )
            else:
                print(f"[ARUCO] ✗ {os.path.basename(vp)} → aucun marker")

        self.scan_complete.emit(found, total)
        print(f"[ARUCO] Scan terminé : {found}/{total} vidéo(s) avec marker ArUco")
