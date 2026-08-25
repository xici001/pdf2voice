# pdf2voice

> 数字管道的建筑师 · 第五块积木：把 PDF 电子书自动转成语音有声书
> 前四块：workflow-templates / digital-twin-mcp / factory-twin-viz / workflow-mcp

**PDF 电子书 → 语音 MP3**：免费、中文自然度最高（微软 Edge TTS），扫描版自动 OCR，通勤路上"听"书。

## 为什么用它（对比）

| | **pdf2voice** | pdf-narrator | Calibre TTS 插件 | 浏览器朗读 |
|---|---|---|---|---|
| 中文扫描版 PDF | ✅ 自动 OCR | 需自配 | ❌ | ❌ |
| 中文噪音过滤（页眉/页脚/封面/版权页） | ✅ 内置启发式 | 部分 | ❌ | ❌ |
| 费用 | 免费（Edge TTS） | 免费 | 免费 | 免费 |
| 批量转换 | ✅ Web 勾选多本排队 | ❌ | 单本 | ❌ |
| 分页/换音色/调速 | ✅ 全部支持 | 部分 | 部分 | 有限 |
| 免装运行 | ✅ Windows exe | 需 Python 环境 | 需装 Calibre | 仅浏览器 |

一句话：**给中文 PDF 电子书（尤其扫描版）做免费有声书，这是最顺手的工具。**

## MCP 接入（AI 客户端可直接调用）

本项目同时是一个 MCP Server（`mcp_server.py`），WorkBuddy / Claude Desktop 等客户端可直接把"PDF 转语音"当工具用：

| 工具 | 说明 |
|------|------|
| `list_books` | 列出 books/ 下的 PDF |
| `convert_pdf_to_audio_async` | 异步转换（立即返回 task_id，后台执行） |
| `get_task_status` | 轮询任务状态（running / done / error） |
| `list_audio_outputs` | 列出已生成的有声书 |

> 长任务必须用异步模式：整本书合成可能数分钟，同步调用会触发客户端请求超时。
> WorkBuddy 接入：把 `pdf2voice-mcp` 合并进 `~/.workbuddy/mcp.json` 后在连接器管理页「信任」。

## 使用

```bash
# 整本书 -> output/书名.mp3
.venv/Scripts/python.exe reader.py books/你的书.pdf

# 只读第 1~10 页
.venv/Scripts/python.exe reader.py books/书.pdf --pages 1-10

# 换男声、加快语速
.venv/Scripts/python.exe reader.py books/书.pdf --voice zh-CN-YunxiNeural --rate +15%
```

或者直接把 PDF 拖到 `读书.bat` 上。

### 方式二：Web 界面（推荐）
```bash
.venv/Scripts/python.exe app.py
# 打开 http://localhost:8765
```
界面功能：
- **上传 PDF**：网页里直接选文件上传到 `books/`，或手动放进 `books/`
- **批量转换**：勾选多本 PDF，一次性排队转换
- **自定义参数**：音色、语速、音调、页码范围、输出文件名（留空=用书名）
- **实时进度**：显示「第几本 / 共几本」和当前阶段（OCR 提取 / 语音合成）
- **停止任务**：转换中途可点「停止」，自动清理未完成的半成品
- **已生成列表**：底部列出 `output/` 里的 MP3，可在线试听或下载

## Web 接口
| 路径 | 说明 |
|---|---|
| `POST /api/upload` | 上传 PDF（multipart 字段 `file`） |
| `GET  /api/books` | 列出 `books/` 下的 PDF |
| `GET  /api/outputs` | 列出已生成的 MP3 |
| `POST /api/start` | 开始转换，body: `{books:[...], voice, rate, pitch, pages, name}` |
| `POST /api/stop` | 停止当前任务 |
| `GET  /api/status` | 轮询任务状态 |
| `GET  /api/audio/<name>` | 试听；加 `?dl=1` 下载 |

## 音色备选
| 音色 | 说明 |
|---|---|
| zh-CN-XiaoxiaoNeural | 晓晓女声（默认） |
| zh-CN-YunxiNeural | 云希男声（年轻） |
| zh-CN-YunjianNeural | 云健男声（沉稳） |
| zh-CN-XiaoyiNeural | 晓伊女声（温柔） |

## 直接下载 exe（免装环境）

Windows 用户可到 **Releases** 页下载 `pdf2voice.exe`（已内置 Python 与全部依赖，免安装）：

- 双击 `pdf2voice.exe` → 启动 Web 界面（http://localhost:8765）
- 把 PDF 拖到 `pdf2voice.exe` 上（或命令行 `pdf2voice.exe 书.pdf`）→ 直接命令行转换

> 内置 OCR（扫描版识别）模型，单个 exe 体积较大属正常。需联网调用微软 Edge TTS。
> 自己打包：`pip install pyinstaller && pyinstaller --onefile --collect-data rapidocr_onnxruntime launcher.py`

## 依赖

```bash
pip install -r requirements.txt   # pymupdf + edge-tts + flask + rapidocr_onnxruntime + opencv + numpy
```

注意：edge-tts 需要联网；若系统开着失效的代理，先清掉代理再运行（`读书.bat` 已自动清代理）。
扫描版（图片）PDF 会自动走 OCR 识别。

## 从零安装

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # 或 .venv/Scripts/python -m pip install -r requirements.txt
```
