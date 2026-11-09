"""Step 7 of the pipeline: write a run's outputs (promos.md / .csv / .json, every candidate, the run log)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .schemas import Promo


def seg_str(p: Promo) -> str:
    return " + ".join(f"E{s.episode:02d} {s.start_ts}-{s.end_ts}" for s in p.segments)


def _scores(p: Promo) -> str:
    return ", ".join(f"{k}={v}" for k, v in p.scores.items()) or "n/a"


def _flags(p: Promo) -> str:
    return ", ".join(k for k, v in p.flags.items() if v) or "none"


def to_markdown(res: dict, show: str) -> str:
    log = res["run_log"]
    out = [f"# Promo picks — {show}", "",
           f"Mode: **{log['mode']}** · {log['episodes']} episodes · {log['lines']} screenplay lines · "
           f"{log['candidates_valid']} valid candidates, {log['candidates_rejected']} rejected · "
           f"final list: {log['final_promos']} promos"
           + (f" + {log['montages']} montages" if log['montages'] else ""), "",
           "Timestamps are screenplay times (mm:ss.ss) in the named episode. All times were computed by code "
           "from line IDs and snapped to safe cut points; none were written by the model.", ""]
    if res.get("show_summary") is not None:
        out += [f"**Premise (model-written):** {getattr(res['show_summary'], 'premise', '')}", ""]

    def card(p: Promo, label: str):
        out.append(f"## {label} — {p.pid} · {seg_str(p)} · {p.duration:.0f}s")
        out.append(f"- **Hook:** {p.hook}  _(type: {p.hook_type})_")
        out.append(f"- **Cliffhanger:** {p.cliffhanger}  _(type: {p.cliffhanger_type})_")
        if p.open_question:
            out.append(f"- **Open question:** {p.open_question}")
        out.append(f"- **Why it works:** {p.why or '—'}")
        out.append(f"- **Scores:** {_scores(p)} · composite {p.composite:.2f} · flags: {_flags(p)}")
        if p.attention:
            a = p.attention
            out.append(f"- **Attention (text proxy):** hook {a['hook_attention']:.2f} · hold {a['hold']:.2f} · "
                       f"first voice at {a['hook_features']['t_first_voice']:.1f}s"
                       + (f" · ⚠ {'; '.join(a['flags'])}" if a.get("flags") else ""))
        if p.rank_reason:
            out.append(f"- **Rank note:** {p.rank_reason}")
        if p.score_note and p.score_note != "none":
            out.append(f"- **Judge note:** {p.score_note}")
        out.append("")
        out.append("<details><summary>script</summary>\n\n```\n" + "\n".join(p.excerpt) + "\n```\n</details>\n")

    for p in res["promos"]:
        card(p, f"#{p.rank}")
    if res["montages"]:
        out += ["# Montage promos (v2: joined moments)", ""]
        for p in res["montages"]:
            card(p, f"M{p.rank}")
    return "\n".join(out)


def to_csv(res: dict) -> str:
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "type", "id", "segments", "duration_s", "hook", "hook_type", "cliffhanger",
                "cliffhanger_type", "open_question", "why", "composite", "scores", "flags", "rank_note",
                "hook_attention", "hold", "attention_flags"])
    for p in list(res["promos"]) + list(res["montages"]):
        w.writerow([("M" if p.kind == "montage" else "") + str(p.rank), p.kind, p.pid, seg_str(p), p.duration,
                    p.hook, p.hook_type, p.cliffhanger, p.cliffhanger_type, p.open_question, p.why,
                    f"{p.composite:.2f}", _scores(p), _flags(p), p.rank_reason,
                    p.attention.get("hook_attention", ""), p.attention.get("hold", ""),
                    "; ".join(p.attention.get("flags", []))])
    return buf.getvalue()


def payload(res: dict, show: str, episode_durations: dict | None = None) -> dict:
    """Everything the website needs, as one JSON-able dict."""
    dump = lambda objs: [o.model_dump() for o in objs]  # noqa: E731
    return {"show": show, "promos": dump(res["promos"]), "montages": dump(res["montages"]),
            "candidates": dump(res["all_candidates"]), "rejected": dump(res["rejected"]),
            "show_summary": res["show_summary"].model_dump() if res.get("show_summary") is not None else None,
            "run_log": json.loads(json.dumps(res["run_log"], default=str)),
            "episode_durations": episode_durations or {},
            "markdown": to_markdown(res, show), "csv": to_csv(res)}


def write_all(res: dict, out_dir: str | Path, show: str) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    dump = lambda objs: [o.model_dump() for o in objs]  # noqa: E731
    (d / "promos.json").write_text(json.dumps(
        {"show": show, "promos": dump(res["promos"]), "montages": dump(res["montages"])},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "candidates_all.json").write_text(json.dumps(
        {"valid": dump(res["all_candidates"]), "rejected": dump(res["rejected"])},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "run_log.json").write_text(json.dumps(res["run_log"], ensure_ascii=False, indent=2, default=str),
                                    encoding="utf-8")
    if res.get("show_summary") is not None:
        (d / "show_summary.json").write_text(json.dumps(res["show_summary"].model_dump(), ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    (d / "promos.md").write_text(to_markdown(res, show), encoding="utf-8")
    (d / "promos.csv").write_text(to_csv(res), encoding="utf-8-sig", newline="")
    return d
