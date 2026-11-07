# AI usage log (required by the brief: which tools, and where they got it wrong)

A running record of how AI tools were used while building PromoFinder, and where they went wrong.

## Tools
- Claude Code (Claude Opus 5.5 / Sonnet 5.5): planning, code, tests, prompts.
- Web research via 3 parallel research sub-agents (market/ad practice, clipping tools, models & free tiers).
- Gemini API (free tier; gemini-3.5/3.1-flash-lite for the many-call stages, gemini-3-flash-preview and gemini-3.6-flash for
  the few-call stages, mixed by availability and daily quota). This is what the pipeline itself runs on; swappable in config.yaml.

## Where the AI got it wrong
1. **Validation bug caught by a test.** My first `validate.py` only trimmed a clip before the "answering" line when that
   line came *after* `end_line`. If the model set `end_line` to the answering line itself, the clip ran straight through
   the resolution (the exact failure the rule exists to stop). The unit test
   `test_clip_never_runs_into_the_answer` failed; fixed by cutting back to the line before the answer and checking the
   cliffhanger line is not at/after it.
2. **Code written against a Pydantic v2 model with undeclared attributes** (`p._final = ...`) would have raised at
   runtime; found on review and replaced with a declared `final` field.
3. **Invented import** (`_overlap_time`) in `pipeline.py`; caught on the first import check.
4. **Research claims to treat as unverified:** model names (`gemini-3.8-flash`, `gemini-3.5-flash-lite`), the "~20
   requests/day" free-tier figure, and the LiteLLM compromise reports came from sub-agent web research and were not
   re-checked on this machine. Verify before relying on them.

5. **Retry logic treated a connection error as fatal** (run 2 crashed after 48/50 episodes); fixed, plus per-batch
   graceful failure so one bad call cannot kill a 25-minute run.
6. **Wrong assumption about free tier**: I assumed per-minute limits and slept/retried; the real limit on the strong
   models was ~20 requests/DAY, so retrying was pointless. Fixed by detecting daily-quota errors and skipping the model.
7. **Model laziness**: the cheap model returned ~1 candidate per episode (asked for 3-5) and ignored the 60s limit
   (an 86s clip). Fixed by one-episode-per-call + deterministic start-trimming in code rather than trusting the model's
   arithmetic. (Good 'where the tool got it wrong' example: LLMs cannot reliably subtract timestamps.)

## Pipeline weaknesses observed on the rule-based baseline (real run, 50 episodes)
- Ranks late-arc villain-defeat episodes (42–44) first → spoiler problem the LLM bible/spoiler flag must fix.
- Hooks like `JULIANA: "Alexander..."` are weak; keyword rules cannot judge whether a line stops a scroll.
- Clips can begin mid-scene without the entrance that makes the moment make sense.
