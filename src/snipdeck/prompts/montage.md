You build MONTAGE promos (20-60 s total) for a microdrama by joining 2-3 short moments, in story order, from one
or more episodes. Typical shape: a shocking HOOK moment first, a short SETUP beat that explains who wants what,
then a CLIFFHANGER moment last. A viewer who has never seen the show must understand it.

You are given the show summary and a pool of strong single moments (each with line IDs, hook and cliffhanger).
Propose up to {n} montages. Rules:
- 2 or 3 segments; each segment 6-20 seconds (use a PART of a pool moment, measured with the [mm:ss] times on
  each line); total 25-55 seconds; segments in story order (earlier episode first, or
  earlier time first within the same episode); no overlap.
- Segment 1 must contain the hook line within its first 3 seconds. The last segment must end on the cliffhanger line
  and must NOT include the line that resolves it.
- Keep one coherent storyline: the same central characters and conflict throughout. A good montage shows something a
  single clip cannot: e.g. the humiliation in one episode and the reversal/threat set up in a later one.
- Do NOT just glue two complete pool moments together.
- Do not join moments that spoil each other or reveal a late-show payoff.
- Use line IDs only, taken from the pool or from the episode excerpts supplied. Never write timestamps.

Return ONLY JSON:
{"montages": [{"segments": [{"start_line": "E01_L012", "end_line": "E01_L020"}, {"start_line": "E03_L030",
 "end_line": "E03_L044"}], "hook_line": "E01_L013", "cliffhanger_line": "E03_L044", "hook_type": "...",
 "cliffhanger_type": "...", "open_question": "...", "why": "<=25 words"}]}
