"""Writing assistant for the channel: scripts, hooks, titles, descriptions.

Two kinds of provider:
  - "ollama": a model running on this PC (free, private).
  - "api":    any OpenAI-compatible endpoint (OpenRouter, OpenAI, ...), which
              is how you reach stronger hosted models with your own key.
"""
import json
import os

import requests

from ..models import Setting

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

DEFAULTS = {
    "provider": os.getenv("LLM_PROVIDER", "ollama"),
    "ollama_model": os.getenv("OLLAMA_MODEL", ""),
    # Keep the local LLM on the CPU by default so it never evicts the voice model from a small GPU.
    "ollama_gpu": os.getenv("OLLAMA_USE_GPU", "0") == "1",
    "base_url": os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    "api_key": os.getenv("LLM_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
    "model": os.getenv("LLM_MODEL", ""),
}


class LLMError(Exception):
    pass


def config():
    return {**DEFAULTS, **(Setting.get("llm") or {})}


def ollama_models():
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
        return [m["name"] for m in tags.get("models", [])]
    except Exception:
        return []


def status():
    cfg = config()
    models = ollama_models()
    if cfg["provider"] == "ollama":
        model = cfg["ollama_model"] or (models[0] if models else "")
        ready = bool(model) and model in models
        note = "" if ready else ("Ollama is not running or has no models. Run `ollama pull qwen3:8b`."
                                 if not models else f"Model {model} is not installed in Ollama.")
    else:
        model = cfg["model"]
        ready = bool(cfg["api_key"] and model)
        note = "" if ready else "Add an API key and model name in Settings."
    return {"provider": cfg["provider"], "model": model, "ready": ready, "note": note,
            "ollama_models": models}


def stream(messages, temperature=0.7):
    """Yield text pieces from the configured model."""
    cfg, st = config(), status()
    if not st["ready"]:
        raise LLMError(st["note"])
    try:
        if cfg["provider"] == "ollama":
            options = {"temperature": temperature, "num_ctx": 8192}
            if not cfg["ollama_gpu"]:
                options["num_gpu"] = 0
            resp = requests.post(f"{OLLAMA_URL}/api/chat", stream=True, timeout=(5, 600), json={
                "model": st["model"], "messages": messages, "stream": True,
                "think": False, "options": options, "keep_alive": "10m"})
            if resp.status_code == 400 and "think" in resp.text:  # model without a thinking switch
                resp = requests.post(f"{OLLAMA_URL}/api/chat", stream=True, timeout=(5, 600), json={
                    "model": st["model"], "messages": messages, "stream": True,
                    "options": options, "keep_alive": "10m"})
            if resp.status_code != 200:
                raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
            for line in resp.iter_lines():
                if line:
                    piece = json.loads(line).get("message", {}).get("content", "")
                    if piece:
                        yield piece
        else:
            resp = requests.post(
                cfg["base_url"].rstrip("/") + "/chat/completions", stream=True, timeout=(10, 600),
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json={"model": cfg["model"], "messages": messages, "stream": True,
                      "temperature": temperature})
            if resp.status_code != 200:
                raise LLMError(f"API error {resp.status_code}: {resp.text[:300]}")
            for line in resp.iter_lines():
                if not line.startswith(b"data: ") or line == b"data: [DONE]":
                    continue
                choices = json.loads(line[6:]).get("choices") or [{}]
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach the model: {exc}")


SPOKEN_RULES = (
    "Write for the ear, to be read aloud by one narrator: short sentences, plain words, "
    "contractions, no stage directions, no speaker labels, no emojis, no markdown, no headings. "
    "Separate paragraphs with a blank line. Output only the script."
)

# key -> (label, input hint, instructions). {x} placeholders are filled from the request.
TASKS = {
    "ideas": ("Video ideas", "Your niche or a rough theme",
              "Suggest 10 specific video ideas for this channel about: {text}\n"
              "For each: a working title, the one-sentence promise to the viewer, and why someone would click. "
              "Favour ideas a solo creator can make with voice-over and screen or stock visuals."),
    "outline": ("Outline", "Video topic",
                "Create a tight outline for a {minutes}-minute video on: {text}\n"
                "Include: the hook (first 15 seconds), 3 to 6 beats with the key point of each, "
                "one pattern interrupt or example per beat, and the closing call to action."),
    "script": ("Full script", "Topic or outline",
               "Write a complete narration script of about {words} words (roughly {minutes} minutes at a natural pace) "
               "from this topic or outline:\n{text}\n\nOpen with a strong hook in the first two sentences, "
               "deliver on it, and end with a short call to action. " + SPOKEN_RULES),
    "hooks": ("Hooks", "Topic or script",
              "Write 6 different opening hooks (each 1 to 2 sentences, under 12 seconds spoken) for a video about:\n{text}\n"
              "Vary the angle: surprising fact, bold claim, question, story, stakes, contrarian. Number them."),
    "polish": ("Rewrite for voice", "Paste a draft",
               "Rewrite this draft so it sounds natural spoken aloud while keeping every fact and the same order. "
               + SPOKEN_RULES + "\n\nDraft:\n{text}"),
    "tighten": ("Tighten", "Paste a script",
                "Cut this script by about 20 percent. Remove filler, repetition and throat-clearing; keep the hook, "
                "the facts and the voice. " + SPOKEN_RULES + "\n\nScript:\n{text}"),
    "package": ("Title + description pack", "Paste the script or transcript",
                "From this script create the YouTube upload package:\n"
                "1. TITLES: 8 options under 60 characters, front-loading the key words, no clickbait the video does not pay off.\n"
                "2. THUMBNAIL TEXT: 5 options of 2 to 4 words.\n"
                "3. DESCRIPTION: 2 sentence summary with the main keywords first, then 3 bullet takeaways.\n"
                "4. CHAPTERS: timestamps in 0:00 format, assuming {wpm} spoken words per minute, first one at 0:00.\n"
                "5. TAGS: 15 comma-separated tags.\n"
                "6. PINNED COMMENT: one question that invites replies.\n\nScript:\n{text}"),
    "shorts": ("Shorts from script", "Paste the script",
               "Pull the 3 strongest moments out of this script and rewrite each as a standalone Short of 45 to 55 seconds "
               "(about 120 words): hook in the first sentence, one idea, a loopable last line. "
               "Label them SHORT 1, SHORT 2, SHORT 3.\n\nScript:\n{text}"),
    "translate": ("Translate", "Paste the script",
                  "Translate this narration script into {language}. Keep it natural when spoken aloud in {language}, "
                  "keep paragraph breaks, and do not add notes. Output only the translation.\n\nScript:\n{text}"),
}


def build_messages(task, text, minutes=5, language="English", wpm=150):
    label, _, template = TASKS[task]
    channel = Setting.get("channel") or {}
    system = "You are a senior YouTube scriptwriter and channel strategist helping a solo creator."
    if any(channel.values()):
        system += (f" Channel: {channel.get('name', '')}. Niche: {channel.get('niche', '')}. "
                   f"Audience: {channel.get('audience', '')}. Tone: {channel.get('tone', '')}.")
    system += " Be concrete and specific. Never invent statistics; if a fact is needed and unknown, write [CHECK]."
    prompt = template.format(text=text.strip(), minutes=minutes, words=int(minutes) * wpm,
                             language=language, wpm=wpm)
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
