# PromoFinder: Automatic Promo Selection for Microdrama Screenplays

This repository contains the complete implementation and evaluation framework for **finding and ranking promo clips in
microdrama screenplays**. Given a show's timestamped scripts, it returns ranked 20–60 second clips that open on a
**hook within the first 3 seconds**, end on an **unresolved cliffhanger**, and **make sense to a viewer who has never
seen the show**: either one continuous stretch, or a montage of 2–3 moments. It was built for the Kuku AI Generalist
Assignment (Problem 1, "Find the Promos").

The central design rule: **the language model may only name script line IDs; code computes every timestamp and enforces
every rule.** This removes the usual failure of model-written timestamps that drift or cut mid-sentence.

* **Live app:** https://deltaparticle.github.io/Kuku-Assignment/ (review the official results, or run it on your own episodes in the browser)
* **Report (2 pages):** [PromoFinder.pdf](PromoFinder.pdf)

---

## 1. Repository Structure

* **`src/promofinder/`**: the core library.
    * [parse.py](src/promofinder/parse.py): reads screenplay files into lines with stable IDs (`E07_L042`), types and start/end times; defines a *safe cut* (no dialogue or sound playing).
    * [subtitles.py](src/promofinder/subtitles.py): imports `.srt` / `.vtt` subtitle files (e.g. YouTube auto-captions) as screenplay-like episodes.
    * [validate.py](src/promofinder/validate.py): turns the model's line IDs into clips: enforces hook ≤ 3 s, 20–60 s, ending on the cliffhanger, and computes legal alternatives for clips that fail.
    * [stages.py](src/promofinder/stages.py): the model-driven stages: story bible and spoiler vote, candidates with repair, rubric scoring, shuffled listwise ranking, diversity selection and montages.
    * [attention.py](src/promofinder/attention.py): a text-based attention check (time to first voice, motion, close-ups, sound, dead air).
    * [heuristics.py](src/promofinder/heuristics.py): keyword/emotion rules used as a recall backstop and as the no-AI baseline.
    * [llm.py](src/promofinder/llm.py): one async client for any OpenAI-compatible endpoint: per-stage models, fallbacks, retries, parallel calls, disk cache.
    * [pipeline.py](src/promofinder/pipeline.py): runs the stages end to end; [export.py](src/promofinder/export.py) writes Markdown, CSV and JSON.
    * [schemas.py](src/promofinder/schemas.py): data models (what the model may return, and what is exported).
    * [prompts/](src/promofinder/prompts): the five prompts (bible, candidates, score, rank, montage).
* **`scripts/`**: executable scripts, grouped by function.
    * [run.py](scripts/run.py): the command-line tool (`check` tests a key and model names; `run` finds promos).
    * **`scripts/eval/`**: [evaluate.py](scripts/eval/evaluate.py) re-checks the hard rules on a saved run; [auto_eval.py](scripts/eval/auto_eval.py) measures run-to-run agreement and runs the blind A/B against the baseline; [show_picks.py](scripts/eval/show_picks.py) prints picks with their script for a manual audit.
    * **`scripts/utils/`**: [build_site.py](scripts/utils/build_site.py) packages the library and data for the website; [make_figures.py](scripts/utils/make_figures.py) draws the report's figure from the saved runs.
* **`results/`**: unedited outputs on the 50-episode pack: [official-run-C](results/official-run-C) (the official run), [repeat-run-D](results/repeat-run-D) (an independent repeat, for stability) and [rule-baseline](results/rule-baseline). In each, `promos.md` is the readable list.
* **`web/`**: the static website (review desk and in-browser runner). It runs the same Python package via Pyodide.
* **`tests/`**: 32 tests on a synthetic fixture, with a fake model for the pipeline wiring.
* **`docs/`**: [architecture.md](docs/architecture.md) (detailed diagram), [research.md](docs/research.md) (industry and competitor research, with sources), [paper/](docs/paper) (LaTeX source of the report).
* **`config.yaml`**: providers, per-stage models, speed profiles, rules and score weights. Models are swapped here, never in code.
* **`requirements.txt`**: Python dependencies.

---

## 2. Setup and Execution Guide

### Prerequisites
Python 3.10+:
```bash
pip install -r requirements.txt
```

### API key
Copy `.env.example` to `.env` and add a key (`GEMINI_API_KEY=...`). The `.env` file is ignored by git. A free Gemini key
works, more slowly; any OpenAI-compatible provider can be configured in `config.yaml`. Check the key and model names:
```bash
python scripts/run.py check
```

### Input data
The tool reads a folder of episode screenplays (`.txt`, the timestamped format described in §3) or one `.srt`/`.vtt`
subtitle file. The 50-episode sample show is in [web/data/sample_show.zip](web/data/sample_show.zip).

### Running
1. **Rule-based baseline** (no key, about 1 second):
   ```bash
   python scripts/run.py run --input <episodes folder> --no-llm
   ```
2. **Full AI pipeline**:
   ```bash
   python scripts/run.py run --input <episodes folder> --profile fast
   ```
   Profiles: `fast` (about 3 minutes for 50 episodes on a paid key), `thorough` (the official run's settings),
   `free_tier` (one call every 7 seconds, for free keys). Outputs go to `outputs/<show>/<run-id>/`.
3. **Subtitle input** (first 10 minutes of a video):
   ```bash
   python scripts/run.py run --input captions.srt --max-minutes 10
   ```
4. **Evaluation** of a saved run:
   ```bash
   python scripts/eval/evaluate.py --input <episodes folder> --run results/official-run-C
   python scripts/eval/auto_eval.py --input <episodes folder> --run results/official-run-C --baseline results/rule-baseline
   ```
5. **Tests**:
   ```bash
   python -m pytest
   ```

---

## 3. Input Format

Each episode file has a header (episode number, logline, continuity notes) and timed blocks:
```
**MATRIARCH (Firm):**
Start: (00:11.30) | End: (00:13.40)
"You should turn around, Juliana."
```
Block types are `CAMERA`, `ACTION`, `SOUND FX` and dialogue (`NAME (Emotion)`, including `(O.S.)`). The pack has 50 episodes,
3,727 timed lines and 103 minutes of screen time. Speaker labels and place names vary across episodes (the same person
may appear as a name or a description), which the story bible resolves.

---

## 4. Pipeline

1. **Parse** (code): every block becomes a line $\ell = (\text{id}, \text{type}, \text{speaker}, t^s, t^e)$. A time $t$ is a
   *safe cut* if no dialogue or sound line has $t^s < t < t^e$.
2. **Story bible** (1 model call): characters and aliases, which twists sell the show, which payoffs would spoil it.
   Spoiler episodes are decided by a two-out-of-three vote so they do not change between runs; an editor can fix them in `config.yaml`.
3. **Candidates** (1 call per episode): three moments, each returned as start, hook, cliffhanger and end **line IDs**, never times.
4. **Validate and snap** (code): the clip starts at most 3 s before the hook, ends on the cliffhanger (keeping only silent
   reaction shots after it) and before the line that answers it, cuts only at safe points, and lasts 20–60 s. A clip that
   fails goes back to the model with the exact line IDs that would make it legal.
5. **Score**, **rank** and **select** (§5).
6. **Montages**: the model joins 2–3 moments in story order; the same validator checks every part.

---

## 5. Scoring and Ranking

### Rubric score
A judge model rates each clip from 1 to 5 on hook, cliffhanger, clarity to a stranger, intensity, plot relevance and genre
fit. It quotes the first 3 s and the last lines before scoring, and is told to spread its scores within each batch. Each clip
is scored twice in differently shuffled batches and averaged. The composite is
$$c = \frac{\sum_k w_k \,(s_k - 1)/4}{\sum_k w_k}, \qquad w = (3, 3, 2, 1, 1, 1)$$
for (hook, cliffhanger, clarity, intensity, plot, genre fit).

### Listwise ranking
The top 40 clips are ordered by the judge three times, each time in a different shuffled order, and combined by Borda
count: $b_i = \sum_r (N - p_{i,r}) / (R N)$.

### Final score
$$f = 0.6\,b + 0.4\,c - 0.15\,[\text{spoiler}] - 0.25\,[\text{ad policy}] - 0.1\,\frac{e-1}{E-1} + 0.15\,(a - 0.55)$$
where $e$ is the episode, $E$ the last episode and $a$ the attention score (§6). The weights were set by hand with a
human in the loop, re-reading the picks after each run, and are tuned on Gemini models only; other models may need
different values.

### Selection
A quality bar (hook score ≥ 2.5, not "needs context"), one cut per scene, at most two clips per episode, and a diversity
penalty across episodes and hook types choose up to 30 promos.

---

## 6. Text Attention Check

Video attention tools look for faces, motion, cuts, loud sounds and early speech. A screenplay describes all of these, so
[attention.py](src/promofinder/attention.py) measures them from text:
* **First 3 seconds:** time to the first spoken line, shot changes, close-ups, physical action, sound spikes, raised or
  emotional delivery, direct address ("you", questions) and stakes words.
* **Whole clip:** longest stretch with nothing said or done, cutting pace, share of time with speech, and whether it ends on
  a close-up, a sound sting or an open line.

It gives an attention score, a hold score and plain warnings such as "no voice until 5.5 s" or "6 s of dead air". It agrees
moderately with the judge's hook score (correlation 0.31), which makes it a useful second opinion rather than a copy.

---

## 7. Results

Official run on the 50-episode pack, with `gemini-3-flash-preview` proposing candidates and `gemini-3.8-flash` judging.

| Metric | Value |
|---|---|
| Valid / rejected candidate clips | 138 / 36 (33 sent back for repair) |
| Final list | 30 promos + 2 montages, from 24 episodes |
| Hard rules re-checked on the saved output | 32 / 32 |
| Clip length | 22–59 s, mean 42 s |
| Blind A/B against the rule baseline (judge sees both clips, both orders) | 13 wins, 4 losses, 5 ties ($p = 0.025$ on decisive pairs) |
| Independent repeat run, same scene | 4 of the top 5, 6 of the top 10, 21 of 30 |
| Fast profile, full show | 103 model calls, 2 min 45 s |

**Top of the list:**

| # | Episode, in–out | Hook | Ends on |
|---|---|---|---|
| 1 | Ep 2, 00:00–00:45 | "I cannot marry you, Juliana." | "Do not disgrace us further." |
| 2 | Ep 3, 00:58–01:25 | "Guards! Remove her!" | "...let her go." |
| 3 | Ep 1, 00:11–01:02 | "You should turn around, Juliana." | "I changed my mind." |
| 4 | Ep 11, 00:17–00:51 | "Your husband stole my gold pocket watch!" | "Search it." |
| 5 | Ep 12, 00:44–01:25 | "I want to see you crawl, sister." | "Tell me where the garden is." |

The full ranked list with scripts, scores and reasons is in [results/official-run-C/promos.md](results/official-run-C/promos.md).

**What made the difference:** the first version's length "rescue" silently replaced the model's chosen hook in 27% of
candidates; the final validator never edits the hook or cliffhanger. Low reasoning effort on the candidate step made each
call about 40× faster (172 s to 4 s) without losing the key scenes.

---

## 8. Market Analysis: How Competitors Promote

ReelShort, DramaBox and their peers win viewers mainly through paid short-video ads, and they cut those ads from the shows
themselves; their ad pool is effectively their content library. We studied their running ads and published industry
analyses. Each observation set a design rule:

* **Long cuts lead paid feeds.** Most of the competitors' top video ads we reviewed were 10–30-minute compilations, not
  short clips. A 20–60 s pick therefore also has to work as the cold open of a long ad, which is why the 3-second hook is
  enforced in code rather than left to the model.
* **Hidden identity sells.** Secret heirs, disguised billionaires and "years later he returns" were the most common
  premises in competitors' ad copy, alongside revenge, contract marriage and betrayal. So the show's title twist ("he was a
  Duke") is treated as a selling point, not a spoiler, and genre fit is scored.
* **Ads open on conflict and come from episode 1.** Long-running drama ads most often open mid-conflict rather than on
  set-up, and ReelShort's best-known creative was cut from episode 1. Hence camera-only hooks are rejected and early
  episodes get a small ranking preference.
* **Volume is the bottleneck.** Short-drama apps run thousands of creative variations, and each wears out within days.
  Hand-picking moments cannot keep that pace, which is the gap this tool fills.

Sources: [docs/research.md](docs/research.md).

---

## 9. Where It Picks Badly

* **Strict length rule:** 16 of 36 rejections were too long or too short; good moments can be lost when the model cannot fit them.
* **Weak endings:** some clips stop on a sad or throwaway line instead of an open question.
* **Noise below the top 5:** the same clip's judge score varies by 0.5–1 point between runs.
* **Blind spots:** visual hooks are read from text, judge and picker are the same model family, and there is no
  human-labelled ground truth. A live split test (hook rate, hold rate, click-through) is the real measure.

---

## 10. Alternatives Considered and Rejected

* **Model-written timestamps:** the first prompts asked for times directly; the model cannot do timestamp arithmetic
  reliably (an 86 s clip when asked for 25–55 s). Line IDs plus code-computed times replaced this.
* **Code repairing clips by itself:** moving the start to fit 20–60 s silently changed the hook. Code now only proposes
  legal alternatives and the model chooses.
* **One call for the whole show:** proposals were too few and too vague; one call per episode gave three usable candidates each.
* **Trusting the judge's per-clip spoiler flag:** it changed between runs and flagged the title twist; a per-show vote replaced it.
* **A Streamlit app:** slow to start and generic; replaced by a static site that runs the pipeline in the browser.
* **LiteLLM as the model client:** avoided after reports of compromised releases; the plain `openai` SDK is used instead.

---

## 11. Report

The two-page report, [PromoFinder.pdf](PromoFinder.pdf), covers the problem choice and assumptions, the method, results,
failure cases, scale and the market research. Its source is in [docs/paper/](docs/paper); the figure is regenerated with
`python scripts/utils/make_figures.py`.
