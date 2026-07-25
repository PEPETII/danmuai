@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: run_poc.bat --model "E:\path\to\Model.model3.json" [--demo-seconds 10]
  echo    or: run_poc.bat --config config.local.json
  exit /b 2
)
python -m src.main %*
exit /b %ERRORLEVEL%
