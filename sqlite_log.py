"""SQLite storage backend for BirdGate logs."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from birdgate.analysis.features import AudioFeatures
from birdgate.routing.birdnet_client import Detection
from birdgate.routing.gate import GateDecision

logger = logging.getLogger(__name__)


class SQLiteStorage:
    """SQLite storage backend for window logs and detections."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        site_id TEXT NOT NULL,
        stream_name TEXT NOT NULL,
        rms_total_db REAL NOT NULL,
        rms_bird_band_db REAL NOT NULL,
        rms_low_band_db REAL NOT NULL,
        snr_bird_db REAL NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        window_id INTEGER NOT NULL,
        species TEXT NOT NULL,
        confidence REAL NOT NULL,
        start_time REAL,
        end_time REAL,
        FOREIGN KEY (window_id) REFERENCES windows(id)
    );

    CREATE INDEX IF NOT EXISTS idx_windows_timestamp ON windows(timestamp);
    CREATE INDEX IF NOT EXISTS idx_windows_stream ON windows(stream_name);
    CREATE INDEX IF NOT EXISTS idx_windows_decision ON windows(decision);
    CREATE INDEX IF NOT EXISTS idx_detections_species ON detections(species);
    CREATE INDEX IF NOT EXISTS idx_detections_window ON detections(window_id);
    """

    def __init__(self, path: str | Path, site_id: str):
        self.path = Path(path)
        self.site_id = site_id
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        with self._connection() as conn:
            conn.executescript(self.SCHEMA)
            logger.info(f"Initialized SQLite database at {self.path}")

    @contextmanager
    def _connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO windows (
                    timestamp, site_id, stream_name,
                    rms_total_db, rms_bird_band_db, rms_low_band_db, snr_bird_db,
                    decision, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp.isoformat(),
                    self.site_id,
                    stream_name,
                    features.rms_total_db,
                    features.rms_bird_band_db,
                    features.rms_low_band_db,
                    features.snr_bird_db,
                    decision.value,
                    reason,
                ),
            )
            window_id = cursor.lastrowid

            # Log detections if any
            if detections:
                for detection in detections:
                    conn.execute(
                        """
                        INSERT INTO detections (
                            window_id, species, confidence, start_time, end_time
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            window_id,
                            detection.species,
                            detection.confidence,
                            detection.start_time,
                            detection.end_time,
                        ),
                    )

            return window_id

    def get_recent_windows(
        self,
        limit: int = 100,
        stream_name: str | None = None,
        decision: GateDecision | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent window logs with optional filtering."""
        query = "SELECT * FROM windows WHERE 1=1"
        params: list[Any] = []

        if stream_name:
            query += " AND stream_name = ?"
            params.append(stream_name)
        
        if decision:
            query += " AND decision = ?"
            params.append(decision.value)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_detections_for_window(self, window_id: int) -> list[dict[str, Any]]:
        """Get all detections for a specific window."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM detections WHERE window_id = ? ORDER BY confidence DESC",
                (window_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_species_summary(
        self,
        since: datetime | None = None,
        stream_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get summary of detected species with counts and max confidence."""
        query = """
            SELECT 
                d.species,
                COUNT(*) as detection_count,
                MAX(d.confidence) as max_confidence,
                AVG(d.confidence) as avg_confidence
            FROM detections d
            JOIN windows w ON d.window_id = w.id
            WHERE 1=1
        """
        params: list[Any] = []

        if since:
            query += " AND w.timestamp >= ?"
            params.append(since.isoformat())
        
        if stream_name:
            query += " AND w.stream_name = ?"
            params.append(stream_name)

        query += " GROUP BY d.species ORDER BY detection_count DESC"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_decision_stats(
        self,
        since: datetime | None = None,
        stream_name: str | None = None,
    ) -> dict[str, int]:
        """Get counts of each decision type."""
        query = "SELECT decision, COUNT(*) as count FROM windows WHERE 1=1"
        params: list[Any] = []

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        
        if stream_name:
            query += " AND stream_name = ?"
            params.append(stream_name)

        query += " GROUP BY decision"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["decision"]: row["count"] for row in rows}
