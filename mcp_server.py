# -*- coding: utf-8 -*-
"""pdf2voice MCP Server：把「PDF 电子书 → 语音有声书」暴露为 MCP 工具。

让任何 MCP 客户端（WorkBuddy / Claude Desktop / Cursor 等）都能直接调用：
列出书库、转换（异步 + 轮询）、查看已生成的有声书。

工具：
    list_books                  列出 books/ 下的 PDF
    list_audio_outputs          列出已生成的 MP3
    convert_pdf_to_audio_async  异步转换（立即返回 task_id，后台执行）
    get_task_status             轮询任务状态（running / done / error）

运行：
    python mcp_server.py                       # stdio（默认）
    python mcp_server.py --transport streamable-http
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import uuid
from pathlib import Path

from fastmcp import FastMCP

import reader
from reader import base_dir

mcp = FastMCP(
    "pdf2voice-mcp",
    version="0.1.0",
    instructions="把 PDF 电子书转成语音有声书（Edge TTS + 离线 OCR）：列出书库、异步转换、查询任务、查看输出。长任务用异步模式。",
)

BOOKS_DIR = base_dir() / "books"
OUT_DIR = base_dir() / "output"
BOOKS_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# 异步任务表（进程内内存态）
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _convert(book_name: str, out: Path, voice: str, rate: str, pitch: str,
             pages: str | None) -> None:
    """同步执行单本转换（在工作线程中调用）。"""
    pdf = BOOKS_DIR / book_name
    pages_data = reader.extract_text(pdf, pages)
    if not pages_data:
        raise RuntimeError(f"未从 {book_name} 提取到文本（可能是空 PDF）")
    text = "\n".join(t for _, t in pages_data)
    chunks = reader.chunk_text(text)
    tmp = out.with_suffix(".parts")
    asyncio.run(reader.synth(chunks, voice, rate, pitch, out, tmp))


@mcp.tool()
def list_books() -> list[dict]:
    """列出 books/ 目录下的 PDF 电子书（文件名 + 大小）。"""
    return [
        {"name": f.name, "size_mb": round(f.stat().st_size / 1024 / 1024, 1)}
        for f in sorted(BOOKS_DIR.glob("*.pdf"))
    ]


@mcp.tool()
def list_audio_outputs() -> list[dict]:
    """列出已生成的有声书 MP3（文件名 + 大小）。"""
    return [
        {"name": f.name, "size_mb": round(f.stat().st_size / 1024 / 1024, 1)}
        for f in sorted(OUT_DIR.glob("*.mp3"))
    ]


@mcp.tool()
def convert_pdf_to_audio_async(
    book_name: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    pages: str | None = None,
    output_name: str | None = None,
) -> dict:
    """把 books/ 下的 PDF 异步转成语音 MP3，立即返回 task_id，用 get_task_status 轮询。

    book_name 必须是 list_books 中的文件名；pages 形如 "1-10" 或 "5,30-40"（留空=整本）。
    """
    if not (BOOKS_DIR / book_name).exists():
        return {"error": f"书库中不存在: {book_name}（先调 list_books 确认）"}
    out = OUT_DIR / f"{output_name or Path(book_name).stem}.mp3"
    with _tasks_lock:
        task_id = uuid.uuid4().hex[:8]
        _tasks[task_id] = {"task_id": task_id, "status": "running", "result": None}

    def _run() -> None:
        try:
            _convert(book_name, out, voice, rate, pitch, pages)
            with _tasks_lock:
                _tasks[task_id]["status"] = "done"
                _tasks[task_id]["result"] = {
                    "ok": True,
                    "name": out.name,
                    "size_mb": round(out.stat().st_size / 1024 / 1024, 1),
                    "path": str(out),
                }
        except Exception as e:
            with _tasks_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["result"] = {"ok": False, "error": str(e)}

    threading.Thread(target=_run, daemon=True, name=f"pdf2voice-{task_id}").start()
    return {"task_id": task_id, "status": "running", "book": book_name}


@mcp.tool()
def get_task_status(task_id: str) -> dict:
    """查询转换任务状态：running / done / error；done 时返回输出文件信息。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        return {"error": f"未知任务: {task_id}"}
    out: dict = {"task_id": task_id, "status": task["status"]}
    if task["status"] in ("done", "error") and task["result"] is not None:
        out["result"] = task["result"]
    return out


def main() -> None:
    reader.ensure_utf8_console()
    ap = argparse.ArgumentParser(description="pdf2voice MCP Server")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = ap.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
