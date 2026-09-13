# limbo-windows-python

Python-only Windows desktop version of the LIMBO-style key shuffle minigame.

Repository URL:
https://github.com/TechItAll/Windows-Limbo-Keys.git

## Requirements

- Windows
- Python 3.13+
- PySide6 (see requirements.txt)

## Setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
py -3.13 main.py --debug
```

Run without debug menu:

```powershell
py -3.13 main.py
```

## Controls

- Left click a key window to pick
- Double right click any key window before shuffle starts to open settings
- Ctrl+C in terminal stops the program

## Debug Highlights

- Random movement is default; original set-pattern movement is optional
- Show-correct overlay mode (green, full key window)
- Forced correct key/color selection with rainbow end-order mapping
- Crash on Death option:
  - OFF by default
  - Requires Administrator to enable
  - Hold button for 3 seconds to turn ON
  - Single click turns OFF
  - Warning dialog appears when enabled and again when starting a run with it ON
  - On wrong pick, runs: `cmd /c echo HELLOCHANGE`

## Data Path

Save config path:

```text
%APPDATA%\limbo-windows-python\limbosave.cfg
```
