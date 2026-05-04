# Textbook Content

教材同步库 —— 按教材每单元的**主题和知识点**自创平行文章（不使用教材原文，避免版权问题）。

## JSON Schema

详见 [SPEC.md](./SPEC.md)。

## 目录结构

```
textbook/
├── SPEC.md                              ← JSON Schema 设计规格
├── README.md                            ← 本文件
├── pep/                                 ← 人教版（PEP）
│   ├── junior/                          ← 初中（5册）
│   │   ├── grade7_up.json
│   │   ├── grade7_down.json
│   │   ├── grade8_up.json
│   │   ├── grade8_down.json
│   │   └── grade9.json
│   └── senior/                          ← 高中（3册）
│       ├── required1.json
│       ├── required2.json
│       └── required3.json
├── fltrp/                               ← 外研版（FLTRP）
│   ├── junior/                          ← 初中
│   │   ├── sun/                         ← 孙有中主编（2022课标修订，4册）
│   │   │   ├── grade7_up.json
│   │   │   ├── grade7_down.json
│   │   │   ├── grade8_up.json
│   │   │   └── grade8_down.json
│   │   └── chen/                        ← 陈琳主编（4册）
│   │       ├── grade8_up.json
│   │       ├── grade8_down.json
│   │       ├── grade9_up.json
│   │       └── grade9_down.json
│   └── senior/                          ← 高中
│       └── chen/                        ← 陈琳主编（3册）
│           ├── required1.json
│           ├── required2.json
│           └── required3.json
```

## 教材版本说明

- **pep**: 人民教育出版社（人教版）— 初中 + 高中
- **fltrp/sun**: 外研版·孙有中主编 — 初中七~八年级（2022课标修订版）
- **fltrp/chen**: 外研版·陈琳主编 — 初中八~九年级 + 高中

## 内容状态

- ⬜ 数据提取中 — 从真实教材 PDF 提取（参见 SPEC.md 提取工作流）
- ⬜ 平行文章（parallel_articles）— 待 AI 生成 + 人工审核

## 原始 PDF

教材 PDF 存放在服务器 `~/moread-assets/textbook/`，不入仓库（版权+体积）。
