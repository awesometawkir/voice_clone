# Linux Deployment Guide

## Prerequisites

### 1. Install System Dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg

# Fedora/RHEL
sudo dnf install -y python3 python3-pip ffmpeg

# Arch Linux
sudo pacman -S python python-pip ffmpeg
```

### 2. Clone/Copy Project

```bash
# If using git
git clone <your-repo-url> voice-clone
cd voice-clone

# Or copy the project directory
cp -r /path/to/voice /path/to/destination/
cd /path/to/destination/voice
```

## Installation

### 1. Create Virtual Environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Note**: The installation may take 5-10 minutes as it downloads the XTTS v2 model (~1.8GB).

### 3. Run Database Migrations

```bash
python manage.py migrate
```

## Running the Server

### Development Server

```bash
python manage.py runserver 0.0.0.0:8000
```

Access at: `http://localhost:8000` or `http://<your-ip>:8000`

### Production Server (Using Gunicorn)

```bash
# Install gunicorn
pip install gunicorn

# Run with gunicorn
gunicorn voice_clone_project.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

## Auto-Start on Boot (systemd)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/voice-clone.service
```

Add the following content:

```ini
[Unit]
Description=Voice Clone Service
After=network.target

[Service]
Type=simple
User=<your-username>
WorkingDirectory=/path/to/voice
Environment="PATH=/path/to/voice/venv/bin"
ExecStart=/path/to/voice/venv/bin/python manage.py runserver 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Replace**:
- `<your-username>` with your Linux username
- `/path/to/voice` with actual project path

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable voice-clone
sudo systemctl start voice-clone
sudo systemctl status voice-clone
```

## Firewall Configuration

If using UFW:

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
```

If using firewalld:

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

## Platform Compatibility Notes

### ✅ Already Cross-Platform

The codebase is **already fully compatible** with Linux:

1. **File Paths**: Uses `os.path` and `tempfile` (cross-platform)
2. **FFmpeg Detection**: Uses `pydub.utils.which()` (works on all platforms)
3. **Audio Processing**: `librosa`, `soundfile`, `pydub` (all cross-platform)
4. **TorchAudio Patch**: The monkey-patch works identically on Linux and Windows

### No Changes Needed!

The voice cloning functionality will work **exactly the same** on Linux as it does on Windows. The torchaudio monkey-patch that fixes the torchcodec issue is platform-independent.

## Testing on Linux

After installation, test voice cloning:

1. Navigate to `http://localhost:8000`
2. Upload a voice sample in "Voice Cloning Studio"
3. Generate cloned speech
4. Verify you see in terminal:
   ```
   ✓ Coqui TTS available for Cloning. Using device: cpu
   ✓ Torchaudio.load patched to use soundfile (bypassing torchcodec)
   ✓ FFmpeg available for audio conversion
   ```

## GPU Support (Optional)

If you have an NVIDIA GPU on Linux:

```bash
# Install CUDA toolkit (if not already installed)
# Follow: https://developer.nvidia.com/cuda-downloads

# Install PyTorch with CUDA support
pip uninstall torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

The code will automatically detect and use GPU (`cuda` device) for faster voice cloning.

## Troubleshooting

### FFmpeg Not Found

```bash
# Verify FFmpeg installation
which ffmpeg
ffmpeg -version

# If not found, install it
sudo apt install ffmpeg  # Ubuntu/Debian
```

### Permission Errors

```bash
# Ensure media directories are writable
chmod -R 755 media/
```

### Port Already in Use

```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process or use a different port
python manage.py runserver 0.0.0.0:8001
```

## Summary

✅ **No code changes needed** - works on Linux out of the box  
✅ **Same dependencies** - `requirements.txt` works on all platforms  
✅ **Same functionality** - voice cloning works identically  
✅ **Cross-platform design** - all file paths and commands are platform-independent  

The project is ready to deploy on Linux!
