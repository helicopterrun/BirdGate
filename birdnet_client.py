"""BirdNET integration clients."""

import json
import logging
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from birdgate.config import BirdNETConfig

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single BirdNET detection result."""
    species: str
    confidence: float
    start_time: float = 0.0
    end_time: float = 0.0


class BirdNETClient(ABC):
    """Abstract base class for BirdNET clients."""

    @abstractmethod
    def analyze(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> list[Detection]:
        """
        Analyze audio samples and return detections.
        
        Args:
            samples: Audio samples (float32, normalized)
            sample_rate: Sample rate in Hz
        
        Returns:
            List of detections sorted by confidence (descending)
        """
        pass


class BirdNETHttpClient(BirdNETClient):
    """Client for BirdNET-Go HTTP API."""

    def __init__(self, config: BirdNETConfig):
        self.config = config
        self.session = requests.Session()

    def analyze(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> list[Detection]:
        """Analyze audio via BirdNET-Go HTTP API."""
        # Write samples to a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Write WAV file
            sf.write(str(temp_path), samples, sample_rate)

            # Send to BirdNET-Go
            with open(temp_path, "rb") as f:
                files = {"audio": ("audio.wav", f, "audio/wav")}
                params = {
                    "lat": self.config.latitude,
                    "lon": self.config.longitude,
                    "min_confidence": self.config.min_confidence,
                }
                
                response = self.session.post(
                    self.config.http_url,
                    files=files,
                    params=params,
                    timeout=self.config.http_timeout,
                )

            response.raise_for_status()
            data = response.json()

            # Parse response (BirdNET-Go format)
            detections = []
            
            # Handle different response formats
            if isinstance(data, list):
                # List of detections
                for item in data:
                    if isinstance(item, dict):
                        species = item.get("scientific_name") or item.get("common_name") or item.get("species", "Unknown")
                        confidence = float(item.get("confidence", 0))
                        detections.append(Detection(
                            species=species,
                            confidence=confidence,
                            start_time=float(item.get("start_time", 0)),
                            end_time=float(item.get("end_time", 0)),
                        ))
            elif isinstance(data, dict):
                # Single detection or wrapped response
                if "detections" in data:
                    return self._parse_detections(data["detections"])
                elif "species" in data or "scientific_name" in data:
                    species = data.get("scientific_name") or data.get("common_name") or data.get("species", "Unknown")
                    detections.append(Detection(
                        species=species,
                        confidence=float(data.get("confidence", 0)),
                    ))

            # Filter by confidence and sort
            detections = [d for d in detections if d.confidence >= self.config.min_confidence]
            detections.sort(key=lambda d: d.confidence, reverse=True)
            
            return detections[:self.config.top_n]

        except requests.RequestException as e:
            logger.error(f"BirdNET HTTP request failed: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse BirdNET response: {e}")
            return []
        except Exception as e:
            logger.error(f"BirdNET analysis error: {e}")
            return []
        finally:
            # Clean up temp file
            try:
                temp_path.unlink()
            except Exception:
                pass

    def _parse_detections(self, data: list) -> list[Detection]:
        """Parse a list of detection objects."""
        detections = []
        for item in data:
            if isinstance(item, dict):
                species = item.get("scientific_name") or item.get("common_name") or item.get("species", "Unknown")
                confidence = float(item.get("confidence", 0))
                if confidence >= self.config.min_confidence:
                    detections.append(Detection(
                        species=species,
                        confidence=confidence,
                        start_time=float(item.get("start_time", 0)),
                        end_time=float(item.get("end_time", 0)),
                    ))
        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections[:self.config.top_n]


class BirdNETCliClient(BirdNETClient):
    """Client for BirdNET-Analyzer CLI."""

    def __init__(self, config: BirdNETConfig):
        self.config = config

    def analyze(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> list[Detection]:
        """Analyze audio via BirdNET-Analyzer CLI."""
        # Write samples to a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_audio_path = Path(f.name)
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_output_path = Path(f.name)

        try:
            # Write WAV file
            sf.write(str(temp_audio_path), samples, sample_rate)

            # Build CLI command
            cmd = self.config.cli_path.split()
            cmd.extend([
                "--i", str(temp_audio_path),
                "--o", str(temp_output_path.parent),
                "--lat", str(self.config.latitude),
                "--lon", str(self.config.longitude),
                "--min_conf", str(self.config.min_confidence),
                "--rtype", "json",
            ])
            
            if self.config.cli_model_path:
                cmd.extend(["--classifier", self.config.cli_model_path])

            logger.debug(f"Running BirdNET CLI: {' '.join(cmd)}")

            # Run BirdNET-Analyzer
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.http_timeout,
            )

            if result.returncode != 0:
                logger.error(f"BirdNET CLI failed: {result.stderr}")
                return []

            # Find and parse output file
            # BirdNET-Analyzer creates files like: audio.BirdNET.results.json
            output_pattern = temp_audio_path.stem + "*.json"
            output_files = list(temp_output_path.parent.glob(output_pattern))
            
            if not output_files:
                logger.warning("No BirdNET output file found")
                return []

            with open(output_files[0], "r") as f:
                data = json.load(f)

            # Parse results
            detections = []
            
            # BirdNET-Analyzer output format
            if isinstance(data, dict) and "results" in data:
                for result_item in data["results"]:
                    for detection in result_item.get("detections", []):
                        species = detection.get("scientific_name", detection.get("common_name", "Unknown"))
                        confidence = float(detection.get("confidence", 0))
                        if confidence >= self.config.min_confidence:
                            detections.append(Detection(
                                species=species,
                                confidence=confidence,
                            ))
            elif isinstance(data, list):
                for item in data:
                    species = item.get("scientific_name", item.get("common_name", "Unknown"))
                    confidence = float(item.get("confidence", 0))
                    if confidence >= self.config.min_confidence:
                        detections.append(Detection(
                            species=species,
                            confidence=confidence,
                        ))

            # Sort by confidence and limit
            detections.sort(key=lambda d: d.confidence, reverse=True)
            return detections[:self.config.top_n]

        except subprocess.TimeoutExpired:
            logger.error("BirdNET CLI timed out")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse BirdNET CLI output: {e}")
            return []
        except Exception as e:
            logger.error(f"BirdNET CLI analysis error: {e}")
            return []
        finally:
            # Clean up temp files
            for path in [temp_audio_path, temp_output_path]:
                try:
                    path.unlink()
                except Exception:
                    pass
            # Also try to clean up the actual output file
            try:
                for f in temp_output_path.parent.glob(temp_audio_path.stem + "*.json"):
                    f.unlink()
            except Exception:
                pass


def create_birdnet_client(config: BirdNETConfig) -> BirdNETClient:
    """Factory function to create the appropriate BirdNET client."""
    if config.mode == "http":
        return BirdNETHttpClient(config)
    elif config.mode == "cli":
        return BirdNETCliClient(config)
    else:
        raise ValueError(f"Unknown BirdNET mode: {config.mode}")
