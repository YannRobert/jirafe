#!/bin/sh
# Stops the Jirafe server started by start.sh.

# Same location as start.sh.
if [ "$(uname)" = "Darwin" ]; then
  STATE_DIR="$HOME/Library/Caches/jirafe"
else
  case "$XDG_CACHE_HOME" in
    /*) STATE_DIR="$XDG_CACHE_HOME/jirafe" ;;
    *) STATE_DIR="$HOME/.cache/jirafe" ;;
  esac
fi
PID_FILE="$STATE_DIR/jirafe.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "Jirafe is not running (no $PID_FILE)."
  exit 0
fi
PID="$(cat "$PID_FILE")"
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Jirafe was no longer running (pid $PID)."
  rm -f "$PID_FILE"
  exit 0
fi

kill "$PID"
# Up to 5 seconds for a clean exit, then forced: a stuck call to Jira must not keep the port taken.
for _ in 1 2 3 4 5; do
  kill -0 "$PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
  kill -9 "$PID"
fi
rm -f "$PID_FILE"
echo "Jirafe stopped (pid $PID)."
