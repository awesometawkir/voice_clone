#!/bin/bash
# Start Voice Studio. Usage: ./run.sh [port]
cd "$(dirname "$0")" || exit 1
PORT="${1:-8010}"
if [ ! -x .venv/bin/python ]; then
    echo "Not installed yet. Run ./install_linux.sh first."
    exit 1
fi
.venv/bin/python manage.py migrate --noinput >/dev/null || exit 1
echo "Voice Studio: http://127.0.0.1:$PORT"
# --noreload: the render worker and the voice model live in this process
exec .venv/bin/python -W ignore manage.py runserver "127.0.0.1:$PORT" --noreload
