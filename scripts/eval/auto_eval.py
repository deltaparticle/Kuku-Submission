"""No-human quality checks (used because there is no hand-labelled gold set).

  python scripts/eval/auto_eval.py --input "<episodes dir>" --run results/official-run-C \
        --baseline outputs/<show>/baseline-test [--prev outputs/<show>/llm-run-1] [--no-judge]

What it measures (all automatic, none of it replaces a human editor):
  1. RULES      hard constraints from the brief, re-checked on the saved output.
  2. AGREEMENT  how much the picks of different runs overlap (temporal IoU >= 0.5, same episode).
                Two independent LLM runs agreeing on a moment is a consistency signal; agreeing with the
                rule-based baseline is a (weak) sanity signal.
  3. BLIND A/B  for every episode where pipeline and baseline chose DIFFERENT moments, a judge model sees both
                clips (order randomised, then swapped). The pipeline only "wins" if it wins in BOTH orders.
                Caveat: judge and proposer are both Gemini-family models, so self-preference is possible.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaluate import iou, rule_checks  # noqa: E402
from snipdeck.llm import LLM, load_config  # noqa: E402
from snipdeck.parse import load_show  # noqa: E402


class PairJ(BaseModel):
    id: int
    winner: str  # "A" | "B" | "tie"
    reason: str = ""


class PairBatch(BaseModel):
    judgments: list[PairJ] = []


JUDGE_SYSTEM = """You are an experienced editor of promo clips for vertical microdrama apps (ReelShort/DramaBox style),
choosing which clip to post as a paid ad on TikTok/Reels/Shorts to viewers who have NEVER seen the show.
A good promo (1) HOOKS in the first 3 seconds (slap, reveal, shocking line), (2) ENDS on an unresolved cliffhanger
that makes the viewer need the next part, and (3) makes sense to a stranger without earlier episodes.
For each numbered pair, read clip A and clip B (screenplay lines with times) and pick the better promo.
Say "tie" only if you truly cannot separate them. Be decisive: judge hook, cliffhanger and clarity, not length.
Return ONLY JSON: {"judgments": [{"id": 1, "winner": "A", "reason": "<=20 words"}, ...]} covering every pair id."""


def load_run(d: Path) -> dict:
    p = json.loads((d / "promos.json").read_text(encoding="utf-8"))
    c = json.loads((d / "candidates_all.json").read_text(encoding="utf-8"))
    return {"promos": p["promos"], "montages": p.get("montages", []), "valid": c["valid"]}


def seg0(p):
    s = p["segments"][0]
    return s["episode"], s["start"], s["end"]


def same_moment(a, b, thr=0.5) -> bool:
    ea, a0, a1 = seg0(a)
    eb, b0, b1 = seg0(b)
    return ea == eb and iou(a0, a1, b0, b1) >= thr


def agreement(a_list, b_list) -> dict:
    hit = sum(1 for a in a_list if any(same_moment(a, b) for b in b_list))
    eps_a = {seg0(a)[0] for a in a_list}
    eps_b = {seg0(b)[0] for b in b_list}
    return {"promos_in_A": len(a_list), "A_found_in_B": hit,
            "share": round(hit / max(1, len(a_list)), 3),
            "episodes_A": len(eps_a), "episodes_B": len(eps_b), "episodes_in_both": len(eps_a & eps_b)}


def clean_excerpt(p) -> str:
    # strip line IDs so nothing but the script itself is shown to the judge
    return "\n".join(re.sub(r"^E\d+_L\d+ ", "", l) for l in p["excerpt"])


def run_blind_ab(llm, pipe: dict, base: dict, seed: int = 11, batch: int = 8) -> dict:
    rng = random.Random(seed)
    base_by_ep: dict[int, list] = {}
    for b in sorted(base["valid"], key=lambda x: -x["composite"]):
        base_by_ep.setdefault(seg0(b)[0], []).append(b)
    pairs, same = [], 0
    for p in pipe["promos"]:
        cands = base_by_ep.get(seg0(p)[0], [])
        if not cands:
            continue
        if same_moment(p, cands[0]):
            same += 1  # both chose the same moment: nothing to judge
            continue
        pairs.append((p, cands[0]))
    results = []  # per pair: outcome from 2 orders
    for i in range(0, len(pairs), batch):
        chunk = pairs[i:i + batch]
        flips = [rng.random() < 0.5 for _ in chunk]  # True => pipeline shown as B in order 1
        outs = []
        for order in (0, 1):
            blocks = []
            for k, ((p, b), flip) in enumerate(zip(chunk, flips), 1):
                pipe_is_b = flip if order == 0 else not flip
                a_clip, b_clip = (b, p) if pipe_is_b else (p, b)
                blocks.append(f"### PAIR {k}\n--- clip A ({a_clip['duration']:.0f}s)\n{clean_excerpt(a_clip)}\n"
                              f"--- clip B ({b_clip['duration']:.0f}s)\n{clean_excerpt(b_clip)}")
            res = llm.json("eval_judge", JUDGE_SYSTEM, "\n\n".join(blocks), PairBatch)
            got = {j.id: j for j in res.judgments}
            m = {}
            for k, flip in enumerate(flips, 1):
                pipe_is_b = flip if order == 0 else not flip
                j = got.get(k)
                if j is None or j.winner not in ("A", "B"):
                    m[k] = "tie"
                else:
                    m[k] = "pipeline" if ((j.winner == "B") == pipe_is_b) else "baseline"
            outs.append(m)
        for k, (p, b) in enumerate(chunk, 1):
            o1, o2 = outs[0][k], outs[1][k]
            final = o1 if o1 == o2 else "tie"
            results.append({"episode": seg0(p)[0], "pipeline": f"{seg0(p)[1]:.1f}-{seg0(p)[2]:.1f}",
                            "baseline": f"{seg0(b)[1]:.1f}-{seg0(b)[2]:.1f}", "order1": o1, "order2": o2,
                            "result": final})
    cnt = {k: sum(1 for r in results if r["result"] == k) for k in ("pipeline", "baseline", "tie")}
    consistent = sum(1 for r in results if r["order1"] == r["order2"])
    return {"episodes_where_both_chose_same_moment": same, "pairs_judged": len(results), **cnt,
            "judge_consistent_in_both_orders": consistent, "details": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--prev", default=None)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    eps = {e.num: e for e in load_show(a.input)}
    run, base = load_run(Path(a.run)), load_run(Path(a.baseline))
    prev = load_run(Path(a.prev)) if a.prev else None

    report: dict = {"run": a.run}
    rc = rule_checks(run["promos"] + run["montages"], eps, cfg)
    report["rules"] = {"promos_checked": rc["n"], "pass_rate": round(rc["pass_rate"], 3), "failures": rc["failures"]}
    rb = rule_checks(base["promos"], eps, cfg)
    report["rules_baseline"] = {"promos_checked": rb["n"], "pass_rate": round(rb["pass_rate"], 3)}
    report["agreement_pipeline_vs_baseline"] = agreement(run["promos"], base["promos"])
    if prev:
        report["agreement_run2_vs_run1"] = agreement(run["promos"], prev["promos"])
        report["agreement_run1_vs_run2"] = agreement(prev["promos"], run["promos"])
    if not a.no_judge:
        llm = LLM(load_config(a.config), cache_dir=ROOT / ".cache")
        report["blind_ab_pipeline_vs_baseline"] = run_blind_ab(llm, run, base)
        report["judge_models_used"] = llm.summary()["by_stage"].get("eval_judge", {}).get("models_used")

    out = Path(a.run)
    (out / "auto_eval.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "blind_ab_pipeline_vs_baseline"}, indent=2))
    ab = report.get("blind_ab_pipeline_vs_baseline")
    if ab:
        print("\nBLIND A/B:", {k: ab[k] for k in ab if k != "details"})
    print(f"\nSaved {out / 'auto_eval.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
