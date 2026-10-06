# BenthOS

> Desktop post-processing workstation for KOSMOS underwater camera deployments.  
> Qualify, annotate, and export marine observation data from raw MP4 footage.

![Python](https://img.shields.io/badge/Python-3.12-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.11-green) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## About

![KOSMOS system](img/screenshots/Kosmos.jpg)

**BenthOS** (*Interface Homme-Machine*) is the companion desktop application for the **KOSMOS system** — an autonomous underwater video recorder developed at IMT Atlantique. After a field deployment, operators bring back a folder of raw MP4 files and run them through this workstation to qualify recordings, annotate biological events, fill in metadata, and extract deliverables.

All campaign data is persisted as per-video `_temp.json` sidecar files. The original raw JSON files produced by the device are **never modified**.

---

## Screenshots

### Home
![Home](img/screenshots/acceuil.png)

The home page lets you open an existing campaign or create a new one by selecting the raw footage folder, the campaign output directory, and the working directory. Recent campaigns are accessible in one click, and a quick single-video mode is available for ad-hoc review.

---

### Qualification
![Qualification](img/screenshots/qualification.png)

The qualification page is the first processing step. All videos of the campaign are displayed in the left panel with their name, duration and file size. The operator watches each video through the embedded player and decides to **Keep** (Garder) or **Discard** (Jeter) it. The right panel shows the motor rotations for the selected video. Discarded videos are moved to a trash bin and can be restored at any time. `Ctrl+Z` undoes the last keep/discard action.

---

### Validation
![Validation](img/screenshots/validation.png)

The validation page is a secondary review pass over the qualified videos. For each video the operator can set its **exploitability** status (exploitable / partially exploitable / not exploitable) and confirm the stereo/mono camera configuration. Filling in the **slate** (ardoise) is mandatory on this page before the video can be considered validated. All choices are persisted in the per-video `_temp.json` sidecar file. `Ctrl+Z` undoes the last exploitability change.

---

### Event annotation
![Events](img/screenshots/event.png)

The event annotation page allows the operator to stamp timestamped biological observations directly on the video timeline. Supported event types include fish, birds, turtles and motor events, each with a configurable sub-type, count and free-text comment. A sound cue plays on each capture. Events are displayed in a tree view on the right and can be moved along the timeline with `Ctrl+drag`. `Ctrl+Z` undoes the last placement, deletion or move. The full event list can be exported to CSV.

### Event export
![Event export](img/screenshots/export_events.png)

The event export dialog lets the operator export the annotated events for one or all videos of the campaign. The output is a CSV file containing the timecodes, event types, values and comments, ready to be imported into analysis tools.

---

### Metadata editing
![Metadata](img/screenshots/metadata.png)

The metadata page exposes all structured observation fields defined in `template.json`: zone, date, boat name, pilot, GPS coordinates, depth, visibility, sea state, and more. Campaign-level fields (zone, date, crew) are read-only and shared across all videos; video-level fields are editable per video. A weather lookup button fetches current conditions from Open-Meteo and pre-fills the relevant fields. A GPS map view lets the operator verify or correct the deployment position.

---

### Extraction
![Extraction](img/screenshots/extraction.png)

The extraction page is used to produce deliverables from each video. The operator sets in/out markers on the timeline to clip a segment, or captures individual still frames. Several image enhancement options are available: histogram equalisation, CLAHE dehazing, underwater colour correction, and stereo rectification for dual-camera footage. All extracted segments and frames are listed in a deliverables tree with thumbnails and can be re-exported at any time.

---

### SFTP transfer
![SFTP](img/screenshots/sftp.py.png)

The SFTP dialog connects directly to the KOSMOS device over SSH/SFTP (via paramiko) without needing to mount the SD card. The operator enters the device's IP address and credentials, browses the remote file system, and transfers the raw footage and JSON telemetry files to the local campaign folder in one operation.

---

### Telemetry
![Telemetry](img/screenshots/telemetry.png)

The telemetry dialog displays the raw sensor data recorded by the KOSMOS device during a deployment. It reads the CSV telemetry file associated with the current video and presents the time-series data (motor rotations, depth, heading, etc.) so the operator can cross-check the deployment conditions alongside the video footage.

---

### Deployment planner
![Planner](img/screenshots/planification.png)

The deployment planner is an interactive Leaflet map (embedded via Qt WebEngine) that lets the team plan the spatial coverage of a mission before heading to the field. Deployment points can be placed, moved and annotated directly on the map. The planned stations can be exported as a waypoint list.

---

### Historical data
![Historical data](img/screenshots/historical_data.png)

The historical data dialog allows the operator to load and browse observation records from previous campaigns. This makes it possible to cross-reference past deployments at the same site, compare event counts over time, and avoid duplicating annotations already recorded in earlier missions.

---

### Progress dashboard
![Progress](img/screenshots/progress.py.png)

The progress dashboard gives a real-time overview of the campaign processing status. It shows how many videos have been qualified, validated, annotated and have their metadata filled in, so the operator can see at a glance what still needs to be done before generating the final PDF report.

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

1. **Raw footage directory** — the KOSMOS unit folder (e.g. `260730_K54/`).
2. **Working directory** — BenthOS will create a `BenthOS_sorties/` folder next to it for all outputs.

Crash logs are written to `kosmos_crash.log` next to `main.py`.

---

## Build a standalone executable

A PyInstaller spec is provided to bundle the application into a self-contained Windows folder:

```bash
py -m PyInstaller KOSMOS_IHM.spec
```

Output: `dist\KOSMOS_IHM\KOSMOS_IHM.exe` — ships with Qt WebEngine, OpenCV, and all data files. No Python installation required on the target machine.

---

## Code architecture

```
BenthOS/
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

## Data architecture

### Input — campaign folder structure

A KOSMOS campaign is organised as follows. The top-level campaign folder contains one sub-folder per KOSMOS unit deployed. Each unit folder contains one sub-folder per station (deployment point), and each station folder holds the files recorded for that drop:

```
260805_ATL_CC_ENEZEG_pourceaux/       ← campaign folder
├── 260730_K54/                        ← KOSMOS unit
│   ├── 0102/                          ← station
│   │   ├── 0102.mp4                   # raw video (never modified)
│   │   ├── 0102.json                  # device metadata (never modified)
│   │   ├── 0102.csv                   # GPS / sensor timeseries (never modified)
│   │   ├── 0102.txt                   # device log (never modified)
│   │   ├── 0102_temp.json             # ← BenthOS annotations (writable)
│   │   └── systemEvent.csv            # system events log (never modified)
│   ├── 0103/
│   └── ...
├── 260805_K52/
└── 260805_K53/
```

| File | Source | Description |
|---|---|---|
| `<stem>.mp4` | KOSMOS device | Raw video footage. Never modified by BenthOS. |
| `<stem>.json` | KOSMOS device | Device metadata: camera, firmware, system config. Read-only. |
| `<stem>.csv` | KOSMOS device | Time-series telemetry: GPS, depth, heading, motor rotations. Read-only. |
| `<stem>.txt` | KOSMOS device | Device event log. Read-only. |
| `systemEvent.csv` | KOSMOS device | System-level events (motor start/stop, etc.). Read-only. |
| `<stem>_temp.json` | BenthOS | **The sole writable file.** Contains all operator annotations (see below). |

The `_temp.json` structure mirrors `template.json` and stores:

```json
{
  "survey":            {},   // Campaign-level fields: zone, date, boat, crew
  "video_observation": {}    // Video-level fields: GPS, depth, visibility, time,
                             // qualification status, exploitability, stereo/mono,
                             // biological events, extraction deliverables
}
```

### Output — BenthOS_sorties

When a campaign is opened, BenthOS automatically creates a `BenthOS_sorties/` folder next to the campaign folder. All deliverables are written there.

```
BenthOS_sorties/
├── 261006_infoStation.csv                  ← generated via "Générer InfoStation" button
└── 202608051148_Lolo_CC260080/             ← one folder per video, renamed on export
    ├── IMG/                                 # extracted image batch (lot d'images)
    ├── 202608051148_Lolo_CC260080.json      # renamed _temp.json
    ├── 202608051148_Lolo_CC260080.lnk       # Windows shortcut → raw .mp4
    └── Annotation_VIAME.csv                 # annotation file ready for VIAME
```

The per-video folder (and its JSON/shortcut) is named after the following convention, built automatically from the metadata filled in on the Metadata page:

```
YYYYMMDDhhmm _ REGION _ ZONEyyNNNN
└─────┬──────┘   └─┬─┘   └───┬───┘
      │             │         └─ Station code:
      │             │              ZONE   = zone field (e.g. CC, ATL…)
      │             │              yy     = 2-digit year from the survey date
      │             │              NNNN   = 4-digit station number (ardoise / point_name)
      │             └─ Region field (e.g. ATL, MED…)
      └─ Survey date (YYYYMMDD) + deployment time HHmm
           (extracted from the video filename stem, or from video_observation.time)
```

**Example:** `202608051148_ATL_CC260080`
- `20260805` — survey date (5 Aug 2026)
- `1148` — deployment time (11:48)
- `ATL` — region
- `CC` — zone, `26` — year 2026, `0080` — station number 80

If the metadata is incomplete (no date, region or zone filled in), BenthOS falls back to the original video stem as the folder name.

| Output | Format | Generated by |
|---|---|---|
| `YYMMDD_infoStation.csv` | CSV | "Générer InfoStation" button on the Metadata page — one row per video |
| `<renamed>/IMG/` | JPG | Extraction page — image batch with optional CLAHE / colour correction |
| `<renamed>.json` | JSON | Export — the `_temp.json` copied and renamed to the final station code |
| `<renamed>.lnk` | Windows shortcut | Export — points back to the raw `.mp4` on the original drive |
| `Annotation_VIAME.csv` | CSV | Export — events pre-formatted for [VIAME](https://github.com/VIAME/VIAME), an open-source tool for fish detection and annotation |

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
