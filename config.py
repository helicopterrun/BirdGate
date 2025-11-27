"""Configuration loading and validation for BirdGate."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import yaml


@dataclass
class FrequencyBand:
    """Frequency band definition in Hz."""
    low: float
    high: float

    def __post_init__(self):
        if self.low >= self.high:
            raise ValueError(f"Band low ({self.low}) must be less than high ({self.high})")
        if self.low < 0:
            raise ValueError(f"Band low frequency must be non-negative")


@dataclass
class GatingThresholds:
    """Thresholds for audio gating decisions."""
    min_overall_rms_db: float = -60.0
    min_bird_snr_db: float = 3.0


@dataclass
class StreamConfig:
    """Configuration for a single RTSP stream."""
    name: str
    url: str
    sample_rate: int = 48000
    window_size_seconds: float = 5.0
    channels: int = 1

    def __post_init__(self):
        if self.sample_rate <= 0:
            raise ValueError(f"Sample rate must be positive")
        if self.window_size_seconds <= 0:
            raise ValueError(f"Window size must be positive")


@dataclass
class BirdNETConfig:
    """Configuration for BirdNET backend."""
    mode: Literal["http", "cli"] = "http"
    # HTTP mode settings
    http_url: str = "http://localhost:8080/analyze"
    http_timeout: float = 30.0
    # CLI mode settings
    cli_path: str = "python -m birdnet_analyzer"
    cli_model_path: str | None = None
    # Common settings
    min_confidence: float = 0.1
    top_n: int = 5
    latitude: float = 47.6
    longitude: float = -122.3


@dataclass
class StorageConfig:
    """Configuration for data storage."""
    backend: Literal["sqlite", "jsonl"] = "sqlite"
    path: str = "birdgate.db"


@dataclass
class Config:
    """Main configuration for BirdGate."""
    site_id: str
    streams: list[StreamConfig]
    bird_band: FrequencyBand = field(default_factory=lambda: FrequencyBand(2000, 9000))
    low_band: FrequencyBand = field(default_factory=lambda: FrequencyBand(20, 500))
    gating: GatingThresholds = field(default_factory=GatingThresholds)
    birdnet: BirdNETConfig = field(default_factory=BirdNETConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    reconnect_delay_seconds: float = 5.0
    max_reconnect_delay_seconds: float = 60.0

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create configuration from a dictionary."""
        # Parse streams
        streams = []
        for stream_data in data.get("streams", []):
            streams.append(StreamConfig(**stream_data))
        
        if not streams:
            raise ValueError("At least one stream must be configured")

        # Parse frequency bands
        bird_band_data = data.get("bird_band", {"low": 2000, "high": 9000})
        bird_band = FrequencyBand(**bird_band_data)
        
        low_band_data = data.get("low_band", {"low": 20, "high": 500})
        low_band = FrequencyBand(**low_band_data)

        # Parse gating thresholds
        gating_data = data.get("gating", {})
        gating = GatingThresholds(**gating_data)

        # Parse BirdNET config
        birdnet_data = data.get("birdnet", {})
        birdnet = BirdNETConfig(**birdnet_data)

        # Parse storage config
        storage_data = data.get("storage", {})
        storage = StorageConfig(**storage_data)

        return cls(
            site_id=data.get("site_id", "default"),
            streams=streams,
            bird_band=bird_band,
            low_band=low_band,
            gating=gating,
            birdnet=birdnet,
            storage=storage,
            reconnect_delay_seconds=data.get("reconnect_delay_seconds", 5.0),
            max_reconnect_delay_seconds=data.get("max_reconnect_delay_seconds", 60.0),
        )
