@echo off
setlocal
cd /d "%~dp0"
where npm >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 24 LTS, reopen this window, then try again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating the project Python environment...
  py -m venv .venv
  if errorlevel 1 goto failed
)
echo Installing Python web dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip==26.2.2
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-web.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('streamlit') else 1)"
if not errorlevel 1 (
  echo Updating the existing local Streamlit fallback security dependencies...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
echo Checking protected organization setup...
.venv\Scripts\python.exe -m scripts.manage_access setup
if errorlevel 1 goto failed
pushd web
echo Installing frontend dependencies...
call npm ci --no-audit --no-fund
if errorlevel 1 (
  popd
  goto failed
)
echo Building the website...
call npm run build
if errorlevel 1 (
  popd
  goto failed
)
popd
.venv\Scripts\python.exe -m scripts.start_web --open
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Setup or startup failed. Keep this window open and review the message above.
pause
exit /b 1
