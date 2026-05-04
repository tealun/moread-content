#!/usr/bin/env python3
"""
教材PDF提取脚本 —— 通用版
从有文字层的教材PDF提取: 目录结构 + 单词表 → 结构化JSON

用法: python3 extract_textbook.py <pdf_path> <output_path> <publisher_code> <level> <grade> <semester> <editor_code> <editor_name>
"""
import sys
import os
import re
import json
import pdfplumber


def split_dual_column(page):
    """分栏提取，返回 (left_text, right_text)"""
    w, h = page.width, page.height
    left = page.crop((0, 0, w / 2, h))
    right = page.crop((w / 2, 0, w, h))
    return left.extract_text() or "", right.extract_text() or ""


def find_toc_pages(pdf, max_scan=15):
    """找到目录页范围"""
    for i in range(min(max_scan, len(pdf.pages))):
        text = pdf.pages[i].extract_text() or ""
        if any(kw in text for kw in ["Scope and sequence", "Contents", "Unit 1", "Unit  1"]):
            return i
    return -1


def find_appendix_start(pdf):
    """找到附录起始页（从后往前找Grammar guide/Appendix等标记）"""
    for i in range(len(pdf.pages) - 1, max(100, len(pdf.pages) - 40), -1):
        text = pdf.pages[i].extract_text() or ""
        if any(kw in text for kw in ["Appendix", "Guide to", "Grammar guide", "注：加粗"]):
            # 找到包含附录标记的页，再往前找单词表
            for j in range(i, max(100, i - 30), -1):
                t = pdf.pages[j].extract_text() or ""
                if "Words and expressions" in t or "Words  and  expressions" in t:
                    return j
            return i
    return -1


def find_vocab_pages(pdf):
    """找到单词表页范围"""
    # 方法：找包含 "Words and expressions" 的页面
    candidates = []
    for i in range(len(pdf.pages)):
        text = pdf.pages[i].extract_text() or ""
        if "Words and expressions" in text or "Words  and  expressions" in text:
            candidates.append(i)

    if not candidates:
        return -1, -1

    # 单词表通常是连续页
    start = candidates[0]
    # 从start开始，找到连续的最后一页
    end = start
    for i in range(start + 1, len(pdf.pages)):
        # 检查这个页或下一个候选页是否仍然是单词表
        text = pdf.pages[i].extract_text() or ""
        if any(kw in text for kw in ["Words and expressions", "Words  and  expressions", "Unit ", "Starter"]):
            end = i
        else:
            # 允许1页gap
            if i + 1 < len(pdf.pages):
                next_text = pdf.pages[i + 1].extract_text() or ""
                if any(kw in next_text for kw in ["Words and expressions", "Words  and  expressions"]):
                    end = i + 1
                    continue
            break

    return start, end


def parse_vocab(pdf, start_page, end_page):
    """分栏提取并解析单词表"""
    all_text = ""
    for i in range(start_page, end_page + 1):
        left, right = split_dual_column(pdf.pages[i])
        all_text += left + "\n" + right + "\n"

    # 解析词条
    unit_markers = {}
    current_unit = "unknown"
    vocab = {}
    lines = all_text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 单元标记
        m = re.match(r'^(Starter|Unit\s+(\d+))$', line)
        if m:
            if m.group(2):
                current_unit = f"unit-{int(m.group(2))}"
            else:
                current_unit = "starter"
            if current_unit not in vocab:
                vocab[current_unit] = []
            i += 1
            continue

        # 跳过无效行
        if not line or re.match(r'^\d+$', line) or 'Words and expressions' in line or line.startswith('注：'):
            i += 1
            continue

        # 跳过纯音标行（无斜杠包裹的纯IPA字符）
        stripped = line.replace(' ', '').replace('/', '')
        if re.match(r'^[ˈˌːɪəeɪɒʌuɑɔɜəiɪʊaɛæŋðθʃʒ\-]+$', stripped) and '/' not in line:
            i += 1
            continue

        # 匹配: word /phonetic/ pos 中文 页码
        m = re.match(
            r'^([\w][\w\s\-]*?)\s*/[^/]*/\s*'
            r'((?:n\.|v\.|adj\.|adv\.|prep\.|pron\.|det\.|conj\.|interj\.|abbr\.)\s*)?'
            r'(.+?)\s+(\d{1,3})$',
            line
        )
        if m:
            word = m.group(1).strip()
            pos = (m.group(2) or "").strip()
            cn = m.group(3).strip()
            page = int(m.group(4))
            if word and current_unit not in vocab:
                vocab[current_unit] = []
            if word:
                vocab.setdefault(current_unit, []).append({
                    "word": word, "pos": pos, "cn": cn, "page": page
                })
            i += 1
            continue

        # 匹配无音标词组: 词组(2+词) 中文 页码
        m = re.match(
            r'^([a-z][\w\s\-]{2,}?)\s+([\u4e00-\u9fff][\u4e00-\u9fff\w\s，、；：（）()·]+?)\s+(\d{1,3})$',
            line
        )
        if m:
            word = m.group(1).strip()
            cn = m.group(2).strip()
            page = int(m.group(3))
            if word:
                vocab.setdefault(current_unit, []).append({
                    "word": word, "pos": "", "cn": cn, "page": page
                })
            i += 1
            continue

        i += 1

    return vocab


def parse_toc(pdf, toc_page):
    """从目录页提取单元结构"""
    # 分栏提取目录
    left, right = split_dual_column(pdf.pages[toc_page])
    toc_text = left + "\n" + right + "\n"

    # 也可能跨页
    if toc_page + 1 < len(pdf.pages):
        left2, right2 = split_dual_column(pdf.pages[toc_page + 1])
        toc_text += left2 + "\n" + right2 + "\n"

    entries = []
    lines = toc_text.split('\n')
    for line in lines:
        line = line.strip()
        # 匹配: Unit 1 Title topic ... 页码
        m = re.match(r'^(Starter|Unit\s+\d+)\s+(.+?)\s{2,}(.+?)\s+(\d{1,3})$', line)
        if m:
            entries.append({
                "raw": line,
                "unit": m.group(1),
                "title_area": m.group(2),
                "desc_area": m.group(3),
                "page": int(m.group(4))
            })
    return entries


def build_json(pdf_path, output_path, publisher_code, level, grade, semester,
               editor_code, editor_name, standard="2022年版课程标准"):
    """主提取函数"""
    filename = os.path.basename(pdf_path)

    # 检测文字层
    doc_test = pdfplumber.open(pdf_path)
    sample = doc_test.pages[5].extract_text() or ""
    if not sample.strip():
        doc_test.close()
        return {"error": "扫描版PDF，需要OCR", "file": filename}

    total_pages = len(doc_test.pages)

    # 找目录页
    toc_page = find_toc_pages(doc_test)
    print(f"  目录页: P{toc_page + 1 if toc_page >= 0 else '?'}")

    # 找单词表
    vocab_start, vocab_end = find_vocab_pages(doc_test)
    print(f"  单词表: P{vocab_start + 1}~P{vocab_end + 1}" if vocab_start >= 0 else "  单词表: 未找到")

    # 提取单词表
    vocab = {}
    if vocab_start >= 0:
        vocab = parse_vocab(doc_test, vocab_start, vocab_end)

    doc_test.close()

    # 构建输出
    total_words = sum(len(v) for v in vocab.values())
    result = {
        "meta": {
            "publisher": publisher_code,
            "publisher_code": publisher_code,
            "editor": editor_code,
            "editor_name": editor_name,
            "standard": standard,
            "level": level,
            "grade": grade,
            "semester": semester,
            "title": f"{'七' if grade==7 else '八' if grade==8 else '九' if grade==9 else str(grade)}年级{'上' if semester=='up' else '下'}册",
            "pages": total_pages,
            "source_pdf": filename,
            "extracted_at": "2026-05-04"
        },
        "vocabulary": vocab,
        "stats": {
            "total_words": total_words,
            "units": len(vocab)
        }
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  结果: {len(vocab)} 单元, {total_words} 词")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 9:
        print("用法: extract_textbook.py <pdf> <output> <publisher> <level> <grade> <semester> <editor_code> <editor_name>")
        sys.exit(1)

    pdf_path, output_path = sys.argv[1], sys.argv[2]
    publisher, level = sys.argv[3], sys.argv[4]
    grade, semester = int(sys.argv[5]), sys.argv[6]
    editor_code, editor_name = sys.argv[7], sys.argv[8]

    print(f"提取: {os.path.basename(pdf_path)}")
    result = build_json(pdf_path, output_path, publisher, level, grade, semester,
                        editor_code, editor_name)
    if "error" in result:
        print(f"跳过: {result['error']}")
    else:
        print(f"已保存: {output_path}")
