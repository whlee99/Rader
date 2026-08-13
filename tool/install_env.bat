@echo off
chcp 65001 > nul
setlocal

echo ============================================================
echo  Rader Flash 환경 설치 (Python 3.13 + esptool)
echo  Windows 11 x64
echo ============================================================
echo.

:: ── 1. Python 3.13 설치 여부 확인 ────────────────────────────────────────────
set PY_VER=3.13.7
set PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-amd64.exe
set PY_INSTALLER=%TEMP%\python-%PY_VER%-amd64.exe

python --version 2>nul | findstr /C:"3.13" > nul
if %errorlevel% == 0 (
    echo [OK] Python 3.13 이미 설치됨
    python --version
    goto :install_esptool
)

echo [INFO] Python %PY_VER% 다운로드 중...
echo   URL : %PY_URL%
echo.

:: winget 으로 먼저 시도 (빠름)
winget --version > nul 2>&1
if %errorlevel% == 0 (
    echo [INFO] winget 으로 Python 설치 중...
    winget install --id Python.Python.3.13 --silent --accept-source-agreements --accept-package-agreements
    if %errorlevel% == 0 (
        echo [OK] winget Python 설치 완료
        goto :reload_path
    )
    echo [WARN] winget 실패, 직접 다운로드로 전환합니다.
)

:: winget 실패 시 공식 installer 직접 다운로드
echo [INFO] 공식 installer 다운로드 중... (%PY_INSTALLER%)
powershell -NoProfile -Command "& { [Net.ServicePointManager]::SecurityProtocol = 'Tls12'; (New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INSTALLER%') }"
if not exist "%PY_INSTALLER%" (
    echo [ERROR] 다운로드 실패. 네트워크 연결 또는 URL 을 확인하세요.
    echo   수동 다운로드: %PY_URL%
    goto :error
)

echo [INFO] Python %PY_VER% 설치 중 (관리자 권한 필요)...
"%PY_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_launcher=1
if %errorlevel% neq 0 (
    echo [ERROR] Python 설치 실패 (code=%errorlevel%)
    goto :error
)
echo [OK] Python %PY_VER% 설치 완료

:reload_path
:: PATH 재로드 (새 cmd 없이 python 사용하기 위해)
for /f "delims=" %%i in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%i"

:install_esptool
echo.
echo ── esptool 설치 ─────────────────────────────────────────────────────────────
python -m pip show esptool 2>nul | findstr /C:"Version" > nul
if %errorlevel% == 0 (
    echo [OK] esptool 이미 설치됨
    python -m pip show esptool | findstr /C:"Version"
    goto :done
)

echo [INFO] esptool 설치 중...
python -m pip install --upgrade pip
python -m pip install "esptool>=4.7"
if %errorlevel% neq 0 (
    echo [ERROR] esptool 설치 실패
    goto :error
)

:done
echo.
echo ============================================================
echo  설치 완료
echo ============================================================
python --version
python -m esptool version
echo.
echo  이제 RaderFlash.exe 를 실행하세요.
echo ============================================================
pause
exit /b 0

:error
echo.
echo [ERROR] 설치 중 오류가 발생했습니다.
echo  수동으로 아래 두 단계를 진행하세요:
echo   1. https://www.python.org/downloads/ 에서 Python 3.13 설치
echo      (설치 시 "Add Python to PATH" 반드시 체크)
echo   2. cmd 창에서:  pip install esptool
echo.
pause
exit /b 1
