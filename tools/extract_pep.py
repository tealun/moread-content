#!/usr/bin/env python3
"""人教版(PEP)教材PDF提取 — 按Unit分栏提取单词表"""
import pdfplumber, re, json, sys, os

def extract_pep(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    total_pages = len(pdf.pages)
    
    # 找单词表起始页
    vocab_start = -1
    for i in range(total_pages):
        text = pdf.pages[i].extract_text() or ""
        # 人教版标题可能包含 "Vocabulary" 或 "Words and expressions"
        if ("Vocabulary" in text or "Words and expressions" in text) and i > 100:
            vocab_start = i
            break
    
    if vocab_start < 0:
        pdf.close()
        return {"error": "未找到单词表"}
    
    # 确定单词表结束页
    vocab_end = vocab_start
    for i in range(vocab_start, min(vocab_start + 20, total_pages)):
        text = pdf.pages[i].extract_text() or ""
        if text.strip() and not any(kw in text for kw in ["后记", "Irregular", "Pronunciation guide"]):
            vocab_end = i
        else:
            break
    
    # 分栏提取
    all_text = ""
    for i in range(vocab_start, vocab_end + 1):
        page = pdf.pages[i]
        x0, y0, x1, y1 = page.bbox
        mid = (x0 + x1) / 2
        left = page.crop((x0, y0, mid, y1))
        right = page.crop((mid, y0, x1, y1))
        lt = left.extract_text() or ""
        rt = right.extract_text() or ""
        all_text += lt + "\n" + rt + "\n"
    
    # 解析
    vocab = {}
    current_unit = "unknown"
    
    for line in all_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ["Vocabulary", "Words and expressions", "V ocabulary"]):
            continue
        if line.startswith("注") or line.startswith("后记"):
            continue
        
        # Starter Unit 标记
        m = re.match(r'^Starter\s+Unit\s+(\d+)', line)
        if m:
            current_unit = f"starter-{int(m.group(1))}"
            vocab.setdefault(current_unit, [])
            continue
        
        # Unit 标记
        m = re.match(r'^Unit\s+(\d+)', line)
        if m:
            current_unit = f"unit-{int(m.group(1))}"
            vocab.setdefault(current_unit, [])
            continue
        
        # 词条: word /phonetic/ pos 中文 p.页码
        m = re.match(
            r'^([\w][\w\s\-\' /]*?)\s*/[^/]*/\s*'
            r'((?:(?:n|v|adj|adv|prep|pron|det|conj|interj|int|num|abbr|modal\s*v)\.\s*(?:&\s*(?:conj|prep)\.\s*)?)*)'
            r'(.+?)\s+p\.\s*(\d{1,3})\s*$',
            line
        )
        if m:
            word = m.group(1).strip()
            pos = m.group(2).strip()
            cn = m.group(3).strip()
            page = int(m.group(4))
            vocab.setdefault(current_unit, []).append({
                "word": word, "pos": pos, "cn": cn, "page": page
            })
            continue
        
        # 词组: phrase 中文 p.页码
        m = re.match(
            r'^([a-z][\w\s\-]{2,}?)\s+([\u4e00-\u9fff][\u4e00-\u9fff\w\s，、；：（）()·]+?)\s+p\.\s*(\d{1,3})\s*$',
            line
        )
        if m:
            word = m.group(1).strip()
            cn = m.group(2).strip()
            page = int(m.group(3))
            vocab.setdefault(current_unit, []).append({
                "word": word, "pos": "", "cn": cn, "page": page
            })
            continue
    
    pdf.close()
    return vocab


def build_pep_json(pdf_path, output_path, level, grade, semester):
    filename = os.path.basename(pdf_path)
    vocab = extract_pep(pdf_path)
    
    if "error" in vocab:
        print(f"  错误: {vocab['error']}")
        return False
    
    total_words = sum(len(v) for v in vocab.values())
    
    result = {
        "meta": {
            "publisher": "人教版（PEP）",
            "publisher_code": "pep",
            "editor": "pep",
            "editor_name": "人教版",
            "level": level,
            "grade": grade,
            "semester": semester,
            "title": f"{'七' if grade==7 else '八' if grade==8 else '九'}年级{'上' if semester=='up' else '下'}册",
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
    
    print(f"  {len(vocab)} 单元, {total_words} 词 -> {output_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("用法: extract_pep.py <pdf> <output> <level> <grade> <semester>")
        sys.exit(1)
    build_pep_json(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
