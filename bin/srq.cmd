@echo off
rem srq shim: same entry as SolidRockQuant `srq mcp serve`
rem usage: bin\srq.cmd mcp serve
setlocal
set "ROOT=%~dp0.."
if not defined PYTHON set "PYTHON=python"
set "PYTHONPATH=%ROOT%"
set "PYTHONIOENCODING=utf-8"
"%PYTHON%" -m quant.cli %*
exit /b %errorlevel%
