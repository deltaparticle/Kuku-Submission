"""The model-driven steps of the pipeline, in the order pipeline.py calls them:

    2 show summary      make_summary, spoiler_episodes
    3 candidates        generate_candidates (validation lives in validate.py)
    5 score and rank    score_promos, listwise_rank, apply_spoiler_policy, final_order, passes_bar, select_diverse
    6 montages          build_montages

The model proposes and judges; code validates, combines scores and selects."""
from __future__ import annotations

import asyncio
import json
import random
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .parse import Episode
from .schemas import (CandidateBatch, MontageBatch, Promo, RankResult, Rejected, ScoreBatch)
from .validate import Invalid, build_montage, validate_many

PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class ShowSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    premise: str = ""


def summary_text(b: ShowSummary | dict | None) -> str:
    if b is None:
        return "(no summary)"
    d = b.model_dump() if isinstance(b, BaseModel) else b
    return json.dumps(d, ensure_ascii=False, indent=1)


async def _ask(llm, *a, **k):
    """Async model call; also accepts simple synchronous test doubles that only implement .json()."""
    if hasattr(llm, "ajson"):
        return await llm.ajson(*a, **k)
    return llm.json(*a, **k)


async def _gather(coros: list, progress, stage: str) -> list:
    """Run calls concurrently (llm.py enforces per-provider limits). Results come back in input order, so a run
    is reproducible whichever call finishes first."""
    total, done = len(coros), 0
    progress(stage, 0, total)

    async def one(c):
        nonlocal done
        r = await c
        done += 1
        progress(stage, done, total)
        return r

    return list(await asyncio.gather(*(one(c) for c in coros)))


# 2. Show summary

def _summary_user(eps: list[Episode], show: str = "") -> str:
    spk = Counter(l.speaker for e in eps for l in e.lines if l.speaker)
    lines = [f"Ep {e.num}: {e.logline}\n   continuity: {e.continuity}" for e in eps]
    return ((f"SHOW TITLE: {show}\n\n" if show else "")
            + "SPEAKER LABELS (label: line count): " + ", ".join(f"{k}: {v}" for k, v in spk.most_common())
            + "\n\nEPISODES:\n" + "\n".join(lines))


async def make_summary(llm, eps: list[Episode], show: str = "") -> ShowSummary:
    return await _ask(llm, "summary", prompt("summary"), _summary_user(eps, show), ShowSummary)


class _Payoffs(BaseModel):
    model_config = ConfigDict(extra="allow")
    late_payoffs: list = []


async def spoiler_episodes(llm, eps: list[Episode], show: str, summary: ShowSummary,
                           rules: dict) -> tuple[set[int], dict]:
    """Episodes treated as spoilers (late-show payoffs), made stable across runs.

    1. rules.late_payoff_episodes (a list in config.yaml) overrides everything: an editor's call per show.
    2. Otherwise majority vote: the main summary plus (spoiler_votes - 1) short passes that only list late payoffs.
       An episode counts if more than half of the passes name it, so episodes that only one pass adds don't
       change between runs."""
    fixed = rules.get("late_payoff_episodes")
    if isinstance(fixed, list):
        return {int(e) for e in fixed}, {"source": "config.yaml override"}
    votes: Counter = Counter(late_payoff_episodes(summary))
    passes = max(1, int(rules.get("spoiler_votes", 1)))
    ask = ("List ONLY the late payoffs for this show, as JSON: "
           '{"late_payoffs": [{"what": "...", "episodes": [n, ...]}]}. Use the definition of late payoffs in the '
           "rules (resolutions that would spoil the show; never the title twist). Give only the episodes where each "
           "one actually plays out on screen.\n\n")

    async def one(k):
        try:
            return await _ask(llm, "summary", prompt("summary"), f"[spoiler check {k}] " + ask + _summary_user(eps, show),
                              _Payoffs, temperature=float(rules.get("spoiler_vote_temperature", 0.5)))
        except (ValueError, RuntimeError):
            return None

    extra = await asyncio.gather(*(one(k) for k in range(1, passes)))
    done = 1
    for b in extra:
        if b is not None:
            votes.update(late_payoff_episodes(b.model_dump()))
            done += 1
    need = done // 2 + 1
    return ({e for e, c in votes.items() if c >= need},
            {"source": f"majority of {done} passes (>= {need})", "votes": {str(e): c for e, c in sorted(votes.items())}})


RE_EPS = re.compile(r"\bEp(?:isode)?s?\.?\s*(\d+)(?:\s*(?:-|–|to|and|&)\s*(\d+))?", re.I)


def late_payoff_episodes(summary: ShowSummary | dict | None) -> set[int]:
    """Episodes the summary lists as late-show payoffs (spoilers for a new viewer)."""
    if summary is None:
        return set()
    d = summary.model_dump() if isinstance(summary, BaseModel) else summary
    out: set[int] = set()
    for item in d.get("late_payoffs") or []:
        if isinstance(item, dict):
            for e in item.get("episodes") or []:
                try:
                    out.add(int(e))
                except (TypeError, ValueError):
                    pass
            item = item.get("what", "")
        for m in RE_EPS.finditer(str(item)):
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else a
            out.update(range(min(a, b), max(a, b) + 1))
    return out


# 3. Candidates

def _batches(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _same_moment(a: Promo, b: Promo, thr: float = 0.5) -> bool:
    s, t = a.segments[0], b.segments[0]
    if s.episode != t.episode:
        return False
    inter = max(0.0, min(s.end, t.end) - max(s.start, t.start))
    union = (s.end - s.start) + (t.end - t.start) - inter
    return union > 0 and inter / union >= thr


def _repair_note(bad: list[Rejected]) -> str:
    rows = []
    for b in bad:
        rows.append(f"- proposal hook {b.hook_line} -> cliffhanger {b.cliffhanger_line} "
                    f"(start {b.start_line}, end {b.end_line}): REJECTED: {b.reason}"
                    + (f"\n  HOW TO FIX: {b.hint}" if b.hint else ""))
    return "\n".join(rows)


async def generate_candidates(llm, eps: list[Episode], summary: ShowSummary, rules: dict, progress=lambda *_: None,
                              repair: bool = True) -> tuple[list[Promo], list[Rejected]]:
    em = {e.num: e for e in eps}
    bt = summary_text(summary)
    want = int(rules.get("candidates_per_episode", 3))
    batches = list(_batches(eps, rules["episodes_per_batch"]))

    async def one(batch) -> tuple[list[Promo], list[Rejected]]:
        user = "SHOW SUMMARY:\n" + bt + "\n\nEPISODES:\n" + "\n\n".join(e.compact() for e in batch)
        try:
            res = await _ask(llm, "candidates", prompt("candidates"), user, CandidateBatch)
        except (ValueError, RuntimeError) as e:  # a failed episode is logged as a rejection; the run continues
            nums = [x.num for x in batch]
            return [], [Rejected(source="llm", episode=nums[0],
                                 reason=f"candidate batch for episodes {nums} failed after retries: {str(e)[:160]}")]
        ok, bad = validate_many(res.candidates, em, rules, "llm")
        ok = [p for i, p in enumerate(ok) if not any(_same_moment(p, q) for q in ok[:i])]
        if not (repair and (bad or len(ok) < want * len(batch))):
            return ok, bad
        kept = "\n".join(f"- {p.hook_line_id} -> {p.cliffhanger_line_id} (episode {p.segments[0].episode})"
                         for p in ok) or "- none"
        user2 = user + (
            "\n\nYour previous proposals were checked by code."
            "\nACCEPTED (do not repeat these moments):\n" + kept +
            ("\nREJECTED (fix each one using the line IDs suggested under HOW TO FIX, which code has already "
             "checked for length; keep the same moment when possible):\n" + _repair_note(bad) if bad else "") +
            f"\nReturn ONLY the corrected proposals plus new distinct moments so that the episode ends up with "
            f"{want} accepted candidates in total. Do not repeat accepted ones.")
        try:
            res2 = await _ask(llm, "candidates", prompt("candidates"), user2, CandidateBatch, max_retries=0)
        except (ValueError, RuntimeError):
            return ok, bad
        ok2, bad2 = validate_many(res2.candidates, em, rules, "llm")
        ok2 = [p for i, p in enumerate(ok2) if not any(_same_moment(p, q) for q in ok + ok2[:i])]
        for b in bad + bad2:
            b.repaired = True
        return ok + ok2, bad + bad2

    results = await _gather([one(b) for b in batches], progress, "candidates")
    promos = [p for ok, _ in results for p in ok]
    rejected = [r for _, bad in results for r in bad]
    for i, p in enumerate(promos, 1):
        p.pid = f"P{i:03d}"
    return promos, rejected


# 5. Score, rank and select

def _score_block(p: Promo) -> str:
    segs = "; ".join(f"E{s.episode:02d} {s.start_ts}-{s.end_ts}" for s in p.segments)
    return (f"### {p.pid} | {segs} | {p.duration:.0f}s | proposed hook: {p.hook_line_id} | "
            f"proposed ending: {p.cliffhanger_line_id}\n" + "\n".join(p.excerpt))


def composite(scores: dict[str, int], weights: dict[str, float]) -> float:
    tot = sum(weights.values())
    return round(sum(w * (scores.get(k, 1) - 1) / 4 for k, w in weights.items()) / tot, 4)


SCORE_KEYS = ("hook_3s", "standalone", "cliffhanger", "intensity", "plot_relevance", "trope_fit")
FLAG_KEYS = ("spoiler_risk", "ad_policy_risk", "needs_context")


async def score_promos(llm, promos: list[Promo], summary: ShowSummary, rules: dict, weights: dict,
                       progress=lambda *_: None) -> None:
    """Judge scores. With score_passes > 1, every clip is scored again inside a differently shuffled batch and
    the scores are averaged: a clip's score then depends less on which other clips shared its batch."""
    bt = summary_text(summary)
    passes = max(1, int(rules.get("score_passes", 1)))
    acc: dict[str, list] = {p.pid: [] for p in promos}
    plan = []
    for k in range(passes):
        order = promos[:]
        if k:
            random.Random(rules.get("seed", 7) + k).shuffle(order)
        plan += list(_batches(order, rules["score_batch"]))

    async def one(batch):
        user = "SHOW SUMMARY:\n" + bt + "\n\nCLIPS:\n" + "\n\n".join(_score_block(p) for p in batch)
        try:
            return batch, await _ask(llm, "score", prompt("score"), user, ScoreBatch)
        except (ValueError, RuntimeError):
            return batch, None

    for batch, res in await _gather([one(b) for b in plan], progress, "score"):
        if res is None:
            continue
        ids = {p.pid for p in batch}
        for sc in res.scores:
            if sc.id in ids and sc.id in acc:
                acc[sc.id].append(sc)
    for p in promos:
        got = acc[p.pid]
        if not got:  # a clip the judge skipped gets 0 and a note
            p.score_note = "not scored by judge (model error or omitted)"
            p.composite = 0.0
            continue
        p.scores = {k: round(sum(getattr(sc, k) for sc in got) / len(got), 2) for k in SCORE_KEYS}
        p.flags = {k: any(getattr(sc, k) for sc in got) for k in FLAG_KEYS}
        p.score_note = " / ".join(dict.fromkeys(sc.note for sc in got if sc.note and sc.note.lower() != "none")) or "none"
        p.composite = composite(p.scores, weights)


def _rank_block(p: Promo) -> str:
    sc = ", ".join(f"{k}={v}" for k, v in p.scores.items())
    fl = ",".join(k for k, v in p.flags.items() if v) or "none"
    ep = p.segments[0].episode
    return (f"{p.pid} | ep {ep} | {p.duration:.0f}s | hook: {p.hook} | ends: {p.cliffhanger} | "
            f"open question: {p.open_question} | scores: {sc} | flags: {fl}")


async def listwise_rank(llm, promos: list[Promo], rules: dict,
                        progress=lambda *_: None) -> tuple[dict[str, dict], int]:
    """Run the LLM ranking several times in shuffled order and aggregate by Borda count."""
    pool = promos[: rules["top_n_for_ranking"]]
    ids = [p.pid for p in pool]
    by = {p.pid: p for p in pool}
    rng = random.Random(rules.get("seed", 7))
    runs = int(rules.get("rank_runs", 3))
    orders = []
    for _ in range(runs):  # shuffle up front, so the orders don't depend on call timing
        order = ids[:]
        rng.shuffle(order)
        orders.append(order)

    async def one(order):
        user = "CANDIDATES:\n" + "\n".join(_rank_block(by[i]) for i in order)
        try:
            return await _ask(llm, "rank", prompt("rank"), user, RankResult)
        except (ValueError, RuntimeError):
            return None

    points = {i: 0.0 for i in ids}
    best_reason: dict[str, tuple[int, str]] = {}
    ok_runs = 0
    for res in await _gather([one(o) for o in orders], progress, "rank"):
        if res is None:
            continue
        seen = [x for x in res.ranking if x.id in points]
        if len({x.id for x in seen}) < max(3, len(ids) // 2):
            continue
        ok_runs += 1
        placed = set()
        for pos, item in enumerate(seen):
            if item.id in placed:
                continue
            placed.add(item.id)
            points[item.id] += len(ids) - pos
            if item.id not in best_reason or pos < best_reason[item.id][0]:
                best_reason[item.id] = (pos, item.reason)
        for i in ids:  # ids the model dropped share the remaining positions
            if i not in placed:
                points[i] += (len(ids) - len(placed) + 1) / 2
    out = {}
    for i in ids:
        denom = max(1, ok_runs) * len(ids)
        out[i] = {"borda": points[i] / denom, "reason": best_reason.get(i, (0, ""))[1]}
    return out, ok_runs


def apply_spoiler_policy(promos: list[Promo], spoiler_eps: set[int], rules: dict) -> None:
    """Decide spoilers per show, not per clip.

    The judge's per-clip spoiler flag changes between runs and tends to flag the title twist. With
    rules.spoiler_source = "vote" (default), spoiler_risk comes from the voted (or config) episode list only, and
    the judge's flag is kept as judge_spoiler. With "judge_or_vote", either source flags the clip."""
    by_vote = rules.get("spoiler_source", "vote") == "vote"
    for p in promos:
        judge = bool(p.flags.get("spoiler_risk")) or bool(p.flags.get("judge_spoiler"))
        in_vote = bool(spoiler_eps & {s.episode for s in p.segments})
        p.flags["judge_spoiler"] = judge
        p.flags["late_payoff_episode"] = in_vote
        p.flags["spoiler_risk"] = in_vote if by_vote else (in_vote or judge)


def final_order(promos: list[Promo], ranks: dict[str, dict], rules: dict, spoiler_eps: set[int] | None = None,
                n_episodes: int | None = None) -> list[Promo]:
    """final = w * rank (Borda) + (1 - w) * judge composite, minus penalties, plus a small attention term.

    Penalties: spoiler, ad-policy risk, needs-context, and a small preference for earlier episodes (a new viewer
    starts the show from there). The attention term comes from attention.py."""
    w = rules["final_llm_weight"]
    spoiler_eps = spoiler_eps or set()
    n_eps = n_episodes or max((s.episode for p in promos for s in p.segments), default=1)
    for p in promos:
        eps_ = [s.episode for s in p.segments]
        if spoiler_eps & set(eps_) and not p.flags.get("late_payoff_episode"):
            p.flags["spoiler_risk"] = True  # callers that skipped apply_spoiler_policy still get the vote
            p.flags["late_payoff_episode"] = True
        r = ranks.get(p.pid)
        base = p.composite if r is None else w * r["borda"] + (1 - w) * p.composite
        if r is None and ranks:
            base *= 0.6  # not in the ranked pool: keep it, below the ranked clips
        pen, tags = 0.0, []
        for flag, key in (("spoiler_risk", "penalty_spoiler"), ("ad_policy_risk", "penalty_policy"),
                          ("needs_context", "penalty_needs_context")):
            if p.flags.get(flag) and rules.get(key):
                pen += rules[key]
                tags.append(flag.replace("_risk", "").replace("_", " "))
        pen += rules.get("penalty_late_episode", 0.0) * (min(eps_) - 1) / max(1, n_eps - 1)
        aw = rules.get("attention_weight", 0.0)
        if aw and p.attention:  # centred, so an average clip is unaffected
            att = 0.7 * p.attention.get("hook_attention", 0.5) + 0.3 * p.attention.get("hold", 0.5)
            pen -= aw * (att - rules.get("attention_center", 0.55))
        p.final = round(base - pen, 4)
        if r and r["reason"]:
            p.rank_reason = r["reason"]
        if tags:
            p.rank_reason = (p.rank_reason + " " if p.rank_reason else "") + f"[pushed down: {', '.join(tags)}]"
    return sorted(promos, key=lambda p: (-p.final, p.pid))


def passes_bar(p: Promo, rules: dict, judged: bool = True) -> bool:
    """Minimum quality for the final list (only applies when an LLM judge scored the clip)."""
    if not judged:
        return True
    if not p.scores:
        return False
    if p.scores.get("hook_3s", 0) < rules.get("min_hook_score", 0):
        return False
    if rules.get("drop_needs_context") and p.flags.get("needs_context"):
        return False
    return not p.flags.get("ad_policy_risk") or not rules.get("drop_ad_policy")


def _overlap(a: Promo, b: Promo) -> bool:
    for s in a.segments:
        for t in b.segments:
            if s.episode == t.episode and s.start < t.end and t.start < s.end:
                return True
    return False


def select_diverse(ordered: list[Promo], rules: dict, k: int) -> list[Promo]:
    """Pick k clips greedily: score minus similarity to clips already picked, at most max_per_episode per episode."""
    chosen: list[Promo] = []
    # Overlapping cuts of the same scene compete on score alone first, so the diversity penalty can't pick the
    # weaker cut and then block the better one as an overlap.
    pool: list[Promo] = []
    for p in sorted(ordered, key=lambda p: (-p.final, p.pid)):
        if not any(_overlap(p, q) for q in pool):
            pool.append(p)
    per_ep: Counter = Counter()
    while pool and len(chosen) < k:
        best, best_v = None, -1e9
        for p in pool:
            eps_ = {s.episode for s in p.segments}
            if any(per_ep[e] >= rules["max_per_episode"] for e in eps_):
                continue
            if any(_overlap(p, c) for c in chosen):
                continue
            sim = 0.0
            for c in chosen:
                if eps_ & {s.episode for s in c.segments}:
                    sim = max(sim, rules["mmr_same_episode"])
                if c.hook_type == p.hook_type and p.hook_type != "other":
                    sim = max(sim, rules["mmr_same_hook_type"])
            v = p.final - rules["mmr_lambda"] * sim
            if v > best_v:
                best, best_v = p, v
        if best is None:
            break
        chosen.append(best)
        pool.remove(best)
        for s in best.segments:
            per_ep[s.episode] += 1
    return chosen


# 6. Montages

async def build_montages(llm, ranked: list[Promo], eps: list[Episode], summary: ShowSummary, rules: dict,
                   start_no: int, spoiler_eps: set[int] | None = None) -> tuple[list[Promo], list[Rejected]]:
    """The model joins 2-3 of the strongest moments into montages; validate.py checks them; one repair round."""
    em = {e.num: e for e in eps}
    spoiler_eps = spoiler_eps or set()
    pool = [p for p in ranked if not (spoiler_eps & {s.episode for s in p.segments})
            and not p.flags.get("ad_policy_risk")][: rules["montage_pool"]]
    blocks = []
    for p in pool:
        s = p.segments[0]
        blocks.append(f"### {p.pid} E{s.episode:02d} {s.start_ts}-{s.end_ts} ({p.duration:.0f}s) | hook {p.hook_line_id}"
                      f" | ends {p.cliffhanger_line_id} | open q: {p.open_question}\n" + "\n".join(p.excerpt))
    logs = "\n".join(f"Ep {e.num}: {e.logline}" for e in eps)
    user = ("SHOW SUMMARY:\n" + summary_text(summary) + "\n\nEPISODE LOGLINES:\n" + logs +
            "\n\nPOOL OF STRONG MOMENTS (with line IDs and times):\n" + "\n\n".join(blocks))
    sysm = prompt("montage").replace("{n}", str(rules["montage_count"]))
    out: list[Promo] = []
    bad: list[Rejected] = []

    def check(ms) -> list[Rejected]:
        rej = []
        for m in ms:
            try:
                out.append(build_montage(m, em, rules, pid=f"M{start_no + len(out):03d}"))
            except Invalid as e:
                rej.append(Rejected(source="montage", start_line=m.segments[0].start_line if m.segments else None,
                                    end_line=m.segments[-1].end_line if m.segments else None,
                                    hook_line=m.hook_line, cliffhanger_line=m.cliffhanger_line, reason=str(e),
                                    hint=" + ".join(f"{s.start_line}..{s.end_line}" for s in m.segments)))
        return rej

    res = await _ask(llm, "montage", sysm, user, MontageBatch)
    first_bad = check(res.montages)
    bad += first_bad
    if first_bad:
        note = "\n".join(f"- segments {b.hint}: REJECTED: {b.reason}" for b in first_bad)
        user2 = user + ("\n\nThese montages from your previous answer were REJECTED by code:\n" + note +
                        "\nReturn corrected versions only (use shorter parts of each moment: about 8-20 s per segment; "
                        "the clock times on each line let you measure).")
        try:
            res2 = await _ask(llm, "montage", sysm, user2, MontageBatch, max_retries=0)
            for b in first_bad:
                b.repaired = True
            bad += check(res2.montages)
        except (ValueError, RuntimeError):
            pass
    seen, uniq = set(), []
    for m in out:
        key = tuple((s.episode, s.start, s.end) for s in m.segments)
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    for i, m in enumerate(uniq, start_no):
        m.pid = f"M{i:03d}"
    return uniq, bad
