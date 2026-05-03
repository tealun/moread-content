"""News in Levels scraper."""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from sources.base import SourceBase, clean_text, fetch_page

logger = logging.getLogger(__name__)


class NewsInLevelsSource(SourceBase):
    """Scrape articles from News in Levels (newsinlevels.com)."""

    name = "newsinlevels"
    base_url = "https://www.newsinlevels.com"

    # Level pages
    LEVEL_PAGES = [
        "/level-1/",  # Level 1 - very easy
        "/level-2/",  # Level 2 - easy
        "/level-3/",  # Level 3 - medium
    ]

    LEVEL_CEFR_MAP = {
        "level-1": "A1",
        "level-2": "A2",
        "level-3": "B1",
    }

    def list_articles(self) -> List[Dict]:
        """List recent articles across all levels."""
        articles = []
        seen_urls = set()

        for level_page in self.LEVEL_PAGES:
            if len(articles) >= self.max_articles * 3:
                break
            try:
                page_url = self.base_url + level_page
                soup = fetch_page(page_url, self.session)
                if not soup:
                    continue

                # Determine level from page
                level_key = level_page.strip("/").split("/")[-1]
                cefr_hint = self.LEVEL_CEFR_MAP.get(level_key, "")

                # Find article links — News in Levels lists articles on each level page
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    title = clean_text(a_tag.get_text())

                    if not title or len(title) < 5:
                        continue

                    # Normalize URL
                    if href.startswith("/"):
                        full_url = self.base_url + href
                    elif href.startswith("http"):
                        full_url = href
                    else:
                        continue

                    # Filter for article URLs
                    if "newsinlevels.com" not in full_url:
                        continue

                    # Skip navigation and non-article links
                    skip = False
                    for skip_pat in ["level-1", "level-2", "level-3", "about", "contact",
                                     "privacy", "terms", "category", "page/", "#"]:
                        if skip_pat in full_url and full_url.endswith(skip_pat + "/"):
                            skip = True
                            break
                    if skip:
                        continue

                    # Clean URL
                    full_url = full_url.split("?")[0].split("#")[0]
                    if not full_url.endswith("/"):
                        full_url += "/"

                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        articles.append({
                            "url": full_url,
                            "title": title,
                            "_cefr_hint": cefr_hint,
                        })

            except Exception as e:
                logger.warning("[newsinlevels] Error scraping %s: %s", level_page, e)

        return articles

    def fetch_article(self, url: str) -> Optional[Dict]:
        """Fetch and parse a single News in Levels article."""
        soup = fetch_page(url, self.session)
        if not soup:
            return None

        # Extract title
        title = ""
        title_tag = soup.find("h1") or soup.find("h2", class_=re.compile(r"title|entry-title", re.I))
        if title_tag:
            title = clean_text(title_tag.get_text())
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = clean_text(og_title.get("content", ""))

        if not title:
            return None

        # Extract content
        content_parts = []

        content_selectors = [
            ".entry-content",
            ".post-content",
            ".article-content",
            "#content",
            "article",
        ]

        body_el = None
        for selector in content_selectors:
            body_el = soup.select_one(selector)
            if body_el:
                break

        if not body_el:
            body_el = soup.find("main")

        if body_el:
            for p in body_el.find_all(["p", "h2", "h3"]):
                text = clean_text(p.get_text())
                if text and len(text) > 10:
                    content_parts.append(text)

        content = "\n\n".join(content_parts)

        if len(content) < 30:
            return None

        # Try to detect level from the page
        cefr_hint = ""
        level_links = soup.find_all("a", href=re.compile(r"level-[123]"))
        for link in level_links:
            href = link.get("href", "")
            for level_key, cefr in self.LEVEL_CEFR_MAP.items():
                if level_key in href and "active" in (link.get("class") or []):
                    cefr_hint = cefr
                    break

        # Fallback: detect from URL
        if not cefr_hint:
            for level_key, cefr in self.LEVEL_CEFR_MAP.items():
                if level_key in url:
                    cefr_hint = cefr
                    break

        # Extract date
        pub_date = ""
        time_tag = soup.find("time")
        if time_tag:
            pub_date = time_tag.get("datetime", clean_text(time_tag.get_text()))
        if not pub_date:
            date_meta = soup.find("meta", property="article:published_time")
            if date_meta:
                pub_date = date_meta.get("content", "")

        return {
            "title": title,
            "content": content,
            "author": "News in Levels",
            "published_date": pub_date,
            "_cefr_hint": cefr_hint,
        }
