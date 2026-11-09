"""Quality checks for one or more runs.

  python scripts/eval/evaluate.py --input "<episodes dir>" --run results/official-run-C [--run ...]
                                  [--gold gold.yaml] [--k 10]

1) RULE CHECKS (no labels needed) - every promo must satisfy the brief's hard constraints.
2) GOLD METRICS (optional: a gold.yaml of editor-picked spans, labelled before looking at model output).
   hit@k      a promo in the top k overlaps a gold span of that episode with temporal IoU >= 0.5
   hook-hit   that promo's hook text contains the gold hook phrase
   cliff-hit  that promo's cliffhanger text contains the gold cliffhanger phrase
   never@k    how many top-k promos land on a gold "never pick" span (lower is better)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from snipdeck.parse import load_show  # noqa: E402


def ts_to_s(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    m, s = str(x).split(":")
    return int(m) * 60 + float(s)


def iou(a0, a1, b0, b1) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union > 0 else 0.0


def rule_checks(promos: list[dict], eps: dict, cfg: dict) -> dict:
    r = cfg["rules"]
    fails: list[str] = []
    per_ep: dict[int, int] = {}
    failed: set[str] = set()
    for p in promos:
        pid = p["pid"]
        n_before = len(fails)
        if not (r["min_len_s"] - 1e-6 <= p["duration"] <= r["max_len_s"] + 1e-6):
            fails.append(f"{pid}: duration {p['duration']}s outside {r['min_len_s']}-{r['max_len_s']}")
        for k, s in enumerate(p["segments"]):
            ep = eps.get(s["episode"])
            if ep is None:
                fails.append(f"{pid}: unknown episode {s['episode']}")
                continue
            if not ep.cut_ok(s["start"]) or not ep.cut_ok(s["end"]):
                fails.append(f"{pid}: segment {k + 1} cuts inside a spoken line/SFX")
            if s["end"] > ep.duration + 0.5:
                fails.append(f"{pid}: segment {k + 1} runs past episode end")
            if p.get("kind", "single") != "montage":  # the cap is for single promos; montages reuse moments
                per_ep[s["episode"]] = per_ep.get(s["episode"], 0) + 1
        hook = eps[p["segments"][0]["episode"]].by_id().get(p["hook_line_id"])
        if hook is None:
            fails.append(f"{pid}: hook line id not found")
        elif hook.start - p["segments"][0]["start"] > r["hook_window_s"] + 1e-6:
            fails.append(f"{pid}: hook starts {hook.start - p['segments'][0]['start']:.1f}s after clip start")
        elif hook.start < p["segments"][0]["start"] - 0.01:
            fails.append(f"{pid}: hook starts before the clip")
        if len(fails) > n_before:
            failed.add(pid)
    singles = [p for p in promos if p.get("kind", "single") != "montage"]  # montages may reuse moments by design
    for i, a in enumerate(singles):
        for b in singles[i + 1:]:
            for s in a["segments"]:
                for t in b["segments"]:
                    if s["episode"] == t["episode"] and s["start"] < t["end"] and t["start"] < s["end"]:
                        fails.append(f"{a['pid']} overlaps {b['pid']} in ep {s['episode']}")
                        failed.update((a["pid"], b["pid"]))
    over = {e: n for e, n in per_ep.items() if n > r["max_per_episode"]}
    for e, n in over.items():
        fails.append(f"episode {e} has {n} promos (cap {r['max_per_episode']})")
    # pass_rate = share of promos with no failure at all (per-episode cap violations are show-level failures)
    return {"n": len(promos), "failures": fails, "promos_passing": len(promos) - len(failed),
            "pass_rate": (len(promos) - len(failed)) / max(1, len(promos))}


def gold_metrics(promos: list[dict], gold: dict, k: int) -> dict:
    topk = promos[:k]
    items = gold.get("promos", [])
    hit = hook_hit = cliff_hit = 0
    for g in items:
        g0, g1 = ts_to_s(g["start"]), ts_to_s(g["end"])
        match = None
        for p in topk:
            for s in p["segments"]:
                if s["episode"] == g["episode"] and iou(s["start"], s["end"], g0, g1) >= 0.5:
                    match = p
                    break
            if match:
                break
        if match:
            hit += 1
            if g.get("hook") and g["hook"].lower() in match["hook"].lower():
                hook_hit += 1
            if g.get("cliffhanger") and g["cliffhanger"].lower() in match["cliffhanger"].lower():
                cliff_hit += 1
    never = 0
    for n in gold.get("never", []):
        n0, n1 = ts_to_s(n["start"]), ts_to_s(n["end"])
        for p in topk:
            if any(s["episode"] == n["episode"] and iou(s["start"], s["end"], n0, n1) > 0.3 for s in p["segments"]):
                never += 1
    return {"gold_promos": len(items), f"hit@{k}": hit, "hook_hit": hook_hit, "cliff_hit": cliff_hit,
            f"never@{k}": never}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--run", action="append", required=True, help="run folder(s) containing promos.json")
    ap.add_argument("--gold", default=str(Path(__file__).with_name("gold.yaml")))
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[2] / "config.yaml"))
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    eps = {e.num: e for e in load_show(a.input)}
    gold = yaml.safe_load(Path(a.gold).read_text(encoding="utf-8")) if Path(a.gold).exists() else None
    if gold is None:
        print(f"(no gold file at {a.gold}: running rule checks only)\n")

    report = {}
    for run in a.run:
        data = json.loads((Path(run) / "promos.json").read_text(encoding="utf-8"))
        promos = data["promos"]
        rc = rule_checks(promos + data.get("montages", []), eps, cfg)
        row = {"rule_checks": {"promos": rc["n"], "pass_rate": round(rc["pass_rate"], 3),
                               "failures": rc["failures"][:10]}}
        if gold:
            row["gold"] = gold_metrics(promos, gold, a.k)
        report[str(run)] = row
        print(f"== {run}")
        print(json.dumps(row, indent=2, ensure_ascii=False))
    out = Path(a.run[0]) / "eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
