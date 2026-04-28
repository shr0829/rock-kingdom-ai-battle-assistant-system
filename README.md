# AI 洛克

AI 洛克是一个面向 **洛克王国 PVP** 的 Windows 本地桌面辅助工具。它把当前战斗截图发送给兼容 OpenAI 接口的多模态模型，再结合本地 SQLite 知识库，为当前回合生成可执行的操作建议。

> 当前版本：`0.1.0`
> 运行平台：Windows 10 / 11
> 技术栈：Python 3.13、uv、PySide6 / Qt、SQLite、多模态模型 API

## 为什么做这个项目

洛克王国 PVP 的临场决策通常依赖宠物、技能、血量、状态、速度关系和攻略资料。手动查询资料会打断对战节奏，而纯截图识别又容易缺少上下文。AI 洛克把这两件事合在一个本地桌面工具里：

- 用截图直接提取当前战局信息，不依赖本地 OCR。
- 用本地知识库检索宠物、技能和自定义攻略资料。
- 把“截图识别结果 + 命中的资料”一起交给模型生成回合建议。
- 只给辅助判断，不自动点击、不自动代打、不接管游戏操作。

## 功能概览

- **截图分析**：截取主屏幕并发送给多模态模型，识别我方宠物、对方宠物、血量、可见技能、状态效果、场地信息和不确定点。
- **回合建议**：基于战局字段和本地资料命中结果，输出推荐操作、理由、资料依据、置信度和注意事项。
- **本地知识库**：使用 SQLite 保存资料，支持关键词检索和资料命中数配置。
- **资料导入**：支持导入 `.txt`、`.md` 文本资料，以及 `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` 图片资料。
- **公开图鉴数据**：仓库内置可公开分发的洛克王国 Wiki 宠物、技能结构化数据和知识库快照。
- **全局热键**：默认 `Ctrl+Shift+A`，可在界面中修改。
- **发布脚本**：提供 Windows PowerShell 打包脚本和 GitHub Release 自动发布 workflow。

## 项目状态

已实现：

- Windows 桌面悬浮窗口
- 主屏幕截图
- 全局热键触发截图分析
- OpenAI 风格 Responses / Chat Completions 兼容请求
- 多种图片输入 payload 兼容策略
- 本地配置读取和界面保存
- 本地资料导入、SQLite 入库和关键词检索
- BiliGame Wiki 宠物 / 技能数据抓取与结构化导出
- 基于 `CHANGELOG.md` 的 GitHub Release 自动说明生成

暂未实现：

- 自动代打、自动点击或自动操作游戏
- 持续监控整场战斗
- 视频流连续识别
- PDF / Word 资料导入
- 向量语义检索
- macOS / Linux 热键和截图适配

## 快速开始

### 1. 克隆仓库

```bash
git clone git@github.com:shr0829/rock-kingdom-ai-battle-assistant-system.git
cd rock-kingdom-ai-battle-assistant-system
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 准备本地配置

```powershell
Copy-Item config.example.toml config.toml
```

`config.toml` 已被 `.gitignore` 忽略，用来保存本机模型网关配置。请至少检查这些字段：

```toml
model_provider = "OpenAI"
model = "gpt-5.5"
review_model = "gpt-5.5"
model_reasoning_effort = "xhigh"
disable_response_storage = true
network_access = "enabled"

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://api.asxs.top/v1"
wire_api = "responses"
requires_openai_auth = true
```

### 4. 启动应用

```bash
uv run ailock
```

启动后，在界面中填入或确认：

- API Key
- Model
- Base URL
- 全局热键
- 本地资料命中数

界面保存的用户设置会写入 `data/settings.json`，该文件不会提交到 Git。

## 使用流程

1. 启动应用并完成模型配置。
2. 准备一局洛克王国 PVP 对战画面。
3. 点击“截图并分析”，或按默认热键 `Ctrl+Shift+A`。
4. 应用截取当前主屏幕并请求多模态模型识别战局。
5. 应用根据识别字段构造检索词，在 `data/knowledge.db` 中查找相关资料。
6. 模型结合战局和资料命中结果生成回合建议。
7. 应用把本次“截图 → 战局识别 → 本地检索 → 建议生成 → 最终结果”的每一步耗时写入 `data/logs/analysis-*.jsonl`，界面会显示对应日志路径。
8. 在界面中查看三类结果：
   - 战局识别
   - 推荐操作
   - 资料依据

建议截图时尽量包含完整战斗区域、我方状态、可见技能和关键场地信息。若截图信息不足，应用会优先给出保守建议，并提示需要补充确认的内容。

## 导入本地攻略资料

点击界面中的“导入资料文件夹”，选择一个本地目录。程序会递归读取支持格式并写入 SQLite 知识库。

支持格式：

- 文本：`.txt`、`.md`
- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`

导入规则：

- 文本资料会截取前约 1200 个字符作为摘要，并从标题和正文中提取关键词。
- 图片资料会调用已配置的多模态模型，生成标题、摘要、关键词和要点。
- 同一路径的资料再次导入会更新原有记录。

## 刷新公开图鉴数据

仓库包含一个 Wiki 抓取脚本，用于刷新宠物、技能和知识库快照：

```bash
uv run python scripts/fetch_rocom_wiki.py
```

默认会更新：

```text
data/rocom_wiki/pets.json
data/rocom_wiki/pets.csv
data/rocom_wiki/skills.json
data/rocom_wiki/skills.csv
data/rocom_wiki/manifest.json
data/knowledge.db
```

调试时可以只抓少量详情页：

```bash
uv run python scripts/fetch_rocom_wiki.py --detail-limit 3 --skip-db
```

也可以跳过详情页，只保留较快的索引抓取：

```bash
uv run python scripts/fetch_rocom_wiki.py --skip-detail-pages
```

## 项目结构

```text
src/ailock/
  app.py          # 应用入口，组装路径、配置、知识库和 Qt 界面
  ui.py           # PySide6 图形界面、异步任务和结果展示
  hotkey.py       # Windows 全局热键注册
  capture.py      # 主屏幕截图
  knowledge.py    # SQLite 知识库、资料导入和关键词检索
  llm_client.py   # 多模态模型请求、响应解析和降级策略
  advisor.py      # 截图 -> 识别 -> 检索 -> 建议的主流程
  models.py       # 应用设置、战局、资料和建议的数据结构
  config.py       # 项目路径、配置读取和本地设置保存

scripts/
  ailock_entry.py        # PyInstaller 打包入口
  build_release.ps1      # Windows 打包脚本
  fetch_rocom_wiki.py    # BiliGame Wiki 数据抓取脚本
  test_image_answer.py   # 图片问答链路调试脚本

tests/
  test_config.py
  test_fetch_rocom_wiki.py
  test_knowledge.py
  test_llm_client.py

data/
  knowledge.db
  logs/              # 每次截图分析的分步耗时 JSONL 日志
  rocom_wiki/
  rocom_wiki_smoke/
  rocom_wiki_smoke_db/
  debug_pages/
  captures/          # 本地截图，默认不提交
  knowledge/         # 本地私有资料，默认不提交
  settings.json      # 本地界面设置，默认不提交
```

## 公开数据与本地数据

会提交到仓库：

- `data/knowledge.db`
- `data/rocom_wiki/`
- `data/rocom_wiki_smoke/`
- `data/rocom_wiki_smoke_db/`
- `data/debug_pages/`
- `data/*_page_sample.html`

不会提交到仓库：

- `config.toml`
- `data/settings.json`
- `data/captures/`
- `data/knowledge/`
- `data/logs/`
- `.venv/`
- `.omx/`
- `.tmp-tests/`
- 本地 API Key

## 测试

运行全部单元测试：

```bash
uv run python -m unittest discover -s tests -v
```

## 打包发布

Windows 本地打包：

```powershell
.\scripts\build_release.ps1
```

脚本会安装依赖、运行测试、使用 PyInstaller 构建桌面可执行包，并生成 zip 发布目录。

GitHub Release 自动发布：

- 推送 `v*` tag 时触发 `.github/workflows/release.yml`。
- workflow 会从 `CHANGELOG.md` 中提取对应版本说明。
- 如果同名 Release 已存在，则更新说明；否则创建新 Release。

典型发布流程：

```bash
git add .
git commit -m "Prepare release v0.1.1"
git push origin master

git tag -a v0.1.1 -m "release v0.1.1"
git push origin v0.1.1
```

## 配置说明

配置读取优先级：

1. `data/settings.json`：界面保存的用户设置。
2. `config.toml`：项目根目录本地配置。
3. `config.example.toml`：仓库内置示例配置。
4. `~/.codex/auth.json`：如果界面设置中没有 API Key，会尝试读取其中的 `OPENAI_API_KEY`。

常用字段：

| 字段 | 说明 |
| --- | --- |
| `model_provider` | 当前模型提供方名称 |
| `model` | 用于截图识别和建议生成的模型 |
| `review_model` | 预留评审模型字段 |
| `model_reasoning_effort` | Responses API 推理强度，当前仅在兼容值时传递 |
| `disable_response_storage` | 是否向模型 API 请求不存储响应 |
| `network_access` | 网络访问策略记录字段 |
| `model_context_window` | 模型上下文窗口记录字段 |
| `model_auto_compact_token_limit` | 自动压缩阈值记录字段 |
| `model_providers.<name>.base_url` | OpenAI 兼容接口地址 |
| `model_providers.<name>.wire_api` | 请求协议，当前主要使用 `responses` |
| `model_providers.<name>.requires_openai_auth` | 是否要求 Bearer API Key |

## 已知限制

- 当前主要面向 Windows 桌面环境。
- 截图质量、UI 遮挡、模型视觉能力和网关稳定性会影响识别结果。
- 本地检索仍是轻量关键词匹配，不是向量语义检索。
- OpenAI 兼容网关必须支持图片输入；仅支持文本的网关无法完成截图识别。
- 本项目只提供辅助判断，不负责自动执行游戏操作。
- 仓库当前没有提供独立 `LICENSE` 文件；公开使用或再分发前请先补充明确的软件许可。

## 数据来源与许可提醒

仓库内置的洛克王国 Wiki 调试页和结构化数据来自公开网页抓取。上游页面显示文字与数据内容采用 **CC BY-NC-SA 4.0** 协议。使用、修改或再分发这些数据时，请遵守上游数据源的署名、非商业性使用和相同方式共享要求。

代码许可目前尚未在仓库中声明。若要正式公开发布，建议补充 `LICENSE` 文件，并在本节明确区分“代码许可”和“数据许可”。
