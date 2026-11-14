"""A one-at-a-time background worker backed by the Job table.

Renders are slow and the GPU is small, so jobs queue up and run in a single
thread inside the server process. The browser polls /api/jobs/<id>/.
"""
import threading
import traceback

from django.db import close_old_connections
from django.utils import timezone

from ..models import Job, Project

_handlers = {}
_wake = threading.Event()
_thread = None
_start_lock = threading.Lock()


class Cancelled(Exception):
    pass


def handler(kind):
    def register(fn):
        _handlers[kind] = fn
        return fn
    return register


def enqueue(kind, payload=None, project=None):
    job = Job.objects.create(kind=kind, payload=payload or {}, project=project)
    ensure_worker()
    _wake.set()
    return job


def ensure_worker():
    global _thread
    with _start_lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, name="studio-worker", daemon=True)
            _thread.start()


def recover():
    """After a restart nothing is running: requeue interrupted jobs."""
    Job.objects.filter(status="running").update(status="queued", progress=0, message="Resuming after restart")
    if Job.objects.filter(status="queued").exists():
        ensure_worker()
        _wake.set()


class Reporter:
    def __init__(self, job):
        self.job = job

    def __call__(self, progress=None, message=None):
        fresh = Job.objects.filter(pk=self.job.pk).values_list("status", flat=True).first()
        if fresh in (None, "cancelled"):
            raise Cancelled()
        fields = {}
        if progress is not None:
            fields["progress"] = round(float(progress), 4)
        if message is not None:
            fields["message"] = message[:300]
        if fields:
            Job.objects.filter(pk=self.job.pk).update(**fields)


def _loop():
    while True:
        close_old_connections()
        job = Job.objects.filter(status="queued").order_by("created_at").first()
        if job is None:
            _wake.clear()
            _wake.wait(timeout=30)
            continue
        if not Job.objects.filter(pk=job.pk, status="queued").update(status="running"):
            continue
        try:
            result = _handlers[job.kind](job, Reporter(job)) or {}
            Job.objects.filter(pk=job.pk).update(status="done", progress=1, result=result,
                                                 finished_at=timezone.now())
        except Cancelled:
            Job.objects.filter(pk=job.pk).update(finished_at=timezone.now(), message="Cancelled")
            if job.project_id:
                Project.objects.filter(pk=job.project_id, status__in=["queued", "rendering"]).update(status="draft")
        except Exception as exc:
            traceback.print_exc()
            Job.objects.filter(pk=job.pk).update(status="error", message=str(exc)[:300],
                                                 finished_at=timezone.now())
            if job.project_id:
                Project.objects.filter(pk=job.project_id).update(status="error")
