@echo off
cd /d C:\Users\ThandokuhleM_7dgopdd\Downloads\cv_parser_latest
if not exist storage\outputs mkdir storage\outputs
"C:\Users\ThandokuhleM_7dgopdd\AppData\Local\Programs\Python\Python313\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>storage\outputs\api_stdout.log 2>storage\outputs\api_stderr.log
