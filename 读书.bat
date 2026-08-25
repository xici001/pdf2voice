@echo off
rem 把 PDF 拖到这个 bat 上，即可自动转成语音 MP3
cd /d %~dp0
set NO_PROXY=*
set HTTP_PROXY=
set HTTPS_PROXY=
.venv\Scripts\python.exe reader.py "%~1" %2 %3 %4
pause
