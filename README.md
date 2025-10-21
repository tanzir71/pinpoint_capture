# PinPoint Capture

Lightweight screen recorder with click‑focused smart zoom. Capture your screen and optional microphone audio, and save precise MP4 recordings — ideal for tutorials, bug reports, and handoffs.

## Features
- Click‑focused smart zoom to spotlight interactions
- Screen + optional microphone audio
- MP4 output saved to `recordings/`
- Configurable zoom level and duration
- Simple, compact UI built with PyQt6
- Runs locally on Windows, macOS, and Linux

## Getting Started

### Requirements
- Python 3.8+
- pip

### Setup (Windows/macOS/Linux)
```bash
# From the project root
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

## Recording Output
- Recordings are saved under `recordings/` with timestamped filenames.
- Logs are written to `logs/pinpoint_capture.log`.

## Configuration
- Basic settings (zoom level, duration, etc.) can be adjusted in-app.
- Persisted settings live in `config/settings.json`.

## Links
- Repo: https://github.com/tanzir71/pinpoint_capture
- Releases: https://github.com/tanzir71/pinpoint_capture/releases/tag/Release

## Contributing
Issues and pull requests are welcome. Please open an issue to discuss any major changes first.