"""Synthetic fixture (not Kuku content) in the same screenplay format, so tests need no confidential data."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from snipdeck.parse import load_show  # noqa: E402


def _ts(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def make_episode(num: int, beats: list[tuple]) -> str:
    """beats: (kind, speaker_or_None, emotion, text, start, end)"""
    out = [f"EPISODE NUMBER: Episode {num}", f"EPISODE LOGLINE: Test episode {num}.",
           "CONTINUITY NOTES: synthetic.", "", "--- SCRIPT START ---", "", "SCENE 01",
           "Scene heading: INT. TEST ROOM – DAY", "Scene start: 00:00.00", "Scene end: 01:00.00", "",
           "Actions and dialogue:", ""]
    for kind, spk, emo, text, a, b in beats:
        if kind == "DIALOGUE":
            out.append(f"**{spk} ({emo}):**")
        else:
            out.append(f"**{kind}:**")
        out.append(f"Start: ({_ts(a)}) | End: ({_ts(b)})")
        out.append(text if kind != "DIALOGUE" else f'"{text}"')
        out.append("")
    out.append("--- SCRIPT END ---")
    return "\n".join(out)


BEATS = [
    ("CAMERA", None, None, "Wide shot of a quiet hall.", 0.0, 3.0),
    ("DIALOGUE", "ANNA", "Cold", "You should leave.", 1.0, 3.0),
    ("DIALOGUE", "BEN", "Shaken", "Why? What did I do?", 3.5, 5.5),
    ("ACTION", None, None, "Anna slaps Ben across the face.", 6.0, 7.5),
    ("DIALOGUE", "BEN", "Furious", "You will regret that!", 8.0, 10.0),
    ("DIALOGUE", "ANNA", "Mocking", "Everyone knows you were never the Duke.", 10.5, 14.0),
    ("DIALOGUE", "BEN", "Stunned", "Who told you?", 14.5, 16.0),
    ("DIALOGUE", "ANNA", "Cruel", "The man behind you.", 16.5, 18.5),
    ("CAMERA", None, None, "Close-up on a figure stepping out of shadow.", 18.5, 22.0),
    ("SOUND FX", None, None, "A low string sting rises.", 20.0, 23.0),
    ("DIALOGUE", "STRANGER", "Menacing", "Hello, brother.", 23.5, 25.5),
    ("DIALOGUE", "BEN", "Horrified", "No... you died!", 26.0, 28.0),
    ("DIALOGUE", "STRANGER", "Cold", "Not yet.", 28.5, 30.0),
    ("DIALOGUE", "ANNA", "Relieved", "Thank you, it is over now.", 31.0, 33.0),
]


@pytest.fixture()
def show_dir(tmp_path):
    for n in (1, 2):
        (tmp_path / f"episode-{n:03d}.txt").write_text(make_episode(n, BEATS), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def eps(show_dir):
    return load_show(show_dir)


@pytest.fixture()
def rules():
    import yaml
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))
    r = dict(cfg["rules"])
    r["min_len_s"] = 15  # fixture episodes are short; real default (20) is exercised in the pack run
    return r
