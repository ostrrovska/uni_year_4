@echo off
REM ---------------------------------------------------------------------------
REM  Two-machine run: this script is the CLIENT side.
REM  It is meant to sit in the ROOT of the security token (the flash drive),
REM  next to the python\ and security\ folders, and to be launched inside the VM.
REM  Everything it needs comes from the flash drive - nothing is installed.
REM
REM  The server address is taken from server_ip.txt, which start_servers_host.ps1
REM  writes onto the token. Pass an address as an argument to override it.
REM ---------------------------------------------------------------------------

setlocal
set ROOT=%~dp0
set PY=%ROOT%python\python.exe
set SEC=%ROOT%security
set LOG=%ROOT%vm_run.log
set SERVER=%1
set TOKENARG=
rem %~dp0 ends with a backslash, and "..." + backslash would escape the closing quote
set ROOTNB=%ROOT:~0,-1%
rem the tokens may sit next to this script, in a token\ subfolder made by Extract All,
rem or in the folder the local demo scripts use
if exist "%ROOT%SECTOKEN" set TOKENARG=--token-dir "%ROOTNB%"
if not defined TOKENARG if exist "%ROOT%token\SECTOKEN" set TOKENARG=--token-dir "%ROOT%token"
if not defined TOKENARG if exist "%LOCALAPPDATA%\BPD_TOKEN\SECTOKEN" set TOKENARG=--token-dir "%LOCALAPPDATA%\BPD_TOKEN"
if not defined TOKENARG echo [!] SECTOKEN folder not found - unpack token.zip next to this script

if "%SERVER%"=="" if exist "%ROOT%token\server_ip.txt" set /p SERVER=<"%ROOT%token\server_ip.txt"
if "%SERVER%"=="" if exist "%ROOT%server_ip.txt" set /p SERVER=<"%ROOT%server_ip.txt"
if "%SERVER%"=="" (
    echo No server address was handed over with the package.
    echo On the host, start_servers_host.ps1 prints the address to use.
    echo.
    set /p SERVER=Server address: 
)
if "%SERVER%"=="" (
    echo [!] No address given - nothing to connect to.
    pause
    exit /b 1
)

if not exist "%PY%" (
    echo [!] %PY% not found - is this script in the root of the flash drive?
    pause
    exit /b 1
)

REM start each run with a clean client-side log
if exist "%LOG%" del /q "%LOG%"

echo ===========================================================================
echo  Security token: %ROOT%
echo  Server        : %SERVER%
echo  This machine  : client   ^|   Server runs on the other machine
echo ===========================================================================
echo.
ipconfig | findstr /i "IPv4"
echo.

echo === LAB 6 / TEST 1: successful authentication over the network ===
"%PY%" "%SEC%\lab_6\client.py" --pin 1111 --slot u_ostrovska --server %SERVER% --port 5607 --log "%LOG%" %TOKENARG%
echo.

echo === LAB 6 / TEST 2: wrong PIN, the token does not open ===
"%PY%" "%SEC%\lab_6\client.py" --pin 9999 --slot u_ostrovska --server %SERVER% --port 5607 --log "%LOG%" %TOKENARG%
echo.

echo === LAB 6 / TEST 3: identifier unknown to the server ===
"%PY%" "%SEC%\lab_6\client.py" --pin 5555 --slot u_mallory --server %SERVER% --port 5607 --log "%LOG%" %TOKENARG%
echo.

echo === LAB 7: access control over the same network link ===
"%PY%" "%SEC%\lab_7\client.py" --pin 1111 --slot u_ostrovska --server %SERVER% --port 5707 --log "%LOG%" %TOKENARG% ^
    --cmd "list" ^
    --cmd "read finance_q1" ^
    --cmd "write finance_q1 written from the virtual machine" ^
    --cmd "read lab_report" ^
    --cmd "delete lab_report" ^
    --cmd "caps"
echo.

echo ===========================================================================
echo  Done. Client-side log: %LOG%
echo  The server windows on the host show peer=^<the address of this machine^>
echo ===========================================================================
pause
endlocal
