"""Article analysis module — CEFR grading, difficulty scoring, keyword extraction, topic classification.

Supports two modes:
  1. Rule-based analysis (always available, used as fallback).
  2. LLM-based analysis (optional, requires llm_base_url in config or env vars).
"""

import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# English stop-words (top ~150 common function words)
# ---------------------------------------------------------------------------
STOP_WORDS = frozenset(
    """
    a an the and or but if then else when where who whom whose which what how
    is am are was were be been being have has had do does did will would shall
    should may might must can could of in on at to for with from by about as
    into through during before after above below between under over out up down
    off again further once here there when where why how all both each few more
    most other some such no not only own same so than too very just because
    also still already even much many well really quite rather enough
    i me my mine myself we us our ours ourselves you your yours yourself
    he him his himself she her hers herself it its itself they them their
    theirs themselves this that these those it its
    said says say saying one two three four five six seven eight nine ten
    also new like get go come make know take see think look want give use find
    tell ask work seem feel try leave call
    mr mrs ms dr
    """.split()
)

# ---------------------------------------------------------------------------
# Topic keyword dictionaries  (English words → Chinese topic label)
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "科技": [
        "technology", "computer", "software", "internet", "digital", "robot",
        "ai", "artificial intelligence", "algorithm", "data", "phone",
        "smartphone", "app", "online", "cyber", "tech", "machine learning",
        "science", "scientific", "research", "experiment", "space", "nasa",
        "satellite", "engineer", "innovation", "device", "electric",
    ],
    "健康": [
        "health", "medical", "doctor", "hospital", "disease", "medicine",
        "vaccine", "virus", "covid", "pandemic", "patient", "treatment",
        "surgery", "mental", "diet", "exercise", "fitness", "obesity",
        "cancer", "heart", "brain", "drug", "therapy", "symptom", "infection",
    ],
    "教育": [
        "education", "school", "student", "teacher", "university", "college",
        "learn", "study", "exam", "classroom", "curriculum", "academic",
        "degree", "scholarship", "homework", "lesson", "library", "campus",
    ],
    "环境": [
        "environment", "climate", "weather", "pollution", "carbon", "emission",
        "renewable", "solar", "wind", "energy", "forest", "ocean", "species",
        "animal", "wildlife", "recycle", "global warming", "ecosystem",
        "drought", "flood", "earthquake", "volcano", "nature",
    ],
    "经济": [
        "economy", "economic", "money", "bank", "finance", "market", "trade",
        "business", "company", "industry", "stock", "investment", "tax",
        "inflation", "gdp", "employment", "salary", "price", "cost",
        "growth", "recession", "currency", "profit", "revenue",
    ],
    "政治": [
        "politics", "political", "government", "president", "election",
        "vote", "parliament", "congress", "senate", "law", "court",
        "judge", "policy", "democracy", "minister", "leader", "party",
        "legislation", "campaign", "candidate",
    ],
    "体育": [
        "sport", "football", "soccer", "basketball", "tennis", "olympics",
        "athlete", "game", "match", "team", "player", "coach", "champion",
        "tournament", "race", "competition", "win", "score", "goal",
    ],
    "文化": [
        "culture", "music", "art", "film", "movie", "book", "literature",
        "history", "museum", "festival", "tradition", "language", "dance",
        "theatre", "theater", "painting", "artist", "actor", "writer",
    ],
    "社会": [
        "social", "society", "community", "family", "children", "people",
        "population", "immigration", "crime", "police", "justice", "rights",
        "equality", "gender", "race", "religion", "marriage", "divorce",
        "homeless", "poverty", "charity",
    ],
    "旅游": [
        "travel", "tourism", "tourist", "flight", "hotel", "destination",
        "airport", "vacation", "holiday", "visit", "trip", "journey",
        "landmark", "attraction", "guide", "passport", "visa",
    ],
}

# Flatten for fast lookup
_TOPIC_LOOKUP: Dict[str, str] = {}
for _topic, _words in TOPIC_KEYWORDS.items():
    for _w in _words:
        _TOPIC_LOOKUP[_w] = _topic


# ---------------------------------------------------------------------------
# Helper: simple tokeniser (split on non-alpha, keep words)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-zA-Z']+")


def _tokenise(text: str) -> List[str]:
    """Return a list of lowercase word tokens from *text*."""
    return [w.lower() for w in _WORD_RE.findall(text) if len(w) > 1]


def _sentences(text: str) -> List[str]:
    """Rough sentence splitter."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in parts if s.strip()]


# ---------------------------------------------------------------------------
# Rule-based analysis
# ---------------------------------------------------------------------------

def _compute_cefr(
    avg_sentence_len: float,
    word_count: int,
    avg_word_len: float,
) -> Tuple[str, int]:
    """Return (cefr_level, difficulty_score 0-100) based on statistical rules."""

    # Weighted scoring — each metric contributes to a raw score 0-100
    # Sentence length weight: 40%
    # Article length weight:  35%
    # Word length weight:     25%

    # Sentence length score (0-100)
    if avg_sentence_len < 8:
        sl_score = avg_sentence_len / 8 * 25
    elif avg_sentence_len < 12:
        sl_score = 25 + (avg_sentence_len - 8) / 4 * 15
    elif avg_sentence_len < 18:
        sl_score = 40 + (avg_sentence_len - 12) / 6 * 20
    elif avg_sentence_len < 22:
        sl_score = 60 + (avg_sentence_len - 18) / 4 * 15
    elif avg_sentence_len < 30:
        sl_score = 75 + (avg_sentence_len - 22) / 8 * 15
    else:
        sl_score = min(100, 90 + (avg_sentence_len - 30) / 5 * 10)

    # Article length score (0-100)
    if word_count < 100:
        al_score = word_count / 100 * 25
    elif word_count < 200:
        al_score = 25 + (word_count - 100) / 100 * 10
    elif word_count < 400:
        al_score = 35 + (word_count - 200) / 200 * 15
    elif word_count < 800:
        al_score = 50 + (word_count - 400) / 400 * 20
    elif word_count < 1500:
        al_score = 70 + (word_count - 800) / 700 * 15
    else:
        al_score = min(100, 85 + (word_count - 1500) / 1500 * 15)

    # Word length score (0-100)
    if avg_word_len < 4.0:
        wl_score = avg_word_len / 4.0 * 30
    elif avg_word_len < 5.0:
        wl_score = 30 + (avg_word_len - 4.0) * 20
    elif avg_word_len < 6.0:
        wl_score = 50 + (avg_word_len - 5.0) * 25
    else:
        wl_score = min(100, 75 + (avg_word_len - 6.0) * 25)

    raw = sl_score * 0.40 + al_score * 0.35 + wl_score * 0.25
    difficulty = max(0, min(100, round(raw)))

    # Map to CEFR
    if difficulty < 20:
        cefr = "A1"
    elif difficulty < 35:
        cefr = "A2"
    elif difficulty < 55:
        cefr = "B1"
    elif difficulty < 72:
        cefr = "B2"
    elif difficulty < 88:
        cefr = "C1"
    else:
        cefr = "C2"

    return cefr, difficulty


def _extract_keywords(tokens: List[str], top_n: int = 15) -> List[str]:
    """Return the top-N highest-frequency content words (excluding stop-words)."""
    content_words = [t for t in tokens if t not in STOP_WORDS and len(t) > 2]
    counter = Counter(content_words)
    return [w for w, _ in counter.most_common(top_n)]


def _classify_topics(tokens: List[str]) -> List[str]:
    """Infer topic(s) from token overlap with topic keyword dicts."""
    topic_hits: Dict[str, int] = Counter()
    lower_tokens = set(tokens)
    for tok in lower_tokens:
        if tok in _TOPIC_LOOKUP:
            topic_hits[_TOPIC_LOOKUP[tok]] += 1
    if not topic_hits:
        return ["综合"]
    # Return topics sorted by hit count, at most 3
    return [t for t, _ in topic_hits.most_common(3)]


def _cefr_to_grade(cefr: str) -> str:
    """Map CEFR level to an approximate Chinese school grade."""
    mapping = {
        "A1": "小学3-4年级",
        "A2": "小学5-6年级",
        "B1": "初中1-2年级",
        "B2": "初中3年级-高中1年级",
        "C1": "高中2-3年级",
        "C2": "大学及以上",
    }
    return mapping.get(cefr, "未知")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_rule_based(article: Dict[str, Any]) -> Dict[str, Any]:
    """Pure rule-based analysis. Returns analysis dict to merge into article."""

    content = article.get("content", "")
    if not content:
        logger.warning("Article has no content, skipping analysis: %s",
                       article.get("title", "?")[:40])
        return _empty_analysis()

    tokens = _tokenise(content)
    word_count = len(tokens)
    if word_count == 0:
        return _empty_analysis()

    sentences_list = _sentences(content)
    sentence_count = max(len(sentences_list), 1)
    avg_sentence_len = word_count / sentence_count

    # Average word length (character length)
    avg_word_len = sum(len(w) for w in tokens) / word_count

    # CEFR + difficulty
    cefr_hint = article.get("_cefr_hint", "")
    cefr, difficulty = _compute_cefr(avg_sentence_len, word_count, avg_word_len)

    # If the source already gave a CEFR hint (e.g. News in Levels), prefer it
    # but still let the difficulty score reflect the computed value.
    if cefr_hint and cefr_hint in ("A1", "A2", "B1", "B2", "C1", "C2"):
        final_cefr = cefr_hint
    else:
        final_cefr = cefr

    keywords = _extract_keywords(tokens)
    topics = _classify_topics(tokens)
    grade = _cefr_to_grade(final_cefr)

    return {
        "cefr_level": final_cefr,
        "difficulty_score": difficulty,
        "grade_level": grade,
        "topics": topics,
        "key_vocabulary": keywords,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_len, 1),
        "avg_word_length": round(avg_word_len, 2),
    }


def analyze_llm(article: Dict[str, Any], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt LLM-based analysis. Returns None on failure (so caller can fallback)."""

    base_url = (
        config.get("llm_base_url")
        or os.environ.get("READING_LLM_BASE_URL", "")
    ).strip()
    api_key = (
        config.get("llm_api_key")
        or os.environ.get("READING_LLM_KEY", "")
    ).strip()
    model = config.get("llm_model", "gpt-4o-mini")

    if not base_url or not api_key:
        return None

    try:
        import json
        import requests as req

        content = article.get("content", "")[:3000]  # truncate to avoid huge prompts
        title = article.get("title", "")

        prompt = (
            "You are an English-teaching expert. Analyse the following article and return a JSON object with these fields:\n"
            '- "cefr_level": one of A1, A2, B1, B2, C1, C2\n'
            '- "difficulty_score": integer 0-100\n'
            '- "grade_level": approximate Chinese school grade (e.g. "初中2年级")\n'
            '- "topics": list of 1-3 Chinese topic labels\n'
            '- "key_vocabulary": list of up to 10 important English words/phrases from the text\n'
            '- "grammar_points": list of up to 5 grammar patterns found in the text\n'
            '- "title_zh": Chinese translation of the title\n'
            '- "summary_zh": 1-2 sentence Chinese summary\n\n'
            f"Title: {title}\n\n"
            f"Content:\n{content}\n\n"
            "Return ONLY valid JSON."
        )

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 800,
        }

        resp = req.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()

        text = resp.json()["choices"][0]["message"]["content"]
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)

        # Normalise fields
        cefr = result.get("cefr_level", "").upper()
        if cefr not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            cefr = "B1"
        result["cefr_level"] = cefr
        result["difficulty_score"] = int(result.get("difficulty_score", 50))
        result.setdefault("key_vocabulary", [])
        result.setdefault("grammar_points", [])
        result.setdefault("topics", [])
        result.setdefault("title_zh", "")
        result.setdefault("summary_zh", "")

        # Also add computed word stats
        tokens = _tokenise(article.get("content", ""))
        result["word_count"] = len(tokens)
        result["avg_sentence_length"] = round(
            len(tokens) / max(len(_sentences(article.get("content", ""))), 1), 1
        )
        result["avg_word_length"] = round(
            sum(len(w) for w in tokens) / max(len(tokens), 1), 2
        )

        logger.info("LLM analysis successful for: %s", title[:50])
        return result

    except Exception as e:
        logger.warning("LLM analysis failed, falling back to rules: %s", e)
        return None


def analyze(article: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Analyse an article. Tries LLM first (if configured), then falls back to rules.

    Returns the *article dict* with analysis fields merged in.
    """
    config = config or {}

    # Try LLM first
    llm_result = analyze_llm(article, config)
    if llm_result:
        article.update(llm_result)
        # Remove internal hint
        article.pop("_cefr_hint", None)
        return article

    # Fallback: rule-based
    rule_result = analyze_rule_based(article)
    article.update(rule_result)

    # Add empty fields that LLM would have provided
    article.setdefault("grammar_points", [])
    article.setdefault("title_zh", "")
    article.setdefault("summary_zh", "")

    # Remove internal hint
    article.pop("_cefr_hint", None)
    return article


def _empty_analysis() -> Dict[str, Any]:
    """Return a minimal analysis dict for empty / unparseable articles."""
    return {
        "cefr_level": "未知",
        "difficulty_score": 0,
        "grade_level": "未知",
        "topics": [],
        "key_vocabulary": [],
        "grammar_points": [],
        "word_count": 0,
        "sentence_count": 0,
        "avg_sentence_length": 0,
        "avg_word_length": 0,
        "title_zh": "",
        "summary_zh": "",
    }
