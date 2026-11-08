"""Record a demo cache for the website.

Runs the pipeline on the given episode files exactly as the web app does (same bridge configuration, same show name,
same options), with real model calls, and zips the saved model replies into web/data/demo_cache.zip. The site loads
that zip into the browser's cache, so uploading the same files with the same settings replays these replies instead
of calling the provider. Any other upload or setting still calls the provider as normal.

    python scripts/utils/record_demo_cache.py "<episode-007 .txt>" "<episode-039 .txt>" --profile free_tier
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "web")]

import bridge  # noqa: E402  (the web app's glue: we reuse its configuration so cache keys match the browser)
from snipdeck.llm import LLM  # noqa: E402
from snipdeck.parse import load_show  # noqa: E402
from snipdeck.pipeline import arun  # noqa: E402

bridge.APP = ROOT  # in the browser config.yaml sits next to bridge.py; here it is at the repo root

# what app.js sends for the Gemini provider with its default model names
DEFAULT_OPTS = {"use_llm": True, "provider": "gemini", "base_url": "", "bulk_model": "gemini-3-flash-preview",
                "judge_model": "gemini-3.8-flash", "montage": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="the exact .txt files a demo will upload")
    ap.add_argument("--profile", default="free_tier", help="the Speed option the demo will pick (fast | thorough | free_tier)")
    ap.add_argument("--out", default=str(ROOT / "web" / "data" / "demo_cache.zip"))
    a = ap.parse_args()

    opts = dict(DEFAULT_OPTS, profile=a.profile)
    with tempfile.TemporaryDirectory() as tmp:
        work, cache = Path(tmp) / "work", Path(tmp) / "cache"
        work.mkdir()
        cache.mkdir()
        for f in a.files:
            shutil.copy(f, work / Path(f).name)
        eps = load_show(work)
        show = "Uploaded show" if len(a.files) > 1 else Path(a.files[0]).stem  # same rule as bridge.load_files
        cfg = bridge._configure(opts)
        llm = LLM(cfg, cache_dir=cache, use_cache=False, log=print)  # use_cache=False: always make real calls
        res = asyncio.run(arun(eps, cfg, llm=llm, use_llm=True, do_montage=True,
                               progress=lambda s, i, n: print(f"  [{s}] {i}/{n}"), show=show))
        print(f"{len(res['promos'])} promos, {len(res['montages'])} montages, {len(llm.calls)} calls")
        out = Path(a.out)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(cache.glob("*.json")):
                z.write(f, f.name)
        meta = {"files": [Path(f).name for f in a.files], "profile": a.profile, "calls": len(llm.calls),
                "models": sorted({c["model"] for c in llm.calls})}
        print(f"wrote {out} ({out.stat().st_size // 1024} KB): {json.dumps(meta)}")


if __name__ == "__main__":
    main()
