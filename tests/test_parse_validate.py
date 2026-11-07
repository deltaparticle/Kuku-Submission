import pytest

from promofinder.schemas import RawCandidate
from promofinder.validate import Invalid, build_single


def cand(**kw):
    base = dict(episode=1, start_line="E01_L002", end_line="E01_L013", hook_line="E01_L002",
                cliffhanger_line="E01_L013", why="t")
    base.update(kw)
    return RawCandidate(**base)


def test_parse_counts_and_kinds(eps):
    assert len(eps) == 2
    e = eps[0]
    assert e.num == 1 and len(e.lines) == 14
    assert e.lines[0].id == "E01_L001" and e.lines[0].kind == "CAMERA"
    assert {l.kind for l in e.lines} == {"CAMERA", "DIALOGUE", "ACTION", "SFX"}
    assert e.lines[1].speaker == "ANNA" and e.lines[1].emotion == "Cold"
    assert e.duration == 33.0


def test_cut_points(eps):
    e = eps[0]
    assert not e.cut_ok(2.0)   # inside ANNA's 1.0-3.0 line
    assert e.cut_ok(3.2)       # gap between lines
    assert not e.cut_ok(21.0)  # inside SFX 20-23


def test_valid_candidate_snaps_to_real_times(eps, rules):
    em = {e.num: e for e in eps}
    p = build_single(cand(), em, rules, "llm", "P001")
    s = p.segments[0]
    assert 15 <= p.duration <= 60
    assert s.start == 1.0                      # starts at the hook line, not at the CAMERA line
    assert eps[0].cut_ok(s.start) and eps[0].cut_ok(s.end)
    assert s.end >= 28.5 + 1.5 - 0.01 + 0  # includes the last line


def test_hallucinated_id_rejected(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid, match="does not exist"):
        build_single(cand(end_line="E01_L999", cliffhanger_line="E01_L999"), em, rules, "llm", "P001")


def test_wrong_episode_line_rejected(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid):
        build_single(cand(end_line="E02_L013", cliffhanger_line="E02_L013"), em, rules, "llm", "P001")


def test_order_violation_rejected(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid, match="start <= hook"):
        build_single(cand(hook_line="E01_L013", cliffhanger_line="E01_L005"), em, rules, "llm", "P001")


def test_too_short_rejected(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid, match="too short"):
        build_single(cand(start_line="E01_L003", end_line="E01_L005", hook_line="E01_L003",
                          cliffhanger_line="E01_L005"), em, rules, "llm", "P001")


def test_late_hook_is_snapped_so_hook_is_in_first_3s(eps, rules):
    em = {e.num: e for e in eps}
    # LLM says clip starts at line 1 but the real hook (slap, L004 at 6.0s) is late
    p = build_single(cand(start_line="E01_L001", hook_line="E01_L004", cliffhanger_line="E01_L013",
                          end_line="E01_L013"), em, rules, "llm", "P001")
    s = p.segments[0]
    assert 6.0 - s.start <= rules["hook_window_s"] + 1e-6


def test_clip_never_runs_into_the_answer(eps, rules):
    em = {e.num: e for e in eps}
    # open question is answered by L014 ("Thank you, it is over now", starts 31.0)
    p = build_single(cand(end_line="E01_L014", cliffhanger_line="E01_L013", answered_at_line="E01_L014"),
                     em, rules, "llm", "P001")
    assert p.segments[0].end <= 31.0 + 1e-6


def test_too_long_is_rejected_with_legal_hooks_and_hook_is_never_replaced(eps, rules):
    em = {e.num: e for e in eps}
    r = dict(rules, max_len_s=20)
    with pytest.raises(Invalid, match="too long") as ei:
        build_single(cand(), em, r, "llm", "P001")
    # code lists hook lines that fit before this cliffhanger (BEN's "Who told you?" at 14.5s gives ~16s)
    assert "E01_L007" in ei.value.hint


def test_too_short_is_rejected_with_earlier_hook_suggestions(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid, match="too short") as ei:
        build_single(cand(start_line="E01_L008", hook_line="E01_L008"), em, rules, "llm", "P001")
    assert "E01_L007" in ei.value.hint and "open on one of these hook lines" in ei.value.hint


def test_unfixable_clip_is_still_rejected(eps, rules):
    em = {e.num: e for e in eps}
    r = dict(rules, min_len_s=40)                  # fixture episode is only 33s long: cannot reach 40s
    with pytest.raises(Invalid, match="too short") as ei:
        build_single(cand(), em, r, "llm", "P001")
    assert "choose a different moment" in ei.value.hint


def test_camera_line_cannot_be_the_hook(eps, rules):
    em = {e.num: e for e in eps}
    with pytest.raises(Invalid, match="CAMERA"):
        build_single(cand(start_line="E01_L001", hook_line="E01_L001"), em, rules, "llm", "P001")


def test_clip_ends_on_the_cliffhanger_not_on_later_dialogue(eps, rules):
    em = {e.num: e for e in eps}
    # model says the cliffhanger is BEN "No... you died!" (L012) but lets the clip run on to L014
    p = build_single(cand(cliffhanger_line="E01_L012", end_line="E01_L014"), em, rules, "llm", "P001")
    assert p.segments[0].end <= 28.5 + 1e-6          # stops before STRANGER's reply "Not yet." (L013, 28.5s)
    assert p.hook_line_id == "E01_L002" and p.cliffhanger_line_id == "E01_L012"


def test_episode_ids_with_three_digits():
    from promofinder.validate import ep_of_id
    assert ep_of_id("E100_L001") == 100 and ep_of_id("E07_L012") == 7
    with pytest.raises(Invalid):
        ep_of_id("E7-12")
