# AI洛克

AI洛克是一个面向 **洛克王国 PVP** 的本地桌面辅助工具：

- 按热键截图当前战斗画面
- **不走 OCR**，而是直接把截图发送给多模态大模型 API
- 结合本地资料库（图片资料 + 文本资料）
- 输出当前回合的 **推荐操作 + 原因**

## 当前实现

- 桌面端：Qt / PySide6 悬浮窗口
- 截图：Windows 内置 .NET 截屏 helper
- 模型调用：默认按 OpenAI Responses 风格接口请求 `/responses`
- 资料导入：
  - 文本资料（`.txt` / `.md`）直接入库
  - 图片资料（`.png` / `.jpg` / `.jpeg` / `.webp` / `.bmp`）直接发给多模态模型做摘要入库
- 存储：SQLite

## 快速开始

### 1. 安装依赖

```powershell
$env:UV_CACHE_DIR='E:\codex\backage\cache'
uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 启动应用

```powershell
uv run ailock
```

### 3. 在界面中填写

- API Key
- Model / Base URL 默认从项目根目录 `config.toml` 读取
- 热键（默认 `Ctrl+Shift+A`）：点击“修改热键”，直接按下想用的组合键，再确认保存。

当前项目配置：

```toml
model_provider = "OpenAI"
model = "gpt-5.5"
review_model = "gpt-5.5"
model_reasoning_effort = "xhigh"
disable_response_storage = true

[model_providers.OpenAI]
base_url = "https://api.asxs.top/v1"
wire_api = "responses"
requires_openai_auth = true
```

### 4. 导入资料

点击“导入资料文件夹”，选择你保存攻略截图/复制文本的文件夹。

### 5. 使用

- 按热键或点击“截图并分析”
- 应用会：
  1. 截图
  2. 将截图发送给大模型识别当前战局
  3. 从本地资料库检索相关内容
  4. 再次调用模型给出推荐操作

## 目录结构

```text
src/ailock/
  app.py
  ui.py
  hotkey.py
  capture.py
  knowledge.py
  llm_client.py
  advisor.py
  models.py
  config.py
```

## 已知边界

- 当前默认兼容 **OpenAI Responses 风格** 多模态接口
- 暂未实现自动操作、代打、持续监控
- 暂未实现 PDF / Word 资料导入
- 当前检索为轻量关键词匹配，适合 v1 验证
