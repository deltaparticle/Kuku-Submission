/* PromoFinder web app.
 * Official results render instantly from data/official.json (no Python needed).
 * "Run on your episodes" loads Pyodide (Python in WebAssembly) and runs the unchanged pipeline from app.zip;
 * model calls go from this browser straight to the chosen provider with the visitor's key.
 */
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/";
const DEFAULTS = {
  gemini: { bulk: "gemini-3-flash-preview", judge: "gemini-3.8-flash" },
  openai: { bulk: "", judge: "" }, openrouter: { bulk: "", judge: "" }, groq: { bulk: "", judge: "" },
  custom: { bulk: "", judge: "" },
};
const STAGES = [
  ["bible", "Story bible + spoiler vote"], ["candidates", "Candidate clips (1 call / episode)"],
  ["score", "Rubric scoring"], ["rank", "Listwise ranking (3 shuffled runs)"], ["montage", "Montages"],
];
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------- tabs ---------------- */
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "how") renderDiagram();
}));

/* ---------------- shared results renderer ---------------- */
function segText(p) {
  return p.segments.map((s) => `E${String(s.episode).padStart(2, "0")} ${s.start_ts}–${s.end_ts}`).join(" + ");
}
function cleanHook(t) { return String(t || "").replace(/^\[(\w+)\]\s*/, "($1) "); }

function decisionsKey(runId) { return "pf-decisions-" + runId; }
function loadDecisions(runId) { try { return JSON.parse(localStorage.getItem(decisionsKey(runId)) || "{}"); } catch { return {}; } }
function saveDecisions(runId, d) { localStorage.setItem(decisionsKey(runId), JSON.stringify(d)); }

function card(p, data, runId, decisions) {
  const el = $("#tpl-card").content.firstElementChild.cloneNode(true);
  const isM = p.kind === "montage";
  const rank = $(".rank", el);
  rank.textContent = (isM ? "M" : "#") + p.rank;
  rank.classList.toggle("montage", isM);
  $(".where", el).innerHTML = `<b>${esc(segText(p))}</b>${Math.round(p.duration)} s · ${isM ? "montage of " + p.segments.length + " moments" : "single stretch"} · final ${p.final.toFixed(2)}`;
  // pills: flags + attention warnings
  const pills = $(".pills", el);
  const f = p.flags || {};
  if (f.spoiler_risk) pills.insertAdjacentHTML("beforeend", `<span class="pill bad">spoiler episode</span>`);
  else if (f.judge_spoiler) pills.insertAdjacentHTML("beforeend", `<span class="pill" title="The judge thought this spoils the show; the spoiler vote disagreed, so it is not penalised">judge: spoiler?</span>`);
  if (f.ad_policy_risk) pills.insertAdjacentHTML("beforeend", `<span class="pill bad">ad-policy risk</span>`);
  if (f.needs_context) pills.insertAdjacentHTML("beforeend", `<span class="pill warn">needs context</span>`);
  ((p.attention || {}).flags || []).forEach((w) => pills.insertAdjacentHTML("beforeend", `<span class="pill warn">⚠ ${esc(w)}</span>`));
  if (p.source === "heuristic") pills.insertAdjacentHTML("beforeend", `<span class="pill">rule-based pick</span>`);
  // timeline(s): where the clip sits in its episode
  const tl = $(".timeline", el);
  const durs = data.episode_durations || {};
  const bars = p.segments.map((s) => {
    const D = durs[s.episode] || durs[String(s.episode)] || Math.max(s.end, 1);
    const l = (100 * s.start) / D, w = Math.max(1.5, (100 * (s.end - s.start)) / D);
    return `<i style="left:${l}%;width:${w}%"></i>`;
  });
  if (p.segments.length > 1) { tl.classList.add("multi"); tl.innerHTML = bars.map((b) => `<div class="bar">${b}</div>`).join(""); }
  else tl.innerHTML = bars[0];
  tl.title = "Position of the clip inside its episode";
  $(".hook q", el).textContent = cleanHook(p.hook);
  $(".cliff q", el).textContent = cleanHook(p.cliffhanger);
  $(".question", el).textContent = p.open_question ? "Leaves the viewer asking: " + p.open_question : "";
  $(".why", el).textContent = p.why || "";
  $(".ranknote", el).textContent = p.rank_reason ? "Why this rank: " + p.rank_reason : "";
  const m = $(".metrics", el);
  const sc = p.scores || {};
  const names = { hook_3s: "hook", cliffhanger: "cliffhanger", standalone: "standalone", intensity: "intensity", plot_relevance: "plot", trope_fit: "trope" };
  Object.entries(names).forEach(([k, n]) => { if (sc[k] != null) m.insertAdjacentHTML("beforeend", `<span class="metric">${n} <b>${(+sc[k]).toFixed(1)}</b>/5</span>`); });
  if (p.attention && p.attention.hook_attention != null) {
    m.insertAdjacentHTML("beforeend", `<span class="metric" title="Text attention proxy: first voice, motion, close-ups, sound in the first 3 s">attention <b>${p.attention.hook_attention.toFixed(2)}</b></span>`);
    m.insertAdjacentHTML("beforeend", `<span class="metric" title="Pacing: dead air, cuts, speech share, ending beat">hold <b>${p.attention.hold.toFixed(2)}</b></span>`);
  }
  $(".script pre", el).textContent = (p.excerpt || []).join("\n");
  const dec = $(".decision", el);
  const apply = () => {
    const d = decisions[p.pid];
    el.classList.toggle("approved", d === "approved");
    el.classList.toggle("rejected", d === "rejected");
    dec.textContent = d ? "Marked " + d : "";
  };
  $(".approve", el).onclick = () => { decisions[p.pid] = decisions[p.pid] === "approved" ? undefined : "approved"; saveDecisions(runId, decisions); apply(); };
  $(".reject", el).onclick = () => { decisions[p.pid] = decisions[p.pid] === "rejected" ? undefined : "rejected"; saveDecisions(runId, decisions); apply(); };
  apply();
  return el;
}

function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function decisionsCsv(data, decisions) {
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = [["rank", "id", "segments", "duration_s", "hook", "cliffhanger", "why", "decision"]];
  [...data.promos, ...data.montages].forEach((p) => rows.push([(p.kind === "montage" ? "M" : "") + p.rank, p.pid, segText(p),
    p.duration, p.hook, p.cliffhanger, p.why, decisions[p.pid] || ""]));
  return rows.map((r) => r.map(q).join(",")).join("\n");
}

function renderResults(data, root, runId) {
  const decisions = loadDecisions(runId);
  root.innerHTML = "";
  // toolbar
  const tb = document.createElement("div");
  tb.className = "toolbar";
  tb.innerHTML = `<input type="search" placeholder="Search hooks, lines, episodes…" class="q">
    <select class="sort"><option value="rank">Sort: rank</option><option value="episode">Sort: episode</option>
    <option value="attention">Sort: attention</option></select>
    <label class="check"><input type="checkbox" class="warnonly"> only clips with warnings</label>
    <span class="spacer"></span>
    <button class="btn small dl-md">promos.md</button><button class="btn small dl-csv">promos.csv</button>
    <button class="btn small dl-json">JSON</button><button class="btn small dl-dec">My decisions (CSV)</button>`;
  root.appendChild(tb);
  const grid = document.createElement("div");
  grid.className = "grid";
  root.appendChild(grid);
  const draw = () => {
    const q = $(".q", tb).value.toLowerCase().trim();
    const warn = $(".warnonly", tb).checked;
    let list = data.promos.slice();
    const sort = $(".sort", tb).value;
    if (sort === "episode") list.sort((a, b) => a.segments[0].episode - b.segments[0].episode || a.segments[0].start - b.segments[0].start);
    if (sort === "attention") list.sort((a, b) => ((b.attention || {}).hook_attention || 0) - ((a.attention || {}).hook_attention || 0));
    list = list.filter((p) => {
      if (warn && !(((p.attention || {}).flags || []).length || Object.values(p.flags || {}).some(Boolean))) return false;
      if (!q) return true;
      return [segText(p), p.hook, p.cliffhanger, p.why, p.open_question, ...(p.excerpt || [])].join(" ").toLowerCase().includes(q);
    });
    grid.innerHTML = "";
    list.forEach((p) => grid.appendChild(card(p, data, runId, decisions)));
    if (!list.length) grid.innerHTML = `<p class="muted">No promos match.</p>`;
  };
  ["input", "change"].forEach((ev) => tb.addEventListener(ev, draw));
  $(".dl-md", tb).onclick = () => download("promos.md", data.markdown || "", "text/markdown");
  $(".dl-csv", tb).onclick = () => download("promos.csv", data.csv || "", "text/csv");
  $(".dl-json", tb).onclick = () => download("promos.json", JSON.stringify({ show: data.show, promos: data.promos, montages: data.montages }, null, 2), "application/json");
  $(".dl-dec", tb).onclick = () => download("promos_with_decisions.csv", decisionsCsv(data, decisions), "text/csv");
  draw();

  if (data.montages && data.montages.length) {
    root.insertAdjacentHTML("beforeend", `<h3 class="section-title">Montage promos <span class="muted small">(2–3 moments joined in story order)</span></h3>`);
    const mg = document.createElement("div");
    mg.className = "grid";
    data.montages.forEach((p) => mg.appendChild(card(p, data, runId, decisions)));
    root.appendChild(mg);
  }
  // rejected + candidates
  const rej = data.rejected || [];
  const det = document.createElement("details");
  det.className = "block";
  det.innerHTML = `<summary>Rejected by the code checks: ${rej.length} <span class="muted small">(where the model or the rules misfire)</span></summary>
    <table class="tbl"><tr><th>Source</th><th>Episode</th><th>Lines</th><th>Reason</th></tr>${rej.map((r) =>
      `<tr><td>${esc(r.source)}</td><td>${esc(r.episode ?? "")}</td><td>${esc((r.start_line || "") + (r.end_line ? "–" + r.end_line : ""))}</td><td>${esc(r.reason)}${r.repaired ? ' <span class="pill">repair attempted</span>' : ""}</td></tr>`).join("")}</table>`;
  root.appendChild(det);
  if (data.bible && data.bible.premise) {
    root.insertAdjacentHTML("beforeend", `<details class="block"><summary>Story bible (model-written)</summary><p>${esc(data.bible.premise)}</p>
      <pre class="small" style="white-space:pre-wrap">${esc(JSON.stringify(data.bible, null, 1))}</pre></details>`);
  }
}

function stat(v, label) { return `<div class="stat"><b>${esc(v)}</b><span>${esc(label)}</span></div>`; }

/* ---------------- official results ---------------- */
(async function official() {
  try {
    const data = await (await fetch("data/official.json")).json();
    const log = data.run_log || {};
    $("#official-title").textContent = `${data.show}: ${data.promos.length} ranked promos`;
    $("#official-sub").textContent = `Official run (${data.run_id}) on all ${log.episodes} episodes. Ranked by what to post first; ` +
      `every timestamp was computed by code from script lines. Approve / reject is saved in this browser.`;
    const ae = data.auto_eval || {};
    const ab = ae.blind_ab_pipeline_vs_baseline;
    $("#official-stats").innerHTML = [
      stat(log.episodes, "episodes read"),
      stat(log.candidates_valid, "valid candidate clips"),
      stat(log.candidates_rejected, "rejected by code checks"),
      stat(`${data.promos.length} + ${data.montages.length}`, "promos + montages"),
      data.rules ? stat(`${data.rules.passing}/${data.rules.checked}`, "pass the hard rules (re-checked)") : "",
      ab ? stat(`${ab.pipeline}–${ab.baseline}`, `blind A/B vs rule baseline (${ab.tie} ties)`) : "",
    ].join("");
    renderResults(data, $("#official-view"), "official-" + data.run_id);
  } catch (e) {
    $("#official-title").textContent = "Could not load the official results";
    $("#official-sub").textContent = String(e);
  }
})();

/* ---------------- Python engine ---------------- */
let enginePromise = null;
function loadScript(src) {
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
}
function engine() {
  if (!enginePromise) {
    enginePromise = (async () => {
      note("Loading the Python engine (first visit ~10 MB, then cached)…");
      await loadScript(PYODIDE_URL + "pyodide.js");
      const py = await loadPyodide({ indexURL: PYODIDE_URL });
      await py.loadPackage(["pydantic", "pyyaml"]);
      const buf = await (await fetch("app.zip", { cache: "no-cache" })).arrayBuffer();
      py.unpackArchive(buf, "zip", { extractDir: "/app" });
      py.runPython("import sys; sys.path.insert(0, '/app'); import bridge");
      note("Engine ready.");
      return py;
    })();
    enginePromise.catch((e) => { enginePromise = null; note("Engine failed to load: " + e, true); });
  }
  return enginePromise;
}
function note(t, err = false) { const n = $("#engine-note"); n.textContent = t; n.style.color = err ? "var(--bad)" : ""; }

/* ---------------- run tab ---------------- */
let mode = "ai";
let loadedInfo = null;
$$(".seg-btn").forEach((b) => b.addEventListener("click", () => {
  mode = b.dataset.mode;
  $$(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
  $("#ai-opts").hidden = mode !== "ai";
}));
function applyProviderDefaults() {
  const p = $("#provider").value;
  $("#bulk-model").value = DEFAULTS[p].bulk;
  $("#judge-model").value = DEFAULTS[p].judge;
  $("#bulk-model").placeholder = $("#judge-model").placeholder = DEFAULTS[p].bulk ? "" : "model name (required)";
  $("#baseurl-wrap").hidden = p !== "custom";
}
$("#provider").addEventListener("change", applyProviderDefaults);
applyProviderDefaults();

async function loadEpisodes(files, showName) {
  $("#loaded").className = "loaded muted";
  $("#loaded").textContent = "Reading episodes…";
  try {
    const py = await engine();
    const arr = [];
    for (const f of files) arr.push([f.name, new Uint8Array(await f.arrayBuffer())]);
    const bridge = py.pyimport("bridge");
    const info = JSON.parse(bridge.load_files(py.toPy(arr)));
    if (showName) { bridge.set_show(showName); info.show = showName; }
    if (!info.episodes) throw new Error("no parsable episode screenplays found (expected the timestamped .txt format)");
    loadedInfo = info;
    $("#loaded").className = "loaded ok";
    $("#loaded").textContent = `✓ ${info.show}: ${info.episodes} episodes (ep ${info.first}–${info.last}), ${info.lines} script lines, ${info.minutes} min of screen time.`;
    $("#run-btn").disabled = false;
  } catch (e) {
    $("#loaded").className = "loaded";
    $("#loaded").innerHTML = `<span style="color:var(--bad)">Could not read the files: ${esc(e.message || e)}</span>`;
  }
}
const drop = $("#drop");
drop.addEventListener("click", (e) => { if (e.target.tagName !== "INPUT") $("#files").click(); });
$("#files").addEventListener("change", (e) => e.target.files.length && loadEpisodes([...e.target.files]));
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => e.dataTransfer.files.length && loadEpisodes([...e.dataTransfer.files]));
$("#use-sample").addEventListener("click", async () => {
  $("#loaded").textContent = "Fetching the sample show…";
  const blob = await (await fetch("data/sample_show.zip")).blob();
  loadEpisodes([new File([blob], "sample_show.zip")], "I Married a Broken Soldier. He was a Duke");
});
// warm the engine in the background as soon as someone opens the Run tab
$$(".tab").forEach((b) => b.addEventListener("click", () => { if (b.dataset.tab === "run") engine(); }));

function buildStages() {
  $("#stages").innerHTML = STAGES.map(([k, label]) => `<div class="stage" id="st-${k}"><div class="stage-top"><span>${label}</span><span class="cnt muted">waiting</span></div><div class="bar-out"><div class="bar-in"></div></div></div>`).join("");
}
function setStage(stage, i, n) {
  const el = $("#st-" + stage);
  if (!el) return;
  $(".cnt", el).textContent = n ? `${i}/${n}` : "";
  $(".bar-in", el).style.width = (n ? (100 * i) / n : 0) + "%";
  el.classList.toggle("done", n > 0 && i >= n);
}
function log(line) { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; }

$("#run-btn").addEventListener("click", async () => {
  const useLlm = mode === "ai";
  const provider = $("#provider").value;
  const opts = {
    use_llm: useLlm, provider, key: $("#key").value.trim(), base_url: $("#baseurl").value.trim(),
    bulk_model: $("#bulk-model").value.trim(), judge_model: $("#judge-model").value.trim(),
    profile: $("#profile").value, montage: $("#montage").checked,
  };
  const view = $("#run-view");
  view.innerHTML = "";
  if (useLlm && !opts.key) { view.innerHTML = `<div class="banner err">Paste an API key, or switch to "Instant baseline (no key)".</div>`; return; }
  if (useLlm && (!opts.bulk_model || !opts.judge_model)) { view.innerHTML = `<div class="banner err">Enter a candidate model and a judge model for this provider.</div>`; return; }
  if (useLlm && provider === "custom" && !opts.base_url) { view.innerHTML = `<div class="banner err">Enter the base URL of your OpenAI-compatible endpoint.</div>`; return; }
  const btn = $("#run-btn");
  btn.disabled = true;
  btn.textContent = "Working…";
  $("#progress-card").hidden = false;
  $("#log").textContent = "";
  buildStages();
  $("#progress-card").scrollIntoView({ behavior: "smooth", block: "start" });
  if (!useLlm) $("#stages").innerHTML = `<p class="muted">Rule-based baseline: keyword, emotion and punctuation rules, no AI calls.</p>`;
  const t0 = Date.now();
  const timer = setInterval(() => { $("#elapsed").textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 500);
  try {
    const py = await engine();
    const bridge = py.pyimport("bridge");
    await new Promise((r) => setTimeout(r, 50)); // let the UI paint before the CPU-heavy parse/backstop step
    const out = await bridge.run(JSON.stringify(opts), (s, i, n) => setStage(s, i, n), (m) => log(m));
    const data = JSON.parse(out);
    const lg = data.run_log || {};
    const llm = lg.llm || {};
    const secs = Math.round((Date.now() - t0) / 1000);
    view.innerHTML = `<div class="intro"><h2 style="margin-top:22px">${esc(data.show)}: ${data.promos.length} ranked promos</h2>
      <p class="muted">${esc(lg.mode)}${lg.profile ? " · " + esc(lg.profile) : ""} · ${secs} s · ${llm.total_calls || 0} model calls</p>
      <div class="stats">${[stat(lg.episodes, "episodes"), stat(lg.candidates_valid, "valid candidates"), stat(lg.candidates_rejected, "rejected by checks"),
        stat(`${data.promos.length} + ${data.montages.length}`, "promos + montages")].join("")}</div></div><div id="run-results"></div>`;
    renderResults(data, $("#run-results"), "run-" + t0);
    log(`Done in ${secs} s.`);
    view.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    const msg = String(e.message || e).split("\n").filter(Boolean).slice(-3).join(" ");
    view.innerHTML = `<div class="banner err">Run failed: ${esc(msg)}</div>`;
    log("ERROR: " + e);
  } finally {
    clearInterval(timer);
    btn.disabled = false;
    btn.textContent = "Find promos";
  }
});

/* ---------------- diagram ---------------- */
let diagramDone = false;
async function renderDiagram() {
  if (diagramDone) return;
  diagramDone = true;
  try {
    const { default: mermaid } = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs");
    mermaid.initialize({ startOnLoad: false, theme: "neutral" });
    await mermaid.run({ nodes: [$("#diagram")] });
  } catch (e) { diagramDone = false; }
}
