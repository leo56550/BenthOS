import csv
import json
import os

from PyQt6.QtCore import QThread, pyqtSignal

from services.campaign_service import get_temp_json_path


_NON_ROT_KW = {
    "atterrissage", "atterissage", "décollage", "decollage",
    "landing", "takeoff", "debut_analyse", "fin_analyse",
    "analysis_start", "analysis_end",
}

# Colonnes du CSV exporté
_CSV_COLUMNS = [
    "video_name",
    "event_category",
    "description_fr",
    "description_en",
    "start_ms",
    "end_ms",
    "frame_number",
    "comment",
]


def _ms_to_tc(ms) -> str:
    """Convertit des millisecondes en HH:MM:SS.mmm."""
    try:
        ms = int(ms)
        h, rem = divmod(ms // 1000, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms % 1000:03d}"
    except Exception:
        return ""


def _is_rotation_motor(desc: str) -> bool:
    return desc.strip().lower() not in _NON_ROT_KW and bool(desc.strip())


class BatchEventsExportWorker(QThread):
    """Parcourt tous les JSON de la campagne et génère un CSV des événements."""

    progress = pyqtSignal(int, int)      # (done, total)
    finished = pyqtSignal(str, int)      # (output_path, row_count)
    error = pyqtSignal(str)

    def __init__(self, working_dir: str, output_path: str, parent=None):
        super().__init__(parent)
        self._working_dir = working_dir
        self._output_path = output_path

    def run(self):
        try:
            json_files = []
            for root, _dirs, files in os.walk(self._working_dir):
                for f in files:
                    if f.endswith(".json"):
                        json_files.append(os.path.join(root, f))
            json_files.sort()

            total = len(json_files)
            rows = []

            for i, json_path in enumerate(json_files):
                if self.isInterruptionRequested():
                    return
                self.progress.emit(i, total)
                try:
                    with open(json_path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    continue

                video_obs = data.get("video_observation", {})
                # Retrouve le nom vidéo depuis le JSON (champ source ou basename sans extension)
                video_name = (
                    video_obs.get("video_filename")
                    or os.path.splitext(os.path.basename(json_path))[0]
                )

                # ── events_motor ──────────────────────────────────────────────
                raw_motor = video_obs.get("events_motor")
                if isinstance(raw_motor, list):
                    for entry in raw_motor:
                        if not isinstance(entry, dict):
                            continue
                        # Filtre placeholder et entrées corrompues à t=0
                        if (entry.get("event_id") is None
                                and entry.get("frame_number") is None):
                            continue
                        if (int(entry.get("start_ms") or 0) == 0
                                and int(entry.get("frame_number") or 0) == 0):
                            continue
                        desc_fr = entry.get("description_fr", "")
                        rows.append({
                            "video_name": video_name,
                            "event_category": "events_motor",
                            "description_fr": desc_fr,
                            "description_en": entry.get("description_en", ""),
                            "start_ms": entry.get("start_ms", ""),
                            "end_ms": entry.get("end_ms", entry.get("start_ms", "")),
                            "frame_number": entry.get("frame_number", ""),
                            "comment": entry.get("comment", ""),
                        })

                # ── events_animal + events_interesting_images ─────────────────
                for json_key in ("events_animal", "events_interesting_images"):
                    raw = video_obs.get(json_key)
                    if not isinstance(raw, list) or not raw:
                        continue
                    first = raw[0] if raw else {}
                    values_list = first.get("values", []) if isinstance(first, dict) else []
                    for val in values_list:
                        if not isinstance(val, dict):
                            continue
                        rows.append({
                            "video_name": video_name,
                            "event_category": json_key,
                            "description_fr": val.get("value", ""),
                            "description_en": val.get("value_en", val.get("value", "")),
                            "start_ms": val.get("start_ms", ""),
                            "end_ms": val.get("end_ms", val.get("start_ms", "")),
                            "frame_number": val.get("frame_number_start", ""),
                            "comment": val.get("comment", ""),
                        })

            self.progress.emit(total, total)

            os.makedirs(os.path.dirname(self._output_path) or ".", exist_ok=True)
            with open(self._output_path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            self.finished.emit(self._output_path, len(rows))

        except Exception as exc:
            self.error.emit(str(exc))
