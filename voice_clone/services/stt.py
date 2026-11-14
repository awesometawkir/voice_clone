"""Speech-to-text with faster-whisper.

Runs on the CPU on purpose: the GPU is small and reserved for the voice model.
"""
import os
import subprocess
import threading

import numpy as np

from . import textprep

_models = {}
_lock = threading.Lock()

DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "small")
CHECK_MODEL = os.getenv("WHISPER_CHECK_MODEL", "base")


def _model(name):
    with _lock:
        if name not in _models:
            from faster_whisper import WhisperModel
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                         cpu_threads=max(2, (os.cpu_count() or 4) // 2))
        return _models[name]


def _load(path):
    """Decode any audio/video file to the 16 kHz mono float array Whisper expects."""
    proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                           "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise ValueError("Could not read this file as audio or video.")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def heard(path, language="en"):
    """Fast transcript of a short generated take, for checking it against the script."""
    name = CHECK_MODEL + (".en" if language == "en" else "")
    segments, _ = _model(name).transcribe(_load(path), language=language, beam_size=1,
                                         condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe(path, language=None, model=None, progress=None):
    """Full transcript with word timings -> text, SRT and VTT."""
    segments, info = _model(model or DEFAULT_MODEL).transcribe(
        _load(path), language=language or None, word_timestamps=True, vad_filter=True)
    text_parts, cues = [], []
    for seg in segments:
        text_parts.append(seg.text.strip())
        line, start, end = "", None, None
        for word in seg.words or []:
            token = word.word.strip()
            if not token:
                continue
            # break captions at ~2 lines or at a natural pause between words
            if line and (len(textprep._cue_lines(f"{line} {token}")) > 1 or word.start - end > 0.7):
                cues.append((start, end, line))
                line, start = "", None
            start = word.start if start is None else start
            end = word.end
            line = f"{line} {token}".strip()
        if line:
            cues.append((start, end, line))
        if progress and info.duration:
            progress(min(1.0, seg.end / info.duration))
    cues = [(a, b, "\n".join(l for block in textprep._cue_lines(t) for l in block)) for a, b, t in cues]
    return {
        "language": info.language,
        "duration": round(info.duration, 2),
        "text": " ".join(text_parts),
        "srt": textprep.to_srt(cues),
        "vtt": textprep.to_vtt(cues),
    }
