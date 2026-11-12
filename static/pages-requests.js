/* Part 3: work requests (list, issue, detail, crew, life cycle, notes, files) and weekly plan. */
const WR_STATUS = ["issued", "assigned", "in_progress", "completion_requested", "completed", "on_hold", "cancelled"];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const isShift = () => App.user.role === "technician" && !!App.user.shift_group;
const wrBadges = r => [badge(r.status), r.overdue ? [" ", badge("overdue")] : null, r.priority === "emergency" ? [" ", badge("emergency")] : null].flat();

registerPage("requests", { async render(el, p, rest) { return rest[0] ? reqDetail(el, +rest[0]) : reqList(el, p); } });

/* ---------- list ---------- */
async function reqList(el, p) {
  const st = h("select", {}, h("option", { value: "" }, "All statuses"), WR_STATUS.map(s => h("option", { value: s }, label(s))));
  st.value = p.status || "";
  const tag = h("input", { placeholder: "Instrument tag", value: p.tag || "" });
  const box = h("div", { class: "box" });
  async function load() {
    const qs = new URLSearchParams();
    if (st.value) qs.set("status", st.value); if (tag.value) qs.set("tag", tag.value); if (p.priority) qs.set("priority", p.priority);
    let r = (await api("GET", "/api/work-requests?" + qs)).requests;
    if (p.overdue === "1") r = r.filter(x => x.overdue);
    box.replaceChildren(...[h("h2", {}, r.length + " requests"),
      p.overdue || p.priority ? h("p", {}, "Filtered. ", h("a", { href: "#/requests" }, "Clear filter")) : null,
      tbl([["Request", x => h("a", { href: "#/requests/" + x.id }, x.code)], ["Instrument", x => x.instrument_tag], ["Area", x => x.area || ""],
        ["Work needed", x => x.work_needed], ["Scheduled", x => fmtDT(x.scheduled_at)], ["Status", wrBadges], ["Leader", x => x.leader_name]], r,
        "No work requests.")].filter(Boolean));
  }
  const go = debounce(() => load().catch(x => toast(x.message, true)));
  st.addEventListener("input", go); tag.addEventListener("input", go);
  el.append(h("div", { class: "bar" }, st, tag, h("span", { class: "sp" }),
    can(["superintendent"]) || isShift() ? h("button", { class: "btn", onclick: () => issueDlg(false) }, "Issue request") : null,
    can(["engineer", "supervisor"]) ? h("button", { class: "btn danger", onclick: () => issueDlg(true) }, "Emergency request") : null), box);
  await load();
}

async function issueDlg(emergency) {
  const [ins, jt, wn, us] = await Promise.all([api("GET", "/api/instruments"), api("GET", "/api/options/job_title"),
    api("GET", "/api/options/work_needed"), api("GET", "/api/users")]);
  const leaders = us.users.filter(u => u.is_leader && u.active).map(u => [u.id, u.name]);
  dlg(emergency ? "Emergency request" : "Issue work request", [
    { name: "instrument_tag", label: "Instrument tag", list: ins.instruments.map(i => i.tag), required: true },
    { name: "job_title", label: "Job title", type: "select", options: jt.options, addNew: addOpt("job_title"), required: true },
    { name: "work_needed", label: "Work needed", type: "select", options: wn.options, addNew: addOpt("work_needed"), required: true },
    { name: "details", label: "Details", type: "textarea" },
    { name: "scheduled_at", label: emergency ? "Date and time (empty = now)" : "Scheduled date and time", type: "datetime-local", required: !emergency },
    ...(emergency ? [] : [{ name: "leader_id", label: "Team leader", type: "select", options: leaders, blank: "Choose...", required: true }])],
    async v => {
      const b = { ...v };
      if (emergency) b.priority = "emergency"; else b.leader_id = +v.leader_id;
      if (!v.scheduled_at) delete b.scheduled_at;
      const r = await api("POST", "/api/work-requests", b);
      toast("Issued " + r.code); location.hash = "#/requests/" + r.id;
    }, "Issue");
}

/* ---------- detail ---------- */
async function reqDetail(el, id) {
  const w = (await api("GET", "/api/work-requests/" + id)).request;
  const u = App.user, st = w.status;
  const leader = u.is_admin || u.id === w.leader_id, mgr = leader || u.role === "superintendent";
  const crew = w.crew.some(c => c.id === u.id), doer = mgr || crew;
  const post = (path, body) => api("POST", `/api/work-requests/${id}/${path}`, body);
  const quick = (path, text) => h("button", { class: "btn sm", onclick: async () => { try { await post(path, {}); toast("Done"); route(); } catch (x) { toast(x.message, true); } } }, text);
  const withNote = (path, text, extra, cls = "btn ghost sm") => h("button", { class: cls, onclick: () => dlg(text, [{ name: "note", label: "Note (optional)", type: "textarea" }],
    async v => { await post(path, { ...extra, ...v }); toast("Done"); route(); }, text) }, text);
  const acts = [
    leader && ["issued", "assigned"].includes(st) ? h("button", { class: "btn sm", onclick: () => assignDlg(id) }, st === "issued" ? "Assign crew" : "Change crew") : null,
    doer && st === "assigned" ? quick("start", "Start work") : null,
    doer && st === "in_progress" ? withNote("request-completion", "Request completion", {}, "btn sm") : null,
    leader && st === "completion_requested" ? withNote("review", "Approve completion", { approve: true }, "btn sm") : null,
    leader && st === "completion_requested" ? withNote("review", "Send back", { approve: false }) : null,
    mgr && ["assigned", "in_progress"].includes(st) ? withNote("hold", "Put on hold", {}) : null,
    mgr && st === "on_hold" ? quick("resume", "Resume") : null,
    mgr && ["issued", "assigned", "in_progress", "on_hold"].includes(st) ? withNote("cancel", "Cancel request", {}, "btn danger sm") : null,
    ["assigned", "in_progress", "on_hold"].includes(st) ? h("button", { class: "btn ghost sm", onclick: () => partsDlg(id) }, "Request parts") : null];

  const noteTxt = h("textarea", { rows: 2, placeholder: "Write a note" });
  const fileIn = h("input", { type: "file", accept: ".png,.jpg,.jpeg,.gif,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv" });
  el.append(h("a", { class: "back", href: "#/requests" }, "Back to requests"),
    h("div", { class: "box" }, h("h2", {}, w.code, " ", wrBadges(w)), h("dl", { class: "kv" },
      h("dt", {}, "Instrument"), h("dd", {}, h("a", { href: "#/instruments/" + encodeURIComponent(w.instrument_tag) }, w.instrument_tag)),
      h("dt", {}, "Job title"), h("dd", {}, w.job_title), h("dt", {}, "Work needed"), h("dd", {}, w.work_needed),
      h("dt", {}, "Details"), h("dd", {}, w.details || "-"), h("dt", {}, "Scheduled"), h("dd", {}, fmtDT(w.scheduled_at)),
      h("dt", {}, "Team leader"), h("dd", {}, w.leader_name), h("dt", {}, "Issued by"), h("dd", {}, w.creator_name),
      h("dt", {}, "Crew"), h("dd", {}, w.crew.length ? w.crew.map(c => c.name + " (" + c.crew_role + ")").join(", ") : "Not assigned yet")),
      h("div", { class: "acts-cell", style: "flex-wrap:wrap" }, acts)),
    h("div", { class: "box" }, h("h2", {}, "Life cycle"), tbl([["When", e => fmtDT(e.created_at)], ["Phase", e => label(e.event)],
      ["Note", e => e.note || ""], ["By", e => e.by_name || "System"]], w.events)),
    h("div", { class: "box" }, h("h2", {}, "Spare parts"), tbl([["Part", x => x.name], ["Quantity", x => num2(x.qty)], ["Status", x => label(x.status)]], w.parts, "No parts requested.")),
    h("div", { class: "box" }, h("h2", {}, "Notes"),
      w.notes.length ? w.notes.map(n => h("p", {}, h("b", {}, n.by_name || ""), " ", h("small", {}, fmtDT(n.created_at)), h("br"), n.text)) : h("p", { class: "empty" }, "No notes yet."),
      noteTxt, h("button", { class: "btn sm", style: "margin-top:.5rem", onclick: async () => {
        if (!noteTxt.value.trim()) return;
        try { await post("notes", { text: noteTxt.value }); route(); } catch (x) { toast(x.message, true); } } }, "Add note")),
    h("div", { class: "box" }, h("h2", {}, "Attachments"),
      w.files.length ? h("ul", {}, w.files.map(f => h("li", {}, h("a", { href: "/api/files/" + f.id }, f.filename), " ", h("small", {}, fmtDT(f.created_at))))) : h("p", { class: "empty" }, "No attachments."),
      fileIn, h("button", { class: "btn sm", style: "margin-top:.5rem", onclick: async () => {
        if (!fileIn.files[0]) return toast("Choose a file first", true);
        const fd = new FormData(); fd.append("file", fileIn.files[0]);
        try { await post("files", fd); toast("Uploaded"); route(); } catch (x) { toast(x.message, true); } } }, "Upload")));
}

async function assignDlg(id) {
  const c = await api("GET", `/api/work-requests/${id}/available-crew`);
  const av = a => a.filter(t => t.available).map(t => [t.id, t.name]);
  dlg("Assign crew", [
    { name: "technician_id", label: "Technician (available that day)", type: "select", options: av(c.technicians), blank: "Choose...", required: true },
    { name: "assistant_id", label: "Technician assistant (optional)", type: "select", options: av(c.assistants), blank: "None" }],
    async v => { await api("POST", `/api/work-requests/${id}/assign`, { technician_id: +v.technician_id, assistant_id: v.assistant_id ? +v.assistant_id : null }); toast("Crew assigned"); route(); }, "Assign");
}

async function partsDlg(id) {
  const items = (await api("GET", "/api/stock")).items;
  dlg("Request spare parts", [
    { name: "item_id", label: "Part", type: "select", options: items.map(i => [i.id, `${i.name} (${num2(i.available)} ${i.unit} available)`]), blank: "Choose...", required: true },
    { name: "qty", label: "Quantity", type: "number", required: true }],
    async v => { await api("POST", `/api/work-requests/${id}/parts`, { item_id: +v.item_id, qty: +v.qty }); toast("Parts requested"); route(); }, "Request");
}

/* ---------- weekly plan ---------- */
registerPage("weekly", { async render(el, p) {
  const d = await api("GET", "/api/weekly-plan" + (p.week_start ? "?week_start=" + p.week_start : ""));
  const ws = d.week_start;
  const shift = n => { const t = new Date(ws + "T00:00:00"); t.setDate(t.getDate() + n);
    return t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-" + String(t.getDate()).padStart(2, "0"); };
  const boxes = d.requests.map(r => ({ r, c: h("input", { type: "checkbox", style: "width:auto", "aria-label": "Select " + r.code }) }));
  const all = h("input", { type: "checkbox", style: "width:auto", "aria-label": "Select all", onchange: () => boxes.forEach(b => { b.c.checked = all.checked; }) });
  const print = () => {
    const rows = boxes.filter(b => b.c.checked).map(b => b.r);
    if (!rows.length) return toast("Select at least one request", true);
    const w = window.open("", "_blank");
    w.document.write(`<html><head><title>Weekly plan</title><style>body{font:14px sans-serif;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #999;padding:6px;text-align:left}</style></head><body><h2>Weekly plan ${esc(ws)} to ${esc(shift(4))}</h2><table><tr><th>Instrument tag</th><th>Plant</th><th>Work needed</th></tr>${rows.map(r => `<tr><td>${esc(r.instrument_tag)}</td><td>${esc(r.area)}</td><td>${esc(r.work_needed)}</td></tr>`).join("")}</table></body></html>`);
    w.document.close(); w.focus(); w.print();
  };
  const byId = Object.fromEntries(boxes.map(b => [b.r.id, b.c]));
  el.append(h("div", { class: "bar" }, h("a", { class: "btn ghost", href: "#/weekly?week_start=" + shift(-7) }, "Previous week"),
    h("b", {}, `Sunday ${ws} to Thursday ${shift(4)}`), h("a", { class: "btn ghost", href: "#/weekly?week_start=" + shift(7) }, "Next week"),
    h("span", { class: "sp" }), h("button", { class: "btn", onclick: print }, "Print selected")),
    h("div", { class: "box" }, d.requests.length ? h("table", {}, h("thead", {}, h("tr", {}, [h("th", {}, all), ...["Request", "Instrument", "Plant", "Work needed", "Scheduled", "Status", "Leader"].map(t => h("th", {}, t))])),
      h("tbody", {}, d.requests.map(r => h("tr", {}, h("td", {}, byId[r.id]), h("td", {}, h("a", { href: "#/requests/" + r.id }, r.code)),
        h("td", {}, r.instrument_tag), h("td", {}, r.area || ""), h("td", {}, r.work_needed), h("td", {}, fmtDT(r.scheduled_at)),
        h("td", {}, wrBadges(r)), h("td", {}, r.leader_name))))) : h("p", { class: "empty" }, "No work requests scheduled this week.")));
} });
