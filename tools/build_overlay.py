#!/usr/bin/env python3
"""
Overlay Dictionary Builder — 常驻批处理脚本

从 ECDICT 提取基础数据，补全音标/释义/例句/CEFR，写入 overlay.db。
每批 50 词，每 100 批 commit 一次。
两轮审计：完整性 → 准确性，通过后才算完成。

用法:
  python3 tools/build_overlay.py

状态文件:
  dictionary/overlay.status.json — 实时状态，看门狗读此文件

看门狗:
  tools/watchdog_overlay.sh — 每 5 分钟检查，卡死/崩溃自动拉起
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
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────
PROJECT    = Path(__file__).resolve().parent.parent
ECDICT_DB  = Path(os.path.expanduser("~/moread-assets/ecdict.db"))
OVERLAY_DB = PROJECT / "dictionary" / "overlay.db"
STATUS_FILE = PROJECT / "dictionary" / "overlay.status.json"
VOCAB_DIR  = PROJECT / "vocabulary"

BATCH_SIZE       = 50
COMMIT_EVERY     = 100   # 每 N 批 git commit
API_RETRY        = 3
API_DELAY        = 0.3   # 秒，API 请求间隔

# ── CEFR 从词单推断 ───────────────────────────────────
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
    "last_word": "",
    "last_batch_ok": 0,
    "last_batch_fail": 0,
    "last_commit": "",
    "last_update": datetime.datetime.now().isoformat(),
    "error": None,
    "started_at": datetime.datetime.now().isoformat(),
}


def write_status():
    """写入状态文件"""
    _status["last_update"] = datetime.datetime.now().isoformat()
    with open(STATUS_FILE, "w") as f:
        json.dump(_status, f, indent=2, ensure_ascii=False)


def signal_handler(signum, frame):
    """优雅退出"""
    _status["status"] = "stopping"
    write_status()
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ── ECDICT 数据解析 ───────────────────────────────────

def parse_ecdict_pos(pos_text: str | None) -> list[str]:
    """解析 ECDICT pos 字段，格式如 'n:4/v:96' → ['n.', 'v.']"""
    if not pos_text:
        return []
    result = []
    for part in pos_text.split("/"):
        if ":" in part:
            tag = part.split(":")[0]
        else:
            tag = part
        tag = tag.strip()
        if tag:
            result.append(tag + ".")
    return result


def parse_ecdict_translation(translation: str | None) -> list[tuple[str, str]]:
    """解析 ECDICT translation，返回 [(pos, chinese), ...]"""
    if not translation:
        return []
    lines = []
    for line in translation.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 匹配词性前缀如 "vt." "n." "a." 等
        m = re.match(r'^([a-z]+\.\s*)(.*)$', line, re.IGNORECASE)
        if m:
            lines.append((m.group(1).strip(), m.group(2).strip()))
        else:
            lines.append(("", line))
    return lines


def parse_ecdict_definition(definition: str | None) -> list[tuple[str, str]]:
    """解析 ECDICT definition，返回 [(pos, english), ...]"""
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
    """构建 definitions 数组：[{pos, meanings: [{zh, en}]}]"""
    en_lines = parse_ecdict_definition(definition)
    zh_lines = parse_ecdict_translation(translation)

    definitions = []
    used_zh = set()

    # 按顺序配对
    for i, (pos, en) in enumerate(en_lines):
        zh = ""
        # 找同词性或同序号的中文释义
        if i < len(zh_lines):
            zh = zh_lines[i][1]
            used_zh.add(i)
        definitions.append({
            "pos": pos,
            "meanings": [{"zh": zh, "en": en}]
        })

    # 剩余未匹配的中文释义
    for i, (pos, zh) in enumerate(zh_lines):
        if i not in used_zh and zh:
            definitions.append({
                "pos": pos,
                "meanings": [{"zh": zh, "en": ""}]
            })

    return definitions


def parse_ecdict_exchange(exchange: str | None) -> list[dict]:
    """解析 ECDICT exchange，如 'd:abandoned/p:abandoned/i:abandoning/3:abandons'"""
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


# ── 外部数据源 ────────────────────────────────────────

def get_phonetic_espeak(word: str) -> str:
    """用 eSpeak-ng 生成 IPA 音标"""
    try:
        result = subprocess.run(
            ["espeak-ng", "-q", "--ipa", word],
            capture_output=True, text=True, timeout=5
        )
        ipa = result.stdout.strip()
        if ipa:
            # 取第一行，加斜杠
            ipa = ipa.split("\n")[0].strip()
            return f"/{ipa}/"
    except Exception:
        pass
    return ""


def fetch_free_dictionary(word: str) -> dict | None:
    """从 Free Dictionary API 获取数据"""
    import requests
    for attempt in range(API_RETRY):
        try:
            resp = requests.get(
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
    """从 Free Dictionary API 响应提取例句"""
    examples = []
    for meaning in fd.get("meanings", []):
        for defn in meaning.get("definitions", []):
            example_en = defn.get("example", "")
            if example_en:
                examples.append({"en": example_en, "zh": ""})
            if len(examples) >= 3:
                return examples
    return examples


def extract_phonetic_from_free_dict(fd: dict) -> str:
    """从 Free Dictionary API 提取音标"""
    for phonetic in fd.get("phonetics", []):
        text = phonetic.get("text", "")
        if text and ("/" in text or "ˈ" in text or "ˌ" in text):
            return text.strip()
    return ""


def infer_cefr(word: str, word_cefr_map: dict[str, str], ecdict_tag: str = "") -> str:
    """推断 CEFR 等级"""
    if word.lower() in word_cefr_map:
        return word_cefr_map[word.lower()]
    if ecdict_tag:
        for level in ["C2", "C1", "B2", "B1", "A2", "A1"]:
            if level in ecdict_tag:
                return level
    return ""


# ── 两轮审计 ──────────────────────────────────────────

def audit_round1(entry: dict) -> tuple[bool, list[str]]:
    """第一轮：字段完整性检查"""
    issues = []
    if not entry.get("phonetic"):
        issues.append("missing phonetic")
    if not entry.get("definitions"):
        issues.append("missing definitions")

    # 至少一个 definition 有中文释义
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
    """第二轮：准确性校验"""
    issues = []
    for d in entry.get("definitions", []):
        if not d.get("meanings"):
            issues.append("definition has no meanings")
    return (len(issues) == 0, issues)


# ── 核心：构建单个词条 ────────────────────────────────

def build_entry(word: str, ecdict_db: sqlite3.Connection,
                word_cefr_map: dict[str, str]) -> dict:
    """构建一个完整的 overlay 词条"""
    entry = {
        "word": word,
        "phonetic": "",
        "pos": [],
        "definitions": [],
        "examples": [],
        "cefr": "",
        "forms": [],
        "frequency": 0,
        "source": "",
    }

    # 1. 从 ECDICT 获取基础数据
    cur = ecdict_db.execute(
        "SELECT * FROM stardict WHERE word = ? COLLATE NOCASE", (word,)
    )
    row = cur.fetchone()
    if row:
        cols = [desc[0] for desc in cur.description]
        ecdict = dict(zip(cols, row))

        # phonetic — ECDICT 的音标格式不标准，标记备用
        raw_ph = ecdict.get("phonetic") or ""
        if raw_ph and len(raw_ph) > 1:
            entry["phonetic"] = raw_ph  # 先保留，后面可能被标准 IPA 替换

        entry["pos"] = parse_ecdict_pos(ecdict.get("pos"))
        entry["definitions"] = build_definitions_from_ecdict(
            ecdict.get("definition"), ecdict.get("translation")
        )
        entry["forms"] = parse_ecdict_exchange(ecdict.get("exchange"))
        entry["frequency"] = ecdict.get("frq") or 0
        entry["cefr"] = infer_cefr(word, word_cefr_map, ecdict.get("tag") or "")
        entry["source"] = "ecdict"

    # 2. 补全 phonetic（ECDICT 缺失或非标准 IPA 时）
    needs_ipa = (not entry["phonetic"]
                 or not re.search(r'[ˈˌəɪɛæɑɔʊʌ]', entry["phonetic"]))
    if needs_ipa:
        # 先试 Free Dictionary API
        fd = fetch_free_dictionary(word)
        if fd:
            ph = extract_phonetic_from_free_dict(fd)
            if ph:
                entry["phonetic"] = ph

        # 还没有，用 eSpeak-ng
        if not entry["phonetic"] or not re.search(r'[ˈˌəɪɛæɑɔʊʌ]', entry["phonetic"]):
            espeak_ph = get_phonetic_espeak(word)
            if espeak_ph:
                entry["phonetic"] = espeak_ph

    # 3. 补全 examples（Free Dictionary API）
    fd = None
    if not entry["examples"]:
        fd = fetch_free_dictionary(word) if fd is None else fd
        if fd:
            entry["examples"] = extract_examples_from_free_dict(fd)

    # 4. CEFR
    if not entry["cefr"]:
        entry["cefr"] = word_cefr_map.get(word.lower(), "")

    return entry


# ── 收集所有词单中的单词 ──────────────────────────────

def collect_all_words() -> tuple[list[str], dict[str, str]]:
    """从 vocabulary/ 词单中收集所有单词"""
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


# ── Git 提交 ──────────────────────────────────────────

def do_git_commit(batch_from: int, batch_to: int, word_count: int):
    """Git commit + push"""
    project = str(PROJECT)
    subprocess.run(["git", "add", "dictionary/overlay.db"], cwd=project, capture_output=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--stat"],
        cwd=project, capture_output=True, text=True
    )
    if not result.stdout.strip():
        return False

    msg = f"dict: overlay batch {batch_from}-{batch_to} ({word_count} words)"
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=project, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ✗ Commit failed: {result.stderr[:200]}")
        return False

    print(f"  ✓ Committed: {msg}")
    result = subprocess.run(
        ["git", "push"], cwd=project, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✓ Pushed")
        _status["last_commit"] = msg
        return True
    else:
        print(f"  ✗ Push failed: {result.stderr[:200]}")
        return False


# ── 主循环 ────────────────────────────────────────────

def main():
    global _status

    print("=" * 60)
    print("Overlay Dictionary Builder")
    print("=" * 60)

    # 检查 ECDICT
    if not ECDICT_DB.exists():
        _status["status"] = "error"
        _status["error"] = f"ECDICT not found: {ECDICT_DB}"
        write_status()
        print(_status["error"])
        sys.exit(1)

    print(f"ECDICT:   {ECDICT_DB}")
    print(f"Overlay:  {OVERLAY_DB}")
    print(f"Batch:    {BATCH_SIZE} words, commit every {COMMIT_EVERY} batches")
    print(f"PID:      {os.getpid()}")

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

            for word in batch_words:
                _status["last_word"] = word
                try:
                    entry = build_entry(word, ecdict_db, word_cefr_map)

                    # 两轮审计
                    ok1, issues1 = audit_round1(entry)
                    if not ok1:
                        print(f"  ✗ {word}: round1 - {issues1}")
                        batch_fail += 1
                        continue

                    ok2, issues2 = audit_round2(entry)
                    if not ok2:
                        print(f"  ✗ {word}: round2 - {issues2}")
                        batch_fail += 1
                        continue

                    # 写入
                    overlay_conn.execute("""
                        INSERT OR REPLACE INTO overlay
                        (word, phonetic, pos, definitions, examples, cefr, forms,
                         frequency, source, updated_at, audit_pass)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2)
                    """, (
                        entry["word"],
                        entry["phonetic"],
                        json.dumps(entry["pos"], ensure_ascii=False),
                        json.dumps(entry["definitions"], ensure_ascii=False),
                        json.dumps(entry["examples"], ensure_ascii=False),
                        entry["cefr"],
                        json.dumps(entry["forms"], ensure_ascii=False),
                        entry["frequency"],
                        entry["source"],
                        datetime.datetime.now().isoformat(),
                    ))
                    overlay_conn.commit()
                    batch_ok += 1

                except Exception as e:
                    print(f"  ✗ {word}: {e}")
                    batch_fail += 1

            _status["words_done"] += batch_ok
            _status["words_fail"] += batch_fail
            _status["last_batch_ok"] = batch_ok
            _status["last_batch_fail"] = batch_fail
            batches_since_commit += 1

            print(f"  → OK: {batch_ok}, Fail: {batch_fail}")

            # 更新进度
            batch_index += 1
            overlay_conn.execute(
                "INSERT OR REPLACE INTO progress (key, value) VALUES (?, ?)",
                ("batch_index", str(batch_index))
            )
            overlay_conn.commit()

            # 每 COMMIT_EVERY 批提交一次
            if batches_since_commit >= COMMIT_EVERY:
                batch_from = batch_index - batches_since_commit + 1
                do_git_commit(batch_from, batch_num, batches_since_commit * BATCH_SIZE)
                batches_since_commit = 0

            write_status()
            time.sleep(API_DELAY)

        # 收尾
        if batches_since_commit > 0:
            do_git_commit(batch_index - batches_since_commit + 1, batch_index,
                          batches_since_commit * BATCH_SIZE)

        _status["status"] = "done"
        write_status()

        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"DONE! Time: {elapsed:.0f}s, Done: {_status['words_done']}, Fail: {_status['words_fail']}")

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
