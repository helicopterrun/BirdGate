"""Storage backends for BirdGate logs."""

from typing import Protocol

from birdgate.config import StorageConfig
from birdgate.storage.jsonl_log import JSONLStorage
from birdgate.storage.sqlite_log import SQLiteStorage


class Storage(Protocol):
    """Protocol for storage backends."""

    def log_window(self, *args, **kwargs) -> int:
        ...

    def get_recent_windows(self, *args, **kwargs) -> list:
        ...

    def get_detections_for_window(self, window_id: int) -> list:
        ...

    def get_species_summary(self, *args, **kwargs) -> list:
        ...

    def get_decision_stats(self, *args, **kwargs) -> dict:
        ...


def create_storage(config: StorageConfig, site_id: str) -> Storage:
    """Factory function to create the appropriate storage backend."""
    if config.backend == "sqlite":
        return SQLiteStorage(config.path, site_id)
    elif config.backend == "jsonl":
        return JSONLStorage(config.path, site_id)
    else:
        raise ValueError(f"Unknown storage backend: {config.backend}")


__all__ = [
    "JSONLStorage",
    "SQLiteStorage",
    "Storage",
    "create_storage",
]
