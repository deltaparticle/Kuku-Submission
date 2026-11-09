"""Attention check from the screenplay text, used as a small term in stages.final_order.

Video attention tools predict, from the video, whether the first seconds grab attention: faces in close-up, motion, cuts,
sound spikes, someone speaking straight away. A timestamped screenplay describes all of these, so they can be
measured from text without a model:

  CAMERA lines   -> shot changes (cuts) and shot size (close-up = a face filling the frame)
  ACTION lines   -> on-screen motion / physical impact
  SOUND FX lines -> sound spikes (crash, slap, gasp, sting)
  DIALOGUE lines -> time to the first voice, vocal intensity (emotion tag, "!"), direct address ("you", questions)

hook_attention (first 3 s) and hold (whole clip: dead air, pacing, speech coverage, ending beat) are 0-1 scores.
They are a second opinion next to the judge, not ground truth: the weights are set by hand from common findings
(faces, motion, sound and early speech catch attention) and are not fitted to real ad results.
"""
from __future__ import annotations

import re

from .heuristics import HOOK_WORDS, HOT_EMO
from .parse import Episode, Line

CLOSEUP = re.compile(r"\b(close-up|close up|closeup|extreme close|tight on|tight shot|on (?:her|his) face)\b", re.I)
MOTION = re.compile(r"\b(slap\w*|strik\w*|struck|shov\w*|grab\w*|yank\w*|drag\w*|slam\w*|lung\w*|rush\w*|burst\w*|"
                    r"crash\w*|collaps\w*|throw\w*|threw|hurl\w*|kick\w*|punch\w*|seiz\w*|wrench\w*|rip\w*|tear\w* (?:off|open)|"
                    r"stumbl\w*|fall\w*|falls|charg\w*|break\w*|smash\w*|shatter\w*|explod\w*|draw\w* (?:a|his|her) (?:sword|dagger|pistol)|"
                    r"violent\w*|forcefully|hoist\w*|pin\w* (?:her|him)|kneel\w*|sink\w* to)\b", re.I)
SOUND_SPIKE = re.compile(r"\b(crash\w*|slap\w*|gasp\w*|scream\w*|shout\w*|bang\w*|gunshot|shatter\w*|thud\w*|thump\w*|"
                         r"slam\w*|sting|explosion|explod\w*|clang\w*|snap\w*|splinter\w*|loud|sharp|sudden|violent\w*|"
                         r"swell\w*|roar\w*|gavel)\b", re.I)
ADDRESS = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
SOFT_SFX = re.compile(r"\b(rain|wind|ambient|birdsong|distant|soft|gentle|quiet|murmur\w*|rustl\w*|crackl\w*)\b", re.I)

WINDOW = 3.0


def _in(l: Line, t0: float, t1: float) -> bool:
    return l.end > t0 + 0.01 and l.start < t1 - 0.01


def _starts_in(l: Line, t0: float, t1: float) -> bool:
    return t0 - 0.01 <= l.start < t1


def hook_features(ep: Episode, t0: float, t1: float) -> dict:
    """What a viewer sees and hears in the first 3 seconds of a clip that starts at t0."""
    w1 = min(t1, t0 + WINDOW)
    lines = [l for l in ep.lines if _in(l, t0, w1)]
    dia = [l for l in lines if l.kind == "DIALOGUE"]
    first_voice = next((l.start for l in ep.lines if l.kind == "DIALOGUE" and l.end > t0 + 0.01), None)
    t_voice = max(0.0, first_voice - t0) if first_voice is not None else 99.0
    cams = [l for l in lines if l.kind == "CAMERA"]
    return {
        "t_first_voice": round(t_voice, 2),
        "cuts_3s": sum(1 for l in cams if _starts_in(l, t0 + 0.2, w1)),  # a new camera line = a new shot
        "closeup_3s": any(CLOSEUP.search(l.text) for l in cams),
        "motion_3s": any(MOTION.search(l.text) for l in lines if l.kind in ("ACTION", "CAMERA")),
        "sound_spike_3s": any(SOUND_SPIKE.search(l.text) and not SOFT_SFX.search(l.text)
                              for l in lines if l.kind == "SFX"),
        "vocal_intensity_3s": any("!" in l.text or HOT_EMO.search(l.emotion or "") for l in dia),
        "direct_address_3s": any(ADDRESS.search(l.text) or l.text.rstrip('"').endswith("?") for l in dia),
        "conflict_words_3s": any(HOOK_WORDS.search(l.text) for l in lines if l.kind != "CAMERA"),
    }


def hook_attention(f: dict) -> float:
    voice = 1.0 if f["t_first_voice"] <= 0.5 else max(0.0, 1 - (f["t_first_voice"] - 0.5) / 2.5)
    parts = [
        (0.22, voice),                                   # a voice in the first second is the strongest stop signal
        (0.14, float(f["vocal_intensity_3s"])),          # raised, emotional delivery
        (0.14, float(f["motion_3s"])),                   # physical action on screen
        (0.10, float(f["sound_spike_3s"])),              # sharp sound
        (0.10, float(f["closeup_3s"])),                  # a face filling the frame
        (0.10, min(1.0, f["cuts_3s"] / 2)),              # visual change (cuts)
        (0.10, float(f["direct_address_3s"])),           # "you" / a question pulls the viewer in
        (0.10, float(f["conflict_words_3s"])),           # stakes words (betray, marry, kill, Duke...)
    ]
    return round(sum(w * v for w, v in parts), 3)


def hold_features(ep: Episode, t0: float, t1: float) -> dict:
    """Whole-clip pacing: does something keep happening, and does it end on a strong beat?"""
    lines = [l for l in ep.lines if _in(l, t0, t1)]
    dur = max(0.1, t1 - t0)
    busy = sorted((max(t0, l.start), min(t1, l.end)) for l in lines if l.kind in ("DIALOGUE", "ACTION", "SFX"))
    gap, cur = 0.0, t0
    for a, b in busy:
        gap = max(gap, a - cur)
        cur = max(cur, b)
    gap = max(gap, t1 - cur)
    speech = 0.0
    for l in lines:
        if l.kind == "DIALOGUE":
            speech += min(t1, l.end) - max(t0, l.start)
    cuts = sum(1 for l in lines if l.kind == "CAMERA" and _starts_in(l, t0 + 0.2, t1))
    tail = [l for l in lines if l.end > t1 - 3.0]
    last_spoken = next((l for l in reversed(lines) if l.kind == "DIALOGUE"), None)
    return {
        "dead_air_s": round(gap, 2),                     # longest stretch with nothing said, done or heard
        "speech_share": round(min(1.0, speech / dur), 2),
        "cuts_per_10s": round(10 * cuts / dur, 2),
        "end_closeup": any(l.kind == "CAMERA" and CLOSEUP.search(l.text) for l in tail),
        "end_sting": any(l.kind == "SFX" and SOUND_SPIKE.search(l.text) for l in tail),
        "end_open_line": bool(last_spoken and re.search(r'(\?|\.\.\.|…|—|-)"?\s*$', last_spoken.text.strip())),
    }


def hold_score(f: dict) -> float:
    dead = 1.0 - min(1.0, max(0.0, f["dead_air_s"] - 2.0) / 4.0)       # >6 s of nothing = viewers swipe away
    pace = min(1.0, f["cuts_per_10s"] / 3.0)                           # ~3 shots per 10 s is typical drama pace
    talk = min(1.0, f["speech_share"] / 0.6)
    end = min(1.0, 0.5 * f["end_closeup"] + 0.4 * f["end_sting"] + 0.5 * f["end_open_line"])
    return round(0.35 * dead + 0.2 * pace + 0.2 * talk + 0.25 * end, 3)


def attention(ep_by_num: dict[int, Episode], segments) -> dict:
    """Attention profile of a promo (single or montage): hook from the first segment, hold over all segments."""
    s0 = segments[0]
    hf = hook_features(ep_by_num[s0.episode], s0.start, s0.end)
    holds = [hold_features(ep_by_num[s.episode], s.start, s.end) for s in segments]
    durs = [s.end - s.start for s in segments]
    hold = round(sum(hold_score(h) * d for h, d in zip(holds, durs)) / max(0.1, sum(durs)), 3)
    last = holds[-1]
    flags = []
    if hf["t_first_voice"] > 2.0:
        flags.append(f"no voice until {hf['t_first_voice']:.1f}s")
    if max(h["dead_air_s"] for h in holds) > 5.0:
        flags.append(f"{max(h['dead_air_s'] for h in holds):.0f}s of dead air")
    if not (last["end_closeup"] or last["end_sting"] or last["end_open_line"]):
        flags.append("flat final beat")
    return {"hook_attention": hook_attention(hf), "hold": hold, "hook_features": hf,
            "hold_features": holds if len(holds) > 1 else holds[0], "flags": flags}
