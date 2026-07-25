@echo off
REM Dev probe launcher for Windows.
REM
REM Picks a Python that actually has aiohttp installed. Plain "python" is often
REM shadowed by the Microsoft Store execution alias, and the "py" launcher
REM defaults to the newest interpreter, which may not have the dependency.
REM
REM Usage (from anywhere):  tools\probe.cmd tokentest
setlocal
set "HERE=%~dp0"

for %%V in (3.13 3.12 3.14) do (
    py -%%V -c "import aiohttp" >nul 2>&1 && (
        set PYTHONUTF8=1
        py -%%V "%HERE%probe_electrica.py" %*
        exit /b %errorlevel%
    )
)

echo No Python with aiohttp was found.
echo Install it with:  py -3.13 -m pip install aiohttp
exit /b 1
