"""Subtitle import (synthetic captions, not real show content)."""
from promofinder.subtitles import load_subtitles

SRT = """1
00:00:01,000 --> 00:00:04,000
Are you ready? The car is

2
00:00:03,000 --> 00:00:06,000
here. >> I can't marry him.

3
00:00:06,000 --> 00:00:09,000
>> You will, or your father dies.

4
00:00:09,500 --> 00:00:12,000
[music] Then I want the truth first.
"""


def test_rolling_captions_become_timed_sentences_with_turns(tmp_path):
    f = tmp_path / "show.srt"
    f.write_text(SRT, encoding="utf-8")
    eps = load_subtitles(f, part_seconds=999)
    lines = eps[0].lines
    texts = [l.text for l in lines]
    assert texts[:2] == ["Are you ready?", "The car is here."]
    assert "I can't marry him." in texts and "[music]" not in " ".join(texts)
    assert all(l.end > l.start for l in lines) and all(a.end <= b.start for a, b in zip(lines, lines[1:]))
    spk = {l.text: l.speaker for l in lines}
    assert spk["The car is here."] != spk["I can't marry him."]          # ">>" starts a new speaker turn
    assert lines[0].id == "E01_L001" and lines[0].start == 1.0           # absolute video time


def test_long_video_is_split_into_parts(tmp_path):
    cues = "".join(f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{(i + 1) // 60:02d}:{(i + 1) % 60:02d},000\n>> Line {i}.\n\n"
                   for i in range(1, 300, 2))
    f = tmp_path / "long.srt"
    f.write_text(cues, encoding="utf-8")
    eps = load_subtitles(f, max_seconds=240, part_seconds=60)
    assert len(eps) >= 3 and all(e.lines for e in eps)
    assert eps[1].lines[0].id == "E02_L001" and eps[1].lines[0].start > 55
