"""JSONL storage backend for BirdGate logs."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from birdgate.analysis.features import AudioFeatures
from birdgate.routing.birdnet_client import Detection
from birdgate.routing.gate import GateDecision

logger = logging.getLogger(__name__)


class JSONLStorage:
    """JSONL (JSON Lines) storage backend for window logs."""

    def __init__(self, path: str | Path, site_id: str):
        self.path = Path(path)
        self.site_id = site_id
        self._window_id = 0
        self._init_storage()

    def _init_storage(self):
        """Initialize the storage file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Count existing lines to set window ID
        if self.path.exists():
            with open(self.path, "r") as f:
                self._window_id = sum(1 for _ in f)
        
        logger.info(f"Initialized JSONL storage at {self.path} (starting ID: {self._window_id})")

    def log_window(
        self,
        timestamp: datetime,
        stream_name: str,
        features: AudioFeatures,
        decision: GateDecision,
        reason: str,
        detections: list[Detection] | None = None,
    ) -> int:
        """
        Log a processed audio window.
        
        Args:
            timestamp: Window timestamp (UTC)
            stream_name: Name of the source stream
            features: Extracted audio features
            decision: Gating decision
            reason: Reason for the decision
            detections: BirdNET detections (if any)
        
        Returns:
            The window ID
        """
        self._window_id += 1
        
        record = {
            "id": self._window_id,
            "timestamp": timestamp.isoformat(),
            "site_id": self.site_id,
            "stream_name": stream_name,
            "features": {
                "rms_total_db": features.rms_total_db,
                "rms_bird_band_db": features.rms_bird_band_db,
                "rms_low_band_db": features.rms_low_band_db,
                "snr_bird_db": features.snr_bird_db,
            },
            "decision": decision.value,
            "reason": reason,
            "detections": [
                {
                    "species": d.species,
                    "confidence": d.confidence,
                    "start_time": d.start_time,
                    "end_time": d.end_time,
                }
                for d in (detections or [])
            ],
        }

        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

        return self._window_id

    def get_recent_windows(
        self,
        limit: int = 100,
        stream_name: str | None = None,
        decision: GateDecision | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent window logs with optional filtering."""
        if not self.path.exists():
            return []

        results = []
        
        with open(self.path, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    
                    # Apply filters
                    if stream_name and record.get("stream_name") != stream_name:
                        continue
                    if decision and record.get("decision") != decision.value:
                        continue
                    
                    results.append(record)
                except json.JSONDecodeError:
                    continue

        # Return most recent (last N lines)
        return list(reversed(results[-limit:]))

    def get_detections_for_window(self, window_id: int) -> list[dict[str, Any]]:
        """Get all detections for a specific window."""
        if not self.path.exists():
            return []

        with open(self.path, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if record.get("id") == window_id:
                        return record.get("detections", [])
                except json.JSONDecodeError:
                    continue

        return []

    def get_species_summary(
        self,
        since: datetime | None = None,
        stream_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get summary of detected species with counts and max confidence."""
        if not self.path.exists():
            return []

        species_stats: dict[str, dict[str, Any]] = {}

        with open(self.path, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    
                    # Apply filters
                    if since:
                        record_time = datetime.fromisoformat(record["timestamp"])
                        if record_time < since:
                            continue
                    
                    if stream_name and record.get("stream_name") != stream_name:
                        continue

                    for detection in record.get("detections", []):
                        species = detection["species"]
                        confidence = detection["confidence"]
                        
                        if species not in species_stats:
                            species_stats[species] = {
                                "species": species,
                                "detection_count": 0,
                                "max_confidence": 0,
                                "total_confidence": 0,
                            }
                        
                        stats = species_stats[species]
                        stats["detection_count"] += 1
                        stats["max_confidence"] = max(stats["max_confidence"], confidence)
                        stats["total_confidence"] += confidence

                except json.JSONDecodeError:
                    continue

        # Calculate averages and sort
        results = []
        for stats in species_stats.values():
            stats["avg_confidence"] = stats["total_confidence"] / stats["detection_count"]
            del stats["total_confidence"]
            results.append(stats)

        results.sort(key=lambda x: x["detection_count"], reverse=True)
        return results

    def get_decision_stats(
        self,
        since: datetime | None = None,
        stream_name: str | None = None,
    ) -> dict[str, int]:
        """Get counts of each decision type."""
        if not self.path.exists():
            return {}

        counts: dict[str, int] = {}

        with open(self.path, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    
                    # Apply filters
                    if since:
                        record_time = datetime.fromisoformat(record["timestamp"])
                        if record_time < since:
                            continue
                    
                    if stream_name and record.get("stream_name") != stream_name:
                        continue

                    decision = record.get("decision", "UNKNOWN")
                    counts[decision] = counts.get(decision, 0) + 1

                except json.JSONDecodeError:
                    continue

        return counts
