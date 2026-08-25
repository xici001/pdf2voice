# pdf2voice

> 数字管道的建筑师 · 第五块积木：把 PDF 电子书自动转成语音有声书
> 前四块：workflow-templates / digital-twin-mcp / factory-twin-viz / workflow-mcp

把 PDF 电子书自动转成语音 MP3，用微软 Edge TTS（免费、中文自然度最高）。

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
