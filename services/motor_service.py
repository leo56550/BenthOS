import json
import os
import uuid

import pandas as pd
from datetime import datetime


def _load_frame_pts(txt_path: str) -> list:
    """Charge les timestamps de frames (PTS en ms) depuis un fichier .txt vidéo."""
    pts = []
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    pts.append(float(line))
    except Exception as e:
        print(f"[MOTOR] Impossible de lire {os.path.basename(txt_path)}: {e}")
    return pts


def _find_nearest_pts(pts: list, target_ms: float) -> float:
    """Retourne le PTS le plus proche de target_ms dans la liste triée pts."""
    if not pts:
        return target_ms
    lo, hi = 0, len(pts) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if pts[mid] < target_ms:
            lo = mid + 1
        else:
            hi = mid
    # lo est l'index du premier PTS >= target_ms
    if lo == 0:
        return pts[0]
    # comparer avec le voisin précédent
    if abs(pts[lo - 1] - target_ms) <= abs(pts[lo] - target_ms):
        return pts[lo - 1]
    return pts[lo]


def get_motor_stable_timestamps(csv_path: str, delay: float = 6.0, start_track_id: int = 6,
                                 txt_path: str = None) -> list:
    """Calcule les timestamps stables depuis un fichier systemEvent.csv.

    Pour chaque START MOTEUR, cherche le premier END AWB ALGO qui suit (fin de
    stabilisation de la balance des blancs) → c'est le vrai début de l'image stable.
    Si aucun END AWB ALGO n'est trouvé entre deux moteurs, repli sur START MOTEUR + delay.

    Si txt_path est fourni (fichier <stem>.txt contenant les PTS de chaque frame en ms),
    le timestamp final est calé sur la frame la plus proche plutôt que sur le temps brut CSV
    (plus précis en cas d'irrégularités d'encodage ou de décalage horloge).

    Args:
        csv_path: Chemin vers le fichier CSV systemEvent.
        delay: Fallback en secondes si aucun END AWB ALGO n'est disponible (défaut 6.0).
        start_track_id: Identifiant de départ pour la séquence de tracks (défaut 6).
        txt_path: Chemin vers le fichier .txt de PTS de frames (optionnel).

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

    # Charger les PTS de frames si le fichier .txt est disponible
    frame_pts: list = []
    if txt_path and os.path.isfile(txt_path):
        frame_pts = _load_frame_pts(txt_path)
        if frame_pts:
            print(f"[MOTOR] {len(frame_pts)} PTS chargés depuis {os.path.basename(txt_path)}")
        else:
            print(f"[MOTOR] Fichier TXT vide ou illisible : {os.path.basename(txt_path)}")
    elif txt_path:
        print(f"[MOTOR] Fichier TXT introuvable : {txt_path}")

    structural_events = []
    track_id = start_track_id

    for i, motor_idx in enumerate(motor_indices):
        t_event_str = df.loc[motor_idx, col_time]
        try:
            t_motor = datetime.strptime(t_event_str, "%Hh%Mm%Ss")
            motor_offset = (t_motor - t0).total_seconds()
            if motor_offset < 0:
                continue

            # Utiliser START MOTEUR directement : les AWB sont périodiques (toutes les ~10s)
            # et non déclenchées par la rotation — leur timing est trop aléatoire.
            stable_offset = motor_offset
            print(f"[MOTOR] Rot #{i+1}: START MOTEUR +{motor_offset:.0f}s depuis encodeur")

            angle_step = (i % 6) + 1
            calculated_angle = angle_step * 60
            rotation_type = "rotation_360°" if calculated_angle == 360 else f"rotation_{calculated_angle}°"

            raw_ms = stable_offset * 1000
            if frame_pts:
                precise_ms = _find_nearest_pts(frame_pts, raw_ms)
                if abs(precise_ms - raw_ms) > 1000:
                    # Si la frame la plus proche est à plus d'1s, on garde le calcul CSV
                    print(f"[MOTOR] Rot #{i+1}: écart TXT/CSV {abs(precise_ms - raw_ms):.0f}ms > 1s → CSV conservé")
                    precise_ms = raw_ms
                else:
                    print(f"[MOTOR] Rot #{i+1}: CSV={raw_ms:.0f}ms → TXT={precise_ms:.3f}ms "
                          f"(écart={precise_ms - raw_ms:+.1f}ms)")
                stable_ms = int(round(precise_ms))
                stable_offset = precise_ms / 1000.0
            else:
                stable_ms = int(raw_ms)

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

    # ── Lire le JSON EN PREMIER pour décider si le calcul est nécessaire ──────
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

    if not force and csv_entries:
        return 0  # entrées CSV auto déjà présentes → saut sans aucun calcul

    # ── Calcul uniquement si nécessaire ──────────────────────────────────────
    stem = os.path.splitext(os.path.basename(video_path))[0]
    txt_path = os.path.join(video_dir, stem + ".txt")
    txt_path = txt_path if os.path.isfile(txt_path) else None

    try:
        motor_data = get_motor_stable_timestamps(csv_path, delay=6.0, txt_path=txt_path)
    except Exception as e:
        print(f"[MOTOR] Erreur lecture CSV {os.path.basename(csv_path)}: {e}")
        return 0

    if not motor_data:
        return 0

    # Avec force=True : remplacer les entrées CSV auto mais garder les entrées manuelles
    new_csv_entries = []
    for mi in motor_data:
        # Utiliser mi["start"] qui contient le ms précis (calé sur TXT si disponible)
        ms_val = int(mi["start"])
        h = ms_val // 3600000
        m = (ms_val % 3600000) // 60000
        s = (ms_val % 60000) // 1000
        ms_sub = ms_val % 1000
        new_csv_entries.append({
            "event_id":       str(uuid.uuid4()),
            "time_code":      f"{h:02d}:{m:02d}:{s:02d}.{ms_sub:03d}",
            "start_ms":       ms_val,
            "frame_number":   int(ms_val / 1000 * fps),
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
