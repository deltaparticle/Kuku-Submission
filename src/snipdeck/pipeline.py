"""Orchestrates stages 0-7. Works with a real LLM, or with use_llm=False (rule-based baseline, zero API calls)."""
from __future__ import annotations

import time
from pathlib import Path

from . import stages as S
from .attention import attention
from .heuristics import propose
from .parse import Episode, load_show
from .schemas import Promo, Rejected
from .validate import validate_many


def _drop_overlapping(extra: list[Promo], base: list[Promo]) -> list[Promo]:
    out = []
    for p in extra:
        if not any(S._overlap(p, b) for b in base):
            out.append(p)
    return out


async def arun(eps: list[Episode], cfg: dict, llm=None, use_llm: bool = True, do_montage: bool = True,
        progress=lambda *_: None, show: str = "") -> dict:
    t0 = time.time()
    rules = dict(cfg["rules"])
    weights = cfg["weights"]
    em = {e.num: e for e in eps}
    n_eps = max((e.num for e in eps), default=1)
    rejected: list[Rejected] = []
    mrejected: list[Rejected] = []
    bible = None
    rank_ok = None
    spoiler_eps: set[int] = set()
    spoiler_info: dict = {}
    promos: list[Promo] = []

    # --- heuristic backstop (always runs: free) ---
    hper = rules.get("heuristic_per_episode", 1) if use_llm else 3
    hcands = [c for e in eps for c in propose(e, rules, per_episode=hper)]
    hpromos, hbad = validate_many(hcands, em, rules, "heuristic", start_no=1)
    rejected += hbad

    if use_llm:
        if llm is None:
            raise ValueError("use_llm=True needs an LLM client")
        progress("bible", 0, 1)
        bible = await S.make_bible(llm, eps, show)
        spoiler_eps, spoiler_info = await S.spoiler_episodes(llm, eps, show, bible, rules)
        progress("bible", 1, 1)
        lp, lbad = await S.generate_candidates(llm, eps, bible, rules, progress)
        rejected += lbad
        # backstop picks only where they add a new moment; re-number so ids are unique across sources
        lp += _drop_overlapping(hpromos, lp)
        for n, p in enumerate(lp, 1):
            p.pid = f"P{n:03d}"
        promos = lp
        for p in promos:
            p.attention = attention(em, p.segments)
        await S.score_promos(llm, promos, bible, rules, weights, progress)
        S.apply_spoiler_policy(promos, spoiler_eps, rules)  # before ranking, so the ranker sees the same flags
        promos.sort(key=lambda p: (-p.composite, p.pid))
        ranks, rank_ok = await S.listwise_rank(llm, promos, rules, progress)
        ordered = S.final_order(promos, ranks, rules, spoiler_eps, n_eps)
    else:
        promos = hpromos
        for p in promos:
            p.attention = attention(em, p.segments)
        mx = max((p.heur_score for p in promos), default=1.0) or 1.0
        for p in promos:
            p.composite = round(p.heur_score / mx, 4)
            p.score_note = "rule-based baseline (no LLM)"
        promos.sort(key=lambda p: (-p.composite, p.pid))
        ordered = S.final_order(promos, {}, {**rules, "final_llm_weight": 0.0}, set(), n_eps)

    # quality bar: a promo must have a hook the judge rates >= min_hook_score and must make sense on its own.
    # The list may be shorter than final_n: better 24 postable clips than 30 with filler.
    eligible = [p for p in ordered if S.passes_bar(p, rules, use_llm)]
    top = S.select_diverse(eligible, rules, rules["final_n"])
    for i, p in enumerate(top, 1):
        p.rank = i

    montages: list[Promo] = []
    if use_llm and do_montage and top:
        try:
            progress("montage", 0, 1)
            montages, mrejected = await S.build_montages(llm, eligible, eps, bible, rules, start_no=1,
                                                   spoiler_eps=spoiler_eps)
            for m in montages:
                m.attention = attention(em, m.segments)
            if montages:
                await S.score_promos(llm, montages, bible, {**rules, "score_batch": 25}, weights)
                S.apply_spoiler_policy(montages, spoiler_eps, rules)
                montages = S.final_order(montages, {}, rules, spoiler_eps, n_eps)
                for m in montages:
                    if not S.passes_bar(m, rules, True) or m.composite < rules.get("montage_min_composite", 0.0):
                        mrejected.append(Rejected(source="montage", reason=f"{m.pid} below the quality bar "
                                                  f"(hook {m.scores.get('hook_3s')}, composite {m.composite:.2f}, "
                                                  f"flags {[k for k, v in m.flags.items() if v]})",
                                                  start_line=m.segments[0].first_line, end_line=m.segments[-1].last_line))
                montages = [m for m in montages if S.passes_bar(m, rules, True)
                            and m.composite >= rules.get("montage_min_composite", 0.0)][: rules.get("montage_keep", 5)]
                for i, m in enumerate(montages, 1):
                    m.rank = i
            progress("montage", 1, 1)
        except (ValueError, RuntimeError) as e:  # montage is v2: never break the main result
            mrejected.append(Rejected(source="montage", reason=f"montage stage failed: {e}"))

    return {
        "promos": top,
        "montages": montages,
        "all_candidates": promos,
        "rejected": rejected + mrejected,
        "bible": bible,
        "run_log": {
            "mode": "llm" if use_llm else "rule-based baseline (no LLM)",
            "episodes": len(eps),
            "lines": sum(len(e.lines) for e in eps),
            "candidates_valid": len(promos),
            "candidates_rejected": len(rejected),
            "candidates_rejected_then_repaired": sum(1 for r in rejected if r.repaired),
            "montages_rejected": len(mrejected),
            "final_promos": len(top),
            "candidates_passing_quality_bar": len(eligible),
            "montages": len(montages),
            "rank_runs_ok": rank_ok,
            "late_payoff_episodes": sorted(spoiler_eps),
            "late_payoff_vote": spoiler_info,
            "seconds": round(time.time() - t0, 1),
            "llm": llm.summary() if llm else None,
            "stage_models": cfg["stages"] if use_llm else None,
        },
    }


def run(*a, **kw) -> dict:
    """Synchronous wrapper (CLI, Streamlit, tests). The browser app awaits arun() directly."""
    from .llm import run_sync
    return run_sync(arun(*a, **kw))


def run_folder(folder: str | Path, cfg: dict, **kw) -> dict:
    return run(load_show(folder), cfg, **kw)
