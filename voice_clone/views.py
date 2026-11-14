import json
import re
from functools import wraps
from pathlib import Path

from django.core.files.storage import default_storage
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import Job, Project, Pronunciation, Segment, Setting, Transcript, VoiceSample
from .services import engines, jobs, llm, pipeline, textprep

RENDER_KEYS = ("voice_id", "engine", "stock_voice", "language")
STYLE_KEYS = ("exaggeration", "cfg_weight", "temperature")


def api(fn):
    """JSON in, JSON out, errors as {'error': ...}."""
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        if request.content_type == "application/json" and request.body:
            try:
                request.json = json.loads(request.body)
            except ValueError:
                return JsonResponse({"error": "Invalid JSON"}, status=400)
        else:
            request.json = request.POST.dict()
        try:
            result = fn(request, *args, **kwargs)
        except (ValueError, KeyError, llm.LLMError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        if isinstance(result, (HttpResponse, StreamingHttpResponse)):
            return result
        return JsonResponse(result, safe=False)
    return wrapper


def url(path):
    return f"/media/{path}" if path else ""


def voice_json(v):
    return {"id": v.pk, "name": v.name, "language": v.language, "is_default": v.is_default,
            "audio": url(v.audio_file.name), "reference": url(v.reference_file.name),
            "transcript": v.transcript, "quality": v.quality, "ready": bool(v.reference_file),
            "created_at": v.created_at.isoformat()}


def job_json(j):
    return {"id": j.pk, "kind": j.kind, "status": j.status, "progress": j.progress,
            "message": j.message, "result": j.result, "project": j.project_id}


def segment_json(s):
    return {"id": s.pk, "index": s.index, "text": s.text, "spoken": s.spoken, "pause_ms": s.pause_ms,
            "audio": url(s.audio), "duration": s.duration, "status": s.status, "score": s.score,
            "heard": s.heard, "attempts": s.attempts, "error": s.error}


def project_json(p, full=False):
    data = {"id": p.pk, "title": p.title, "status": p.status, "engine": p.engine,
            "voice_id": p.voice_id, "stock_voice": p.stock_voice, "language": p.language,
            "settings": p.settings, "stats": p.stats, "wav": url(p.output_wav), "mp3": url(p.output_mp3),
            "updated_at": p.updated_at.isoformat(), "words": len(textprep.words(p.script))}
    if full:
        data["script"] = p.script
        data["has_captions"] = bool(p.srt)
        data["segments"] = [segment_json(s) for s in p.segments.all()]
        job = p.job_set.filter(status__in=["queued", "running"]).first()
        data["job"] = job_json(job) if job else None
    return data


def transcript_json(t, full=False):
    data = {"id": t.pk, "title": t.title, "language": t.language, "duration": t.duration,
            "ready": bool(t.text), "created_at": t.created_at.isoformat()}
    if full:
        data.update(text=t.text, srt=t.srt, vtt=t.vtt)
    return data


@ensure_csrf_cookie
def home(request):
    return render(request, "home.html")


@api
def status(request):
    return {
        "engines": engines.catalog(),
        "device": engines.device_info(),
        "llm": llm.status(),
        "tasks": [{"id": k, "label": v[0], "hint": v[1]} for k, v in llm.TASKS.items()],
        "jobs": [job_json(j) for j in Job.objects.filter(status__in=["queued", "running"])],
    }


# ---------- voices ----------

@api
@require_http_methods(["GET", "POST"])
def voices(request):
    if request.method == "GET":
        return [voice_json(v) for v in VoiceSample.objects.all()]
    upload = request.FILES.get("audio")
    if not upload:
        raise ValueError("Attach or record an audio sample.")
    if request.json.get("consent") not in ("true", "on", "1", True):
        raise ValueError("Confirm that this is your own voice, or that you have the speaker's permission.")
    voice = VoiceSample.objects.create(
        name=request.json.get("name", "").strip() or "My voice",
        language=request.json.get("language", "en"), consent=True,
        audio_file=upload, is_default=not VoiceSample.objects.exists())
    job = jobs.enqueue("voice", {"voice": voice.pk})
    return {"voice": voice_json(voice), "job": job_json(job)}


@api
@require_http_methods(["PATCH", "DELETE"])
def voice_detail(request, pk):
    voice = get_object_or_404(VoiceSample, pk=pk)
    if request.method == "DELETE":
        for f in (voice.audio_file, voice.reference_file):
            if f:
                f.delete(save=False)
        voice.delete()
        return {"ok": True}
    if "name" in request.json:
        voice.name = request.json["name"].strip() or voice.name
    if request.json.get("is_default"):
        VoiceSample.objects.update(is_default=False)
        voice.is_default = True
    voice.save()
    return voice_json(voice)


# ---------- projects ----------

@api
@require_http_methods(["GET", "POST"])
def projects(request):
    if request.method == "GET":
        return [project_json(p) for p in Project.objects.all()]
    default_voice = VoiceSample.objects.filter(reference_file__gt="").first()
    data = request.json
    project = Project.objects.create(
        title=data.get("title", "").strip() or "Untitled narration",
        script=data.get("script", ""),
        voice_id=data.get("voice_id") or (default_voice.pk if default_voice else None),
        engine=data.get("engine") or engines.default_engine(),
        stock_voice=data.get("stock_voice", ""),
        language=data.get("language", "en"),
        settings=data.get("settings") or {})
    return project_json(project, full=True)


@api
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == "DELETE":
        project.delete()
        folder = pipeline.media("projects", pk, "x").parent
        for f in folder.glob("*"):
            f.unlink()
        folder.rmdir()
        return {"ok": True}
    if request.method == "PATCH":
        data = request.json
        redo = any(k in data and data[k] != getattr(project, k) for k in RENDER_KEYS)
        new_settings = {**project.settings, **(data.get("settings") or {})}
        redo = redo or any(new_settings.get(k) != project.settings.get(k) for k in STYLE_KEYS)
        for key in ("title", "script", *RENDER_KEYS):
            if key in data:
                setattr(project, key, data[key] or (None if key == "voice_id" else ""))
        project.settings = new_settings
        project.save()
        if redo:
            pipeline.invalidate_takes(project)
    return project_json(project, full=True)


def _busy(project):
    return project.job_set.filter(status__in=["queued", "running"]).exists()


@api
@require_http_methods(["POST"])
def project_render(request, pk):
    """Render everything that is new or changed. {all: true} re-records every segment."""
    project = get_object_or_404(Project, pk=pk)
    if _busy(project):
        raise ValueError("This project is already rendering.")
    if not project.script.strip():
        raise ValueError("Write or paste a script first.")
    engines.get(project.engine)
    count = pipeline.sync_segments(project)
    if not count:
        raise ValueError("The script has no speakable text.")
    if request.json.get("all"):
        pipeline.invalidate_takes(project)
    project.status = "queued"
    project.save()
    job = jobs.enqueue("render", {}, project)
    return {"job": job_json(job), "project": project_json(project, full=True)}


@api
@require_http_methods(["POST"])
def segment_action(request, pk):
    """Re-record one segment (optionally with edited text), then rebuild the final file."""
    seg = get_object_or_404(Segment, pk=pk)
    project = seg.project
    if _busy(project):
        raise ValueError("Wait for the current render to finish.")
    text = request.json.get("text")
    if text is not None and text.strip() and text.strip() != seg.text:
        rules = list(Pronunciation.objects.values_list("written", "spoken"))
        if seg.text in project.script:  # keep the script in step with the edit
            project.script = project.script.replace(seg.text, text.strip(), 1)
        seg.text = text.strip()
        seg.spoken = textprep.normalize(seg.text, rules, project.language)
        seg.save()
    if "pause_ms" in request.json:
        seg.pause_ms = max(0, min(5000, int(request.json["pause_ms"])))
        seg.save()
        if request.json.get("pause_only"):
            job = jobs.enqueue("assemble", {}, project)
            return {"job": job_json(job)}
    seg.attempts = 0
    seg.save()
    project.status = "queued"
    project.save()
    job = jobs.enqueue("render", {"segments": [seg.pk]}, project)
    return {"job": job_json(job)}


def captions(request, pk, fmt):
    project = get_object_or_404(Project, pk=pk)
    body = project.vtt if fmt == "vtt" else project.srt
    resp = HttpResponse(body, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{pipeline.slug(project.title)}.{fmt}"'
    return resp


# ---------- jobs ----------

@api
def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "DELETE":
        if Job.objects.filter(pk=pk, status__in=["queued", "running"]).update(status="cancelled"):
            if job.project_id:
                Project.objects.filter(pk=job.project_id).update(status="draft")
        job.refresh_from_db()
    return job_json(job)


# ---------- transcripts & clean-up ----------

def _save_upload(upload, folder):
    name = re.sub(r"[^\w.\-]+", "_", upload.name)[-80:]
    return default_storage.save(f"{folder}/{name}", upload)


@api
@require_http_methods(["GET", "POST"])
def transcripts(request):
    if request.method == "GET":
        return [transcript_json(t) for t in Transcript.objects.all()]
    upload = request.FILES.get("file")
    if not upload:
        raise ValueError("Choose an audio or video file.")
    row = Transcript.objects.create(title=Path(upload.name).stem, source=_save_upload(upload, "uploads/transcribe"))
    job = jobs.enqueue("transcribe", {"transcript": row.pk, "language": request.json.get("language", "")})
    return {"transcript": transcript_json(row), "job": job_json(job)}


@api
@require_http_methods(["GET", "DELETE"])
def transcript_detail(request, pk):
    row = get_object_or_404(Transcript, pk=pk)
    if request.method == "DELETE":
        default_storage.delete(row.source)
        row.delete()
        return {"ok": True}
    return transcript_json(row, full=True)


@api
@require_http_methods(["POST"])
def clean(request):
    upload = request.FILES.get("file")
    if not upload:
        raise ValueError("Choose a recording to clean.")
    job = jobs.enqueue("clean", {
        "source": _save_upload(upload, "uploads/clean"), "name": upload.name,
        "denoise": request.json.get("denoise", 12)})
    return {"job": job_json(job)}


# ---------- writing assistant ----------

@api
@require_http_methods(["POST"])
def ai(request):
    data = request.json
    task = data.get("task")
    if task not in llm.TASKS:
        raise ValueError("Unknown task.")
    if not data.get("text", "").strip():
        raise ValueError("Type a topic or paste some text first.")
    messages = llm.build_messages(task, data["text"], minutes=int(data.get("minutes") or 5),
                                  language=data.get("language") or "English")
    if not llm.status()["ready"]:
        raise llm.LLMError(llm.status()["note"])

    def body():
        try:
            yield from llm.stream(messages)
        except llm.LLMError as exc:
            yield f"\n\n[Error: {exc}]"

    resp = StreamingHttpResponse(body(), content_type="text/plain; charset=utf-8")
    resp["X-Accel-Buffering"] = "no"
    return resp


@api
@require_http_methods(["GET", "POST"])
def settings_view(request):
    if request.method == "POST":
        data = request.json
        if "llm" in data:
            current = Setting.get("llm") or {}
            incoming = {k: v for k, v in data["llm"].items()
                        if k in ("provider", "ollama_model", "ollama_gpu", "base_url", "model", "api_key")}
            if incoming.get("api_key") in ("", None):  # blank means "keep the saved key"
                incoming.pop("api_key", None)
            Setting.put("llm", {**current, **incoming})
        if "channel" in data:
            Setting.put("channel", {k: str(data["channel"].get(k, ""))[:500]
                                    for k in ("name", "niche", "audience", "tone")})
    cfg = llm.config()
    key = cfg.pop("api_key", "")
    cfg["has_key"] = bool(key)
    return {"llm": cfg, "llm_status": llm.status(), "channel": Setting.get("channel") or {}}


@api
@require_http_methods(["GET", "POST"])
def pronunciations(request):
    if request.method == "POST":
        written, spoken = request.json.get("written", "").strip(), request.json.get("spoken", "").strip()
        if not written or not spoken:
            raise ValueError("Enter the word and how it should be said.")
        Pronunciation.objects.update_or_create(written=written, defaults={"spoken": spoken})
    return list(Pronunciation.objects.values("id", "written", "spoken"))


@api
@require_http_methods(["DELETE"])
def pronunciation_detail(request, pk):
    Pronunciation.objects.filter(pk=pk).delete()
    return {"ok": True}
