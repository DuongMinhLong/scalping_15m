#!/usr/bin/env bash

set -e

echo "🚀 Starting full deployment for scalping 15m bot..."

# Ensure python3 and pip are available
if ! command -v python3 >/dev/null; then
    echo "❌ Python3 not found. Please install Python 3.9+."
    exit 1
fi

if ! command -v pip >/dev/null; then
    echo "❌ pip not found. Please install pip."
    exit 1
fi

# Stop any running orchestrator via PID file
echo "🛑 Checking and stopping old futures_gpt_orchestrator_full.py if running..."
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

# Create virtual environment if missing
if [ ! -d "venv" ]; then
    echo "🌐 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created."
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "🔧 Upgrading pip inside virtual environment..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing Python libraries..."
pip install -r requirements.txt

# Load environment variables from .env
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

# Remove Python cache files
find . -name "*.pyc" -delete

# Run orchestrator
echo "🏃 Running futures_gpt_orchestrator_full.py in background with nohup ..."
nohup python3 futures_gpt_orchestrator_full.py --loop > bot.log 2>&1 &
echo $! > "$PID_FILE"

# Deactivate environment
deactivate

echo "🎉 Deployment finished!"
