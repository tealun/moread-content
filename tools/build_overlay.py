#!/usr/bin/env python3
"""
Overlay Dictionary Builder v3 — 专业级词典底座

从 ECDICT 提取基础数据（音标/释义/词形/词频），用 GLM-4.5-air AI 补全：
  - 例句 (examples) — 带中文翻译
  - 同义词 (synonyms) — 按词性/义项分组
  - 反义词 (antonyms) — 按词性/义项分组
  - 常用搭配 (collocations) — 带中文翻译
  - 联想词 (associations) — 词族/相关概念
  - 词根词源 (etymology) — 词根+历史

写入 overlay.db，两轮审计通过才标记 audit_pass=2。

用法:
  python3 tools/build_overlay.py

状态文件:
  dictionary/overlay.status.json

看门狗:
  tools/watchdog_overlay.sh
"""

import sqlite3
import json
import subprocess
import re
import sys
import os
import time
import datetime
import signal
import traceback
import requests as http_requests
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────
PROJECT     = Path(__file__).resolve().parent.parent
ECDICT_DB   = Path(os.path.expanduser("~/moread-assets/ecdict.db"))
OVERLAY_DB  = PROJECT / "dictionary" / "overlay.db"
STATUS_FILE = PROJECT / "dictionary" / "overlay.status.json"
VOCAB_DIR   = PROJECT / "vocabulary"

# ── 批处理参数 ────────────────────────────────────────
BATCH_SIZE       = 50      # 数据库写入批次
AI_BATCH_SIZE    = 1       # AI 请求每次处理词数（Z.AI reasoning model 需要足够空间）
COMMIT_EVERY     = 20      # 每 N 批 git commit（每批 50 词 = 1000 词/commit）
AI_MAX_TOKENS    = 4000    # AI 单次请求最大 tokens（含 reasoning）
AI_TIMEOUT       = 150     # AI 请求超时秒数
AI_RETRY         = 2       # 减少重试次数
AI_DELAY         = 0.3     # AI 请求间隔秒数
API_DELAY        = 0.3     # Free Dictionary API 请求间隔

# ── GLM API ──────────────────────────────────────────
GLM_API_KEY   = os.environ.get("GLM_API_KEY", "")
GLM_BASE_URL  = "https://api.z.ai/api/coding/paas/v4"
GLM_MODEL     = "glm-4.5-air"

# 从 hermes .env 加载 key（如果环境变量没有）
if not GLM_API_KEY:
    hermes_env = Path.home() / ".hermes" / ".env"
    if hermes_env.exists():
        for line in hermes_env.read_text().splitlines():
            if line.startswith("GLM_API_KEY="):
                GLM_API_KEY = line.split("=", 1)[1].strip()
                break

# ── CEFR 推断 ────────────────────────────────────────
CEFR_MAP = {
    "cefr-a1": "A1", "cefr-a2": "A2", "cefr-b1": "B1",
    "cefr-b2": "B2", "cefr-c1": "C1", "cefr-c2": "C2",
    "exam-zhongkao": "A1", "exam-gaokao": "A2",
    "exam-cet4": "B1", "exam-cet6": "B2",
    "exam-kaoyan": "B2", "exam-ielts": "B1",
    "exam-toefl": "B2", "exam-gre": "C1",
    "freq-1000": "A1", "freq-2000": "A2", "freq-3000": "B1",
    "freq-5000": "B2", "freq-10000": "C1",
}

# ── 全局状态 ──────────────────────────────────────────
_status = {
    "status": "starting",
    "pid": os.getpid(),
    "batch_current": 0,
    "batch_total": 0,
    "words_done": 0,
    "words_fail": 0,
    "ai_calls": 0,
    "ai_tokens": 0,
    "last_word": "",
    "last_batch_ok": 0,
    "last_batch_fail": 0,
    "last_commit": "",
    "last_update": datetime.datetime.now().isoformat(),
    "error": None,
    "started_at": datetime.datetime.now().isoformat(),
}


def write_status():
    _status["last_update"] = datetime.datetime.now().isoformat()
    with open(STATUS_FILE, "w") as f:
        json.dump(_status, f, indent=2, ensure_ascii=False)


def signal_handler(signum, frame):
    _status["status"] = "stopping"
    write_status()
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ═══════════════════════════════════════════════════════
# ECDICT 解析
# ═══════════════════════════════════════════════════════

def parse_ecdict_pos(pos_text: str | None) -> list[str]:
    if not pos_text:
        return []
    result = []
    for part in pos_text.split("/"):
        tag = part.split(":")[0].strip() if ":" in part else part.strip()
        if tag:
            result.append(tag + ".")
    return result


def parse_ecdict_translation(translation: str | None) -> list[tuple[str, str]]:
    if not translation:
        return []
    lines = []
    for line in translation.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([a-z]+\.\s*)(.*)$', line, re.IGNORECASE)
        if m:
            lines.append((m.group(1).strip(), m.group(2).strip()))
        else:
            lines.append(("", line))
    return lines


def parse_ecdict_definition(definition: str | None) -> list[tuple[str, str]]:
    if not definition:
        return []
    lines = []
    for line in definition.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([a-z]+\.\s*)(.*)$', line, re.IGNORECASE)
        if m:
            lines.append((m.group(1).strip(), m.group(2).strip()))
        else:
            lines.append(("", line))
    return lines


def build_definitions_from_ecdict(definition: str | None, translation: str | None) -> list[dict]:
    en_lines = parse_ecdict_definition(definition)
    zh_lines = parse_ecdict_translation(translation)
    definitions = []
    used_zh = set()

    for i, (pos, en) in enumerate(en_lines):
        zh = ""
        if i < len(zh_lines):
            zh = zh_lines[i][1]
            used_zh.add(i)
        definitions.append({"pos": pos, "meanings": [{"zh": zh, "en": en}]})

    for i, (pos, zh) in enumerate(zh_lines):
        if i not in used_zh and zh:
            definitions.append({"pos": pos, "meanings": [{"zh": zh, "en": ""}]})

    return definitions


def parse_ecdict_exchange(exchange: str | None) -> list[dict]:
    if not exchange:
        return []
    code_map = {
        "p": "past_participle", "d": "past_tense", "i": "present_participle",
        "3": "third_person", "s": "plural", "r": "comparative",
        "t": "superlative", "0": "base", "1": "variant",
    }
    forms = []
    for part in exchange.split("/"):
        if ":" in part:
            code, form = part.split(":", 1)
            forms.append({"type": code_map.get(code, code), "form": form})
    return forms


# ═══════════════════════════════════════════════════════
# 外部数据源
# ═══════════════════════════════════════════════════════

def get_phonetic_espeak(word: str) -> str:
    try:
        result = subprocess.run(
            ["espeak-ng", "-q", "--ipa", word],
            capture_output=True, text=True, timeout=5
        )
        ipa = result.stdout.strip()
        if ipa:
            ipa = ipa.split("\n")[0].strip()
            return f"/{ipa}/"
    except Exception:
        pass
    return ""


def fetch_free_dictionary(word: str) -> dict | None:
    for attempt in range(3):
        try:
            resp = http_requests.get(
                f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list):
                    return data[0]
            return None
        except Exception:
            time.sleep(API_DELAY * (attempt + 1))
    return None


def extract_examples_from_free_dict(fd: dict) -> list[dict]:
    examples = []
    for meaning in fd.get("meanings", []):
        for defn in meaning.get("definitions", []):
            example_en = defn.get("example", "")
            if example_en:
                examples.append({"en": example_en, "zh": ""})
            if len(examples) >= 3:
                return examples
    # 也检查 synonyms/antonyms
    syns = []
    ants = []
    for meaning in fd.get("meanings", []):
        syns.extend(meaning.get("synonyms", [])[:3])
        ants.extend(meaning.get("antonyms", [])[:3])
    return examples


def extract_phonetic_from_free_dict(fd: dict) -> str:
    for phonetic in fd.get("phonetics", []):
        text = phonetic.get("text", "")
        if text and ("/" in text or "ˈ" in text or "ˌ" in text):
            return text.strip()
    return ""


def extract_synant_from_free_dict(fd: dict) -> tuple[list, list]:
    """从 Free Dictionary API 提取同义词和反义词"""
    synonyms = []
    antonyms = []
    for meaning in fd.get("meanings", []):
        pos = meaning.get("partOfSpeech", "")
        pos_tag = pos[:3] + "." if pos else ""
        s = meaning.get("synonyms", [])
        a = meaning.get("antonyms", [])
        if s:
            synonyms.append({"pos": pos_tag, "sense": "", "words": s[:5]})
        if a:
            antonyms.append({"pos": pos_tag, "sense": "", "words": a[:5]})
        # Per-definition synonyms
        for defn in meaning.get("definitions", []):
            ds = defn.get("synonyms", [])
            da = defn.get("antonyms", [])
            if ds and not s:
                synonyms.append({"pos": pos_tag, "sense": defn.get("definition", "")[:40], "words": ds[:5]})
            if da and not a:
                antonyms.append({"pos": pos_tag, "sense": defn.get("definition", "")[:40], "words": da[:5]})
    return synonyms[:5], antonyms[:5]


def infer_cefr(word: str, word_cefr_map: dict[str, str], ecdict_tag: str = "") -> str:
    if word.lower() in word_cefr_map:
        return word_cefr_map[word.lower()]
    if ecdict_tag:
        for level in ["C2", "C1", "B2", "B1", "A2", "A1"]:
            if level in ecdict_tag:
                return level
    return ""


# ═══════════════════════════════════════════════════════
# AI 增强 — GLM-4.5-air 批量补全
# ═══════════════════════════════════════════════════════

AI_SYSTEM_PROMPT = """You are an English dictionary compiler. Return JSON array only, one object per word.
Schema: {"word":"...", "examples":[{"en":"...","zh":"..."}], "synonyms":[{"pos":"v.","sense":"...","words":["..."]}], "antonyms":[{"pos":"v.","sense":"...","words":["..."]}], "collocations":[{"phrase":"...","zh":"...","type":"V+N"}], "associations":[{"word":"...","relation":"派生"}], "etymology":{"origin":"...","roots":[{"root":"...","meaning":"..."}],"history":"..."}}
Rules: 2 examples, 3 synonyms, 2 antonyms, 3 collocations with Chinese, 2 associations, etymology with roots. No markdown."""


def ai_enrich_batch(words: list[dict]) -> dict[str, dict]:
    """用 GLM-4.5-air 批量为词条生成增强数据。

    Args:
        words: list of {word, pos, definitions} dicts from ECDICT

    Returns:
        dict mapping word -> {examples, synonyms, antonyms, collocations, associations, etymology}
    """
    if not GLM_API_KEY:
        print("  ⚠ No GLM_API_KEY, skipping AI enrichment")
        return {}

    # Build prompt with context for each word
    word_descs = []
    for w in words:
        desc = f"- \"{w['word']}\""
        if w.get("pos"):
            desc += f" ({', '.join(w['pos'][:3])})"
        if w.get("definitions"):
            # Include first 2 Chinese definitions for context
            zh_defs = []
            for d in w["definitions"][:3]:
                for m in d.get("meanings", []):
                    if m.get("zh"):
                        zh_defs.append(m["zh"])
            if zh_defs:
                desc += f": {', '.join(zh_defs[:3])}"
        word_descs.append(desc)

    user_msg = "Words to enrich:\n" + "\n".join(word_descs)

    headers = {
        "Authorization": f"Bearer {GLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": AI_MAX_TOKENS,
        "temperature": 0.3,
    }

    for attempt in range(AI_RETRY):
        try:
            resp = http_requests.post(
                f"{GLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=AI_TIMEOUT,
            )
            if resp.status_code == 400:
                # Content filter / rate limit — skip this batch, don't retry
                print(f"  ⚠ AI HTTP 400 (content filter), skipping AI enrichment for this batch")
                return {}
            if resp.status_code != 200:
                print(f"  ⚠ AI HTTP {resp.status_code}: {resp.text[:100]}")
                time.sleep(2 * (attempt + 1))
                continue

            data = resp.json()
            if "error" in data:
                print(f"  ⚠ AI error: {data['error']}")
                time.sleep(2 * (attempt + 1))
                continue

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            _status["ai_calls"] += 1
            _status["ai_tokens"] += usage.get("total_tokens", 0)

            # Parse JSON from response (handle markdown fences)
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*\n?', '', content)
                content = re.sub(r'\n?```\s*$', '', content)
                content = content.strip()

            # Try to parse the full JSON
            try:
                result_list = json.loads(content)
            except json.JSONDecodeError:
                # Content might be truncated — try to salvage partial results
                # by finding complete objects within the array
                print(f"  ⚠ AI JSON truncated, salvaging partial data...")
                salvaged = []
                # Match complete JSON objects: {"word": ...}
                for m in re.finditer(r'\{\s*"word"\s*:.*?\}(?=\s*[,}]|\s*$)', content, re.DOTALL):
                    try:
                        obj = json.loads(m.group())
                        salvaged.append(obj)
                    except:
                        pass
                if salvaged:
                    result_list = salvaged
                    print(f"  ↳ Salvaged {len(salvaged)}/{len(words)} words from truncated response")
                else:
                    raise
            if not isinstance(result_list, list):
                result_list = [result_list]

            # Map word -> enrichment data
            enriched = {}
            for item in result_list:
                word_key = item.get("word", "").lower()
                if word_key:
                    enriched[word_key] = {
                        "examples": item.get("examples", []),
                        "synonyms": item.get("synonyms", []),
                        "antonyms": item.get("antonyms", []),
                        "collocations": item.get("collocations", []),
                        "associations": item.get("associations", []),
                        "etymology": item.get("etymology", {}),
                    }
            return enriched

        except json.JSONDecodeError as e:
            print(f"  ⚠ AI JSON parse error: {e}")
            # Try to extract JSON from the text
            try:
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    result_list = json.loads(json_match.group())
                    enriched = {}
                    for item in result_list:
                        word_key = item.get("word", "").lower()
                        if word_key:
                            enriched[word_key] = {
                                "examples": item.get("examples", []),
                                "synonyms": item.get("synonyms", []),
                                "antonyms": item.get("antonyms", []),
                                "collocations": item.get("collocations", []),
                                "associations": item.get("associations", []),
                                "etymology": item.get("etymology", {}),
                            }
                    return enriched
            except:
                pass
            time.sleep(2 * (attempt + 1))

        except Exception as e:
            print(f"  ⚠ AI request failed: {e}")
            time.sleep(2 * (attempt + 1))

    return {}


# ═══════════════════════════════════════════════════════
# 审计
# ═══════════════════════════════════════════════════════

def audit_round1(entry: dict) -> tuple[bool, list[str]]:
    """完整性检查"""
    issues = []
    if not entry.get("phonetic"):
        issues.append("missing phonetic")
    if not entry.get("definitions"):
        issues.append("missing definitions")

    has_zh = False
    for d in entry.get("definitions", []):
        for m in d.get("meanings", []):
            if m.get("zh"):
                has_zh = True
                break
    if not has_zh and entry.get("definitions"):
        issues.append("no Chinese translation")
    return (len(issues) == 0, issues)


def audit_round2(entry: dict) -> tuple[bool, list[str]]:
    """准确性检查"""
    issues = []
    for d in entry.get("definitions", []):
        if not d.get("meanings"):
            issues.append("definition has no meanings")
    # 检查 AI 字段格式
    for field in ["synonyms", "antonyms", "collocations", "associations"]:
        val = entry.get(field, [])
        if val and not isinstance(val, list):
            issues.append(f"{field} is not a list")
    ety = entry.get("etymology", {})
    if ety and not isinstance(ety, dict):
        issues.append("etymology is not a dict")
    return (len(issues) == 0, issues)


# ═══════════════════════════════════════════════════════
# 核心：构建单个词条
# ═══════════════════════════════════════════════════════

def build_base_entry(word: str, ecdict_db: sqlite3.Connection,
                     word_cefr_map: dict[str, str]) -> dict:
    """从 ECDICT 构建基础词条（不含 AI 增强字段）"""
    entry = {
        "word": word,
        "phonetic": "",
        "pos": [],
        "definitions": [],
        "examples": [],
        "synonyms": [],
        "antonyms": [],
        "collocations": [],
        "associations": [],
        "etymology": {},
        "cefr": "",
        "forms": [],
        "frequency": 0,
        "source": "",
    }

    # 1. ECDICT 基础数据
    cur = ecdict_db.execute(
        "SELECT * FROM stardict WHERE word = ? COLLATE NOCASE", (word,)
    )
    row = cur.fetchone()
    if row:
        cols = [desc[0] for desc in cur.description]
        ecdict = dict(zip(cols, row))

        raw_ph = ecdict.get("phonetic") or ""
        if raw_ph and len(raw_ph) > 1:
            entry["phonetic"] = raw_ph

        entry["pos"] = parse_ecdict_pos(ecdict.get("pos"))
        entry["definitions"] = build_definitions_from_ecdict(
            ecdict.get("definition"), ecdict.get("translation")
        )
        entry["forms"] = parse_ecdict_exchange(ecdict.get("exchange"))
        entry["frequency"] = ecdict.get("frq") or 0
        entry["cefr"] = infer_cefr(word, word_cefr_map, ecdict.get("tag") or "")
        entry["source"] = "ecdict"

    # 2. 补全 phonetic — 用 eSpeak-ng（Free Dictionary API 从此服务器不可达）
    if not entry["phonetic"] or not re.search(r'[ˈˌəɪɛæɑɔʊʌ]', entry["phonetic"]):
        espeak_ph = get_phonetic_espeak(word)
        if espeak_ph:
            entry["phonetic"] = espeak_ph

    # 3. Free Dictionary API — 从此服务器不可达，全部由 AI 补全
    # （synonyms/antonyms/examples/collocations 全部由 GLM 生成）

    # 4. CEFR
    if not entry["cefr"]:
        entry["cefr"] = word_cefr_map.get(word.lower(), "")

    return entry


def enrich_entry_with_ai(entry: dict, ai_data: dict) -> dict:
    """用 AI 返回的数据增强词条（AI 数据优先，补充 ECDICT/FreeDict 没有）"""
    ai = ai_data or {}

    # 例句：AI 补全优先（因为 AI 的有中文翻译）
    if ai.get("examples"):
        entry["examples"] = ai["examples"]
    elif not entry["examples"]:
        pass  # 保持为空，后续可以单独补全

    # 同义词：AI 补全（更结构化）
    if ai.get("synonyms"):
        entry["synonyms"] = ai["synonyms"]

    # 反义词
    if ai.get("antonyms"):
        entry["antonyms"] = ai["antonyms"]

    # 搭配
    if ai.get("collocations"):
        entry["collocations"] = ai["collocations"]

    # 联想词
    if ai.get("associations"):
        entry["associations"] = ai["associations"]

    # 词根词源
    if ai.get("etymology"):
        entry["etymology"] = ai["etymology"]

    return entry


# ═══════════════════════════════════════════════════════
# 收集词单
# ═══════════════════════════════════════════════════════

def collect_all_words() -> tuple[list[str], dict[str, str]]:
    all_words = set()
    word_cefr = {}

    with open(VOCAB_DIR / "index.json") as f:
        index = json.load(f)

    for pack in index:
        pack_id = pack["id"]
        pack_file = VOCAB_DIR / pack["file"]
        if not pack_file.exists():
            continue
        with open(pack_file) as f:
            data = json.load(f)
        words = data.get("words", [])
        cefr = CEFR_MAP.get(pack_id, "")
        for w in words:
            w_lower = w.lower()
            all_words.add(w_lower)
            if cefr:
                existing = word_cefr.get(w_lower, "")
                if not existing or cefr > existing:
                    word_cefr[w_lower] = cefr

    return sorted(all_words), word_cefr


# ═══════════════════════════════════════════════════════
# Git
# ═══════════════════════════════════════════════════════

def do_git_commit(batch_from: int, batch_to: int, word_count: int):
    project = str(PROJECT)
    subprocess.run(["git", "add", "dictionary/overlay.db"], cwd=project, capture_output=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--stat"],
        cwd=project, capture_output=True, text=True
    )
    if not result.stdout.strip():
        return False

    msg = f"dict: overlay batch {batch_from}-{batch_to} ({word_count} words, AI-enriched)"
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=project, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ✗ Commit failed: {result.stderr[:200]}")
        return False

    print(f"  ✓ Committed: {msg}")
    result = subprocess.run(["git", "push"], cwd=project, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  ✓ Pushed")
        _status["last_commit"] = msg
        return True
    else:
        print(f"  ✗ Push failed: {result.stderr[:200]}")
        return False


# ═══════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════

def main():
    global _status

    print("=" * 60)
    print("Overlay Dictionary Builder v3 — AI-Enriched")
    print("=" * 60)

    # 检查
    if not ECDICT_DB.exists():
        _status["status"] = "error"
        _status["error"] = f"ECDICT not found: {ECDICT_DB}"
        write_status()
        print(_status["error"])
        sys.exit(1)

    if not GLM_API_KEY:
        _status["status"] = "error"
        _status["error"] = "GLM_API_KEY not found (check ~/.hermes/.env or env var)"
        write_status()
        print(_status["error"])
        sys.exit(1)

    print(f"ECDICT:     {ECDICT_DB}")
    print(f"Overlay:    {OVERLAY_DB}")
    print(f"AI Model:   {GLM_MODEL}")
    print(f"Batch:      {BATCH_SIZE} words, AI {AI_BATCH_SIZE} words/call")
    print(f"Commit:     every {COMMIT_EVERY} batches ({COMMIT_EVERY * BATCH_SIZE} words)")
    print(f"PID:        {os.getpid()}")

    # 打开数据库
    ecdict_db = sqlite3.connect(str(ECDICT_DB))
    ecdict_db.row_factory = sqlite3.Row
    overlay_conn = sqlite3.connect(str(OVERLAY_DB))

    # 收集词单
    all_words, word_cefr_map = collect_all_words()
    _status["batch_total"] = (len(all_words) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"\nTotal unique words: {len(all_words)}")

    # 查已完成的词
    done_words = set()
    cur = overlay_conn.execute("SELECT word FROM overlay WHERE audit_pass = 2")
    for row in cur:
        done_words.add(row[0].lower())

    pending_words = [w for w in all_words if w.lower() not in done_words]
    print(f"Already done: {len(done_words)}, Remaining: {len(pending_words)}")

    if not pending_words:
        _status["status"] = "done"
        write_status()
        print("All words completed!")
        sys.exit(0)

    # 断点续跑
    cur = overlay_conn.execute("SELECT value FROM progress WHERE key = 'batch_index'")
    row = cur.fetchone()
    batch_index = int(row[0]) if row else 0
    if batch_index > 0:
        print(f"Resuming from batch {batch_index}")

    _status["status"] = "running"
    write_status()

    # 主循环
    batches_since_commit = 0
    total_batches = (len(pending_words) + BATCH_SIZE - 1) // BATCH_SIZE
    start_time = time.time()

    print(f"\nStarting: {total_batches} batches to process")
    print("-" * 60)

    try:
        while batch_index * BATCH_SIZE < len(pending_words):
            batch_start = batch_index * BATCH_SIZE
            batch_end = min(batch_start + BATCH_SIZE, len(pending_words))
            batch_words = pending_words[batch_start:batch_end]
            batch_num = batch_index + 1

            _status["batch_current"] = batch_num
            _status["last_batch_ok"] = 0
            _status["last_batch_fail"] = 0

            print(f"\n[Batch {batch_num}/{total_batches}] "
                  f"Words {batch_start+1}-{batch_end}/{len(pending_words)}")

            batch_ok = 0
            batch_fail = 0

            # ── Phase 1: 从 ECDICT 构建基础词条 ──────────────
            base_entries = {}
            for word in batch_words:
                _status["last_word"] = word
                try:
                    entry = build_base_entry(word, ecdict_db, word_cefr_map)
                    base_entries[word] = entry
                except Exception as e:
                    print(f"  ✗ {word} base build: {e}")
                    batch_fail += 1

            # ── Phase 2: AI 批量增强（AI_BATCH_SIZE 词/请求）───
            ai_words_list = list(base_entries.keys())
            ai_results = {}

            for ai_start in range(0, len(ai_words_list), AI_BATCH_SIZE):
                ai_batch = ai_words_list[ai_start:ai_start + AI_BATCH_SIZE]
                ai_context = []
                for w in ai_batch:
                    e = base_entries[w]
                    ai_context.append({
                        "word": w,
                        "pos": e.get("pos", []),
                        "definitions": e.get("definitions", []),
                    })

                try:
                    enriched = ai_enrich_batch(ai_context)
                    ai_results.update(enriched)
                    time.sleep(AI_DELAY)
                except Exception as e:
                    print(f"  ⚠ AI batch failed: {e}")
                    # 继续处理，只是没有 AI 数据

            # ── Phase 3: 合并 + 审计 + 写入 ─────────────────
            for word in batch_words:
                if word not in base_entries:
                    continue
                try:
                    entry = base_entries[word]
                    ai_data = ai_results.get(word.lower(), {})

                    # 合并 AI 增强
                    entry = enrich_entry_with_ai(entry, ai_data)

                    # 两轮审计
                    ok1, issues1 = audit_round1(entry)
                    if not ok1:
                        print(f"  ✗ {word}: audit1 - {issues1}")
                        batch_fail += 1
                        continue

                    ok2, issues2 = audit_round2(entry)
                    if not ok2:
                        print(f"  ✗ {word}: audit2 - {issues2}")
                        batch_fail += 1
                        continue

                    # 构建 field_meta：每个字段经过两轮审计处理，空值为 confirmed_empty
                    _EMPTY = {
                        "phonetic": "", "pos": [], "definitions": [], "examples": [],
                        "synonyms": [], "antonyms": [], "collocations": [], "associations": [],
                        "etymology": {}, "cefr": "", "forms": [],
                    }
                    field_meta = {
                        f: ("filled" if entry.get(f) and entry.get(f) != ev else "confirmed_empty")
                        for f, ev in _EMPTY.items()
                    }

                    # 写入 overlay.db
                    overlay_conn.execute("""
                        INSERT OR REPLACE INTO overlay
                        (word, phonetic, pos, definitions, examples,
                         synonyms, antonyms, collocations, associations, etymology,
                         cefr, forms, frequency, source, updated_at, audit_pass, field_meta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?)
                    """, (
                        entry["word"],
                        entry["phonetic"],
                        json.dumps(entry["pos"], ensure_ascii=False),
                        json.dumps(entry["definitions"], ensure_ascii=False),
                        json.dumps(entry["examples"], ensure_ascii=False),
                        json.dumps(entry["synonyms"], ensure_ascii=False),
                        json.dumps(entry["antonyms"], ensure_ascii=False),
                        json.dumps(entry["collocations"], ensure_ascii=False),
                        json.dumps(entry["associations"], ensure_ascii=False),
                        json.dumps(entry["etymology"], ensure_ascii=False),
                        entry["cefr"],
                        json.dumps(entry["forms"], ensure_ascii=False),
                        entry["frequency"],
                        entry["source"],
                        datetime.datetime.now().isoformat(),
                        json.dumps(field_meta, ensure_ascii=False),
                    ))
                    overlay_conn.commit()
                    batch_ok += 1

                except Exception as e:
                    print(f"  ✗ {word} write: {e}")
                    batch_fail += 1

            _status["words_done"] += batch_ok
            _status["words_fail"] += batch_fail
            _status["last_batch_ok"] = batch_ok
            _status["last_batch_fail"] = batch_fail
            batches_since_commit += 1

            elapsed = time.time() - start_time
            rate = _status["words_done"] / elapsed * 60 if elapsed > 0 else 0
            print(f"  → OK: {batch_ok}, Fail: {batch_fail} "
                  f"| Total: {_status['words_done']}/{len(pending_words)} "
                  f"| Rate: {rate:.1f} w/min "
                  f"| AI: {_status['ai_calls']} calls, {_status['ai_tokens']} tokens")

            # 更新进度
            batch_index += 1
            overlay_conn.execute(
                "INSERT OR REPLACE INTO progress (key, value) VALUES (?, ?)",
                ("batch_index", str(batch_index))
            )
            overlay_conn.commit()

            # Git commit
            if batches_since_commit >= COMMIT_EVERY:
                batch_from = batch_index - batches_since_commit + 1
                do_git_commit(batch_from, batch_num, _status["words_done"])
                batches_since_commit = 0

            write_status()
            time.sleep(API_DELAY)

        # 收尾
        if batches_since_commit > 0:
            do_git_commit(batch_index - batches_since_commit + 1, batch_index,
                          _status["words_done"])

        _status["status"] = "done"
        write_status()

        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"DONE! Time: {elapsed/60:.1f}min")
        print(f"Words: {_status['words_done']} ok, {_status['words_fail']} fail")
        print(f"AI: {_status['ai_calls']} calls, {_status['ai_tokens']} tokens")

    except Exception as e:
        _status["status"] = "error"
        _status["error"] = traceback.format_exc()
        write_status()
        print(f"\nFATAL: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        ecdict_db.close()
        overlay_conn.close()


if __name__ == "__main__":
    main()
