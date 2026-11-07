"""PromoFinder CLI.

  python cli.py run --input "<episodes dir>"                  # full LLM pipeline (needs an API key)
  python cli.py run --input "<episodes dir>" --no-llm         # rule-based baseline, zero API calls
  python cli.py run --input ... --config my.yaml --out outputs
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from promofinder.export import write_all  # noqa: E402
from promofinder.llm import LLM, load_config  # noqa: E402
from promofinder.parse import load_show  # noqa: E402
from promofinder.pipeline import run  # noqa: E402


def check(config_path: str) -> int:
    """Make one tiny call per distinct (provider, model) so key/model-name problems show up in 5 seconds."""
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool

    cfg = load_config(config_path)
    llm = LLM(cfg, cache_dir=Path(__file__).parent / ".cache", use_cache=False)
    seen, bad = set(), 0
    for stage, s in cfg["stages"].items():
        key = (s["provider"], s["model"])
        if key in seen:
            continue
        seen.add(key)
        try:
            llm.json(stage, "Reply with only JSON.", 'Return {"ok": true}', Ping, max_retries=0)
            print(f"OK    {s['provider']} / {s['model']}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL  {s['provider']} / {s['model']}")
            print(f"      {str(e)[:300]}")
            if "No API key" not in str(e):
                try:
                    names = [m.id for m in llm._client(s["provider"], cfg["providers"][s["provider"]]).models.list()]
                    print("      models your key can use (pick names from here, put them in config.yaml):")
                    print("      " + ", ".join(sorted(names))[:900])
                except Exception:  # noqa: BLE001
                    pass
    print("\nAll good - you can run the pipeline." if not bad else "\nFix the FAIL lines above, then run check again.")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="promofinder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="find and rank promos")
    r.add_argument("--input", required=True, help="folder containing episode .txt screenplays")
    r.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    r.add_argument("--out", default=str(Path(__file__).parent / "outputs"))
    r.add_argument("--show", default=None, help="show name (default: input folder name)")
    r.add_argument("--no-llm", action="store_true", help="rule-based baseline only (no API calls)")
    r.add_argument("--no-montage", action="store_true")
    r.add_argument("--no-cache", action="store_true")
    r.add_argument("--fresh-stages", default="", help="comma list of stages to re-call instead of reading the cache, "
                   "e.g. bible,score,rank,montage (keeps the cached candidates)")
    r.add_argument("--run-id", default=None)
    r.add_argument("--profile", default=None, help="fast | thorough (default) | free_tier, see config.yaml")
    r.add_argument("--cache-dir", default=str(Path(__file__).parent / ".cache"),
                   help="model-response cache (use a separate one for an independent repeat run)")
    c = sub.add_parser("check", help="test your API key and the model names in config.yaml")
    c.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    a = ap.parse_args()
    if a.cmd == "check":
        return check(a.config)

    cfg = load_config(a.config, a.profile)
    eps = load_show(a.input)
    if not eps:
        print(f"No episode .txt files found under {a.input}", file=sys.stderr)
        return 2
    show = a.show or Path(a.input).name
    slug = re.sub(r"[^A-Za-z0-9]+", "_", show).strip("_")[:60]
    run_id = a.run_id or time.strftime("%Y%m%d-%H%M%S") + ("-baseline" if a.no_llm else "")
    print(f"Loaded {len(eps)} episodes, {sum(len(e.lines) for e in eps)} lines from {a.input} "
          f"(profile: {cfg.get('active_profile', 'none')})")

    llm = None if a.no_llm else LLM(cfg, cache_dir=a.cache_dir, use_cache=not a.no_cache,
                              fresh_stages={x.strip() for x in a.fresh_stages.split(",") if x.strip()})

    def progress(stage, i, n):
        print(f"  [{stage}] {i}/{n}", flush=True)

    res = run(eps, cfg, llm=llm, use_llm=not a.no_llm, do_montage=not a.no_montage, progress=progress,
              show=show)
    out = write_all(res, Path(a.out) / slug / run_id, show)
    lg = res["run_log"]
    print(f"\nDone in {lg['seconds']}s: {lg['final_promos']} promos, {lg['montages']} montages, "
          f"{lg['candidates_rejected']} rejected candidates.")
    if lg["llm"]:
        print(f"LLM calls: {lg['llm']['total_calls']} ({lg['llm']['cache_hits']} cached)")
    print(f"Outputs: {out}")
    for p in res["promos"][:5]:
        s = p.segments[0]
        print(f"  #{p.rank} E{s.episode:02d} {s.start_ts}-{s.end_ts} ({p.duration:.0f}s) {p.hook[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
