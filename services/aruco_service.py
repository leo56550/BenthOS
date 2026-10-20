import os
import logging
import math

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

_LOG = logging.getLogger(__name__)

# Dictionnaires ArUco testés dans l'ordre le plus courant pour les ardoises terrain.
# Les marqueurs physiques sont DICT_4X4_50 ID=0, mais un marqueur dégradé/lointain peut
# être détecté dans un autre dictionnaire compatible — on garde donc les 5 pour maximiser le taux.
_ARUCO_DICT_IDS = [
    cv2.aruco.DICT_4X4_50,
    cv2.aruco.DICT_4X4_100,
]

# Largeur cible pour la détection
_DETECT_WIDTH = 640

# Périmètre minimum (en pixels de l'image originale) pour accepter un marqueur.
# Filtre les détections dégénérées (marqueurs 1-2 px, bruit CLAHE, artefacts de compression).
# Un vrai marqueur ArUco sur une ardoise occupe typiquement > 200 px de périmètre.
_MIN_MARKER_PERIMETER_PX = 100.0

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
    """Redimensionne et détecte le marqueur ArUco.
    Retourne (dict_id, ids, corners_orig) ou (None, None, None).
    Parmi tous les marqueurs valides trouvés, retourne celui au PÉRIMÈTRE LE PLUS GRAND :
    le vrai ArUco sur l'ardoise est toujours plus grand que les faux positifs de fond.
    corners_orig : liste de 4 points [x, y] dans les coordonnées de l'image originale."""
    h, w = frame.shape[:2]
    scale = 1.0
    if w > target_width:
        scale = target_width / w
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    gray = _CLAHE.apply(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))

    best_perim    = 0.0
    best_corners  = None
    best_dict_id  = None
    best_ids      = None

    for dict_id, detector in detectors:
        corners, ids, _ = detector.detectMarkers(gray)
        if ids is None or len(ids) == 0:
            continue
        for i in range(len(ids)):
            pts = corners[i][0]  # shape (4, 2)
            if scale != 1.0:
                pts = pts / scale
            perim = sum(
                math.hypot(pts[j][0] - pts[(j + 1) % 4][0],
                           pts[j][1] - pts[(j + 1) % 4][1])
                for j in range(4)
            )
            if perim >= _MIN_MARKER_PERIMETER_PX and perim > best_perim:
                best_perim   = perim
                best_corners = pts.tolist()
                best_dict_id = dict_id
                best_ids     = [int(ids[i][0])]

    if best_corners:
        return best_dict_id, best_ids, best_corners
    return None, None, None


def detect_aruco_corners_in_frame(frame_bgr):
    """Détecte un marqueur ArUco dans une frame BGR et retourne ses 4 coins ou None.
    Utilisé pour l'affichage de la bounding box sur la frame ouverte."""
    detectors = _make_detectors()
    _, _, corners = _detect_in_frame(frame_bgr, detectors, _DETECT_WIDTH)
    return corners


def detect_aruco_in_video(video_path: str,
                           max_scan_seconds: float = 60.0,
                           step_frames: int = 5) -> dict | None:
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
    _best_score_seen = 0  # meilleur score vu, même si < seuil

    # Sauter la 1ère seconde : frames noires d'intro compressées.
    start_frame = min(int(fps * 1.0), max_frames - 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_num = start_frame

    _LOG.info("[ARUCO] Scan %-30s | %d frames max (pas=%d)", name, max_frames, step_frames)

    while frame_num < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        dict_id, ids, _corners = _detect_in_frame(frame, detectors, _DETECT_WIDTH)
        if ids is not None:
            # Confirmation en 2 étapes :
            # 1) 5 frames consécutives (élimine les artefacts de compression)
            # 2) présence vérifiée 10 secondes plus tard (élimine les faux positifs
            #    au-dessus de l'eau : équipement/surface qui disparaît au plongeon)
            ok = 0
            for _ in range(2):
                ret_c, frame_c = cap.read()
                if not ret_c:
                    ok += 1
                    break
                _, ids_c, _ = _detect_in_frame(frame_c, detectors, _DETECT_WIDTH)
                if ids_c is not None:
                    ok += 1
                else:
                    break

            confirmed = ok >= 2

            if confirmed:
                # Affinage : rembobiner step_frames en arrière et avancer frame par frame.
                refine_start = max(start_frame, frame_num - step_frames)
                cap.set(cv2.CAP_PROP_POS_FRAMES, refine_start)
                exact_frame = frame_num
                ms = int((exact_frame / fps) * 1000)
                exact_corners = _corners
                while True:
                    actual_fn = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    actual_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                    if actual_fn > frame_num:
                        break
                    ret_r, frame_r = cap.read()
                    if not ret_r:
                        break
                    _, ids_r, corners_r = _detect_in_frame(frame_r, detectors, _DETECT_WIDTH)
                    if ids_r is not None:
                        exact_frame = actual_fn
                        ms = actual_ms
                        exact_corners = corners_r
                        break
                # ── Score de détection (0-100) ────────────────────────────────
                # Composante taille (0-75) : périmètre du marqueur dans l'image
                # de détection (640 px) normalisé par sa largeur.
                # Composante dictionnaire (0-25) : DICT_4X4_50 est le dictionnaire
                # physique réel → détection la plus fiable.
                _fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
                _det_scale = min(1.0, _DETECT_WIDTH / _fw)
                _corn = exact_corners
                _perim_orig = sum(
                    math.hypot(_corn[j][0] - _corn[(j + 1) % 4][0],
                               _corn[j][1] - _corn[(j + 1) % 4][1])
                    for j in range(4)
                )
                _perim_det = _perim_orig * _det_scale
                _size_score = min(75, int(_perim_det / _DETECT_WIDTH * 300))
                _dict_bonus = 25 if dict_id == cv2.aruco.DICT_4X4_50 else 15
                _score = _size_score + _dict_bonus

                result = {
                    "frame_number": exact_frame,
                    "frame_ms": ms,
                    "marker_ids": ids,
                    "dict_id": dict_id,
                    "corners": exact_corners,  # 4 points [[x,y], ...] dans l'image originale
                    "score": _score,           # confiance 0-100 (taille + dictionnaire)
                }
                _LOG.info(
                    "[ARUCO] ✓ %-30s | marker(s) %s à frame %d (%d ms) score=%d [affiné depuis %d]",
                    name, ids, exact_frame, ms, _score, frame_num,
                )
                print(f"[ARUCO] QR code détecté à : frame {exact_frame}  score={_score}  ({name})")
                _best_score_seen = max(_best_score_seen, _score)
                if _score >= 30:
                    # Score suffisant → QRcode trouvé, passer à la vidéo suivante
                    cap.release()
                    return result
                # Score < 30 : détection peu fiable, on continue de scanner la vidéo
                print(f"[ARUCO] Score {_score}/100 < 30 → on continue ({name})")
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
    _LOG.info("[ARUCO] ✗ %-30s | aucun marker retenu (meilleur score=%d)", name, _best_score_seen)
    if _best_score_seen > 0:
        print(f"[ARUCO] QR code non retenu — meilleur score vu : {_best_score_seen}/100  ({name})")
    else:
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
