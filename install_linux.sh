#!/bin/bash

# Voice Clone Service - Linux Installation Script
# This script automates the installation process on Linux

set -e  # Exit on error

echo "=================================="
echo "Voice Clone Service - Linux Setup"
echo "=================================="

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "Error: This script is for Linux only"
    exit 1
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Install it with: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Check for FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Warning: FFmpeg is not installed"
    echo "Install it with: sudo apt install ffmpeg"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing Python dependencies..."
echo "This may take 5-10 minutes (downloading XTTS v2 model ~1.8GB)..."
pip install -r requirements.txt

# Run migrations
echo "Running database migrations..."
python manage.py migrate

echo ""
echo "=================================="
echo "Installation Complete!"
echo "=================================="
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  python manage.py runserver 0.0.0.0:8000"
echo ""
echo "Then open: http://localhost:8000"
echo ""
