"""Import subtitle files (.srt / .vtt) as screenplay-like episodes.

For inputs that are not Kuku's screenplay format, e.g. YouTube auto-captions of a full microdrama. Captions have no
camera/action lines and usually no speaker names, so the pipeline sees dialogue only (text judgement still works;
attention.py has less to go on).

* Rolling auto-caption cues (overlapping fragments that break mid-sentence) are rebuilt into whole sentences.
* ">>" (YouTube's speaker-change marker) or "- " starts a new speaker turn; "NAME: text" keeps the name.
* Each sentence gets the start time of the cue its first word came from; it ends where the next sentence starts,
  so cuts can only fall between sentences.
* A long video is split into parts of ~part_seconds at sentence boundaries; each part is treated as an "episode".
  Times stay absolute (seconds from the start of the video), so a promo's timestamps map straight onto the video.
"""
from __future__ import annotations

import re
from pathlib import Path

from .parse import Episode, Line

RE_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
RE_TAG = re.compile(r"<[^>]+>|\{[^}]+\}")
RE_NAME = re.compile(r"^([A-Z][A-Za-z .'-]{1,30}):\s+(.+)$")
SUBTITLE_EXT = (".srt", ".vtt")


def _sec(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def read_cues(path: str | Path) -> list[tuple[float, float, str]]:
    """(start, end, text) per cue, de-duplicated (auto-captions repeat the previous line inside the next cue)."""
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    cues, cur, buf = [], None, []
    for ln in raw + [""]:
        m = RE_TIME.search(ln)
        if m:
            cur = (_sec(*m.groups()[:4]), _sec(*m.groups()[4:]))
            buf = []
            continue
        if cur is None:
            continue
        if ln.strip():
            if not ln.strip().isdigit():
                buf.append(RE_TAG.sub("", ln).strip())
            continue
        if buf:
            cues.append((cur[0], cur[1], " ".join(x for x in buf if x)))
        cur, buf = None, []
    out, prev = [], ""
    for a, b, t in cues:  # drop the repeated tail of the previous cue (rolling captions)
        if prev and t.startswith(prev):
            t = t[len(prev):].strip()
        if t:
            out.append((a, b, t))
            prev = t
    return out


def _sentences(cues) -> list[dict]:
    """Words keep the start time of their cue; split into sentences and speaker turns."""
    words: list[tuple[float, str, bool]] = []  # (time, word, starts_new_turn)
    for ci, (a, b, t) in enumerate(cues):
        t = re.sub(r"\[(?:music|applause|laughter|__)\]", " ", t, flags=re.I)
        span_end = cues[ci + 1][0] if ci + 1 < len(cues) else b  # words of this cue are spoken until the next cue
        toks = [x for x in re.split(r"(>>|^- |\s+)", t) if x and not x.isspace()]
        n = max(1, sum(1 for x in toks if x not in (">>", "- ")))
        k = 0
        for x in toks:
            if x in (">>", "- "):
                words.append((a + (span_end - a) * k / n, "", True))
                continue
            words.append((a + (span_end - a) * k / n, x, False))  # spread words evenly across the cue
            k += 1
    sents, cur, t0, turn, speaker = [], [], None, 1, None
    new_turn = False
    for t, w, flag in words:
        if flag:
            if cur:
                sents.append({"start": t0, "text": " ".join(cur), "turn": turn, "speaker": speaker})
                cur = []
            turn += 1
            new_turn, speaker = True, None
            continue
        if not cur:
            t0 = t
        cur.append(w)
        if re.search(r"[.!?…][\"')\]]*$", w) and len(" ".join(cur)) > 2:
            sents.append({"start": t0, "text": " ".join(cur), "turn": turn, "speaker": speaker})
            cur = []
    if cur:
        sents.append({"start": t0, "text": " ".join(cur), "turn": turn, "speaker": speaker})
    for s in sents:  # "NAME: text" speaker labels, if the file has them
        m = RE_NAME.match(s["text"])
        if m:
            s["speaker"], s["text"] = m.group(1).upper(), m.group(2)
    return sents


def load_subtitles(path: str | Path, max_seconds: float | None = None, part_seconds: float = 150.0,
                   show: str | None = None) -> list[Episode]:
    cues = read_cues(path)
    if max_seconds:
        cues = [c for c in cues if c[0] < max_seconds]
    sents = _sentences(cues)
    if not sents:
        return []
    last_end = max(c[1] for c in cues)
    for i, s in enumerate(sents):
        nxt = sents[i + 1]["start"] if i + 1 < len(sents) else last_end
        s["end"] = max(s["start"] + 0.3, nxt - 0.05)
    # split into parts at sentence boundaries
    parts: list[list[dict]] = [[]]
    part_start = sents[0]["start"]
    for s in sents:
        if parts[-1] and s["start"] - part_start >= part_seconds and s["turn"] != parts[-1][-1]["turn"]:
            parts.append([])
            part_start = s["start"]
        parts[-1].append(s)
    eps = []
    name = show or Path(path).stem
    for n, part in enumerate(parts, 1):
        a, b = part[0]["start"], part[-1]["end"]
        ep = Episode(num=n, logline=f"Part {n} of '{name}' ({_mmss(a)}-{_mmss(b)} of the video). Source is auto-generated "
                                    f"captions: dialogue only, speaker names unknown (each new speaker turn is a new "
                                    f"label), no camera or action descriptions.",
                     continuity="", path=str(path))
        for i, s in enumerate(part, 1):
            spk = s["speaker"] or f"VOICE {'A' if s['turn'] % 2 else 'B'}"
            ep.lines.append(Line(id=f"E{n:02d}_L{i:03d}", ep=n, idx=i, scene=1, scene_heading="", kind="DIALOGUE",
                                 speaker=spk, emotion=None, text=s["text"], start=round(s["start"], 2),
                                 end=round(s["end"], 2)))
        eps.append(ep)
    return eps


def _mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"
