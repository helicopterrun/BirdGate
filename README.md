# BirdGate

Audio gating and filtering service for BirdNET. BirdGate sits between your audio streams (RTSP) and BirdNET, filtering out silence and noise to reduce false positives and unnecessary processing.

## Features

- **RTSP stream ingestion** via FFmpeg with automatic reconnection
- **Frequency-based audio gating**:
  - Silence detection (overall RMS threshold)
  - Bird-band SNR filtering (rejects traffic/rumble)
- **BirdNET integration**:
  - HTTP API (BirdNET-Go)
  - CLI (BirdNET-Analyzer)
- **Comprehensive logging**:
  - SQLite or JSONL storage
  - All metrics, decisions, and detections logged
- **24/7 operation** with robust error handling

## Architecture

```
RTSP Stream(s) → FFmpeg → Audio Windows → Feature Extraction → Gating → BirdNET → Storage
                              │                                 │           │
                              │                                 │           │
                         5-sec chunks                      SILENCE?        Top N
                         @ 48kHz mono                      TRASH?          species
                                                           SEND?
```

## Installation

### Prerequisites

- Python 3.11+
- FFmpeg (for RTSP decoding)
- BirdNET-Go or BirdNET-Analyzer (for bird identification)

### Install from source

```bash
git clone https://github.com/yourusername/birdgate.git
cd birdgate
pip install -e .
```

### Install dependencies only

```bash
pip install numpy scipy soundfile requests pyyaml
```

## Quick Start

1. **Create a configuration file** (`config.yaml`):

```yaml
site_id: "my-site"

streams:
  - name: "main-mic"
    url: "rtsp://localhost:8554/birdmic"
    sample_rate: 48000
    window_size_seconds: 5.0

bird_band:
  low: 2000
  high: 9000

low_band:
  low: 20
  high: 500

gating:
  min_overall_rms_db: -50.0
  min_bird_snr_db: 6.0

birdnet:
  mode: "http"
  http_url: "http://localhost:8080/analyze"
  latitude: 47.68
  longitude: -122.39
  min_confidence: 0.25

storage:
  backend: "sqlite"
  path: "birdgate.db"
```

2. **Run BirdGate**:

```bash
python -m birdgate.scripts.run_birdgate --config config.yaml
```

Or if installed:

```bash
birdgate --config config.yaml
```

3. **Inspect the logs**:

```bash
# Recent windows
python -m birdgate.scripts.inspect_logs --config config.yaml recent

# Species summary
python -m birdgate.scripts.inspect_logs --config config.yaml species

# Decision statistics
python -m birdgate.scripts.inspect_logs --config config.yaml stats
```

## Configuration Reference

### Streams

Each stream defines an RTSP source:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Unique stream identifier |
| `url` | string | required | RTSP URL |
| `sample_rate` | int | 48000 | Sample rate in Hz |
| `window_size_seconds` | float | 5.0 | Analysis window duration |
| `channels` | int | 1 | Audio channels (converted to mono) |

### Frequency Bands

| Band | Default | Purpose |
|------|---------|---------|
| `bird_band` | 2000-9000 Hz | Bird vocalization range |
| `low_band` | 20-500 Hz | Traffic/rumble/HVAC noise |

### Gating Thresholds

| Threshold | Default | Description |
|-----------|---------|-------------|
| `min_overall_rms_db` | -50.0 | Below this = SILENCE |
| `min_bird_snr_db` | 6.0 | Below this = TRASH (likely noise) |

The SNR is calculated as: `RMS(bird_band) - RMS(low_band)`

Higher `min_bird_snr_db` = more selective = fewer windows sent to BirdNET

### BirdNET

| Field | Default | Description |
|-------|---------|-------------|
| `mode` | "http" | "http" (BirdNET-Go) or "cli" (Analyzer) |
| `http_url` | "http://localhost:8080/analyze" | BirdNET-Go endpoint |
| `http_timeout` | 30.0 | Request timeout in seconds |
| `latitude` | 47.6 | Location for species filtering |
| `longitude` | -122.3 | Location for species filtering |
| `min_confidence` | 0.1 | Minimum detection confidence |
| `top_n` | 5 | Max detections per window |

### Storage

| Field | Default | Description |
|-------|---------|-------------|
| `backend` | "sqlite" | "sqlite" or "jsonl" |
| `path` | "birdgate.db" | Database/log file path |

## Database Schema (SQLite)

```sql
-- Windows table
CREATE TABLE windows (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    site_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    rms_total_db REAL NOT NULL,
    rms_bird_band_db REAL NOT NULL,
    rms_low_band_db REAL NOT NULL,
    snr_bird_db REAL NOT NULL,
    decision TEXT NOT NULL,  -- SILENCE, TRASH, or SEND_TO_BIRDNET
    reason TEXT
);

-- Detections table
CREATE TABLE detections (
    id INTEGER PRIMARY KEY,
    window_id INTEGER REFERENCES windows(id),
    species TEXT NOT NULL,
    confidence REAL NOT NULL
);
```

## Tuning Tips

### Too many false triggers (traffic, wind)?

Increase `min_bird_snr_db` (try 8-12 dB)

### Missing quiet bird calls?

- Lower `min_overall_rms_db` (try -55 to -60 dB)
- Lower `min_bird_snr_db` (try 3-5 dB)

### High CPU usage?

- Increase `window_size_seconds` (fewer analyses per minute)
- Raise thresholds to send fewer windows to BirdNET

## Integration with MediaMTX

If using MediaMTX for RTSP, ensure your stream is accessible:

```yaml
# mediamtx.yml
paths:
  birdmic:
    source: "..." # your audio source
    sourceOnDemand: no
```

Then configure BirdGate with:
```yaml
streams:
  - name: "birdmic"
    url: "rtsp://localhost:8554/birdmic"
```

## Logging

BirdGate uses Python's logging module. Enable debug logging with:

```bash
birdgate --config config.yaml --verbose
```

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR on GitHub.
