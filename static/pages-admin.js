/* Part 6: purchase requests and admin (users, drop-down lists). */
const YESNO = [["0", "No"], ["1", "Yes"]];

/* ================= purchase requests ================= */
registerPage("purchases", { async render(el) {
  const [stock, us] = await Promise.all([api("GET", "/api/stock"), api("GET", "/api/users")]);
  const u = App.user, keeper = can(["stock_keeper"]);
  const leaders = us.users.filter(x => x.is_leader && x.active).map(x => [x.id, x.name]);
  const st = h("select", {}, h("option", { value: "" }, "All statuses"), ["pending", "approved", "rejected", "received"].map(s => h("option", { value: s }, label(s))));
  const mine = h("input", { type: "checkbox", id: "mine", style: "width:auto" });
  const box = h("div", { class: "box" });
  async function load() {
    const qs = new URLSearchParams();
    if (st.value) qs.set("status", st.value); if (mine.checked) qs.set("mine", "1");
    const rows = (await api("GET", "/api/purchase-requests?" + qs)).requests;
    const call = (path, body, msg) => async () => { try { await api("POST", `/api/purchase-requests/${path}`, body); toast(msg); load(); } catch (x) { toast(x.message, true); } };
    box.replaceChildren(h("h2", {}, rows.length + " purchase requests"), tbl([
      ["#", r => r.id], ["Part", r => r.item_name], ["Quantity", r => num2(r.qty)], ["Team leader", r => r.leader_name], ["Note", r => r.note || ""],
      ["Status", r => badge(r.status)], ["Date", r => fmtDT(r.created_at)],
      ["", r => h("div", { class: "acts-cell" },
        r.status === "pending" && (u.is_admin || u.id === r.leader_id) ? [h("button", { class: "btn sm", onclick: call(`${r.id}/decide`, { approve: true }, "Approved") }, "Approve"),
          h("button", { class: "btn ghost sm", onclick: call(`${r.id}/decide`, { approve: false }, "Rejected") }, "Reject")] : null,
        r.status === "approved" && keeper ? h("button", { class: "btn sm", onclick: call(`${r.id}/receive`, {}, "Received into stock") }, "Mark received") : null)]], rows, "No purchase requests."));
  }
  const go = () => load().catch(x => toast(x.message, true));
  st.addEventListener("input", go); mine.addEventListener("change", go);
  el.append(h("div", { class: "bar" }, st, u.is_leader ? h("label", { for: "mine", style: "margin:0;font-weight:400" }, mine, " Waiting for me") : null, h("span", { class: "sp" }),
    can(["stock_keeper", "engineer", "supervisor"]) ? h("button", { class: "btn", onclick: () => dlg("New purchase request", [
      { name: "item_id", label: "Part", type: "select", options: stock.items.map(i => [i.id, `${i.name} (${num2(i.available)} ${i.unit} available, min ${num2(i.min_qty)})`]), blank: "Choose...", required: true },
      { name: "qty", label: "Quantity to buy", type: "number", required: true },
      { name: "leader_id", label: "Team leader to approve", type: "select", options: leaders, blank: "Choose...", required: true },
      { name: "note", label: "Note", type: "textarea" }],
      async v => { await api("POST", "/api/purchase-requests", { item_id: +v.item_id, qty: +v.qty, leader_id: +v.leader_id, note: v.note }); toast("Request sent"); load(); }, "Send request") }, "New request") : null), box);
  await load();
} });

/* ================= admin: users and lists ================= */
registerPage("admin", { async render(el, p) {
  const tab = p.tab || "users", body = h("div", {});
  el.append(h("div", { class: "bar" }, [["users", "Users"], ["lists", "Drop-down lists"]].map(([k, t]) =>
    h("a", { class: "btn" + (k === tab ? "" : " ghost"), href: "#/admin?tab=" + k }, t))), body);
  await (tab === "lists" ? adminLists : adminUsers)(body);
} });

async function adminUsers(el) {
  const [us, sg] = await Promise.all([api("GET", "/api/users"), api("GET", "/api/options/shift_group")]);
  const roles = Object.entries(ROLE_LABEL), q = h("input", { class: "grow", placeholder: "Search by name or username" });
  const box = h("div", { class: "box" });
  const flags = (v, edit) => ({ ...v, is_admin: v.is_admin === "1", is_leader: v.is_leader === "1", is_density: v.is_density === "1", ...(edit ? { active: v.active === "1" } : {}) });
  const fields = x => [
    { name: "name", label: "Full name", value: x?.name, required: true },
    ...(x ? [] : [{ name: "username", label: "Username (empty = made from the name)" }]),
    { name: "role", label: "Role", type: "select", options: roles, value: x?.role, blank: x ? null : "Choose...", required: true },
    { name: "shift_group", label: "Shift (shift technicians only)", type: "select", options: sg.options, blank: "None", value: x?.shift_group || "" },
    { name: "is_leader", label: "Team leader", type: "select", options: YESNO, value: x ? String(x.is_leader) : "0" },
    { name: "is_density", label: "Density staff", type: "select", options: YESNO, value: x ? String(x.is_density) : "0" },
    { name: "is_admin", label: "Admin", type: "select", options: YESNO, value: x ? String(x.is_admin) : "0" },
    ...(x ? [{ name: "active", label: "Account", type: "select", options: [["1", "Active"], ["0", "Disabled"]], value: String(x.active) }] : [])];
  function draw() {
    const t = q.value.toLowerCase(), rows = us.users.filter(x => !t || (x.name + " " + x.username).toLowerCase().includes(t));
    box.replaceChildren(h("h2", {}, rows.length + " users"), tbl([
      ["Name", x => x.name], ["Username", x => x.username], ["Role", x => ROLE_LABEL[x.role]], ["Shift", x => x.shift_group || ""],
      ["Leader", x => x.is_leader ? "Yes" : ""], ["Density", x => x.is_density ? "Yes" : ""], ["Admin", x => x.is_admin ? "Yes" : ""],
      ["Account", x => x.active ? "Active" : badge("cancelled")],
      ["", x => h("div", { class: "acts-cell" },
        h("button", { class: "btn ghost sm", onclick: () => dlg("Edit " + x.name, fields(x), async v => {
          const b = flags(v, true); b.shift_group = v.shift_group || null; await api("PATCH", "/api/users/" + x.id, b); toast("Saved"); route(); }) }, "Edit"),
        h("button", { class: "btn ghost sm", onclick: async () => {
          if (!confirm("Reset the password of " + x.name + " to the default?")) return;
          try { const r = await api("POST", `/api/users/${x.id}/reset-password`); toast("Password reset to " + r.default_password); } catch (e) { toast(e.message, true); } } }, "Reset password"))]], rows));
  }
  q.addEventListener("input", draw);
  el.append(h("div", { class: "bar" }, q, h("span", { class: "sp" }),
    h("button", { class: "btn", onclick: () => dlg("Add user", fields(null), async v => {
      const b = flags(v); if (!v.username) delete b.username; if (!v.shift_group) delete b.shift_group;
      const r = await api("POST", "/api/users", b); toast("User added. Default password: " + r.default_password); route(); }, "Add user") }, "Add user")), box);
  draw();
}

async function adminLists(el) {
  const cats = [["job_title", "Job titles"], ["work_needed", "Work needed"], ["instrument_type", "Instrument types"], ["area", "Areas"], ["unit", "Stock units"]];
  const data = await Promise.all(cats.map(([c]) => api("GET", "/api/options/" + c)));
  el.append(...cats.map(([c, t], i) => h("div", { class: "box" }, h("h2", {}, t),
    data[i].options.length ? h("div", { style: "display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.8rem" }, data[i].options.map(v => h("span", { class: "badge" }, v))) : h("p", { class: "empty" }, "Empty."),
    h("button", { class: "btn ghost sm", onclick: () => dlg("Add to " + t, [{ name: "value", label: "New value", required: true }],
      async v => { await api("POST", "/api/options/" + c, { value: v.value }); toast("Added"); route(); }, "Add") }, "Add value"))));
}
