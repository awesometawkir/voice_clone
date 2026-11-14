"""Audio utilities: conversion, voice-sample analysis, stitching and mastering.

Everything here is ffmpeg + numpy/soundfile so it works without a GPU.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000  # working sample rate for voice references and stitching


class AudioError(Exception):
    pass


def ffmpeg(*args, capture=False):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-4:])
        raise AudioError(f"ffmpeg failed: {tail}")
    return proc.stderr if capture else None


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        raise AudioError("Could not read this file as audio or video.")


def to_wav(src, dst, sr=SR, filters=None):
    """Decode anything ffmpeg understands (audio or video) to mono 16-bit WAV."""
    args = ["-i", src, "-vn", "-ac", "1", "-ar", sr]
    if filters:
        args += ["-af", filters]
    ffmpeg(*args, "-c:a", "pcm_s16le", dst)
    return dst


def _frame_db(x, sr, ms=20):
    n = max(1, int(sr * ms / 1000))
    frames = x[: len(x) // n * n].reshape(-1, n)
    if not len(frames):
        return np.array([-120.0])
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def analyze(path):
    """Measure the things that decide how well a recording clones."""
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    db = _frame_db(x, sr)
    speech = float(np.percentile(db, 90))
    noise = float(np.percentile(db, 5))
    voiced = float((db > speech - 25).mean())
    return {
        "duration": round(len(x) / sr, 2),
        "peak_db": round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 1),
        "speech_db": round(speech, 1),
        "noise_db": round(noise, 1),
        "snr_db": round(speech - noise, 1),
        "clipping_pct": round(float((np.abs(x) > 0.999).mean() * 100), 3),
        "speech_ratio": round(voiced, 2),
    }


def grade(stats):
    """Turn measurements into a 0-100 score and plain-language advice."""
    score, tips = 100, []
    speech_seconds = stats["duration"] * stats["speech_ratio"]
    if speech_seconds < 5:
        score -= 45
        tips.append("Too short. Record at least 10 seconds of continuous speech; 15 to 30 is ideal.")
    elif speech_seconds < 10:
        score -= 15
        tips.append("A little short. 15 to 30 seconds of speech gives a closer match.")
    if stats["snr_db"] < 20:
        score -= 30
        tips.append("Noisy background. Record in a quiet room, close to the microphone.")
    elif stats["snr_db"] < 30:
        score -= 10
        tips.append("Some background noise. A quieter room will improve the clone.")
    if stats["clipping_pct"] > 0.05:
        score -= 20
        tips.append("The recording is clipping (too loud). Lower the input gain or move back.")
    if stats["speech_db"] < -40:
        score -= 15
        tips.append("Very quiet recording. Move closer to the microphone or raise the gain.")
    if not tips:
        tips.append("Clean sample. This should clone well.")
    return max(0, score), tips


def squeeze_silence(x, sr, keep_ms=220, floor_db=None):
    """Trim leading/trailing silence and shorten long internal pauses."""
    db = _frame_db(x, sr)
    if floor_db is None:
        floor_db = max(np.percentile(db, 90) - 35, -55)
    n = int(sr * 0.02)
    voiced = db > floor_db
    if not voiced.any():
        return x
    keep = int(keep_ms / 20)
    mask = np.zeros(len(voiced), dtype=bool)
    for i in np.flatnonzero(voiced):
        mask[max(0, i - keep // 2): i + keep // 2 + 1] = True
    first, last = np.flatnonzero(voiced)[[0, -1]]
    mask[: max(0, first - 2)] = False
    mask[last + 3:] = False
    return x[: len(mask) * n].reshape(-1, n)[mask].reshape(-1)


def trim_edges(x, sr, pad_ms=40):
    """Trim only leading/trailing silence of a generated take."""
    db = _frame_db(x, sr)
    voiced = np.flatnonzero(db > max(db.max() - 45, -60))
    if not len(voiced):
        return x
    n, pad = int(sr * 0.02), int(sr * pad_ms / 1000)
    start = max(0, voiced[0] * n - pad)
    end = min(len(x), (voiced[-1] + 1) * n + pad)
    return x[start:end]


def prepare_reference(src, dst, max_seconds=30):
    """Make a clean mono reference clip for cloning and report its quality."""
    raw = Path(dst).with_suffix(".raw.wav")
    to_wav(src, raw)
    before = analyze(raw)
    filters = "highpass=f=70"
    if before["snr_db"] < 32:  # only denoise when it helps; it can colour a clean voice
        filters += ",afftdn=nr=10:nf=-40"
    to_wav(src, raw, filters=filters)
    x, sr = sf.read(str(raw), dtype="float32")
    raw.unlink(missing_ok=True)
    x = squeeze_silence(x, sr)[: max_seconds * sr]
    peak = np.abs(x).max()
    if peak > 0:
        x = x * (10 ** (-3 / 20) / peak)
    sf.write(str(dst), x, sr, subtype="PCM_16")
    stats = analyze(dst)
    stats["original_duration"] = before["duration"]
    stats["original_snr_db"] = before["snr_db"]
    stats["clipping_pct"] = before["clipping_pct"]
    stats["denoised"] = "afftdn" in filters
    score, tips = grade({**stats, "snr_db": max(stats["snr_db"], before["snr_db"])})
    stats["score"], stats["tips"] = score, tips
    return stats


def stitch(parts, dst, sr=SR):
    """Join takes with pauses. parts: [(wav_path, pause_after_ms)].

    Returns [(start, end)] in seconds for each part, used for subtitles.
    """
    out, timings, pos = [], [], 0
    for path, pause_ms in parts:
        x, file_sr = sf.read(str(path), dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        if file_sr != sr:
            raise AudioError(f"{path} has sample rate {file_sr}, expected {sr}")
        fade = min(len(x) // 2, int(sr * 0.008))
        if fade:
            ramp = np.linspace(0, 1, fade, dtype="float32")
            x[:fade] *= ramp
            x[-fade:] *= ramp[::-1]
        out.append(x)
        timings.append((pos / sr, (pos + len(x)) / sr))
        gap = np.zeros(int(sr * pause_ms / 1000), dtype="float32")
        out.append(gap)
        pos += len(x) + len(gap)
    if not out:
        raise AudioError("Nothing to stitch.")
    sf.write(str(dst), np.concatenate(out), sr, subtype="PCM_16")
    return timings


def _loudnorm_measure(src, pre, target, tp):
    log = ffmpeg("-i", src, "-af", f"{pre}loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
                 "-f", "null", "-", capture=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.S)
    return json.loads(match.group(0)) if match else None


VOICE_CHAIN = (
    "highpass=f=75,"
    "equalizer=f=220:t=q:w=1.2:g=-1.5,"      # ease boxiness
    "equalizer=f=4200:t=q:w=1.0:g=1.5,"      # presence
    "acompressor=threshold=-20dB:ratio=3:attack=8:release=160:makeup=2,"
)


def master(src, dst_wav, dst_mp3=None, target_lufs=-14.0, true_peak=-1.0, denoise=0, polish=True):
    """Voice mastering: EQ, compression and two-pass loudness normalisation.

    -14 LUFS / -1 dBTP is what YouTube normalises to, so the upload is not
    turned down or left quiet next to other videos.
    """
    pre = ""
    if denoise:
        pre += f"afftdn=nr={int(denoise)}:nf=-35,"
    if polish:
        pre += VOICE_CHAIN
    m = _loudnorm_measure(src, pre, target_lufs, true_peak)
    norm = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
    if m and m.get("input_i") not in (None, "-inf"):
        norm += (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                 f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                 f":offset={m['target_offset']}:linear=true")
    ffmpeg("-i", src, "-vn", "-af", pre + norm, "-ar", 48000, "-ac", 1, "-c:a", "pcm_s16le", dst_wav)
    after = _loudnorm_measure(dst_wav, "", target_lufs, true_peak) or {}
    try:
        short = target_lufs - float(after.get("input_i"))
    except (TypeError, ValueError):
        short = 0
    if 0.5 < short < 12:
        # Peaks stopped the normaliser short of the target: lift the level and catch the peaks with a limiter.
        ceiling = 10 ** ((true_peak - 0.5) / 20)
        lifted = Path(dst_wav).with_suffix(".lift.wav")
        ffmpeg("-i", dst_wav, "-af", f"volume={short + 0.2:.2f}dB,alimiter=limit={ceiling:.3f}:level=false:attack=3:release=60",
               "-ar", 48000, "-c:a", "pcm_s16le", lifted)
        lifted.replace(dst_wav)
        after = _loudnorm_measure(dst_wav, "", target_lufs, true_peak) or after
    if dst_mp3:
        ffmpeg("-i", dst_wav, "-c:a", "libmp3lame", "-b:a", "192k", dst_mp3)
    return {
        "lufs_before": m.get("input_i") if m else None,
        "lufs": after.get("input_i"),
        "true_peak": after.get("input_tp"),
        "duration": round(duration_of(dst_wav), 2),
    }
