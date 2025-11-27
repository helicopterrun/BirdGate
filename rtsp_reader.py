"""RTSP audio stream ingestion using FFmpeg."""

import logging
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from birdgate.config import StreamConfig

logger = logging.getLogger(__name__)


@dataclass
class AudioWindow:
    """A window of audio samples with metadata."""
    samples: np.ndarray  # Shape: (num_samples,), dtype: float32, normalized to [-1, 1]
    timestamp: datetime
    stream_name: str
    sample_rate: int
    duration_seconds: float


class RTSPReader:
    """Reads audio from an RTSP stream using FFmpeg."""

    def __init__(
        self,
        stream_config: StreamConfig,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
    ):
        self.config = stream_config
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._process: subprocess.Popen | None = None
        self._running = False

    def _start_ffmpeg(self) -> subprocess.Popen:
        """Start FFmpeg process to decode RTSP stream to raw PCM."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            # Input options
            "-rtsp_transport", "tcp",  # More reliable than UDP
            "-i", self.config.url,
            # Output options
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # 16-bit signed little-endian
            "-ar", str(self.config.sample_rate),
            "-ac", str(self.config.channels),
            "-f", "s16le",  # Raw PCM format
            "-",  # Output to stdout
        ]

        logger.info(f"Starting FFmpeg for stream '{self.config.name}': {self.config.url}")
        
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,  # Unbuffered for real-time
        )

    def _read_window(self) -> AudioWindow | None:
        """Read a single window of audio samples."""
        if self._process is None or self._process.poll() is not None:
            return None

        # Calculate bytes needed for one window
        samples_per_window = int(self.config.sample_rate * self.config.window_size_seconds)
        bytes_per_sample = 2  # 16-bit = 2 bytes
        bytes_needed = samples_per_window * self.config.channels * bytes_per_sample

        # Read raw PCM data
        raw_data = self._process.stdout.read(bytes_needed)
        
        if len(raw_data) < bytes_needed:
            logger.warning(
                f"Incomplete read from stream '{self.config.name}': "
                f"got {len(raw_data)} bytes, expected {bytes_needed}"
            )
            return None

        # Convert to numpy array
        samples_int16 = np.frombuffer(raw_data, dtype=np.int16)
        
        # Normalize to float32 [-1, 1]
        samples = samples_int16.astype(np.float32) / 32768.0

        # If stereo, convert to mono by averaging channels
        if self.config.channels > 1:
            samples = samples.reshape(-1, self.config.channels).mean(axis=1)

        return AudioWindow(
            samples=samples,
            timestamp=datetime.now(timezone.utc),
            stream_name=self.config.name,
            sample_rate=self.config.sample_rate,
            duration_seconds=self.config.window_size_seconds,
        )

    def stop(self):
        """Stop the FFmpeg process."""
        self._running = False
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            logger.info(f"Stopped stream '{self.config.name}'")

    def stream_windows(self) -> Generator[AudioWindow, None, None]:
        """
        Continuously yield audio windows from the RTSP stream.
        
        Handles reconnection with exponential backoff on stream failures.
        """
        self._running = True
        current_delay = self.reconnect_delay

        while self._running:
            try:
                self._process = self._start_ffmpeg()
                current_delay = self.reconnect_delay  # Reset delay on successful start

                while self._running:
                    window = self._read_window()
                    if window is None:
                        # Stream ended or error
                        break
                    yield window

            except Exception as e:
                logger.error(f"Error reading stream '{self.config.name}': {e}")

            finally:
                if self._process is not None:
                    self._process.terminate()
                    try:
                        stderr = self._process.stderr.read()
                        if stderr:
                            logger.debug(f"FFmpeg stderr: {stderr.decode('utf-8', errors='replace')}")
                    except Exception:
                        pass
                    self._process = None

            if self._running:
                logger.info(
                    f"Stream '{self.config.name}' disconnected, "
                    f"reconnecting in {current_delay:.1f}s..."
                )
                time.sleep(current_delay)
                # Exponential backoff
                current_delay = min(current_delay * 2, self.max_reconnect_delay)

        logger.info(f"Stream '{self.config.name}' reader stopped")
