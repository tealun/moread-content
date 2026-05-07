# moread-content

> 开源英语教学内容资源库，面向中国初高中学习者。
> 提供词典底座、分级词表、考试词库、词频词表、教材同步数据。
> MIT 许可证，可商用。

---

## 两大使命

1. **词库数据管理** — 为背单词功能提供系统内置词库（19 个，73,542 词）
2. **教材同步数据** — 按初高中教学大纲生成同步阅读文章（待建设）

---

## 目录结构

```
moread-content/
├── dictionary/              ← 底座（ECDICT 77万词条，SQLite）
│   ├── ecdict.db            ← SQLite 数据库（完整英汉词典）
│   └── _meta.json           ← 词典元数据
│
├── vocabulary/              ← 词单（轻量，只有单词列表）
│   ├── index.json           ← 词库索引（19 个词库）
│   ├── cefr/                ← CEFR 分级（6 个：A1~C2）
│   ├── exam/                ← 考试考纲（8 个：中考/高考/CET-4/CET-6/考研/雅思/托福/GRE）
│   ├── frequency/           ← 词频词表（5 个：Top 1k~10k，按真实词频排序）
│   └── textbook/            ← 教材词单（待追加）
│
├── textbook/                ← 教材同步数据
│   ├── SPEC.md              ← 教材数据设计文档
│   ├── pep/                 ← 人教版（待提取）
│   └── fltrp/               ← 外研版（待提取）
│
├── api/                     ← API 模块
│   ├── middleware.py        ← IP 白名单 + CORS + 配置加载
│   ├── data.py              ← 数据加载层（索引/词库/词典缓存）
│   ├── vocabulary.py        ← 词库路由（packs/words/stats/health）
│   └── dictionary.py        ← 词典路由（lookup/batch/search）
├── main.py                  ← 启动入口（创建 app + 挂载路由）
├── DATA_API_SPEC.md         ← 数据端完整规格（API 文档 + 消费端集成方式）
├── requirements.txt         ← Python 依赖（fastapi/uvicorn/orjson/python-dotenv）
└── .env.example             ← 配置模板
```

---

## 架构：词单 + 底座分离

**词库文件只存单词列表**，不存音标、不存释义。释义从 `dictionary/`（ECDICT 70万词条底座）按需查。

```json
// vocabulary/exam/gaokao.json — 词库只长这样
{
  "id": "exam-gaokao",
  "name": "高考考纲",
  "category": "exam",
  "difficulty": "A2-B2",
  "words": ["abandon", "ability", "able", ...]
}
```

```
消费端 → GET /api/packs → 词库列表
消费端 → GET /api/packs/{id} → 词单
消费端 → GET /api/dictionary/{word} → 完整释义
```

---

## 19 个词库一览

| 类别 | 词库 | 词数 | 难度 |
|------|------|------|------|
| CEFR | A1 | 600 | A1 |
| CEFR | A2 | 600 | A2 |
| CEFR | B1 | 1,298 | B1 |
| CEFR | B2 | 2,500 | B2 |
| CEFR | C1 | 1,026 | C1 |
| CEFR | C2 | 999 | C2 |
| 考试 | 中考 | 1,600 | A1-A2 |
| 考试 | 高考 | 3,837 | A2-B2 |
| 考试 | CET-4 | 5,183 | B1-B2 |
| 考试 | CET-6 | 5,974 | B2-C1 |
| 考试 | 考研 | 5,648 | B2-C1 |
| 考试 | 雅思 | 3,576 | B1-C1 |
| 考试 | 托福 | 10,365 | B2-C2 |
| 考试 | GRE | 9,468 | C1-C2 |
| 词频 | Top 1000 | 1,000 | — |
| 词频 | Top 2000 | 2,000 | — |
| 词频 | Top 3000 | 3,000 | — |
| 词频 | Top 5000 | 5,000 | — |
| 词频 | Top 10000 | 9,868 | — |

**总计 73,542 词**

---

## 集成方式

### 方式一：API（推荐）

```bash
# 启动 API 服务
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8900
```

消费端通过 HTTP 接口获取所有数据，详见 `DATA_API_SPEC.md` §6。

### 方式二：直接读 JSON

```javascript
import packs from 'moread-content/vocabulary/index.json'
import gaokao from 'moread-content/vocabulary/exam/gaokao.json'
```

### 方式三：导入数据库

`dictionary/` 下已提供 SQL 格式（a.sql ~ z.sql）和建表语句（schema.sql），消费端自行导入。

---

## 数据来源与版权

| 数据 | 来源 | 许可证 |
|------|------|--------|
| 词典底座 | [ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| CEFR 词表 | vocabulary.englishprofile.org | 整理加工 |
| 考试词库 | mahavivo/english-wordlists + KyleBing/english-vocabulary | 双源合并 |
| 词频词表 | Google 10K Corpus | 整理加工 |
| 教材同步 | AI 自创 + 人工审核 | MIT（本仓库） |

---

## 详细设计文档

- `DATA_API_SPEC.md` — 数据端完整规格（架构、词库格式、API 文档、消费端集成方式）
- `textbook/SPEC.md` — 教材同步数据设计（JSON Schema、学段隔离原则）
