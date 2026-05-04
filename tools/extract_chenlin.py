#!/usr/bin/env python3
"""陈琳版教材PDF提取 — 按Module分栏提取单词表"""
import pdfplumber, re, json, sys, os

def extract_chenlin(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    total_pages = len(pdf.pages)
    
    # 1. 找单词表起始页（包含 "W ords and expressions" 或 "Words and expressions"）
    vocab_start = -1
    for i in range(len(pdf.pages)):
        text = pdf.pages[i].extract_text() or ""
        if "Words and expressions" in text or "W ords and" in text:
            # 排除目录页（目录页P7/P8也有此文本）
            if i > 100:  # 单词表一定在后半部分
                vocab_start = i
                break
    
    if vocab_start < 0:
        pdf.close()
        return {"error": "未找到单词表"}
    
    # 2. 找单词表结束页（下一页不包含 Module 词条特征）
    vocab_end = vocab_start
    for i in range(vocab_start, min(vocab_start + 10, len(pdf.pages))):
        text = pdf.pages[i].extract_text() or ""
        if re.search(r'Module\s+\d+', text) or re.search(r'\(\d{1,3}\)', text):
            vocab_end = i
        else:
            break
    
    # 3. 分栏提取单词表文本
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
    
    # 4. 解析词条
    # 陈琳版格式: word /phonetic/ pos 中文 (页码)
    # 或: phrase 中文 (页码)  (无音标)
    # Module标记作为单元分隔
    
    vocab = {}
    current_module = "module-unknown"
    lines = all_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 跳过标题行和注释行
        if line.startswith("W ords") or line.startswith("Words and"):
            continue
        if line.startswith("注：") or line.startswith("注:"):
            continue
        if re.match(r'^\d{1,3}$', line):  # 纯页码
            continue
        
        # Module标记
        m = re.match(r'^Module\s+(\d+)', line)
        if m:
            current_module = f"module-{int(m.group(1))}"
            if current_module not in vocab:
                vocab[current_module] = []
            continue
        
        # 词条: word /phonetic/ pos 中文 (页码)
        m = re.match(
            r'^(\*?\s*[\w][\w\s\-\' ]*?)\s*/[^/]*/\s*'
            r'((?:n\.|v\.|v\. aux\.|adj\.|adv\.|prep\.|pron\.|det\.|conj\.|interj\.|int\.|num\.|abbr\.)\s*)'
            r'(.+?)\s*\((\d{1,3})\)\s*$',
            line
        )
        if m:
            word = m.group(1).strip().lstrip('* ')
            pos = m.group(2).strip()
            cn = m.group(3).strip()
            page = int(m.group(4))
            vocab.setdefault(current_module, []).append({
                "word": word, "pos": pos, "cn": cn, "page": page
            })
            continue
        
        # 词组/短语 (无音标): phrase 中文 (页码)
        m = re.match(
            r'^([a-z][\w\s\-]{2,}?)\s+([\u4e00-\u9fff][\u4e00-\u9fff\w\s，、；：（）()·]+?)\s*\((\d{1,3})\)\s*$',
            line
        )
        if m:
            word = m.group(1).strip()
            cn = m.group(2).strip()
            page = int(m.group(3))
            vocab.setdefault(current_module, []).append({
                "word": word, "pos": "", "cn": cn, "page": page
            })
            continue
    
    pdf.close()
    return vocab


def build_chenlin_json(pdf_path, output_path, level, grade, semester):
    filename = os.path.basename(pdf_path)
    vocab = extract_chenlin(pdf_path)
    
    if "error" in vocab:
        print(f"  错误: {vocab['error']}")
        return False
    
    total_words = sum(len(v) for v in vocab.values())
    
    result = {
        "meta": {
            "publisher": "外研版（FLTRP）",
            "publisher_code": "fltrp",
            "editor": "chenlin",
            "editor_name": "陈琳",
            "level": level,
            "grade": grade,
            "semester": semester,
            "title": f"{'八' if grade==8 else '九'}年级{'上' if semester=='up' else '下'}册",
            "source_pdf": filename,
            "extracted_at": "2026-05-04"
        },
        "vocabulary": vocab,
        "stats": {
            "total_words": total_words,
            "modules": len(vocab)
        }
    }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"  {len(vocab)} 模块, {total_words} 词 -> {output_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("用法: extract_chenlin.py <pdf> <output> <level> <grade> <semester>")
        sys.exit(1)
    build_chenlin_json(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
