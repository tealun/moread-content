"""Storage module — save articles to disk, maintain index and fetch-history for dedup.

Layout:
    output/
    ├── articles/
    │   ├── 2025-01-15/
    │   │   ├── abcd1234.json
    │   │   └── ef567890.json
    │   └── 2025-01-16/
    │       └── ...
    ├── index.json                # summary of all saved articles
    └── .fetch_history.json       # {url_hash: timestamp} for dedup
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Storage:
    """File-system storage for fetched articles."""

    def __init__(self, config: Dict[str, Any]):
        storage_cfg = config.get("storage", {})
        self.articles_dir = os.path.abspath(
            storage_cfg.get("output_dir", "./output/articles")
        )
        self.index_file = os.path.abspath(
            storage_cfg.get("index_file", "./output/index.json")
        )
        self.history_file = os.path.abspath(
            storage_cfg.get("history_file", "./output/.fetch_history.json")
        )

        # Ensure directories exist
        os.makedirs(self.articles_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)

        # In-memory caches (loaded on demand)
        self._history: Optional[Dict[str, str]] = None
        self._index: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # History (dedup)
    # ------------------------------------------------------------------

    def _load_history(self) -> Dict[str, str]:
        if self._history is not None:
            return self._history
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load fetch history: %s", e)
                self._history = {}
        else:
            self._history = {}
        return self._history

    def _save_history(self) -> None:
        if self._history is None:
            return
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self._history, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("Failed to save fetch history: %s", e)

    @staticmethod
    def _url_hash(url: str) -> str:
        """Short deterministic hash for a URL."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    def is_fetched(self, url: str) -> bool:
        """Check if a URL has already been fetched."""
        h = self._url_hash(url)
        return h in self._load_history()

    def _record_fetched(self, url: str) -> None:
        h = self._url_hash(url)
        self._load_history()[h] = datetime.utcnow().isoformat() + "Z"

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _load_index(self) -> List[Dict[str, Any]]:
        if self._index is not None:
            return self._index
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load index: %s", e)
                self._index = []
        else:
            self._index = []
        return self._index

    def _save_index(self) -> None:
        if self._index is None:
            return
        try:
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("Failed to save index: %s", e)

    def _append_index(self, article: Dict[str, Any], filepath: str) -> None:
        """Append a lightweight summary to the index."""
        summary = {
            "id": article.get("id", ""),
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "cefr_level": article.get("cefr_level", ""),
            "difficulty_score": article.get("difficulty_score", 0),
            "topics": article.get("topics", []),
            "fetched_date": article.get("fetched_date", ""),
            "file": filepath,
        }
        self._load_index().append(summary)

    # ------------------------------------------------------------------
    # Save a single article
    # ------------------------------------------------------------------

    def save(self, article: Dict[str, Any]) -> Optional[str]:
        """Save an article JSON file and update index + history.

        Returns the relative file path on success, or None if the article
        was already saved (dedup).
        """
        url = article.get("source_url", "")
        if not url:
            logger.warning("Article missing source_url, skipping save: %s",
                           article.get("title", "?")[:40])
            return None

        # Dedup check
        if self.is_fetched(url):
            logger.debug("Already fetched, skipping: %s", url)
            return None

        # Determine date-based subdirectory
        fetched_date = article.get("fetched_date", "")
        try:
            dt = datetime.fromisoformat(fetched_date.replace("Z", "+00:00"))
            date_dir = dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            date_dir = datetime.utcnow().strftime("%Y-%m-%d")

        day_dir = os.path.join(self.articles_dir, date_dir)
        os.makedirs(day_dir, exist_ok=True)

        article_id = article.get("id", self._url_hash(url))
        filename = f"{article_id}.json"
        filepath = os.path.join(day_dir, filename)

        # Write article JSON
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("Failed to write article file %s: %s", filepath, e)
            return None

        # Update index and history
        rel_path = os.path.relpath(filepath, os.path.dirname(self.index_file))
        self._append_index(article, rel_path)
        self._record_fetched(url)
        self._save_index()
        self._save_history()

        logger.info("Saved article: %s → %s", article.get("title", "?")[:50], filepath)
        return filepath

    # ------------------------------------------------------------------
    # Batch save
    # ------------------------------------------------------------------

    def save_all(self, articles: List[Dict[str, Any]]) -> int:
        """Save a list of articles. Returns the count of newly saved articles."""
        saved = 0
        for article in articles:
            try:
                result = self.save(article)
                if result:
                    saved += 1
            except Exception as e:
                logger.error("Error saving article %s: %s",
                             article.get("id", "?"), e)
        return saved

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_article_count(self) -> int:
        """Return number of articles in the index."""
        return len(self._load_index())

    def get_fetched_count(self) -> int:
        """Return number of unique URLs in fetch history."""
        return len(self._load_history())
