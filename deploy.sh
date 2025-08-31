#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Helper function to print step numbers
step=1
step() { echo -e "\n[$step] $1"; step=$((step+1)); }

echo "🚀 Starting full deployment for 1h trading bot..."

step "Ensure python3 and pip are available"
if ! command -v python3 >/dev/null; then
    echo "❌ Python3 not found. Please install Python 3.9+."
    exit 1
fi

if ! command -v pip >/dev/null; then
    echo "❌ pip not found. Please install pip."
    exit 1
fi

step "Stop any running orchestrator"
PID_FILE="orchestrator.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        if ps -p "$OLD_PID" -o args= | grep -q "futures_gpt_orchestrator_full.py"; then
            echo "Stopping orchestrator PID $OLD_PID"
            kill "$OLD_PID"
            sleep 2
        else
            echo "PID $OLD_PID does not belong to orchestrator, skipping"
        fi
    else
        echo "No process found for PID $OLD_PID"
    fi
    rm -f "$PID_FILE"
else
    echo "No existing PID file found"
fi

step "Create virtual environment if missing"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created."
fi

step "Activate virtual environment"
source venv/bin/activate

step "Upgrade pip"
pip install --upgrade pip

step "Install dependencies"
pip install -r requirements.txt

step "Load environment variables from .env"
if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
    echo "✅ Loaded environment variables."
else
    echo "⚠️  No .env file found. Please create one!"
    deactivate
    exit 1
fi

step "Remove Python cache files"
find . -name "*.pyc" -delete

step "Run orchestrator"
nohup python3 futures_gpt_orchestrator_full.py --loop > bot.log 2>&1 &
echo $! > "$PID_FILE"

step "Deactivate environment"
deactivate

echo -e "\n🎉 Deployment finished!"

