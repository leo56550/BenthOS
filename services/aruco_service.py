import os
import logging
import math

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

_LOG = logging.getLogger(__name__)

_DETECTOR = cv2.aruco.ArucoDetector(
    cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
    cv2.aruco.DetectorParameters(),
)


def _detect_in_frame(frame):
    """Détecte le plus grand marqueur ArUco 4x4_50 dans une frame BGR.
    Retourne (ids, corners) ou (None, None).
    corners : liste de 4 points [[x, y], ...] en coordonnées originales."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _DETECTOR.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        return None, None
    # Garder le marqueur avec le plus grand périmètre (le plus proche / le plus net)
    best_i, best_perim = 0, 0.0
    for i in range(len(ids)):
        pts = corners[i][0]
        p = sum(math.hypot(pts[j][0] - pts[(j+1)%4][0],
                           pts[j][1] - pts[(j+1)%4][1]) for j in range(4))
        if p > best_perim:
            best_perim, best_i = p, i
    return [int(ids[best_i][0])], corners[best_i][0].tolist()


def detect_aruco_in_video(video_path: str,
                           max_scan_seconds: float = 60.0,
                           step_frames: int = 5) -> dict | None:
    """Scanne les premières max_scan_seconds d'une vidéo.
    Retourne un dict {frame_number, frame_ms, marker_ids, corners, score} ou None.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _LOG.warning("[ARUCO] Impossible d'ouvrir : %s", os.path.basename(video_path))
        return None

    fps         = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total       = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames  = min(total, int(max_scan_seconds * fps))
    name        = os.path.basename(video_path)

    # Sauter la 1ère seconde (frames noires d'intro)
    start = min(int(fps), max_frames - 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    frame_num = start

    while frame_num < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        ids, corners = _detect_in_frame(frame)
        if ids is not None:
            # Confirmation sur 2 frames consécutives (anti-artefact)
            ok = 0
            for _ in range(2):
                ret_c, frame_c = cap.read()
                if not ret_c:
                    ok += 1
                    break
                ids_c, _ = _detect_in_frame(frame_c)
                if ids_c is not None:
                    ok += 1
                else:
                    break

            if ok >= 2:
                ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                # Score basé sur la taille du marqueur dans l'image (0-100)
                fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
                perim = sum(math.hypot(corners[j][0] - corners[(j+1)%4][0],
                                       corners[j][1] - corners[(j+1)%4][1])
                            for j in range(4))
                score = min(100, int(perim / fw * 400))
                result = {
                    "frame_number": frame_num,
                    "frame_ms":     ms,
                    "marker_ids":   ids,
                    "corners":      corners,
                    "score":        score,
                }
                print(f"[ARUCO] QR code détecté à : frame {frame_num}  score={score}  ({name})")
                cap.release()
                return result

        # Avancer de step_frames
        frame_num += step_frames
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

    cap.release()
    print(f"[ARUCO] QR code non détecté  ({name})")
    return None


class ArucoWorker(QThread):
    """Thread background : détecte les markers ArUco dans toutes les vidéos d'une campagne."""

    video_scanned = pyqtSignal(str, object)
    scan_complete = pyqtSignal(int, int)

    def __init__(self, video_paths: list, parent=None):
        super().__init__(parent)
        self._video_paths = list(video_paths)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        total = len(self._video_paths)
        found = 0
        print(f"[ARUCO] Lancement scan de {total} vidéo(s)…")
        for vp in self._video_paths:
            if self._abort:
                break
            result = detect_aruco_in_video(vp)
            self.video_scanned.emit(vp, result)
            if result:
                found += 1
        self.scan_complete.emit(found, total)
        print(f"[ARUCO] Scan terminé : {found}/{total} vidéo(s) avec marker ArUco")
