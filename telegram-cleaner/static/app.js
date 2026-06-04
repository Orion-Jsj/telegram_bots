// ---------- shared helpers ----------
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = async (url, opts = {}) => {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  return r.json();
};

const CONTENT_TYPES = [
  ["text", "Text messages", "plain"],
  ["links", "Links", "urls"],
  ["photos", "Photos", "img"],
  ["videos", "Videos", "vid"],
  ["files", "Files / docs", "doc"],
  ["voice", "Voice notes", "ogg"],
  ["stickers", "Stickers", "tgs"],
  ["gifs", "GIFs", "anim"],
  ["polls", "Polls", "poll"],
  ["forwards", "Forwarded", "fwd"],
  ["service", "Service msgs", "sys"],
];
const PROTECTED_MEMBERS = new Map(); // user_id -> label

// ---------- session pill ----------
async function refreshSession() {
  const pill = $("#sessionPill"), txt = $("#sessionText");
  if (!pill) return;
  try {
    const s = await api("/api/status");
    pill.className = "session-pill" + (s.authorized ? " ok" : " bad");
    if (s.authorized && s.me) txt.textContent = (s.me.username ? "@" + s.me.username : s.me.name) || "authorized";
    else if (s.state === "no_credentials") txt.textContent = "no .env credentials";
    else txt.textContent = s.state || "not logged in";
    return s;
  } catch { txt.textContent = "offline"; }
}

// ---------- live log SSE ----------
function startLogStream() {
  const feed = $("#logFeed");
  if (!feed) return;
  const clear = $("#logClear");
  if (clear) clear.onclick = () => (feed.innerHTML = "");
  const es = new EventSource("/stream/logs");
  es.onmessage = (e) => {
    const d = JSON.parse(e.data);
    const row = document.createElement("div");
    row.className = "row " + (d.level || "info");
    row.innerHTML = `<span class="t">${d.ts || ""}</span><span class="m"></span>`;
    row.querySelector(".m").textContent = d.message;
    feed.appendChild(row);
    feed.scrollTop = feed.scrollHeight;
    while (feed.children.length > 400) feed.removeChild(feed.firstChild);
  };
}

// ---------- LOGIN tab ----------
function initLogin() {
  const out = $("#loginOut");
  const show = (el) => $$(".lstep").forEach((s) => s.classList.toggle("hidden", s !== el));
  const msg = (m, bad) => { out.textContent = m; out.style.color = bad ? "var(--red)" : "var(--teal)"; };

  refreshSession().then((s) => {
    if (s && s.authorized) show($("#stepDone")), ($("#whoami").textContent = s.me ? (s.me.username ? "@" + s.me.username : s.me.name) : "");
    else if (s && s.state === "no_credentials") show($("#stepNoCreds"));
    else show($("#stepPhone"));
  });

  $("#btnPhone").onclick = async () => {
    msg("Requesting code…");
    const r = await api("/api/login/start", { method: "POST", body: { phone: $("#phone").value.trim() } });
    if (!r.ok) return msg(r.error || "failed", true);
    if (r.state === "authorized") { show($("#stepDone")); refreshSession(); }
    else { show($("#stepCode")); msg("Code sent to your Telegram app."); }
  };
  $("#btnCode").onclick = async () => {
    msg("Verifying…");
    const r = await api("/api/login/code", { method: "POST", body: { code: $("#code").value.trim() } });
    if (!r.ok) return msg(r.error || "failed", true);
    if (r.state === "password_needed") { show($("#stepPw")); msg("2FA enabled — enter your password."); }
    else { show($("#stepDone")); refreshSession(); }
  };
  $("#btnPw").onclick = async () => {
    msg("Checking password…");
    const r = await api("/api/login/password", { method: "POST", body: { password: $("#pw").value } });
    if (!r.ok) return msg(r.error || "failed", true);
    show($("#stepDone")); refreshSession();
  };
  $("#btnLogout").onclick = async () => { await api("/api/logout", { method: "POST" }); location.reload(); };
}

// ---------- JOBS tab ----------
let DIALOGS = { groups: [], channels: [], dms: [] };
let SELECTED = new Set();

function initCreate() {
  buildChecks();
  loadDialogs();
  // keep the .on highlight in sync with static protection checkboxes
  $$(".card .chk input[type=checkbox]").forEach((cb) => {
    const lab = cb.closest(".chk");
    if (!lab) return;
    lab.classList.toggle("on", cb.checked);
    cb.addEventListener("change", () => lab.classList.toggle("on", cb.checked));
  });
  $$(".subtab").forEach((t) => (t.onclick = () => switchSub(t.dataset.k)));
  $("#btnRefreshChats").onclick = () => loadDialogs(true);
  $("#btnRights").onclick = probeSelected;
  $("#btnLoadMembers").onclick = loadMembers;
  $("#btnCreate").onclick = createJob;
}

async function loadMembers() {
  const box = $("#memberBox");
  const groups = [...SELECTED].filter((id) =>
    DIALOGS.groups.some((g) => g.id === id) || DIALOGS.channels.some((c) => c.id === id));
  if (!groups.length) { box.innerHTML = `<div class="item muted">Select a group or channel first.</div>`; return; }
  box.innerHTML = `<div class="item muted">loading members…</div>`;
  const seen = new Map();
  for (const id of groups) {
    const r = await api(`/api/target/${id}/users?limit=500`);
    if (r.error) continue;
    const changedIds = new Set((r.changes || []).map((c) => String(c.user_id)));
    (r.members || []).forEach((m) => {
      if (!seen.has(m.user_id)) seen.set(m.user_id, { ...m, changed: changedIds.has(String(m.user_id)) });
    });
  }
  if (!seen.size) { box.innerHTML = `<div class="item muted">no members found (need admin rights on large groups)</div>`; return; }
  box.innerHTML = "";
  [...seen.values()].forEach((m) => {
    const name = [m.first_name, m.last_name].filter(Boolean).join(" ") || (m.username ? "@" + m.username : m.user_id);
    const tags = [m.is_owner ? `<span class="badge owner">owner</span>` : "",
                  m.is_admin ? `<span class="badge admin">admin</span>` : "",
                  m.changed ? `<span class="badge changed">changed</span>` : ""].join("");
    const it = document.createElement("label");
    it.className = "item" + (PROTECTED_MEMBERS.has(m.user_id) ? " sel" : "");
    it.innerHTML = `<input type="checkbox" ${PROTECTED_MEMBERS.has(m.user_id) ? "checked" : ""}>
      <span class="nm">${escapeHtml(name)}</span> ${tags}
      <span class="meta">${m.username ? "@" + m.username + " · " : ""}${m.user_id}</span>`;
    const cb = it.querySelector("input");
    cb.onchange = () => {
      cb.checked ? PROTECTED_MEMBERS.set(m.user_id, name) : PROTECTED_MEMBERS.delete(m.user_id);
      it.classList.toggle("sel", cb.checked);
    };
    box.appendChild(it);
  });
}

function buildChecks() {
  const wrap = $("#checks");
  wrap.innerHTML = "";
  CONTENT_TYPES.forEach(([key, label, hint]) => {
    const el = document.createElement("label");
    el.className = "chk";
    el.innerHTML = `<input type="checkbox" data-k="${key}"><span class="lbl">${label}</span><span class="hint">${hint}</span>`;
    const cb = el.querySelector("input");
    cb.onchange = () => el.classList.toggle("on", cb.checked);
    wrap.appendChild(el);
  });
}

async function loadDialogs(fresh = false) {
  $("#chatlist").innerHTML = `<div class="item muted">loading chats…</div>`;
  const d = await api("/api/dialogs" + (fresh ? "?fresh=1" : ""));
  if (d.error) { $("#chatlist").innerHTML = `<div class="item" style="color:var(--red)">${d.error}</div>`; return; }
  DIALOGS = d;
  switchSub("groups");
}

function switchSub(k) {
  $$(".subtab").forEach((t) => t.classList.toggle("active", t.dataset.k === k));
  const list = k === "groups" ? DIALOGS.groups : k === "channels" ? DIALOGS.channels : DIALOGS.dms;
  const wrap = $("#chatlist");
  wrap.innerHTML = "";
  if (!list.length) { wrap.innerHTML = `<div class="item muted">none found</div>`; return; }
  list.forEach((c) => {
    const it = document.createElement("label");
    it.className = "item" + (SELECTED.has(c.id) ? " sel" : "");
    it.innerHTML = `<input type="checkbox" ${SELECTED.has(c.id) ? "checked" : ""}>
      <span class="nm">${escapeHtml(c.title)}</span>
      <span class="meta">${c.username ? "@" + c.username + " · " : ""}${c.kind} · ${c.id}</span>`;
    const cb = it.querySelector("input");
    cb.onchange = () => { cb.checked ? SELECTED.add(c.id) : SELECTED.delete(c.id); it.classList.toggle("sel", cb.checked); updateSelCount(); };
    wrap.appendChild(it);
  });
  updateSelCount();
}
function updateSelCount() { $("#selCount").textContent = SELECTED.size; }

async function probeSelected() {
  const box = $("#rightsBox");
  if (!SELECTED.size) { box.innerHTML = `<div class="muted">Select at least one target first.</div>`; return; }
  box.innerHTML = `<div class="muted">probing rights…</div>`;
  let html = "";
  for (const id of SELECTED) {
    const r = await api(`/api/target/${id}/rights`);
    if (r.error) { html += `<div class="rights-line" style="color:var(--red)">${id}: ${r.error}</div>`; continue; }
    const roleBadge = r.role === "owner" ? `<span class="badge owner">owner</span>`
      : r.role === "admin" ? `<span class="badge admin">admin</span>`
      : `<span class="badge">${r.role}</span>`;
    const cap = r.can_delete_others
      ? `<span style="color:var(--teal)">full cleanup ✓</span>`
      : `<span style="color:var(--amber)">own messages only — missing: ${r.missing_right || "rights"}</span>`;
    html += `<div class="rights-line">${roleBadge}<strong>${escapeHtml(r.title)}</strong> ${cap}</div>
             <div class="muted" style="font-size:11px;padding-bottom:8px">${escapeHtml(r.note || "")}</div>`;
  }
  box.innerHTML = html;
}

async function createJob() {
  if (!SELECTED.size) return alert("Select at least one target.");
  const delete_types = {};
  $$('#checks input').forEach((cb) => (delete_types[cb.dataset.k] = cb.checked));
  const typed = $("#whitelist").value.split(/[,\s]+/).filter(Boolean);
  const whitelist = [...new Set([...PROTECTED_MEMBERS.keys(), ...typed])].map(String);
  const body = {
    name: $("#jobName").value.trim() || undefined,
    targets: [...SELECTED],
    cutoff_date: $("#cutoff").value || null,
    delete_types,
    whitelist_user_ids: whitelist,
    protect_pinned: $("#pPinned").checked,
    protect_owner: $("#pOwner").checked,
    protect_admins: $("#pAdmins").checked,
    protect_self: $("#pSelf").checked,
    dm_scope: $("#dmScope").value,
    verbose: $("#verbose").checked,
  };
  const r = await api("/api/jobs", { method: "POST", body });
  const msg = $("#createMsg");
  if (r.ok) {
    SELECTED.clear(); PROTECTED_MEMBERS.clear();
    $("#jobName").value = "";
    if (msg) { msg.style.color = "var(--teal)"; msg.innerHTML = `saved ✓ — <a href="#jobs" style="color:var(--amber)">go to Jobs</a>`; }
  } else if (msg) { msg.style.color = "var(--red)"; msg.textContent = r.error || "failed"; }
}

// ================= MODAL =================
function openModal(title, bodyHtml, footEls = []) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  const foot = $("#modalFoot"); foot.innerHTML = "";
  footEls.forEach((el) => foot.appendChild(el));
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }
function mkBtn(label, cls, onClick) {
  const b = document.createElement("button"); b.className = "btn " + cls;
  b.textContent = label; b.onclick = onClick; return b;
}

// ================= JOBS tab (table) =================
async function loadJobsTable() {
  const jobs = await api("/api/jobs");
  const tb = $("#jobRows");
  if (!jobs.length) { tb.innerHTML = `<tr><td colspan="7" class="muted" style="padding:18px">No jobs yet. <a href="#create" style="color:var(--amber)">Create one</a>.</td></tr>`; return; }
  tb.innerHTML = "";
  jobs.forEach((j) => {
    const types = Object.entries(j.config.delete_types || {}).filter(([, v]) => v).map(([k]) => k);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${j.id}</td>
      <td class="nm">${escapeHtml(j.name)}</td>
      <td>${j.config.targets.length}</td>
      <td>${types.length ? types.join(", ") : "—"}</td>
      <td>${j.config.cutoff_date || "all"}</td>
      <td>${j.run_count || 0}</td>
      <td class="actions"></td>`;
    const act = tr.querySelector(".actions");
    const dry = document.createElement("button"); dry.className = "iconbtn dry"; dry.textContent = "dry run";
    const live = document.createElement("button"); live.className = "iconbtn live"; live.textContent = "run";
    const del = document.createElement("button"); del.className = "iconbtn del"; del.textContent = "delete";
    dry.onclick = (e) => { e.stopPropagation(); runJob(j.id, true); };
    live.onclick = (e) => { e.stopPropagation(); confirmLive(j); };
    del.onclick = (e) => { e.stopPropagation(); deleteJob(j); };
    act.append(dry, live, del);
    tr.onclick = () => showJobModal(j);
    tb.appendChild(tr);
  });
}

function showJobModal(j) {
  const c = j.config;
  const types = Object.entries(c.delete_types || {}).filter(([, v]) => v).map(([k]) => k);
  const keep = [c.protect_pinned && "pinned", c.protect_owner && "owner",
                c.protect_admins && "admins", c.protect_self && "my own"].filter(Boolean);
  const body = `<div class="kv">
    <div class="k">name</div><div>${escapeHtml(j.name)} <span class="pill-sm">#${j.id}</span></div>
    <div class="k">targets</div><div class="mono">${(c.targets || []).join("<br>") || "—"}</div>
    <div class="k">delete</div><div>${types.length ? types.join(", ") : "<span style='color:var(--teal)'>nothing (all protected)</span>"}</div>
    <div class="k">cutoff</div><div>${c.cutoff_date || "all history"}</div>
    <div class="k">keep / protect</div><div>${keep.join(", ") || "—"}</div>
    <div class="k">protected ids</div><div class="mono">${(c.whitelist_user_ids || []).join(", ") || "—"}</div>
    <div class="k">DM scope</div><div>${c.dm_scope || "both"}</div>
    <div class="k">verbose</div><div>${c.verbose ? "on" : "off"}</div>
  </div>`;
  openModal("Job: " + j.name, body, [
    mkBtn("Dry run", "safe", () => { closeModal(); runJob(j.id, true); }),
    mkBtn("Run & delete", "danger", () => { closeModal(); confirmLive(j); }),
    mkBtn("Close", "ghost", closeModal),
  ]);
}

function confirmLive(j) {
  const body = `<p>This will <strong style="color:var(--red)">permanently delete</strong> messages in
    <strong>${j.config.targets.length}</strong> target(s) according to job
    <strong>${escapeHtml(j.name)}</strong>. Dry-run first if unsure.</p>`;
  const chk = document.createElement("label"); chk.className = "confirm-chk";
  chk.innerHTML = `<input type="checkbox" id="confirmBox"> I understand this can't be undone`;
  const runBtn = mkBtn("Delete for real", "danger", async () => {
    if (!$("#confirmBox").checked) return;
    closeModal(); runJob(j.id, false);
  });
  openModal("Confirm live delete", body, [chk, mkBtn("Cancel", "ghost", closeModal), runBtn]);
}

async function deleteJob(j) {
  const body = `<p>Delete job <strong>${escapeHtml(j.name)}</strong> (#${j.id})? Its past run
    history in Reports is kept.</p>`;
  openModal("Delete job", body, [
    mkBtn("Cancel", "ghost", closeModal),
    mkBtn("Delete", "danger", async () => {
      await api(`/api/jobs/${j.id}`, { method: "DELETE" }); closeModal(); loadJobsTable();
    }),
  ]);
}

async function runJob(id, dry) {
  const r = await api(`/api/jobs/${id}/run`, { method: "POST", body: { dry_run: dry, confirm: !dry } });
  if (!r.ok) return alert(r.error || "failed");
  location.hash = "reports";
  loadRunsTable();
}

// ================= REPORTS tab (table) =================
let REPORTS_TIMER = null;
function startReportsTimer() {
  if (REPORTS_TIMER) return;
  REPORTS_TIMER = setInterval(() => {
    const panel = document.querySelector('[data-panel="reports"]');
    if (!panel || panel.classList.contains("hidden")) return;   // only when Reports is showing
    if (document.hidden) return;
    if (!$("#modal").classList.contains("hidden")) return;       // not under an open popup
    loadRunsTable();
  }, 5000);
}

async function loadRunsTable() {
  const runs = await api("/api/runs");
  const tb = $("#runRows");
  if (!runs.length) { tb.innerHTML = `<tr><td colspan="9" class="muted" style="padding:18px">No runs yet.</td></tr>`; return; }
  tb.innerHTML = "";
  runs.forEach((r) => {
    const mode = r.dry_run ? `<span class="badge dry">dry</span>` : `<span class="badge live">live</span>`;
    const when = r.started_at ? new Date(r.started_at * 1000).toLocaleString() : "—";
    const stBadge = r.status === "paused" ? `<span class="badge paused">paused</span>`
      : r.status === "running" || r.status === "queued" ? `<span class="badge">${r.status}</span>`
      : r.status === "error" ? `<span class="badge live">error</span>`
      : `<span class="badge dry">done</span>`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${r.id}</td>
      <td class="nm">${escapeHtml(r.job_name || "—")}</td>
      <td>${mode}</td>
      <td>${stBadge}</td>
      <td>${r.scanned}</td>
      <td>${r.matched}</td>
      <td>${r.dry_run ? "—" : r.deleted}</td>
      <td class="mono" style="font-size:11px">${when}</td>
      <td class="actions"></td>`;
    const act = tr.querySelector(".actions");
    if (r.status === "paused") {
      const res = document.createElement("button"); res.className = "iconbtn dry"; res.textContent = "resume";
      res.onclick = (e) => { e.stopPropagation(); resumeRun(r); };
      act.appendChild(res);
    }
    const del = document.createElement("button"); del.className = "iconbtn del"; del.textContent = "delete";
    del.onclick = (e) => { e.stopPropagation(); deleteRun(r); };
    act.appendChild(del);
    tr.onclick = () => showRunModal(r);
    tb.appendChild(tr);
  });
}

function resumeRun(r) {
  if (r.dry_run) {
    api(`/api/runs/${r.id}/resume`, { method: "POST", body: {} }).then((res) => {
      if (!res.ok) alert(res.error || "failed"); else loadRunsTable();
    });
    return;
  }
  const body = `<p>Resume live run <strong>#${r.id}</strong> (${escapeHtml(r.job_name || "")})?
    It continues deleting from where it stopped.</p>`;
  const chk = document.createElement("label"); chk.className = "confirm-chk";
  chk.innerHTML = `<input type="checkbox" id="confirmBox"> I understand this deletes messages`;
  openModal("Resume live run", body, [chk,
    mkBtn("Cancel", "ghost", closeModal),
    mkBtn("Resume & delete", "danger", async () => {
      if (!$("#confirmBox").checked) return;
      closeModal();
      const res = await api(`/api/runs/${r.id}/resume`, { method: "POST", body: { confirm: true } });
      if (!res.ok) alert(res.error || "failed"); else loadRunsTable();
    })]);
}

function showRunModal(r) {
  const det = (r.detail && r.detail.targets) ? r.detail.targets : [];
  const rows = det.map((t) => `<tr>
    <td class="nm">${escapeHtml(t.title || t.id)}${t.complete === false ? ' <span class="pill-sm" style="color:var(--amber)">partial</span>' : ""}</td>
    <td>${t.role || "-"}</td>
    <td>${t.scanned}</td><td>${t.matched}</td><td>${r.dry_run ? "—" : t.deleted}</td>
    <td class="mono" style="font-size:11px">${Object.entries(t.by_type || {}).map(([k, v]) => k + ":" + v).join(" ") || "—"}</td>
    <td class="mono" style="font-size:11px">${Object.entries(t.skips || {}).map(([k, v]) => k + ":" + v).join(" ") || "—"}</td>
  </tr>`).join("");

  // matched-message preview per target
  const previews = det.filter((t) => (t.samples || []).length).map((t) => {
    const sr = t.samples.map((m) => `<tr>
      <td class="mono" style="font-size:11px">${m.date}</td>
      <td class="mono" style="font-size:11px">${escapeHtml(m.type)}</td>
      <td class="mono" style="font-size:11px">${m.sender ?? ""}</td>
      <td>${escapeHtml(m.text)}</td></tr>`).join("");
    return `<div style="margin-top:16px">
      <div class="eyebrow" style="margin-bottom:6px">${r.dry_run ? "would delete" : "deleted"} — ${escapeHtml(t.title || String(t.id))}
        <span class="muted">(${t.matched} matched, showing first ${t.samples.length})</span></div>
      <table><thead><tr><th>date</th><th>type</th><th>sender</th><th>message</th></tr></thead>
      <tbody>${sr}</tbody></table></div>`;
  }).join("");

  const pausedNote = r.status === "paused"
    ? `<div class="notice" style="margin-top:0">This run is <strong>paused</strong> — it reached the
       per-run scan limit. Resume to continue from where it stopped.</div>` : "";

  const body = `
    ${pausedNote}
    <div class="grid three" style="margin-bottom:16px">
      <div class="stat"><div class="k">scanned</div><div class="v">${r.scanned}</div></div>
      <div class="stat"><div class="k">${r.dry_run ? "would delete (matched)" : "matched"}</div><div class="v">${r.matched}</div></div>
      <div class="stat"><div class="k">${r.dry_run ? "—" : "deleted"}</div><div class="v">${r.dry_run ? "—" : r.deleted}</div></div>
    </div>
    ${det.length ? `<table><thead><tr><th>target</th><th>role</th><th>scanned</th><th>matched</th><th>deleted</th><th>by type</th><th>skipped</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<p class="muted">No per-target detail yet (run may be starting).</p>`}
    ${previews || (det.length && r.matched === 0 ? `<p class="muted" style="margin-top:14px">No messages matched — nothing to ${r.dry_run ? "delete" : "remove"}. Check the skipped column for why.</p>` : "")}
    ${r.floodwait_total ? `<div class="muted mono" style="font-size:11px;margin-top:10px">floodwait waited: ${Math.round(r.floodwait_total)}s</div>` : ""}`;

  const foot = [];
  if (r.status === "paused") foot.push(mkBtn("Resume", "safe", () => { closeModal(); resumeRun(r); }));
  foot.push(mkBtn("Delete run", "danger", () => { closeModal(); deleteRun(r); }));
  foot.push(mkBtn("Close", "ghost", closeModal));
  openModal(`Run #${r.id} · ${r.dry_run ? "dry" : "live"} · ${escapeHtml(r.job_name || "")}`, body, foot);
}

async function deleteRun(r) {
  await api(`/api/runs/${r.id}`, { method: "DELETE" });
  loadRunsTable();
}

// ================= HOME =================
async function initHome() {
  const s = await refreshSession();
  const jobs = await api("/api/jobs");
  const runs = await api("/api/runs");
  $("#hJobs") && ($("#hJobs").textContent = jobs.length);
  $("#hRuns") && ($("#hRuns").textContent = runs.length);
  $("#hDeleted") && ($("#hDeleted").textContent = runs.reduce((a, r) => a + (r.deleted || 0), 0));
  const banner = $("#authBanner");
  if (banner) banner.classList.toggle("hidden", !!(s && s.authorized));
}

function escapeHtml(s) { return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ================= tab router (single page) =================
const PANELS = ["home", "create", "jobs", "reports", "login"];
const INITED = {};

function showTab(name) {
  if (!PANELS.includes(name)) name = "home";
  PANELS.forEach((p) => {
    const el = document.querySelector(`[data-panel="${p}"]`);
    if (el) el.classList.toggle("hidden", p !== name);
  });
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  if (location.hash.slice(1) !== name) location.hash = name;

  // build form once; refresh data-driven tabs every time they're shown (cheap, local DB)
  if (name === "create" && !INITED.create) { initCreate(); INITED.create = true; }
  else if (name === "login" && !INITED.login) { initLogin(); INITED.login = true; }
  else if (name === "jobs") loadJobsTable();
  else if (name === "reports") loadRunsTable();
  else if (name === "home") initHome();
}

// ================= theme =================
function initTheme() {
  const btn = $("#themeToggle");
  if (!btn) return;
  const glyph = (t) => (btn.textContent = t === "light" ? "☾" : "☀");
  glyph(document.documentElement.getAttribute("data-theme") || "dark");
  btn.onclick = () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("tgc-theme", next); } catch (e) {}
    glyph(next);
  };
}

// ================= boot =================
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  startLogStream();
  refreshSession();
  setInterval(refreshSession, 30000);
  startReportsTimer();
  const close = $("#modalClose"); if (close) close.onclick = closeModal;
  const back = $("#modal"); if (back) back.onclick = (e) => { if (e.target === back) closeModal(); };
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  showTab(location.hash.slice(1) || "home");
});
