"""BBC Learning English scraper."""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Tag

from sources.base import SourceBase, clean_text, fetch_page

logger = logging.getLogger(__name__)


class BBCSource(SourceBase):
    """Scrape articles from BBC Learning English."""

    name = "bbc"
    base_url = "https://www.bbc.co.uk/learningenglish"

    # Course paths to explore for articles
    COURSE_PATHS = [
        "/english/features/news-review",
        "/english/features/lingohack",
        "/english/features/6-minute-english",
        "/english/features/english-at-work",
        "/english/course/lower-intermediate",
        "/english/course/intermediate",
        "/english/course/towards-advanced",
    ]

    def list_articles(self) -> List[Dict]:
        """List recent articles from BBC Learning English."""
        articles = []
        seen_urls = set()

        for path in self.COURSE_PATHS:
            if len(articles) >= self.max_articles * 3:
                break
            try:
                page_urls = self._scrape_course_page(path)
                for item in page_urls:
                    url = item["url"]
                    if url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(item)
            except Exception as e:
                logger.warning("[bbc] Error scraping %s: %s", path, e)

        return articles

    def _scrape_course_page(self, path: str) -> List[Dict]:
        """Scrape links from a course listing page."""
        url = self.base_url + path
        soup = fetch_page(url, self.session)
        if not soup:
            return []

        results = []
        # BBC LE uses various link patterns
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = clean_text(a_tag.get_text())

            # Filter for article/course links
            if not title or len(title) < 5:
                continue

            # Normalize URL
            if href.startswith("/"):
                full_url = "https://www.bbc.co.uk" + href
            elif href.startswith("http"):
                full_url = href
            else:
                continue

            # Only include learning english pages
            if "/learningenglish/" not in full_url:
                continue

            # Skip non-article pages
            skip_patterns = [
                "#", "/courses/", "/english/features$", "\?.*$",
                "facebook", "twitter", "instagram", "youtube",
            ]
            if any(re.search(p, full_url) for p in skip_patterns):
                continue

            results.append({"url": full_url, "title": title})

        return results

    def fetch_article(self, url: str) -> Optional[Dict]:
        """Fetch and parse a single BBC Learning English article."""
        soup = fetch_page(url, self.session)
        if not soup:
            return None

        # Extract title
        title = ""
        title_tag = soup.find("h1")
        if title_tag:
            title = clean_text(title_tag.get_text())
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = clean_text(og_title.get("content", ""))

        if not title:
            return None

        # Extract article body
        content_parts = []

        # BBC LE articles use various container patterns
        content_selectors = [
            ".story-body__inner",
            ".article__body",
            ".bb-wp-content",
            ".article-body",
            "#article-content",
            ".text",
            "[data-widget-type='body']",
        ]

        body_el = None
        for selector in content_selectors:
            body_el = soup.select_one(selector)
            if body_el:
                break

        if not body_el:
            # Fallback: look for the main content area
            body_el = soup.find("article") or soup.find("main")

        if body_el:
            # Extract paragraphs, skipping scripts and styles
            for p in body_el.find_all(["p", "h2", "h3"]):
                text = clean_text(p.get_text())
                if text and len(text) > 10:  # Skip very short fragments
                    content_parts.append(text)

        content = "\n\n".join(content_parts)

        if len(content) < 50:
            # Not enough content, skip
            return None

        # Try to extract date
        pub_date = ""
        date_tag = soup.find("time")
        if date_tag:
            pub_date = date_tag.get("datetime", date_tag.get_text("").strip())
        if not pub_date:
            date_meta = soup.find("meta", property="article:published_time")
            if date_meta:
                pub_date = date_meta.get("content", "")

        # Try to extract author
        author = ""
        author_tag = soup.find("span", class_=re.compile(r"author|byline", re.I))
        if author_tag:
            author = clean_text(author_tag.get_text())
        if not author:
            author_meta = soup.find("meta", attrs={"name": "author"})
            if author_meta:
                author = author_meta.get("content", "")

        # Estimate CEFR from URL path hints
        cefr_hint = ""
        if "lower-intermediate" in url or "6-minute" in url:
            cefr_hint = "A2"
        elif "intermediate" in url:
            cefr_hint = "B1"
        elif "towards-advanced" in url:
            cefr_hint = "B2"

        return {
            "title": title,
            "content": content,
            "author": author,
            "published_date": pub_date,
            "_cefr_hint": cefr_hint,
        }
