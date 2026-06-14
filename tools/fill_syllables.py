"""填充 overlay.db 的 syllables 列

数据源优先级:
  1. pyphen en_US (left=1, right=2) — TeX 连字符模式，辅音群准确
  2. NLTK SSP SyllableTokenizer — 元音核探测，修复 pyphen 漏切
  3. CMU Pronouncing Dictionary — 音节数仲裁

已知限制:
  - 缩略词/专有名词（abs, ac, aaa...）CMU 数量可能与拼写不符，忽略
  - CMU 语音缩读（basically=3音）与拼写音节（ba-sic-al-ly=4）不同时，保留拼写音节
  - 少量法语借词（analogue, baroque）末尾静音-e 无法自动识别，留 review CSV 人工修正
"""

import sqlite3
import csv
from pathlib import Path

import pyphen
from nltk.tokenize import SyllableTokenizer
from nltk.corpus import cmudict

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "dictionary" / "overlay.db"
CSV_PATH = BASE_DIR / "dictionary" / "syllables_review.csv"

_dic     = pyphen.Pyphen(lang="en_US", left=1, right=2)
_SSP     = SyllableTokenizer()
_VOWELS  = set("aeiouy")


def _has_vowel(s: str) -> bool:
    return any(c in _VOWELS for c in s.lower())


def _clean(parts: list[str]) -> list[str]:
    """合并无元音的孤立片段（left=1 产生的 d-if、s-tu 等）"""
    p = list(parts)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(p):
            if not _has_vowel(p[i]):
                if i > 0:
                    p[i - 1] += p[i]; p.pop(i); changed = True
                elif len(p) > 1:
                    p[i + 1] = p[i] + p[i + 1]; p.pop(i); changed = True
                else:
                    i += 1
            else:
                i += 1
    return p


def _try_silent_e(parts: list[str], cmu_n: int | None) -> list[str]:
    """仅当能使音节数更接近 CMU 时，合并 SSP 错误拆出的词尾静音-e。
    例: abide → [a, bi, de] → [a, bide]  ✓
        abalone → [a, ba, lo, ne] → 不合并（ne 是真实音节）
    """
    if len(parts) < 2:
        return parts
    last = parts[-1].lower()
    # 末尾是 [辅音]+e，且不是 -le（table/simple 的 -le 是真实音节）
    if (last.endswith("e") and len(last) >= 2
            and last[-2] not in _VOWELS and not last.endswith("le")):
        fixed = parts[:-2] + [parts[-2] + parts[-1]]
        if cmu_n is not None and abs(len(fixed) - cmu_n) < abs(len(parts) - cmu_n):
            return fixed
    return parts


def _build_cmu_dict() -> dict[str, int]:
    entries: dict[str, int] = {}
    for word, phones in cmudict.entries():
        if word not in entries:
            entries[word] = sum(1 for p in phones if p[-1].isdigit())
    return entries


_CMU: dict[str, int] = _build_cmu_dict()


def _syl_one(part: str) -> str:
    """对单个无连字符词段做音节切分"""
    if not part or len(part) <= 1:
        return part

    raw        = _dic.inserted(part, hyphen="-").split("-")
    pyph_parts = _clean(raw)
    pyph_n     = len(pyph_parts)
    cmu_n      = _CMU.get(part.lower())

    # CMU 无条目 或 pyphen 数量匹配 → 直接用 pyphen
    if cmu_n is None or pyph_n == cmu_n:
        return "-".join(pyph_parts)

    # pyphen 少切 → SSP 补救，CMU 验证静音-e 修复
    if pyph_n < cmu_n:
        ssp_raw   = _clean(_SSP.tokenize(part))
        ssp_parts = _try_silent_e(ssp_raw, cmu_n)
        ssp_n     = len(ssp_parts)
        if abs(ssp_n - cmu_n) <= abs(pyph_n - cmu_n):
            return "-".join(ssp_parts)
        return "-".join(pyph_parts)

    # pyphen 多切（通常是 CMU 缩读导致；拼写音节数更适合教学）→ 保留 pyphen
    return "-".join(pyph_parts)


def syllabify(word: str) -> str:
    """对完整词做音节切分，处理含连字符的复合词"""
    if "-" in word:
        return "-".join(_syl_one(p) for p in word.split("-") if p)
    return _syl_one(word)


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))

    # 确保列存在（首次运行时建列；已有列时忽略错误）
    try:
        conn.execute("ALTER TABLE overlay ADD COLUMN syllables TEXT")
        conn.commit()
        print("[fill_syllables] Added column 'syllables'")
    except sqlite3.OperationalError:
        pass  # 列已存在

    rows = conn.execute("SELECT word FROM overlay").fetchall()
    print(f"[fill_syllables] Processing {len(rows)} words …")

    batch: list[tuple[str, str]] = []
    results: list[tuple[str, str, int]] = []

    for (word,) in rows:
        syl = syllabify(word)
        batch.append((syl, word))
        results.append((word, syl, syl.count("-") + 1))
        if len(batch) >= 500:
            conn.executemany("UPDATE overlay SET syllables=? WHERE word=?", batch)
            batch.clear()

    if batch:
        conn.executemany("UPDATE overlay SET syllables=? WHERE word=?", batch)

    conn.commit()

    # 验证
    filled = conn.execute("SELECT COUNT(*) FROM overlay WHERE syllables IS NOT NULL").fetchone()[0]
    total  = len(rows)
    conn.close()
    print(f"[fill_syllables] Filled {filled}/{total} words")

    # 输出 review CSV（按词排序）
    results.sort(key=lambda r: r[0].lower())
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["word", "syllables", "syllable_count"])
        w.writerows(results)
    print(f"[fill_syllables] Review CSV → {CSV_PATH}")

    # 音节分布
    dist: dict[int, int] = {}
    for _, _, n in results:
        dist[n] = dist.get(n, 0) + 1
    print("[fill_syllables] Distribution:")
    for k in sorted(dist):
        print(f"  {k} syllable(s): {dist[k]:6d}")


if __name__ == "__main__":
    main()
