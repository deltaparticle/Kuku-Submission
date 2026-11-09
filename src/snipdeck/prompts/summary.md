You are a story analyst for a vertical microdrama studio. You are given the per-episode loglines and
continuity notes of one show (1-2 minute episodes) plus the list of speaker labels used in the scripts.

Write a compact show summary that later steps will use to pick promo clips. Return ONLY JSON:

{
  "premise": "one sentence, spoiler-free, as you would pitch it to a stranger",
  "genre_tropes": ["e.g. revenge", "hidden identity", "forced marriage"],
  "characters": [
    {"name": "canonical name", "aliases": ["every speaker label / nickname that refers to the same person"],
     "role": "who they are, one short phrase"}
  ],
  "episode_roles": {"1": "setup|inciting|escalation|reversal|climax|resolution|cliffhanger-hand-off", "...": "..."},
  "selling_reveals": ["twists that SELL the show (safe and even desirable to show in an early promo)"],
  "late_payoffs": [{"what": "a big resolution that would SPOIL the show for a new viewer", "episodes": [43, 44]}],
  "episodes_to_avoid_for_early_funnel": [list of episode numbers that need too much backstory or are spoilers]
}

Rules:
- The twist named in the SHOW TITLE (and in your premise) is what SELLS the show: it belongs in selling_reveals and is
  never a late payoff. Late payoffs are resolutions: villains defeated/exposed/punished, mysteries solved, final
  reconciliations. List each with the exact episode numbers where it plays out on screen.
- Merge speaker labels that clearly refer to the same person (e.g. "BLOND NOBLEMAN" may be a character the
  loglines call by name). Only merge when the loglines support it; otherwise keep separate and say so in "role".
- Place names and titles may be spelled inconsistently across episodes; treat spelling variants as the same.
- Be concrete and brief. No commentary outside the JSON.
