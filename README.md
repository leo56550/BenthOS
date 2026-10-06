# KOSMOS IHM

> Desktop post-processing workstation for KOSMOS underwater camera deployments.  
> Qualify, annotate, and export marine observation data from raw MP4 footage.

![Python](https://img.shields.io/badge/Python-3.12-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.11-green) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## About

KOSMOS IHM (*Interface Homme-Machine*) is the companion desktop application for the **KOSMOS system** — an autonomous underwater video recorder developed at IMT Atlantique. After a field deployment, operators bring back a folder of raw MP4 files and run them through this workstation to qualify recordings, annotate biological events, fill in metadata, and extract deliverables.

All campaign data is persisted as per-video `_temp.json` sidecar files. The original raw JSON files produced by the device are **never modified**.

---

## Features

| Page | Description |
|---|---|
| **Qualification** | Review all recordings on an interactive GPS map. Keep or discard each video with one click. |
| **Validation** | Secondary review pass. Toggle exploitability and stereo/mono status per video. |
| **Event annotation** | Mark timestamped events on the video timeline: fish, birds, turtles, motor events — with audio cues. |
| **Metadata editing** | Edit structured fields driven by a configurable `template.json` schema. Includes weather lookup and GPS map view. |
| **Extraction** | Clip video segments and capture still frames with CLAHE dehazing, histogram equalisation and stereo rectification. |
| **PDF report** | Generate a campaign report with statistics, GPS scatter, and per-video data sheets. |
| **SFTP transfer** | Pull files from the KOSMOS SD card directly over SSH/SFTP without mounting the drive. |
| **Bilingual UI** | French / English toggle at runtime. |

---

## Requirements

- **OS:** Windows 10 / 11
- **Python:** 3.12

| Package | Version | Role |
|---|---|---|
| `PyQt6` | 6.11.0 | GUI framework |
| `PyQt6-WebEngine` | 6.11.0 | Embedded Chromium for Leaflet maps |
| `opencv-python` | 4.13.0 | Video reading, frame extraction, stereo rectification |
| `numpy` | 2.4.4 | Vectorised image processing |
| `matplotlib` | 3.10.9 | PDF report generation |
| `pandas` | 3.0.2 | Telemetry CSV reading |
| `paramiko` | 4.0.0 | SFTP transfer from KOSMOS hardware |
| `requests` | 2.33.1 | Weather API (Open-Meteo) |
| `folium` | 0.20.0 | Interactive Leaflet map generation |
| `openpyxl` | — | Excel export |
| `pywin32` | 312 | Windows shell integration |

---

## Installation

### Option A — Conda (recommended)

```bash
conda env create -f environment.yml
conda activate kosmos-ihm
```

### Option B — pip / venv

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> **Note:** The map views require `PyQt6-WebEngine`. Make sure it is installed alongside `PyQt6`.

---

## Running

```bash
python main.py
```

On first launch, click **Open Campaign** and select:

1. **Raw footage directory** — folder containing the `.mp4` files from the KOSMOS device.
2. **Campaign output directory** — where processed results and sidecar JSON files will be written.
3. **Working directory** — temporary workspace used by the extraction pipeline.

Crash logs are written to `kosmos_crash.log` next to `main.py`.

---

## Build a standalone executable

A PyInstaller spec is provided to bundle the application into a self-contained Windows folder:

```bash
py -m PyInstaller KOSMOS_IHM.spec
```

Output: `dist\KOSMOS_IHM\KOSMOS_IHM.exe` — ships with Qt WebEngine, OpenCV, and all data files. No Python installation required on the target machine.

---

## Architecture

```
KOSMOS-IHM/
├── main.py                   # Entry point
├── ihm2.ui                   # Qt Designer layout (loaded at runtime)
├── template.json             # Metadata schema (drives the Metadata editor)
├── requirements.txt
├── environment.yml           # Conda environment spec (Python 3.12)
├── KOSMOS_IHM.spec           # PyInstaller build spec
│
├── controllers/              # Business logic, one controller per page
│   ├── app_controller.py     # Top-level orchestrator
│   ├── accueil_controller.py
│   ├── qualif_controller.py
│   ├── validation_controller.py
│   ├── evenements_controller.py
│   ├── metadonnees_controller.py
│   ├── extraction_controller.py
│   └── apropos_controller.py
│
├── models/                   # Qt item models (no widgets)
├── views/                    # Page widgets, dialogs, reusable widgets
├── services/                 # Backend I/O (SFTP, thumbnails, PDF, weather…)
├── assets/                   # Leaflet HTML/JS, WAV sound cues
└── img/                      # Application icons
```

---

## Data format

Each video `<stem>.mp4` is paired with two JSON files:

| File | Written by | Description |
|---|---|---|
| `<stem>.json` | KOSMOS device | **Read-only.** Raw telemetry and device metadata. Never modified by the IHM. |
| `<stem>_temp.json` | IHM | All operator annotations: qualification status, events, metadata, exploitability. The sole writable file. |

The structure of `_temp.json` is defined by `template.json` and initialised by `services/migration_service.py`.

---

## Keyboard shortcuts

| Shortcut | Page | Action |
|---|---|---|
| `Ctrl+Z` | Qualification | Undo last Keep / Discard |
| `Ctrl+Z` | Validation | Undo last exploitability change |
| `Ctrl+Z` | Events | Undo last event placement, deletion, or move |
| `Ctrl+drag` | Events — timeline | Move an event to a new position |
| `Space` | Video player | Play / Pause |
| `Delete` | Events — tree | Delete selected event |

---

## Authors

Developed at **IMT Atlantique** — Léo Bultel
