# AI洛克

AI洛克是一个面向 **洛克王国 PVP** 的本地桌面辅助工具。  
它通过 **截图 + 多模态模型识图 + 本地知识库检索** 的方式，为当前回合生成可执行的操作建议。

> 当前版本：`0.1.0`  
> 运行平台：**Windows**  
> 界面框架：**PySide6 / Qt**

---

## 这个项目能做什么

### 1. 直接截图识别战局

- 支持一键截取当前主屏幕
- 不走本地 OCR
- 直接把截图发送给兼容的多模态模型接口
- 从截图中提取当前对战信息

当前版本重点提取这些内容：

- 我方精灵
- 对方精灵
- 我方血量状态
- 当前可见技能
- 状态效果
- 节奏/场地信息
- 检索关键词
- 不确定点与置信度

### 2. 基于本地知识库给出回合建议

识别完截图后，程序会：

1. 根据战局生成检索词
2. 在本地 SQLite 知识库中搜索相关资料
3. 将战局信息和命中的知识一起交给模型
4. 输出当前回合建议

建议结果包含：

- 推荐操作
- 原因说明
- 资料依据
- 置信度
- 注意事项

### 3. 导入本地攻略资料

可以把你自己的资料导入知识库中：

- 文本资料：`.txt`、`.md`
- 图片资料：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`

导入行为：

- 文本会直接截取内容摘要并入库
- 图片会交给模型总结后入库

### 4. 内置公开图鉴数据

仓库当前已经包含可公开分发的洛克王国图鉴数据，例如：

- 精灵图鉴结构化数据
- 技能图鉴结构化数据
- SQLite 知识库快照
- 调试页与样例页

这些数据可直接作为初始检索库使用。

### 5. 支持全局热键

- 默认热键：`Ctrl+Shift+A`
- 支持在界面里修改
- 适合边对战边调用

### 6. 失败时优先安全降级

如果截图信息不足、模型响应不稳定或接口兼容性漂移，程序会尽量：

- 保留已识别到的信息
- 明确提示哪些内容不确定
- 给出“先补截图再决策”的保守建议

---

## 当前版本的功能边界

### 已实现

- Windows 桌面悬浮窗口
- 主屏幕截图
- 全局热键触发截图分析
- 模型配置读取与本地保存
- 本地知识库导入与检索
- 基于截图 + 知识库的回合建议生成
- Wiki 图鉴抓取与结构化导出
- GitHub Release 自动化发布

### 暂未实现

- 自动代打 / 自动点击 / 自动操作游戏
- 持续监控整场战斗
- 视频流连续识别
- PDF / Word 资料导入
- 高级语义向量检索
- 跨平台截图与热键支持（当前以 Windows 为主）

---

## 项目工作流

程序的核心流程如下：

1. 用户按热键或点击“截图并分析”
2. 程序截取当前主屏幕并保存截图
3. 把截图发给多模态模型识别战局
4. 根据战局字段构造检索词
5. 在本地 SQLite 知识库中搜索命中资料
6. 将战局 + 资料命中交给模型生成建议
7. 在界面中显示：
   - 战局识别结果
   - 推荐操作
   - 资料依据

---

## 环境要求

建议环境：

- Windows 10 / 11
- Python `>= 3.13`
- [uv](https://docs.astral.sh/uv/)（推荐）
- 可用的多模态模型 API

---

## 安装与启动

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd rock-kingdom-ai-battle-assistant-system
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 准备配置文件

仓库提交的是示例配置文件 `config.example.toml`。  
首次运行前请复制为本地配置文件：

#### PowerShell

```powershell
Copy-Item config.example.toml config.toml
```

#### Bash

```bash
cp config.example.toml config.toml
```

### 4. 修改配置

请按你自己的模型环境调整 `config.toml`，主要字段包括：

- `model_provider`
- `model`
- `review_model`
- `model_reasoning_effort`
- `disable_response_storage`
- `network_access`
- `model_context_window`
- `model_auto_compact_token_limit`
- `model_providers.<ProviderName>.base_url`
- `model_providers.<ProviderName>.wire_api`
- `model_providers.<ProviderName>.requires_openai_auth`

> 程序会优先读取 `config.toml`。  
> 如果它不存在，则回退读取 `config.example.toml`。

### 5. 启动应用

```bash
uv run ailock
```

---

## 使用教程

下面是按当前版本整理的推荐使用流程。

### 第一步：启动后先检查模型设置

启动应用后，界面左上区域会显示模型相关表单。  
当前你可以在界面中直接调整：

- API Key
- Model
- Base URL
- 全局热键
- 资料命中数

建议先完成以下动作：

1. 填入 API Key
2. 检查 Model 是否正确
3. 检查 Base URL 是否正确
4. 点击“保存设置”

设置会保存在本地 `data/settings.json` 中。

### 第二步：准备知识库资料

你有两种方式准备知识库。

#### 方式 A：直接使用仓库自带公开数据

当前仓库已经包含公开可分发的数据集，可以直接用来检索。

#### 方式 B：导入你自己的资料

点击界面中的 **“导入资料文件夹”**，选择一个本地文件夹。  
程序会递归读取该目录下支持的资料文件。

支持格式：

- 文本：`.txt`、`.md`
- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`

导入完成后，资料会写入本地知识库。

### 第三步：开始截图分析

你可以通过两种方式触发分析：

- 点击按钮：**截图并分析**
- 使用全局热键：默认 `Ctrl+Shift+A`

触发后程序会自动完成：

1. 截图
2. 战局识别
3. 本地知识检索
4. 回合建议生成

### 第四步：阅读结果

界面会显示三个主要结果区域：

#### 1. 战局识别

这里会显示：

- 当前识别状态
- 战术总结
- 我方信息
- 对方信息
- 节奏/场地信息
- 识别疑点
- 截图存档位置

#### 2. 推荐操作

这里会显示：

- 推荐操作
- 原因
- 置信度
- 注意事项

#### 3. 资料依据

这里会显示本次建议命中的本地资料摘要。  
如果没有命中，会明确提示未命中本地资料。

---

## 如何抓取最新图鉴数据

如果你想刷新仓库中的图鉴数据，可运行：

```bash
uv run python scripts/fetch_rocom_wiki.py
```

它会抓取 BiliGame Wiki 中可见的结构化图鉴信息，并更新：

- `data/rocom_wiki/pets.json`
- `data/rocom_wiki/pets.csv`
- `data/rocom_wiki/skills.json`
- `data/rocom_wiki/skills.csv`
- `data/rocom_wiki/manifest.json`
- `data/knowledge.db`

### 可选参数

#### 只抓取少量详情页用于调试

```bash
uv run python scripts/fetch_rocom_wiki.py --detail-limit 3 --skip-db
```

#### 跳过详情页，只保留较快的索引抓取

```bash
uv run python scripts/fetch_rocom_wiki.py --skip-detail-pages
```

---

## 打包发布

当前仓库提供了 PowerShell 打包脚本：

```powershell
./scripts/build_release.ps1
```

它会完成：

1. 安装依赖
2. 运行测试
3. 使用 PyInstaller 构建桌面可执行包
4. 生成发布目录
5. 打包为 zip

> 说明：打包脚本当前主要面向 Windows 使用场景。

---

## 目录说明

### 核心源码

```text
src/ailock/
  app.py          # 程序入口
  ui.py           # Qt 图形界面
  hotkey.py       # Windows 全局热键
  capture.py      # 主屏幕截图
  knowledge.py    # 本地知识库导入/检索
  llm_client.py   # 多模态模型请求与解析
  advisor.py      # 截图分析总流程编排
  models.py       # 数据结构定义
  config.py       # 配置读取与路径管理
```

### 脚本

```text
scripts/
  ailock_entry.py        # 打包入口
  build_release.ps1      # Windows 打包脚本
  fetch_rocom_wiki.py    # Wiki 图鉴抓取
  test_image_answer.py   # 截图/模型链路调试脚本
```

### 测试

```text
tests/
  test_config.py
  test_fetch_rocom_wiki.py
  test_knowledge.py
  test_llm_client.py
```

### 数据目录

```text
data/
  knowledge.db
  rocom_wiki/
  rocom_wiki_smoke/
  rocom_wiki_smoke_db/
  debug_pages/
  captures/          # 本地截图存档（不提交）
  knowledge/         # 本地私有资料（不提交）
  settings.json      # 本地设置（不提交）
```

---

## 仓库中哪些数据会公开，哪些不会

### 会公开提交

- `data/knowledge.db`
- `data/rocom_wiki/`
- `data/rocom_wiki_smoke/`
- `data/rocom_wiki_smoke_db/`
- `data/debug_pages/`
- `data/*_page_sample.html`

### 不会提交

- `data/settings.json`
- `data/captures/`
- `data/knowledge/`
- `.venv/`
- `.omx/`
- `.tmp-tests/`
- 本地私有 API Key

---

## 版本与发布

本项目使用 **SemVer（语义化版本）**：

- `0.1.0`：首个公开版本
- `0.1.x`：补丁修复
- `0.2.0`：新增功能但仍处于快速迭代期
- `1.0.0`：功能稳定后的正式版本

版本规则：

- `pyproject.toml` 使用不带 `v` 的版本号，例如 `0.1.0`
- Git tag / GitHub Release 使用带 `v` 的标签，例如 `v0.1.0`
- 发布说明维护在 `CHANGELOG.md`

---

## 自动 GitHub Release

仓库内置 GitHub Actions 自动发布流程：

- 当 push 一个 `v*` tag（如 `v0.1.1`）时
- workflow 会读取 `CHANGELOG.md`
- 自动创建或更新同名 GitHub Release

典型发版流程：

```bash
# 1. 更新版本号与 changelog

# 2. 提交代码
git add .
git commit -m "release prep v0.1.1"

# 3. 推送主分支
git push origin master

# 4. 创建并推送 tag
git tag -a v0.1.1 -m "release v0.1.1"
git push origin v0.1.1
```

---

## 已知限制

- 当前以 Windows 桌面环境为主
- 目前默认依赖兼容 OpenAI 风格的多模态接口
- 截图识别质量受截图清晰度、UI遮挡、模型能力影响
- 本地知识检索当前仍是轻量关键词匹配，不是向量语义检索
- 当前不负责自动执行游戏操作，只提供辅助判断

---

## 测试

运行全部单元测试：

```bash
uv run python -m unittest discover -s tests -v
```

---

## 适合谁使用

这个项目更适合以下场景：

- 想做 **洛克王国 PVP 回合辅助**
- 想把自己的攻略资料整理成可检索知识库
- 想验证“截图识别 + 本地知识 + 大模型建议”的工作流
- 想在 Windows 本地桌面环境中快速迭代这类工具

如果你想做的是：

- 全自动代打
- 全流程托管操作
- 长时间后台监控整局对战

那当前版本还不是这个方向。
