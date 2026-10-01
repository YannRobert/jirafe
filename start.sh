#!/bin/sh
# Jirafe in the background (Linux / macOS): the server survives the terminal that started it, until stop.sh.
# Starting it again while it runs does nothing. Options are passed to the server: ./start.sh --port 9101
cd "$(dirname "$0")/src" || exit 1

# Next to the local copy (paths.py, cache_dir): outside the repository, and a cache the system may clear.
if [ "$(uname)" = "Darwin" ]; then
  STATE_DIR="$HOME/Library/Caches/jirafe"
else
  case "$XDG_CACHE_HOME" in
    /*) STATE_DIR="$XDG_CACHE_HOME/jirafe" ;;
    *) STATE_DIR="$HOME/.cache/jirafe" ;;
  esac
fi
PID_FILE="$STATE_DIR/jirafe.pid"
LOG_FILE="$STATE_DIR/jirafe.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Jirafe is already running (pid $(cat "$PID_FILE")): ./stop.sh to stop it."
  exit 0
fi

if [ -z "$JIRA_PAT" ]; then
  echo "JIRA_PAT is not set."
  echo " 1. In Jira: avatar at the top right > Profile > Personal Access Tokens > Create token."
  echo " 2. In ~/.profile (or ~/.zshrc): export JIRA_PAT=\"the-token\""
  echo " 3. Open a new terminal and run this script again."
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

mkdir -p "$STATE_DIR" || exit 1
# -u: without a terminal, Python buffers its output and the log would stay empty.
nohup "$PYTHON" -u -m jirafe --quiet "$@" >"$LOG_FILE" 2>&1 </dev/null &
echo $! >"$PID_FILE"

# A server that cannot start (port taken, invalid configuration) exits at once: report it rather than a
# pid that no longer exists.
sleep 1
if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  rm -f "$PID_FILE"
  cat "$LOG_FILE"
  exit 1
fi
cat "$LOG_FILE"
echo "Running in the background (pid $(cat "$PID_FILE")), log: $LOG_FILE"
