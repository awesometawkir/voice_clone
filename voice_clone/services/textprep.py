"""Turn a written script into speakable segments.

TTS models drift on long inputs and stumble on symbols, so the script is
normalised (numbers, symbols, your pronunciation rules) and split into short
segments at sentence boundaries. Each segment is generated, checked and
re-recordable on its own.
"""
import re

try:
    from num2words import num2words
except ImportError:  # optional
    num2words = None

MAX_CHARS = 260
PAUSE_RE = re.compile(r"\[pause(?:\s+([\d.]+)\s*(ms|s)?)?\]", re.I)
ABBREV = {
    "e.g.": "for example", "i.e.": "that is", "etc.": "et cetera", "vs.": "versus",
    "Mr.": "Mister", "Mrs.": "Missus", "Dr.": "Doctor", "approx.": "approximately",
}
SYMBOLS = {"&": " and ", "%": " percent", "+": " plus ", "=": " equals ", "@": " at ", "→": " to ", "~": " about "}


def _number(match):
    raw = match.group(0)
    try:
        if match.group("cur"):
            value = float(match.group("num").replace(",", ""))
            unit = {"$": "dollar", "€": "euro", "£": "pound", "৳": "taka"}[match.group("cur")]
            words = num2words(int(value) if value.is_integer() else value)
            return f"{words} {unit}{'' if value == 1 or unit == 'taka' else 's'}"
        num = match.group("num").replace(",", "")
        if match.group("ord"):
            return num2words(int(num), to="ordinal")
        if re.fullmatch(r"(1[5-9]|20)\d\d", num) and not match.group("pct"):
            return num2words(int(num), to="year")
        value = float(num)
        words = num2words(int(value) if value.is_integer() else value)
        return words + (" percent" if match.group("pct") else "")
    except Exception:
        return raw


NUMBER_RE = re.compile(
    r"(?P<cur>[$€£৳])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<ord>st|nd|rd|th)?(?P<pct>%)?(?![\w])"
)


def normalize(text, rules=(), language="en"):
    """Make text speakable. rules: [(written, spoken)] pronunciation overrides."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = text.replace("…", "...")
    text = re.sub(r"https?://(?:www\.)?([^\s/]+)\S*", r"\1", text)
    text = re.sub(r"^[#>*\-\s]+(?=\S)", "", text, flags=re.M)      # markdown headings/bullets
    text = re.sub(r"[*_`]+", "", text)
    for written, spoken in rules:
        if written:
            text = re.sub(rf"(?<!\w){re.escape(written)}(?!\w)", spoken, text, flags=re.I)
    if language == "en":
        for short, full in ABBREV.items():
            text = text.replace(short, full)
        if num2words:
            text = NUMBER_RE.sub(_number, text)
        for sym, word in SYMBOLS.items():
            text = text.replace(sym, word)
    return re.sub(r"[ \t]+", " ", text).strip()


def _split_long(sentence, limit):
    if len(sentence) <= limit:
        return [sentence]
    pieces, current = [], ""
    for part in re.split(r"(?<=[,;:])\s+", sentence):
        while len(part) > limit:  # no punctuation at all: hard wrap on spaces
            cut = part.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(part[:cut])
            part = part[cut:].strip()
        if current and len(current) + len(part) + 1 > limit:
            pieces.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_script(text, limit=MAX_CHARS, sentence_pause=280, paragraph_pause=750):
    """Return [{'text', 'pause_ms'}]. A blank line is a paragraph break;
    `[pause 1.5s]` inserts an explicit pause."""
    segments = []

    def add_pause(ms):
        if segments:
            segments[-1]["pause_ms"] = max(segments[-1]["pause_ms"], ms)

    for para in re.split(r"\n\s*\n", text):
        pos = 0
        chunks = []
        for m in PAUSE_RE.finditer(para):
            chunks.append(("text", para[pos:m.start()]))
            amount = float(m.group(1) or 1)
            ms = amount if (m.group(2) or "s").lower() == "ms" else amount * 1000
            chunks.append(("pause", int(ms)))
            pos = m.end()
        chunks.append(("text", para[pos:]))
        for kind, value in chunks:
            if kind == "pause":
                add_pause(value)
                continue
            flat = " ".join(value.split())
            if not flat:
                continue
            sentences = re.split(r"(?<=[.!?।])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9\u0080-￿])", flat)
            current = ""
            for sentence in sentences:
                for piece in _split_long(sentence.strip(), limit):
                    if current and len(current) + len(piece) + 1 > limit:
                        segments.append({"text": current, "pause_ms": sentence_pause})
                        current = piece
                    else:
                        current = f"{current} {piece}".strip()
            if current:
                segments.append({"text": current, "pause_ms": sentence_pause})
        add_pause(paragraph_pause)
    if segments:
        segments[-1]["pause_ms"] = 0
    return segments


def words(text):
    return re.findall(r"[\w']+", text.lower().replace("-", " "))


def similarity(expected, heard):
    """1 - word error rate, floored at 0. Used to catch bad takes."""
    a, b = words(expected), words(heard)
    if not a:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return max(0.0, 1 - prev[-1] / len(a))


def _stamp(seconds, sep=","):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def _cue_lines(text, width=42):
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return [lines[i:i + 2] for i in range(0, len(lines), 2)]


def cues_from_segments(items):
    """items: [(text, start, end)] -> caption cues of at most two 42-char lines,
    timed in proportion to their share of the segment."""
    cues = []
    for text, start, end in items:
        blocks = _cue_lines(text)
        total = sum(len(" ".join(b)) for b in blocks) or 1
        t = start
        for block in blocks:
            span = (end - start) * len(" ".join(block)) / total
            cues.append((t, t + span, "\n".join(block)))
            t += span
    return cues


def to_srt(cues):
    return "\n".join(f"{i}\n{_stamp(a)} --> {_stamp(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, 1))


def to_vtt(cues):
    return "WEBVTT\n\n" + "\n".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{text}\n" for a, b, text in cues)
