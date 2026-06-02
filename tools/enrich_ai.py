#!/usr/bin/env python3
"""
enrich_ai.py — 补全 overlay.db 中缺少 AI 数据的词条
用 DeepSeek-V3 批量补全: examples, synonyms, antonyms, collocations, associations, etymology

用法:
  DEEPSEEK_API_KEY=xxx python3 tools/enrich_ai.py              # 全量
  DEEPSEEK_API_KEY=xxx OVERLAY_MAX_WORDS=1000 python3 tools/enrich_ai.py  # 限 1000 词
"""

import json, os, sys, time, traceback, requests
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────
AI_BATCH_SIZE    = 5       # 每次请求处理词数
AI_MAX_TOKENS       = 8192
AI_TIMEOUT       = 30
AI_RETRY         = 3
AI_DELAY         = 0.5
COMMIT_EVERY     = 50      # 每 N 词 commit 一次
PUSH_EVERY       = 5000    # 每 N 词 git push 一次
MAX_WORDS        = int(os.environ.get("OVERLAY_MAX_WORDS", "0"))  # 0=全部

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL   = "deepseek-chat"

OVERLAY_DB = Path(__file__).parent.parent / "dictionary" / "overlay.db"
STATUS_FILE = Path(__file__).parent.parent / "dictionary" / "enrich_status.json"

# ── AI Prompt ───────────────────────────────────────────
AI_SYSTEM_PROMPT = """You are an English dictionary compiler. Return JSON array only, one object per word.
For each word, provide:
- "examples": array of 2 example sentences (natural, diverse contexts, each as {"en": "...", "zh": "..."})
- "synonyms": array of up to 5 synonyms (strings)
- "antonyms": array of up to 3 antonyms (strings)
- "collocations": array of 3 common collocations (strings like "verb + noun")
- "associations": array of 3 related words for memory (strings)
- "etymology": brief etymology note (string, English)

IMPORTANT: Return ONLY the JSON array. No markdown, no explanation."""

# ── Status tracking ─────────────────────────────────────
_status = {
    "status": "starting",
    "pid": os.getpid(),
    "words_done": 0,
    "words_fail": 0,
    "ai_calls": 0,
    "ai_tokens": 0,
    "last_word": "",
    "last_update": "",
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "error": None,
}

def write_status():
    _status["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STATUS_FILE.write_text(json.dumps(_status, indent=2, ensure_ascii=False))

# ── AI 调用 ─────────────────────────────────────────────
def ai_enrich_batch(words_ctx):
    """调用 DeepSeek 批量增强词条。
    
    Args:
        words_ctx: list of {word, pos, definitions}
    Returns:
        dict mapping word -> AI data
    """
    if not DEEPSEEK_API_KEY:
        return {}

    word_descs = []
    for w in words_ctx:
        desc = f"- \"{w['word']}\""
        if w.get("pos"):
            desc += f" ({', '.join(w['pos'][:3])})"
        if w.get("definitions"):
            zh_defs = []
            for d in w["definitions"][:3]:
                for m in d.get("meanings", []):
                    if m.get("zh"):
                        zh_defs.append(m["zh"])
            if zh_defs:
                desc += f" meaning: {'; '.join(zh_defs[:3])}"
        word_descs.append(desc)

    user_msg = "Words to enrich:\n" + "\n".join(word_descs)

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": AI_MAX_TOKENS,
        "temperature": 0.1,
    }

    for attempt in range(AI_RETRY):
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=AI_TIMEOUT,
            )
            if resp.status_code == 400:
                print(f"  ⚠ HTTP 400 (content filter), skipping batch")
                return {}
            resp.raise_for_status()

            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Track tokens
            usage = data.get("usage", {})
            _status["ai_tokens"] += usage.get("total_tokens", 0)
            _status["ai_calls"] += 1

            # Parse JSON
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            results = json.loads(content)
            if not isinstance(results, list):
                results = [results]

            # Build result dict with robust matching
            result_map = {}
            for idx, r in enumerate(results):
                if not isinstance(r, dict):
                    continue
                # Normalize examples: accept both [{en,zh}] and plain strings
                ex = r.get("examples", [])
                if ex and isinstance(ex[0], str):
                    r["examples"] = [{"en": s, "zh": ""} for s in ex]
                # Match by word name, then by position (fallback)
                word_key = r.get("word", "").lower()
                if word_key:
                    result_map[word_key] = r
                elif idx < len(words_ctx):
                    # Fallback: positional match
                    result_map[words_ctx[idx]["word"].lower()] = r
            return result_map

        except requests.exceptions.Timeout:
            print(f"  ⚠ Timeout (attempt {attempt+1}/{AI_RETRY})")
            time.sleep(2)
        except json.JSONDecodeError as e:
            # Try to salvage partial JSON
            try:
                import re
                fixed = re.sub(r',\s*}', '}', content)
                fixed = re.sub(r',\s*]', ']', fixed)
                results = json.loads(fixed)
                if isinstance(results, list):
                    result_map = {}
                    for idx, r in enumerate(results):
                        if not isinstance(r, dict):
                            continue
                        ex = r.get("examples", [])
                        if ex and isinstance(ex[0], str):
                            r["examples"] = [{"en": s, "zh": ""} for s in ex]
                        word_key = r.get("word", "").lower()
                        if word_key:
                            result_map[word_key] = r
                        elif idx < len(words_ctx):
                            result_map[words_ctx[idx]["word"].lower()] = r
                    return result_map
            except:
                pass
            print(f"  ⚠ JSON parse error: {e}")
        except Exception as e:
            print(f"  ⚠ API error: {e}")
            time.sleep(2)

    return {}


def main():
    print("=" * 60)
    print("Overlay AI Enrichment — DeepSeek-V3")
    print("=" * 60)

    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set")
        sys.exit(1)

    if not OVERLAY_DB.exists():
        print(f"ERROR: {OVERLAY_DB} not found")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(str(OVERLAY_DB))
    conn.row_factory = sqlite3.Row

    # Find words needing AI enrichment (empty examples)
    rows = conn.execute(
        "SELECT word, pos, definitions FROM overlay WHERE examples = '[]' OR examples IS NULL OR examples = ''"
    ).fetchall()

    pending = []
    for r in rows:
        pending.append({
            "word": r["word"],
            "pos": json.loads(r["pos"]) if r["pos"] else [],
            "definitions": json.loads(r["definitions"]) if r["definitions"] else [],
        })

    if MAX_WORDS > 0:
        pending = pending[:MAX_WORDS]

    print(f"AI Model:   {DEEPSEEK_MODEL}")
    print(f"Batch size: {AI_BATCH_SIZE} words/call")
    print(f"Pending:    {len(pending)} words need AI enrichment")
    if MAX_WORDS:
        print(f"Capped at:  {MAX_WORDS}")
    print(f"PID:        {os.getpid()}")
    print()

    if not pending:
        print("Nothing to do!")
        conn.close()
        sys.exit(0)

    _status["status"] = "running"
    write_status()

    ok_count = 0
    fail_count = 0
    start_time = time.time()

    try:
        for i in range(0, len(pending), AI_BATCH_SIZE):
            batch = pending[i:i + AI_BATCH_SIZE]
            batch_words = [w["word"] for w in batch]

            _status["last_word"] = batch_words[-1]

            # Call DeepSeek
            ai_data = ai_enrich_batch(batch)

            # Update overlay rows
            for w in batch:
                word = w["word"]
                ai = ai_data.get(word.lower(), {})

                if not ai:
                    fail_count += 1
                    continue

                # Extract fields with defaults
                examples = ai.get("examples", [])
                synonyms = ai.get("synonyms", [])
                antonyms = ai.get("antonyms", [])
                collocations = ai.get("collocations", [])
                associations = ai.get("associations", [])
                etymology = ai.get("etymology", "")

                if not examples:
                    fail_count += 1
                    continue

                try:
                    conn.execute("""
                        UPDATE overlay SET
                            examples = ?,
                            synonyms = ?,
                            antonyms = ?,
                            collocations = ?,
                            associations = ?,
                            etymology = ?,
                            source = 'ecdict+ai',
                            updated_at = ?
                        WHERE word = ?
                    """, (
                        json.dumps(examples, ensure_ascii=False),
                        json.dumps(synonyms, ensure_ascii=False),
                        json.dumps(antonyms, ensure_ascii=False),
                        json.dumps(collocations, ensure_ascii=False),
                        json.dumps(associations, ensure_ascii=False),
                        etymology,
                        time.strftime("%Y-%m-%dT%H:%M:%S"),
                        word,
                    ))
                    ok_count += 1
                except Exception as e:
                    print(f"  ✗ DB error for {word}: {e}")
                    fail_count += 1

            _status["words_done"] = ok_count
            _status["words_fail"] = fail_count

            # Commit every batch (minimal data loss on crash)
            conn.commit()
            if ok_count > 0 and ok_count % COMMIT_EVERY == 0:
                elapsed = time.time() - start_time
                rate = ok_count / elapsed * 60 if elapsed > 0 else 0
                print(f"  Progress: {ok_count}/{len(pending)} "
                      f"({rate:.1f} w/min, "
                      f"{_status['ai_calls']} calls, {_status['ai_tokens']} tokens)")

            # Periodic git push every PUSH_EVERY words
            if ok_count > 0 and ok_count % PUSH_EVERY == 0:
                import subprocess
                print(f"  Git push checkpoint at {ok_count} words...")
                try:
                    subprocess.run(["git", "add", "dictionary/overlay.db"], cwd=str(OVERLAY_DB.parent.parent), check=True)
                    subprocess.run(["git", "commit", "-m", f"chore: overlay AI enrichment checkpoint {ok_count} words"], cwd=str(OVERLAY_DB.parent.parent), check=True)
                    subprocess.run(["git", "push"], cwd=str(OVERLAY_DB.parent.parent), check=True)
                    print(f"  Pushed {ok_count} words to remote")
                except Exception as e:
                    print(f"  ⚠ Git push failed: {e} (non-fatal, continuing)")

            write_status()
            time.sleep(AI_DELAY)

        # Final commit
        conn.commit()
        _status["status"] = "done"
        write_status()

        elapsed = time.time() - start_time
        print()
        print("=" * 60)
        print(f"DONE! Time: {elapsed/60:.1f}min")
        print(f"Words: {ok_count} enriched, {fail_count} failed")
        print(f"AI: {_status['ai_calls']} calls, {_status['ai_tokens']} tokens")
        # Cost estimate: DeepSeek-V3 ¥2/M input + ¥8/M output
        est_cost = _status["ai_tokens"] * 5 / 1_000_000  # average ¥5/M tokens
        print(f"Estimated cost: ¥{est_cost:.2f}")

    except Exception as e:
        conn.commit()  # save progress
        _status["status"] = "error"
        _status["error"] = traceback.format_exc()
        write_status()
        print(f"\nERROR: {e}")
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
