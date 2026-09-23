@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m combochan.dashboard --open
) else (
  echo ComboChan needs its Python environment first.
  echo Run: python -m venv .venv
  echo Then double-click this launcher again.
)
pause
