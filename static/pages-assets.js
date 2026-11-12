/* Part 2: instruments, control valves, spare parts. Shared helpers: modal, dlg, tbl. */
const STOCK_EDIT = ["engineer", "supervisor", "stock_keeper"];
const num2 = n => +(+n).toFixed(2);

function modal(title, content, wide) {
  const close = () => { o.remove(); document.removeEventListener("keydown", esc); };
  const esc = e => { if (e.key === "Escape") close(); };
  const o = h("div", { class: "overlay", onmousedown: e => { if (e.target === o) close(); } },
    h("div", { class: "dlg" + (wide ? " wide" : ""), role: "dialog", "aria-label": title }, h("h2", {}, title), content));
  document.addEventListener("keydown", esc);
  document.body.append(o);
  return { close };
}

/* fields: {name,label,type(text|number|date|time|textarea|select),options,value,required,blank,addNew(value)->Promise} */
function dlg(title, fields, onOk, okText = "Save") {
  const msg = h("p", { class: "err", role: "alert" }), ins = {};
  const rows = fields.map(f => {
    const id = "f_" + f.name;
    let el, extra = null;
    if (f.type === "select") {
      const opts = (f.options || []).map(o => Array.isArray(o) ? o : [o, o]);
      const blank = f.blank || (f.addNew && f.value == null ? "Choose..." : null);
      el = h("select", { id }, blank ? h("option", { value: "" }, blank) : null, opts.map(([v, t]) => h("option", { value: v }, t)));
      if (f.value != null) el.value = f.value;
      if (f.addNew) {
        el.append(h("option", { value: "__new__" }, "+ Add new..."));
        let prev = el.value;
        el.addEventListener("change", async () => {
          if (el.value !== "__new__") { prev = el.value; return; }
          const v = (prompt("New value") || "").trim();
          if (!v) { el.value = prev; return; }
          try { await f.addNew(v); el.insertBefore(h("option", { value: v }, v), el.querySelector('option[value="__new__"]')); el.value = prev = v; }
          catch (x) { toast(x.message, true); el.value = prev; }
        });
      }
    } else if (f.type === "textarea") el = h("textarea", { id, rows: 3 }, f.value || "");
    else {
      el = h("input", { id, type: f.type || "text", value: f.value ?? "" });
      if (f.type === "number") { el.step = "any"; el.min = "0"; }
      if (f.list) { el.setAttribute("list", id + "_l"); extra = h("datalist", { id: id + "_l" }, f.list.map(v => h("option", { value: v }))); }
    }
    if (f.required) el.required = true;
    ins[f.name] = el;
    return [h("label", { for: id }, f.label), el, extra];
  });
  let m;
  const form = h("form", { onsubmit: async e => {
    e.preventDefault(); msg.textContent = "";
    const v = Object.fromEntries(Object.entries(ins).map(([k, el]) => [k, el.value]));
    try { await onOk(v); m.close(); } catch (x) { msg.textContent = x.message; }
  } }, rows.flat(), msg, h("div", { class: "acts" },
    h("button", { type: "button", class: "btn ghost", onclick: () => m.close() }, "Cancel"), h("button", { class: "btn" }, okText)));
  m = modal(title, form);
  form.querySelector("input,select,textarea")?.focus();
}

const tbl = (cols, rows, empty = "Nothing to show.") => rows.length
  ? h("table", {}, h("thead", {}, h("tr", {}, cols.map(c => h("th", {}, c[0])))),
      h("tbody", {}, rows.map(r => { const tr = h("tr", { class: r._cls || "" }, cols.map(c => h("td", {}, c[1](r)))); return tr; })))
  : h("p", { class: "empty" }, empty);
const addOpt = cat => v => api("POST", "/api/options/" + cat, { value: v });
const field = (lbl, ctrl) => h("div", {}, h("label", {}, lbl), ctrl);
const debounce = (fn, ms = 250) => { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; };

/* ================= instruments ================= */
registerPage("instruments", { async render(el, p, rest) {
  return rest[0] ? instDetail(el, decodeURIComponent(rest[0])) : instList(el, p);
} });

async function instList(el, p) {
  const [areas, types] = await Promise.all([api("GET", "/api/options/area"), api("GET", "/api/options/instrument_type")]);
  const q = h("input", { class: "grow", placeholder: "Search tag or description", value: p.q || "" });
  const sa = h("select", {}, h("option", { value: "" }, "All areas"), areas.options.map(a => h("option", {}, a)));
  const st = h("select", {}, h("option", { value: "" }, "All types"), types.options.map(a => h("option", {}, a)));
  const box = h("div", { class: "box" });
  async function load() {
    const qs = new URLSearchParams();
    [["q", q], ["area", sa], ["type", st]].forEach(([k, c]) => c.value && qs.set(k, c.value));
    const r = (await api("GET", "/api/instruments?" + qs)).instruments;
    box.replaceChildren(h("h2", {}, r.length + " instruments"), tbl([
      ["Tag", i => h("a", { href: "#/instruments/" + encodeURIComponent(i.tag) }, i.tag)],
      ["Type", i => i.type], ["Area", i => i.area], ["Description", i => i.description || ""]], r));
  }
  const go = debounce(() => load().catch(x => toast(x.message, true)));
  [q, sa, st].forEach(c => c.addEventListener("input", go));
  el.append(h("div", { class: "bar" }, q, sa, st, h("span", { class: "sp" }),
    can(ENG) ? h("button", { class: "btn", onclick: () => dlg("Add instrument", [
      { name: "tag", label: "Tag (density meters: DNT-1234)", required: true },
      { name: "type", label: "Type", type: "select", options: types.options, addNew: addOpt("instrument_type"), required: true },
      { name: "area", label: "Area", type: "select", options: areas.options, required: true },
      { name: "description", label: "Description" }],
      async v => { await api("POST", "/api/instruments", v); toast("Instrument added"); load(); }) }, "Add instrument") : null), box);
  await load();
}

async function instDetail(el, tag) {
  const [{ instrument: i }, areas, types, users] = await Promise.all([api("GET", "/api/instruments/" + encodeURIComponent(tag)),
    api("GET", "/api/options/area"), api("GET", "/api/options/instrument_type"), api("GET", "/api/users")]);
  const hist = h("div", { class: "box" });
  const code = h("input", { placeholder: "Request code" }), d1 = h("input", { type: "date", title: "From" }), d2 = h("input", { type: "date", title: "To" });
  const us = users.users.filter(u => u.active);
  const ld = h("select", {}, h("option", { value: "" }, "Any leader"), us.filter(u => u.is_leader).map(u => h("option", { value: u.id }, u.name)));
  const tc = h("select", {}, h("option", { value: "" }, "Any technician"), us.filter(u => ["technician", "assistant"].includes(u.role)).map(u => h("option", { value: u.id }, u.name)));
  async function load() {
    const qs = new URLSearchParams();
    [["code", code], ["from", d1], ["to", d2], ["leader_id", ld], ["technician_id", tc]].forEach(([k, c]) => c.value && qs.set(k, c.value));
    const r = (await api("GET", `/api/instruments/${encodeURIComponent(tag)}/history?` + qs)).history;
    hist.replaceChildren(h("h2", {}, "Work request history"), h("div", { class: "bar" }, code, d1, d2, ld, tc),
      tbl([["Request", r => h("a", { href: "#/requests/" + r.id }, r.code)], ["Job", r => r.job_title], ["Work needed", r => r.work_needed],
        ["Scheduled", r => fmtDT(r.scheduled_at)], ["Status", r => badge(r.status)], ["Leader", r => r.leader_name], ["Crew", r => r.crew || ""]],
        r, "No work requests for this instrument."));
    [code, d1, d2, ld, tc].forEach(c => { c.oninput = go; });
  }
  const go = debounce(() => load().catch(x => toast(x.message, true)));
  el.append(h("a", { class: "back", href: "#/instruments" }, "Back to instruments"),
    h("div", { class: "box" }, h("h2", {}, i.tag), h("dl", { class: "kv" },
      h("dt", {}, "Type"), h("dd", {}, i.type), h("dt", {}, "Area"), h("dd", {}, i.area),
      h("dt", {}, "Description"), h("dd", {}, i.description || "-"),
      h("dt", {}, "Control valve"), h("dd", {}, i.valve ? h("a", { href: "#/valves/" + encodeURIComponent(i.valve.serial) }, i.valve.serial) : "-")),
      can(ENG) ? h("button", { class: "btn ghost", onclick: () => dlg("Edit " + i.tag, [
        { name: "type", label: "Type", type: "select", options: types.options, addNew: addOpt("instrument_type"), value: i.type },
        { name: "area", label: "Area", type: "select", options: areas.options, value: i.area },
        { name: "description", label: "Description", value: i.description }],
        async v => { await api("PATCH", "/api/instruments/" + encodeURIComponent(i.tag), v); toast("Saved"); route(); }) }, "Edit") : null),
    hist);
  await load();
}

/* ================= control valves ================= */
const VSTATUS = { in_service: "In service", workshop: "In workshop", spare: "Spare", scrapped: "Scrapped" };
const vbadge = s => h("span", { class: "badge " + (s === "scrapped" ? "cancelled" : s === "in_service" ? "assigned" : s === "workshop" ? "on_hold" : "") }, VSTATUS[s] || s);

registerPage("valves", { async render(el, p, rest) {
  return rest[0] ? valveDetail(el, decodeURIComponent(rest[0])) : valveList(el);
} });

async function valveList(el) {
  const q = h("input", { class: "grow", placeholder: "Search serial or instrument tag" });
  const st = h("select", {}, h("option", { value: "" }, "All statuses"), Object.entries(VSTATUS).map(([k, v]) => h("option", { value: k }, v)));
  const box = h("div", { class: "box" });
  async function load() {
    const qs = new URLSearchParams();
    if (q.value) qs.set("q", q.value); if (st.value) qs.set("status", st.value);
    const r = (await api("GET", "/api/valves?" + qs)).valves;
    box.replaceChildren(h("h2", {}, r.length + " valves"), tbl([
      ["Serial", v => h("a", { href: "#/valves/" + encodeURIComponent(v.serial) }, v.serial)], ["Status", v => vbadge(v.status)],
      ["Installed on", v => v.instrument_tag || "-"], ["Manufacturer", v => v.manufacturer || ""],
      ["Model", v => v.model || ""], ["Size", v => v.size || ""]], r));
  }
  const go = debounce(() => load().catch(x => toast(x.message, true)));
  [q, st].forEach(c => c.addEventListener("input", go));
  el.append(h("div", { class: "bar" }, q, st, h("span", { class: "sp" }),
    can(ENG) ? h("button", { class: "btn", onclick: () => dlg("Register control valve", [
      { name: "serial", label: "Serial number", required: true },
      { name: "manufacturer", label: "Manufacturer" }, { name: "model", label: "Model" }, { name: "size", label: "Size" },
      { name: "instrument_tag", label: "Installed on instrument tag (leave empty if spare)" },
      { name: "note", label: "Note" }],
      async v => { await api("POST", "/api/valves", v); toast("Valve registered"); load(); }) }, "Register valve") : null), box);
  await load();
}

async function valveDetail(el, serial) {
  const v = (await api("GET", "/api/valves/" + encodeURIComponent(serial))).valve;
  const ev = (event, text, withTag) => h("button", { class: "btn ghost sm", onclick: () => dlg(text + " " + v.serial,
    [withTag ? { name: "instrument_tag", label: "Instrument tag", required: true } : null,
     { name: "note", label: "Note", type: "textarea" }].filter(Boolean),
    async f => { await api("POST", `/api/valves/${encodeURIComponent(v.serial)}/events`, { event, ...f }); toast("Saved"); route(); }, text) }, text);
  const acts = v.status === "scrapped" ? [] : [
    v.status !== "in_service" ? ev("installed", "Install", true) : null,
    v.status === "in_service" ? ev("removed", "Remove") : null,
    v.status === "workshop" ? ev("repaired", "Mark repaired") : null,
    ev("calibrated", "Log calibration"), ev("tested", "Log test"), ev("note", "Add note"), ev("scrapped", "Scrap")];
  el.append(h("a", { class: "back", href: "#/valves" }, "Back to valves"),
    h("div", { class: "box" }, h("h2", {}, v.serial), h("dl", { class: "kv" },
      h("dt", {}, "Status"), h("dd", {}, vbadge(v.status)),
      h("dt", {}, "Installed on"), h("dd", {}, v.instrument_tag ? h("a", { href: "#/instruments/" + encodeURIComponent(v.instrument_tag) }, v.instrument_tag) : "-"),
      h("dt", {}, "Manufacturer"), h("dd", {}, v.manufacturer || "-"), h("dt", {}, "Model"), h("dd", {}, v.model || "-"),
      h("dt", {}, "Size"), h("dd", {}, v.size || "-")),
      can([...ENG, "technician"]) ? h("div", { class: "acts-cell" }, acts) : null),
    h("div", { class: "box" }, h("h2", {}, "Life cycle"), tbl([["When", e => fmtDT(e.created_at)], ["Event", e => label(e.event)],
      ["Instrument", e => e.instrument_tag || ""], ["Note", e => e.note || ""], ["By", e => e.by_name || ""]], v.events)));
}

/* ================= spare parts ================= */
registerPage("stock", { async render(el, p) {
  const isKeeper = App.user.role === "stock_keeper" || App.user.is_admin;
  const units = (await api("GET", "/api/options/unit")).options;
  const low = h("input", { type: "checkbox", id: "low", style: "width:auto" }); low.checked = p.low === "1";
  const q = h("input", { class: "grow", placeholder: "Search part name or number" });
  const box = h("div", { class: "box" }), resBox = h("div", { class: "box" });
  const after = () => load().catch(x => toast(x.message, true));
  const qtyDlg = (title, it, path, extra = []) => dlg(title + ": " + it.name, [{ name: "qty", label: "Quantity (" + it.unit + ")", type: "number", required: true }, ...extra],
    async v => { await api("POST", `/api/stock/${it.id}/${path}`, { ...v, qty: +v.qty }); toast("Saved"); after(); });
  const refNote = [{ name: "ref", label: "Reference" }, { name: "note", label: "Note" }];
  const itemForm = (title, it) => dlg(title, [
    { name: "part_no", label: "Part number", value: it?.part_no }, { name: "name", label: "Name", value: it?.name, required: true },
    { name: "unit", label: "Unit", type: "select", options: units, value: it?.unit },
    ...(it ? [] : [{ name: "qty_on_hand", label: "Opening quantity", type: "number", value: 0 }]),
    { name: "min_qty", label: "Minimum quantity", type: "number", value: it ? it.min_qty : 0 }],
    async v => { it ? await api("PATCH", "/api/stock/" + it.id, v) : await api("POST", "/api/stock", v); toast("Saved"); after(); });
  async function moves(it) {
    const m = (await api("GET", `/api/stock/${it.id}/moves`)).moves;
    modal("Movements: " + it.name, tbl([["When", x => fmtDT(x.created_at)], ["Kind", x => label(x.kind)], ["Qty", x => num2(x.qty)],
      ["Reference", x => x.ref || ""], ["Note", x => x.note || ""], ["By", x => x.by_name || ""]], m), true);
  }
  async function load() {
    const [s, r] = await Promise.all([api("GET", "/api/stock" + (low.checked ? "?low=1" : "")), api("GET", "/api/reservations")]);
    const items = s.items.filter(i => !q.value || (i.name + " " + (i.part_no || "")).toLowerCase().includes(q.value.toLowerCase()));
    items.forEach(i => { i._cls = i.low ? "low" : ""; });
    box.replaceChildren(h("h2", {}, items.length + " items"), tbl([
      ["Part", i => i.name + (i.part_no ? " (" + i.part_no + ")" : "")], ["Unit", i => i.unit], ["On hand", i => num2(i.qty_on_hand)],
      ["Reserved", i => num2(i.reserved)], ["Available", i => h("b", {}, num2(i.available))], ["Minimum", i => num2(i.min_qty)],
      ["", i => i.low ? h("span", { class: "badge on_hold" }, "Low") : ""],
      ["", i => h("div", { class: "acts-cell" },
        h("button", { class: "btn ghost sm", onclick: () => moves(i) }, "History"),
        h("button", { class: "btn ghost sm", onclick: () => qtyDlg("Reserve", i, "reserve", [{ name: "ref", label: "Work request code or reference" }]) }, "Reserve"),
        isKeeper ? h("button", { class: "btn ghost sm", onclick: () => qtyDlg("Receive", i, "receive", refNote) }, "Receive") : null,
        isKeeper ? h("button", { class: "btn ghost sm", onclick: () => qtyDlg("Issue", i, "issue", refNote) }, "Issue") : null,
        can(STOCK_EDIT) ? h("button", { class: "btn ghost sm", onclick: () => itemForm("Edit part", i) }, "Edit") : null)]], items));
    const mine = x => isKeeper || x.requested_by === App.user.id;
    resBox.replaceChildren(h("h2", {}, "Active reservations"), tbl([["Part", x => x.item_name], ["Qty", x => num2(x.qty)], ["Reference", x => x.ref || ""],
      ["Requested by", x => x.by_name || ""], ["Date", x => fmtDT(x.created_at)],
      ["", x => h("div", { class: "acts-cell" },
        isKeeper ? h("button", { class: "btn sm", onclick: async () => { try { await api("POST", `/api/stock/${x.item_id}/issue`, { reservation_id: x.id }); toast("Issued"); after(); } catch (e) { toast(e.message, true); } } }, "Issue") : null,
        mine(x) ? h("button", { class: "btn ghost sm", onclick: async () => { try { await api("POST", `/api/reservations/${x.id}/release`); toast("Released"); after(); } catch (e) { toast(e.message, true); } } }, "Release") : null)]],
      r.reservations, "No active reservations."));
  }
  const go = debounce(after);
  q.addEventListener("input", go); low.addEventListener("change", after);
  el.append(h("div", { class: "bar" }, q, h("label", { for: "low", style: "margin:0;font-weight:400" }, low, " Low stock only"), h("span", { class: "sp" }),
    can(STOCK_EDIT) ? h("button", { class: "btn", onclick: () => itemForm("Add part", null) }, "Add part") : null), box, resBox);
  await load();
} });
