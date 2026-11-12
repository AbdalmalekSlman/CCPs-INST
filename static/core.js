/* CMMS front end - core: api, login, shell, navigation, notifications, dashboard.
   Later parts add files that call registerPage(id, {render(el, params, rest)}). */
const $ = (s, r = document) => r.querySelector(s);
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
async function api(method, url, body) {
  const o = { method, headers: {}, credentials: "same-origin" };
  if (body instanceof FormData) o.body = body;
  else if (body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(url, o);
  let j = {};
  try { j = await r.json(); } catch {}
  if (r.status === 401 && url !== "/api/login") { App.user = null; showLogin(); throw new Error("Please sign in"); }
  if (!r.ok) throw new Error(j.error || "Request failed (" + r.status + ")");
  return j;
}
function toast(msg, bad) {
  const t = h("div", { class: "toast" + (bad ? " bad" : "") }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 3500);
}
const label = s => String(s || "").replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const badge = s => h("span", { class: "badge " + s }, label(s));
const fmtDT = s => (s || "").slice(0, 16).replace("T", " ");

const App = { user: null, pages: {} };
const ROLE_LABEL = { superintendent: "Superintendent", engineer: "Engineer", supervisor: "Supervisor technician",
  technician: "Technician", assistant: "Technician assistant", stock_keeper: "Stock keeper" };
const ENG = ["superintendent", "engineer", "supervisor"];
/* id, label, roles allowed (undefined = everyone; admin always allowed) */
const NAV = [
  ["dashboard", "Dashboard"], ["requests", "Work requests"], ["weekly", "Weekly plan", ENG],
  ["instruments", "Instruments"], ["valves", "Control valves"], ["stock", "Spare parts"],
  ["purchases", "Purchase requests", [...ENG, "stock_keeper"]], ["pm", "Preventive maintenance"],
  ["leave", "Leave", ["technician", "assistant", ...ENG]], ["shifts", "Shift schedule"],
  ["followup", "Employee follow-up", ENG], ["reports", "Reports", ENG], ["admin", "Users & lists", ["admin"]],
];
const can = roles => !roles || App.user.is_admin || roles.includes(App.user.role);
function registerPage(id, page) { App.pages[id] = page; }

/* ---------- login ---------- */
function showLogin() {
  const msg = h("p", { class: "err", role: "alert" });
  const u = h("input", { id: "u", autocomplete: "username", autocapitalize: "none", required: true });
  const p = h("input", { id: "p", type: "password", autocomplete: "current-password", required: true });
  const f = h("form", { onsubmit: async e => {
    e.preventDefault(); msg.textContent = "";
    try { App.user = (await api("POST", "/api/login", { username: u.value, password: p.value })).user; start(); }
    catch (x) { msg.textContent = x.message; }
  } }, h("h1", {}, "CMMS"), h("p", { class: "sub" }, "CCPs Instrument department"),
    h("label", { for: "u" }, "Username"), u, h("label", { for: "p" }, "Password"), p,
    msg, h("button", { class: "btn" }, "Sign in"));
  $("#app").replaceChildren(h("div", { class: "login" }, f));
  u.focus();
}

function showChangePassword(forced) {
  const msg = h("p", { class: "err", role: "alert" });
  const o = h("input", { id: "o", type: "password", autocomplete: "current-password", required: true });
  const n = h("input", { id: "n", type: "password", autocomplete: "new-password", minlength: 8, required: true });
  const c = h("input", { id: "c", type: "password", autocomplete: "new-password", required: true });
  const f = h("form", { onsubmit: async e => {
    e.preventDefault(); msg.textContent = "";
    if (n.value !== c.value) { msg.textContent = "The new passwords do not match."; return; }
    try { await api("POST", "/api/change-password", { old_password: o.value, new_password: n.value });
      App.user.must_change = 0; toast("Password changed"); start(); }
    catch (x) { msg.textContent = x.message; }
  } }, h("h1", {}, forced ? "Choose a new password" : "Change password"),
    forced ? h("p", { class: "sub" }, "You are using the default password. Pick your own to continue.") : null,
    h("label", { for: "o" }, "Current password"), o, h("label", { for: "n" }, "New password (8+ characters)"), n,
    h("label", { for: "c" }, "Repeat new password"), c, msg,
    h("button", { class: "btn" }, "Save password"),
    forced ? null : h("button", { type: "button", class: "btn ghost", style: "margin-top:.5rem", onclick: start }, "Cancel"));
  $("#app").replaceChildren(h("div", { class: "login" }, f));
  o.focus();
}

/* ---------- shell ---------- */
let pollTimer;
function start() {
  if (App.user.must_change) return showChangePassword(true);
  const nav = h("nav", {}, NAV.filter(n => can(n[2])).map(n => h("a", { href: "#/" + n[0], "data-id": n[0] }, n[1])));
  const side = h("aside", { class: "side", id: "side" },
    h("div", { class: "who" }, h("b", {}, App.user.name),
      h("span", {}, ROLE_LABEL[App.user.role] + (App.user.is_admin ? " · Admin" : ""))),
    nav, h("div", { class: "foot" },
      h("button", { onclick: () => showChangePassword(false) }, "Password"),
      h("button", { onclick: async () => { await api("POST", "/api/logout"); clearInterval(pollTimer); App.user = null; showLogin(); } }, "Sign out")));
  const bell = h("button", { class: "bell", id: "bell", "aria-label": "Notifications", onclick: togglePanel }, "Alerts");
  const top = h("header", { class: "top" },
    h("button", { class: "menu", "aria-label": "Menu", onclick: () => side.classList.toggle("open") }, "Menu"),
    h("h1", { id: "title" }), bell);
  $("#app").replaceChildren(h("div", { class: "shell" }, side,
    h("div", { class: "main" }, top, h("main", { class: "page", id: "page" }))));
  side.addEventListener("click", e => { if (e.target.closest("nav a")) side.classList.remove("open"); });
  clearInterval(pollTimer); pollNotes(); pollTimer = setInterval(pollNotes, 60000);
  route();
}

/* ---------- router: #/page/rest?query ---------- */
function route() {
  if (!App.user || App.user.must_change) return;
  const [path, qs] = (location.hash.slice(2) || "dashboard").split("?");
  const [id, ...rest] = path.split("/");
  const nav = NAV.find(n => n[0] === id);
  const el = $("#page");
  if (!nav || !can(nav[2])) { location.hash = "#/dashboard"; return; }
  $("#title").textContent = nav[1];
  document.title = nav[1] + " - CMMS";
  document.querySelectorAll(".side nav a").forEach(a => a.classList.toggle("on", a.dataset.id === id));
  const page = App.pages[id];
  el.replaceChildren();
  if (!page) { el.append(h("div", { class: "box" }, "This page is built in a later part of the front end.")); return; }
  Promise.resolve(page.render(el, Object.fromEntries(new URLSearchParams(qs || "")), rest))
    .catch(x => el.replaceChildren(h("div", { class: "box err" }, x.message)));
}
window.addEventListener("hashchange", route);

/* ---------- notifications ---------- */
async function pollNotes() {
  try {
    const d = await api("GET", "/api/notifications");
    App.notes = d.notifications;
    const b = $("#bell");
    if (!b) return;
    b.replaceChildren(...["Alerts", d.unread ? h("i", {}, d.unread) : null].filter(Boolean));
    if ($("#panel")) drawPanel();
  } catch {}
}
function togglePanel() { const p = $("#panel"); if (p) p.remove(); else { document.body.append(h("div", { class: "panel", id: "panel" })); drawPanel(); } }
function drawPanel() {
  const p = $("#panel"), list = App.notes || [];
  p.replaceChildren(h("header", {}, "Notifications",
    h("button", { onclick: async () => { await api("POST", "/api/notifications/read-all"); pollNotes(); } }, "Mark all read")),
    ...(list.length ? list.map(n => h("div", { class: "note" + (n.is_read ? "" : " unread"), onclick: async () => {
      if (!n.is_read) await api("POST", `/api/notifications/${n.id}/read`);
      p.remove(); if (n.wr_id) location.hash = "#/requests/" + n.wr_id; pollNotes();
    } }, n.message, h("small", {}, fmtDT(n.created_at)))) : [h("div", { class: "empty" }, "No notifications yet.")]));
}
document.addEventListener("click", e => { const p = $("#panel"); if (p && !p.contains(e.target) && !e.target.closest("#bell")) p.remove(); });

/* ---------- dashboard ---------- */
registerPage("dashboard", { async render(el) {
  const jobs = (await api("GET", "/api/work-requests")).requests
    .filter(r => !["completed", "cancelled"].includes(r.status));
  if (ENG.includes(App.user.role) || App.user.is_admin) {
    try {
      const o = await api("GET", "/api/overview"), s = o.requests_by_status;
      const open = Object.entries(s).filter(([k]) => !["completed", "cancelled"].includes(k)).reduce((a, [, v]) => a + v, 0);
      const card = (n, t, href, cls) => h("a", { class: "stat " + (cls || ""), href }, h("b", {}, n), t);
      el.append(h("div", { class: "cards" },
        card(open, "Open requests", "#/requests"),
        card(o.overdue, "Overdue", "#/requests?overdue=1", o.overdue ? "bad" : ""),
        card(o.open_emergency, "Open emergencies", "#/requests?priority=emergency", o.open_emergency ? "bad" : ""),
        card(o.low_stock, "Low stock items", "#/stock?low=1", o.low_stock ? "warn" : ""),
        card(o.purchase_pending, "Purchase requests pending", "#/purchases", o.purchase_pending ? "warn" : ""),
        card(o.leave_to_decide, "Leave to decide", "#/leave", o.leave_to_decide ? "warn" : ""),
        card(o.on_leave_today, "On leave today", "#/followup"),
        card(o.pm_due_7_days, "PM due in 7 days", "#/pm")));
    } catch (x) { toast(x.message, true); }
  }
  el.append(h("div", { class: "box" }, h("h2", {}, "My active work requests"),
    jobs.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Code", "Instrument", "Work needed", "Scheduled", "Status"].map(t => h("th", {}, t)))),
      h("tbody", {}, jobs.map(r => h("tr", {}, h("td", {}, h("a", { href: "#/requests/" + r.id }, r.code)),
        h("td", {}, r.instrument_tag), h("td", {}, r.work_needed), h("td", {}, fmtDT(r.scheduled_at)),
        h("td", {}, badge(r.status), r.overdue ? [" ", badge("overdue")] : null)))))
      : h("p", { class: "empty" }, "Nothing active right now.")));
} });

/* ---------- boot ---------- */
async function boot() {
  try { App.user = (await api("GET", "/api/me")).user; start(); } catch { showLogin(); }
}
