const $ = (s) => document.querySelector(s);
const money = (n) => "$" + Number(n).toLocaleString("en-US", {maximumFractionDigits: 2});

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* ---------- summary ---------- */
async function loadSummary() {
  const s = await api("/api/summary");
  $("#sim-now").textContent = "sim time " + s.sim_now.replace("T", " ").slice(0, 16);
  $("#cards").innerHTML = [
    ["Value at risk (open)", money(s.value_at_risk_open), "bad"],
    ["Open discrepancies", s.open_count, ""],
    ["Pending approvals", s.pending, "warn"],
    ["Value reconciled", money(s.value_reconciled), "good"],
    ["Agent accuracy", (s.accuracy * 100).toFixed(1) + "%", "accent"],
  ].map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`
  ).join("");
  $("#queue-count").textContent = s.pending;
  document.querySelector(".top-causes")?.remove();
  const tc = document.createElement("div");
  tc.className = "top-causes";
  tc.innerHTML = "<span style='border:none;background:none'>Top root causes (7d):</span>" +
    s.top_root_causes_week.map((t) => `<span>${t.cause} ×${t.count}</span>`).join("");
  document.querySelector("nav.tabs").after(tc);
}

/* ---------- discrepancies ---------- */
async function loadDiscs() {
  const rows = await api("/api/discrepancies");
  $("#disc-table tbody").innerHTML = rows.map((d) => `
    <tr data-id="${d.id}">
      <td>${d.id}</td><td>${d.category}</td>
      <td>${d.sku}<br><span style="color:var(--dim)">${d.lot_code || ""}</span></td>
      <td class="num">${d.erp_qty ?? "—"}</td><td class="num">${d.wms_qty ?? "—"}</td>
      <td class="num sev-${d.severity}">${money(d.value_at_risk)}</td>
      <td>${d.root_cause || "—"}</td>
      <td class="status-${d.inv_status || ""}">${d.inv_status || "OPEN"}</td>
    </tr>`).join("");
  document.querySelectorAll("#disc-table tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => openDrawer(tr.dataset.id)));
}

/* ---------- drawer ---------- */
async function openDrawer(id) {
  const { discrepancy: d, investigation: inv, label_url } =
    await api("/api/discrepancy/" + id);
  let html = `<h2>${d.id} · ${d.category}</h2>
    <p>${d.sku} · lot ${d.lot_code || "—"} · <b class="sev-${d.severity}">${money(d.value_at_risk)}</b> at risk</p>
    <p>ERP ${d.erp_qty ?? "—"} ${d.uom || ""} vs WMS ${d.wms_qty ?? "—"} ${d.uom || ""}</p>`;
  if (inv) {
    html += `<p>Root cause: <b>${inv.root_cause}</b> (confidence ${inv.confidence})
      <span class="status-${inv.status}"> · ${inv.status}</span></p>
      <h3>Evidence trail</h3><ul class="evidence">` +
      inv.evidence.map((e) => `<li>${e}</li>`).join("") + `</ul>
      <div class="fix"><div class="action">Proposed fix [requires approval]: ${inv.proposed_fix.action}</div>
      <p>${inv.proposed_fix.description}</p></div>`;
    if (inv.status === "PENDING_APPROVAL") {
      html += `<div class="btns">
        <button class="approve" data-act="approve" data-id="${inv.id}">Approve fix</button>
        <button class="reject" data-act="reject" data-id="${inv.id}">Reject</button>
      </div>`;
    } else {
      html += `<p class="note">Decided ${inv.decided_at || ""}${inv.decide_note ? " — " + inv.decide_note : ""}</p>`;
    }
  } else {
    html += `<p class="note">Not yet investigated.</p>`;
  }
  if (label_url) html += `<h3>Pallet label</h3><img class="label-img" src="${label_url}">`;
  $("#drawer-body").innerHTML = html;
  $("#drawer").classList.remove("hidden");
  document.querySelectorAll("#drawer-body [data-act]").forEach((b) =>
    b.addEventListener("click", () => decide(b.dataset.id, b.dataset.act)));
}

async function decide(id, action) {
  const note = prompt(`Note for ${action} ${id} (optional):`) || "";
  await api(`/api/investigations/${id}/${action}`,
    { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ note }) });
  $("#drawer").classList.add("hidden");
  await refresh();
}
$("#drawer-close").addEventListener("click", () =>
  $("#drawer").classList.add("hidden"));

/* ---------- queue ---------- */
async function loadQueue() {
  const rows = await api("/api/queue");
  const pend = rows.filter((r) => r.status === "PENDING_APPROVAL");
  $("#queue-table tbody").innerHTML = pend.map((r) => {
    const fix = JSON.parse(r.proposed_fix);
    return `<tr>
      <td>${r.id}</td><td class="num">${money(r.priority)}</td>
      <td>${r.root_cause}${r.repeat_group ? ` <span class="note">[repeat of ${r.repeat_group}]</span>` : ""}</td>
      <td>${r.sku}<br><span style="color:var(--dim)">${r.lot_code || ""}</span></td>
      <td class="num">${money(r.value_at_risk)}</td>
      <td><b>${fix.action}</b><br><span class="note">${fix.description.slice(0, 80)}…</span></td>
      <td><button class="approve" data-act="approve" data-id="${r.id}">Approve</button>
          <button class="reject" data-act="reject" data-id="${r.id}">Reject</button></td>
    </tr>`;
  }).join("");
  document.querySelectorAll("#queue-table [data-act]").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); decide(b.dataset.id, b.dataset.act); }));
}

/* ---------- eval ---------- */
async function loadEval() {
  const e = await api("/api/eval");
  $("#eval-summary").innerHTML = [
    ["Accuracy", (e.accuracy * 100).toFixed(1) + "%", "accent"],
    ["Evaluated", e.total_evaluated, ""],
    ["Correct", e.correct, "good"],
    ["Missed", e.misses.length, e.misses.length ? "bad" : ""],
  ].map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`
  ).join("");
  $("#eval-cats").innerHTML = Object.entries(e.per_category).map(([cat, b]) => `
    <div class="bar-row"><div class="name">${cat}</div>
      <div class="bar"><div style="width:${b.accuracy * 100}%"></div></div>
      <div>${b.correct}/${b.n} (${(b.accuracy * 100).toFixed(0)}%)</div></div>`
  ).join("");
  $("#eval-misses").innerHTML = e.misses.length
    ? e.misses.map((m) => `<div class="miss"><b>${m.inv_id}</b> ${m.sku} ${m.lot_code}:
        diagnosed <b>${m.diagnosed}</b>, truth <b>${m.truth}</b>
        (confidence ${m.confidence})</div>`).join("")
    : `<p class="note">No misses — every investigated discrepancy matched ground truth.</p>`;
  $("#eval-note").textContent = e.note;
}

/* ---------- tabs + boot ---------- */
function showTab(name) {
  document.querySelectorAll("nav.tabs button").forEach((x) =>
    x.classList.toggle("active", x.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.add("hidden"));
  $("#tab-" + name).classList.remove("hidden");
}
document.querySelectorAll("nav.tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
const deep = location.hash.replace("#", "");
if (deep && document.querySelector(`[data-tab="${deep}"]`)) showTab(deep);

async function refresh() {
  await Promise.all([loadSummary(), loadDiscs(), loadQueue(), loadEval()]);
}
refresh();
