"""VOA Learning English scraper."""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from sources.base import SourceBase, clean_text, fetch_page

logger = logging.getLogger(__name__)


class VOASource(SourceBase):
    """Scrape articles from VOA Learning English."""

    name = "voa"
    base_url = "https://learningenglish.voanews.com"

    # Section URLs that list articles
    SECTIONS = [
        "/",
        "/z/3521",
        "/z/3522",
        "/z/3523",
        "/z/3524",
        "/z/3525",
    ]

    def list_articles(self) -> List[Dict]:
        """List recent articles from VOA Learning English."""
        articles = []
        seen_urls = set()

        for section in self.SECTIONS:
            if len(articles) >= self.max_articles * 3:
                break
            try:
                page_url = self.base_url + section
                soup = fetch_page(page_url, self.session)
                if not soup:
                    continue

                # Find article links
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    title = clean_text(a_tag.get_text())

                    if not title or len(title) < 8:
                        continue

                    # Normalize URL
                    if href.startswith("/"):
                        full_url = self.base_url + href
                    elif href.startswith("http"):
                        full_url = href
                    else:
                        continue

                    # Filter for article URLs (contain /a/ pattern typical of VOA articles)
                    if "/a/" not in full_url:
                        continue

                    # Remove query strings and fragments
                    full_url = full_url.split("?")[0].split("#")[0]

                    if full_url not in seen_urls:
                        seen_urls.add(full_url)
                        articles.append({"url": full_url, "title": title})

            except Exception as e:
                logger.warning("[voa] Error scraping section %s: %s", section, e)

        return articles

    def fetch_article(self, url: str) -> Optional[Dict]:
        """Fetch and parse a single VOA Learning English article."""
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

        # Extract article content
        content_parts = []

        # VOA uses various content containers
        content_selectors = [
            ".article__content",
            ".body",
            "#article-content",
            ".article-body",
            ".story-body",
            "[data-v-69461a62]",  # sometimes used
        ]

        body_el = None
        for selector in content_selectors:
            body_el = soup.select_one(selector)
            if body_el:
                break

        if not body_el:
            body_el = soup.find("article") or soup.find("main")

        if body_el:
            for p in body_el.find_all(["p", "h2"]):
                text = clean_text(p.get_text())
                # Skip very short lines and media descriptions
                if text and len(text) > 15:
                    # Skip lines that look like image captions or credits
                    if not re.match(r"^\(.*\)$", text) and "Getty Images" not in text:
                        content_parts.append(text)

        content = "\n\n".join(content_parts)

        if len(content) < 50:
            return None

        # Extract date
        pub_date = ""
        date_tag = soup.find("time")
        if date_tag:
            pub_date = date_tag.get("datetime", clean_text(date_tag.get_text()))
        if not pub_date:
            date_meta = soup.find("meta", property="article:published_time")
            if date_meta:
                pub_date = date_meta.get("content", "")
        if not pub_date:
            # VOA sometimes has date spans
            date_span = soup.find("span", class_=re.compile(r"date|time|publish", re.I))
            if date_span:
                pub_date = clean_text(date_span.get_text())

        # Extract author
        author = ""
        author_span = soup.find("span", class_=re.compile(r"author|byline", re.I))
        if author_span:
            author = clean_text(author_span.get_text())
        if not author:
            author_meta = soup.find("meta", attrs={"name": "author"})
            if author_meta:
                author = author_meta.get("content", "")

        return {
            "title": title,
            "content": content,
            "author": author,
            "published_date": pub_date,
        }
