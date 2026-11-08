"""Browser glue: runs the unchanged SnipDeck pipeline inside Pyodide (Python compiled to WebAssembly).

The page (app.js) calls:
  load_files([(name, bytes), ...]) -> JSON summary     # .zip and/or .txt screenplays, unpacked into an in-memory FS
  await run(options_json, progress_fn, log_fn) -> JSON  # the same payload export.payload() gives the CLI
Model calls go straight from the visitor's browser to the provider with the visitor's key (llm.py uses fetch when
it detects Pyodide). Nothing is sent to any server of ours.
"""
import io
import json
import shutil
import zipfile
from pathlib import Path

from snipdeck.export import payload
from snipdeck.llm import LLM, load_config
from snipdeck.parse import load_show
from snipdeck.subtitles import SUBTITLE_EXT, load_subtitles
from snipdeck.pipeline import arun

APP = Path(__file__).resolve().parent
WORK = Path("/work")
STATE = {"eps": [], "show": "show"}

JUDGE_STAGES = ("bible", "score", "rank", "montage")


def load_files(files, max_minutes: float = 10) -> str:
    """files: list of (filename, bytes). Accepts .zip archives, .txt screenplays, or one .srt/.vtt subtitle file
    (first `max_minutes` minutes, split into ~2.5-minute parts)."""
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    names = []
    for name, data in files:
        data = bytes(data)
        low = name.lower()
        if low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(WORK)
            names.append(name)
        elif low.endswith(".txt") or low.endswith(SUBTITLE_EXT):
            (WORK / Path(name).name).write_bytes(data)
            names.append(name)
    subs = sorted(f for f in WORK.rglob("*") if f.suffix.lower() in SUBTITLE_EXT)
    if subs:
        eps = load_subtitles(subs[0], max_seconds=max_minutes * 60 if max_minutes else None, show=subs[0].stem)
    else:
        eps = load_show(WORK)
    STATE["eps"] = eps
    first = names[0] if names else "show"
    STATE["show"] = (Path(first).stem if len(names) == 1 and first.lower().endswith((".zip",) + SUBTITLE_EXT)
                     else "Uploaded show")
    return json.dumps({
        "episodes": len(eps), "lines": sum(len(e.lines) for e in eps),
        "first": eps[0].num if eps else None, "last": eps[-1].num if eps else None,
        "minutes": round(sum(e.duration for e in eps) / 60, 1), "show": STATE["show"],
        "files": len(names)})


def set_show(name: str) -> None:
    STATE["show"] = name


def _configure(opts: dict) -> dict:
    cfg = load_config(APP / "config.yaml", opts.get("profile") or None)
    prov = opts.get("provider") or "gemini"
    if prov == "custom":
        cfg["providers"]["custom"] = {"base_url": opts.get("base_url", "").strip(), "api_key_env": "SNIPDECK_CUSTOM_KEY"}
    pc = cfg["providers"].setdefault(prov, {})
    if opts.get("base_url") and prov != "custom":
        pc["base_url"] = opts["base_url"].strip()
    pc.setdefault("concurrency", 6)
    pc.setdefault("min_interval_s", 0.3)
    pc.setdefault("retries", 3)
    pc.setdefault("timeout", 300)
    picks = {"candidates": (opts.get("bulk_model") or "").strip()}
    for s in JUDGE_STAGES:
        picks[s] = (opts.get("judge_model") or "").strip()
    for stage, model in picks.items():
        st = cfg["stages"][stage]
        if not model:
            model = st["model"]
        if st["provider"] != prov or st["model"] != model:
            # config fallbacks belong to the configured provider/model: never mix them into a swap
            st.update(provider=prov, model=model, fallback_models=[])
    # reasoning_effort stays on (it caps billed "thinking"); llm.py drops it automatically if an endpoint rejects it
    return cfg


async def run(options_json: str, progress_fn, log_fn) -> str:
    opts = json.loads(options_json)
    eps = STATE["eps"]
    if not eps:
        raise ValueError("No episodes loaded")
    use_llm = bool(opts.get("use_llm"))
    cfg = _configure(opts)
    llm = None
    if use_llm:
        prov = opts.get("provider") or "gemini"
        llm = LLM(cfg, cache_dir="/cache", api_keys={prov: opts.get("key", "")}, log=lambda m: log_fn(str(m)))
    res = await arun(eps, cfg, llm=llm, use_llm=use_llm, do_montage=bool(opts.get("montage", True)),
                     progress=lambda s, i, n: progress_fn(s, i, n), show=STATE["show"])
    durations = {e.num: round(e.duration, 2) for e in eps}
    out = payload(res, STATE["show"], durations)
    out["run_log"]["profile"] = cfg.get("active_profile")
    return json.dumps(out, ensure_ascii=False)
