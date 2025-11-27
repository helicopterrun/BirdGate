"""Audio feature extraction for gating decisions."""

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfilt

from birdgate.config import FrequencyBand

logger = logging.getLogger(__name__)


@dataclass
class AudioFeatures:
    """Extracted audio features for a window."""
    rms_total_db: float
    rms_bird_band_db: float
    rms_low_band_db: float
    snr_bird_db: float


def _db_from_rms(rms: float, floor: float = 1e-10) -> float:
    """Convert RMS amplitude to decibels."""
    return 20.0 * np.log10(max(rms, floor))


def _rms(samples: np.ndarray) -> float:
    """Calculate RMS of samples."""
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def _bandpass_filter(
    samples: np.ndarray,
    sample_rate: int,
    low_freq: float,
    high_freq: float,
    order: int = 4,
) -> np.ndarray:
    """
    Apply a Butterworth bandpass filter.
    
    Args:
        samples: Input audio samples
        sample_rate: Sample rate in Hz
        low_freq: Lower cutoff frequency in Hz
        high_freq: Upper cutoff frequency in Hz
        order: Filter order (default 4)
    
    Returns:
        Filtered audio samples
    """
    nyquist = sample_rate / 2.0
    
    # Clamp frequencies to valid range
    low = max(low_freq / nyquist, 0.001)
    high = min(high_freq / nyquist, 0.999)
    
    if low >= high:
        logger.warning(f"Invalid band: {low_freq}-{high_freq} Hz at {sample_rate} Hz sample rate")
        return samples
    
    try:
        sos = butter(order, [low, high], btype="band", output="sos")
        return sosfilt(sos, samples)
    except Exception as e:
        logger.warning(f"Filter error: {e}")
        return samples


def _lowpass_filter(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_freq: float,
    order: int = 4,
) -> np.ndarray:
    """Apply a Butterworth lowpass filter."""
    nyquist = sample_rate / 2.0
    normalized_cutoff = min(cutoff_freq / nyquist, 0.999)
    
    try:
        sos = butter(order, normalized_cutoff, btype="low", output="sos")
        return sosfilt(sos, samples)
    except Exception as e:
        logger.warning(f"Lowpass filter error: {e}")
        return samples


class FeatureExtractor:
    """Extracts audio features for gating decisions."""

    def __init__(
        self,
        sample_rate: int,
        bird_band: FrequencyBand,
        low_band: FrequencyBand,
    ):
        self.sample_rate = sample_rate
        self.bird_band = bird_band
        self.low_band = low_band

    def extract(self, samples: np.ndarray) -> AudioFeatures:
        """
        Extract audio features from a window of samples.
        
        Args:
            samples: Audio samples, float32 normalized to [-1, 1]
        
        Returns:
            AudioFeatures with RMS levels and SNR
        """
        # Total RMS
        rms_total = _rms(samples)
        rms_total_db = _db_from_rms(rms_total)

        # Bird band RMS (typically 2-9 kHz)
        bird_filtered = _bandpass_filter(
            samples,
            self.sample_rate,
            self.bird_band.low,
            self.bird_band.high,
        )
        rms_bird = _rms(bird_filtered)
        rms_bird_band_db = _db_from_rms(rms_bird)

        # Low band RMS (typically 20-500 Hz for traffic/rumble)
        low_filtered = _bandpass_filter(
            samples,
            self.sample_rate,
            self.low_band.low,
            self.low_band.high,
        )
        rms_low = _rms(low_filtered)
        rms_low_band_db = _db_from_rms(rms_low)

        # SNR: how much more energy in bird band vs low band
        snr_bird_db = rms_bird_band_db - rms_low_band_db

        return AudioFeatures(
            rms_total_db=rms_total_db,
            rms_bird_band_db=rms_bird_band_db,
            rms_low_band_db=rms_low_band_db,
            snr_bird_db=snr_bird_db,
        )
