"""Audio gating logic for routing decisions."""

from dataclasses import dataclass
from enum import Enum

from birdgate.analysis.features import AudioFeatures
from birdgate.config import GatingThresholds


class GateDecision(Enum):
    """Possible gating decisions for an audio window."""
    SILENCE = "SILENCE"
    TRASH = "TRASH"
    SEND_TO_BIRDNET = "SEND_TO_BIRDNET"


@dataclass
class GateResult:
    """Result of gating decision with explanation."""
    decision: GateDecision
    reason: str


class AudioGate:
    """Applies gating rules to determine if audio should be sent to BirdNET."""

    def __init__(self, thresholds: GatingThresholds):
        self.thresholds = thresholds

    def evaluate(self, features: AudioFeatures) -> GateResult:
        """
        Evaluate audio features and return gating decision.
        
        Decision logic:
        1. If overall RMS is below threshold -> SILENCE (nothing to analyze)
        2. If bird band SNR is below threshold -> TRASH (likely traffic/noise)
        3. Otherwise -> SEND_TO_BIRDNET (potential bird audio)
        
        Args:
            features: Extracted audio features
        
        Returns:
            GateResult with decision and reason
        """
        # Check for silence
        if features.rms_total_db < self.thresholds.min_overall_rms_db:
            return GateResult(
                decision=GateDecision.SILENCE,
                reason=f"RMS {features.rms_total_db:.1f} dB < threshold {self.thresholds.min_overall_rms_db:.1f} dB",
            )

        # Check bird band SNR
        if features.snr_bird_db < self.thresholds.min_bird_snr_db:
            return GateResult(
                decision=GateDecision.TRASH,
                reason=f"Bird SNR {features.snr_bird_db:.1f} dB < threshold {self.thresholds.min_bird_snr_db:.1f} dB",
            )

        # Audio passes gate
        return GateResult(
            decision=GateDecision.SEND_TO_BIRDNET,
            reason=f"RMS {features.rms_total_db:.1f} dB, Bird SNR {features.snr_bird_db:.1f} dB",
        )
