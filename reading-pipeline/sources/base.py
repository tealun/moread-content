"""Base class for content sources."""

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "MoreadReadingPipeline/1.0 "
        "(+https://github.com/nousresearch/moread-content; "
        "Educational content aggregator for English learners)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 30  # seconds


def url_to_id(url: str) -> str:
    """Generate a unique ID from a URL using SHA-256."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def clean_text(text: str) -> str:
    """Clean and normalize text content."""
    if not text:
        return ""
    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_page(url: str, session: Optional[requests.Session] = None) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object."""
    try:
        s = session or requests.Session()
        resp = s.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


class SourceBase(ABC):
    """Abstract base class for all content sources."""

    name: str = "unknown"
    base_url: str = ""

    def __init__(self, max_articles: int = 10):
        self.max_articles = max_articles
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    @abstractmethod
    def list_articles(self) -> List[Dict]:
        """Return a list of article metadata dicts with at least 'title' and 'url'."""
        ...

    @abstractmethod
    def fetch_article(self, url: str) -> Optional[Dict]:
        """Fetch and parse a single article, returning structured data."""
        ...

    def fetch_all(self) -> List[Dict]:
        """Fetch all articles from this source."""
        articles = []
        try:
            article_list = self.list_articles()
            logger.info("[%s] Found %d article links", self.name, len(article_list))

            for meta in article_list[: self.max_articles]:
                url = meta.get("url", "")
                if not url:
                    continue
                try:
                    article = self.fetch_article(url)
                    if article:
                        article["source"] = self.name
                        article["source_url"] = url
                        article["id"] = url_to_id(url)
                        article["fetched_date"] = datetime.utcnow().isoformat() + "Z"
                        articles.append(article)
                        logger.info("[%s] Fetched: %s", self.name, article.get("title", url)[:60])
                except Exception as e:
                    logger.error("[%s] Error fetching %s: %s", self.name, url, e)
        except Exception as e:
            logger.error("[%s] Error listing articles: %s", self.name, e)

        logger.info("[%s] Successfully fetched %d articles", self.name, len(articles))
        return articles
