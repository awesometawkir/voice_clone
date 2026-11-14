# Voice Studio

A local studio for narrating YouTube videos in your own cloned voice. Everything runs on your PC:
no subscription, no per-character fees, and your voice sample never leaves the machine.

## What it does

- **Narrate** – paste a script and render it in your voice. The script is split into sentences; each
  one is generated, transcribed and compared with the script, and re-recorded automatically if the
  model skipped or garbled words. Edit or re-record a single sentence without redoing the video.
  Output is mastered to YouTube loudness (-14 LUFS, -1 dBTP) as WAV and MP3, with `.srt`/`.vtt` captions.
- **Voices** – record or upload 15 to 30 seconds of speech. The sample is cleaned, scored, and you get
  plain advice on how to improve it.
- **Write** – a writing assistant for video ideas, outlines, full scripts, hooks, rewrites for the ear,
  titles/description/chapters/tags, Shorts, and translation. Uses a local Ollama model or any
  OpenAI-compatible API key.
- **Transcribe** – turn any audio or video file into text and captions (faster-whisper).
- **Clean up** – denoise, EQ, compress and loudness-normalise a real microphone recording.
- **Settings** – channel profile for the assistant, writing model, and a pronunciation dictionary
  for names and brand words.

## Voice engines

| Engine | Clones your voice | Languages | Notes |
| --- | --- | --- | --- |
| Chatterbox Turbo | yes | English | Fastest. Supports sound tags such as `[laugh]`, `[sigh]`. |
| Chatterbox | yes | English | Expressiveness and pacing controls. |
| Chatterbox Multilingual | yes | 23 languages | Largest model. |
| Online stock voices | no | 24, including Bengali | Microsoft Edge voices; needs internet. |

Chatterbox is MIT licensed and adds an inaudible watermark to generated audio.

## Install (Linux)

Requirements: Python 3.12, FFmpeg, about 8 GB of disk. An NVIDIA GPU with 4 GB or more is strongly
recommended; without one the cloning engines run on the CPU, slowly.

```bash
sudo apt install ffmpeg
./install_linux.sh
./run.sh            # then open http://127.0.0.1:8010
```

`./run.sh 9000` uses another port. For the writing assistant, install [Ollama](https://ollama.com)
and `ollama pull qwen3:8b`, or add an API key in Settings.

## Use only voices you have the right to use

Clone your own voice, or a voice whose owner has given you permission. The app asks you to confirm
this for every sample. YouTube also requires you to disclose realistic synthetic content in some
cases; check its current "altered or synthetic content" policy when you upload.

## Layout

```
voice_clone/services/engines.py   voice models (one loaded at a time)
voice_clone/services/pipeline.py  script -> checked takes -> mastered audio + captions
voice_clone/services/textprep.py  number/symbol normalisation, sentence splitting, captions
voice_clone/services/audio.py     ffmpeg mastering, sample analysis
voice_clone/services/stt.py       faster-whisper (CPU)
voice_clone/services/llm.py       writing assistant
voice_clone/services/jobs.py      one-at-a-time background worker
templates/home.html, static/      the single-page interface
```

This is a single-user local app. Do not expose it to the internet as is: it has no login.
