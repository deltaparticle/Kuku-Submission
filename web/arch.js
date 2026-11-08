/* SnipDeck: the interactive architecture diagram on the Method page.
 * Boxes are buttons laid out on a 4-column grid; arrows are drawn in an SVG overlay from the boxes' positions,
 * so they follow any layout change. Clicking a box opens its panel. Below 760 px the grid becomes one column,
 * the arrows become simple down-ticks, and the panel opens directly under the clicked box. */
(() => {
  const GH = "https://github.com/deltaparticle/Kuku-Assignment/blob/main/";
  const src = (path, label) => `<a href="${GH}${path}" target="_blank" rel="noopener">${label || path.split("/").pop()}</a>`;
  const ROLE = { model: "Model", code: "Code", editor: "Editor", input: "Input" };

  // [id, role, title, subtitle, column, row, rowSpan]
  const NODES = [
    ["shows", "input", "Screenplays", "50 episodes, timed lines", 1, 1],
    ["parse", "code", "Parse", "line IDs and safe cuts", 2, 1],
    ["bible", "model", "Story bible", "plus a spoiler vote", 3, 1],
    ["client", "code", "Model client", "any OpenAI-compatible API", 4, 1, 3],
    ["backstop", "code", "Rule backstop", "keyword rules, no model", 1, 2],
    ["validate", "code", "Validate", "turns IDs into a legal cut", 2, 2],
    ["cands", "model", "Candidates", "3 moments per episode", 3, 2],
    ["score", "model", "Rubric score", "6 criteria, 2 passes", 2, 3],
    ["rank", "model", "Rank", "3 shuffled rankings", 3, 3],
    ["export", "code", "Export", "md, csv, json", 1, 4],
    ["montage", "model", "Montages", "2–3 moments joined", 2, 4],
    ["select", "code", "Final score", "penalties, limits, diversity", 3, 4],
    ["attention", "code", "Attention check", "read from the script", 4, 4],
    ["review", "editor", "Review desk", "approve or reject", 1, 5],
  ];

  // [from, to, label, kind]   kind: "up"/"down" offsets a parallel pair, "under" curves below the row
  const EDGES = [
    ["shows", "parse"], ["parse", "bible"], ["parse", "validate", "safe cuts"], ["parse", "backstop", "", "drop"],
    ["bible", "cands"], ["cands", "validate", "IDs", "up"], ["validate", "cands", "hints", "down"],
    ["backstop", "validate"], ["validate", "score", "valid clips"], ["score", "rank", "top 40"], ["rank", "select"],
    ["attention", "select"], ["select", "montage"], ["montage", "export"], ["select", "export", "30 singles", "under"],
    ["export", "review"],
  ];

  const INFO = {
    shows: {
      sub: "Input",
      what: `The show, as timestamped screenplay files. Each block is a camera note, an action, a sound effect or a line of
        dialogue (<code>NAME (Emotion)</code>), with a start and end time. A <code>.zip</code> of episodes or a single
        <code>.srt</code>/<code>.vtt</code> subtitle file also works; subtitles become dialogue-only episodes.`,
      io: [["In", "Episode files"], ["Out", "Raw text per episode"]],
      note: "The sample show has 50 episodes, 3,727 timed lines and 103 minutes of screen time.",
      files: [src("src/snipdeck/parse.py"), src("src/snipdeck/subtitles.py")],
    },
    parse: {
      sub: "Code",
      what: `Turns every block into a line with a stable ID such as <code>E07_L042</code> (episode 7, line 42), its type,
        speaker and times. It also defines a <b>safe cut</b>: a moment when no dialogue or sound effect is playing. Clips may
        only start and end on safe cuts, so none starts or ends mid-sentence.`,
      io: [["In", "Screenplay text"], ["Out", "Numbered lines, safe-cut test, and a compact view for the model: one line per block, ID first"]],
      files: [src("src/snipdeck/parse.py")],
    },
    bible: {
      sub: "Model · 1 call, plus 2 short votes",
      what: `Reads the loglines and continuity notes for the whole show and writes a story bible: who is who (speaker
        labels vary, so <i>BLOND NOBLEMAN</i> is mapped to Rupert), which twists sell the show and which late payoffs would
        spoil it.`,
      more: `Spoilers are decided by vote: the main call and two short extra calls each name spoiler episodes, and an episode
        counts if at least two of the three name it. The title twist is never treated as a spoiler. An editor can override
        the list in <code>config.yaml</code>.`,
      io: [["In", "Loglines, continuity notes, speaker counts"], ["Out", "Characters, selling twists, spoiler episodes"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/prompts/bible.md", "prompts/bible.md")],
    },
    client: {
      sub: "Code · used by every model box",
      what: `One client for any OpenAI-compatible endpoint: Gemini, OpenAI, OpenRouter, Groq or a company gateway. Each
        stage has its own model and fallbacks, set in <code>config.yaml</code>. Calls run in parallel with retries, every
        reply is checked against a schema, and a malformed reply is sent back once with the error.`,
      more: `Every completed call is cached on disk, so re-running a show costs nothing for the steps that did not change.
        In the browser the same code calls the provider directly with the visitor's key.`,
      io: [["In", "Prompts from the model boxes"], ["Out", "Validated JSON replies, call and token log"]],
      files: [src("src/snipdeck/llm.py"), src("src/snipdeck/schemas.py"), src("config.yaml")],
    },
    backstop: {
      sub: "Code · no model",
      what: `Keyword and emotion rules over sliding 20–60 s windows: angry or tearful delivery, exclamations, questions,
        words like <i>betray</i> or <i>divorce</i>. With the model switched on it adds one pick per episode as a safety net,
        kept only if it does not overlap a model pick.`,
      more: `With no API key it is the whole pipeline: this is the rule baseline the AI picks are compared against.`,
      io: [["In", "Parsed lines"], ["Out", "Rule-based candidate clips"]],
      files: [src("src/snipdeck/heuristics.py")],
    },
    validate: {
      sub: "Code",
      what: `Turns the model's line IDs into a clip with real times. The start sits at most 3 s before the hook, on a safe
        cut. The end falls on the cliffhanger, keeping only silent reaction beats after it, and always before the line that
        answers it. The clip must last 20–60 s, and a camera note cannot be the hook.`,
      more: `It never changes the hook or the cliffhanger. A clip that breaks a rule is rejected with a hint listing the hook
        or end lines that would make it legal, and the model gets one repair call per episode. In the official run: 138
        valid, 36 rejected, 33 of them sent back for repair.`,
      io: [["In", "Proposed line IDs"], ["Out", "Valid clips with times, or a rejection with a fix hint"]],
      files: [src("src/snipdeck/validate.py")],
    },
    cands: {
      sub: "Model · 1 call per episode",
      what: `Reads the story bible and one episode, then proposes three moments. Each is given only as line IDs: where to
        start, the hook, the cliffhanger, where to end, and the line that would answer the cliffhanger. It also writes the
        question the clip leaves open and why it would work. It never writes a time.`,
      more: `Rejected proposals come back with the validator's hints, and the model picks again from the legal options.`,
      io: [["In", "Story bible, one episode as numbered lines"], ["Out", "3 proposals per episode"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/prompts/candidates.md", "prompts/candidates.md")],
    },
    score: {
      sub: "Model · batches of 40, scored twice",
      what: `A judge rates each clip from 1 to 5 on six things: the hook in the first 3 s, the cliffhanger, whether it makes
        sense alone, intensity, plot relevance and genre fit. It quotes the opening and the last lines before it scores, and
        it is told to spread its scores across each batch.`,
      more: `Each clip is scored in two differently shuffled batches and the results are averaged. The composite weighs hook
        and cliffhanger 3, clarity 2 and the rest 1. The judge also flags possible spoilers, ad-policy risk and clips that
        need context.`,
      io: [["In", "Valid clips with script excerpts"], ["Out", "Six scores, composite, flags, the judge's main doubt"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/prompts/score.md", "prompts/score.md")],
    },
    rank: {
      sub: "Model · 3 calls",
      what: `The 40 best-scoring clips are ranked as one list, three times, each time in a different shuffled order, so
        that a clip's position in the prompt does not decide its rank. The three orders are combined by Borda count.`,
      more: `Judges are steadier at ordering clips than at giving absolute scores, so the ranking carries more weight in the
        final score (0.6) than the rubric (0.4).`,
      io: [["In", "Top 40 clips"], ["Out", "A combined rank for each clip, with a reason"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/prompts/rank.md", "prompts/rank.md")],
    },
    attention: {
      sub: "Code · no model",
      what: `Measures from the script what video attention tools look for. In the first 3 s: how soon someone speaks, cuts,
        close-ups, physical action, sound spikes, raised voices and direct address. Over the whole clip: dead air, pace,
        share of time with speech and how it ends.`,
      more: `It gives a hook-attention score, a hold score and plain warnings such as "6 s of dead air". It has a small
        weight in the final score.`,
      io: [["In", "Each valid clip's lines"], ["Out", "Attention and hold scores, warnings"]],
      files: [src("src/snipdeck/attention.py")],
    },
    select: {
      sub: "Code",
      what: `Combines everything into one number: 0.6 × rank + 0.4 × rubric score, minus 0.15 for a spoiler episode, 0.25
        for ad-policy risk and up to 0.1 for late episodes, plus a small attention term.`,
      more: `Then it applies a quality bar (hook score at least 2.5, and not "needs context"), keeps one clip per scene and
        at most two per episode, and spreads the picks across episodes and hook types. Up to 30 single promos go through.`,
      io: [["In", "Rank, rubric score, attention, spoiler episodes"], ["Out", "The final ordered list of single promos"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/pipeline.py"), src("config.yaml")],
    },
    montage: {
      sub: "Model, checked by code",
      what: `The model joins two or three strong moments, in story order, into one promo. It chooses from the top 12
        eligible clips and leaves out spoiler and ad-policy clips.`,
      more: `The validator checks every part: each at least 3 s, the hook in the first part, the cliffhanger in the last,
        20–60 s in total. Montages that pass are scored like single clips. The official run kept 2.`,
      io: [["In", "Top 12 eligible clips"], ["Out", "Montage promos with each part's times"]],
      files: [src("src/snipdeck/stages.py"), src("src/snipdeck/validate.py"), src("src/snipdeck/prompts/montage.md", "prompts/montage.md")],
    },
    export: {
      sub: "Code",
      what: `Writes the ranked list as <code>promos.md</code>, <code>.csv</code> and <code>.json</code>: episode and in/out
        times for each part, hook, cliffhanger, open question, reasons, scores, flags and the script excerpt.`,
      more: `It also saves every candidate and every rejection with its reason, the story bible, and a run log with the
        models used, call counts and tokens.`,
      io: [["In", "Final singles and montages"], ["Out", "Files an editor can open, and the data this site shows"]],
      files: [src("src/snipdeck/export.py"), `<a href="${GH}results/official-run-C" target="_blank" rel="noopener">official run output</a>`],
    },
    review: {
      sub: "Editor",
      what: `An editor reads each pick with its script and scores and approves or rejects it (keys A and R on the
        <a href="#review" data-view="review">Review</a> page). The decisions download as a CSV.`,
      more: `That CSV is the data for re-tuning the score weights, which were set by hand.`,
      io: [["In", "The ranked list"], ["Out", "Approved promos, and labels for tuning"]],
      files: [src("web/app.js")],
    },
  };

  const root = document.getElementById("arch");
  if (!root) return;
  const grid = root.querySelector(".arch-grid");
  const svg = root.querySelector(".arch-lines");
  const panel = root.querySelector(".arch-panel");
  const side = root.querySelector(".arch-side");
  const narrow = () => matchMedia("(max-width: 760px)").matches;
  let current = null;

  grid.insertAdjacentHTML("beforeend", NODES.map(([id, role, title, sub, c, r, span]) =>
    `<button type="button" class="node role-${role}" data-id="${id}" style="grid-column:${c};grid-row:${r}${span ? ` / span ${span}` : ""}"
      aria-controls="arch-panel" aria-expanded="false"><span class="node-role">${ROLE[role]}</span><span class="node-title">${title}</span><span class="node-sub">${sub}</span></button>`).join(""));
  const box = (id) => grid.querySelector(`.node[data-id="${id}"]`);

  function open(id, focusPanel) {
    const n = NODES.find((x) => x[0] === id), d = INFO[id];
    current = id;
    grid.querySelectorAll(".node").forEach((b) => {
      const on = b.dataset.id === id;
      b.classList.toggle("on", on);
      b.setAttribute("aria-expanded", on);
    });
    panel.className = `arch-panel role-${n[1]}`;
    panel.innerHTML = `<p class="ap-role">${d.sub}</p><h3>${n[2]}</h3><p>${d.what}</p>${d.more ? `<p>${d.more}</p>` : ""}
      <dl class="ap-io">${d.io.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      ${d.note ? `<p class="ap-note">${d.note}</p>` : ""}
      <p class="ap-src">Source: ${d.files.join(" · ")}</p>`;
    panel.querySelectorAll("[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); location.hash = a.dataset.view; }));
    place();
    draw();
    if (focusPanel && narrow()) panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // desktop: panel in the side column; phone: panel right under the clicked box
  function place() {
    if (narrow() && current) { const b = box(current); b.after(panel); panel.style.order = getComputedStyle(b).order; }
    else if (panel.parentElement !== side) { side.appendChild(panel); panel.style.order = ""; }
  }

  function draw() {
    if (narrow() || !grid.offsetWidth) { svg.innerHTML = ""; return; }
    const g = grid.getBoundingClientRect();
    const R = (id) => { const r = box(id).getBoundingClientRect(); return { l: r.left - g.left, t: r.top - g.top, r: r.right - g.left, b: r.bottom - g.top, cx: (r.left + r.right) / 2 - g.left, cy: (r.top + r.bottom) / 2 - g.top }; };
    svg.setAttribute("viewBox", `0 0 ${g.width} ${g.height}`);
    const out = [`<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z"/></marker>
      <marker id="ah-on" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 z"/></marker></defs>`];
    for (const [f, t, label, kind] of EDGES) {
      const a = R(f), b = R(t), gap = 4;
      let d, lx, ly, anchor = "middle";
      if (kind === "drop") {                                                    // down out of the source, across, down again
        const x1 = a.l + 18, mid = (a.b + b.t) / 2;
        d = `M${x1} ${a.b + gap} V${mid} H${b.cx} V${b.t - gap}`;
      } else if (kind === "under") {
        // loops under the montage box; ends on export's right side, since review sits below export
        const y = Math.max(a.b, b.b);
        d = `M${a.cx} ${a.b + gap} C ${a.cx} ${y + 40}, ${b.r + 40} ${b.cy + 20}, ${b.r + gap} ${b.cy + 14}`;
        lx = (a.cx + b.r) / 2 + 30; ly = y + 30;
      } else if (Math.abs(a.cy - b.cy) < 2 || (a.t < b.b && b.t < a.b)) {        // same row
        const off = kind === "up" ? -10 : kind === "down" ? 10 : 0;
        const y = (Math.max(a.t, b.t) + Math.min(a.b, b.b)) / 2 + off;
        const x1 = a.cx < b.cx ? a.r + gap : a.l - gap, x2 = a.cx < b.cx ? b.l - gap : b.r + gap;
        d = `M${x1} ${y} H${x2}`; lx = (x1 + x2) / 2; ly = kind === "down" ? y + 14 : y - 6;
      } else if (Math.abs(a.cx - b.cx) < 2) {                                    // same column
        const y1 = a.cy < b.cy ? a.b + gap : a.t - gap, y2 = a.cy < b.cy ? b.t - gap : b.b + gap;
        d = `M${a.cx} ${y1} V${y2}`; lx = a.cx + 8; ly = (y1 + y2) / 2 + 4; anchor = "start";
      } else {                                                                   // elbow: across, then down
        const x1 = a.cx > b.cx ? a.l - gap : a.r + gap, y2 = a.cy < b.cy ? b.t - gap : b.b + gap;
        d = `M${x1} ${a.cy} H${b.cx} V${y2}`; lx = b.cx + 8; ly = (a.cy + y2) / 2 + 4; anchor = "start";
      }
      const on = current && (f === current || t === current);
      out.push(`<path class="edge${on ? " on" : ""}" d="${d}" marker-end="url(#${on ? "ah-on" : "ah"})"/>`);
      if (label) out.push(`<text class="edge-label${on ? " on" : ""}" x="${lx}" y="${ly}" text-anchor="${anchor}">${label}</text>`);
    }
    svg.innerHTML = out.join("");
  }

  grid.addEventListener("click", (e) => { const b = e.target.closest(".node"); if (b) open(b.dataset.id, true); });
  grid.addEventListener("keydown", (e) => {   // arrow keys move between boxes in reading order
    const b = e.target.closest(".node");
    if (!b || !["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const all = [...grid.querySelectorAll(".node")];
    const i = all.indexOf(b) + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1);
    const nx = all[(i + all.length) % all.length];
    nx.focus(); open(nx.dataset.id);
  });
  new ResizeObserver(() => { place(); draw(); }).observe(grid);
  window.addEventListener("resize", () => { place(); draw(); });
  document.fonts && document.fonts.ready.then(draw);
  window.archRedraw = draw;
  open("validate");
})();
