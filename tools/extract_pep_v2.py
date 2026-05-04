#!/usr/bin/env python3
"""人教版(PEP)教材PDF提取 v2 — 支持 Vocabulary in Each Unit 格式"""
import pdfplumber, re, json, sys, os

def extract_pep_v2(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    total_pages = len(pdf.pages)
    
    # 策略: 找按单元排列的单词表
    # PEP 标题可能是 "Vocabulary in Each Unit" 或 PDF渲染畸变如 "VoVcoacbaublaurlayr..."
    # 可靠特征: 页面同时包含 "Unit" 标记 + "p.\d+" 页码 + 音标斜杠，且在后半部分
    vocab_start = -1
    for i in range(total_pages // 2, total_pages):
        text = pdf.pages[i].extract_text() or ""
        # 核心特征：有 Unit 标记 + 词条格式 p.N + 音标
        has_unit = bool(re.search(r'(?:Starter\s+)?Unit\s+\d+', text))
        has_page_ref = bool(re.search(r'p\.\s*\d{1,3}', text))
        has_phonetic = '/' in text and re.search(r'/[^/]*/', text)
        # 排除正文页（正文也有 Unit 但不会有大量 p.N 格式）
        page_ref_count = len(re.findall(r'p\.\s*\d{1,3}', text))
        
        if has_unit and has_page_ref and has_phonetic and page_ref_count >= 3:
            vocab_start = i
            break
    
    if vocab_start < 0:
        pdf.close()
        return {"error": "未找到单词表"}
    
    # 确定结束页：找到 Vocabulary A-Z 或非词汇内容的页面
    # 特征：Vocabulary A-Z 页面的词条没有 Unit 标记（或标题含 A-Z）
    vocab_end = vocab_start
    for i in range(vocab_start, min(vocab_start + 20, total_pages)):
        page = pdf.pages[i]
        x0, y0, x1, y1 = page.bbox
        mid = (x0 + x1) / 2
        left = page.crop((x0, y0, mid, y1))
        right = page.crop((mid, y0, x1, y1))
        full = (left.extract_text() or "") + "\n" + (right.extract_text() or "")
        
        # 遇到 A-Z 字母序表就停
        if 'A-Z' in full or 'A–Z' in full:
            break
        if 'Vocabulary from Primary' in full or 'V ocabulary from' in full:
            break
        if re.search(r'[Aa]ppendix|Irregular|Pronunciation|后记', full):
            break
        
        # 仍然是词汇页
        if re.search(r'p\.\s*\d{1,3}', full) or re.search(r'Unit\s+\d+', full):
            vocab_end = i
        elif i > vocab_start:
            break
    
    # 分栏提取全部文本
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
    
    pdf.close()
    
    # 解析
    vocab = {}
    current_unit = "unknown"
    lines = all_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 跳过标题/注释
        if any(kw in line for kw in ["Vocabulary in Each", "Vocabular", "Words and expressions", "注：", "注:", "重点词汇"]):
            continue
        if line.startswith("（注"):
            continue
        
        # Starter Unit 标记
        m = re.match(r'^Starter\s+Unit\s+(\d+)', line)
        if m:
            current_unit = f"starter-{int(m.group(1))}"
            vocab.setdefault(current_unit, [])
            continue
        
        # Unit 标记
        m = re.match(r'^Unit\s+(\d+)\s*$', line)
        if m:
            current_unit = f"unit-{int(m.group(1))}"
            vocab.setdefault(current_unit, [])
            continue
        
        # Unit标记带词条（同行）: "Unit 1 word /phon/ pos 中文 p.N"
        m = re.match(r'^Unit\s+(\d+)\s+([\w].*)', line)
        if m:
            current_unit = f"unit-{int(m.group(1))}"
            vocab.setdefault(current_unit, [])
            line = m.group(2).strip()
            # 继续解析这一行
        
        # 词条: word /phonetic/ pos 中文 p.页码
        m = re.match(
            r'^([\w][\w\s\-\'/]*?)\s*/[^/]*/\s*'
            r'((?:(?:n|v|adj|adv|prep|pron|det|conj|interj|int|num|abbr|modal\s*v|vt|vi)\.\s*(?:&\s*(?:conj|prep)\.\s*)?)*)'
            r'(.+?)\s+p\.\s*(\d{1,3})\s*$',
            line
        )
        if m:
            word = m.group(1).strip()
            pos = m.group(2).strip()
            cn = m.group(3).strip()
            page = int(m.group(4))
            if word:
                vocab.setdefault(current_unit, []).append({
                    "word": word, "pos": pos, "cn": cn, "page": page
                })
            continue
        
        # 词条: word /phonetic/ pos 中文 (页码) — 陈琳格式
        m = re.match(
            r'^([\w][\w\s\-\'/]*?)\s*/[^/]*/\s*'
            r'((?:(?:n|v|adj|adv|prep|pron|det|conj|interj|int|num|abbr|modal\s*v|vt|vi)\.\s*(?:&\s*(?:conj|prep)\.\s*)?)*)'
            r'(.+?)\s*\((\d{1,3})\)\s*$',
            line
        )
        if m:
            word = m.group(1).strip()
            pos = m.group(2).strip()
            cn = m.group(3).strip()
            page = int(m.group(4))
            if word:
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
    
    return vocab


def build_pep_json(pdf_path, output_path, level, grade, semester):
    filename = os.path.basename(pdf_path)
    vocab = extract_pep_v2(pdf_path)
    
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
            "title": f"{'七' if grade==7 else '八' if grade==8 else '九'}年级{'上' if semester=='up' else '下' if semester=='down' else '全一册'}",
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
    
    for u in sorted(vocab.keys()):
        print(f"  {u}: {len(vocab[u])} 词")
    print(f"  合计: {len(vocab)} 单元, {total_words} 词")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("用法: extract_pep_v2.py <pdf> <output> <level> <grade> <semester>")
        sys.exit(1)
    print(f"提取: {os.path.basename(sys.argv[1])}")
    build_pep_json(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
