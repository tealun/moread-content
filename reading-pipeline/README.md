# Moread Reading Pipeline

自动抓取英文阅读素材 → 研判 CEFR 等级/主题/年级 → 入库为结构化 JSON。

## 功能

- **多源抓取**：BBC Learning English、VOA Learning English、News in Levels
- **AI 研判**：支持 LLM 深度分析（OpenAI 兼容接口），纯规则分析作为 fallback
- **结构化入库**：每篇文章输出包含 CEFR 等级、主题、关键词汇、语法点等
- **去重机制**：基于 URL hash，避免重复抓取
- **定时执行**：支持单次运行和守护进程模式

## 安装

```bash
cd reading-pipeline
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`，可配置：
- 启用/禁用数据源
- 每个源的最大抓取数量
- LLM 接口（可选）
- 规则分析参数
- 存储路径
- 轮询间隔

也可通过环境变量配置 LLM：
```bash
export READING_LLM_BASE_URL="https://api.example.com/v1"
export READING_LLM_KEY="sk-xxx"
```

## 运行

### 单次执行
```bash
python pipeline.py --once
```

### 守护进程模式（持续轮询）
```bash
python pipeline.py --daemon
```

### 指定配置文件
```bash
python pipeline.py --once --config /path/to/config.yaml
```

### Cron 定时任务
```bash
# 每6小时执行一次（编辑 crontab -e）
0 */6 * * * cd ~/projects/moread-content/reading-pipeline && /usr/bin/python3 pipeline.py --once >> /var/log/moread-pipeline.log 2>&1
```

## 项目结构

```
reading-pipeline/
├── README.md              # 本文件
├── requirements.txt       # Python 依赖
├── config.yaml            # 配置文件
├── pipeline.py            # 主程序入口
├── sources/               # 数据源抓取器
│   ├── __init__.py
│   ├── base.py            # 基类 SourceBase
│   ├── bbc.py             # BBC Learning English
│   ├── voa.py             # VOA Learning English
│   └── newsinlevels.py    # News in Levels
├── analyzer.py            # AI 研判模块
├── storage.py             # 入库模块
└── output/                # 输出目录
    ├── articles/          # 按日期+主题组织的 JSON 文件
    └── index.json         # 索引文件
```

## 文章 JSON 格式

每篇文章包含以下字段：

| 字段 | 说明 |
|------|------|
| `id` | URL hash 生成的唯一 ID |
| `title` | 英文标题 |
| `title_zh` | 中文标题翻译 |
| `source` | 来源标识 |
| `source_url` | 原始 URL |
| `cefr_level` | CEFR 等级 (A1-C2) |
| `difficulty_score` | 难度分数 (0-100) |
| `grade_level` | 适合年级 |
| `topics` | 主题（中文） |
| `key_vocabulary` | 关键词汇 |
| `grammar_points` | 语法点 |
| `summary_zh` | 中文摘要 |

## License

MIT
