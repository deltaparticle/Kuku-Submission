# PromoFinder

**Finds and ranks 20–60 s promo clips in microdrama screenplays**: a hook in the first 3 seconds, an unresolved
cliffhanger at the cut, and a clip that makes sense to someone who has never seen the show.
Built for the Kuku AI Generalist Assignment (Problem 1, "Find the Promos").

**Live app: https://deltaparticle.github.io/Kuku-Assignment/**: a review desk with the official results, plus *Run*
(upload a zip, paste a key, get ranked promos in ~3 minutes for 50 episodes, entirely in your browser).

## The one idea
The model only ever names **script line IDs** (e.g. `E07_L042`). **Code computes every timestamp**, snaps cuts to
gaps between spoken lines, and enforces the brief's rules. A clip can never start mid-sentence or carry an invented time.

```
episodes (.txt) -> 0 parse (code): line IDs + safe cut points
  -> 1 story bible (AI) + spoiler-episode vote (2 of 3 passes)
  -> 2 candidates (AI, 1 call per episode, IDs only) <-> 3 validate + snap (code)
       rejected clips go back to the model with code-computed legal fixes
  -> text attention proxy (code): first voice, motion, close-ups, dead air
  -> 4 rubric score (AI judge, 6 criteria) -> 5 rank (AI, 3 shuffled runs, Borda) + penalties + quality bar + diversity
  -> 6 montages (2-3 joined moments) -> 7 ranked promos (md / csv / json) -> editor approve / reject
```
Full diagram: [docs/architecture.md](docs/architecture.md).

## Results on the 50-episode input pack (official run)
Raw, unedited outputs: [`raw_outputs/official-run-C/`](raw_outputs/official-run-C) (`promos.md` is the readable list).

| | |
|---|---|
| Episodes / script lines read | 50 / 3,727 |
| Valid candidate clips · rejected by code checks | 138 · 36 |
| Final list | 30 ranked promos + 2 montages |
| Hard rules re-checked on the saved output (20–60 s, hook ≤ 3 s, safe cuts, no overlap, ≤ 2 per episode) | 32 / 32 |
| Blind A/B vs a rule-based baseline (AI judge, both orders) | pipeline 13 · baseline 4 · tie 5 |
| Independent repeat run ([`repeat-run-D`](raw_outputs/repeat-run-D)): same scene in both | 4 of top 5 · 6 of top 10 · 21 of 30 |

Top picks: the altar rejection (ep 2, "I cannot marry you, Juliana."), "Guards! Remove her!" → the stranger steps in
(ep 3), the betrayal reveal (ep 1), the stolen-watch frame-up (ep 11), "I want to see you crawl, sister" (ep 12).

## Run it
**In the browser:** open the live app → *Run* → drop a zip of episode `.txt` files (or use the
sample show) → paste a key → *Find promos*. No key? Choose *Instant baseline*.

**Command line:**
```bash
pip install -r requirements.txt
cp .env.example .env                                     # paste GEMINI_API_KEY=... (or another provider's key)
python cli.py check                                      # tests the key and the model names in config.yaml
python cli.py run --input "<folder of episode .txt files>" --profile fast       # ~3 min for 50 episodes
python cli.py run --input "<folder>" --no-llm             # rule-based baseline, no key, ~1 s
python -m pytest -q                                       # 29 tests (synthetic fixture)
```
The sample show is in [`web/data/sample_show.zip`](web/data/sample_show.zip). Profiles: `fast` (judges think less, one
scoring pass), `thorough` (the official run's settings), `free_tier` (one call every 7 s for free Gemini keys).

**Swap the model:** any OpenAI-compatible endpoint (Gemini, OpenAI, OpenRouter, Groq, a company gateway). Choose
it in the app, or edit `providers` / `stages` in [`config.yaml`](config.yaml); no code changes.

## Honest limits
- **No human-labelled ground truth.** Quality evidence is rule checks, run-to-run agreement and an AI judge's blind A/B.
  The judge is the same model family as the picker. Nothing here proves a clip will perform; a live A/B on hook rate,
  hold rate and CTR would.
- **Text only.** Visual hooks are judged from camera/action descriptions; screenplay times are assumed to match the video.
- **Run-to-run variation** remains in the lower half of the list (the ranking model is not fully deterministic).
- **Spoilers are a judgment call:** the title twist (the Duke reveal) is treated as a selling point; villain defeats as spoilers.
  An editor can fix the list per show in `config.yaml` (`late_payoff_episodes`).

## Repository map
```
promofinder/   parse, validate (cut rules), stages (AI steps), heuristics (baseline), attention, llm (any provider), export
prompts are in promofinder/prompts/*.md      config.yaml   models, speed profiles, rules, weights
cli.py         command line                  app.py        Streamlit app (local)
web/           the static browser app (Pyodide runs the same Python package)
eval/          evaluate.py (rule checks, gold metrics), auto_eval.py (agreement, blind A/B), show_picks.py
raw_outputs/   official run C, repeat run D, rule-based baseline
docs/          architecture, research (incl. Meta Ad Library check)     notes/ai_log.md  where the AI tools got it wrong
```
