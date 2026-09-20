# 图片信息识别与 AI 多智能体自动回复工具

> 一个桌面端工具：**前半程**把散落的图片资料 OCR 成结构化表格，**后半程**把大模型接到业务界面上，让它自己看屏幕、自己判断要不要回、自己组织语言 —— 给 LLM 装上「手和脚」。

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-tkinter-4B8BBE)
![LLM](https://img.shields.io/badge/LLM-Ollama%20%2F%20OpenAI%20%E5%85%BC%E5%AE%B9-000000)
![OCR](https://img.shields.io/badge/OCR-EasyOCR-FF6F00)

---

## 目录

- [一、项目简介](#一项目简介)
- [二、功能特性](#二功能特性)
- [三、技术栈](#三技术栈)
- [四、目录结构](#四目录结构)
- [五、核心设计](#五核心设计)
- [六、快速开始](#六快速开始)
- [七、配置说明](#七配置说明)
- [八、已知限制](#八已知限制)

---

## 一、项目简介

工具由两条业务线组成，共用同一套感知层与 LLM 基础设施：

| 模块 | 解决的问题 | 关键能力 |
| --- | --- | --- |
| **图片信息识别与整理** | 大量身份证 / 发票 / 名片 / 合同照片依赖人工录入 | OCR 识别 → 正则结构化抽取 → 文档类型自动分类 → 导出 Excel / CSV |
| **AI 多智能体自动回复** | 招聘沟通场景需要第一时间响应，人工值守成本高 | 截图 → OCR → 界面结构化分析 → Agent 决策 → 生成回复 → 人工审批或自动发送 |

第二块是本项目的主体：它不只是一个「调 API 的脚本」，而是一个具备**感知（看屏幕）、决策（回不回）、记忆（记得聊过什么）、行动（发送）、风控（什么必须转人工）**完整闭环的智能体。

---

## 二、功能特性

### 1. 图片信息识别与分类整理

- **批量导入**：文件选择 / 文件夹递归 / 拖拽添加
- **OCR 文字识别**：EasyOCR 中英文识别，兼容 PyInstaller 打包后的模型加载路径
- **结构化抽取**：日期、金额、手机号、固定电话、身份证号、邮箱、网址（正则表集中在 `config.py`）
- **文档类型分类**：身份证 / 发票 / 名片 / 收据 / 合同（关键词表驱动）
- **图片属性**：EXIF 元数据与基本视觉特征提取
- **结果导出**：Excel（`.xlsx`）/ CSV

### 2. AI 多智能体自动回复

- **多智能体**：`AgentManager` 按岗位加载多个 `AgentEngine` 实例，一个岗位一套人格、策略与记忆，互不串味
- **感知层（给模型「眼睛」）**：`BrowserController` 浏览器自动化（登录 / 截图 / DOM 抓取 / 发送消息）+ `UIAnalyzer` 把聊天界面截图解析成结构化会话
- **决策闭环**：`AgentEngine.process_ui_result` → 判断是否需要回复 → `ReplyGenerator` 构建 prompt → LLM 生成 → `MemoryStore` 落记忆 → 人工审批或自动发送
- **会话记忆**：按候选人独立存储，支持上下文窗口、历史摘要、跟进检测、归档
- **策略配置化**：岗位信息与回复策略全部外置为 JSON（`data/positions`、`data/strategies`），带字段校验与岗位克隆
- **人工审批闸门**：薪资谈判 / 面试时间 / offer / 入职时间等敏感话题强制转人工
- **安全护栏**：`blocked_phrases` 拦截私下联系与索要账号类话术，`auto_reject_keywords` 自动识别无意向对话
- **发送节流**：冷却时间、单候选人每日上限、夜间模式
- **守护进程**：`DaemonService` 周期巡检（默认 300s），支持启停 / 暂停 / 恢复与活动日志
- **跟进机制**：超时未回复按策略自动跟进，可配置次数与间隔

### 3. 图形界面

- tkinter 三栏布局：左（图片列表）/ 中（预览）/ 右（识别与提取结果）
- 独立的「AI 助手」与「守护进程监控」Tab
- 独立的 Agent 配置窗口（岗位 / 策略 / 模型 / 节流参数）

---

## 三、技术栈

| 层 | 选型 |
| --- | --- |
| 语言 | Python 3.8+ |
| LLM | Ollama 本地模型（默认 `qwen2.5:3b`）；`LLMClient` 用 httpx 直连 `/api/generate`、`/api/chat`、`/api/pull` |
| OCR | EasyOCR + PyTorch |
| 图像处理 | Pillow / OpenCV |
| 浏览器自动化 | Selenium + undetected-chromedriver |
| 界面 | tkinter |
| 导出 | openpyxl |
| 并发 | threading（守护进程与 OCR 后台线程） |

---

## 四、目录结构

```
.
├── main.py                     # 程序入口
├── config.py                   # 全局配置：OCR 参数、抽取正则表、文档分类关键词
├── requirements.txt
├── automation/
│   └── browser_controller.py   # 浏览器自动化：登录 / 截图 / DOM 抓取 / 发送消息
├── core/
│   ├── agent_engine.py         # 智能体引擎：决策 → 生成 → 记忆 → 审批/发送（含 AgentManager）
│   ├── daemon_service.py       # 后台监控守护进程：截图 → OCR → 分析 → 回复
│   ├── llm_client.py           # Ollama / OpenAI 兼容客户端封装
│   ├── memory_store.py         # 按候选人隔离的会话记忆（上下文 / 摘要 / 跟进 / 归档）
│   ├── strategy_loader.py      # 岗位与策略 JSON 的加载、校验、克隆
│   ├── reply_generator.py      # prompt 构建、回复生成、安全检查与内容清洗
│   ├── ui_analyzer.py          # 招聘聊天界面截图的结构化提取
│   ├── ocr_engine.py           # EasyOCR 封装
│   ├── image_analyzer.py       # EXIF 与图片属性
│   └── extractor.py            # 从 OCR 文本抽取结构化字段并分类
├── gui/
│   ├── main_window.py          # 主界面
│   └── agent_config_window.py  # Agent 配置窗口
├── data/
│   ├── positions/              # 岗位配置（含公司信息、JD、自动回复与监控参数）
│   └── strategies/             # 回复策略（system prompt 模板、温度、跟进、审批清单、黑名单）
├── utils/
│   └── exporter.py             # Excel / CSV 导出
└── dist_new/                   # PyInstaller 打包产物
```

---

## 五、核心设计

### 1. 手写 Agent 循环，不依赖框架

`core/agent_engine.py` 里没有引入 LangChain 之类的编排框架，而是用 httpx 直接调模型、手写状态机。这样做的好处是四个关注点彼此隔离、可以分别调优：

| 关注点 | 落点 | 出问题时的改法 |
| --- | --- | --- |
| 说什么 | `data/strategies/*.json` 的 `system_prompt_template` | 改 prompt 模板，不碰代码 |
| 记得什么 | `core/memory_store.py` | 调上下文窗口 / 摘要策略 |
| 什么时候能发 | `auto_reply` 节流参数 | 调冷却时间、每日上限、夜间窗口 |
| 什么不能发 | `require_human_approval` / `blocked_phrases` | 加一条规则即可 |

### 2. 提示词工程：模板外置 + 变量注入

system prompt 不硬编码在代码里，而是存在策略 JSON 中，由岗位配置注入变量：

```
你是{company_name}的招聘负责人，正在{platform}上与对{position_name}岗位感兴趣的求职者沟通。
...
6. 每次回复控制在 2-4 句话，简洁有力
9. 基于已知信息回答，不确定的就说需要和部门确认
10. 不要做出无法兑现的承诺
```

同一套代码，换一个岗位 JSON 就是一套全新的沟通策略 —— 这是「配置驱动」而非「改代码」的调优路径。

### 3. 记忆与配置分离

运行时状态（待审批队列、回复记录）与岗位/策略配置分开存放，`save_approval_queue` / `load_approval_queue` 支持中途重启后恢复未处理队列，不丢待办。

### 4. 对话安全闸门

自动回复最容易出事的地方是「说错话」和「说太多」。本项目用三层约束收敛：

1. **关键词黑名单**：命中即拦截（不私下联系、不索要账号信息）
2. **敏感话题转人工**：薪资谈判、面试时间、offer、入职时间一律不自动回
3. **频率限制**：冷却时间 + 每日上限 + 夜间模式，避免短时间内刷屏

---

## 六、快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
```

### 2. 启动本地模型（可选）

默认使用 Ollama 本地模型，无需联网与 API Key：

```bash
ollama serve
ollama pull qwen2.5:3b
```

### 3. 运行

```bash
python main.py
```

### 4. 打包（可选）

```bash
pyinstaller -F -w main.py
```

---

## 七、配置说明

### 岗位配置 `data/positions/*.json`

```json
{
  "position_id": "front_desk",
  "position_name": "前台接待",
  "company_name": "星辰科技有限公司",
  "salary_range": "5000-8000元/月",
  "strategy_id": "default",
  "llm_model": "qwen2.5:3b",
  "auto_reply": {
    "enabled": true,
    "night_mode_only": true,
    "night_start_hour": 22,
    "night_end_hour": 8,
    "max_replies_per_candidate_per_day": 5,
    "cooldown_minutes": 5
  },
  "monitoring": { "enabled": true, "check_interval_seconds": 300 }
}
```

### 策略配置 `data/strategies/*.json`

提供 `default`（标准招聘回复）/ `aggressive`（主动跟进）/ `conservative`（保守）三套预设，字段包含：

| 字段 | 作用 |
| --- | --- |
| `system_prompt_template` | 角色设定与回复规则，支持岗位变量注入 |
| `temperature` / `max_tokens` | 生成参数 |
| `follow_up` | 跟进开关、次数、间隔与话术模板 |
| `require_human_approval` | 必须人工审批的话题清单 |
| `auto_reject_keywords` / `blocked_phrases` | 自动拒绝词与拦截短语 |

---

## 八、已知限制

- **记忆层是 JSON 文件**，不是数据库；候选人规模上去后需要替换为数据库存储
- **未接入向量库**，检索能力停留在结构化匹配，尚不构成 RAG —— 若要做企业级知识库，下一步是引入 embedding + 向量检索
- **OCR 与 LLM 串行**，批量导入大文件夹时吞吐受限，可改为流水线并发
- **Windows 优先**：含 `.bat` 脚本与 PyInstaller 打包产物，其他平台需自行调整
- 涉及浏览器自动化的能力，请在遵守目标平台服务条款的前提下使用

---

## License

MIT
