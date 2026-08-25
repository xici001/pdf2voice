# -*- coding: utf-8 -*-
"""
自动读书：把 PDF 电子书转成语音（MP3），支持整本转换或按页朗读。

用法:
  python reader.py 书.pdf                 # 整本书转成一个 MP3
  python reader.py 书.pdf -o out.mp3      # 指定输出文件
  python reader.py 书.pdf --pages 1-10    # 只转第 1~10 页
  python reader.py 书.pdf --voice zh-CN-YunxiNeural   # 换男声
  python reader.py 书.pdf --rate +20%     # 加快语速
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

import edge_tts
import fitz  # pymupdf

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"   # 晓晓女声，自然度高
CHUNK_LIMIT = 1800                        # 每段合成文本上限（edge-tts 稳定值）


def base_dir() -> Path:
    """运行基准目录：PyInstaller exe 用 exe 所在目录，源码运行用项目目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

# 常用中文音色备选:
#   zh-CN-XiaoxiaoNeural  女声（默认）
#   zh-CN-YunxiNeural     男声（年轻）
#   zh-CN-YunjianNeural   男声（沉稳）
#   zh-CN-liaoning-XiaobeiNeural  东北口音女声


def extract_text(pdf_path: Path, pages: str | None, cb=None) -> list[tuple[int, str]]:
    """提取 PDF 文本，返回 [(页码, 文本)]。跳过空白页。文字层为空时自动走 OCR。
    cb(当前第几页, 总页数) 用于进度回调。"""
    doc = fitz.open(pdf_path)
    if pages:
        page_ids = set()
        for part in pages.split(","):
            if "-" in part:
                a, b = part.split("-")
                page_ids.update(range(int(a) - 1, int(b)))
            else:
                page_ids.add(int(part) - 1)
        indices = sorted(i for i in page_ids if 0 <= i < len(doc))
    else:
        indices = range(len(doc))

    result = []
    # 先收集各页原始文本，用于统计页眉/页脚等跨页重复噪音（参考 pdf-narrator 的做法）
    raw = {}
    for n, i in enumerate(indices):
        text = doc[i].get_text("text")
        if not text.strip():
            text = ocr_page(doc, i)
        raw[i] = text
        if cb:
            cb(n, len(indices))
    noisy_lines = detect_noisy_lines(raw)

    for i in indices:
        lines = [l.strip() for l in raw[i].splitlines() if l.strip()]
        if looks_like_cover(lines):
            continue                                  # 封面/扉页/版权页整页跳过
        kept = [l for l in lines if l not in noisy_lines and is_content(l)]
        text = clean_text("\n".join(kept))
        if text.strip():
            result.append((i + 1, text))
    doc.close()
    return result


def is_content(line: str) -> bool:
    """单行判断：过滤页码、纯英文装饰行、出版社/丛书信息。"""
    s = line.strip()
    if len(s) <= 5 and re.fullmatch(r"[-–—\s]*\d+[-–—\s]*", s):
        return False                                  # 纯页码 / 罗马数字页脚
    if re.fullmatch(r"[ivxlcIVXLC]{1,6}", s):
        return False
    # 出版社 / 丛书 / 作者签名等固定噪音
    noise_kw = ("出版社", "出版集团", "出版公司", "系列", "雷欧幻", "工作室",
                "定价", "开本", "印张", "版次", "ISBN", "印次")
    if any(k in s for k in noise_kw) and len(s) < 30:
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    if cjk == 0:
        letters = re.findall(r"[A-Za-z]", s)
        if len(s) <= 30 and not re.search(r"\d{2,}", s):
            return False                              # 短英文装饰行
        if re.fullmatch(r"[A-Za-z .!?'’\-]+", s) and len(letters) >= len(s) - 3 and len(s.split()) < 8:
            return False                              # 全英文字母行（封面标语）
    return True


def looks_like_cover(lines: list[str]) -> bool:
    """整页判断：像封面/扉页/版权页则跳过。"""
    text = "".join(lines)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    sentences = re.findall(r"[\u4e00-\u9fff]{6,}[。！？…”]", text)
    cover_kw = ("出版社", "出版集团", "ISBN", "定价", "版权所有", "版次")
    if any(k in text for k in cover_kw) and len(sentences) <= 1:
        return True                                   # 版权页
    if cjk < 40 and len(sentences) == 0:
        return True                                   # 封面/扉页
    return False


def detect_noisy_pages(raw: dict) -> set:
    """启发式找封面/扉页：中文极少且无连续句子的页。"""
    noisy = set()
    for i, t in raw.items():
        cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
        sentences = re.findall(r"[\u4e00-\u9fff]{6,}[。！？…]", t)
        if cjk < 40 and len(sentences) == 0:
            noisy.add(i)
    return noisy


def detect_noisy_lines(raw: dict) -> set:
    """出现在 >=30% 页面同一位置的短行 => 页眉/页脚/丛书名。"""
    from collections import Counter
    tops, bottoms = Counter(), Counter()
    n = 0
    for text in raw.values():
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            continue
        n += 1
        if len(lines[0]) < 25:
            tops[lines[0]] += 1
        if len(lines[-1]) < 25:
            bottoms[lines[-1]] += 1
    noisy = {l for l, c in tops.items() if n >= 5 and c / n >= 0.3}
    noisy |= {l for l, c in bottoms.items() if n >= 5 and c / n >= 0.3}
    return noisy


_OCR = None

def ocr_page(doc, index: int, dpi: int = 200) -> str:
    """对单页截图做 OCR（RapidOCR，离线中文识别）。"""
    global _OCR
    import cv2
    import numpy as np
    if _OCR is None:
        print("🔍 检测到扫描版 PDF，加载离线中文 OCR 模型 ...")
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    pix = doc[index].get_pixmap(dpi=dpi)
    img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8),
                       cv2.IMREAD_COLOR)
    res, _ = _OCR(img)
    return "\n".join(line[1] for line in res) if res else ""


def clean_text(text: str) -> str:
    """清理 PDF 提取出的杂质：多余换行、连字符断词、页眉页脚噪音。"""
    text = text.replace("\u00ad", "")                # 软连字符
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)     # 断词连字符合并
    text = re.sub(r"(\S)\n(?!\n)(?=[\u4e00-\u9fff])", r"\1", text)  # 中文行尾换行合并
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """把长文本切成适合 TTS 的段，尽量在句子边界切。"""
    chunks, buf = [], ""
    sentences = re.split(r"(?<=[。！？；!?;.])\s*", text)
    for s in sentences:
        while len(s) > limit:            # 单句超长则硬切
            chunks.append(s[:limit])
            s = s[limit:]
        if len(buf) + len(s) > limit and buf:
            chunks.append(buf.strip())
            buf = s
        else:
            buf += s
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


async def synth(chunks: list[str], voice: str, rate: str, pitch: str,
                out_path: Path, tmp_dir: Path):
    """逐段合成 MP3 再拼接（避免一次请求过长失败）。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        mp3 = tmp_dir / f"part_{i:04d}.mp3"
        print(f"\r  合成中 {i}/{total} ...", end="", flush=True)
        for attempt in range(3):
            try:
                await edge_tts.Communicate(chunk, voice, rate=rate,
                                           pitch=pitch).save(str(mp3))
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"第 {i} 段合成失败: {e}") from e
                await asyncio.sleep(2 * (attempt + 1))
        parts.append(mp3)

    with open(out_path, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
    try:  # 清理半成品：尽力而为，失败不阻塞交付
        for p in parts:
            p.unlink(missing_ok=True)
        tmp_dir.rmdir()
    except OSError:
        print(f"[warn] 临时目录清理失败: {tmp_dir}（可手动删除）")
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\r✅ 完成 {total} 段 -> {out_path.name} ({size_mb:.1f} MB)")


def ensure_utf8_console() -> None:
    """Windows 控制台默认 GBK，emoji 会编码崩溃；统一转 UTF-8（失败则忽略）。"""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main():
    ensure_utf8_console()
    ap = argparse.ArgumentParser(description="PDF 电子书 -> 语音朗读")
    ap.add_argument("pdf", type=Path, help="PDF 文件路径")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="输出音频路径 (默认 output/书名.mp3)")
    ap.add_argument("--pages", help="页码范围，如 5 或 1-10,15")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="音色")
    ap.add_argument("--rate", default="+0%", help='语速，如 "+20%%" / "-10%%"')
    ap.add_argument("--pitch", default="+0Hz", help="音调，如 \"+20Hz\"")
    args = ap.parse_args()

    pdf: Path = args.pdf.resolve()
    if not pdf.exists():
        sys.exit(f"找不到文件: {pdf}")

    pages_data = extract_text(pdf, args.pages)
    if not pages_data:
        sys.exit("没有从 PDF 中提取到文本（可能是扫描版图片 PDF，需要 OCR）。")

    full_text = "\n".join(t for _, t in pages_data)
    n_chars = len(full_text)
    print(f"📖 《{pdf.stem}》 共提取 {len(pages_data)} 页 / {n_chars} 字")

    base_out = args.output or base_dir() / "output" / f"{pdf.stem}.mp3"
    base_out.parent.mkdir(parents=True, exist_ok=True)

    chunks = chunk_text(full_text)
    est_min = n_chars / 4.5 / 60          # 中文约 270 字/分钟
    print(f"🎙️ 音色: {args.voice} | 语速: {args.rate} | 预计时长 ~{est_min:.0f} 分钟")
    print(f"💾 输出: {base_out}")

    tmp = base_out.with_suffix(".parts")
    asyncio.run(synth(chunks, args.voice, args.rate, args.pitch, base_out, tmp))


# Web 界面用的别名
extract_text_progress = extract_text


if __name__ == "__main__":
    main()
