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

## 获取洛克王国 Wiki 图鉴资料

从 BiliGame Wiki 抓取精灵图鉴和技能图鉴的事实型索引数据，并写入本地 `data/`：

```powershell
uv run python scripts\fetch_rocom_wiki.py
```

输出：

- `data/rocom_wiki/pets.json`
- `data/rocom_wiki/pets.csv`
- `data/rocom_wiki/skills.json`
- `data/rocom_wiki/skills.csv`
- `data/rocom_wiki/manifest.json`
- 同时写入 `data/knowledge.db`，供 AI洛克检索使用

数据来源采用 BiliGame Wiki 页面中可见的图鉴索引字段；不复制文章正文。

默认会继续进入每个精灵/技能详情页补充结构化字段：

- 技能：属性、类型（物攻/魔攻/状态等）、耗能、威力/伤害、效果、可学习精灵
- 精灵：种族值总分、生命/物攻/魔攻/物防/魔防/速度分项、特性、精灵技能、血脉技能、可学技能石

导出的 `pets.json/csv` 与 `skills.json/csv` 默认只保留结构化内容，不再保存页面链接、图片链接等 URL 字段。

调试时可限制详情页数量：

```powershell
uv run python scripts\fetch_rocom_wiki.py --detail-limit 3 --skip-db
```

如只想保留旧版索引卡片抓取速度：

```powershell
uv run python scripts\fetch_rocom_wiki.py --skip-detail-pages
```

## 快速开始

### 1. 安装依赖

```powershell
uv sync
```

### 2. 准备项目配置

公开仓库中提交的是 `config.example.toml`。首次运行前请先复制一份本地配置：

```powershell
Copy-Item config.example.toml config.toml
```

或在类 Unix shell 中：

```bash
cp config.example.toml config.toml
```

然后根据你自己的环境填写或调整：

- 模型服务商
- API Base URL
- 模型名
- 是否需要 OpenAI 兼容认证
- 其他运行参数

### 3. 启动应用

```powershell
uv run ailock
```

### 4. 在界面中填写

- API Key
- Model / Base URL 默认从项目根目录 `config.toml` 读取；如果缺失，则回退到 `config.example.toml`
- 热键（默认 `Ctrl+Shift+A`）：点击“修改热键”，直接按下想用的组合键，再确认保存。

### 5. 导入资料

点击“导入资料文件夹”，选择你保存攻略截图/复制文本的文件夹。

### 6. 使用

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

## 仓库内公开数据与本地私有数据

当前公开仓库会保留可分发的数据资产，例如：

- `data/rocom_wiki/`
- `data/rocom_wiki_smoke/`
- `data/rocom_wiki_smoke_db/`
- `data/knowledge.db`
- `data/debug_pages/`
- `data/*_page_sample.html`

以下本地运行数据不会提交：

- `data/settings.json`
- `data/captures/`
- `data/knowledge/`
- `.venv/`
- `.omx/`
- `.tmp-tests/`

## 版本与 GitHub Release

本项目采用 **SemVer（语义化版本）** 管理 GitHub Release：

- 首个公开版本通常从 `v0.1.0` 开始
- `v0.1.x`：只修复 bug，不改公开接口预期
- `v0.2.0`：新增功能，但仍处于 0.x 快速迭代阶段
- `v1.0.0`：功能和使用方式基本稳定后再进入正式稳定版

版本维护建议：

- `pyproject.toml` 使用不带 `v` 的版本号，例如 `0.1.0`
- Git tag / GitHub Release 使用带 `v` 的标签，例如 `v0.1.0`
- 发布说明维护在 `CHANGELOG.md`
- 实际当前版本以 `pyproject.toml`、Git tag 和 `CHANGELOG.md` 为准

## 自动 Release

仓库内置 GitHub Actions 自动发布流程：

- 当你 push 一个符合 `v*` 规则的 tag（例如 `v0.1.1`）时
- workflow 会自动读取对应的 `CHANGELOG.md` 小节
- 然后创建或更新同名 GitHub Release

典型发布流程：

1. 更新 `pyproject.toml` 版本号
2. 更新 `CHANGELOG.md`
3. 提交代码
4. 创建 tag，例如：

   ```bash
   git tag -a v0.1.1 -m "release v0.1.1"
   git push origin master
   git push origin v0.1.1
   ```

这样就会自动生成或更新对应的 GitHub Release。

## 已知边界

- 当前默认兼容 **OpenAI Responses 风格** 多模态接口
- 暂未实现自动操作、代打、持续监控
- 暂未实现 PDF / Word 资料导入
- 当前检索为轻量关键词匹配，适合 v1 验证
