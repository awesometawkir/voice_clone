# Voice Clone Service

A Django-based web application for voice cloning and text-to-speech using XTTS v2, OpenAI TTS, and OpenRouter.

## Features

- 🎤 **Voice Cloning** - Clone any voice with a 5-10 second sample using Coqui XTTS v2
- 🗣️ **Multiple TTS Options**:
  - Free: Edge TTS (Aria, Guy, and more voices)
  - Premium: OpenAI TTS (GPT-4o Audio)
  - Premium: OpenRouter (ElevenLabs, Coqui XTTS v2, and more)
- 🎙️ **Speech-to-Text** - Transcribe audio using Google Speech Recognition or Whisper
- 📂 **Voice Sample Management** - Upload or record voice samples directly in browser
- 🌍 **Multi-language Support** - English, Spanish, French, German, and more

## Quick Start

### Windows

```powershell
# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Start server
python manage.py runserver 8000
```

### Linux

```bash
# Run installation script
chmod +x install_linux.sh
./install_linux.sh

# Activate virtual environment
source venv/bin/activate

# Start server
python manage.py runserver 0.0.0.0:8000
```

Then open: http://localhost:8000

## Requirements

- Python 3.8+
- FFmpeg (for audio conversion)
- ~2GB disk space (for XTTS v2 model)

### Install FFmpeg

**Windows**: Download from https://ffmpeg.org/download.html

**Linux**:
```bash
sudo apt install ffmpeg  # Ubuntu/Debian
sudo dnf install ffmpeg  # Fedora
```

## Voice Cloning Usage

1. **Upload Voice Sample**
   - Go to "Voice Cloning Studio"
   - Upload a 5-10 second clear audio sample OR record your voice
   - Give it a name

2. **Generate Cloned Speech**
   - Select your uploaded voice sample
   - Enter any text
   - Click "Clone Voice - Generate Speech!"
   - Wait ~20-30 seconds
   - Download the cloned audio

## API Keys (Optional)

For premium TTS services:

- **OpenAI**: Get API key from https://platform.openai.com/api-keys
- **OpenRouter**: Get API key from https://openrouter.ai/keys

Keys are saved securely in your browser's localStorage.

## Project Structure

```
voice/
├── voice_clone/          # Main Django app
│   ├── services/         # TTS service implementations
│   ├── models.py         # Database models
│   └── views.py          # API endpoints
├── templates/            # HTML templates
├── media/                # Uploaded files and outputs
├── requirements.txt      # Python dependencies
└── manage.py             # Django management script
```

## Deployment

### Linux Production

See [LINUX_DEPLOYMENT.md](LINUX_DEPLOYMENT.md) for detailed instructions including:
- systemd service setup
- Gunicorn configuration
- Firewall setup
- GPU support

### Windows Auto-Start

Use `setup_startup.ps1` to configure automatic startup on Windows.

## Troubleshooting

### Voice Cloning Not Working

Check terminal for:
```
✓ Coqui TTS available for Cloning. Using device: cpu
✓ Torchaudio.load patched to use soundfile (bypassing torchcodec)
✓ FFmpeg available for audio conversion
```

If you see errors, ensure:
1. FFmpeg is installed and in PATH
2. All dependencies are installed: `pip install -r requirements.txt`

### "Baby Voice" Issue

This has been fixed! The code now:
- Uses soundfile instead of incompatible torchcodec
- Properly handles audio sample rates
- Uses the correct XTTS v2 API methods

## Technical Details

- **Framework**: Django 5.2.9
- **Voice Cloning**: Coqui TTS XTTS v2
- **Audio Processing**: librosa, soundfile, pydub
- **Fallback TTS**: Edge TTS (Aria voice)
- **Database**: SQLite (default)

## License

MIT License - Feel free to use and modify!

## Credits

- Coqui TTS for XTTS v2 model
- OpenAI for TTS API
- OpenRouter for unified TTS access
- Edge TTS for free fallback voices
