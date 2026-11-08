"""Figure for the 2-page paper. Every number is read from the saved run outputs (or recomputed from them).

  python scripts/utils/make_figures.py   ->  docs/paper/fig_results.pdf
"""
import collections
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "paper" / "fig_results.pdf"
L = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8"))  # noqa: E731
RUN2 = "outputs/I_Married_a_Broken_Soldier_He_was_a_Duke/llm-run-2"
RUNC = "results/official-run-C"
USD_INR = 88.0
PRICE = {"gemini-3.8-flash": (0.75, 3.75), "gemini-3-flash-preview": (0.50, 3.00)}  # $/1M tokens (in, out incl. thinking)


def same_scene(a, b):
    s, t = a["segments"][0], b["segments"][0]
    return s["episode"] == t["episode"] and s["start"] < t["end"] + 5 and t["start"] < s["end"] + 5


def iou(a, b):
    s, t = a["segments"][0], b["segments"][0]
    if s["episode"] != t["episode"]:
        return 0.0
    i = max(0.0, min(s["end"], t["end"]) - max(s["start"], t["start"]))
    return i / ((s["end"] - s["start"]) + (t["end"] - t["start"]) - i)


def agreement(a, b):
    A, B = L(a)["promos"], L(b)["promos"]
    return [100 * sum(any(same_scene(x, y) for y in B[:5]) for x in A[:5]) / 5,
            100 * sum(any(same_scene(x, y) for y in B) for x in A) / len(A),
            100 * sum(any(iou(x, y) >= .5 for y in B) for x in A) / len(A)]


pairs = {"v0": ("outputs/I_Married_a_Broken_Soldier_He_was_a_Duke/llm-run-1/promos.json", RUN2 + "/promos.json"),
         "v1": ("outputs/I_Married_a_Broken_Soldier_He_was_a_Duke_script/llm-run-3/promos.json",
                "outputs/I_Married_a_Broken_Soldier_He_was_a_Duke_script/llm-run-4/promos.json"),
         "v2": (RUNC + "/promos.json", "results/repeat-run-D/promos.json")}
agr = {k: agreement(*v) for k, v in pairs.items()}

hook = {}
for name, d in (("v0 judge (run 2)", RUN2), ("v2 judge (run C)", RUNC)):
    vals = [round(x["scores"]["hook_3s"]) for x in L(d + "/candidates_all.json")["valid"] if x["scores"]]
    c = collections.Counter(vals)
    hook[name] = [100 * c.get(k, 0) / len(vals) for k in range(1, 6)]

log = L(RUNC + "/run_log.json")["llm"]["by_stage"]
cost = {}
for s, v in log.items():
    m = max(v["models_used"], key=v["models_used"].get)
    pi, po = PRICE[m]
    cost[s] = USD_INR * (v["prompt_tokens"] * pi + (v["completion_tokens"] + v["thinking_tokens"]) * po) / 1e6

plt.rcParams.update({"font.size": 7, "font.family": "serif", "axes.spines.top": False, "axes.spines.right": False,
                     "axes.linewidth": .6, "xtick.major.width": .6, "ytick.major.width": .6, "legend.frameon": False})
fig, ax = plt.subplots(1, 3, figsize=(7.1, 1.75), gridspec_kw={"width_ratios": [1.25, 1, 1.05]})
greys = ["#bdbdbd", "#7a7a7a", "#c0392b"]

# (a) stability
labels = ["same scene\ntop-5", "same scene\ntop-30", "same moment\ntop-30 (IoU≥.5)"]
w = .26
for i, (k, vals) in enumerate(agr.items()):
    xs = [j + (i - 1) * w for j in range(3)]
    ax[0].bar(xs, vals, w, color=greys[i], label=k, edgecolor="none")
    for x, v in zip(xs, vals):
        ax[0].text(x, v + 2, f"{v:.0f}", ha="center", va="bottom", fontsize=5.5)
ax[0].set_xticks(range(3), labels, fontsize=6)
ax[0].set_ylim(0, 100)
ax[0].set_ylabel("agreement between\nindependent runs (%)")
ax[0].legend(ncol=3, loc="upper left", fontsize=6, handlelength=1, columnspacing=.8)
ax[0].set_title("(a) run-to-run stability", fontsize=7, loc="left")

# (b) judge calibration
xs = range(1, 6)
for i, (k, vals) in enumerate(hook.items()):
    ax[1].bar([x + (i - .5) * .38 for x in xs], vals, .38, color=greys[0] if i == 0 else greys[2], label=k, edgecolor="none")
ax[1].set_xticks(list(xs))
ax[1].set_ylim(0, 54)
ax[1].set_xlabel("judge hook score (1–5)")
ax[1].set_ylabel("% of candidates")
ax[1].legend(loc="upper right", fontsize=6, handlelength=1)
ax[1].set_title("(b) hook-score distribution", fontsize=7, loc="left")

# (c) what the code checks caught (single-clip rejections in the official run)
def reason(r):
    t = r["reason"]
    if t.startswith("too long"):
        return "too long"
    if t.startswith("too short"):
        return "too short"
    if "CAMERA" in t:
        return "camera-only hook"
    if "does not exist" in t:
        return "invented line ID"
    return "other"


rej = [r for r in L(RUNC + "/candidates_all.json")["rejected"] if r["source"] != "montage"]
cnt = collections.Counter(reason(r) for r in rej)
order = ["too long", "camera-only hook", "invented line ID", "too short", "other"]
vals = [cnt.get(k, 0) for k in order]
ax[2].barh(order[::-1], vals[::-1], color=["#7a7a7a"] * 4 + ["#c0392b"], height=.6, edgecolor="none")
for y, v in enumerate(vals[::-1]):
    ax[2].text(v + .2, y, str(v), va="center", fontsize=5.5)
ax[2].set_xlabel(f"rejected clips ({sum(vals)}; {sum(r.get('repaired', False) for r in rej)} repaired)")
ax[2].set_xlim(0, max(vals) * 1.3)
ax[2].tick_params(axis="y", labelsize=6)
ax[2].set_title("(c) caught by the code checks", fontsize=7, loc="left")

fig.tight_layout(pad=.3, w_pad=1.2)
fig.savefig(OUT)
print("wrote", OUT, {k: [round(x) for x in v] for k, v in agr.items()}, dict(zip(order, vals)))
