"""Détection automatique des rotations moteur par corrélation de phase horizontale."""

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


def _timecode_to_ms(tc: str) -> int:
    """Convertit 'HH:MM:SS' ou 'HH:MM:SS.mmm' en millisecondes."""
    if not tc:
        return 0
    try:
        parts = tc.split(":")
        h, m = int(parts[0]), int(parts[1])
        s_parts = parts[2].split(".")
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        return (h * 3600 + m * 60 + s) * 1000 + ms
    except Exception:
        return 0


def _refine_onset_frame(cap, first_frame: int, last_frame: int,
                        direction: float, small_size: tuple, hann,
                        abort_check=None) -> int:
    """Retrouve la première frame où le décalage atteint 25 % du maximum observé."""
    first_frame = max(0, first_frame)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
    prev_gray = None
    frame_shifts = []
    for _ in range(last_frame - first_frame + 1):
        if abort_check and abort_check():
            break
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                          small_size, interpolation=cv2.INTER_NEAREST).astype(np.float32)
        if prev_gray is not None:
            (dx, _), _ = cv2.phaseCorrelate(prev_gray, gray, hann)
            frame_shifts.append(dx * direction)
        prev_gray = gray

    if not frame_shifts or max(frame_shifts) <= 0:
        return last_frame
    limit = 0.25 * max(frame_shifts)
    k = next((k for k, s in enumerate(frame_shifts) if s >= limit), 0)
    return first_frame + k + 1


def detect_motor_rotations(
    video_path: str,
    ignore_before_ms: int = 0,
    ignore_after_ms: int = None,
    sample_fps: int = 2,
    window_sec: float = 2.0,
    shift_threshold_ratio: float = 0.35,
    onset_threshold_ratio: float = 0.01,
    scale: int = 6,
    progress_cb=None,
    abort_check=None,
) -> list:
    """
    Détecte les rotations moteur (panoramiques horizontaux) dans une vidéo.

    Args:
        video_path: chemin vers la vidéo source.
        ignore_before_ms: ignorer les rotations avant ce timestamp (ATT).
        ignore_after_ms: ignorer les rotations après ce timestamp (DÉC). None = pas de limite.
        sample_fps: fréquence d'échantillonnage (frames/s analysées). 2 = bon compromis vitesse/précision.
        scale: facteur de réduction spatiale pour la corrélation de phase. 6 = 1456→242px.
        progress_cb: callable(pct: int, msg: str).
        abort_check: callable() → bool, retourne True si l'opération doit s'arrêter.

    Returns:
        Liste de dicts {start_ms, end_ms}.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir la vidéo : {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0 or width <= 0:
        cap.release()
        raise RuntimeError("Métadonnées vidéo invalides.")

    # ── Étape 1 : corrélation de phase ─────────────────────────────────────
    step = max(1, int(round(fps / sample_fps)))
    small_w = max(16, width // scale)
    small_h = max(16, height // scale)
    small_size = (small_w, small_h)
    hann = cv2.createHanningWindow(small_size, cv2.CV_32F)

    prev_gray = None
    sample_frames = []
    shifts = []
    frame_idx = 0

    while True:
        if abort_check and abort_check():
            cap.release()
            raise InterruptedError("Annulé.")

        if frame_idx % step != 0:
            if not cap.grab():
                break
            frame_idx += 1
            continue

        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                          small_size, interpolation=cv2.INTER_NEAREST).astype(np.float32)
        if prev_gray is not None:
            (dx, _), response = cv2.phaseCorrelate(prev_gray, gray, hann)
            sample_frames.append(frame_idx)
            shifts.append(dx * scale if response > 0.05 else 0.0)
        prev_gray = gray
        frame_idx += 1

        if progress_cb and total_frames > 0 and sample_frames and len(sample_frames) % 8 == 0:
            pct = min(49, int(frame_idx / total_frames * 50))
            progress_cb(pct, f"Analyse… {int(frame_idx/fps)//60:02d}:{int(frame_idx/fps)%60:02d} / "
                             f"{int(total_frames/fps)//60:02d}:{int(total_frames/fps)%60:02d}")

    cap.release()

    if not shifts:
        return []

    # ── Étape 2 : regroupement des zones de mouvement ─────────────────────
    if abort_check and abort_check():
        raise InterruptedError("Annulé.")

    shifts_arr = np.array(shifts)
    window = max(1, int(window_sec * sample_fps))
    cumulative = np.convolve(shifts_arr, np.ones(window), mode='same')
    is_moving = np.abs(cumulative) > shift_threshold_ratio * width

    events_raw = []
    for i in np.flatnonzero(is_moving):
        if events_raw and i - events_raw[-1][1] <= window:
            events_raw[-1][1] = i
        else:
            events_raw.append([i, i])

    if progress_cb:
        progress_cb(55, f"{len(events_raw)} zone(s) de mouvement…")

    # ── Étape 3 : affinage de l'onset ─────────────────────────────────────
    onset_threshold = onset_threshold_ratio * width
    cap = cv2.VideoCapture(video_path)
    results = []
    ignore_after_sec = (ignore_after_ms / 1000.0) if ignore_after_ms is not None else None
    ignore_before_sec = ignore_before_ms / 1000.0

    for evt_i, (start, end) in enumerate(events_raw):
        if abort_check and abort_check():
            cap.release()
            raise InterruptedError("Annulé.")

        first = max(0, start - window // 2)
        last = min(len(sample_frames) - 1, end + window // 2)
        direction = float(np.sign(shifts_arr[first:last + 1].sum()))

        onset = next(
            (i for i in range(first, last + 1) if shifts_arr[i] * direction > onset_threshold),
            first,
        )
        prev_frame = max(0, sample_frames[onset] - step)
        start_frame = _refine_onset_frame(cap, prev_frame, sample_frames[onset],
                                          direction, small_size, hann, abort_check=abort_check)
        end_frame = sample_frames[last]

        start_sec = start_frame / fps
        if start_sec < ignore_before_sec:
            continue
        if ignore_after_sec is not None and start_sec > ignore_after_sec:
            continue

        start_ms = int(start_frame / fps * 1000)
        end_ms = int(end_frame / fps * 1000)
        results.append({"start_ms": start_ms, "end_ms": end_ms})

        if progress_cb:
            pct = 60 + int(evt_i / max(1, len(events_raw)) * 35)
            progress_cb(pct, f"Rotation à {int(start_sec)//60:02d}:{int(start_sec)%60:02d}…")

    cap.release()
    if progress_cb:
        progress_cb(100, f"{len(results)} rotation(s) retenue(s).")
    return results


class MotorRotationBatchWorker(QThread):
    """Worker Qt : détecte les rotations moteur sur une liste de vidéos, séquentiellement."""

    video_started  = pyqtSignal(str, int, int)   # (video_name, idx_1based, total)
    video_progress = pyqtSignal(int, str)          # (pct 0-100, msg) pour la vidéo courante
    video_done     = pyqtSignal(str, str, list)    # (video_path, json_path, detections)
    video_error    = pyqtSignal(str, str)          # (video_name, error_msg)

    def __init__(self, tasks: list, parent=None):
        """tasks : liste de (video_path, json_path, landing_ms, takeoff_ms)."""
        super().__init__(parent)
        self._tasks = tasks
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        import os as _os
        total = len(self._tasks)
        for idx, (video_path, json_path, landing_ms, takeoff_ms) in enumerate(self._tasks):
            if self._abort:
                break
            self.video_started.emit(_os.path.basename(video_path), idx + 1, total)
            try:
                results = detect_motor_rotations(
                    video_path,
                    ignore_before_ms=landing_ms,
                    ignore_after_ms=takeoff_ms,
                    progress_cb=lambda pct, msg: self.video_progress.emit(pct, msg),
                    abort_check=lambda: self._abort,
                )
                self.video_done.emit(video_path, json_path, results)
            except InterruptedError:
                break
            except Exception as exc:
                self.video_error.emit(_os.path.basename(video_path), str(exc))


class MotorRotationDetectionWorker(QThread):
    """Worker Qt : lance detect_motor_rotations en arrière-plan."""

    progress = pyqtSignal(int, str)
    rotations_detected = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, video_path: str, ignore_before_ms: int, ignore_after_ms,
                 parent=None):
        super().__init__(parent)
        self._video_path = video_path
        self._ignore_before_ms = ignore_before_ms
        self._ignore_after_ms = ignore_after_ms
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            results = detect_motor_rotations(
                self._video_path,
                ignore_before_ms=self._ignore_before_ms,
                ignore_after_ms=self._ignore_after_ms,
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
                abort_check=lambda: self._abort,
            )
            self.rotations_detected.emit(results)
        except InterruptedError:
            self.rotations_detected.emit([])
        except Exception as exc:
            self.error.emit(str(exc))
