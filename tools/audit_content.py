#!/usr/bin/env python3
"""moread-content 离线只读质量审计（词库 vocabulary/ + 词典 dictionary/overlay.db + 教材词表）。

原则
  * 只读：overlay.db 以 SQLite URI `mode=ro&immutable=1` 打开，不会生成 -wal/-shm，不改任何文件
    （除非显式传 --update-baseline / --report / --issues-csv）。
  * 离线：不访问网络、不调用任何 AI。可选依赖 `cmudict`（requirements.txt 已包含），
    未安装时跳过音节数/拼写交叉校验，并在结果中注明。
  * 基线：tools/audit_baseline.json 记录每项问题计数和字段覆盖率。
    问题计数 > 基线、或覆盖率 < 基线 → 退出码 1（回归）。修复后用 --update-baseline 下调基线。

用法
  python tools/audit_content.py                       # 与基线比对，打印摘要
  python tools/audit_content.py --report /tmp/r.md --issues-csv /tmp/i.csv
  python tools/audit_content.py --update-baseline     # 修复后重写基线（需在 PR 中说明）
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "dictionary" / "overlay.db"
DEFAULT_BASELINE = ROOT / "tools" / "audit_baseline.json"

CJK = re.compile(r"[\u4e00-\u9fff]")
IPA_OK = set("abdefhijklmnoprstuvwzæðŋɑɒɔəɚɛɜɝɡɪɫɹɾʃʊʌʒʔθːˈˌ.()ʍɐɘɵɨʉɯɤøœɶɞʏʎɲɳɴʀʁχʝɣɦɬɮʋɥʤʧ̩̃͡ɕʑçɟ ̯ᵻᵿ‿-yxcqg")
IPA_VOWEL_RE = re.compile(r"[aeiouæɑɒɔəɚɛɜɝɪʊʌɐ]+")
PLACEHOLDER = re.compile(r"^\s*(n/?a|none|null|tbd|todo|\.\.\.|…|-|—|example|placeholder|xxx|\?+)\s*$", re.I)
TERMINAL = tuple('.!?"\'”’)）。！？')
JSON_FIELDS = ["pos", "definitions", "examples", "synonyms", "antonyms", "collocations",
               "associations", "etymology", "forms", "field_meta", "phonetic_sources"]
JSON_DEFAULTS = {"etymology": "{}", "field_meta": "{}", "phonetic_sources": "{}"}
# 规范词性（与 api/ 返回、Moread 后端按 definitions[].pos 分组展示保持一致的常见写法）
CANONICAL_POS = {"n.", "v.", "vt.", "vi.", "adj.", "adv.", "prep.", "conj.", "pron.", "num.",
                 "art.", "det.", "int.", "aux.", "abbr."}
ECDICT_POS_LETTER = {"j.", "r.", "i.", "c.", "p.", "m.", "d.", "u.", "a.", "t.", "x.", "e."}
# 英文释义行首 WordNet 词性字母（无点："n v s r"；带点："n. v. a. s. r."）。不含无点 "a "（与冠词歧义）。
WORDNET_PREFIX_RE = re.compile(r"^(?:([nvsr]) |([nvasr])\. )(?=[a-z(`'\"])")
SHORT_OK = {"a", "i", "an", "am", "as", "at", "be", "by", "do", "go", "he", "hi", "if", "in", "is",
            "it", "me", "my", "no", "of", "oh", "ok", "on", "or", "so", "to", "up", "us", "we"}
KID_UNSAFE = re.compile(r"^(porn\w*|sexy|xxx|nudes|fuck\w*|shit\w*|dick|cock|pussy|anal|tits|boobs|horny|"
                        r"escorts|viagra|cialis|casino|poker|holdem|bdsm|fetish|hentai|milf|slut|whore|"
                        r"beastality|bestiality|penis|vagina|erotic|livecam|webcam|thumbzilla|transsexual|"
                        r"shemale|incest|rape)$")
CODE_ONLY_RE = re.compile(r"^[pdi3srt01]{1,3}$")  # ECDICT exchange 代码残留


# ───────────────────────── 公共工具（tools/fix_rules.py 复用） ─────────────────────────

def open_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_cmu():
    """返回 {word: {音节数,...}}；未安装 cmudict 时返回 None。"""
    try:
        import cmudict  # type: ignore
    except Exception:
        return None
    d: dict[str, set[int]] = defaultdict(set)
    for w, ph in cmudict.entries():
        d[w.lower()].add(sum(1 for x in ph if x[-1:].isdigit()))
    return d


def is_monosyllable(word: str, ipa: str, cmu) -> bool:
    """单音节判断：CMU 可用时要求 CMU 全部读音都是 1 个音节；否则用 IPA 元音组数 == 1。"""
    if " " in word or "-" in word:
        return False
    body = ipa.strip("/")
    if "̩" in body or len(IPA_VOWEL_RE.findall(body)) != 1:
        return False
    if cmu is not None:
        return word.lower() in cmu and cmu[word.lower()] == {1}
    return True


def jl(s, default):
    try:
        return json.loads(s), None
    except Exception as e:  # noqa: BLE001
        return default, str(e)


def inflections(word: str, forms) -> set[str]:
    w = word.lower()
    out = {w}
    for f in forms or []:
        if isinstance(f, dict) and f.get("form"):
            out.add(str(f["form"]).lower())
        elif isinstance(f, str):
            out.add(f.lower().split(":")[-1])
    if " " in w:
        return out
    out |= {w + "s", w + "es", w + "ed", w + "d", w + "ing", w + "er", w + "est", w + "ly", w + "'s"}
    if w.endswith("y"):
        out |= {w[:-1] + "ies", w[:-1] + "ied", w[:-1] + "ier", w[:-1] + "iest", w[:-1] + "ily"}
    if w.endswith("e"):
        out |= {w[:-1] + "ing", w[:-1] + "ed", w[:-1] + "er", w[:-1] + "est"}
    if w.endswith("ie"):
        out.add(w[:-2] + "ying")
    if len(w) >= 3 and w[-1] not in "aeiouwxy" and w[-2] in "aeiou":
        out |= {w + w[-1] + "ed", w + w[-1] + "ing", w + w[-1] + "er", w + w[-1] + "est"}
    if w.endswith("c"):
        out |= {w + "ked", w + "king"}
    return out


def headword_in(text: str, word: str, infl: set[str]) -> bool:
    t = text.lower()
    if " " in word or "-" in word:
        return any(x in t for x in infl) or all(p in t for p in re.split(r"[ -]", word.lower()) if len(p) > 2)
    toks = set(re.findall(r"[a-z]+(?:'[a-z]+)?", t))
    if toks & infl:
        return True
    return any(tok.startswith(word.lower()) and len(word) >= 4 for tok in toks)


def ipa_issue(p: str) -> str | None:
    if not p:
        return "empty"
    if not (p.startswith("/") and p.endswith("/")):
        return "no_slashes"
    body = p[1:-1]
    if not body.strip():
        return "empty_body"
    if re.search(r"[0-9!%=*^,;:']|ә", body):
        return "ascii_or_cyrillic_junk"
    bad = {ch for ch in body if ch not in IPA_OK}
    if bad:
        return "nonstandard_chars"
    return None


def syll_count(s: str) -> int:
    return s.count("-") + 1 if s else 0


def load_pack_words(p: Path):
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("words", []) if isinstance(d, dict) else d


# ───────────────────────── 词典审计 ─────────────────────────

def audit_dictionary(db: Path, cmu, sample_n: int, seed: int):
    con = open_ro(db)
    rows = [dict(r) for r in con.execute("SELECT * FROM overlay")]
    con.close()
    N = len(rows)
    cov: Counter = Counter()
    iss: Counter = Counter()
    issues: list[dict] = []
    examples: dict[str, list] = defaultdict(list)

    def flag(word, kind, detail=""):
        iss[kind] += 1
        issues.append({"word": word, "issue": kind, "detail": str(detail)[:200]})
        if len(examples[kind]) < 5:
            examples[kind].append((word, str(detail)[:120]))

    for w, n in Counter(r["word"].lower() for r in rows).items():
        if n > 1:
            flag(w, "duplicate_word_ci", n)

    for r in rows:
        w = r["word"]
        P = {}
        for f in JSON_FIELDS:
            P[f], err = jl(r[f] or JSON_DEFAULTS.get(f, "[]"), None)
            if err:
                flag(w, f"json_error:{f}", err)
        if w != w.strip() or "  " in w:
            flag(w, "headword_whitespace")
        if len(w) <= 2 and w not in SHORT_OK:
            flag(w, "headword_suspicious_short", w)
        if r["audit_pass"] != 2:
            flag(w, "hidden_audit_pass_not_2", r["audit_pass"])

        # 音标
        for col in ("phonetic", "phonetic_uk", "phonetic_us"):
            if r[col]:
                cov[col] += 1
                e = ipa_issue(r[col])
                if e:
                    flag(w, f"ipa_{e}:{col}", r[col])
                if "ʰ" in r[col]:
                    flag(w, f"ipa_aspiration_mark:{col}", r[col])
                if r[col].strip("/").startswith("ˈ") and is_monosyllable(w, r[col], cmu):
                    flag(w, f"ipa_stress_on_monosyllable:{col}", r[col])
        if r["phonetic_uk"] or r["phonetic_us"]:
            cov["phonetic_uk_or_us"] += 1
        ph = r["phonetic"] or ""
        body = ph.strip("/")
        if re.search(r"[bcdfgklmnprstvzθðʃʒŋ]ˈ[aeiouæɑɒɔəɛɜɪʊʌ]", body) and not re.search(r"[ptkbdg]ˈ[ɹrlj]", body):
            flag(w, "ipa_espeak_stress_before_vowel:phonetic", ph)
        if r["phonetic_variant_status"] == "conflict":
            iss["info_phonetic_conflict_unresolved"] += 1
        srcs = P["phonetic_sources"] or {}
        cands = (srcs.get("candidates") or {}) if isinstance(srcs, dict) else {}
        for dia, lst in cands.items():
            if isinstance(lst, list) and len(lst) != len({json.dumps(x, sort_keys=True) for x in lst}):
                flag(w, "phonetic_sources_duplicate_candidates", dia)
                break

        # 词性
        pos = P["pos"] or []
        if pos:
            cov["pos"] += 1
        if any(":" in str(x) for x in pos):
            flag(w, "pos_ecdict_ratio_format", pos)
        elif any(str(x) not in CANONICAL_POS for x in pos):
            flag(w, "pos_noncanonical", pos)

        # 释义
        defs = P["definitions"] or []
        zh_any = False
        meanings = 0
        webster = prefix_leak = bracket = False
        for d in defs if isinstance(defs, list) else []:
            if not isinstance(d, dict):
                continue
            dp = str(d.get("pos") or "")
            if dp and dp not in CANONICAL_POS:
                iss["info_def_pos_noncanonical"] += 1
            if not dp:
                iss["info_def_pos_empty"] += 1
            for m in d.get("meanings") or []:
                meanings += 1
                zh = (m.get("zh") or "").strip()
                en = (m.get("en") or "").strip()
                if zh and CJK.search(zh):
                    zh_any = True
                elif zh:
                    flag(w, "def_zh_not_chinese", zh)
                else:
                    iss["info_meanings_with_empty_zh"] += 1
                if en and re.search(r"See [A-Z][a-z]+\.|\n\s{2,}|-- used", en):
                    webster = True
                if any(WORDNET_PREFIX_RE.match(line) for line in en.split("\n")):
                    prefix_leak = True
                if zh.count("[") != zh.count("]"):
                    bracket = True
                if PLACEHOLDER.match(zh or "x") or PLACEHOLDER.match(en or "x"):
                    flag(w, "def_placeholder", m)
        if meanings:
            cov["definitions"] += 1
        if zh_any:
            cov["definitions_zh"] += 1
        else:
            flag(w, "def_no_chinese", json.dumps(defs, ensure_ascii=False)[:120])
        if webster:
            flag(w, "def_en_webster1913_raw_text")
        if prefix_leak:
            flag(w, "def_en_wordnet_pos_prefix_leak")
        if bracket:
            flag(w, "def_zh_unbalanced_bracket")

        # 例句
        ex = P["examples"] or []
        infl = inflections(w, P["forms"])
        if ex:
            cov["examples"] += 1
        for e in ex if isinstance(ex, list) else []:
            if not isinstance(e, dict):
                flag(w, "example_bad_shape", e)
                continue
            en = (e.get("en") or "").strip()
            zh = (e.get("zh") or "").strip()
            if not en:
                flag(w, "example_en_empty")
                continue
            if not zh or not CJK.search(zh):
                flag(w, "example_zh_missing", en)
            if CJK.search(en):
                flag(w, "example_en_has_chinese", en)
            if not headword_in(en, w, infl):
                flag(w, "example_missing_headword", en)
            if not en.endswith(TERMINAL) or en.endswith(("...", "…")):
                flag(w, "example_maybe_truncated", en)

        # 同义/反义/搭配/联想
        for f in ("synonyms", "antonyms", "collocations", "associations"):
            v = P[f] or []
            if v:
                cov[f] += 1
            if v and isinstance(v[0], dict):
                flag(w, f"schema_dict_variant:{f}")
            flat = []
            for x in v:
                if isinstance(x, str):
                    flat.append(x)
                elif isinstance(x, dict):
                    flat += [str(y) for y in (x.get("words") or [x.get("phrase") or x.get("word") or ""])]
            if any(PLACEHOLDER.match(x) or not x.strip() for x in flat):
                flag(w, f"placeholder:{f}", flat)
            if f in ("synonyms", "antonyms") and w.lower() in {x.lower() for x in flat}:
                flag(w, f"self_reference:{f}", flat)
        sy = {x.lower() for x in (P["synonyms"] or []) if isinstance(x, str)}
        an = {x.lower() for x in (P["antonyms"] or []) if isinstance(x, str)}
        if sy & an:
            flag(w, "synonym_antonym_overlap", sy & an)

        # 词源
        et = P["etymology"] or {}
        txt = (et.get("summary") or et.get("origin") or "") if isinstance(et, dict) else ""
        if txt:
            cov["etymology"] += 1
        if isinstance(et, dict) and set(et) - {"summary"}:
            flag(w, "schema_dict_variant:etymology")
        if txt and not txt.rstrip().endswith(TERMINAL):
            flag(w, "etymology_maybe_truncated", txt)

        # 音节
        s = r["syllables"] or ""
        if s:
            cov["syllables"] += 1
        if s and " " not in w and s.replace("-", "") != w.replace("-", ""):
            flag(w, "syllables_spelling_mismatch", s)
        if s and cmu is not None and " " not in w and w in cmu and syll_count(s) not in cmu[w]:
            flag(w, "syllables_count_vs_cmu", f"{s} cmu={sorted(cmu[w])}")

        # CEFR / 词形
        if r["cefr"]:
            cov["cefr"] += 1
        forms = P["forms"] or []
        if forms:
            cov["forms"] += 1
        if any(isinstance(f, str) for f in forms):
            flag(w, "forms_string_items_dropped_by_api", forms[:4])
        for f in forms if isinstance(forms, list) else []:
            ff = f.get("form", "") if isinstance(f, dict) else str(f)
            code_junk = (len(ff) == 1 and ff.lower() not in ("a", "i")) or \
                (bool(CODE_ONLY_RE.match(ff.lower())) and (cmu is None or ff.lower() not in cmu))
            if (isinstance(f, dict) and f.get("type") == "variant") or code_junk \
                    or not re.fullmatch(r"[a-z][a-z'\- ]*", ff.lower()):
                flag(w, "forms_junk_value", f)
                break
        for f in forms if isinstance(forms, list) else []:
            if isinstance(f, dict) and f.get("type") == "plural" and w.endswith("s") and f.get("form") == w + "s":
                flag(w, "forms_bad_plural_ss", f.get("form"))
                break

    by_word = {r["word"]: r for r in rows}
    rng = random.Random(seed)
    sample = rng.sample(rows, min(sample_n, N))
    return {
        "N": N, "cov": cov, "iss": iss, "issues": issues, "examples": examples,
        "words": set(by_word), "by_word": by_word, "sample": sample,
        "cefr_dist": Counter(r["cefr"] or "∅" for r in rows),
    }


# ───────────────────────── 词库审计 ─────────────────────────

def audit_packs(repo: Path, overlay_words: set[str], cmu):
    vdir = repo / "vocabulary"
    idx = json.loads((vdir / "index.json").read_text(encoding="utf-8"))
    rows, listed, errors = [], set(), []
    for e in idx:
        f = vdir / e["file"]
        listed.add(f.resolve())
        row = {"id": e["id"], "index_count": e.get("word_count")}
        if not f.exists():
            errors.append(f"{e['id']}: file missing {e['file']}")
            rows.append(row)
            continue
        raw = json.loads(f.read_text(encoding="utf-8"))
        ws = raw.get("words", []) if isinstance(raw, dict) else raw
        strs = [x for x in ws if isinstance(x, str)]
        uniq = {x.strip().lower() for x in strs}
        row.update({
            "actual": len(ws),
            "unique": len(uniq),
            "non_string": len(ws) - len(strs),
            "dups_ci": len(strs) - len(uniq),
            "whitespace": sum(1 for x in strs if x != x.strip() or "  " in x),
            "uppercase": sum(1 for x in strs if x != x.lower()),
            "junk": sum(1 for x in strs if not re.fullmatch(r"[A-Za-z][A-Za-z'’.\- ]*", x.strip())
                        or (len(x.strip()) == 1 and x.strip().lower() not in "ai")),
            "missing_in_overlay": sum(1 for x in uniq if x not in overlay_words),
            "kid_unsafe": sorted(x for x in uniq if KID_UNSAFE.match(x)),
        })
        if cmu is not None:
            row["not_in_cmu"] = sum(1 for x in uniq if " " not in x and "-" not in x and x not in cmu)
        if row["index_count"] != row["actual"]:
            errors.append(f"{e['id']}: index.json word_count={row['index_count']} != actual {row['actual']}")
        rows.append(row)
    orphan = [str(p.relative_to(vdir)) for p in vdir.rglob("*.json")
              if p.name != "index.json" and p.resolve() not in listed]
    errors += [f"orphan pack file not in index.json: {o}" for o in orphan]
    total = sum(r.get("actual", 0) for r in rows)
    readme = (repo / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*总计\s*([\d,]+)\s*词", readme)
    readme_total = int(m.group(1).replace(",", "")) if m else None
    if readme_total is not None and readme_total != total:
        errors.append(f"README 总计 {readme_total} 词 != 全部词库实际合计 {total}")
    m = re.search(r"系统内置词库（(\d+) 个", readme)
    if m and int(m.group(1)) != len(idx):
        errors.append(f"README 写 {m.group(1)} 个词库 != index.json {len(idx)} 个")
    return rows, errors, total


# ───────────────────────── 教材词表审计 ─────────────────────────

def audit_textbooks(repo: Path, cmu):
    out = {}
    for f in sorted((repo / "textbook").rglob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        items = []
        for u in d.get("units") or []:
            items += u.get("key_vocabulary") or []
            for su in u.get("sub_units") or []:
                items += su.get("key_vocabulary") or []
        v = d.get("vocabulary")
        if isinstance(v, dict):
            for lst in v.values():
                items += lst if isinstance(lst, list) else []
        words = {(x.get("word") if isinstance(x, dict) else str(x)).strip() for x in items if x}
        dropped = 0
        if cmu is not None:
            dropped = sum(1 for w in words if " " not in w and w.lower() not in cmu
                          and any((ch + w.lower()) in cmu for ch in "abcdefghijklmnopqrstuvwxyz"))
        bad_ipa = sum(1 for x in items if isinstance(x, dict) and x.get("phonetic")
                      and re.search(r"[0-9ә']", x["phonetic"]))
        out[str(f.relative_to(repo))] = {
            "units": len(d.get("units") or (v or {})),
            "words": len(words),
            "ocr_first_letter_dropped": dropped,
            "phonetic_polluted": bad_ipa,
            "parallel_articles": sum(len(u.get("parallel_articles") or []) for u in d.get("units") or []),
        }
    return out


# ───────────────────────── 基线比对 ─────────────────────────

def build_metrics(D, packs, tb, cmu_on, errors):
    m = {"dictionary.entries": D["N"], "structure.errors": len(errors)}
    for k, v in D["iss"].items():
        m[f"dictionary.issue.{k}"] = v
    for p in packs:
        for k in ("dups_ci", "whitespace", "uppercase", "junk", "missing_in_overlay", "non_string", "not_in_cmu"):
            if k in p:
                m[f"pack.{p['id']}.{k}"] = p[k]
        if "kid_unsafe" in p:
            m[f"pack.{p['id']}.kid_unsafe"] = len(p["kid_unsafe"])
    for f, t in tb.items():
        m[f"textbook.{f}.ocr_first_letter_dropped"] = t["ocr_first_letter_dropped"]
        m[f"textbook.{f}.phonetic_polluted"] = t["phonetic_polluted"]
    cov = {k: D["cov"][k] for k in sorted(D["cov"])}
    return {"cmudict": cmu_on, "issues": dict(sorted(m.items())), "coverage": cov}


def compare(cur, base):
    regress, improved = [], []
    if base.get("cmudict") and not cur["cmudict"]:
        print("WARN: 基线含 CMU 校验但当前未安装 cmudict，CMU 相关项跳过比对", file=sys.stderr)
    for k, v in cur["issues"].items():
        b = base.get("issues", {}).get(k, 0)
        if (".not_in_cmu" in k or "vs_cmu" in k or "ocr_first" in k or "monosyllable" in k) and not cur["cmudict"]:
            continue
        if k == "dictionary.entries":
            continue
        if v > b:
            regress.append(f"issue {k}: {b} -> {v}")
        elif v < b:
            improved.append(f"issue {k}: {b} -> {v}")
    for k, b in base.get("issues", {}).items():
        if k not in cur["issues"] and b:
            improved.append(f"issue {k}: {b} -> 0")
    for k, b in base.get("coverage", {}).items():
        v = cur["coverage"].get(k, 0)
        if v < b:
            regress.append(f"coverage {k}: {b} -> {v}")
    return regress, improved


def md_table(headers, rows):
    s = "| " + " | ".join(headers) + " |\n|" + "---|" * len(headers) + "\n"
    for r in rows:
        s += "| " + " | ".join(str(x).replace("|", "/") for x in r) + " |\n"
    return s


def write_report(path: Path, D, packs, tb, errors, total, cmu_on):
    N = D["N"]
    L = ["# moread-content 质量审计报告\n\n",
         f"- 词典条目 {N}；CMU 交叉校验：{'开' if cmu_on else '关'}；词库合计 {total} 条\n\n",
         "## 字段覆盖率\n\n",
         md_table(["字段", "条目"], [(k, f"{v} ({100 * v / N:.1f}%)") for k, v in sorted(D["cov"].items())]),
         "\n## 问题计数\n\n",
         md_table(["问题", "条目数", "示例"], [(k, v, "; ".join(f"`{w}` {d}" for w, d in D["examples"].get(k, [])[:3]))
                                          for k, v in sorted(D["iss"].items(), key=lambda x: -x[1])]),
         "\n## overlay.cefr 分布\n\n", ", ".join(f"{k}={v}" for k, v in sorted(D["cefr_dist"].items())), "\n",
         "\n## 词库\n\n",
         md_table(["id", "index", "实际", "重复", "大小写", "空白", "垃圾", "overlay缺失", "不在CMU", "少儿敏感"],
                  [(p["id"], p.get("index_count"), p.get("actual"), p.get("dups_ci"), p.get("uppercase"),
                    p.get("whitespace"), p.get("junk"), p.get("missing_in_overlay"), p.get("not_in_cmu", "-"),
                    ", ".join(p.get("kid_unsafe", []))) for p in packs]),
         "\n## 教材词表\n\n",
         md_table(["文件", "单元", "词数", "疑似OCR首字母丢失", "音标污染", "平行文章"],
                  [(f, t["units"], t["words"], t["ocr_first_letter_dropped"], t["phonetic_polluted"], t["parallel_articles"])
                   for f, t in tb.items()]),
         "\n## 结构错误\n\n", "\n".join(f"- {e}" for e in errors) or "无", "\n",
         f"\n## 随机抽样 {len(D['sample'])} 条\n\n"]
    for r in D["sample"]:
        L.append(f"- **{r['word']}** `{r['phonetic']}` pos={r['pos']} cefr={r['cefr']} syl={r['syllables']}\n"
                 f"  - defs: {r['definitions'][:220]}\n  - ex: {r['examples'][:200]}\n")
    path.write_text("".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--db", type=Path, default=None, help="默认 <repo>/dictionary/overlay.db")
    ap.add_argument("--baseline", type=Path, default=None, help="默认 <repo>/tools/audit_baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--report", type=Path, help="写 Markdown 报告到该路径（建议放仓库外或 /tmp）")
    ap.add_argument("--issues-csv", type=Path, help="写逐条问题 CSV 到该路径")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261008)
    a = ap.parse_args()
    db = a.db or a.repo / "dictionary" / "overlay.db"
    baseline_path = a.baseline or a.repo / "tools" / "audit_baseline.json"

    cmu = load_cmu()
    D = audit_dictionary(db, cmu, a.sample, a.seed)
    packs, errors, total = audit_packs(a.repo, D["words"], cmu)
    tb = audit_textbooks(a.repo, cmu)
    cur = build_metrics(D, packs, tb, cmu is not None, errors)

    if a.report:
        write_report(a.report, D, packs, tb, errors, total, cmu is not None)
    if a.issues_csv:
        with open(a.issues_csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, ["word", "issue", "detail"])
            wr.writeheader()
            wr.writerows(D["issues"])

    print(f"overlay 条目 {D['N']}；词库 {len(packs)} 个 / {total} 条；CMU={'on' if cmu else 'off'}")
    for e in errors:
        print(f"STRUCTURE: {e}")
    if a.update_baseline:
        baseline_path.write_text(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        print(f"baseline updated: {baseline_path}")
        return 0
    if not baseline_path.exists():
        print(f"no baseline at {baseline_path}; run with --update-baseline", file=sys.stderr)
        return 1
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    regress, improved = compare(cur, base)
    for x in improved:
        print(f"IMPROVED {x}")
    for x in regress:
        print(f"REGRESSION {x}")
    if regress:
        print(f"FAIL: {len(regress)} 项比基线变差", file=sys.stderr)
        return 1
    if improved:
        print("OK（有改进：可在同一 PR 中用 --update-baseline 下调基线）")
    else:
        print("OK（与基线一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
