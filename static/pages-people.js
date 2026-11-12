/* Part 4: leave, shift schedule, employee follow-up. */
const APPROVES = { technician: ["engineer"], assistant: ["supervisor"], engineer: ["superintendent"], supervisor: ["superintendent"] };
const FILE_OK = ".png,.jpg,.jpeg,.gif,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv";
const pad = n => String(n).padStart(2, "0");
const ymd = d => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());

/* ================= leave ================= */
registerPage("leave", { async render(el) {
  const u = App.user, mine = h("input", { type: "checkbox", id: "mine", style: "width:auto" });
  const box = h("div", { class: "box" });
  async function load() {
    const rows = (await api("GET", "/api/leave" + (mine.checked ? "?mine=1" : ""))).leave;
    const act = (text, fn, cls = "btn ghost sm") => h("button", { class: cls, onclick: fn }, text);
    const decide = (l, approve) => dlg((approve ? "Approve" : "Reject") + " leave: " + l.employee, [{ name: "note", label: "Note (optional)", type: "textarea" }],
      async v => { await api("POST", `/api/leave/${l.id}/decide`, { approve, note: v.note }); toast("Saved"); load(); }, approve ? "Approve" : "Reject");
    const quick = (path, body, msg) => async () => { try { await api("POST", `/api/leave/${path}`, body); toast(msg); load(); } catch (x) { toast(x.message, true); } };
    const report = id => { const i = h("input", { type: "file", accept: FILE_OK });
      i.onchange = async () => { const fd = new FormData(); fd.append("file", i.files[0]);
        try { await api("POST", `/api/leave/${id}/report`, fd); toast("Report uploaded"); load(); } catch (x) { toast(x.message, true); } }; i.click(); };
    box.replaceChildren(h("h2", {}, rows.length + " leave requests"), tbl([
      ["Employee", l => l.employee], ["Type", l => label(l.type)], ["From", l => l.start_date + (l.start_time ? " " + l.start_time : "")],
      ["To", l => l.end_date + (l.end_time ? " " + l.end_time : "")], ["Length", l => l.type === "partial" ? num2(l.hours) + " h" : l.days + " d"],
      ["Replacement", l => l.replacement_name || ""], ["Status", l => badge(l.status)], ["Reason", l => l.reason || ""],
      ["", l => {
        const own = l.user_id === u.id, canDecide = (APPROVES[l.employee_role] || []).includes(u.role) && !own;
        return h("div", { class: "acts-cell" },
          l.replacement_id === u.id && l.status === "awaiting_replacement" ? [act("Can cover", quick(`${l.id}/confirm`, { accept: true }, "Confirmed"), "btn sm"), act("Cannot", quick(`${l.id}/confirm`, { accept: false }, "Declined"))] : null,
          canDecide && l.status === "pending" ? [act("Approve", () => decide(l, true), "btn sm"), act("Reject", () => decide(l, false))] : null,
          own && l.type === "sick" ? act(l.has_report ? "Replace report" : "Upload report", () => report(l.id)) : null,
          l.has_report && (own || canDecide) ? h("a", { class: "btn ghost sm", href: `/api/leave/${l.id}/report` }, "Report") : null,
          own && ["awaiting_replacement", "pending", "approved"].includes(l.status) ? act("Cancel", quick(`${l.id}/cancel`, {}, "Cancelled")) : null);
      }]], rows, "No leave requests."));
  }
  mine.addEventListener("change", () => load().catch(x => toast(x.message, true)));
  el.append(h("div", { class: "bar" }, h("label", { for: "mine", style: "margin:0;font-weight:400" }, mine, " Only my leave"), h("span", { class: "sp" }),
    can(["technician", "assistant", "engineer", "supervisor"]) ? h("button", { class: "btn", onclick: applyDlg }, "Request leave") : null), box);
  await load();
} });

async function applyDlg() {
  const shift = isShift();
  const techs = shift ? (await api("GET", "/api/users")).users.filter(x => x.role === "technician" && x.active && x.id !== App.user.id).map(x => [x.id, x.name]) : [];
  dlg("Request leave", [
    { name: "type", label: "Type", type: "select", options: [["annual", "Annual leave"], ["partial", "Partial leave (hours)"], ["sick", "Sick leave"]] },
    { name: "start_date", label: "Start date", type: "date", required: true }, { name: "end_date", label: "End date (empty = same day)", type: "date" },
    { name: "start_time", label: "From time (partial leave only)", type: "time" }, { name: "end_time", label: "To time (partial leave only)", type: "time" },
    ...(shift ? [{ name: "replacement_id", label: "Replacement technician (must confirm)", type: "select", options: techs, blank: "Choose...", required: true }] : []),
    { name: "reason", label: "Reason", type: "textarea" }],
    async v => {
      const b = { type: v.type, start_date: v.start_date, end_date: v.end_date || v.start_date, reason: v.reason };
      if (v.type === "partial") { b.start_time = v.start_time; b.end_time = v.end_time; }
      if (shift) b.replacement_id = +v.replacement_id;
      await api("POST", "/api/leave", b);
      toast(v.type === "sick" ? "Request sent. Upload the doctor report from the list." : "Request sent"); route();
    }, "Send request");
}

/* ================= shift schedule ================= */
registerPage("shifts", { async render(el, p) {
  const now = new Date(), [y, m] = (p.month || now.getFullYear() + "-" + pad(now.getMonth() + 1)).split("-").map(Number);
  const last = new Date(y, m, 0).getDate(), from = `${y}-${pad(m)}-01`, to = `${y}-${pad(m)}-${pad(last)}`;
  const mv = n => { const d = new Date(y, m - 1 + n, 1); return "#/shifts?month=" + d.getFullYear() + "-" + pad(d.getMonth() + 1); };
  const d = await api("GET", `/api/shifts?from=${from}&to=${to}`);
  const grid = {}; d.rows.forEach(r => { (grid[r.day] = grid[r.day] || {})[r.shift_group] = r.code; });
  const edit = can(["superintendent"]), G = ["A", "B", "C", "D"];
  const cell = (day, g) => {
    const c = (grid[day] || {})[g];
    if (!c) return edit ? h("button", { class: "code", onclick: () => setCode(day, g, "O") }, "-") : "-";
    return edit ? h("button", { class: "code " + c, title: "Change", onclick: () => setCode(day, g, c) }, c) : h("span", { class: "code " + c }, c);
  };
  const setCode = (day, g, cur) => dlg(`Shift ${g} on ${day}`, [{ name: "code", label: "Code", type: "select", value: cur,
    options: [["M", "M - Morning"], ["A", "A - Afternoon"], ["N", "N - Night"], ["O", "O - Off"]] }],
    async v => { await api("PUT", `/api/shifts/${day}/${g}`, { code: v.code }); route(); });
  const days = Array.from({ length: last }, (_, i) => new Date(y, m - 1, i + 1));
  const gen = () => dlg("Generate a year of shifts", [
    { name: "year", label: "Year", type: "number", value: y, required: true },
    { name: "pattern", label: "Repeating cycle (codes M, A, N, O separated by commas)", value: "M,M,A,A,N,N,O,O", required: true },
    ...G.map(g => ({ name: "off" + g, label: `Shift ${g} position in the cycle on 1 January (0 = first)`, type: "number", value: G.indexOf(g) * 2 }))],
    async v => {
      const offsets = Object.fromEntries(G.map(g => [g, parseInt(v["off" + g], 10) || 0]));
      await api("POST", "/api/shifts/generate", { year: +v.year, pattern: v.pattern.split(",").map(s => s.trim().toUpperCase()), offsets });
      toast("Schedule generated"); route();
    }, "Generate");
  el.append(h("div", { class: "bar" }, h("a", { class: "btn ghost", href: mv(-1) }, "Previous month"), h("b", {}, new Date(y, m - 1, 1).toLocaleString("en", { month: "long", year: "numeric" })),
    h("a", { class: "btn ghost", href: mv(1) }, "Next month"), h("span", { class: "sp" }),
    edit ? h("button", { class: "btn ghost", onclick: gen }, "Generate year") : null),
    h("div", { class: "box" }, d.rows.length ? h("table", {}, h("thead", {}, h("tr", {}, [h("th", {}, "Day"), ...G.map(g => h("th", {}, "Shift " + g, h("br"), h("small", {}, d.people[g] || "")))])),
      h("tbody", {}, days.map(dt => { const k = ymd(dt), wd = dt.getDay();
        return h("tr", { class: (wd === 5 || wd === 6 ? "we " : "") + (k === ymd(now) ? "today" : "") },
          h("td", {}, dt.toLocaleString("en", { weekday: "short" }) + " " + dt.getDate()), G.map(g => h("td", {}, cell(k, g)))); })))
      : h("p", { class: "empty" }, edit ? "No schedule for this month. Use Generate year." : "No schedule for this month yet.")));
} });

/* ================= employee follow-up ================= */
registerPage("followup", { async render(el, p) {
  const y = +(p.year || new Date().getFullYear());
  const d = await api("GET", "/api/followup?year=" + y);
  const ys = h("select", { style: "width:auto" }, [y - 1, y, y + 1].map(v => h("option", { value: v }, v)));
  ys.value = y; ys.onchange = () => { location.hash = "#/followup?year=" + ys.value; };
  el.append(h("div", { class: "bar" }, ys),
    h("div", { class: "box" }, h("h2", {}, "On leave today"), d.on_leave_today.length
      ? tbl([["Employee", x => x.name], ["Type", x => label(x.type)]], d.on_leave_today) : h("p", { class: "empty" }, "Nobody is on leave today.")),
    h("div", { class: "box" }, h("h2", {}, "Approved leave in " + y), tbl([["Employee", e => e.name], ["Role", e => ROLE_LABEL[e.role] + (e.shift_group ? " (shift " + e.shift_group + ")" : "")],
      ["Annual days", e => num2(e.annual_days)], ["Sick days", e => num2(e.sick_days)], ["Partial hours", e => num2(e.partial_hours)]], d.employees)));
} });
