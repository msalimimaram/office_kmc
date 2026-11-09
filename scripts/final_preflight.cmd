@echo off
setlocal EnableExtensions

rem Run the PowerShell preflight from CMD without relying on PATH configuration.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"

set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (
    set "POWERSHELL_EXE="
    where powershell.exe >nul 2>&1
    if not errorlevel 1 set "POWERSHELL_EXE=powershell.exe"
)

if not defined POWERSHELL_EXE (
    if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
        set "POWERSHELL_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
    ) else (
        where pwsh.exe >nul 2>&1
        if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"
    )
)

if not defined POWERSHELL_EXE (
    echo ERROR: Windows PowerShell or PowerShell 7 could not be located.
    echo Install PowerShell or run scripts\final_preflight.ps1 from an existing PowerShell session.
    endlocal & exit /b 9009
)

pushd "%REPO_ROOT%" >nul
if errorlevel 1 (
    echo ERROR: Could not enter the repository root: "%REPO_ROOT%"
    endlocal & exit /b 1
)

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%final_preflight.ps1" %*
set "PREFLIGHT_EXIT=%ERRORLEVEL%"

popd
endlocal & exit /b %PREFLIGHT_EXIT%
