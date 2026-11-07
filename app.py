"""PromoFinder web UI (Streamlit). Upload a show's screenplays, get ranked promo picks, approve/reject them."""
import copy
import csv
import io
import os
import tempfile
import time
import zipfile
from pathlib import Path

import streamlit as st

from promofinder.export import seg_str, to_markdown, write_all
from promofinder.llm import LLM, load_config
from promofinder.parse import load_show
from promofinder.pipeline import run

ROOT = Path(__file__).parent
st.set_page_config(page_title="PromoFinder", page_icon="🎬", layout="wide")
st.title("🎬 PromoFinder")
st.caption("Finds and ranks 20–60s promo clips (hook in 3s, cliffhanger ending, makes sense alone) in microdrama "
           "screenplays. The model names line IDs; code computes every timestamp.")

cfg = load_config(ROOT / "config.yaml")

with st.sidebar:
    st.header("Input")
    up = st.file_uploader("Zip of episode .txt files", type=["zip"])
    local = st.text_input("…or a local folder path", value="")
    st.header("Model")
    use_llm = st.toggle("Use LLM (off = rule-based baseline, no API)", value=True)
    prov = st.selectbox("Provider", list(cfg["providers"].keys()), index=0)
    bulk = st.text_input("Bulk model (candidates: 1 call per episode)", cfg["stages"]["candidates"]["model"])
    strong = st.text_input("Judge model (bible, scoring, ranking, montage)", cfg["stages"]["score"]["model"])
    st.caption("Change the provider or a model name and its config fallbacks are dropped, so every call uses the "
               "model you typed.")
    key_default = ""
    try:
        key_default = st.secrets.get(cfg["providers"][prov]["api_key_env"], "")
    except Exception:  # noqa: BLE001 - no secrets file locally
        pass
    key = st.text_input("API key (never stored)", type="password", value="",
                        placeholder="uses server secret if blank" if key_default else "paste key")
    montage = st.toggle("Also build montage promos (v2)", value=True)
    go = st.button("Find promos", type="primary", width="stretch")


def load_input():
    if up is not None:
        d = Path(tempfile.mkdtemp(prefix="promofinder_"))
        with zipfile.ZipFile(io.BytesIO(up.getvalue())) as z:
            z.extractall(d)
        return d
    if local.strip():
        return Path(local.strip())
    return None


if go:
    src = load_input()
    if src is None or not src.exists():
        st.error("Upload a zip or give a valid folder path.")
        st.stop()
    eps = load_show(src)
    if not eps:
        st.error("No parsable episode .txt files found.")
        st.stop()
    c = copy.deepcopy(cfg)
    for names, model in ((("candidates",), bulk.strip()), (("bible", "score", "rank", "montage"), strong.strip())):
        for s in names:
            st_cfg = c["stages"][s]
            if st_cfg["provider"] != prov or st_cfg["model"] != model:
                # fallbacks in config.yaml belong to the configured provider/model: never mix them with a swap
                st_cfg.update(provider=prov, model=model, fallback_models=[])
    llm = None
    if use_llm:
        keys = {prov: key or key_default}
        if not keys[prov] and not os.environ.get(c["providers"][prov]["api_key_env"]):
            st.error("No API key. Paste one, set the env var, or switch the LLM toggle off.")
            st.stop()
        llm = LLM(c, cache_dir=ROOT / ".cache", api_keys=keys)
    bar = st.progress(0.0, text="Starting…")

    def progress(stage, i, n):
        bar.progress(min(1.0, i / max(1, n)), text=f"{stage}: {i}/{n}")

    try:
        with st.spinner("Working…"):
            show_name = Path(up.name).stem if up is not None else Path(src).name
            st.session_state["res"] = run(eps, c, llm=llm, use_llm=use_llm, do_montage=montage, progress=progress,
                                          show=show_name)
        st.session_state["show"] = show_name
        st.session_state["decisions"] = {}
    except Exception as e:  # noqa: BLE001 - surface any provider error to the user
        st.error(f"Run failed: {e}")
        st.stop()
    bar.empty()

res = st.session_state.get("res")
if not res:
    st.info("Upload a zip of episodes (or enter a folder path), then press **Find promos**. "
            "No key? Turn the LLM toggle off to see the rule-based baseline.")
    st.stop()

lg = res["run_log"]
a, b, c_, d = st.columns(4)
a.metric("Episodes", lg["episodes"])
b.metric("Valid candidates", lg["candidates_valid"])
c_.metric("Rejected by checks", lg["candidates_rejected"])
d.metric("LLM calls", lg["llm"]["total_calls"] if lg["llm"] else 0)
st.caption(f"Mode: {lg['mode']} · {lg['seconds']}s")

dec = st.session_state.setdefault("decisions", {})


def cards(items, prefix):
    for p in items:
        with st.container(border=True):
            h1, h2 = st.columns([5, 2])
            h1.subheader(f"{prefix}{p.rank} · {seg_str(p)} · {p.duration:.0f}s")
            flags = [k.replace("_risk", "").replace("_", " ") for k, v in p.flags.items() if v]
            if flags:
                h2.warning("⚠ " + ", ".join(flags))
            st.markdown(f"**Hook:** {p.hook}  \n**Cliffhanger:** {p.cliffhanger}")
            if p.open_question:
                st.markdown(f"**Open question:** {p.open_question}")
            st.markdown(f"**Why it works:** {p.why or '—'}")
            if p.rank_reason:
                st.caption(f"Rank note: {p.rank_reason}")
            if p.scores:
                st.caption("Scores: " + ", ".join(f"{k} {v}" for k, v in p.scores.items())
                           + f" · composite {p.composite:.2f}")
            if p.attention:
                a = p.attention
                st.caption(f"Attention (text proxy): hook {a['hook_attention']:.2f} · hold {a['hold']:.2f} · first "
                           f"voice at {a['hook_features']['t_first_voice']:.1f}s"
                           + (f" · ⚠ {'; '.join(a['flags'])}" if a.get("flags") else ""))
            with st.expander("Script"):
                st.code("\n".join(p.excerpt), language=None)
            c1, c2, c3 = st.columns([1, 1, 6])
            if c1.button("✅ Approve", key=f"a{p.pid}"):
                dec[p.pid] = "approved"
            if c2.button("❌ Reject", key=f"r{p.pid}"):
                dec[p.pid] = "rejected"
            if dec.get(p.pid):
                c3.write(f"Marked **{dec[p.pid]}**")


tab1, tab2, tab3 = st.tabs(["Ranked promos", "Montages (v2)", "Rejected candidates"])
with tab1:
    cards(res["promos"], "#")
with tab2:
    if res["montages"]:
        cards(res["montages"], "M")
    else:
        st.write("No montages produced (needs LLM mode and the montage toggle).")
with tab3:
    st.write("Candidates dropped by the deterministic checks, with the reason (shows where the model/rules misfire).")
    st.dataframe([r.model_dump() for r in res["rejected"]], width="stretch")

st.divider()
show = st.session_state.get("show", "show")
c1, c2, c3 = st.columns(3)
c1.download_button("⬇ promos.md", to_markdown(res, show), "promos.md")
buf = io.StringIO()
w = csv.writer(buf)
w.writerow(["rank", "id", "segments", "duration_s", "hook", "cliffhanger", "why", "decision"])
for p in res["promos"] + res["montages"]:
    w.writerow([("M" if p.kind == "montage" else "") + str(p.rank), p.pid, seg_str(p), p.duration, p.hook,
                p.cliffhanger, p.why, dec.get(p.pid, "")])
c2.download_button("⬇ promos + decisions (CSV)", buf.getvalue(), "promos_with_feedback.csv")
if c3.button("Save run to outputs/"):
    out = write_all(res, ROOT / "outputs" / "ui_runs" / time.strftime("%Y%m%d-%H%M%S"), show)
    st.success(f"Saved to {out}")
