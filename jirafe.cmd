@echo off
rem Jirafe: starts the local server and opens the board in the browser.
rem Shortcut: right-click this file > Send to > Desktop (create shortcut).
rem Launching it again does not start another server: it only reopens the board.
rem Options are passed to the server, for instance: jirafe.cmd --port 9101
chcp 65001 >nul
setlocal
cd /d "%~dp0src"

if not defined JIRA_PAT (
  echo JIRA_PAT is not set.
  echo  1. In Jira: avatar at the top right ^> Profile ^> Personal Access Tokens ^> Create token.
  echo  2. In a terminal: setx JIRA_PAT "the-token"
  echo  3. Run this launcher again.
  pause
  exit /b 1
)

set "PYTHON="
py -3 --version >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON python --version >nul 2>nul && set "PYTHON=python"
if not defined PYTHON (
  echo Python 3 not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH"
  echo ^(install for the current user only: no administrator rights needed^).
  pause
  exit /b 1
)

title Jirafe
echo Jirafe runs as long as this window stays open.
%PYTHON% -m jirafe --open --quiet %*
if errorlevel 1 pause
