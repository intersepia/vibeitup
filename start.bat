@echo off
setlocal
cd /d "%~dp0"
if defined PYTHON goto custom
where py >nul 2>nul
if not errorlevel 1 goto launcher
python scripts\start.py %*
goto finished
:launcher
py -3 scripts\start.py %*
goto finished
:custom
"%PYTHON%" scripts\start.py %*
:finished
exit /b %errorlevel%
