#!/usr/bin/env python3
"""确定性规则修复（无网络、无 AI、不 commit/push）。

只做可由规则完全决定的格式修复，不改语义：
  pos_canonical      overlay.pos：ECDICT 比例格式 `n:40/v:60` 与字母码 `j./r./i./u./m./d./a./p./c.`
                     → 规范写法 n./v./adj./adv./prep./conj./pron./num./det./art./int.（按比例降序，去重）
  def_pos_canonical  definitions[].pos：WordNet/ECDICT 的 a./s./j.→adj.，r.→adv.，interj.→int.
  en_prefix_strip    definitions[].meanings[].en 行首 WordNet 词性字母（"v make…"、"n. a score…"、"s …"、"r …"）
                     去掉；所在义项块 pos 为空时用该字母补全；与块 pos 冲突时保留证据到 meaning.en_pos
                     （不做义项重配）。无点的 "a " 与冠词歧义，不处理；含 Webster 原文的不处理。
  forms_clean        forms：去掉 ECDICT exchange 代码残留（variant/"3"/"s3"/"dp"、单字母）、未知类型 f/b/z 的重复项、
                     `…ss` 双写复数（以 ss 结尾的词改为 +es，否则删除该项）、明确非名词词条上的 plural、重复项；
                     字符串列表按规则形态学转成 [{type, form}]（API 只输出 dict 形式）
  ipa_cleanup        phonetic / phonetic_uk / phonetic_us：去掉送气符 ʰ；CMU 确认单音节时去掉首位重音符 ˈ。
                     不改写 eSpeak 风格音标（仍由审计标记）。
  phonetic_sources_dedupe  phonetic_sources.candidates 中完全相同的候选去重
  readme_counts      README 词库数/总词数/词库一览表按 vocabulary/index.json 重新生成

不做：CEFR、义项重配、删除词条、敏感词、词库增删词（需人工决策）。
幂等：重复运行不会产生新变更。

用法
  python tools/fix_rules.py --dry-run            # 只统计，不写
  python tools/fix_rules.py --log /tmp/fix.jsonl # 写库 + 完整变更日志
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_content import CODE_ONLY_RE, is_monosyllable, load_cmu  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CMU = None  # 由 main() 载入；用于判断 "its"/"id"/"i" 这类真实词不是 exchange 代码


def is_code_junk(f: str) -> bool:
    f = f.strip().lower()
    if len(f) == 1:
        return f not in ("a", "i")
    return bool(CODE_ONLY_RE.match(f)) and (CMU is None or f not in CMU)

ECDICT_CODE = {"n": "n.", "v": "v.", "j": "adj.", "r": "adv.", "i": "prep.", "c": "conj.", "p": "pron.",
               "m": "num.", "d": "det.", "u": "int."}
DEF_POS_MAP = {"a.": "adj.", "s.": "adj.", "j.": "adj.", "r.": "adv.", "interj.": "int."}
PREFIX_MAP = {"n": "n.", "v": "v.", "s": "adj.", "a": "adj.", "r": "adv."}
PREFIX_RE = re.compile(r"^(?:([nvsr]) |([nvasr])\. )(?=[a-z(`'\"])")
WEBSTER_RE = re.compile(r"See [A-Z][a-z]+\.|\n\s{2,}|-- used|^[a-z]\. [a-z]\. ")
VERBISH = {"v.", "vt.", "vi."}


def code_pos(code: str, word: str) -> str | None:
    if code == "a":
        return "art." if word in ("a", "an", "the") else "det."
    return ECDICT_CODE.get(code)


def canon_pos(word: str, pos: list) -> list:
    out: list[str] = []
    for item in pos:
        s = str(item).strip()
        if ":" in s:
            parts = []
            for part in s.split("/"):
                if ":" not in part:
                    continue
                code, ratio = part.split(":", 1)
                try:
                    r = int(ratio)
                except ValueError:
                    r = 0
                parts.append((r, code_pos(code.strip(), word) or part))
            out += [p for _, p in sorted(parts, key=lambda x: -x[0])]
        elif re.fullmatch(r"[a-z]\.", s) and code_pos(s[0], word):
            out.append(code_pos(s[0], word))
        else:
            out.append(s)
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


# ── 形态学 ──
def _sets(w: str) -> dict[str, set[str]]:
    cons_y = len(w) > 1 and w.endswith("y") and w[-2] not in "aeiou"
    cvc = len(w) >= 3 and w[-1] not in "aeiouwxy" and w[-2] in "aeiou" and w[-3] not in "aeiou"
    s3 = {w + "s", w + "es"} | ({w[:-1] + "ies"} if cons_y else set())
    ing = {w + "ing"} | ({w[:-1] + "ing"} if w.endswith("e") and not w.endswith("ee") else set()) \
        | ({w[:-2] + "ying"} if w.endswith("ie") else set()) | ({w + w[-1] + "ing"} if cvc else set()) \
        | ({w + "king"} if w.endswith("c") else set())
    ed = {w + "ed"} | ({w + "d"} if w.endswith("e") else set()) | ({w[:-1] + "ied"} if cons_y else set()) \
        | ({w + w[-1] + "ed"} if cvc else set()) | ({w + "ked"} if w.endswith("c") else set())
    er = {w + "er"} | ({w + "r"} if w.endswith("e") else set()) | ({w[:-1] + "ier"} if cons_y else set()) \
        | ({w + w[-1] + "er"} if cvc else set())
    est = {w + "est"} | ({w + "st"} if w.endswith("e") else set()) | ({w[:-1] + "iest"} if cons_y else set()) \
        | ({w + w[-1] + "est"} if cvc else set())
    return {"s3": s3, "ing": ing, "ed": ed, "er": er, "est": est}


def classify_string_form(word: str, s: str, pos: set[str]) -> list[dict] | None:
    """返回 [{type, form}]；None 表示丢弃。"""
    w, f = word.lower(), s.strip().lower()
    if not f or f == w or is_code_junk(f) or not re.fullmatch(r"[a-z][a-z'\- ]*", f):
        return None
    S = _sets(w)
    has_n = "n." in pos
    has_v = bool(VERBISH & pos)
    if f in S["ing"]:
        return [{"type": "present_participle", "form": s}]
    if f in S["ed"]:
        return [{"type": "past_tense", "form": s}, {"type": "past_participle", "form": s}]
    if f in S["s3"]:
        if has_n and not has_v:
            return [{"type": "plural", "form": s}]
        if has_v and not has_n:
            return [{"type": "third_person", "form": s}]
        if has_v and has_n:
            return [{"type": "plural", "form": s}, {"type": "third_person", "form": s}]
        return [{"type": "inflection", "form": s}]
    if f in S["er"] and "adj." in pos:
        return [{"type": "comparative", "form": s}]
    if f in S["est"] and "adj." in pos:
        return [{"type": "superlative", "form": s}]
    if any(w in v for v in _sets(f).values()):
        return [{"type": "base", "form": s}]
    return [{"type": "inflection", "form": s}]


def fix_forms(word: str, forms: list, pos: set[str], def_pos: set[str], log) -> list:
    known = {"plural", "past_tense", "past_participle", "present_participle", "third_person", "base",
             "comparative", "superlative", "inflection"}
    out: list[dict] = []
    staged: list = []
    for item in forms:
        if isinstance(item, str):
            conv = classify_string_form(word, item, pos | def_pos)
            if conv is None:
                log("forms_drop_code_or_junk", item, None)
            else:
                log("forms_string_to_dict", item, conv)
                staged += conv
        else:
            staged.append(item)
    forms = staged
    for item in forms:
        if not isinstance(item, dict):
            log("forms_drop_bad_shape", item, None)
            continue
        t, f = item.get("type"), str(item.get("form") or "")
        if t == "variant" or not f or is_code_junk(f):
            log("forms_drop_code_or_junk", item, None)
            continue
        if t not in known:
            if any(o.get("form") == f for o in out) or any(isinstance(x, dict) and x.get("type") in known and x.get("form") == f for x in forms):
                log("forms_drop_unknown_type_duplicate", item, None)
                continue
            log("forms_unknown_type_to_inflection", item, {"type": "inflection", "form": f})
            item = {"type": "inflection", "form": f}
            t = "inflection"
        if t in ("plural", "third_person") and word.endswith("s") and f == word + "s":
            if word.endswith("ss"):
                new = {"type": t, "form": word + "es"}
                log("forms_fix_double_s", item, new)
                item = new
            else:
                log("forms_drop_double_s", item, None)
                continue
        out.append(item)
    # 明确非名词：overlay.pos 非空且无 n.，释义块也无 n. → 删 plural
    all_pos = pos | def_pos
    if pos and "n." not in all_pos:
        kept = []
        for it in out:
            if it.get("type") == "plural":
                log("forms_drop_plural_on_non_noun", it, None)
            else:
                kept.append(it)
        out = kept
    seen, res = set(), []
    for it in out:
        k = (it.get("type"), it.get("form"))
        if k in seen:
            continue
        seen.add(k)
        res.append(it)
    return res


def fix_definitions(word: str, defs: list, log) -> list:
    for d in defs:
        if not isinstance(d, dict):
            continue
        p = str(d.get("pos") or "")
        if p in DEF_POS_MAP:
            log("def_pos_canonical", p, DEF_POS_MAP[p])
            d["pos"] = DEF_POS_MAP[p]
        block_prefix = set()
        for m in d.get("meanings") or []:
            en = m.get("en") or ""
            if not en or WEBSTER_RE.search(en):
                continue
            lines = en.split("\n")
            matches = [PREFIX_RE.match(line) for line in lines if line.strip()]
            if not matches or not all(matches):
                continue
            letters = {(mm.group(1) or mm.group(2)) for mm in matches}
            canon = {PREFIX_MAP[x] for x in letters}
            if len(canon) != 1:
                log("en_prefix_skip_mixed", en[:80], None)
                continue
            cp = canon.pop()
            new_en = "\n".join(PREFIX_RE.sub("", line, count=1) if line.strip() else line for line in lines)
            log("en_prefix_strip", en[:80], new_en[:80])
            m["en"] = new_en
            block_prefix.add(cp)
            cur = str(d.get("pos") or "")
            if cur and not (cur == cp or (cp == "v." and cur in VERBISH)):
                if m.get("en_pos") != cp:
                    m["en_pos"] = cp
                    log("en_pos_conflict_recorded", cur, cp)
        if not d.get("pos") and len(block_prefix) == 1:
            np = block_prefix.pop()
            log("def_pos_filled_from_prefix", "", np)
            d["pos"] = np
    return defs


def fix_ipa(word: str, ipa: str, cmu, col: str, log) -> str:
    new = ipa.replace("ʰ", "")
    if new != ipa:
        log(f"ipa_strip_aspiration:{col}", ipa, new)
    body = new.strip("/")
    if new.startswith("/") and body.startswith("ˈ") and is_monosyllable(word, new, cmu):
        newer = "/" + body[1:] + "/"
        log(f"ipa_strip_monosyllable_stress:{col}", new, newer)
        new = newer
    return new


def dedupe_sources(src: dict, log) -> dict:
    cands = src.get("candidates") if isinstance(src, dict) else None
    if not isinstance(cands, dict):
        return src
    for dia, lst in list(cands.items()):
        if not isinstance(lst, list):
            continue
        seen, res = set(), []
        for x in lst:
            k = json.dumps(x, sort_keys=True, ensure_ascii=False)
            if k not in seen:
                seen.add(k)
                res.append(x)
        if len(res) != len(lst):
            log("phonetic_sources_dedupe", len(lst), len(res))
            cands[dia] = res
    return src


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def fix_readme(repo: Path, log, dry: bool) -> None:
    idx = json.loads((repo / "vocabulary" / "index.json").read_text(encoding="utf-8"))
    total = sum(e["word_count"] for e in idx)
    n = len(idx)
    cat_name = {"cefr": "CEFR", "exam": "考试", "frequency": "词频", "basic": "基础"}
    rows = "".join(f"| {cat_name.get(e['category'], e['category'])} | {e['name']} | {e['word_count']:,} | "
                   f"{e.get('difficulty') or '—'} |\n" for e in idx)
    p = repo / "README.md"
    s = p.read_text(encoding="utf-8")
    orig = s
    s = re.sub(r"系统内置词库（\d+ 个，[\d,]+ 词）", f"系统内置词库（{n} 个，{total:,} 词）", s)
    s = re.sub(r"词库索引（\d+ 个词库）", f"词库索引（{n} 个词库）", s)
    if "│   ├── basic/" not in s:
        s = s.replace("│   ├── cefr/                ← CEFR 分级",
                      "│   ├── basic/               ← 基础英语（5 个：Ogden 850/1000、VOA 1500、国际通用词、综合 2000）\n"
                      "│   ├── cefr/                ← CEFR 分级", 1)
    s = re.sub(r"## \d+ 个词库一览\n\n\| 类别 \| 词库 \| 词数 \| 难度 \|\n\|[-|]+\|\n(?:\|.*\|\n)+\n\*\*总计 [\d,]+ 词\*\*[^\n]*",
               f"## {n} 个词库一览\n\n| 类别 | 词库 | 词数 | 难度 |\n|------|------|------|------|\n{rows}\n"
               f"**总计 {total:,} 词**（{n} 个词库词数之和，各词库之间有重叠；由 `tools/fix_rules.py` 按 `vocabulary/index.json` 生成）", s)
    if "| 基础英语 |" not in s:
        s = s.replace("| 词频词表 | Google 10K Corpus | 整理加工 |",
                      "| 词频词表 | Google 10K Corpus | 整理加工 |\n| 基础英语 | Wikipedia/Wiktionary Basic English project（Ogden / VOA Special English） | 整理加工 |", 1)
    if s != orig:
        log("readme_counts", f"README -> {n} packs / {total}", None)
        if not dry:
            p.write_text(s, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", type=Path, help="完整变更日志 JSONL（建议放仓库外）")
    ap.add_argument("--summary", type=Path, help="变更摘要 JSON（规则计数 + 每条规则前 20 个示例）")
    ap.add_argument("--skip-readme", action="store_true")
    a = ap.parse_args()
    db = a.db or a.repo / "dictionary" / "overlay.db"
    global CMU
    cmu = CMU = load_cmu()
    if cmu is None:
        print("ERROR: 需要 cmudict（pip install cmudict）用于单音节判断", file=sys.stderr)
        return 2

    counts: Counter = Counter()
    rows_changed: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    logf = open(a.log, "w", encoding="utf-8") if a.log else None
    cur_word = {"w": ""}

    def log(rule, before, after):
        counts[rule] += 1
        rec = {"word": cur_word["w"], "rule": rule, "before": before, "after": after}
        if len(examples[rule]) < 20:
            examples[rule].append(rec)
        if logf:
            logf.write(json.dumps(rec, ensure_ascii=False) + "\n")

    con = sqlite3.connect(str(db)) if not a.dry_run else sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT word, pos, definitions, forms, phonetic, phonetic_uk, phonetic_us, phonetic_sources FROM overlay")]
    updates = []
    for r in rows:
        w = r["word"]
        cur_word["w"] = w
        new = {}
        pos = json.loads(r["pos"] or "[]")
        npos = canon_pos(w, pos)
        if npos != pos:
            log("pos_canonical", pos, npos)
            new["pos"] = dumps(npos)
        defs = json.loads(r["definitions"] or "[]")
        before_defs = dumps(defs)
        defs = fix_definitions(w, defs, log)
        if dumps(defs) != before_defs:
            new["definitions"] = dumps(defs)
        def_pos = {str(d.get("pos")) for d in defs if isinstance(d, dict) and d.get("pos")}
        forms = json.loads(r["forms"] or "[]")
        nforms = fix_forms(w, forms, set(npos), def_pos, log)
        if nforms != forms:
            new["forms"] = dumps(nforms)
        for col in ("phonetic", "phonetic_uk", "phonetic_us"):
            if r[col]:
                v = fix_ipa(w, r[col], cmu, col, log)
                if v != r[col]:
                    new[col] = v
        src = json.loads(r["phonetic_sources"] or "{}")
        before_src = dumps(src)
        src = dedupe_sources(src, log)
        if dumps(src) != before_src:
            new["phonetic_sources"] = dumps(src)
        if new:
            for k in new:
                rows_changed[k] += 1
            updates.append((w, new))

    if not a.skip_readme:
        cur_word["w"] = "README.md"
        fix_readme(a.repo, log, a.dry_run)

    if not a.dry_run and updates:
        with con:
            for w, new in updates:
                cols = ", ".join(f"{k} = ?" for k in new)
                con.execute(f"UPDATE overlay SET {cols} WHERE word = ?", (*new.values(), w))
    con.close()
    if logf:
        logf.close()

    summary = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "dry_run": a.dry_run,
        "entries_changed": len(updates),
        "columns_changed": dict(sorted(rows_changed.items())),
        "rule_counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
        "examples": examples,
    }
    if a.summary:
        a.summary.parent.mkdir(parents=True, exist_ok=True)
        a.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{'DRY-RUN ' if a.dry_run else ''}entries changed: {len(updates)}")
    for k, v in summary["columns_changed"].items():
        print(f"  column {k}: {v}")
    for k, v in summary["rule_counts"].items():
        print(f"  rule {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
