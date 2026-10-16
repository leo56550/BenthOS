import os
import logging

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

_LOG = logging.getLogger(__name__)

# Dictionnaires ArUco testés dans l'ordre le plus courant pour les ardoises terrain.
# Les marqueurs physiques sont DICT_4X4_50 ID=0, mais un marqueur dégradé/lointain peut
# être détecté dans un autre dictionnaire compatible — on garde donc les 5 pour maximiser le taux.
_ARUCO_DICT_IDS = [
    cv2.aruco.DICT_4X4_100,
    cv2.aruco.DICT_4X4_50,
    cv2.aruco.DICT_5X5_100,
    cv2.aruco.DICT_6X6_250,
    cv2.aruco.DICT_4X4_1000,
]

# Largeur cible pour la détection
_DETECT_WIDTH = 640

# CLAHE : égalisation locale du contraste — fait ressortir les coins du marqueur
# pour les vidéos à faible contraste (contre-jour, eau trouble).
# clipLimit=2.0 évite de sur-égaliser les marqueurs déjà nets.
_CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def _make_detectors():
    """Paramètres permissifs pour les marqueurs lointains/flous/contre-jour."""
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 53
    params.adaptiveThreshWinSizeStep = 10
    params.adaptiveThreshConstant = 7
    params.minMarkerPerimeterRate = 0.02
    params.maxMarkerPerimeterRate = 4.0
    params.polygonalApproxAccuracyRate = 0.05
    params.errorCorrectionRate = 0.9
    return [
        (d, cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(d), params))
        for d in _ARUCO_DICT_IDS
    ]


def _detect_in_frame(frame, detectors: list, target_width: int):
    """Redimensionne et détecte le marqueur ArUco. Retourne (dict_id, ids) ou (None, None)."""
    h, w = frame.shape[:2]
    if w > target_width:
        scale = target_width / w
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    gray = _CLAHE.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    for dict_id, detector in detectors:
        _, ids, _ = detector.detectMarkers(gray)
        if ids is not None and len(ids) > 0:
            return dict_id, ids.flatten().tolist()
    return None, None


def detect_aruco_in_video(video_path: str,
                           max_scan_seconds: float = 60.0,
                           step_frames: int = 10) -> dict | None:
    """Scanne les premières max_scan_seconds d'une vidéo à la recherche d'un marker ArUco.

    Utilise des paramètres permissifs pour maximiser la détection, mais confirme chaque
    candidat sur la frame suivante pour éliminer les faux positifs (artifacts 1 frame).

    Retourne {"frame_ms", "frame_number", "marker_ids", "dict_id"} ou None.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _LOG.warning("[ARUCO] Impossible d'ouvrir : %s", os.path.basename(video_path))
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames = min(total_frames, int(max_scan_seconds * fps))
    detectors = _make_detectors()
    name = os.path.basename(video_path)

    # Sauter la 1ère seconde : frames noires d'intro compressées
    # La confirmation sur 5 frames suffit à filtrer les faux positifs restants
    start_frame = min(int(fps * 1), max_frames - 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_num = start_frame

    _LOG.info("[ARUCO] Scan %-30s | %d frames max (pas=%d)", name, max_frames, step_frames)

    while frame_num < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        dict_id, ids = _detect_in_frame(frame, detectors, _DETECT_WIDTH)
        if ids is not None:
            # Confirmation sur 5 frames consécutives — une vraie ardoise est tenue
            # plusieurs secondes, un artefact de compression disparaît en 1-2 frames.
            # Les faux positifs de taille insuffisante sont déjà filtrés dans _detect_in_frame.
            ok = 0
            for _ in range(5):
                ret_c, frame_c = cap.read()
                if not ret_c:
                    ok += 1
                    break
                _, ids_c = _detect_in_frame(frame_c, detectors, _DETECT_WIDTH)
                if ids_c is not None:
                    ok += 1
                else:
                    break
            confirmed = ok >= 5

            if confirmed:
                # Affinage : rembobiner step_frames en arrière et avancer frame par frame.
                # On lit la position réelle depuis OpenCV (cap.get) car cap.set sur H.264
                # atterrit sur le keyframe le plus proche, pas la frame exacte demandée.
                # POS_MSEC avant cap.read() donne l'horodatage exact de la frame à lire.
                refine_start = max(start_frame, frame_num - step_frames)
                cap.set(cv2.CAP_PROP_POS_FRAMES, refine_start)
                exact_frame = frame_num
                ms = int((exact_frame / fps) * 1000)
                while True:
                    actual_fn = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    actual_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                    if actual_fn > frame_num:
                        break
                    ret_r, frame_r = cap.read()
                    if not ret_r:
                        break
                    _, ids_r = _detect_in_frame(frame_r, detectors, _DETECT_WIDTH)
                    if ids_r is not None:
                        exact_frame = actual_fn
                        ms = actual_ms
                        break
                result = {
                    "frame_number": exact_frame,
                    "frame_ms": ms,
                    "marker_ids": ids,
                    "dict_id": dict_id,
                }
                _LOG.info(
                    "[ARUCO] ✓ %-30s | marker(s) %s à frame %d (%d ms) [affiné depuis %d]",
                    name, ids, exact_frame, ms, frame_num,
                )
                print(f"[ARUCO] QR code détecté à : frame {exact_frame}  ({name})")
                cap.release()
                return result
            else:
                _LOG.debug("[ARUCO] faux positif écarté à frame %d (%s)", frame_num, name)
            # Continuer à frame_num + step_frames (la frame2 lue est perdue, on re-seek)
            frame_num += step_frames
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            continue

        skipped = 0
        while skipped < step_frames - 1:
            if not cap.grab():
                break
            skipped += 1
        frame_num += step_frames

    cap.release()
    _LOG.info("[ARUCO] ✗ %-30s | aucun marker détecté", name)
    print(f"[ARUCO] QR code non détecté  ({name})")
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
