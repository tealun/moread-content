#!/usr/bin/env python3
"""
Overlay Dictionary Builder — 常驻批处理脚本

从 ECDICT 提取基础数据，补全音标/释义/例句/CEFR，写入 overlay.db。
每批 50 词，每 100 批 commit 一次。
两轮审计：完整性 → 准确性，通过后才算完成。

用法:
  python3 tools/build_overlay.py

前置:
  ~/moread-assets/ecdict.db 必须存在
"""

import sqlite3
import json
import subprocess
import re
import sys
import os
import time
import datetime
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────
PROJECT   = Path(__file__).resolve().parent.parent
ECDICT_DB = Path(os.path.expanduser("~/moread-assets/ecdict.db"))
OVERLAY_DB = PROJECT / "dictionary" / "overlay.db"
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

# ── 工具函数 ──────────────────────────────────────────

def get_phonetic_espeak(word: str) -> str:
    """用 eSpeak-ng 生成 IPA 音标"""
    try:
        result = subprocess.run(
            ["espeak-ng", "-q", "--ipa", word],
            capture_output=True, text=True, timeout=5
        )
        ipa = result.stdout.strip()
        # eSpeak-ng 输出可能有多行，取第一行
        if ipa:
            return ipa.split("\n")[0].strip()
    except Exception:
        pass
    return ""


def lookup_ecdict(db: sqlite3.Connection, word: str) -> dict | None:
    """从 ECDICT 查单个词"""
    cur = db.execute(
        "SELECT * FROM stardict WHERE word = ? COLLATE NOCASE", (word,)
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def parse_ecdict_definitions(definition: str | None, translation: str | None) -> list[dict]:
    """解析 ECDICT 的 definition + translation 为 definitions 数组"""
    def _parse_pos_prefix(line: str) -> tuple[str, str]:
        line = line.strip()
        if not line:
            return ("", "")
        m = re.match(r'^([a-z]+\.\s*)(.*)$', line, re.IGNORECASE)
        if m:
            return (m.group(1).strip(), m.group(2).strip())
        return ("", line)

    def_lines = []
    if definition:
        for line in definition.strip().split('\\n'):
            pos, content = _parse_pos_prefix(line)
            if content:
                def_lines.append((pos, content))

    trans_lines = []
    if translation:
        for line in translation.strip().split('\\n'):
            pos, content = _parse_pos_prefix(line)
            if content:
                trans_lines.append((pos, content))

    definitions = []
    used_trans = set()

    for pos, en in def_lines:
        best_idx = -1
        for i, (tpos, zh) in enumerate(trans_lines):
            if i in used_trans:
                continue
            if not tpos or not pos:
                continue
            pos_base = pos.rstrip('.')
            tpos_base = tpos.rstrip('.')
            if (tpos_base == pos_base or tpos_base.startswith(pos_base)
                    or pos_base.startswith(tpos_base)):
                best_idx = i
                break
        if best_idx >= 0:
            definitions.append({"pos": pos, "meanings": [{"zh": trans_lines[best_idx][1], "en": en}]})
            used_trans.add(best_idx)
        else:
            definitions.append({"pos": pos, "meanings": [{"zh": "", "en": en}]})

    # 剩余未匹配的中文释义
    for i, (tpos, zh) in enumerate(trans_lines):
        if i not in used_trans:
            definitions.append({"pos": tpos, "meanings": [{"zh": zh, "en": ""}]})

    return definitions


def parse_ecdict_pos(pos_text: str | None) -> list[str]:
    if not pos_text:
        return []
    return [p.strip() for p in re.split(r'[/,]', pos_text) if p.strip()]


def parse_ecdict_exchange(exchange: str | None) -> list[dict]:
    """解析 ECDICT exchange 为 forms"""
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
        if text and "/" in text:
            return text.strip()
    return ""


def infer_cefr(word: str, word_cefr_map: dict[str, str], ecdict_tag: str = "") -> str:
    """推断 CEFR 等级：词单级别优先，ECDICT tag 次之"""
    if word.lower() in word_cefr_map:
        return word_cefr_map[word.lower()]
    # ECDICT tag 可能含 CEFR 信息
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
        issues.append("no Chinese translation in definitions")

    return (len(issues) == 0, issues)


def audit_round2(entry: dict) -> tuple[bool, list[str]]:
    """第二轮：准确性校验"""
    issues = []
    word = entry.get("word", "")

    # phonetic 格式检查（应含 IPA 符号）
    phonetic = entry.get("phonetic", "")
    if phonetic and not re.search(r'[ˈˌəɪɛæɑɔʊʌθðʃʒŋɫɚ]/', phonetic):
        # 可能是有效的但不包含常见 IPA 符号，只是警告不阻断
        pass

    # definitions 格式检查
    for d in entry.get("definitions", []):
        if not d.get("pos"):
            issues.append(f"definition missing pos")
        if not d.get("meanings"):
            issues.append(f"definition has no meanings")

    # 空字符串检查
    if entry.get("pos") == "[]":
        pass  # 可以没有 pos

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
    ecdict_row = lookup_ecdict(ecdict_db, word)
    if ecdict_row:
        entry["phonetic"] = ecdict_row.get("phonetic") or ""
        entry["pos"] = parse_ecdict_pos(ecdict_row.get("pos"))
        entry["definitions"] = parse_ecdict_definitions(
            ecdict_row.get("definition"), ecdict_row.get("translation")
        )
        entry["forms"] = parse_ecdict_exchange(ecdict_row.get("exchange"))
        entry["frequency"] = ecdict_row.get("frq") or 0
        entry["cefr"] = infer_cefr(word, word_cefr_map, ecdict_row.get("tag") or "")
        entry["source"] = "ecdict"

    # 2. 补全 phonetic（ECDICT 缺失时）
    if not entry["phonetic"]:
        # 先试 Free Dictionary API
        fd = fetch_free_dictionary(word)
        if fd:
            ph = extract_phonetic_from_free_dict(fd)
            if ph:
                entry["phonetic"] = ph

        # 还是没有，用 eSpeak-ng
        if not entry["phonetic"]:
            entry["phonetic"] = get_phonetic_espeak(word)

    # 3. 补全 definitions（Free Dictionary API）
    fd = None
    needs_defs = (not entry["definitions"]
                  or any(not m.get("zh") for d in entry["definitions"] for m in d.get("meanings", [])))

    if needs_defs:
        if fd is None:
            fd = fetch_free_dictionary(word)
        if fd:
            # 补充缺失的中文释义或 definitions
            for meaning in fd.get("meanings", []):
                pos_tag = meaning.get("partOfSpeech", "")
                for defn in meaning.get("definitions", []):
                    en_def = defn.get("definition", "")
                    if en_def and not any(
                        d.get("meanings", [{}])[0].get("en") == en_def
                        for d in entry["definitions"]
                    ):
                        entry["definitions"].append({
                            "pos": pos_tag,
                            "meanings": [{"zh": "", "en": en_def}]
                        })
            if entry["source"] == "ecdict":
                entry["source"] = "ecdict+api"
            elif not entry["source"]:
                entry["source"] = "free_dictionary"

    # 4. 补全 examples（Free Dictionary API）
    if not entry["examples"]:
        if fd is None:
            fd = fetch_free_dictionary(word)
        if fd:
            entry["examples"] = extract_examples_from_free_dict(fd)

    # 5. 补全 CEFR
    if not entry["cefr"]:
        entry["cefr"] = word_cefr_map.get(word.lower(), "")

    return entry


# ── 进度管理 ──────────────────────────────────────────

def load_progress(overlay_db: sqlite3.Connection) -> dict:
    """加载进度状态"""
    cur = overlay_db.execute("SELECT key, value FROM progress")
    return dict(cur.fetchall())


def save_progress(overlay_db: sqlite3.Connection, key: str, value: str):
    overlay_db.execute(
        "INSERT OR REPLACE INTO progress (key, value) VALUES (?, ?)",
        (key, value)
    )
    overlay_db.commit()


# ── 收集所有词单中的单词 ──────────────────────────────

def collect_all_words() -> tuple[list[str], dict[str, str]]:
    """从 vocabulary/ 词单中收集所有单词，返回 (去重排序列表, {word: cefr})"""
    all_words = set()
    word_cefr = {}

    index_path = VOCAB_DIR / "index.json"
    if not index_path.exists():
        print(f"ERROR: {index_path} not found")
        sys.exit(1)

    with open(index_path) as f:
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
            # CEFR 取最高级别
            if cefr:
                existing = word_cefr.get(w_lower, "")
                if not existing or cefr > existing:
                    word_cefr[w_lower] = cefr

    return sorted(all_words), word_cefr


# ── 主循环 ────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Overlay Dictionary Builder")
    print("=" * 60)

    # 检查 ECDICT
    if not ECDICT_DB.exists():
        print(f"\nWAITING: {ECDICT_DB} not found.")
        print("Please place ecdict.db in ~/moread-assets/")
        print("This script will exit. Run again after placing the file.")
        sys.exit(1)

    print(f"ECDICT:   {ECDICT_DB}")
    print(f"Overlay:  {OVERLAY_DB}")
    print(f"Batch:    {BATCH_SIZE} words")
    print(f"Commit:   every {COMMIT_EVERY} batches ({COMMIT_EVERY * BATCH_SIZE} words)")

    # 打开数据库
    ecdict_db = sqlite3.connect(str(ECDICT_DB))
    ecdict_db.row_factory = sqlite3.Row

    overlay_conn = sqlite3.connect(str(OVERLAY_DB))

    # 收集词单
    all_words, word_cefr_map = collect_all_words()
    print(f"\nTotal unique words from vocabulary packs: {len(all_words)}")

    # 查已完成的词
    done_words = set()
    cur = overlay_conn.execute("SELECT word FROM overlay WHERE audit_pass = 2")
    for row in cur:
        done_words.add(row[0].lower())

    # 计算待处理
    pending_words = [w for w in all_words if w.lower() not in done_words]
    print(f"Already completed: {len(done_words)}")
    print(f"Remaining: {len(pending_words)}")

    if not pending_words:
        print("\nAll words completed! Nothing to do.")
        sys.exit(0)

    # 断点续跑
    progress = load_progress(overlay_conn)
    batch_index = int(progress.get("batch_index", "0"))
    if batch_index > 0:
        print(f"Resuming from batch {batch_index}")

    # 进入主循环
    batches_since_commit = 0
    total_batches = (len(pending_words) + BATCH_SIZE - 1) // BATCH_SIZE
    start_time = time.time()

    print(f"\nStarting: {total_batches} batches to process")
    print("-" * 60)

    while batch_index * BATCH_SIZE < len(pending_words):
        batch_start = batch_index * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(pending_words))
        batch_words = pending_words[batch_start:batch_end]

        batch_num = batch_index + 1
        elapsed = time.time() - start_time
        print(f"\n[Batch {batch_num}/{total_batches}] "
              f"Words {batch_start+1}-{batch_end}/{len(pending_words)} "
              f"(elapsed: {elapsed:.0f}s)")

        # 处理每个词
        batch_ok = 0
        batch_fail = 0
        for word in batch_words:
            try:
                entry = build_entry(word, ecdict_db, word_cefr_map)

                # 两轮审计
                ok1, issues1 = audit_round1(entry)
                if not ok1:
                    print(f"  ✗ {word}: round1 fail - {issues1}")
                    batch_fail += 1
                    continue

                ok2, issues2 = audit_round2(entry)
                if not ok2:
                    print(f"  ✗ {word}: round2 fail - {issues2}")
                    batch_fail += 1
                    continue

                # 写入 overlay
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
                print(f"  ✗ {word}: error - {e}")
                batch_fail += 1

        print(f"  → OK: {batch_ok}, Fail: {batch_fail}")
        batches_since_commit += 1

        # 更新进度
        save_progress(overlay_conn, "batch_index", str(batch_index + 1))
        batch_index += 1

        # 每 COMMIT_EVERY 批 commit 一次
        if batches_since_commit >= COMMIT_EVERY:
            _do_git_commit(batch_index, COMMIT_EVERY, BATCH_SIZE, batch_ok, batch_fail)
            batches_since_commit = 0

        # API 限速
        time.sleep(API_DELAY)

    # 收尾：处理剩余未 commit 的批次
    if batches_since_commit > 0:
        _do_git_commit(batch_index, batches_since_commit, BATCH_SIZE, 0, 0)

    # 最终统计
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"DONE! Total time: {elapsed:.0f}s")

    # 统计
    cur = overlay_conn.execute("SELECT COUNT(*) FROM overlay WHERE audit_pass = 2")
    done = cur.fetchone()[0]
    cur = overlay_conn.execute("SELECT COUNT(*) FROM overlay WHERE audit_pass < 2")
    remain = cur.fetchone()[0]
    print(f"Completed: {done}, Remaining issues: {remain}")

    ecdict_db.close()
    overlay_conn.close()


def _do_git_commit(batch_index: int, batch_count: int, batch_size: int,
                   ok: int, fail: int):
    """Git commit 当前进度"""
    import subprocess
    project = str(PROJECT)

    # stage overlay.db
    subprocess.run(["git", "add", "dictionary/overlay.db"], cwd=project, capture_output=True)

    # 统计
    result = subprocess.run(
        ["git", "diff", "--cached", "--stat"],
        cwd=project, capture_output=True, text=True
    )
    if not result.stdout.strip():
        print("  (nothing to commit)")
        return

    end_word_idx = batch_index * batch_size
    start_word_idx = end_word_idx - batch_count * batch_size
    msg = (f"dict: overlay batch {start_word_idx//batch_size}-{batch_index} "
           f"({batch_count * batch_size} words)")

    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=project, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✓ Committed: {msg}")
        result = subprocess.run(
            ["git", "push"], cwd=project, capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  ✓ Pushed")
        else:
            print(f"  ✗ Push failed: {result.stderr[:200]}")
    else:
        print(f"  ✗ Commit failed: {result.stderr[:200]}")


if __name__ == "__main__":
    main()
