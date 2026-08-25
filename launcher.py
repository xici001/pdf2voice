# -*- coding: utf-8 -*-
"""pdf2voice 启动器（PyInstaller 打包入口）。

双模式：
    pdf2voice.exe 书.pdf [--pages 1-10] [--voice ...]   # 命令行转换
    pdf2voice.exe                                        # 启动 Web 界面 http://localhost:8765
"""
import sys
from pathlib import Path


def _cli_main() -> None:
    import reader
    reader.main()


def _web_main() -> None:
    import app
    print("📖 pdf2voice 界面: http://localhost:8765（Ctrl+C 退出）")
    app.app.run(host="127.0.0.1", port=8765, debug=False)


def main() -> None:
    # Windows 控制台默认 GBK：先把输出切到 UTF-8，避免 emoji 编码崩溃
    from reader import ensure_utf8_console
    ensure_utf8_console()

    # 第一个参数是 .pdf 文件（或 -h/--help）→ CLI；否则 → Web
    first = sys.argv[1] if len(sys.argv) > 1 else ""
    if first.lower().endswith(".pdf") or first in ("-h", "--help"):
        _cli_main()
    else:
        _web_main()


if __name__ == "__main__":
    main()
