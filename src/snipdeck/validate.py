"""Step 4 of the pipeline: turn the model's line IDs into clips with real times, on safe cut points.

The model only names line IDs. Everything here is plain code, so an invented or mid-sentence timestamp cannot
reach the output. Entry points: validate_many (single clips) and build_montage.

Code never replaces the model's hook or cliffhanger. It only pads the clip and moves its cuts to safe points. If a moment
cannot meet the rules (20-60 s, hook in the first 3 s), it is rejected with a hint that lists the legal
alternatives, and stages.generate_candidates asks the model to choose again.
"""
from __future__ import annotations

import re

from .parse import Episode, Line, fmt
from .schemas import Promo, RawCandidate, RawMontage, Rejected, Segment

RE_ID = re.compile(r"^E(\d+)_L(\d+)$")


class Invalid(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint  # concrete fix suggestions (legal line IDs) fed back to the model in the repair call


def _line(idx: dict[str, Line], lid: str, what: str) -> Line:
    if lid not in idx:
        raise Invalid(f"{what} '{lid}' does not exist")
    return idx[lid]


def _text_of(l: Line) -> str:
    if l.kind == "DIALOGUE":
        return f'{l.speaker}: "{l.text.strip(chr(34))}"'
    return f"[{l.kind.lower()}] {l.text}"


def _short(l: Line, n: int = 70) -> str:
    t = _text_of(l)
    return t if len(t) <= n else t[: n - 1] + "…"


def ep_of_id(lid: str) -> int:
    m = RE_ID.match(lid or "")
    if not m:
        raise Invalid(f"bad line id '{lid}'")
    return int(m.group(1))


# cut points
def _start_time(ep: Episode, first: Line, hook: Line | None, rules: dict) -> float:
    """Clip start: the model's first line, but never more than hook_window_s before the hook."""
    t0 = first.start
    if hook is not None and hook.start - t0 > rules["hook_window_s"]:
        t0 = max(first.start, hook.start - rules["lead_in_s"])  # hook too late: open right on the hook
    if ep.cut_ok(t0):
        return t0
    anchor = hook.start if hook is not None else first.start
    x = anchor  # latest safe point at or before the anchor that still keeps the hook in the window
    floor = anchor - (rules["hook_window_s"] - 0.05 if hook is not None else 0.0)
    while x >= max(0.0, floor) - 1e-6:
        if ep.cut_ok(x):
            return x
        x -= 0.05
    t0 = ep.next_safe_after(anchor, limit=8.0)  # slide forward to the next gap between spoken lines
    if not ep.cut_ok(t0):
        raise Invalid("start falls inside a spoken line")
    return t0


def _end_time(ep: Episode, last: Line, rules: dict, answered: Line | None = None) -> float:
    """Clip end: just after `last` on a safe cut, never into the next spoken line or the answering line."""
    limit = ep.duration
    nxt = next((l for l in ep.lines[last.idx:] if l.kind == "DIALOGUE" and l.start >= last.end - 0.01), None)
    if nxt is not None:
        limit = min(limit, nxt.start)
    if answered is not None and answered.idx > last.idx:
        limit = min(limit, answered.start)
    limit = max(limit, last.end)
    t1 = min(last.end + rules["tail_s"], limit)
    x = t1
    while x >= last.end - 1e-6:  # latest safe point between the end of `last` and t1
        if ep.cut_ok(x):
            return x
        x -= 0.05
    t1 = ep.next_safe_after(t1)  # e.g. an SFX sting spans the cut: let it finish
    if answered is not None and answered.idx > last.idx and t1 > answered.start + 0.01:
        raise Invalid("cliffhanger line is answered before it finishes")
    if not ep.cut_ok(t1):
        raise Invalid("no safe cut point after the last line")
    return t1


def _cut_at_cliff(ep: Episode, cliff: Line, last: Line, react_s: float) -> Line:
    """End on the cliffhanger: keep only non-spoken reaction beats (camera/action/SFX) right after it.

    Dialogue after the cliffhanger line starts answering it, so it is dropped."""
    keep = cliff
    for l in ep.lines[cliff.idx: last.idx]:  # lines after the cliffhanger, up to the model's end_line
        if l.kind == "DIALOGUE" or l.start > cliff.end + react_s:
            break
        keep = l
    return keep


def snap_segment(ep: Episode, first: Line, last: Line, rules: dict, hook: Line | None = None,
                 answered: Line | None = None, enforce_hook: bool = True) -> tuple[float, float]:
    """Return (start, end) seconds for lines first..last, on safe cut points."""
    if last.idx < first.idx:
        raise Invalid("end_line is before start_line")
    if hook is not None and enforce_hook and not (first.idx <= hook.idx <= last.idx):
        raise Invalid("hook_line is outside the clip")
    t0 = _start_time(ep, first, hook if enforce_hook else None, rules)
    t1 = _end_time(ep, last, rules, answered)
    if t1 <= t0:
        raise Invalid("empty clip")
    return round(t0, 2), round(t1, 2)


def _length_hint(ep: Episode, hook: Line, cliff: Line, end_t: float, rules: dict, k: int = 6) -> str:
    """Tell the model exactly which hook lines (for this ending) or endings (for this hook) give a legal length."""
    lo, hi, lead, tail = rules["min_len_s"], rules["max_len_s"], rules["lead_in_s"], rules["tail_s"]
    hooks = [l for l in ep.lines if l.kind != "CAMERA" and l.idx <= cliff.idx
             and lo + 0.5 <= end_t - max(0.0, l.start - lead) <= hi - 0.5]
    hooks = sorted(hooks, key=lambda l: abs(l.start - hook.start))[:k]
    t0 = max(0.0, hook.start - lead)
    ends = [l for l in ep.lines if l.kind != "CAMERA" and l.idx >= hook.idx
            and lo + 0.5 <= l.end + tail - t0 <= hi - 0.5]
    ends = sorted(ends, key=lambda l: abs(l.start - cliff.start))[:k]
    out = []
    if hooks:
        out.append("keep this cliffhanger and open on one of these hook lines: "
                   + "; ".join(f"{l.id} [{fmt(l.start)[:-1]}] {_short(l)}" for l in sorted(hooks, key=lambda l: l.idx)))
    if ends:
        out.append("or keep this hook and end on one of these lines: "
                   + "; ".join(f"{l.id} [{fmt(l.start)[:-1]}] {_short(l)}" for l in sorted(ends, key=lambda l: l.idx)))
    return " | ".join(out) or "no legal hook/ending combination exists around this moment: choose a different moment"


def _mk_segment(ep: Episode, t0: float, t1: float) -> Segment:
    inside = [l for l in ep.lines if l.end > t0 + 0.01 and l.start < t1 - 0.01]
    return Segment(episode=ep.num, start=t0, end=t1, start_ts=fmt(t0), end_ts=fmt(t1),
                   first_line=inside[0].id if inside else "", last_line=inside[-1].id if inside else "")


def _excerpt(ep: Episode, t0: float, t1: float, include_camera: bool = False) -> list[str]:
    out = []
    for l in ep.lines:
        if l.end > t0 + 0.01 and l.start < t1 - 0.01 and (include_camera or l.kind != "CAMERA"):
            out.append(f"{l.id} {fmt(l.start)[:-1]}  {_text_of(l)}")
    return out


# single clips
def build_single(c: RawCandidate, eps: dict[int, Episode], rules: dict, source: str, pid: str) -> Promo:
    """Turn a model proposal (line IDs) into a clip with real times, or raise Invalid (with a fix hint)."""
    if c.episode not in eps:
        raise Invalid(f"episode {c.episode} not found")
    ep = eps[c.episode]
    idx = ep.by_id()
    first = _line(idx, c.start_line, "start_line")
    last = _line(idx, c.end_line, "end_line")
    hook = _line(idx, c.hook_line, "hook_line")
    cliff = _line(idx, c.cliffhanger_line, "cliffhanger_line")
    for l, nm in ((first, "start_line"), (last, "end_line"), (hook, "hook_line"), (cliff, "cliffhanger_line")):
        if l.ep != ep.num:
            raise Invalid(f"{nm} belongs to a different episode")
    if not (first.idx <= hook.idx <= cliff.idx <= last.idx):
        raise Invalid("need start <= hook <= cliffhanger <= end")
    if hook.kind == "CAMERA":
        raise Invalid("hook_line is a CAMERA description: the hook must be something said or done on screen")
    answered = idx.get(c.answered_at_line) if c.answered_at_line else None
    if answered is not None and answered.ep == ep.num and answered.idx <= last.idx:
        # the model let the clip run through the answer: cut back to just before it
        if answered.idx <= cliff.idx:
            raise Invalid("cliffhanger_line is at or after the line that answers the open question")
        last = ep.lines[answered.idx - 2]  # idx is 1-based: line just before the answer
    last = _cut_at_cliff(ep, cliff, last, rules.get("react_s", 3.0))

    t0 = round(_start_time(ep, first, hook, rules), 2)
    t1 = round(_end_time(ep, last, rules, answered), 2)
    if t1 <= t0:
        raise Invalid("empty clip")
    if hook.start < t0 - 0.01 or hook.start - t0 > rules["hook_window_s"] + 1e-6:
        raise Invalid("hook does not start within the first 3 s after snapping to safe cuts")
    dur = t1 - t0
    lo, hi = rules["min_len_s"], rules["max_len_s"]
    if not (lo <= dur <= hi):
        kind = "long" if dur > hi else "short"
        raise Invalid(f"too {kind}: {dur:.1f}s from hook {hook.id} to cliffhanger {cliff.id} (limit {lo}-{hi}s)",
                      hint=_length_hint(ep, hook, cliff, t1, rules))
    return Promo(
        pid=pid, kind="single", source=source, segments=[_mk_segment(ep, t0, t1)], duration=round(dur, 2),
        hook=_text_of(hook), hook_line_id=hook.id, hook_type=c.hook_type,
        cliffhanger=_text_of(cliff), cliffhanger_line_id=cliff.id, cliffhanger_type=c.cliffhanger_type,
        open_question=c.open_question, why=c.why, excerpt=_excerpt(ep, t0, t1), heur_score=c.heur_score,
    )


# montages
def build_montage(m: RawMontage, eps: dict[int, Episode], rules: dict, pid: str) -> Promo:
    if not (2 <= len(m.segments) <= 3):
        raise Invalid("montage needs 2-3 segments")
    segs: list[Segment] = []
    excerpt: list[str] = []
    last_key = (-1, -1.0)
    total = 0.0
    hook_l = cliff_l = None
    for i, rs in enumerate(m.segments):
        ep_no = ep_of_id(rs.start_line)
        if ep_no not in eps:
            raise Invalid(f"episode {ep_no} not found")
        ep = eps[ep_no]
        idx = ep.by_id()
        first, last = _line(idx, rs.start_line, "start_line"), _line(idx, rs.end_line, "end_line")
        if last.ep != first.ep:
            raise Invalid("segment spans two episodes")
        hk = idx.get(m.hook_line)
        hook_here = hk if (i == 0 and hk is not None and first.idx <= hk.idx <= last.idx) else None
        if i == 0 and hook_here is None:
            raise Invalid("hook_line must be inside the first segment")
        if i == len(m.segments) - 1:
            cl = idx.get(m.cliffhanger_line)
            if cl is None or not (first.idx <= cl.idx <= last.idx):
                raise Invalid("cliffhanger_line must be inside the last segment")
            last = _cut_at_cliff(ep, cl, last, rules.get("react_s", 3.0))
            cliff_l = cl
        t0, t1 = snap_segment(ep, first, last, rules, hook=hook_here, enforce_hook=(i == 0))
        if i == 0 and (hook_here.start < t0 - 0.01 or hook_here.start - t0 > rules["hook_window_s"] + 1e-6):
            raise Invalid("hook does not start within the first 3 s of the montage")
        if t1 - t0 < 3.0:
            raise Invalid("each montage segment must be >= 3s")
        if (ep.num, t0) <= last_key:
            raise Invalid("segments must be in story order and not overlap")
        last_key = (ep.num, t1)
        total += t1 - t0
        segs.append(_mk_segment(ep, t0, t1))
        excerpt.append(f"--- segment {i + 1}: E{ep.num:02d} {fmt(t0)}-{fmt(t1)}")
        excerpt += _excerpt(ep, t0, t1)
        if i == 0:
            hook_l = hook_here
    if not (rules["min_len_s"] <= total <= rules["max_len_s"]):
        raise Invalid(f"total {total:.1f}s outside {rules['min_len_s']}-{rules['max_len_s']}s "
                      f"(segments: {', '.join(f'{s.end - s.start:.0f}s' for s in segs)}); shorten or drop a segment")
    return Promo(
        pid=pid, kind="montage", source="montage", segments=segs, duration=round(total, 2),
        hook=_text_of(hook_l), hook_line_id=hook_l.id, hook_type=m.hook_type,
        cliffhanger=_text_of(cliff_l), cliffhanger_line_id=cliff_l.id, cliffhanger_type=m.cliffhanger_type,
        open_question=m.open_question, why=m.why, excerpt=excerpt,
    )


def validate_many(cands, eps: dict[int, Episode], rules: dict, source: str, start_no: int = 1):
    """Return (promos, rejected). Never raises on bad candidates: they are logged with the reason and a fix hint."""
    ok: list[Promo] = []
    bad: list[Rejected] = []
    n = start_no
    for c in cands:
        try:
            ok.append(build_single(c, eps, rules, source, pid=f"P{n:03d}"))
            n += 1
        except Invalid as e:
            bad.append(Rejected(source=source, episode=c.episode, start_line=c.start_line, end_line=c.end_line,
                                hook_line=c.hook_line, cliffhanger_line=c.cliffhanger_line,
                                reason=str(e), hint=e.hint))
    return ok, bad
