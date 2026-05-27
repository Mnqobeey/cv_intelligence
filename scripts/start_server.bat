@echo off
cd /d "%~dp0.."
if not exist storage\outputs mkdir storage\outputs
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>storage\outputs\api_stdout.log 2>storage\outputs\api_stderr.log
