#!/bin/bash
pkill -f "streamlit run.*app.py" 2>/dev/null && echo "Stopped." || echo "Not running."
