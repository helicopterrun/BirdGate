"""Main processing pipeline for BirdGate."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from birdgate.analysis import AudioFeatures, FeatureExtractor
from birdgate.config import Config, StreamConfig
from birdgate.ingest import AudioWindow, RTSPReader
from birdgate.routing import (
    AudioGate,
    BirdNETClient,
    Detection,
    GateDecision,
    create_birdnet_client,
)
from birdgate.storage import Storage, create_storage

logger = logging.getLogger(__name__)


class StreamPipeline:
    """Processing pipeline for a single audio stream."""

    def __init__(
        self,
        stream_config: StreamConfig,
        config: Config,
        storage: Storage,
        birdnet_client: BirdNETClient,
    ):
        self.stream_config = stream_config
        self.config = config
        self.storage = storage
        self.birdnet_client = birdnet_client
        
        self.reader = RTSPReader(
            stream_config,
            reconnect_delay=config.reconnect_delay_seconds,
            max_reconnect_delay=config.max_reconnect_delay_seconds,
        )
        self.feature_extractor = FeatureExtractor(
            sample_rate=stream_config.sample_rate,
            bird_band=config.bird_band,
            low_band=config.low_band,
        )
        self.gate = AudioGate(config.gating)
        
        self._running = False
        self._thread: threading.Thread | None = None

    def _process_window(self, window: AudioWindow) -> None:
        """Process a single audio window through the pipeline."""
        try:
            # Extract features
            features = self.feature_extractor.extract(window.samples)
            
            # Apply gating
            gate_result = self.gate.evaluate(features)
            
            # Log decision
            detections: list[Detection] = []
            
            if gate_result.decision == GateDecision.SEND_TO_BIRDNET:
                # Send to BirdNET for analysis
                detections = self.birdnet_client.analyze(
                    window.samples,
                    window.sample_rate,
                )
                
                if detections:
                    logger.info(
                        f"[{window.stream_name}] Detections: "
                        f"{', '.join(f'{d.species} ({d.confidence:.2f})' for d in detections)}"
                    )
                else:
                    logger.debug(f"[{window.stream_name}] No detections (sent to BirdNET)")
            else:
                logger.debug(
                    f"[{window.stream_name}] {gate_result.decision.value}: {gate_result.reason}"
                )

            # Store results
            self.storage.log_window(
                timestamp=window.timestamp,
                stream_name=window.stream_name,
                features=features,
                decision=gate_result.decision,
                reason=gate_result.reason,
                detections=detections if detections else None,
            )

        except Exception as e:
            logger.error(f"Error processing window from {window.stream_name}: {e}")

    def run(self) -> None:
        """Run the pipeline continuously."""
        self._running = True
        logger.info(f"Starting pipeline for stream '{self.stream_config.name}'")
        
        for window in self.reader.stream_windows():
            if not self._running:
                break
            self._process_window(window)
        
        logger.info(f"Pipeline for stream '{self.stream_config.name}' stopped")

    def start(self) -> None:
        """Start the pipeline in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"Pipeline for '{self.stream_config.name}' already running")
            return
        
        self._thread = threading.Thread(
            target=self.run,
            name=f"pipeline-{self.stream_config.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False
        self.reader.stop()
        
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None


class BirdGate:
    """Main BirdGate service managing multiple stream pipelines."""

    def __init__(self, config: Config):
        self.config = config
        self.storage = create_storage(config.storage, config.site_id)
        self.birdnet_client = create_birdnet_client(config.birdnet)
        
        self.pipelines: list[StreamPipeline] = []
        for stream_config in config.streams:
            pipeline = StreamPipeline(
                stream_config=stream_config,
                config=config,
                storage=self.storage,
                birdnet_client=self.birdnet_client,
            )
            self.pipelines.append(pipeline)

    def run(self) -> None:
        """Run all pipelines continuously (blocking)."""
        logger.info(
            f"Starting BirdGate with {len(self.pipelines)} stream(s) "
            f"for site '{self.config.site_id}'"
        )
        
        # Start all pipelines
        for pipeline in self.pipelines:
            pipeline.start()
        
        # Wait for all pipelines (they run forever until stopped)
        try:
            for pipeline in self.pipelines:
                if pipeline._thread:
                    pipeline._thread.join()
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down...")
            self.stop()

    def stop(self) -> None:
        """Stop all pipelines."""
        logger.info("Stopping BirdGate...")
        for pipeline in self.pipelines:
            pipeline.stop()
        logger.info("BirdGate stopped")
