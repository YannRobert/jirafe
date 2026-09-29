#!/bin/sh
# Jirafe: starts the local server and opens the board in the browser (Linux / macOS).
# Launching it again does not start another server: it only reopens the board.
# Options are passed to the server, for instance: ./jirafe.sh --port 9101
cd "$(dirname "$0")/src" || exit 1

if [ -z "$JIRA_PAT" ]; then
  echo "JIRA_PAT is not set."
  echo " 1. In Jira: avatar at the top right > Profile > Personal Access Tokens > Create token."
  echo " 2. In ~/.profile (or ~/.zshrc): export JIRA_PAT=\"the-token\""
  echo " 3. Open a new terminal and run this launcher again."
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Python 3 not found: install it with the system's package manager."
  exit 1
fi

exec "$PYTHON" -m jirafe --open --quiet "$@"
