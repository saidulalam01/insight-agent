#!/bin/bash
# One command to start the insight dashboard.
# Usage: just run `insight` from anywhere (alias added to your shell)
# Or: bash ~/work/insight-agent/start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Kill any existing instance
pkill -f "streamlit run.*app.py" 2>/dev/null

echo "Starting Insight Agent..."
streamlit run app.py --server.port 8501 --server.headless true &>/dev/null &
sleep 2
open http://localhost:8501
echo "Running at http://localhost:8501"
echo "To stop: insight-stop  (or: pkill -f 'streamlit run.*app.py')"
