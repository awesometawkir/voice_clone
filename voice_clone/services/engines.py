"""Voice engines.

  turbo         Chatterbox Turbo: fastest cloning model, English, sound tags.
  chatterbox    Chatterbox: English cloning with expressiveness controls.
  multilingual  Chatterbox Multilingual: cloning in 23 languages.
  edge          Microsoft Edge online voices: no cloning, any language, no GPU.

Only one model is kept in memory at a time, because a 4 GB card cannot hold two.
"""
import asyncio
import gc
import importlib.util
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import soundfile as sf

from . import audio

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

MULTI_LANGS = ["en", "es", "fr", "de", "it", "pt", "hi", "ar", "zh", "ja", "ko", "ru", "tr", "nl", "pl",
               "sv", "da", "fi", "el", "he", "ms", "no", "sw"]
EDGE_LANGS = MULTI_LANGS + ["bn"]
TURBO_TAGS = ["[laugh]", "[chuckle]", "[sigh]", "[gasp]", "[cough]", "[clear throat]", "[sniff]", "[groan]", "[shush]"]
TAG_RE = re.compile(r"\[[a-z ]{3,14}\]", re.I)

_lock = threading.RLock()
_loaded = {"id": None, "model": None, "device": None, "voice": None}


def _has(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


_device = None


def device_info():
    """GPU name and memory, read once from nvidia-smi (cheap; does not import torch)."""
    global _device
    if _device is None:
        _device = {"gpu": "", "vram_gb": 0}
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            if out:
                name, mem = [p.strip() for p in out[0].split(",")]
                _device = {"gpu": name.replace("NVIDIA GeForce ", ""), "vram_gb": round(int(mem) / 1024, 1)}
        except Exception:
            pass
    return _device


def _unload():
    if _loaded["model"] is not None:
        import torch
        _loaded.update(id=None, model=None, device=None, voice=None)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _is_oom(exc):
    return "out of memory" in str(exc).lower()


def forget_voice(ref=None):
    """A reference clip changed on disk: recompute its voice print next time."""
    with _lock:
        _loaded["voice"] = None


class Engine:
    id = label = note = ""
    clones = True
    verify = True          # check takes with speech-to-text
    languages = ["en"]
    controls = []
    tags = None
    module = "chatterbox"

    @property
    def available(self):
        return _has(self.module)

    def describe(self):
        return {"id": self.id, "label": self.label, "available": self.available, "clones": self.clones,
                "languages": self.languages, "controls": self.controls, "note": self.note, "tags": self.tags,
                "stock_voices": self.stock_voices()}

    def stock_voices(self):
        return []

    def load(self):
        pass


class _Chatterbox(Engine):
    def _cls(self):
        raise NotImplementedError

    def load(self):
        with _lock:
            if _loaded["id"] == self.id:
                return _loaded["model"]
            _unload()
            import torch
            import warnings
            warnings.filterwarnings("ignore")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                model = self._cls().from_pretrained(device=device)
            except Exception as exc:
                if device != "cuda" or not _is_oom(exc):
                    raise
                gc.collect()
                torch.cuda.empty_cache()
                device = "cpu"   # too big for this card: slower, but it works
                model = self._cls().from_pretrained(device=device)
            _loaded.update(id=self.id, model=model, device=device, voice=None)
            return model

    def _condition(self, model, voice_ref, exaggeration):
        ref = Path(voice_ref)
        key = (str(ref), ref.stat().st_mtime)
        if _loaded["voice"] != key:
            if sf.info(str(ref)).duration < 5.2:
                raise ValueError("The voice sample is shorter than 5 seconds of speech. Record a longer one.")
            model.prepare_conditionals(str(ref), exaggeration=exaggeration)
            _loaded["voice"] = key

    def _kwargs(self, language, opts):
        return {}

    def _speak(self, model, text, language, opts):
        import torch
        try:
            with torch.inference_mode():
                return model.generate(text, **self._kwargs(language, opts)).squeeze(0).cpu().numpy()
        except Exception as exc:
            if not _is_oom(exc):
                raise
            gc.collect()
            torch.cuda.empty_cache()
            if len(text) < 80:
                raise
        # Out of GPU memory on a long sentence: say it in two halves.
        import numpy as np
        mid = len(text) // 2
        cuts = [m.end() for m in re.finditer(r"[,;:]\s|\s", text)] or [mid]
        cut = min(cuts, key=lambda c: abs(c - mid))
        gap = np.zeros(int(model.sr * 0.12), dtype="float32")
        return np.concatenate([self._speak(model, text[:cut].strip(), language, opts), gap,
                               self._speak(model, text[cut:].strip(), language, opts)])

    def generate(self, text, out_path, voice_ref=None, language="en", seed=None, **opts):
        import torch
        if not voice_ref:
            raise ValueError("Choose a voice for this project first.")
        with _lock:
            model = self.load()
            if seed is not None:
                torch.manual_seed(seed)
            self._condition(model, voice_ref, float(opts.get("exaggeration", 0.5)))
            wav = self._speak(model, text, language, opts)
            if model.sr != audio.SR:
                raise audio.AudioError(f"Unexpected model sample rate {model.sr}")
            sf.write(str(out_path), wav, model.sr, subtype="PCM_16")
        return out_path


class Turbo(_Chatterbox):
    id, label = "turbo", "Chatterbox Turbo (fast, English)"
    controls = ["temperature"]
    tags = TURBO_TAGS

    def _cls(self):
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        return ChatterboxTurboTTS

    def _kwargs(self, language, opts):
        return {"temperature": float(opts.get("temperature", 0.8))}


class Classic(_Chatterbox):
    id, label = "chatterbox", "Chatterbox (expressive, English)"
    controls = ["exaggeration", "cfg_weight", "temperature"]

    def _cls(self):
        from chatterbox.tts import ChatterboxTTS
        return ChatterboxTTS

    def _kwargs(self, language, opts):
        return {"exaggeration": float(opts.get("exaggeration", 0.5)),
                "cfg_weight": float(opts.get("cfg_weight", 0.5)),
                "temperature": float(opts.get("temperature", 0.8))}


class Multilingual(Classic):
    id, label = "multilingual", "Chatterbox Multilingual (23 languages)"
    languages = MULTI_LANGS

    def _cls(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        return ChatterboxMultilingualTTS

    def _kwargs(self, language, opts):
        return {**super()._kwargs(language, opts), "language_id": language}


_edge_voices = {"at": 0, "list": None}
EDGE_FALLBACK = ["en-US-AndrewNeural", "en-US-AvaNeural", "en-US-BrianNeural", "en-US-EmmaNeural",
                 "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-IN-PrabhatNeural", "en-IN-NeerjaNeural",
                 "bn-BD-PradeepNeural", "bn-BD-NabanitaNeural", "bn-IN-BashkarNeural", "bn-IN-TanishaaNeural",
                 "hi-IN-MadhurNeural", "hi-IN-SwaraNeural", "es-ES-AlvaroNeural", "es-MX-DaliaNeural",
                 "fr-FR-HenriNeural", "fr-FR-DeniseNeural", "de-DE-ChristophNeural", "de-DE-TanjaNeural",
                 "ar-SA-HamedNeural", "ar-EG-SalmaNeural", "pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"]


def _edge_entry(short, gender=""):
    locale, _, name = short.rpartition("-")
    lang, _, region = locale.partition("-")
    name = re.sub(r"(Multilingual|Expressive)?Neural$", "", name)
    extra = ", ".join(p for p in (region, gender.lower()) if p)
    return {"id": short, "label": f"{name} ({extra})" if extra else name, "lang": {"nb": "no"}.get(lang, lang)}


class Edge(Engine):
    id, label = "edge", "Online stock voices (no cloning)"
    clones, verify = False, False
    module = "edge_tts"
    languages = EDGE_LANGS
    note = ("Ready-made Microsoft voices, generated online. Not your voice, but instant, and the only option "
            "here for Bengali. Needs an internet connection.")

    def stock_voices(self):
        if not self.available:
            return []
        if _edge_voices["list"] is None and time.time() - _edge_voices["at"] > 300:
            _edge_voices["at"] = time.time()
            try:
                import edge_tts
                rows = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=12))
                keep = [_edge_entry(r["ShortName"], r.get("Gender", "")) for r in rows]
                _edge_voices["list"] = sorted((v for v in keep if v["lang"] in EDGE_LANGS),
                                              key=lambda v: (v["lang"], v["id"]))
            except Exception:
                pass
        return _edge_voices["list"] or [_edge_entry(v) for v in EDGE_FALLBACK]

    def generate(self, text, out_path, stock_voice="", language="en", **opts):
        import edge_tts
        voice = stock_voice or next((v["id"] for v in self.stock_voices() if v["lang"] == language), "en-US-AndrewNeural")
        mp3 = Path(out_path).with_suffix(".edge.mp3")
        try:
            asyncio.run(edge_tts.Communicate(TAG_RE.sub("", text), voice).save(str(mp3)))
            audio.to_wav(mp3, out_path)
        except audio.AudioError:
            raise
        except Exception as exc:
            raise ValueError(f"Online voice failed (are you connected to the internet?): {exc}")
        finally:
            mp3.unlink(missing_ok=True)
        return out_path


ENGINES = {e.id: e for e in (Turbo(), Classic(), Multilingual(), Edge())}


def get(engine_id):
    engine = ENGINES.get(engine_id)
    if engine is None:
        raise ValueError(f"Unknown voice engine: {engine_id}")
    if not engine.available:
        raise ValueError(f"{engine.label} is not installed on this machine.")
    return engine


def catalog():
    return [e.describe() for e in ENGINES.values()]


def default_engine():
    return next((e.id for e in ENGINES.values() if e.available), "turbo")
