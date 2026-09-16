@echo off
setlocal DisableDelayedExpansion
set "ROUTER_ROOT=%~dp0.."
set "ROUTER_PY=%ROUTER_ROOT%\runtime\python\python.exe"
if exist "%ROUTER_PY%" goto run
if exist "%ROUTER_ROOT%\runtime\runtime.json" goto missing
if not defined CODEX_ROUTER_PYTHON goto missing
set "ROUTER_PY=%CODEX_ROUTER_PYTHON%"
:run
"%ROUTER_PY%" -I -S -B -X utf8 "%ROUTER_ROOT%\scripts\runtime_dispatch.py" %*
exit /b %ERRORLEVEL%
:missing
echo ERROR: bundled Python missing. Obtain the complete Windows package for this CPU. 1>&2
exit /b 2
