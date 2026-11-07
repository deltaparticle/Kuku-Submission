"""Print a run's final picks with their script excerpts, for a quick human audit.

  python eval/show_picks.py outputs/<show>/<run-id> [--top 30] [--no-excerpt]
"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--top", type=int, default=30)
ap.add_argument("--no-excerpt", action="store_true")
a = ap.parse_args()
d = json.loads((Path(a.run) / "promos.json").read_text(encoding="utf-8"))
for p in d["promos"][: a.top] + d.get("montages", []):
    segs = " + ".join(f"E{s['episode']:02d} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])
    flags = [k for k, v in p["flags"].items() if v]
    print(f"\n#{'M' if p['kind'] == 'montage' else ''}{p['rank']} {p['pid']} {segs} {p['duration']:.0f}s "
          f"final={p['final']:.3f} comp={p['composite']:.2f} flags={flags}")
    print("   scores:", p["scores"])
    print("   HOOK :", p["hook"][:120])
    print("   CLIFF:", p["cliffhanger"][:120])
    print("   WHY  :", p["why"][:160])
    if not a.no_excerpt:
        print("   " + "\n   ".join(p["excerpt"]))
