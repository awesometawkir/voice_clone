#!/bin/bash
# Voice Studio - Linux installation
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg is required. Install it with: sudo apt install ffmpeg"
    exit 1
fi

echo "Creating the Python 3.12 environment and installing dependencies."
echo "This downloads PyTorch (about 2.5 GB), so it can take a while."
if command -v uv &> /dev/null; then
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r requirements.txt
else
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

[ -f .env ] || cp .env.example .env
.venv/bin/python manage.py migrate --noinput

echo ""
echo "Installed. Start the studio with:  ./run.sh"
echo "The voice model (1 to 3 GB) downloads the first time you render."
echo "For the writing assistant, install Ollama and run: ollama pull qwen3:8b"
