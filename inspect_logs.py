#!/usr/bin/env python3
"""Utility script for inspecting BirdGate logs."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from birdgate.config import Config
from birdgate.routing.gate import GateDecision
from birdgate.storage import create_storage


def format_timestamp(ts: str) -> str:
    """Format ISO timestamp for display."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def cmd_recent(storage, args):
    """Show recent windows."""
    decision = None
    if args.decision:
        try:
            decision = GateDecision(args.decision.upper())
        except ValueError:
            print(f"Invalid decision: {args.decision}")
            print(f"Valid values: {', '.join(d.value for d in GateDecision)}")
            sys.exit(1)

    windows = storage.get_recent_windows(
        limit=args.limit,
        stream_name=args.stream,
        decision=decision,
    )

    if not windows:
        print("No windows found")
        return

    print(f"{'Timestamp':<20} {'Stream':<15} {'Decision':<15} {'RMS':>8} {'Bird':>8} {'SNR':>8}")
    print("-" * 85)
    
    for w in windows:
        # Handle both dict formats (SQLite returns flat, JSONL returns nested)
        if "features" in w:
            rms = w["features"]["rms_total_db"]
            bird = w["features"]["rms_bird_band_db"]
            snr = w["features"]["snr_bird_db"]
        else:
            rms = w.get("rms_total_db", 0)
            bird = w.get("rms_bird_band_db", 0)
            snr = w.get("snr_bird_db", 0)
        
        print(
            f"{format_timestamp(w['timestamp']):<20} "
            f"{w['stream_name']:<15} "
            f"{w['decision']:<15} "
            f"{rms:>8.1f} "
            f"{bird:>8.1f} "
            f"{snr:>8.1f}"
        )


def cmd_species(storage, args):
    """Show species summary."""
    since = None
    if args.hours:
        since = datetime.utcnow() - timedelta(hours=args.hours)

    summary = storage.get_species_summary(
        since=since,
        stream_name=args.stream,
    )

    if not summary:
        print("No detections found")
        return

    print(f"{'Species':<40} {'Count':>8} {'Max Conf':>10} {'Avg Conf':>10}")
    print("-" * 70)
    
    for s in summary:
        print(
            f"{s['species']:<40} "
            f"{s['detection_count']:>8} "
            f"{s['max_confidence']:>10.2f} "
            f"{s['avg_confidence']:>10.2f}"
        )


def cmd_stats(storage, args):
    """Show decision statistics."""
    since = None
    if args.hours:
        since = datetime.utcnow() - timedelta(hours=args.hours)

    stats = storage.get_decision_stats(
        since=since,
        stream_name=args.stream,
    )

    if not stats:
        print("No data found")
        return

    total = sum(stats.values())
    
    print("Decision Statistics")
    print("-" * 40)
    
    for decision, count in sorted(stats.items()):
        pct = (count / total * 100) if total > 0 else 0
        print(f"{decision:<20} {count:>10} ({pct:>5.1f}%)")
    
    print("-" * 40)
    print(f"{'Total':<20} {total:>10}")


def cmd_detections(storage, args):
    """Show detections for a window."""
    detections = storage.get_detections_for_window(args.window_id)
    
    if not detections:
        print(f"No detections found for window {args.window_id}")
        return

    print(f"Detections for window {args.window_id}:")
    print("-" * 50)
    
    for d in detections:
        conf = d.get("confidence", 0)
        print(f"  {d['species']:<35} {conf:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="Inspect BirdGate logs",
    )
    
    parser.add_argument(
        "--config", "-c",
        type=Path,
        required=True,
        help="Path to YAML configuration file",
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Recent windows
    recent = subparsers.add_parser("recent", help="Show recent windows")
    recent.add_argument("-n", "--limit", type=int, default=20, help="Number of windows")
    recent.add_argument("-s", "--stream", help="Filter by stream name")
    recent.add_argument("-d", "--decision", help="Filter by decision")
    
    # Species summary
    species = subparsers.add_parser("species", help="Show species summary")
    species.add_argument("--hours", type=float, help="Only include last N hours")
    species.add_argument("-s", "--stream", help="Filter by stream name")
    
    # Decision stats
    stats = subparsers.add_parser("stats", help="Show decision statistics")
    stats.add_argument("--hours", type=float, help="Only include last N hours")
    stats.add_argument("-s", "--stream", help="Filter by stream name")
    
    # Window detections
    detections = subparsers.add_parser("detections", help="Show detections for a window")
    detections.add_argument("window_id", type=int, help="Window ID")
    
    args = parser.parse_args()
    
    # Load config and create storage
    try:
        config = Config.from_yaml(args.config)
    except Exception as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)
    
    storage = create_storage(config.storage, config.site_id)
    
    # Run command
    commands = {
        "recent": cmd_recent,
        "species": cmd_species,
        "stats": cmd_stats,
        "detections": cmd_detections,
    }
    
    commands[args.command](storage, args)


if __name__ == "__main__":
    main()
