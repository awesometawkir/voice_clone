"""Narration pipeline: script -> segments -> checked takes -> mastered audio + captions.

What makes this better than "paste text, get a file":
  * each sentence-sized segment is generated on its own, so one bad sentence
    never costs a whole re-render;
  * every take is transcribed and compared with the script, and automatically
    re-recorded when the model skipped, repeated or garbled words;
  * unchanged sentences are reused when the script is edited;
  * the result is mastered to YouTube loudness and comes with captions timed
    from the real audio.
"""
import random
import re
from pathlib import Path

import soundfile as sf
from django.conf import settings as django_settings

from ..models import Job, Pronunciation, Project, Segment, Transcript, VoiceSample
from . import audio, engines, jobs, stt, textprep

PASS_SCORE = 0.86
MAX_ATTEMPTS = 3


def media(*parts):
    path = Path(django_settings.MEDIA_ROOT).joinpath(*map(str, parts))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def rel(path):
    return str(Path(path).relative_to(django_settings.MEDIA_ROOT))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "narration"


def sync_segments(project):
    """Rebuild segments from the script, keeping takes of sentences that did not change."""
    rules = list(Pronunciation.objects.values_list("written", "spoken"))
    opts = project.settings or {}
    pieces = textprep.split_script(
        project.script,
        sentence_pause=int(opts.get("sentence_pause", 280)),
        paragraph_pause=int(opts.get("paragraph_pause", 750)),
    )
    old = {}
    for seg in project.segments.all():
        old.setdefault(seg.spoken, []).append(seg)
    keep = []
    for index, piece in enumerate(pieces):
        spoken = textprep.normalize(piece["text"], rules, project.language)
        if not spoken:
            continue
        reuse = old.get(spoken)
        if reuse:
            seg = reuse.pop(0)
            seg.index, seg.text, seg.pause_ms = index, piece["text"], piece["pause_ms"]
            seg.save()
        else:
            seg = Segment.objects.create(project=project, index=index, text=piece["text"],
                                         spoken=spoken, pause_ms=piece["pause_ms"])
        keep.append(seg.pk)
    project.segments.exclude(pk__in=keep).delete()
    return len(keep)


def invalidate_takes(project):
    """Voice/engine/style changed: every take must be recorded again."""
    project.segments.update(status="pending", audio="", score=None, heard="", attempts=0, error="")


def render_segment(project, seg, engine, report=None):
    """Generate one segment, verify it against the script, retry if needed. Keeps the best take."""
    opts = project.settings or {}
    verify = opts.get("verify", True) and engine.verify
    expected = engines.TAG_RE.sub(" ", seg.spoken)   # sound tags like [laugh] are not words
    voice_ref = project.voice.reference_file.path if (engine.clones and project.voice) else None
    best = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if report:
            report(message=f"Segment {seg.index + 1}: take {attempt}")
        take = media("projects", project.pk, f"seg{seg.pk}_{random.randrange(10**6):06d}.wav")
        engine.generate(seg.spoken, take, voice_ref=voice_ref, language=project.language,
                        stock_voice=project.stock_voice, seed=random.randrange(2**31), **opts)
        x, sr = sf.read(str(take), dtype="float32")
        x = audio.trim_edges(x, sr)
        sf.write(str(take), x, sr, subtype="PCM_16")
        duration = len(x) / sr
        score, said = None, ""
        if verify:
            said = stt.heard(take, project.language)
            score = textprep.similarity(expected, textprep.normalize(said, (), project.language))
            # a take that runs far longer than speech should is a sign of babble
            if duration > max(4.0, len(expected) / 6.0):
                score = min(score, 0.5)
        candidate = (score if score is not None else 1.0, take, duration, said)
        if best is None or candidate[0] > best[0]:
            if best:
                Path(best[1]).unlink(missing_ok=True)
            best = candidate
        else:
            take.unlink(missing_ok=True)
        seg.attempts += 1
        if not verify or best[0] >= PASS_SCORE:
            break
    old_take = seg.audio
    seg.audio, seg.duration, seg.heard = rel(best[1]), round(best[2], 3), best[3]
    seg.score = round(best[0], 3) if verify else None
    seg.status = "done" if (not verify or best[0] >= PASS_SCORE) else "flagged"
    seg.error = ""
    seg.save()
    if old_take and old_take != seg.audio:
        media(old_take).unlink(missing_ok=True)


def assemble(project, report=None):
    """Stitch all takes, master to YouTube loudness, and write captions."""
    segs = list(project.segments.exclude(audio=""))
    if not segs:
        raise audio.AudioError("No audio has been generated yet.")
    opts = project.settings or {}
    if report:
        report(message="Stitching and mastering")
    raw = media("projects", project.pk, "_stitched.wav")
    timings = audio.stitch([(media(s.audio), s.pause_ms) for s in segs], raw)
    speed = min(1.3, max(0.8, float(opts.get("speed", 1.0))))
    if abs(speed - 1) > 0.01:
        sped = media("projects", project.pk, "_speed.wav")
        audio.ffmpeg("-i", raw, "-af", f"atempo={speed}", sped)
        sped.replace(raw)
        timings = [(a / speed, b / speed) for a, b in timings]
    base = f"{slug(project.title)}-{project.pk}"
    wav, mp3 = media("projects", project.pk, base + ".wav"), media("projects", project.pk, base + ".mp3")
    stats = audio.master(raw, wav, mp3, target_lufs=float(opts.get("lufs", -14)),
                         polish=opts.get("polish", True))
    raw.unlink(missing_ok=True)
    cues = textprep.cues_from_segments([(s.text, a, b) for s, (a, b) in zip(segs, timings)])
    project.srt, project.vtt = textprep.to_srt(cues), textprep.to_vtt(cues)
    project.output_wav, project.output_mp3 = rel(wav), rel(mp3)
    flagged = sum(1 for s in segs if s.status == "flagged")
    project.stats = {**stats, "segments": len(segs), "flagged": flagged,
                     "words": len(textprep.words(project.script))}
    project.status = "done"
    project.save()
    return project.stats


@jobs.handler("render")
def render_job(job, report):
    project = Project.objects.get(pk=job.project_id)
    only = job.payload.get("segments")
    engine = engines.get(project.engine)
    if engine.clones and not project.voice:
        raise ValueError("Choose a voice for this project first.")
    Project.objects.filter(pk=project.pk).update(status="rendering")
    todo = project.segments.filter(pk__in=only) if only else project.segments.exclude(status__in=["done", "flagged"])
    todo = list(todo)
    if todo:
        report(0.01, f"Loading {engine.label}. The first use downloads the model, which can take several minutes.")
        engine.load()
    for n, seg in enumerate(todo):
        report(0.02 + 0.9 * n / len(todo))
        try:
            render_segment(project, seg, engine, report)
        except jobs.Cancelled:
            raise
        except Exception as exc:
            if "out of memory" in str(exc).lower():
                raise
            seg.status, seg.error = "error", str(exc)[:500]
            seg.save()
    report(0.94)
    return assemble(project, report)


@jobs.handler("assemble")
def assemble_job(job, report):
    return assemble(Project.objects.get(pk=job.project_id), report)


@jobs.handler("voice")
def voice_job(job, report):
    """Clean an uploaded sample into a cloning reference and transcribe it."""
    voice = VoiceSample.objects.get(pk=job.payload["voice"])
    report(0.1, "Cleaning the recording")
    ref = media("voices", f"voice{voice.pk}.wav")
    quality = audio.prepare_reference(voice.audio_file.path, ref)
    voice.reference_file.name = rel(ref)
    report(0.6, "Transcribing the sample")
    try:
        voice.transcript = stt.heard(ref, voice.language)
    except Exception:
        voice.transcript = ""
    voice.quality = quality
    voice.save()
    engines.forget_voice(ref)
    return quality


@jobs.handler("transcribe")
def transcribe_job(job, report):
    row = Transcript.objects.get(pk=job.payload["transcript"])
    report(0.02, "Decoding audio")
    wav = media("transcripts", f"t{row.pk}.wav")
    audio.to_wav(media(row.source), wav, sr=16000)
    report(0.05, "Transcribing")
    result = stt.transcribe(wav, language=job.payload.get("language") or None,
                            progress=lambda p: report(0.05 + 0.93 * p))
    wav.unlink(missing_ok=True)
    for key in ("language", "text", "srt", "vtt", "duration"):
        setattr(row, key, result[key])
    row.save()
    return {"transcript": row.pk}


@jobs.handler("clean")
def clean_job(job, report):
    """Polish a real microphone recording: denoise, EQ, compress, loudness."""
    src = media(job.payload["source"])
    report(0.1, "Cleaning and mastering")
    base = media("cleaned", f"{Path(job.payload['name']).stem}-clean-{job.pk}")
    wav, mp3 = base.with_suffix(".wav"), base.with_suffix(".mp3")
    stats = audio.master(src, wav, mp3, denoise=int(job.payload.get("denoise", 12)),
                         target_lufs=float(job.payload.get("lufs", -14)))
    return {**stats, "wav": rel(wav), "mp3": rel(mp3)}
