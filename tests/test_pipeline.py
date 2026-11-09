import json
import yaml
from pathlib import Path

from fake_llm import FakeLLM
from snipdeck.export import write_all
from snipdeck.pipeline import run

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))


def _cfg(rules):
    c = dict(CFG)
    c["rules"] = rules
    return c


def test_baseline_no_llm_runs_and_respects_rules(eps, rules):
    res = run(eps, _cfg(rules), llm=None, use_llm=False)
    assert res["promos"], "baseline should find something in the synthetic episodes"
    for p in res["promos"]:
        assert rules["min_len_s"] <= p.duration <= rules["max_len_s"]
        assert p.rank is not None


def test_full_pipeline_with_fake_llm(eps, rules, tmp_path):
    fake = FakeLLM(eps, rules)
    res = run(eps, _cfg(rules), llm=fake, use_llm=True)
    assert {"summary", "candidates", "score", "rank", "montage"} <= set(fake.calls)
    ranks = [p.rank for p in res["promos"]]
    assert ranks == list(range(1, len(ranks) + 1))
    # per-episode cap
    from collections import Counter
    per_ep = Counter(s.episode for p in res["promos"] for s in p.segments)
    assert max(per_ep.values()) <= rules["max_per_episode"]
    # no two promos overlap in time
    for i, a in enumerate(res["promos"]):
        for b in res["promos"][i + 1:]:
            for s in a.segments:
                for t in b.segments:
                    assert not (s.episode == t.episode and s.start < t.end and t.start < s.end)
    # the flagged (ad policy) promo is penalised in its rank note
    assert any("pushed down" in p.rank_reason for p in res["all_candidates"])

    out = write_all(res, tmp_path / "out", "synthetic")
    for name in ("promos.json", "promos.md", "promos.csv", "candidates_all.json", "run_log.json"):
        assert (out / name).exists()
    data = json.loads((out / "promos.json").read_text(encoding="utf-8"))
    assert data["promos"][0]["segments"][0]["start_ts"]
