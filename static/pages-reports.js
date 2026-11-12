/* Part 5: preventive maintenance plans and reports (overview, daily, weekly, evaluation). */
const addDays = (s, n) => { const t = new Date(s + "T00:00:00"); t.setDate(t.getDate() + n); return ymd(t); };

/* ================= preventive maintenance ================= */
registerPage("pm", { async render(el) {
  const [pl, jt, wn, us] = await Promise.all([api("GET", "/api/pm/plans"), api("GET", "/api/options/job_title"),
    api("GET", "/api/options/work_needed"), api("GET", "/api/users")]);
  const soon = addDays(ymd(new Date()), 7), isSup = can(["superintendent"]), isEng = can(["engineer", "superintendent"]);
  const leaders = us.users.filter(u => u.is_leader && u.active).map(u => [u.id, u.name]);
  const planFields = p => [
    { name: "name", label: "Plan name", value: p?.name, required: true },
    { name: "job_title", label: "Job title", type: "select", options: jt.options, addNew: addOpt("job_title"), value: p?.job_title, required: true },
    { name: "work_needed", label: "Work needed", type: "select", options: wn.options, addNew: addOpt("work_needed"), value: p?.work_needed, required: true },
    { name: "interval_days", label: "Repeat every (days)", type: "number", value: p?.interval_days, required: true },
    { name: "next_due", label: "Next due date", type: "date", value: p?.next_due, required: true },
    { name: "time_of_day", label: "Time of day", type: "time", value: p?.time_of_day || "07:00" },
    ...(p ? [{ name: "active", label: "Status", type: "select", options: [["1", "Active"], ["0", "Paused"]], value: p.active ? "1" : "0" }] : [])];
  const body = (v, edit) => ({ ...v, interval_days: +v.interval_days, ...(edit ? { active: v.active === "1" } : {}) });
  const rm = (p, tag) => async () => { try { await api("DELETE", `/api/pm/plans/${p.id}/instruments/${encodeURIComponent(tag)}`); route(); } catch (x) { toast(x.message, true); } };
  el.append(h("div", { class: "bar" }, h("span", { class: "sp" }),
    isSup ? h("button", { class: "btn", onclick: () => dlg("Add PM plan", planFields(null), async v => { await api("POST", "/api/pm/plans", body(v)); toast("Plan added"); route(); }) }, "Add PM plan") : null),
    h("div", { class: "box" }, tbl([
      ["Plan", p => p.name], ["Job", p => p.job_title + " / " + p.work_needed], ["Every", p => p.interval_days + " d"],
      ["Next due", p => [p.next_due + " " + p.time_of_day, p.active && p.next_due <= soon ? [" ", h("span", { class: "badge on_hold" }, "Due soon")] : null].flat()],
      ["Status", p => p.active ? "Active" : "Paused"],
      ["Instruments", p => h("details", {}, h("summary", {}, p.instruments.length + " instruments"),
        h("div", { style: "display:flex;gap:.3rem;flex-wrap:wrap;max-width:420px;margin-top:.4rem" },
          p.instruments.map(t => isEng ? h("button", { class: "btn ghost sm", title: "Remove from plan", onclick: rm(p, t) }, t + " x") : h("span", { class: "badge" }, t))))],
      ["", p => h("div", { class: "acts-cell" },
        isEng ? h("button", { class: "btn ghost sm", onclick: () => dlg("Add instruments to " + p.name, [{ name: "tags", label: "Instrument tags (separated by commas or spaces)", type: "textarea", required: true }],
          async v => { await api("POST", `/api/pm/plans/${p.id}/instruments`, { tags: v.tags.split(/[\s,;]+/).filter(Boolean) }); toast("Instruments added"); route(); }) }, "Add instruments") : null,
        isSup ? h("button", { class: "btn ghost sm", onclick: () => dlg("Edit " + p.name, planFields(p), async v => { await api("PATCH", "/api/pm/plans/" + p.id, body(v, true)); toast("Saved"); route(); }) }, "Edit") : null,
        isSup && p.active ? h("button", { class: "btn sm", onclick: () => dlg("Issue work requests for " + p.name,
          [{ name: "leader_id", label: "Team leader", type: "select", options: leaders, blank: "Choose...", required: true }],
          async v => { const r = await api("POST", `/api/pm/plans/${p.id}/generate`, { leader_id: +v.leader_id });
            toast(`Issued ${r.created.length} work requests` + (r.skipped_need_density_leader.length ? `; ${r.skipped_need_density_leader.length} density meters skipped (need a density leader)` : "")); route(); }, "Issue") }, "Issue requests") : null)]],
      pl.plans, "No PM plans yet.")));
} });

/* ================= reports ================= */
const REP_TABS = [["overview", "Overview"], ["daily", "Daily report"], ["weekly", "Weekly report"], ["evaluation", "Evaluation"]];
registerPage("reports", { async render(el, p) {
  const tab = p.tab || "overview", body = h("div", {});
  el.append(h("div", { class: "bar" }, REP_TABS.map(([k, t]) => h("a", { class: "btn" + (k === tab ? "" : " ghost"), href: "#/reports?tab=" + k }, t))), body);
  await ({ overview: repOverview, daily: repDaily, weekly: repWeekly, evaluation: repEval }[tab] || repOverview)(body, p);
} });

async function repOverview(el) {
  const o = await api("GET", "/api/overview"), c = (n, t, href, cls) => h("a", { class: "stat " + (cls || ""), href }, h("b", {}, n), t);
  el.append(h("div", { class: "cards" },
    c(o.overdue, "Overdue", "#/requests?overdue=1", o.overdue ? "bad" : ""), c(o.open_emergency, "Open emergencies", "#/requests?priority=emergency", o.open_emergency ? "bad" : ""),
    c(o.low_stock, "Low stock items", "#/stock?low=1", o.low_stock ? "warn" : ""), c(o.purchase_pending, "Purchase requests pending", "#/purchases"),
    c(o.leave_to_decide, "Leave to decide", "#/leave"), c(o.on_leave_today, "On leave today", "#/followup"), c(o.pm_due_7_days, "PM due in 7 days", "#/pm")),
    h("div", { class: "box" }, h("h2", {}, "Work requests by status"), tbl([["Status", r => h("a", { href: "#/requests?status=" + r[0] }, badge(r[0]))], ["Count", r => r[1]]],
      Object.entries(o.requests_by_status), "No work requests yet.")));
}

function repDaily(el) {
  const d = h("input", { type: "date", value: ymd(new Date()) });
  el.append(h("div", { class: "box" }, h("h2", {}, "Daily work report (Excel)"), field("Date", d),
    h("p", {}, "Groups the day's requests by plant (CCP1, CCP2, COMPACTION) with assignment, assigned to, status and notes."),
    h("button", { class: "btn", onclick: () => { location.href = "/api/reports/daily?date=" + d.value; } }, "Download daily report")));
}

async function repWeekly(el, p) {
  const [c, gen] = await Promise.all([api("GET", "/api/weekly-report/candidates" + (p.week_start ? "?week_start=" + p.week_start : "")), api("GET", "/api/reports")]);
  const ws = c.week_start, wk = h("input", { type: "number", min: "1", value: Math.ceil(((new Date(ws) - new Date(ws.slice(0, 4) + "-01-01")) / 864e5 + 1) / 7), style: "width:6rem" });
  const boxes = c.requests.map(r => ({ r, c: h("input", { type: "checkbox", style: "width:auto", "aria-label": "Select " + r.code }) }));
  const all = h("input", { type: "checkbox", style: "width:auto", "aria-label": "Select all", onchange: () => boxes.forEach(b => { b.c.checked = all.checked; }) });
  const byId = Object.fromEntries(boxes.map(b => [b.r.id, b.c]));
  const make = async () => {
    const ids = boxes.filter(b => b.c.checked).map(b => b.r.id);
    if (!ids.length) return toast("Select at least one request", true);
    try { const r = await api("POST", "/api/weekly-report", { week_start: ws, request_ids: ids, week_no: +wk.value });
      toast("Created " + r.filename); location.href = `/api/reports/${r.id}/download`; } catch (x) { toast(x.message, true); }
  };
  const mv = n => "#/reports?tab=weekly&week_start=" + addDays(ws, n);
  el.append(h("div", { class: "bar" }, h("a", { class: "btn ghost", href: mv(-7) }, "Previous week"), h("b", {}, `Week of ${ws} (Sunday to Thursday)`),
    h("a", { class: "btn ghost", href: mv(7) }, "Next week"), h("span", { class: "sp" }), field("Week no.", wk), h("button", { class: "btn", onclick: make }, "Create weekly report")),
    h("div", { class: "box" }, h("h2", {}, "Choose the jobs to include"), c.requests.length ? h("table", {}, h("thead", {}, h("tr", {}, [h("th", {}, all),
      ...["Request", "Instrument", "Area", "Work needed", "Scheduled", "Status", "Photos"].map(t => h("th", {}, t))])),
      h("tbody", {}, c.requests.map(r => h("tr", {}, h("td", {}, byId[r.id]), h("td", {}, h("a", { href: "#/requests/" + r.id }, r.code)), h("td", {}, r.instrument_tag),
        h("td", {}, r.area || ""), h("td", {}, r.work_needed), h("td", {}, fmtDT(r.scheduled_at)), h("td", {}, badge(r.status)), h("td", {}, r.files)))))
      : h("p", { class: "empty" }, "No work requests for this week.")),
    h("div", { class: "box" }, h("h2", {}, "Reports already created"), tbl([["File", r => h("a", { href: `/api/reports/${r.id}/download` }, r.filename)],
      ["Week starting", r => r.period], ["Created", r => fmtDT(r.created_at)], ["By", r => r.by_name || ""]], gen.reports, "No weekly reports yet.")));
}

async function repEval(el, p) {
  const y = new Date().getFullYear(), from = h("input", { type: "date", value: p.from || y + "-01-01" }), to = h("input", { type: "date", value: p.to || y + "-12-31" });
  const d = await api("GET", `/api/evaluation?from=${from.value}&to=${to.value}`), W = d.weights;
  el.append(h("div", { class: "bar" }, field("From", from), field("To", to),
    h("button", { class: "btn", onclick: () => { location.hash = `#/reports?tab=evaluation&from=${from.value}&to=${to.value}`; } }, "Show")),
    h("div", { class: "box" }, h("h2", {}, "Technician evaluation"),
      h("p", {}, `Score out of 100: completed jobs ${W.work}, speed ${W.speed}, annual leave ${W.annual}, sick leave ${W.sick}. Speed compares each job time with the typical time for the same work needed.`),
      tbl([["#", e => e._i], ["Employee", e => e.name], ["Role", e => ROLE_LABEL[e.role]], ["Jobs done", e => e.jobs_completed],
        ["Annual days", e => num2(e.annual_days)], ["Sick days", e => num2(e.sick_days)], ["Work", e => e.components.work], ["Speed", e => e.components.speed],
        ["Annual", e => e.components.annual], ["Sick", e => e.components.sick], ["Score", e => h("b", {}, e.score)]],
        d.employees.map((e, i) => ({ ...e, _i: i + 1 })))));
}
