#!/usr/bin/env python3
"""Moread Reading Pipeline — main entry point.

Usage:
    python pipeline.py --once [--source bbc] [--dry-run] [--config path]
    python pipeline.py --daemon [--source bbc] [--config path]
"""

import argparse
import importlib
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Resolve base directory (wherever this script lives)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from analyzer import analyze  # noqa: E402
from storage import Storage  # noqa: E402

logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Daemon shutdown flag
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %s, shutting down gracefully …", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load YAML config. Falls back to config.yaml next to this script."""
    if config_path is None:
        config_path = str(BASE_DIR / "config.yaml")
    config_path = os.path.abspath(config_path)
    if not os.path.exists(config_path):
        logger.warning("Config file not found: %s — using defaults", config_path)
        return _default_config()
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    logger.info("Loaded config from %s", config_path)
    return cfg


def _default_config() -> Dict[str, Any]:
    return {
        "sources": {},
        "analyzer": {},
        "storage": {
            "output_dir": "./output/articles",
            "index_file": "./output/index.json",
            "history_file": "./output/.fetch_history.json",
        },
        "schedule": {"interval_minutes": 360},
    }


# ---------------------------------------------------------------------------
# Source initialisation
# ---------------------------------------------------------------------------

def init_sources(config: Dict[str, Any], source_filter: Optional[str] = None
                 ) -> List[Any]:
    """Instantiate enabled source scrapers and return a list of SourceBase objects."""
    from sources import ALL_SOURCES

    sources_cfg = config.get("sources", {})
    instances = []

    for name, cls in ALL_SOURCES.items():
        src_cfg = sources_cfg.get(name, {})
        if not src_cfg.get("enabled", False):
            logger.debug("Source '%s' is disabled, skipping", name)
            continue
        if source_filter and name != source_filter:
            logger.debug("Source '%s' filtered out (--source %s)", name, source_filter)
            continue
        max_articles = int(src_cfg.get("max_articles", 10))
        instances.append(cls(max_articles=max_articles))
        logger.info("Initialised source: %s (max_articles=%d)", name, max_articles)

    if not instances:
        logger.warning("No sources enabled%s", f" (filter: {source_filter})" if source_filter else "")
    return instances


# ---------------------------------------------------------------------------
# Single pipeline run
# ---------------------------------------------------------------------------

def run_once(
    config: Dict[str, Any],
    sources: List[Any],
    *,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Execute one fetch → analyse → store cycle.

    Returns a stats dict: {fetched, analysed, saved, errors}.
    """
    stats = {"fetched": 0, "analysed": 0, "saved": 0, "errors": 0}
    analyzer_cfg = config.get("analyzer", {})
    storage = Storage(config) if not dry_run else None

    if dry_run:
        logger.info("=== DRY-RUN mode — articles will NOT be saved ===")

    for source in sources:
        name = getattr(source, "name", "unknown")
        logger.info("--- Fetching from source: %s ---", name)
        try:
            articles = source.fetch_all()
        except Exception as e:
            logger.error("[%s] fetch_all failed: %s", name, e)
            stats["errors"] += 1
            continue

        stats["fetched"] += len(articles)

        for article in articles:
            try:
                # Analyse
                analyze(article, analyzer_cfg)
                stats["analysed"] += 1

                cefr = article.get("cefr_level", "?")
                diff = article.get("difficulty_score", 0)
                topics = ", ".join(article.get("topics", []))
                logger.info(
                    "  [%s] %s | CEFR=%s diff=%d topics=[%s] words=%d",
                    name,
                    article.get("title", "?")[:50],
                    cefr,
                    diff,
                    topics,
                    article.get("word_count", 0),
                )

                # Store
                if not dry_run and storage:
                    saved_path = storage.save(article)
                    if saved_path:
                        stats["saved"] += 1

            except Exception as e:
                logger.error("[%s] Error processing article %s: %s",
                             name, article.get("id", "?"), e)
                stats["errors"] += 1

    logger.info(
        "Run complete — fetched: %d, analysed: %d, saved: %d, errors: %d",
        stats["fetched"], stats["analysed"], stats["saved"], stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------

def run_daemon(
    config: Dict[str, Any],
    sources: List[Any],
    *,
    dry_run: bool = False,
) -> None:
    """Run the pipeline in a loop with a configurable interval."""
    interval = config.get("schedule", {}).get("interval_minutes", 360)
    interval_sec = int(interval) * 60
    logger.info("Daemon mode — polling every %d minutes (%d seconds)", interval, interval_sec)

    cycle = 0
    while not _shutdown:
        cycle += 1
        logger.info("====== Daemon cycle #%d ======", cycle)
        try:
            run_once(config, sources, dry_run=dry_run)
        except Exception as e:
            logger.error("Unexpected error in daemon cycle: %s", e)

        if _shutdown:
            break

        # Sleep in small increments so we can react to signals quickly
        logger.info("Sleeping %d minutes until next cycle …", interval)
        for _ in range(interval_sec):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Daemon shut down cleanly after %d cycle(s)", cycle)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Moread Reading Pipeline — fetch, analyse, store English reading material.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run once and exit.")
    mode.add_argument("--daemon", action="store_true",
                      help="Run continuously, polling at the configured interval.")

    p.add_argument("--source", type=str, default=None,
                   help="Only run the specified source (e.g. bbc, voa, newsinlevels).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and analyse but do NOT write to disk.")
    p.add_argument("--config", type=str, default=None,
                   help="Path to config.yaml (default: ./config.yaml).")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable DEBUG-level logging.")
    return p


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quieten noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    config = load_config(args.config)
    sources = init_sources(config, source_filter=args.source)

    if not sources:
        logger.error("No sources to process. Check config.yaml and --source flag.")
        sys.exit(1)

    if args.once:
        stats = run_once(config, sources, dry_run=args.dry_run)
        sys.exit(1 if stats["errors"] > 0 else 0)
    elif args.daemon:
        run_daemon(config, sources, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
