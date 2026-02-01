@echo off
REM FastAPI 앱 실행 스크립트 (바이트코드 생성 방지)
set PYTHONDONTWRITEBYTECODE=1
python -B -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
pause

