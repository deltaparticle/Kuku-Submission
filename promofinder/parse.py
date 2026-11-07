"""Stage 0: parse timestamped microdrama screenplays into addressable lines.

Every line gets a stable ID like E07_L042. Downstream LLM stages only ever return
these IDs; real timestamps are computed by code from the parsed data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TS = r"(\d{2}):(\d{2})\.(\d{2})"
RE_TIME = re.compile(rf"^Start: \({TS}\) \| End: \({TS}\)\s*$")
RE_HEADER = re.compile(r"^\*\*(.+?):\*\*\s*$")
RE_SCENE = re.compile(r"^SCENE (\d+)\s*$")
RE_EP_NUM = re.compile(r"^EPISODE NUMBER:\s*Episode\s+(\d+)", re.I)

# Dialogue header: NAME [(O.S.)] (Emotion)   e.g. "MATRIARCH (O.S.) (Firm)"
RE_SPEAKER = re.compile(r"^(?P<name>[^()]+?)(?:\s*\((?P<tag>O\.S\.|V\.O\.|CONT'D)\))?\s*(?:\((?P<emo>[^()]*)\))?$")

NON_SPEECH = {"CAMERA": "CAMERA", "ACTION": "ACTION", "SOUND FX": "SFX"}


def to_sec(m: str, s: str, c: str) -> float:
    return int(m) * 60 + int(s) + int(c) / 100.0


def fmt(t: float) -> str:
    """Seconds -> mm:ss.ss (the screenplay's own format)."""
    m = int(t // 60)
    return f"{m:02d}:{t - 60 * m:05.2f}"


@dataclass
class Line:
    id: str
    ep: int
    idx: int
    scene: int
    scene_heading: str
    kind: str  # CAMERA | ACTION | SFX | DIALOGUE
    speaker: str | None
    emotion: str | None
    text: str
    start: float
    end: float

    def compact(self, max_chars: int = 140) -> str:
        """One-line LLM-facing rendering. Keeps the ID so the LLM can cite it."""
        t = self.text.strip()
        if self.kind == "DIALOGUE":
            emo = f" ({self.emotion})" if self.emotion else ""
            return f'{self.id} [{fmt(self.start)[:-1]}] {self.speaker}{emo}: "{t.strip(chr(34))}"'
        tag = {"CAMERA": "CAM", "ACTION": "ACT", "SFX": "SFX"}[self.kind]
        if len(t) > max_chars:
            t = t[: max_chars - 1].rstrip() + "…"
        return f"{self.id} [{fmt(self.start)[:-1]}] {tag}: {t}"


@dataclass
class Episode:
    num: int
    logline: str
    continuity: str
    path: str
    lines: list[Line] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max((l.end for l in self.lines), default=0.0)

    def by_id(self) -> dict[str, Line]:
        return {l.id: l for l in self.lines}

    def compact(self, max_chars: int = 140) -> str:
        head = f"=== EPISODE {self.num} | logline: {self.logline}"
        return head + "\n" + "\n".join(l.compact(max_chars) for l in self.lines)

    # -- cut-point logic ----------------------------------------------------
    def cut_ok(self, t: float, eps: float = 0.01) -> bool:
        """True if time t does not fall strictly inside any spoken line or SFX."""
        for l in self.lines:
            if l.kind in ("DIALOGUE", "SFX") and l.start + eps < t < l.end - eps:
                return False
        return True

    def next_safe_after(self, t: float, step: float = 0.1, limit: float = 5.0) -> float:
        """Smallest t' >= t (within limit) that is a safe cut; else t."""
        x = t
        while x <= t + limit:
            if self.cut_ok(x):
                return round(x, 2)
            x += step
        return t

    def prev_safe_before(self, t: float, step: float = 0.1, limit: float = 5.0) -> float:
        x = t
        while x >= max(0.0, t - limit):
            if self.cut_ok(x):
                return round(x, 2)
            x -= step
        return t


def parse_episode(path: str | Path) -> Episode:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()

    num = None
    logline = continuity = ""
    scene_no, scene_head = 0, ""
    ep = Episode(num=0, logline="", continuity="", path=str(path))
    pending: tuple[str, str | None, str | None] | None = None  # (kind, speaker, emotion)
    pending_time: tuple[float, float] | None = None

    for ln in raw:
        s = ln.rstrip()
        if not s.strip():
            continue
        if (m := RE_EP_NUM.match(s)):
            num = int(m.group(1))
            continue
        if s.startswith("EPISODE LOGLINE:"):
            logline = s.split(":", 1)[1].strip()
            continue
        if s.startswith("CONTINUITY NOTES:"):
            continuity = s.split(":", 1)[1].strip()
            continue
        if (m := RE_SCENE.match(s)):
            scene_no = int(m.group(1))
            continue
        if s.startswith("Scene heading:"):
            scene_head = s.split(":", 1)[1].strip()
            continue
        if s.startswith(("Scene start:", "Scene end:", "Actions and dialogue:", "--- SCRIPT")):
            continue
        if (m := RE_HEADER.match(s)):
            title = m.group(1).strip()
            if title in NON_SPEECH:
                pending = (NON_SPEECH[title], None, None)
            else:
                sm = RE_SPEAKER.match(title)
                name = (sm.group("name") if sm else title).strip()
                emo = sm.group("emo") if sm else None
                pending = ("DIALOGUE", name, emo)
            pending_time = None
            continue
        if (m := RE_TIME.match(s)):
            g = m.groups()
            pending_time = (to_sec(*g[0:3]), to_sec(*g[3:6]))
            continue
        # a text line: belongs to the pending block
        if pending and pending_time:
            kind, spk, emo = pending
            idx = len(ep.lines) + 1
            ep.lines.append(
                Line(
                    id=f"E{(num or 0):02d}_L{idx:03d}", ep=num or 0, idx=idx,
                    scene=scene_no, scene_heading=scene_head, kind=kind,
                    speaker=spk, emotion=emo, text=s.strip(),
                    start=pending_time[0], end=pending_time[1],
                )
            )
            pending, pending_time = None, None

    ep.num = num or 0
    ep.logline, ep.continuity = logline, continuity
    # ensure id prefix is right even if EPISODE NUMBER came after (it never does, but be safe)
    for l in ep.lines:
        l.ep = ep.num
    return ep


def load_show(folder: str | Path) -> list[Episode]:
    folder = Path(folder)
    files = sorted(folder.rglob("*.txt"))
    eps = [parse_episode(f) for f in files]
    eps = [e for e in eps if e.lines]
    eps.sort(key=lambda e: e.num)
    return eps
