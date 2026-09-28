import json
import os
import uuid

import pandas as pd
from datetime import datetime


def get_motor_stable_timestamps(csv_path: str, delay: float = 6.0, start_track_id: int = 6) -> list:
    """Calcule les timestamps stables depuis un fichier systemEvent.csv.

    Pour chaque START MOTEUR, cherche le premier END AWB ALGO qui suit (fin de
    stabilisation de la balance des blancs) → c'est le vrai début de l'image stable.
    Si aucun END AWB ALGO n'est trouvé entre deux moteurs, repli sur START MOTEUR + delay.

    Args:
        csv_path: Chemin vers le fichier CSV systemEvent.
        delay: Fallback en secondes si aucun END AWB ALGO n'est disponible (défaut 6.0).
        start_track_id: Identifiant de départ pour la séquence de tracks (défaut 6).

    Returns:
        Liste de dicts avec 'track_id', 'timestamp', 'duration', 'start' (ms),
        'type', 'angle', 'rotation_index'.
    """
    try:
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='utf-8')
    except Exception:
        df = pd.read_csv(csv_path, sep=None, engine='python', encoding='cp1252')

    df.columns = [c.strip().lower() for c in df.columns]

    col_event = 'event'
    col_time = 'heure'

    if col_event not in df.columns:
        raise KeyError(f"Colonne 'Event' introuvable. Colonnes détectées : {list(df.columns)}")

    df[col_event] = df[col_event].astype(str).str.strip().str.upper()
    df[col_time] = df[col_time].astype(str).str.strip()

    start_encoder_rows = df[df[col_event] == 'START ENCODER']
    if start_encoder_rows.empty:
        print("START ENCODER non trouvé, utilisation de la première ligne.")
        t0_str = df.iloc[0][col_time]
    else:
        t0_str = start_encoder_rows.iloc[0][col_time]

    t0 = datetime.strptime(t0_str, "%Hh%Mm%Ss")

    motor_indices = df.index[df[col_event] == 'START MOTEUR'].tolist()

    structural_events = []
    track_id = start_track_id

    for i, motor_idx in enumerate(motor_indices):
        t_event_str = df.loc[motor_idx, col_time]
        try:
            t_motor = datetime.strptime(t_event_str, "%Hh%Mm%Ss")
            motor_offset = (t_motor - t0).total_seconds()
            if motor_offset < 0:
                continue

            # Chercher le premier END AWB ALGO entre ce moteur et le suivant
            next_motor_idx = motor_indices[i + 1] if i + 1 < len(motor_indices) else len(df)
            window = df.loc[motor_idx + 1:next_motor_idx - 1]
            awb_end_rows = window[window[col_event] == 'END AWB ALGO']

            if not awb_end_rows.empty:
                t_awb_str = awb_end_rows.iloc[0][col_time]
                t_awb = datetime.strptime(t_awb_str, "%Hh%Mm%Ss")
                stable_offset = (t_awb - t0).total_seconds()
                print(f"[MOTOR] Rot #{i+1}: START MOTEUR +{motor_offset:.0f}s → END AWB +{stable_offset:.0f}s"
                      f" (awb_delay={stable_offset - motor_offset:.0f}s)")
            else:
                stable_offset = motor_offset + delay
                print(f"[MOTOR] Rot #{i+1}: START MOTEUR +{motor_offset:.0f}s → fallback +{stable_offset:.0f}s"
                      f" (no AWB found, delay={delay}s)")

            angle_step = (i % 6) + 1
            calculated_angle = angle_step * 60
            rotation_type = "rotation_360°" if calculated_angle == 360 else f"rotation_{calculated_angle}°"
            stable_ms = int(stable_offset * 1000)

            structural_events.append({
                "track_id": track_id,
                "timestamp": stable_offset,
                "duration": 6.0,
                "start": stable_ms,
                "type": rotation_type,
                "angle": calculated_angle,
                "rotation_index": (i // 6) + 1
            })
            track_id += 1

        except Exception as e:
            print(f"Erreur de format temporel : {e}")

    return structural_events


def _is_csv_auto_event(entry: dict) -> bool:
    """Vrai si l'entrée events_motor a été générée automatiquement depuis le CSV (pas saisie manuellement)."""
    desc = entry.get("description_fr", "") or ""
    return bool(desc and "Rotation moteur #" in desc and "°)" in desc)


def persist_motor_events_from_csv(video_path: str, json_path: str, fps: float = 25.0,
                                   force: bool = False) -> int:
    """Analyse le systemEvent.csv voisin de video_path et écrit les rotations dans json_path.

    Ne fait rien si :
    - aucun systemEvent.csv n'existe à côté de la vidéo
    - le JSON n'existe pas
    - events_motor contient des entrées saisies manuellement (non CSV)

    Avec force=True : réécrit même si les événements CSV auto existent déjà.
    Retourne le nombre de rotations écrites (0 si rien fait).
    """
    video_dir = os.path.dirname(video_path)
    csv_path = os.path.join(video_dir, "systemEvent.csv")
    if not os.path.isfile(csv_path) or not os.path.isfile(json_path):
        return 0

    try:
        motor_data = get_motor_stable_timestamps(csv_path, delay=6.0)
    except Exception as e:
        print(f"[MOTOR] Erreur lecture CSV {os.path.basename(csv_path)}: {e}")
        return 0

    if not motor_data:
        return 0

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[MOTOR] Erreur lecture JSON {os.path.basename(json_path)}: {e}")
        return 0

    obs = data.setdefault("video_observation", {})
    existing = [
        e for e in (obs.get("events_motor") or [])
        if isinstance(e, dict) and (e.get("event_id") is not None or e.get("frame_number") is not None)
    ]

    manual_entries = [e for e in existing if not _is_csv_auto_event(e)]
    csv_entries    = [e for e in existing if _is_csv_auto_event(e)]

    if not force and existing:
        return 0  # déjà rempli (entrées manuelles ou CSV) → pas de réécriture

    # Avec force=True : remplacer les entrées CSV auto mais garder les entrées manuelles
    new_csv_entries = []
    for mi in motor_data:
        ms_val = int(mi["timestamp"] * 1000)
        h = ms_val // 3600000
        m = (ms_val % 3600000) // 60000
        s = (ms_val % 60000) // 1000
        ms_sub = ms_val % 1000
        new_csv_entries.append({
            "event_id":       str(uuid.uuid4()),
            "time_code":      f"{h:02d}:{m:02d}:{s:02d}.{ms_sub:03d}",
            "start_ms":       ms_val,
            "frame_number":   int(mi["timestamp"] * fps),
            "description_fr": f"Rotation moteur #{mi['rotation_index']} ({mi['angle']}°)",
            "description_en": f"Motor rotation #{mi['rotation_index']} ({mi['angle']}°)",
            "comment":        "",
        })

    obs["events_motor"] = manual_entries + new_csv_entries

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        n = len(obs["events_motor"])
        print(f"[TEMP_JSON] {os.path.basename(json_path)} ← events_motor auto ({n} rotation(s) depuis CSV)")
        return n
    except Exception as e:
        print(f"[MOTOR] Erreur écriture JSON {os.path.basename(json_path)}: {e}")
        return 0
