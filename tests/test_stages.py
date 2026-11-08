"""Stage logic that needs no network: repair loop, bible-driven spoilers, ranking penalties, eval pass rate."""
from promofinder import stages as S
from promofinder.llm import run_sync
from promofinder.schemas import CandidateBatch, RawCandidate
from promofinder.stages import Bible


class RepairLLM:
    """First answer is too short; the repair answer uses a hook line that code suggested."""

    def __init__(self):
        self.users = []

    def json(self, stage, system, user, schema, **kw):
        self.users.append(user)
        if "HOW TO FIX" in user:
            return CandidateBatch(candidates=[RawCandidate(
                episode=1, start_line="E01_L006", end_line="E01_L013", hook_line="E01_L006",
                cliffhanger_line="E01_L013")])
        return CandidateBatch(candidates=[RawCandidate(
            episode=1, start_line="E01_L008", end_line="E01_L013", hook_line="E01_L008", cliffhanger_line="E01_L013")])


def test_repair_call_gets_code_hints_and_recovers_the_moment(eps, rules):
    llm = RepairLLM()
    promos, rejected = run_sync(S.generate_candidates(llm, eps[:1], Bible(), dict(rules, candidates_per_episode=1)))
    assert len(llm.users) == 2 and "E01_L007" in llm.users[1]      # the legal hook list reached the model
    assert len(promos) == 1 and promos[0].hook_line_id == "E01_L006"
    assert rejected and rejected[0].repaired and "too short" in rejected[0].reason


def test_late_payoff_episodes_from_structured_and_free_text_bible():
    b = Bible(late_payoffs=[{"what": "villain arrested", "episodes": [43, "44"]},
                            "Catherine stripped of status (Ep 47)", "affair exposed (Eps 49-50)"])
    assert S.late_payoff_episodes(b) == {43, 44, 47, 49, 50}
    assert S.late_payoff_episodes(None) == set()


def test_final_order_applies_bible_spoilers_and_prefers_early_episodes(eps, rules):
    from promofinder.validate import build_single
    em = {e.num: e for e in eps}
    c = dict(episode=1, start_line="E01_L002", end_line="E01_L013", hook_line="E01_L002", cliffhanger_line="E01_L013")
    a = build_single(RawCandidate(**c), em, rules, "llm", "P001")
    b = build_single(RawCandidate(**{**c, "episode": 2, "start_line": "E02_L002", "end_line": "E02_L013",
                                     "hook_line": "E02_L002", "cliffhanger_line": "E02_L013"}), em, rules, "llm", "P002")
    a.composite = b.composite = 0.8
    out = S.final_order([b, a], {}, rules, spoiler_eps={2}, n_episodes=2)
    assert out[0].pid == "P001"
    assert b.flags["spoiler_risk"] and "spoiler" in b.rank_reason
    # with no spoiler, the earlier episode still wins a tie
    a.flags, b.flags, b.rank_reason = {}, {}, ""
    out = S.final_order([b, a], {}, rules, set(), n_episodes=2)
    assert out[0].pid == "P001" and out[0].final > out[1].final


def test_eval_pass_rate_counts_promos_not_failures(eps):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
    from evaluate import rule_checks
    em = {e.num: e for e in eps}
    good = {"pid": "P1", "duration": 30, "hook_line_id": "E01_L002",
            "segments": [{"episode": 1, "start": 1.0, "end": 31.0}]}
    bad = {"pid": "P2", "duration": 90, "hook_line_id": "E01_L011",       # too long AND late hook: 2 failures
           "segments": [{"episode": 2, "start": 1.0, "end": 31.0}]}
    cfg = {"rules": {"min_len_s": 15, "max_len_s": 60, "hook_window_s": 3.0, "max_per_episode": 2}}
    r = rule_checks([good, bad], em, cfg)
    assert len(r["failures"]) >= 2 and r["promos_passing"] == 1 and r["pass_rate"] == 0.5


def test_montage_validator_joins_segments_across_episodes(eps, rules):
    import pytest
    from promofinder.schemas import RawMontage, RawSegment
    from promofinder.validate import Invalid, build_montage
    em = {e.num: e for e in eps}
    m = RawMontage(segments=[RawSegment(start_line="E01_L002", end_line="E01_L005"),
                             RawSegment(start_line="E02_L011", end_line="E02_L013")],
                   hook_line="E01_L002", cliffhanger_line="E02_L012")
    p = build_montage(m, em, dict(rules, min_len_s=10), "M001")
    assert [s.episode for s in p.segments] == [1, 2] and p.segments[1].end <= 28.5 + 1e-6  # cut at the cliffhanger
    with pytest.raises(Invalid, match="story order"):
        build_montage(RawMontage(segments=m.segments[::-1], hook_line="E02_L011", cliffhanger_line="E01_L005"),
                      em, dict(rules, min_len_s=10), "M002")


class VoteLLM:
    """Extra spoiler passes: one agrees on 41-44, the other adds a boundary episode 45."""
    def __init__(self):
        self.k = 0

    def json(self, stage, system, user, schema, **kw):
        self.k += 1
        eps = [41, 42, 43, 44] if self.k == 1 else [41, 42, 43, 44, 45]
        return schema(late_payoffs=[{"what": "villains fall", "episodes": eps}])


def test_spoiler_majority_vote_and_config_override(eps, rules):
    bible = Bible(late_payoffs=[{"what": "x", "episodes": [36, 41, 42, 43, 44]}])
    got, info = run_sync(S.spoiler_episodes(VoteLLM(), eps, "show", bible, dict(rules, spoiler_votes=3, late_payoff_episodes=None)))
    assert got == {41, 42, 43, 44} and "majority of 3" in info["source"]   # 36 and 45 named once: dropped
    got, info = run_sync(S.spoiler_episodes(VoteLLM(), eps, "show", bible, dict(rules, late_payoff_episodes=[7])))
    assert got == {7} and info["source"] == "config.yaml override"


def test_text_attention_proxy_reads_screenplay_signals(eps):
    from promofinder.attention import attention
    from promofinder.schemas import Segment
    em = {e.num: e for e in eps}
    seg = lambda a, b: Segment(episode=1, start=a, end=b, start_ts="", end_ts="", first_line="", last_line="")
    # opens on ANNA "You should leave." (voice at 1.0s, direct address) -> slap at 6s is outside the first 3 s
    a = attention(em, [seg(0.0, 30.4)])
    assert a["hook_features"]["t_first_voice"] == 1.0 and a["hook_features"]["direct_address_3s"]
    assert not a["hook_features"]["motion_3s"]
    # opening on the slap: motion inside the first 3 s, voice ("You will regret that!") at 2.0s -> stronger hook
    b = attention(em, [seg(6.0, 30.4)])
    assert b["hook_features"]["motion_3s"] and b["hook_features"]["vocal_intensity_3s"]
    assert b["hook_attention"] > a["hook_attention"]
    # a clip that opens on the long camera/SFX stretch has no voice for a while and is flagged
    c = attention(em, [seg(18.5, 33.0)])
    assert any("no voice" in f for f in c["flags"])


def test_spoiler_policy_trusts_the_vote_over_the_judge_flag(eps, rules):
    from promofinder.validate import build_single
    em = {e.num: e for e in eps}
    c = dict(episode=1, start_line="E01_L002", end_line="E01_L013", hook_line="E01_L002", cliffhanger_line="E01_L013")
    a = build_single(RawCandidate(**c), em, rules, "llm", "P001")
    a.flags = {"spoiler_risk": True}                    # judge thinks it is a spoiler (e.g. the title twist)
    S.apply_spoiler_policy([a], spoiler_eps={2}, rules=dict(rules, spoiler_source="vote"))
    assert a.flags["spoiler_risk"] is False and a.flags["judge_spoiler"] is True
    S.apply_spoiler_policy([a], spoiler_eps={2}, rules=dict(rules, spoiler_source="judge_or_vote"))
    assert a.flags["spoiler_risk"] is True
    S.apply_spoiler_policy([a], spoiler_eps={1}, rules=dict(rules, spoiler_source="vote"))
    assert a.flags["spoiler_risk"] is True and a.flags["late_payoff_episode"] is True
