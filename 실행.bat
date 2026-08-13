@echo off
REM ---------------- vacation-tracker 서버 시작 ----------------

REM 0) 문자셋을 UTF-8 로 (한글 경로 출력 오류 예방용 선택 사항)
chcp 65001 >nul

REM 1) 프로젝트 폴더로 이동
cd /d "C:\server"
if errorlevel 1 (
    echo [ERROR] 폴더 경로를 찾을 수 없습니다.^^!
    pause
    exit /b
)

REM 2) 가상환경이 없으면 생성, 있으면 스킵
if not exist venv (
    echo [INFO] venv 폴더가 없어 새로 만듭니다...
    py -3 -m venv venv
)

REM 3) 가상환경 활성화
call venv\Scripts\activate

REM 4) 필요 패키지(Flask) 설치 (처음 한 번만)
pip show flask >nul 2>&1 || (
    echo [INFO] Flask 설치 중...
    pip install flask
)

REM 5) 서버 백그라운드 실행
echo [INFO] 서버 실행...
set "TRUST_PROXY_HEADERS=1"
set "STUDENT_APP_PUBLIC_ENABLED=1"
set "STUDENT_APP_PUBLIC_HOST=app.5a-math.com"
set "STUDENT_APP_REDIRECT_HOST=5a-math.com"
start "" /B py -3 app.py

REM 6) 3초 대기 후 브라우저 열기
timeout /t 3 >nul
start "" "http://192.168.0.5:8003/"

exit /b
