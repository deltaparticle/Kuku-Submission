/* SnipDeck — review desk.
 * Review: official results from data/official.json (no Python needed), or the results of a run done in this tab.
 * Run: loads Pyodide (Python in WebAssembly) and the unchanged pipeline from app.zip; model calls go from this browser
 * straight to the chosen provider with the visitor's key.
 */
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/";
const DEFAULTS = {
  gemini: { bulk: "gemini-3-flash-preview", judge: "gemini-3.8-flash" },
  openai: { bulk: "", judge: "" }, openrouter: { bulk: "", judge: "" }, groq: { bulk: "", judge: "" }, custom: { bulk: "", judge: "" },
};
const STAGES = [["bible", "Story bible"], ["candidates", "Candidate clips"], ["score", "Scoring"], ["rank", "Ranking"], ["montage", "Montages"]];
const SCORE_NAMES = [["hook_3s", "Hook, first 3 s"], ["cliffhanger", "Cliffhanger"], ["standalone", "Makes sense alone"],
  ["intensity", "Intensity"], ["plot_relevance", "Plot relevance"], ["trope_fit", "Genre fit"]];

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const toSec = (ts) => { const [m, s] = String(ts).split(":"); return (+m) * 60 + (+s); };
const tc = (sec) => `${pad(Math.floor(sec / 60))}:${(sec % 60).toFixed(2).padStart(5, "0")}`;
const short = (sec) => `${Math.floor(sec / 60)}:${pad(Math.floor(sec % 60))}`;

/* ---------------- views ---------------- */
const VIEWS = ["home", "review", "run", "method"];
function show(view) {
  if (!VIEWS.includes(view)) view = "home";
  const was = document.body.dataset.view;
  document.body.dataset.view = view;
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + view));
  $$(".nav-links a[data-view]").forEach((a) => a.classList.toggle("on", a.dataset.view === view));
  pillTo($(".nav-links a.on"));
  if (view === "run") engine();
  if (was && was !== view) window.scrollTo({ top: 0 });
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
}
$$("[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.view); }));

/* floating nav: a pill that springs to the hovered link and settles back on the current one */
function pillTo(a) {
  const pill = $("#nav-pill");
  if (!a || !a.offsetWidth) { pill.style.opacity = 0; return; }
  pill.style.opacity = 1;
  pill.style.width = a.offsetWidth + "px";
  pill.style.transform = `translateX(${a.offsetLeft}px)`;
}
$$(".nav-links a").forEach((a) => a.addEventListener("mouseenter", () => pillTo(a)));
$("#nav-links").addEventListener("mouseleave", () => pillTo($(".nav-links a.on")));
window.addEventListener("resize", () => pillTo($(".nav-links a.on")));
document.fonts && document.fonts.ready.then(() => pillTo($(".nav-links a.on")));

/* footer clock: the builder's time zone */
function clock() {
  const t = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
  $("#clock").textContent = `${t} IST · made in India`;
}
clock(); setInterval(clock, 30000);

/* landing: the real #1 pick from the official run */
function heroSample(data) {
  const p = data.promos && data.promos[0];
  if (!p) return;
  const s = p.segments[0], e = p.segments[p.segments.length - 1];
  const D = (data.episode_durations || {})[s.episode] || (data.episode_durations || {})[String(s.episode)] || s.end;
  $("#hs-rank").textContent = "#" + p.rank;
  $("#hs-where").textContent = `Episode ${s.episode} · ${short(s.start)}–${short(e.end)} · ${Math.round(p.duration)} s`;
  $("#hs-hook").textContent = lineText(p.hook);
  $("#hs-ends").textContent = lineText(p.cliffhanger);
  $("#hs-q").textContent = p.open_question ? "Leaves you asking: " + p.open_question : "";
  const bar = $("#hs-bar");
  bar.style.left = (100 * s.start) / D + "%";
  requestAnimationFrame(() => { bar.style.width = (100 * (e.end - s.start)) / D + "%"; });
}

/* ---------------- state ---------------- */
const S = { data: null, runId: "", label: "", filter: "all", sel: null, decisions: {}, official: null };
const decKey = () => "sd-dec-" + S.runId;
const loadDec = () => { try { return JSON.parse(localStorage.getItem(decKey()) || "{}"); } catch { return {}; } };
const saveDec = () => localStorage.setItem(decKey(), JSON.stringify(S.decisions));
const allPromos = () => [...S.data.promos, ...S.data.montages];
const warns = (p) => ((p.attention || {}).flags || []).length + (p.flags && (p.flags.spoiler_risk || p.flags.ad_policy_risk || p.flags.needs_context) ? 1 : 0);
const segText = (p) => p.segments.map((s) => `E${pad(s.episode)} ${s.start_ts}–${s.end_ts}`).join("  +  ");
const lineText = (t) => String(t || "").replace(/^\[(\w+)\]\s*/, "").replace(/^([^:"]{1,60}):\s*"(.*)"$/, "$2");
const speaker = (t) => { const m = String(t || "").match(/^([^:"\[]{1,60}):\s*"/); return m ? m[1].replace(/\s*\([^)]*\)/g, "").trim() : (String(t).match(/^\[(\w+)\]/) || [, ""])[1]; };

function loadDataset(data, runId, label) {
  S.data = data; S.runId = runId; S.label = label; S.decisions = loadDec(); S.filter = "all"; S.sel = null;
  $$("#filters button").forEach((b) => b.classList.toggle("on", b.dataset.f === "all"));
  const log = data.run_log || {};
  $("#show-title").textContent = data.show;
  $("#run-title").innerHTML = esc(label) + (S.official && data !== S.official ? ` · <a href="#review" id="back-official">back to official run</a>` : "");
  const back = $("#back-official");
  if (back) back.onclick = (e) => { e.preventDefault(); loadDataset(S.official, "official-" + S.official.run_id, "Official run"); };
  const bits = [`<b>${log.episodes}</b> episodes`, `<b>${log.candidates_valid}</b> candidates`, `<b>${log.candidates_rejected}</b> rejected by checks`];
  if (data.rules) bits.push(`<b>${data.rules.passing}/${data.rules.checked}</b> pass the rules`);
  const ab = (data.auto_eval || {}).blind_ab_pipeline_vs_baseline;
  if (ab) bits.push(`blind A/B vs baseline <b>${ab.pipeline}–${ab.baseline}</b>`);
  if (log.llm && log.llm.total_calls != null && data !== S.official) bits.push(`<b>${log.llm.total_calls}</b> model calls`);
  $("#run-meta").innerHTML = bits.join(" · ");
  $("#n-all").textContent = allPromos().length;
  $("#n-single").textContent = data.promos.length;
  $("#n-montage").textContent = data.montages.length;
  $("#n-warn").textContent = allPromos().filter(warns).length;
  $("#n-rej").textContent = (data.rejected || []).length;
  drawList();
  const first = visible()[0];
  if (first) select(first.pid);
  tally();
}

/* ---------------- list ---------------- */
function visible() {
  if (!S.data || S.filter === "rejected") return [];
  const q = $("#q").value.toLowerCase().trim();
  let list = S.filter === "single" ? S.data.promos.slice() : S.filter === "montage" ? S.data.montages.slice() : allPromos();
  if (S.filter === "warn") list = list.filter(warns);
  if (q) list = list.filter((p) => [segText(p), p.hook, p.cliffhanger, p.why, p.open_question, ...(p.excerpt || [])].join(" ").toLowerCase().includes(q));
  const sort = $("#sort").value;
  if (sort === "episode") list.sort((a, b) => a.segments[0].episode - b.segments[0].episode || a.segments[0].start - b.segments[0].start);
  else if (sort === "attention") list.sort((a, b) => ((b.attention || {}).hook_attention || 0) - ((a.attention || {}).hook_attention || 0));
  return list;
}
function drawList() {
  const ol = $("#rows");
  if (S.filter === "rejected") {
    ol.innerHTML = `<li class="none">${(S.data.rejected || []).length} candidates failed the code checks. The list is on the right.</li>`;
    drawRejected();
    return;
  }
  const list = visible();
  ol.innerHTML = list.map((p) => {
    const d = S.decisions[p.pid] || "";
    const isM = p.kind === "montage";
    const s0 = p.segments[0];
    const w = warns(p);
    return `<li class="row ${p.pid === S.sel ? "sel" : ""} ${d}" data-pid="${p.pid}">
      <span class="rk">${isM ? "M" : ""}${p.rank}</span>
      <div><div class="line1">${esc(lineText(p.hook))}</div>
        <div class="tc"><span class="ep">Ep ${s0.episode}</span> · ${short(s0.start)}–${short(p.segments[p.segments.length - 1].end)}${isM ? ` · ${p.segments.length} parts` : ""}${w ? ` · <span class="warn">flagged</span>` : ""}</div></div>
      <div class="side"><span class="score">${Math.round(p.duration)}s</span><span class="state ${d}"></span></div>
    </li>`;
  }).join("") || `<li class="none">Nothing matches that. Try fewer words, or clear the search.</li>`;
  $$(".row", ol).forEach((li) => li.addEventListener("click", () => {
    select(li.dataset.pid);
    if (narrow()) $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}
$$("#filters button").forEach((b) => b.addEventListener("click", () => {
  S.filter = b.dataset.f;
  $$("#filters button").forEach((x) => x.classList.toggle("on", x === b));
  drawList();
  if (S.filter !== "rejected") { const v = visible(); if (v.length && !v.find((p) => p.pid === S.sel)) select(v[0].pid); else if (S.sel) select(S.sel); }
}));
$("#q").addEventListener("input", drawList);
$("#sort").addEventListener("change", drawList);

/* ---------------- detail ---------------- */
function parseExcerpt(ex) {
  return (ex || []).map((l) => {
    if (l.startsWith("---")) return { brk: l.replace(/^-+\s*/, "") };
    const m = l.match(/^(E\d+_L\d+)\s+(\d+:\d+(?:\.\d+)?)\s+(.*)$/);
    if (!m) return { text: l };
    return { id: m[1], t: m[2], raw: m[3] };
  });
}
function select(pid) {
  S.sel = pid;
  $$(".row").forEach((r) => r.classList.toggle("sel", r.dataset.pid === pid));
  const li = $(`.row[data-pid="${pid}"]`), rows = $("#rows");
  if (li && rows.scrollHeight > rows.clientHeight) {   // keep the row visible inside the list only; never move the page
    const top = li.offsetTop - 6, bot = li.offsetTop + li.offsetHeight + 6;
    if (top < rows.scrollTop) rows.scrollTop = top;
    else if (bot > rows.scrollTop + rows.clientHeight) rows.scrollTop = bot - rows.clientHeight;
  }
  const p = allPromos().find((x) => x.pid === pid);
  if (p) drawDetail(p);
  tally();
}
function drawDetail(p) {
  const isM = p.kind === "montage";
  const ex = parseExcerpt(p.excerpt);
  const f = p.flags || {}, att = p.attention || {};
  const risks = [];
  if (f.spoiler_risk) risks.push("comes from a spoiler episode");
  if (f.ad_policy_risk) risks.push("may break ad policy");
  if (f.needs_context) risks.push("may need context to follow");
  const where = p.segments.map((s) => `Episode ${s.episode}, ${short(s.start)}–${short(s.end)}`).join(" + ");

  // where the cut sits in its episode: one thin bar per part
  const durs = S.data.episode_durations || {};
  const track = p.segments.map((s, i) => {
    const D = durs[s.episode] || durs[String(s.episode)] || Math.max(s.end, 1);
    const L = (x) => Math.max(0, Math.min(100, (100 * x) / D));
    return `<div class="track-seg"><div class="track-bar"><span class="track-in" style="left:${L(s.start)}%;width:${Math.max(.8, L(s.end) - L(s.start))}%"></span></div>
      <div class="track-cap"><span>${isM ? `Part ${i + 1}, episode ${s.episode}: ` : ""}${short(s.start)}–${short(s.end)}</span><span>episode runs ${short(D)}</span></div></div>`;
  }).join("");

  // the script, as a screenplay page; the hook and the cliffhanger are marked in the margin
  const script = ex.map((l) => {
    if (l.brk) return `<div class="sl seg-break">${esc(l.brk)}</div>`;
    if (!l.id) return `<div class="sl"><span></span><span>${esc(l.text)}</span></div>`;
    const isAct = /^\[(action|sfx|camera)\]/i.test(l.raw);
    const hook = l.id === p.hook_line_id, cut = l.id === p.cliffhanger_line_id;
    const cls = [hook ? "hook" : "", cut ? "cut" : "", isAct ? "act" : ""].join(" ");
    const tag = hook ? "Hook" : cut ? "Cliffhanger" : "";
    return `<div class="sl ${cls}"><span class="t">${short(toSec(l.t))}</span><span>${tag ? `<span class="tag">${tag}</span>` : ""}${
      isAct ? esc(lineText(l.raw)) : `<span class="who">${esc(speaker(l.raw))}</span>${esc(lineText(l.raw))}`}</span></div>`;
  }).join("");

  const scoreRows = SCORE_NAMES.filter(([k]) => p.scores && p.scores[k] != null).map(([k, n]) =>
    `<tr><td>${n}</td><td><div class="meter"><i style="width:${(p.scores[k] / 5) * 100}%"></i></div></td><td class="v">${(+p.scores[k]).toFixed(1)}</td></tr>`).join("");
  const attRows = att.hook_attention != null ? `
    <tr><td title="How soon someone speaks, motion, close-ups and sound in the first 3 s, read from the screenplay">Attention, first 3 s</td><td><div class="meter"><i style="width:${att.hook_attention * 100}%"></i></div></td><td class="v">${att.hook_attention.toFixed(2)}</td></tr>
    <tr><td title="Dead air, cutting pace, share of time with speech, ending beat">Holds attention</td><td><div class="meter"><i style="width:${att.hold * 100}%"></i></div></td><td class="v">${att.hold.toFixed(2)}</td></tr>` : "";
  const fine = [];
  if ((att.flags || []).length) fine.push(`The text check noticed: ${esc(att.flags.join(", "))}.`);
  if (!f.spoiler_risk && f.judge_spoiler) fine.push("The judge thought this might spoil the show; the spoiler vote disagreed, so it isn't penalised.");
  if (p.source === "heuristic") fine.push("Picked by the keyword rules, not the model.");

  $("#detail").innerHTML = `
    <p class="d-eyebrow"><b>${isM ? "Montage " : "#"}${p.rank}</b> · ${esc(where)} · ${Math.round(p.duration)} seconds</p>
    <h1 class="d-title">${esc(lineText(p.hook))}</h1>
    ${p.open_question ? `<p class="d-q">Leaves the viewer asking: ${esc(p.open_question)}</p>` : ""}
    ${risks.length ? `<p class="d-warn">This clip ${risks.join(" and ")}.</p>` : ""}
    <div class="track">${track}</div>
    <div class="d-body">
      <div class="script">${script}</div>
      <aside class="d-notes">
        ${p.why || p.rank_reason ? `<h3>Why it's here</h3>${p.why ? `<p>${esc(p.why)}</p>` : ""}${p.rank_reason ? `<p>${esc(p.rank_reason)}</p>` : ""}` : ""}
        ${scoreRows || attRows ? `<h3>Scores</h3><table class="scores">${scoreRows}${attRows}</table>` : ""}
        ${fine.map((t) => `<p class="fine">${t}</p>`).join("")}
        ${p.score_note && p.score_note !== "none" ? `<h3>The judge's doubt</h3><p>${esc(p.score_note)}</p>` : ""}
      </aside>
    </div>`;
  toDetailTop();
}
const narrow = () => matchMedia("(max-width: 900px)").matches;
function toDetailTop() {   // a new clip starts at its title; the list keeps its place
  if (narrow() || !$("#view-review").classList.contains("on")) return;
  const y = $(".desk").getBoundingClientRect().top + scrollY - $(".nav-wrap").offsetHeight - 4;
  if (scrollY > y) window.scrollTo({ top: y });
}
function drawRejected() {
  const rej = S.data.rejected || [];
  $("#detail").innerHTML = `<h1 class="d-title">Rejected by the code checks</h1>
    <p class="d-q">${rej.length} proposals broke a hard rule. Most went back to the model with the lines that would fix them.</p>
    <table class="table" style="margin-top:24px"><tr><th>Episode</th><th>Lines</th><th>Reason</th></tr>${rej.map((r) =>
      `<tr><td class="mono">${esc(r.episode ?? "—")}</td><td class="mono">${esc((r.start_line || "") + (r.end_line ? " – " + r.end_line : ""))}</td><td>${esc(r.reason)}${r.repaired ? " (repair tried)" : ""}</td></tr>`).join("")}</table>`;
}

/* ---------------- approve / reject ---------------- */
function decide(kind) {
  if (!S.sel) return;
  S.decisions[S.sel] = S.decisions[S.sel] === kind ? undefined : kind;
  saveDec();
  const cur = S.sel;
  drawList();
  select(cur);
  if (S.decisions[cur]) step(1);
}
function step(d) {
  const v = visible();
  const i = v.findIndex((p) => p.pid === S.sel);
  const n = v[Math.max(0, Math.min(v.length - 1, i + d))];
  if (n) select(n.pid);
}
function tally() {
  if (!S.data) return;
  const vals = Object.values(S.decisions);
  const a = vals.filter((x) => x === "approved").length, r = vals.filter((x) => x === "rejected").length;
  $("#tally").textContent = `${a} approved · ${r} rejected · ${allPromos().length - a - r} to review`;
  const cur = S.decisions[S.sel];
  $("#act-approve").textContent = cur === "approved" ? "Approved ✓" : "Approve";
  $("#act-reject").classList.toggle("is-on", cur === "rejected");
  $("#act-reject").textContent = cur === "rejected" ? "Rejected" : "Reject";
}
$("#act-approve").onclick = () => decide("approved");
$("#act-reject").onclick = () => decide("rejected");
document.addEventListener("keydown", (e) => {
  if (!$("#view-review").classList.contains("on") || /input|select|textarea/i.test(e.target.tagName)) return;
  const k = e.key.toLowerCase();
  if (k === "j" || e.key === "ArrowDown") { e.preventDefault(); step(1); }
  else if (k === "k" || e.key === "ArrowUp") { e.preventDefault(); step(-1); }
  else if (k === "a") decide("approved");
  else if (k === "r") decide("rejected");
});

/* ---------------- export ---------------- */
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
$("#export-btn").onclick = (e) => { e.stopPropagation(); $("#export-menu").hidden = !$("#export-menu").hidden; };
document.addEventListener("click", () => { $("#export-menu").hidden = true; });
$$("#export-menu button").forEach((b) => b.addEventListener("click", () => {
  const d = S.data;
  if (!d) return;
  if (b.dataset.dl === "md") download("promos.md", d.markdown || "", "text/markdown");
  if (b.dataset.dl === "csv") download("promos.csv", d.csv || "", "text/csv");
  if (b.dataset.dl === "json") download("promos.json", JSON.stringify({ show: d.show, promos: d.promos, montages: d.montages }, null, 2), "application/json");
  if (b.dataset.dl === "dec") {
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const rows = [["rank", "id", "segments", "duration_s", "hook", "cliffhanger", "decision"],
      ...allPromos().map((p) => [(p.kind === "montage" ? "M" : "") + p.rank, p.pid, segText(p), p.duration, p.hook, p.cliffhanger, S.decisions[p.pid] || ""])];
    download("promos_with_approvals.csv", rows.map((r) => r.map(q).join(",")).join("\n"), "text/csv");
  }
}));

/* ---------------- official results ---------------- */
(async () => {
  try {
    const data = await (await fetch("data/official.json")).json();
    S.official = data;
    loadDataset(data, "official-" + data.run_id, "Official run");
    heroSample(data);
  } catch (e) {
    $("#show-title").textContent = "The official picks didn't load. A refresh usually fixes it.";
    $("#run-title").textContent = String(e);
  }
})();

/* ---------------- Python engine ---------------- */
let enginePromise = null;
const note = (t, bad = false) => { const n = $("#engine-note"); n.textContent = t; n.classList.toggle("bad", bad); };
const loadScript = (src) => new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
function engine() {
  if (!enginePromise) {
    enginePromise = (async () => {
      note("Loading the Python engine…");
      await loadScript(PYODIDE_URL + "pyodide.js");
      const py = await loadPyodide({ indexURL: PYODIDE_URL });
      await py.loadPackage(["pydantic", "pyyaml"]);
      const buf = await (await fetch("app.zip", { cache: "no-cache" })).arrayBuffer();
      py.unpackArchive(buf, "zip", { extractDir: "/app" });
      py.runPython("import sys; sys.path.insert(0, '/app'); import bridge");
      note("Engine ready.");
      return py;
    })();
    enginePromise.catch((e) => { enginePromise = null; note("The engine failed to load: " + e, true); });
  }
  return enginePromise;
}

/* ---------------- run ---------------- */
let mode = "ai";
$$("#mode button").forEach((b) => b.addEventListener("click", () => {
  mode = b.dataset.mode;
  $$("#mode button").forEach((x) => x.classList.toggle("on", x === b));
  $("#ai-opts").hidden = mode !== "ai";
}));
function providerDefaults() {
  const p = $("#provider").value;
  $("#bulk-model").value = DEFAULTS[p].bulk;
  $("#judge-model").value = DEFAULTS[p].judge;
  $("#baseurl-wrap").hidden = p !== "custom";
}
$("#provider").addEventListener("change", providerDefaults);
providerDefaults();

async function loadEpisodes(files, showName) {
  const st = $("#loaded");
  st.className = "status-line"; st.textContent = "Reading…";
  try {
    const py = await engine();
    const arr = [];
    for (const f of files) arr.push([f.name, new Uint8Array(await f.arrayBuffer())]);
    const bridge = py.pyimport("bridge");
    const info = JSON.parse(bridge.load_files(py.toPy(arr)));
    if (showName) { bridge.set_show(showName); info.show = showName; }
    if (!info.episodes) throw new Error("no readable screenplay or subtitle text found");
    st.className = "status-line ok";
    st.textContent = `${info.show} — ${info.episodes} ${info.episodes === 1 ? "part" : "episodes"} · ${info.lines} lines · ${info.minutes} min`;
    $("#run-btn").disabled = false;
  } catch (e) {
    st.className = "status-line bad"; st.textContent = "Couldn't read those files (" + (e.message || e) + "). A .zip of .txt screenplays or one .srt file works best.";
  }
}
const drop = $("#drop");
$("#files").addEventListener("change", (e) => e.target.files.length && loadEpisodes([...e.target.files]));
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => e.dataTransfer.files.length && loadEpisodes([...e.dataTransfer.files]));
$("#use-sample").addEventListener("click", async () => {
  $("#loaded").textContent = "Fetching the sample…";
  const blob = await (await fetch("data/sample_show.zip")).blob();
  loadEpisodes([new File([blob], "sample_show.zip")], "I Married a Broken Soldier. He was a Duke");
});

function setStage(stage, i, n) {
  const el = $("#st-" + stage);
  if (!el) return;
  $(".cnt", el).textContent = n ? `${i} / ${n}` : "";
  $(".pb i", el).style.width = (n ? (100 * i) / n : 0) + "%";
  el.classList.add("active");
  el.classList.toggle("done", n > 0 && i >= n);
}
const log = (line) => { const l = $("#log"); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; };

$("#run-btn").addEventListener("click", async () => {
  const useLlm = mode === "ai";
  const provider = $("#provider").value;
  const opts = { use_llm: useLlm, provider, key: $("#key").value.trim(), base_url: $("#baseurl").value.trim(),
    bulk_model: $("#bulk-model").value.trim(), judge_model: $("#judge-model").value.trim(), profile: $("#profile").value, montage: $("#montage").checked };
  const err = $("#run-error");
  const fail = (m) => { err.hidden = false; err.textContent = m; };
  err.hidden = true;
  if (useLlm && !opts.key) return fail("Add an API key, or switch to “Rules only” to run without one.");
  if (useLlm && (!opts.bulk_model || !opts.judge_model)) return fail("This provider needs two model names: one that proposes clips and one that judges them.");
  if (useLlm && provider === "custom" && !opts.base_url) return fail("Add the base URL of your endpoint, usually ending in /v1/.");
  const btn = $("#run-btn");
  btn.disabled = true; btn.textContent = "Running…";
  $("#progress").hidden = false; $("#log").textContent = "";
  $("#stages").innerHTML = useLlm ? STAGES.map(([k, n]) => `<div class="stage" id="st-${k}"><span>${n}</span><span class="pb"><i></i></span><span class="cnt">—</span></div>`).join("")
    : `<div class="stage active"><span>Rule baseline</span><span class="pb"><i style="width:100%"></i></span><span class="cnt">no calls</span></div>`;
  $("#progress").scrollIntoView({ behavior: "smooth", block: "start" });
  const t0 = Date.now();
  const timer = setInterval(() => { $("#elapsed").textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 500);
  try {
    const py = await engine();
    const bridge = py.pyimport("bridge");
    await new Promise((r) => setTimeout(r, 50));
    const out = await bridge.run(JSON.stringify(opts), (s, i, n) => setStage(s, i, n), (m) => log(m));
    const data = JSON.parse(out);
    const secs = Math.round((Date.now() - t0) / 1000);
    log(`Done in ${secs} s.`);
    const label = `Your run · ${useLlm ? (data.run_log.profile || "AI") : "rule baseline"} · ${secs} s`;
    loadDataset(data, "run-" + t0, label);
    show("review");
  } catch (e) {
    const lines = String(e.message || e).split("\n").filter(Boolean);
    const fatal = lines.filter((l) => /FatalProviderError: /.test(l)).pop();
    fail(fatal ? fatal.replace(/^.*FatalProviderError:\s*/, "") : "The run stopped: " + lines.slice(-2).join(" "));
    log("ERROR: " + e);
  } finally {
    clearInterval(timer);
    btn.disabled = false; btn.textContent = "Find the promos";
  }
});

/* ---------------- start ---------------- */
show((location.hash || "#home").slice(1).replace(/[^a-z]/g, "") || "home");
window.addEventListener("hashchange", () => show(location.hash.slice(1).replace(/[^a-z]/g, "")));
