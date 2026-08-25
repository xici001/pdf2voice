# -*- coding: utf-8 -*-
"""pdf2voice Web 界面：上传/选 PDF -> 配置参数 -> 转换（实时进度）-> 在线试听/下载。"""
import json
import re
import threading
import time
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_file, render_template_string
import reader  # PDF 文本提取 / 分块 / OCR（reader.py 与本文件同目录）

BASE = reader.base_dir()   # exe 模式下为 exe 所在目录，保证 books/output 落盘在用户看得见的地方
BOOKS_DIR = BASE / "books"
OUT_DIR = BASE / "output"
BOOKS_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# 全局任务状态
TASK = {
    "running": False,
    "cancel": False,     # 请求停止
    "stage": "",         # 当前阶段描述
    "page": 0, "pages": 0,
    "chunk": 0, "chunks": 0,
    "done": False,
    "error": None,
    "output": None,      # 最后完成的文件名（用于试听）
    "book": "",          # 当前正在处理的书
    "books": [],         # 本次任务的书列表
    "idx": 0, "total": 0,
}


def _safe_name(name: str) -> str:
    """把自定义输出名清洗成安全的文件名（保留中文，去路径/危险字符）。"""
    name = Path(name).name
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    name = name.rstrip(". ")
    if not name:
        name = "output"
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    return name


def synth_book(text: str, out: Path, voice: str, rate: str, pitch: str) -> bool:
    """合成单本书到 out。返回 False 表示被取消（已清理半成品）。"""
    import asyncio
    from edge_tts import Communicate

    chunks = reader.chunk_text(text)
    tmp = out.with_suffix(".parts")
    tmp.mkdir(parents=True, exist_ok=True)

    async def _one(chunk, mp3):
        for attempt in range(3):
            try:
                await Communicate(chunk, voice, rate=rate, pitch=pitch).save(str(mp3))
                return
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

    async def _synth():
        for i, c in enumerate(chunks):
            if TASK["cancel"]:
                raise asyncio.CancelledError()
            await _one(c, tmp / f"part_{i:04d}.mp3")
            TASK.update(chunk=i + 1)

    try:
        asyncio.run(_synth())
    except asyncio.CancelledError:
        for p in tmp.glob("part_*.mp3"):
            p.unlink()
        if tmp.exists():
            try:
                tmp.rmdir()
            except OSError:
                pass
        return False

    with open(out, "wb") as f:
        for p in sorted(tmp.glob("part_*.mp3")):
            f.write(p.read_bytes())
    try:  # 清理半成品：尽力而为，失败不阻塞交付
        for p in tmp.glob("part_*.mp3"):
            p.unlink()
        tmp.rmdir()
    except OSError:
        pass
    return True


def run_task(book_list: list[str], voice: str, rate: str, pitch: str,
             pages: str | None, name: str | None):
    try:
        from pathlib import Path as P

        total = len(book_list)
        TASK.update(total=total, idx=0, cancel=False, error=None)
        last_out = None
        single = (total == 1)

        for bi, bname in enumerate(book_list, 1):
            if TASK["cancel"]:
                break
            TASK.update(idx=bi, book=bname, stage="提取文本",
                        page=0, pages=0, chunk=0, chunks=0)
            pdf_path = P(BOOKS_DIR / bname)
            if not pdf_path.exists():
                continue
            doc_pages = reader.extract_text_progress(
                pdf_path, pages,
                cb=lambda i, n: TASK.update(page=i + 1, pages=n),
            )
            if TASK["cancel"]:
                break
            if not doc_pages:
                continue

            text = "\n".join(t for _, t in doc_pages)
            TASK.update(stage="合成语音", chunk=0,
                        chunks=(len(text) + reader.CHUNK_LIMIT - 1) // reader.CHUNK_LIMIT)
            out = OUT_DIR / (_safe_name(name) if single and name else f"{pdf_path.stem}.mp3")
            if synth_book(text, out, voice, rate, pitch):
                last_out = out.name
            if TASK["cancel"]:
                break

        if TASK["cancel"]:
            TASK.update(stage="已取消", done=False, output=last_out, error=None)
        else:
            TASK.update(stage="完成", done=True, output=last_out, error=None)
    except Exception:
        TASK.update(error=traceback.format_exc()[-500:], stage="失败")
    finally:
        TASK["running"] = False


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/books")
def books():
    seen, files = set(), []
    for f in list(BOOKS_DIR.glob("*.pdf")) + list(BOOKS_DIR.glob("*.PDF")):
        k = f.name.lower()
        if k not in seen:
            seen.add(k)
            files.append(f.name)
    return jsonify(sorted(files))


@app.route("/api/outputs")
def outputs():
    items = []
    for f in sorted(OUT_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True):
        items.append({
            "name": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
        })
    return jsonify(items)


@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "没有收到文件"}), 400
    raw = f.filename or "book.pdf"
    if not raw.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "只支持 PDF 文件"}), 400
    # 保留中文名，仅去掉路径分隔等危险字符
    safe = re.sub(r"[\\/:*?\"<>|]", "_", Path(raw).name).strip() or "book.pdf"
    dst = BOOKS_DIR / safe
    if dst.exists():
        return jsonify({"ok": False, "error": f"books 目录已存在 {safe}，请先重命名或删除"}), 409
    f.save(str(dst))
    return jsonify({"ok": True, "name": safe})


@app.route("/api/status")
def status():
    return jsonify(TASK)


@app.route("/api/stop", methods=["POST"])
def stop():
    if not TASK["running"]:
        return jsonify({"ok": False, "error": "当前没有进行中的任务"}), 409
    TASK["cancel"] = True
    return jsonify({"ok": True})


@app.route("/api/start", methods=["POST"])
def start():
    data = request.json or {}
    names = data.get("books") or []
    if isinstance(names, str):
        names = [names]
    names = [n for n in names if (BOOKS_DIR / n).exists()]
    if not names:
        return jsonify({"ok": False, "error": "没有可转换的 PDF"}), 400
    if TASK["running"]:
        return jsonify({"ok": False, "error": "已有任务在进行中"}), 409

    TASK.update(running=True, done=False, error=None, stage="准备中",
                book="", output=None, page=0, pages=0, chunk=0, chunks=0,
                books=names)
    threading.Thread(target=run_task, daemon=True,
                     args=(names, data.get("voice", "zh-CN-XiaoxiaoNeural"),
                           data.get("rate", "+0%"), data.get("pitch", "+0Hz"),
                           data.get("pages") or None,
                           data.get("name") or None)).start()
    return jsonify({"ok": True})


@app.route("/api/audio/<name>")
def audio(name):
    f = (OUT_DIR / name).resolve()
    if f.parent != OUT_DIR.resolve() or not f.exists():
        return "not found", 404
    as_attachment = request.args.get("dl") == "1"
    return send_file(f, mimetype="audio/mpeg",
                     as_attachment=as_attachment,
                     download_name=name if as_attachment else None)


PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📖 pdf2voice</title>
<style>
  :root { --bg:#0f1115; --card:#1a1d24; --fg:#e8eaf0; --mut:#8b93a7;
          --acc:#6c8cff; --ok:#3fbf7f; --err:#ff6c6c; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg);
         font-family:"Microsoft YaHei",sans-serif; padding:32px; max-width:720px; margin:auto; }
  h1 { font-size:26px; margin-bottom:6px; }
  .sub { color:var(--mut); margin-bottom:28px; font-size:14px; }
  .card { background:var(--card); border-radius:14px; padding:22px; margin-bottom:18px; }
  label { display:block; color:var(--mut); font-size:13px; margin:14px 0 6px; }
  select,input[type=text] { width:100%; padding:10px 12px; border-radius:9px;
      border:1px solid #2c3140; background:#12141a; color:var(--fg); font-size:15px; outline:none; }
  select:focus,input:focus { border-color:var(--acc); }
  .row { display:flex; gap:12px; } .row > div { flex:1; }
  button { width:100%; margin-top:20px; padding:13px; border:none; border-radius:10px;
      background:var(--acc); color:#fff; font-size:16px; cursor:pointer; font-weight:bold; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .btn2 { background:#2c3140; }
  #prog { display:none; margin-top:18px; }
  .bar { height:10px; background:#12141a; border-radius:6px; overflow:hidden; }
  .bar > div { height:100%; background:linear-gradient(90deg,var(--acc),#9db4ff); width:0%;
      transition:width .4s; border-radius:6px; }
  #msg { font-size:13px; color:var(--mut); margin-top:8px; }
  #err, #uerr { color:var(--err); white-space:pre-wrap; font-size:12px; margin-top:8px; display:none; }
  #player { display:none; margin-top:16px; width:100%; }
  .done-tag { color:var(--ok); font-weight:bold; }
  .olist { list-style:none; padding:0; margin:0; }
  .olist li { display:flex; align-items:center; gap:10px; padding:11px 12px;
      background:#12141a; border:1px solid #2c3140; border-radius:9px; margin-top:10px; }
  .olist .nm { flex:1; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .olist .sz { color:var(--mut); font-size:12px; }
  .olist a { color:var(--acc); text-decoration:none; font-size:13px; padding:4px 8px;
      border:1px solid #2c3140; border-radius:7px; }
  .olist a:hover { border-color:var(--acc); }
  .empty { color:var(--mut); font-size:13px; }
  .up { display:flex; gap:10px; align-items:center; }
  .up input[type=file] { flex:1; font-size:13px; color:var(--mut); }
  .booklist { max-height:210px; overflow:auto; border:1px solid #2c3140;
      border-radius:9px; padding:6px 10px; background:#12141a; margin-top:6px; }
  .booklist label { display:flex; align-items:center; gap:9px; margin:7px 0;
      color:var(--fg); font-size:14px; cursor:pointer; }
  .booklist input { width:auto; margin:0; }
</style>
</head>
<body>
  <h1>📖 pdf2voice</h1>
  <div class="sub">PDF 电子书 → 语音有声书（OCR 扫描版支持 · 噪音过滤 · Edge TTS）</div>

  <div class="card">
    <label>上传 PDF（也可直接放到 books 目录）</label>
    <div class="up">
      <input type="file" id="file" accept="application/pdf,.pdf">
      <button class="btn2" style="width:auto; margin-top:0; padding:10px 16px;" onclick="upload()">上传</button>
    </div>
    <div id="uerr"></div>

    <label style="margin-top:18px;">选择电子书（可多选，批量转换）</label>
    <div class="up">
      <span class="sz" id="selinfo">未选择</span>
      <a href="#" onclick="selAll(true);return false;" style="margin-left:auto;color:var(--acc);text-decoration:none;font-size:13px;">全选</a>
      <a href="#" onclick="selAll(false);return false;" style="color:var(--acc);text-decoration:none;font-size:13px;">清空</a>
    </div>
    <div id="booklist" class="booklist"></div>

    <div class="row">
      <div>
        <label>音色</label>
        <select id="voice">
          <option value="zh-CN-XiaoxiaoNeural">晓晓 · 女声（推荐）</option>
          <option value="zh-CN-YunxiNeural">云希 · 男声（年轻）</option>
          <option value="zh-CN-YunjianNeural">云健 · 男声（沉稳）</option>
          <option value="zh-CN-XiaoyiNeural">晓伊 · 女声（温柔）</option>
        </select>
      </div>
      <div>
        <label>语速</label>
        <select id="rate">
          <option value="-10%">慢 10%</option>
          <option value="+0%" selected>正常</option>
          <option value="+15%">快 15%</option>
          <option value="+30%">快 30%</option>
        </select>
      </div>
      <div>
        <label>音调</label>
        <select id="pitch">
          <option value="-15%">低</option>
          <option value="+0Hz" selected>正常</option>
          <option value="+15%">高</option>
          <option value="+30%">更高</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div>
        <label>页码范围（留空 = 整本，如 1-20 或 5,30-40）</label>
        <input type="text" id="pages" placeholder="整本书">
      </div>
      <div>
        <label>输出文件名（留空 = 用书名）</label>
        <input type="text" id="name" placeholder="与书名一致">
      </div>
    </div>
    <button id="go" onclick="start()">🎧 开始转换</button>
    <button id="stop" class="btn2" style="display:none;" onclick="stopTask()">⏹ 停止</button>
    <div id="prog">
      <div class="bar"><div id="fill"></div></div>
      <div id="msg"></div>
    </div>
    <div id="err"></div>
    <audio id="player" controls></audio>
  </div>

  <div class="card">
    <label>已生成的有声书</label>
    <ul class="olist" id="outputs"><li class="empty">加载中…</li></ul>
  </div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadBooks(){
  const l = await (await fetch('/api/books')).json();
  $('booklist').innerHTML = l.length
    ? l.map(f=>`<label><input type="checkbox" value="${esc(f)}"> ${esc(f)}</label>`).join('')
    : `<div class="empty">（books 目录为空，请先上传 PDF）</div>`;
  updateSel();
}
function selAll(v){
  document.querySelectorAll('#booklist input[type=checkbox]').forEach(c=>c.checked=v);
  updateSel();
}
function selectedBooks(){
  return [...document.querySelectorAll('#booklist input[type=checkbox]:checked')].map(c=>c.value);
}
function updateSel(){
  const n = selectedBooks().length;
  $('selinfo').textContent = n ? `已选 ${n} 本` : '未选择';
}
async function loadOutputs(){
  const l = await (await fetch('/api/outputs')).json();
  $('outputs').innerHTML = l.length
    ? l.map(o=>`<li><span class="nm">${esc(o.name)}</span><span class="sz">${o.size_mb} MB</span>`
            + `<a href="#" onclick="play('${encodeURIComponent(o.name)}');return false;">试听</a>`
            + `<a href="/api/audio/${encodeURIComponent(o.name)}?dl=1">下载</a></li>`).join('')
    : `<li class="empty">还没有生成的有声书</li>`;
}
function play(name){
  $('player').src = '/api/audio/' + name;   // name 已编码
  $('player').style.display = 'block';
  $('player').play();
}
async function upload(){
  const f = $('file').files[0];
  if (!f) { $('uerr').textContent='请先选择 PDF 文件'; $('uerr').style.display='block'; return; }
  $('uerr').style.display='none';
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/upload', {method:'POST', body:fd});
  const j = await r.json();
  if (!j.ok) { $('uerr').textContent=j.error; $('uerr').style.display='block'; return; }
  $('file').value='';
  await loadBooks();
}
async function poll(){
  const s = await (await fetch('/api/status')).json();
  if (!s.running && !s.done && !s.error) { setTimeout(poll, 1500); return; }
  $('prog').style.display = 'block';
  if (s.running) $('stop').style.display = 'block';
  let pct = 0, msg = '';
  const head = s.total > 1 ? `[${s.idx}/${s.total}] ${s.book} · ` : '';
  if (s.stage === '提取文本') {
    pct = s.pages ? s.page / s.pages * 40 : 5;
    msg = head + `🔍 OCR 识别第 ${s.page}/${s.pages || '?'} 页 …`;
  } else if (s.stage === '合成语音') {
    pct = 40 + s.chunk / s.chunks * 60;
    msg = head + `🎙️ 合成语音 ${s.chunk}/${s.chunks} 段 …`;
  } else if (s.stage === '完成') {
    pct = 100; msg = `<span class="done-tag">✅ 完成！</span>`;
    $('go').disabled = false; $('go').textContent = '🎧 再转一本';
    $('stop').style.display = 'none';
    if (s.output) { $('player').src = '/api/audio/' + encodeURIComponent(s.output); $('player').style.display = 'block'; }
    loadOutputs();
    setTimeout(poll, 4000); return;
  } else if (s.stage === '已取消') {
    pct = 100; msg = `⏹ <span class="done-tag">已取消</span>`;
    $('go').disabled = false; $('go').textContent = '🎧 开始转换';
    $('stop').style.display = 'none';
    loadOutputs();
    setTimeout(poll, 4000); return;
  } else {
    msg = s.stage;
  }
  if (s.error) { $('err').textContent = s.error; $('err').style.display='block';
                 $('go').disabled=false; $('stop').style.display='none'; }
  $('fill').style.width = pct + '%';
  $('msg').innerHTML = msg;
  setTimeout(poll, 1200);
}
poll();
async function start(){
  const bs = selectedBooks();
  if (!bs.length) { $('err').textContent='请先勾选至少一本 PDF'; $('err').style.display='block'; return; }
  $('err').style.display='none'; $('player').style.display='none';
  $('go').disabled = true; $('go').textContent = '转换中…';
  $('stop').style.display = 'block';
  $('prog').style.display='block'; $('fill').style.width='2%';
  $('msg').textContent = '提交任务…';
  await fetch('/api/start', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ books:bs, voice:$('voice').value,
                           rate:$('rate').value, pitch:$('pitch').value,
                           pages:$('pages').value.trim(),
                           name:$('name').value.trim() })});
}
async function stopTask(){
  await fetch('/api/stop', {method:'POST'});
  $('msg').textContent = '正在停止…';
}
loadBooks(); loadOutputs();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("📖 pdf2voice 界面: http://localhost:8765")
    app.run(host="127.0.0.1", port=8765, debug=False)
