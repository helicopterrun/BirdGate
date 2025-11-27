"""Audio routing modules."""

from birdgate.routing.birdnet_client import (
    BirdNETClient,
    BirdNETCliClient,
    BirdNETHttpClient,
    Detection,
    create_birdnet_client,
)
from birdgate.routing.gate import AudioGate, GateDecision, GateResult

__all__ = [
    "AudioGate",
    "BirdNETClient",
    "BirdNETCliClient",
    "BirdNETHttpClient",
    "Detection",
    "GateDecision",
    "GateResult",
    "create_birdnet_client",
]
