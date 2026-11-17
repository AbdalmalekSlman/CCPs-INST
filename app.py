"""CMMS backend.
Run:  pip install -r requirements.txt
      SECRET_KEY=... python app.py     (listens on 127.0.0.1:$PORT, default 8100; put nginx in front)
"""
import os, secrets, sys, sqlite3, time
from functools import wraps
from flask import Flask, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cmms.db")
DEFAULT_PASSWORD = "changeme123"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or sys.exit("SECRET_KEY environment variable is not set")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)  # "keep me logged in"
SHORT_SESSION = 60 * 60 * 12   # normal login lasts 12 h

# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  is_leader INTEGER NOT NULL DEFAULT 0,
  is_density INTEGER NOT NULL DEFAULT 0,
  shift_group TEXT,
  must_change INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS options(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  value TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 100,
  UNIQUE(category, value)
);
CREATE TABLE IF NOT EXISTS instruments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  area TEXT NOT NULL,
  description TEXT,
  is_density INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS valves(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  serial TEXT NOT NULL UNIQUE,
  instrument_tag TEXT,
  manufacturer TEXT, model TEXT, size TEXT,
  status TEXT NOT NULL DEFAULT 'spare',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS valve_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  valve_id INTEGER NOT NULL REFERENCES valves(id),
  event TEXT NOT NULL,
  instrument_tag TEXT,
  note TEXT,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS stock_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  part_no TEXT, name TEXT NOT NULL, unit TEXT NOT NULL,
  qty_on_hand REAL NOT NULL DEFAULT 0,
  min_qty REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS stock_moves(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES stock_items(id),
  kind TEXT NOT NULL, qty REAL NOT NULL, ref TEXT, note TEXT,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES stock_items(id),
  qty REAL NOT NULL, ref TEXT,
  requested_by INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS purchase_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES stock_items(id),
  qty REAL NOT NULL, note TEXT,
  leader_id INTEGER NOT NULL REFERENCES users(id),
  requested_by INTEGER REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS work_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'normal',
  instrument_tag TEXT NOT NULL REFERENCES instruments(tag),
  job_title TEXT NOT NULL, work_needed TEXT NOT NULL, details TEXT,
  scheduled_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'issued',
  leader_id INTEGER NOT NULL REFERENCES users(id),
  created_by INTEGER NOT NULL REFERENCES users(id),
  overdue_notified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS wr_crew(
  wr_id INTEGER NOT NULL REFERENCES work_requests(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  crew_role TEXT NOT NULL,
  PRIMARY KEY(wr_id, user_id)
);
CREATE TABLE IF NOT EXISTS wr_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wr_id INTEGER NOT NULL REFERENCES work_requests(id),
  event TEXT NOT NULL, note TEXT,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS wr_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wr_id INTEGER NOT NULL REFERENCES work_requests(id),
  text TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS wr_files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wr_id INTEGER NOT NULL REFERENCES work_requests(id),
  filename TEXT NOT NULL, stored TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  message TEXT NOT NULL,
  wr_id INTEGER,
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS leave_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT NOT NULL,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  start_time TEXT, end_time TEXT,
  days REAL NOT NULL DEFAULT 0, hours REAL NOT NULL DEFAULT 0,
  reason TEXT,
  replacement_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL,
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT, decision_note TEXT,
  report_name TEXT, report_stored TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS shift_schedule(
  day TEXT NOT NULL,
  shift_group TEXT NOT NULL,
  code TEXT NOT NULL,
  PRIMARY KEY(day, shift_group)
);
CREATE TABLE IF NOT EXISTS pm_plans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  job_title TEXT NOT NULL, work_needed TEXT NOT NULL,
  interval_days INTEGER NOT NULL,
  next_due TEXT NOT NULL,
  time_of_day TEXT NOT NULL DEFAULT '07:00',
  active INTEGER NOT NULL DEFAULT 1,
  last_generated TEXT
);
CREATE TABLE IF NOT EXISTS pm_instruments(
  plan_id INTEGER NOT NULL REFERENCES pm_plans(id),
  instrument_tag TEXT NOT NULL REFERENCES instruments(tag),
  PRIMARY KEY(plan_id, instrument_tag)
);
CREATE TABLE IF NOT EXISTS generated_reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, period TEXT NOT NULL,
  filename TEXT NOT NULL, stored TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

ROLES = ["superintendent", "engineer", "supervisor", "technician",
         "assistant", "stock_keeper"]
SHIFT_GROUPS = ["A", "B", "C", "D"]

# who may add options per category (admin can always)
OPTION_ADD_ROLES = {
    "job_title": ["superintendent", "engineer", "supervisor"],
    "work_needed": ["superintendent", "engineer", "supervisor"],
    "instrument_type": ["superintendent", "engineer", "supervisor"],
    "area": [], "role": [],
}
# technicians on shift can also issue requests -> allowed in init for job_title/work_needed
SHIFT_CAN_ADD = {"job_title", "work_needed"}

SEED_OPTIONS = {
    "role": ROLES,
    "area": ["CCP1", "CCP2", "COMPACTION"],
    "shift_group": SHIFT_GROUPS,
    "job_title": [], "work_needed": [], "instrument_type": [],
    "unit": ["pcs", "m", "kg", "l", "set"],
}

# name, role, admin, leader, density, shift_group
SEED_USERS = [
    ("Raed Khamis", "superintendent", 0, 0, 0, None),
    ("Wael al-Khlefat", "engineer", 0, 1, 1, None),
    ("Hamza Al-Othman", "engineer", 0, 1, 0, None),
    ("Abdalmalek Salman", "engineer", 1, 1, 0, None),
    ("Tawfeeq Al-Jarrah", "supervisor", 0, 1, 0, None),
    ("Shade Al-Adayyliah", "technician", 0, 0, 0, None),
    ("Ahmad Menzel", "technician", 0, 0, 1, None),
    ("Hashem Al-Khlefat", "technician", 0, 0, 1, None),
    ("Bahaa Al-Mahafzah", "technician", 0, 0, 0, None),
    ("Mahmoud Al-Hmedi", "stock_keeper", 0, 0, 0, None),
    ("Thakre Al-Shamaseen", "technician", 0, 0, 0, "A"),
    ("Ali Abdollah", "technician", 0, 0, 0, "B"),
    ("Hamza Al-Isuoss", "technician", 0, 0, 0, "C"),
    ("Mohammed Al-Qatawneh", "technician", 0, 0, 0, "D"),
    ("Ahmad Al-Shwareeh", "assistant", 0, 0, 0, None),
    ("Mohammed Al-Shuar", "assistant", 0, 0, 0, None),
    ("Mohammed Al-Kurdi", "assistant", 0, 0, 0, None),
    ("Abdelrahman Azozz", "assistant", 0, 0, 0, None),
    ("Mohammed Shareef", "assistant", 0, 0, 0, None),
]

def make_username(name, con):
    base = ".".join(name.lower().replace("-", "").split())
    u, i = base, 2
    while con.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
        u, i = f"{base}{i}", i + 1
    return u

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    for cat, vals in SEED_OPTIONS.items():
        for i, v in enumerate(vals):
            con.execute("INSERT OR IGNORE INTO options(category,value,sort) VALUES(?,?,?)",
                        (cat, v, i))
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pw = generate_password_hash(DEFAULT_PASSWORD)
        for n, r, a, l, d, s in SEED_USERS:
            con.execute("""INSERT INTO users(name,username,password_hash,role,is_admin,
                           is_leader,is_density,shift_group) VALUES(?,?,?,?,?,?,?,?)""",
                        (n, make_username(n, con), pw, r, a, l, d, s))
    con.commit()
    con.close()

# ---------- auth helpers ----------
def public_user(r):
    d = dict(r)
    d.pop("password_hash", None)
    return d

def current_user():
    uid = session.get("uid")
    if not uid or session.get("exp", float("inf")) < time.time():
        return None
    r = db().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    return r

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u:
            return jsonify(error="login required"), 401
        g.user = u
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a, **k):
        if not g.user["is_admin"]:
            return jsonify(error="admin only"), 403
        return f(*a, **k)
    return w

def err(msg, code=400):
    return jsonify(error=msg), code

# ---------- auth routes ----------
@app.post("/api/login")
def login():
    j = request.get_json(silent=True) or {}
    r = db().execute("SELECT * FROM users WHERE username=? AND active=1",
                     ((j.get("username") or "").strip().lower(),)).fetchone()
    if not r or not check_password_hash(r["password_hash"], j.get("password") or ""):
        return err("wrong username or password", 401)
    session.clear()
    session.permanent = True
    session["uid"] = r["id"]
    if not j.get("remember"):
        session["exp"] = time.time() + SHORT_SESSION
    return jsonify(user=public_user(r))

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
@login_required
def me():
    return jsonify(user=public_user(g.user))

@app.post("/api/change-password")
@login_required
def change_password():
    j = request.get_json(silent=True) or {}
    if not check_password_hash(g.user["password_hash"], j.get("old_password") or ""):
        return err("old password is wrong", 403)
    new = j.get("new_password") or ""
    if len(new) < 8:
        return err("new password must be at least 8 characters")
    db().execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                 (generate_password_hash(new), g.user["id"]))
    db().commit()
    return jsonify(ok=True)

# ---------- users ----------
def valid_role_fields(j, partial=False):
    if "role" in j and j["role"] not in ROLES:
        return "invalid role"
    if j.get("shift_group") not in (None, "") + tuple(SHIFT_GROUPS):
        return "invalid shift group"
    if not partial and not (j.get("name") or "").strip():
        return "name is required"
    return None

@app.get("/api/users")
@login_required
def list_users():
    rows = db().execute("SELECT * FROM users ORDER BY name").fetchall()
    return jsonify(users=[public_user(r) for r in rows])

@app.post("/api/users")
@admin_required
def add_user():
    j = request.get_json(silent=True) or {}
    if "role" not in j:
        return err("role is required")
    m = valid_role_fields(j)
    if m:
        return err(m)
    con = db()
    username = (j.get("username") or "").strip().lower() or make_username(j["name"], con)
    if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return err("username already exists", 409)
    cur = con.execute("""INSERT INTO users(name,username,password_hash,role,is_admin,
        is_leader,is_density,shift_group) VALUES(?,?,?,?,?,?,?,?)""",
        (j["name"].strip(), username, generate_password_hash(DEFAULT_PASSWORD), j["role"],
         int(bool(j.get("is_admin"))), int(bool(j.get("is_leader"))),
         int(bool(j.get("is_density"))), j.get("shift_group") or None))
    con.commit()
    r = con.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(user=public_user(r), default_password=DEFAULT_PASSWORD), 201

@app.patch("/api/users/<int:uid>")
@admin_required
def edit_user(uid):
    j = request.get_json(silent=True) or {}
    m = valid_role_fields(j, partial=True)
    if m:
        return err(m)
    allowed = ["name", "role", "is_admin", "is_leader", "is_density", "shift_group", "active"]
    sets = {k: j[k] for k in allowed if k in j}
    if not sets:
        return err("nothing to update")
    if uid == g.user["id"] and (sets.get("is_admin") == 0 or sets.get("active") == 0):
        return err("you cannot remove your own admin access or deactivate yourself")
    for k in ("is_admin", "is_leader", "is_density", "active"):
        if k in sets:
            sets[k] = int(bool(sets[k]))
    if "shift_group" in sets:
        sets["shift_group"] = sets["shift_group"] or None
    con = db()
    con.execute(f"UPDATE users SET {','.join(k + '=?' for k in sets)} WHERE id=?",
                (*sets.values(), uid))
    con.commit()
    r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(user=public_user(r)) if r else err("not found", 404)

@app.post("/api/users/<int:uid>/reset-password")
@admin_required
def reset_password(uid):
    con = db()
    cur = con.execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?",
                      (generate_password_hash(DEFAULT_PASSWORD), uid))
    con.commit()
    return jsonify(default_password=DEFAULT_PASSWORD) if cur.rowcount else err("not found", 404)

# ---------- drop-down options ----------
@app.get("/api/options/<category>")
@login_required
def get_options(category):
    rows = db().execute("SELECT value FROM options WHERE category=? ORDER BY sort, value",
                        (category,)).fetchall()
    return jsonify(options=[r["value"] for r in rows])

@app.post("/api/options/<category>")
@login_required
def add_option(category):
    u = g.user
    ok = bool(u["is_admin"]) or u["role"] in OPTION_ADD_ROLES.get(category, []) \
        or (category in SHIFT_CAN_ADD and u["role"] == "technician" and u["shift_group"])
    if not ok:
        return err("not allowed to add options here", 403)
    v = ((request.get_json(silent=True) or {}).get("value") or "").strip()
    if not v:
        return err("value is required")
    con = db()
    top = con.execute("SELECT COALESCE(MAX(sort),0)+1 FROM options WHERE category=?",
                      (category,)).fetchone()[0]
    try:
        con.execute("INSERT INTO options(category,value,sort) VALUES(?,?,?)", (category, v, top))
        con.commit()
    except sqlite3.IntegrityError:
        return err("option already exists", 409)
    return jsonify(ok=True), 201

# ================= step 2: instruments, control valves, stock =================
import re

ENG = ("superintendent", "engineer", "supervisor")
STOCK_EDIT = ("engineer", "supervisor", "stock_keeper")

def roles_required(*roles):
    def deco(f):
        @wraps(f)
        @login_required
        def w(*a, **k):
            if not (g.user["is_admin"] or g.user["role"] in roles):
                return err("not allowed", 403)
            return f(*a, **k)
        return w
    return deco

def q_all(sql, args=()):
    return [dict(r) for r in db().execute(sql, args)]

def q_one(sql, args=()):
    r = db().execute(sql, args).fetchone()
    return dict(r) if r else None

def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None

def opt_ok(cat, v):
    return bool(q_one("SELECT 1 x FROM options WHERE category=? AND value=?", (cat, v)))

# ---------- instruments ----------
def check_tag(tag):
    if tag.startswith("DNT") and not re.match(r"^DNT-\d{4}$", tag):
        return "density meter tags must look like DNT-1234"

@app.get("/api/instruments")
@login_required
def list_instruments():
    q, a = "SELECT * FROM instruments WHERE active=1", []
    for f in ("area", "type"):
        if request.args.get(f):
            q += f" AND {f}=?"
            a.append(request.args[f])
    if request.args.get("q"):
        q += " AND (tag LIKE ? OR description LIKE ?)"
        a += [f"%{request.args['q']}%"] * 2
    return jsonify(instruments=q_all(q + " ORDER BY tag", a))

@app.get("/api/instruments/<tag>")
@login_required
def get_instrument(tag):
    i = q_one("SELECT * FROM instruments WHERE tag=?", (tag.upper(),))
    if not i:
        return err("not found", 404)
    i["valve"] = q_one("SELECT * FROM valves WHERE instrument_tag=? AND status='in_service'",
                       (i["tag"],))
    return jsonify(instrument=i)

@app.post("/api/instruments")
@roles_required(*ENG)
def add_instrument():
    j = request.get_json(silent=True) or {}
    tag = (j.get("tag") or "").strip().upper()
    if not tag:
        return err("tag is required")
    m = check_tag(tag)
    if m:
        return err(m)
    if not opt_ok("instrument_type", j.get("type")) or not opt_ok("area", j.get("area")):
        return err("type and area must be chosen from the lists")
    if q_one("SELECT 1 x FROM instruments WHERE tag=?", (tag,)):
        return err("tag already exists", 409)
    db().execute("INSERT INTO instruments(tag,type,area,description,is_density) VALUES(?,?,?,?,?)",
                 (tag, j["type"], j["area"], j.get("description"), int(tag.startswith("DNT"))))
    db().commit()
    return jsonify(ok=True), 201

@app.patch("/api/instruments/<tag>")
@roles_required(*ENG)
def edit_instrument(tag):
    j = request.get_json(silent=True) or {}
    s = {k: j[k] for k in ("type", "area", "description", "active") if k in j}
    if not s:
        return err("nothing to update")
    if ("type" in s and not opt_ok("instrument_type", s["type"])) or \
       ("area" in s and not opt_ok("area", s["area"])):
        return err("type and area must be chosen from the lists")
    if "active" in s:
        s["active"] = int(bool(s["active"]))
    cur = db().execute(f"UPDATE instruments SET {','.join(k + '=?' for k in s)} WHERE tag=?",
                       (*s.values(), tag.upper()))
    db().commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)

# ---------- control valves (life cycle by serial number) ----------
VALVE_STATUS = {"installed": "in_service", "removed": "workshop",
                "repaired": "spare", "scrapped": "scrapped"}
VALVE_NOTE_EVENTS = ("calibrated", "tested", "note")

def tag_problem(tag, serial=None):
    if not q_one("SELECT 1 x FROM instruments WHERE tag=? AND active=1", (tag,)):
        return "instrument tag not found"
    if q_one("SELECT 1 x FROM valves WHERE instrument_tag=? AND status='in_service' AND serial<>?",
             (tag, serial or "")):
        return "another valve is already installed on this instrument"

def log_valve(vid, event, tag, note):
    db().execute("INSERT INTO valve_events(valve_id,event,instrument_tag,note,user_id) "
                 "VALUES(?,?,?,?,?)", (vid, event, tag, note, g.user["id"]))

@app.get("/api/valves")
@login_required
def list_valves():
    q, a = "SELECT * FROM valves WHERE 1=1", []
    if request.args.get("status"):
        q += " AND status=?"
        a.append(request.args["status"])
    if request.args.get("q"):
        q += " AND (serial LIKE ? OR instrument_tag LIKE ?)"
        a += [f"%{request.args['q']}%"] * 2
    return jsonify(valves=q_all(q + " ORDER BY serial", a))

@app.get("/api/valves/<serial>")
@login_required
def get_valve(serial):
    v = q_one("SELECT * FROM valves WHERE serial=?", (serial,))
    if not v:
        return err("not found", 404)
    v["events"] = q_all("""SELECT e.*, u.name AS by_name FROM valve_events e
        LEFT JOIN users u ON u.id=e.user_id WHERE valve_id=? ORDER BY e.id""", (v["id"],))
    return jsonify(valve=v)

@app.post("/api/valves")
@roles_required(*ENG)
def add_valve():
    j = request.get_json(silent=True) or {}
    serial = (j.get("serial") or "").strip()
    if not serial:
        return err("serial number is required")
    if q_one("SELECT 1 x FROM valves WHERE serial=?", (serial,)):
        return err("serial number already exists", 409)
    tag = (j.get("instrument_tag") or "").strip().upper() or None
    if tag:
        m = tag_problem(tag)
        if m:
            return err(m, 409 if "already" in m else 400)
    cur = db().execute("INSERT INTO valves(serial,instrument_tag,manufacturer,model,size,status) "
                       "VALUES(?,?,?,?,?,?)",
                       (serial, tag, j.get("manufacturer"), j.get("model"), j.get("size"),
                        "in_service" if tag else "spare"))
    log_valve(cur.lastrowid, "registered", None, j.get("note"))
    if tag:
        log_valve(cur.lastrowid, "installed", tag, None)
    db().commit()
    return jsonify(ok=True), 201

@app.post("/api/valves/<serial>/events")
@roles_required(*ENG, "technician")
def valve_event(serial):
    j = request.get_json(silent=True) or {}
    ev = j.get("event")
    if ev not in VALVE_STATUS and ev not in VALVE_NOTE_EVENTS:
        return err("invalid event")
    v = q_one("SELECT * FROM valves WHERE serial=?", (serial,))
    if not v:
        return err("not found", 404)
    if v["status"] == "scrapped":
        return err("valve is scrapped", 409)
    log_tag, new_tag = v["instrument_tag"], v["instrument_tag"]
    if ev == "installed":
        log_tag = new_tag = (j.get("instrument_tag") or "").strip().upper()
        m = tag_problem(new_tag, serial) if new_tag else "instrument_tag is required"
        if m:
            return err(m, 409 if "already" in m else 400)
    elif ev in ("removed", "scrapped"):
        new_tag = None
    db().execute("UPDATE valves SET status=?, instrument_tag=? WHERE id=?",
                 (VALVE_STATUS.get(ev, v["status"]), new_tag, v["id"]))
    log_valve(v["id"], ev, log_tag, j.get("note"))
    db().commit()
    return jsonify(ok=True)

# ---------- stock ----------
def stock_row(i):
    i["available"] = i["qty_on_hand"] - i["reserved"]
    i["low"] = i["available"] <= i["min_qty"]
    return i

def move(item_id, kind, qty, ref=None, note=None):
    db().execute("INSERT INTO stock_moves(item_id,kind,qty,ref,note,user_id) VALUES(?,?,?,?,?,?)",
                 (item_id, kind, qty, ref, note, g.user["id"]))

def get_item(iid):
    return q_one("""SELECT s.*, COALESCE((SELECT SUM(qty) FROM reservations r
        WHERE r.item_id=s.id AND r.status='active'),0) AS reserved
        FROM stock_items s WHERE id=? AND active=1""", (iid,))

@app.get("/api/stock")
@login_required
def list_stock():
    rows = q_all("""SELECT s.*, COALESCE((SELECT SUM(qty) FROM reservations r
        WHERE r.item_id=s.id AND r.status='active'),0) AS reserved
        FROM stock_items s WHERE active=1 ORDER BY name""")
    items = [stock_row(r) for r in rows]
    if request.args.get("low") == "1":
        items = [i for i in items if i["low"]]
    return jsonify(items=items)

@app.post("/api/stock")
@roles_required(*STOCK_EDIT)
def add_stock():
    j = request.get_json(silent=True) or {}
    if not (j.get("name") or "").strip() or not opt_ok("unit", j.get("unit")):
        return err("name and a unit from the list are required")
    qty, mn = float(j.get("qty_on_hand") or 0), float(j.get("min_qty") or 0)
    if qty < 0 or mn < 0:
        return err("quantities cannot be negative")
    cur = db().execute("INSERT INTO stock_items(part_no,name,unit,qty_on_hand,min_qty) "
                       "VALUES(?,?,?,?,?)", (j.get("part_no"), j["name"].strip(), j["unit"], qty, mn))
    if qty:
        move(cur.lastrowid, "receive", qty, note="opening quantity")
    db().commit()
    return jsonify(id=cur.lastrowid), 201

@app.patch("/api/stock/<int:iid>")
@roles_required(*STOCK_EDIT)
def edit_stock(iid):
    j = request.get_json(silent=True) or {}
    s = {k: j[k] for k in ("part_no", "name", "unit", "min_qty", "active") if k in j}
    if not s:
        return err("nothing to update")
    if "unit" in s and not opt_ok("unit", s["unit"]):
        return err("unit must be chosen from the list")
    if "min_qty" in s and float(s["min_qty"]) < 0:
        return err("minimum cannot be negative")
    if "active" in s:
        s["active"] = int(bool(s["active"]))
    cur = db().execute(f"UPDATE stock_items SET {','.join(k + '=?' for k in s)} WHERE id=?",
                       (*s.values(), iid))
    db().commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)

@app.get("/api/stock/<int:iid>/moves")
@login_required
def stock_moves(iid):
    return jsonify(moves=q_all("""SELECT m.*, u.name AS by_name FROM stock_moves m
        LEFT JOIN users u ON u.id=m.user_id WHERE item_id=? ORDER BY m.id DESC""", (iid,)))

@app.post("/api/stock/<int:iid>/receive")
@roles_required("stock_keeper")
def receive_stock(iid):
    j = request.get_json(silent=True) or {}
    qty = num(j.get("qty"))
    if not qty:
        return err("qty must be greater than 0")
    if not get_item(iid):
        return err("not found", 404)
    db().execute("UPDATE stock_items SET qty_on_hand=qty_on_hand+? WHERE id=?", (qty, iid))
    move(iid, "receive", qty, j.get("ref"), j.get("note"))
    db().commit()
    return jsonify(ok=True)

@app.post("/api/stock/<int:iid>/reserve")
@login_required
def reserve_stock(iid):
    j = request.get_json(silent=True) or {}
    qty, it = num(j.get("qty")), get_item(iid)
    if not it:
        return err("not found", 404)
    if not qty:
        return err("qty must be greater than 0")
    if qty > it["qty_on_hand"] - it["reserved"]:
        return err("not enough available stock", 409)
    cur = db().execute("INSERT INTO reservations(item_id,qty,ref,requested_by) VALUES(?,?,?,?)",
                       (iid, qty, j.get("ref"), g.user["id"]))
    db().commit()
    return jsonify(reservation_id=cur.lastrowid), 201

@app.get("/api/reservations")
@login_required
def list_reservations():
    return jsonify(reservations=q_all("""SELECT r.*, s.name AS item_name, u.name AS by_name
        FROM reservations r JOIN stock_items s ON s.id=r.item_id
        LEFT JOIN users u ON u.id=r.requested_by WHERE r.status=? ORDER BY r.id DESC""",
        (request.args.get("status", "active"),)))

@app.post("/api/reservations/<int:rid>/release")
@login_required
def release_reservation(rid):
    r = q_one("SELECT * FROM reservations WHERE id=? AND status='active'", (rid,))
    if not r:
        return err("active reservation not found", 404)
    if not (g.user["is_admin"] or g.user["role"] == "stock_keeper" or r["requested_by"] == g.user["id"]):
        return err("not allowed", 403)
    db().execute("UPDATE reservations SET status='released', closed_at=CURRENT_TIMESTAMP WHERE id=?",
                 (rid,))
    db().commit()
    return jsonify(ok=True)

@app.post("/api/stock/<int:iid>/issue")
@roles_required("stock_keeper")
def issue_stock(iid):
    j = request.get_json(silent=True) or {}
    it = get_item(iid)
    if not it:
        return err("not found", 404)
    rid = j.get("reservation_id")
    if rid:
        r = q_one("SELECT * FROM reservations WHERE id=? AND item_id=? AND status='active'",
                  (rid, iid))
        if not r:
            return err("active reservation not found for this item", 404)
        qty = r["qty"]
    else:
        qty = num(j.get("qty"))
        if not qty:
            return err("qty must be greater than 0")
        if qty > it["qty_on_hand"] - it["reserved"]:
            return err("not enough available stock", 409)
    if qty > it["qty_on_hand"]:
        return err("not enough stock on hand", 409)
    db().execute("UPDATE stock_items SET qty_on_hand=qty_on_hand-? WHERE id=?", (qty, iid))
    if rid:
        db().execute("UPDATE reservations SET status='issued', closed_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", (rid,))
    move(iid, "issue", qty, j.get("ref") or (r["ref"] if rid else None), j.get("note"))
    if it["qty_on_hand"] - qty - (it["reserved"] - (qty if rid else 0)) <= it["min_qty"]:
        notify(ids_of("stock_keeper"), f"Low stock: {it['name']}", skip_self=False)
    db().commit()
    return jsonify(ok=True)

# ---------- purchase requests (stock keeper -> team leader) ----------
@app.get("/api/purchase-requests")
@login_required
def list_purchase():
    q, a = """SELECT p.*, s.name AS item_name, l.name AS leader_name FROM purchase_requests p
        JOIN stock_items s ON s.id=p.item_id JOIN users l ON l.id=p.leader_id WHERE 1=1""", []
    if request.args.get("status"):
        q += " AND p.status=?"
        a.append(request.args["status"])
    if g.user["is_leader"] and request.args.get("mine") == "1":
        q += " AND p.leader_id=?"
        a.append(g.user["id"])
    return jsonify(requests=q_all(q + " ORDER BY p.id DESC", a))

@app.post("/api/purchase-requests")
@roles_required("stock_keeper", "engineer", "supervisor")
def add_purchase():
    j = request.get_json(silent=True) or {}
    qty = num(j.get("qty"))
    if not qty or not get_item(j.get("item_id")):
        return err("valid item_id and qty are required")
    if not q_one("SELECT 1 x FROM users WHERE id=? AND is_leader=1 AND active=1", (j.get("leader_id"),)):
        return err("leader_id must be a team leader")
    cur = db().execute("INSERT INTO purchase_requests(item_id,qty,note,leader_id,requested_by) "
                       "VALUES(?,?,?,?,?)",
                       (j["item_id"], qty, j.get("note"), j["leader_id"], g.user["id"]))
    notify([j["leader_id"]] + ids_of("engineer"), f"Purchase request #{cur.lastrowid} needs approval")
    db().commit()
    return jsonify(id=cur.lastrowid), 201

@app.post("/api/purchase-requests/<int:pid>/decide")
@login_required
def decide_purchase(pid):
    p = q_one("SELECT * FROM purchase_requests WHERE id=? AND status='pending'", (pid,))
    if not p:
        return err("pending request not found", 404)
    if not (g.user["is_admin"] or g.user["id"] == p["leader_id"]):
        return err("only the assigned team leader can decide", 403)
    st = "approved" if (request.get_json(silent=True) or {}).get("approve") else "rejected"
    db().execute("UPDATE purchase_requests SET status=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
                 (st, pid))
    db().commit()
    return jsonify(status=st)

@app.post("/api/purchase-requests/<int:pid>/receive")
@roles_required("stock_keeper")
def receive_purchase(pid):
    p = q_one("SELECT * FROM purchase_requests WHERE id=? AND status='approved'", (pid,))
    if not p:
        return err("approved request not found", 404)
    db().execute("UPDATE stock_items SET qty_on_hand=qty_on_hand+? WHERE id=?", (p["qty"], p["item_id"]))
    move(p["item_id"], "receive", p["qty"], f"PR-{pid}", "purchase received")
    db().execute("UPDATE purchase_requests SET status='received' WHERE id=?", (pid,))
    db().commit()
    return jsonify(ok=True)

# ================= step 3: work requests, notifications, weekly plan =================
from datetime import datetime, date, timedelta
from flask import send_from_directory

UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx",
               "ppt", "pptx", "txt", "csv"}
FMT = "%Y-%m-%d %H:%M"

def parse_dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("T", " ")[:16])
    except ValueError:
        return None

def save_upload(f):
    """Saves an uploaded file under a random name; returns stored name or None if type not allowed."""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_EXT:
        return None
    stored = secrets.token_hex(16) + "." + ext
    f.save(os.path.join(UPLOAD_DIR, stored))
    return stored

def ids_of(role):
    return [r["id"] for r in q_all("SELECT id FROM users WHERE role=? AND active=1", (role,))]

def notify(ids, msg, wid=None, skip_self=True):
    me = g.user["id"] if skip_self and "user" in g else None
    for u in set(ids):
        if u and u != me:
            db().execute("INSERT INTO notifications(user_id,message,wr_id) VALUES(?,?,?)",
                         (u, msg, wid))

def log_wr(wid, ev, note=None, system=False):
    db().execute("INSERT INTO wr_events(wr_id,event,note,user_id) VALUES(?,?,?,?)",
                 (wid, ev, note, None if system else g.user["id"]))

def get_wr(wid):
    return q_one("""SELECT w.*, l.name AS leader_name, c.name AS creator_name
        FROM work_requests w JOIN users l ON l.id=w.leader_id JOIN users c ON c.id=w.created_by
        WHERE w.id=?""", (wid,))

def crew_ids(wid):
    return [r["user_id"] for r in q_all("SELECT user_id FROM wr_crew WHERE wr_id=?", (wid,))]

def is_leader_of(w):
    return bool(g.user["is_admin"]) or g.user["id"] == w["leader_id"]

def is_mgr(w):
    return is_leader_of(w) or g.user["role"] == "superintendent"

def can_touch(w):
    return is_mgr(w) or g.user["id"] == w["created_by"] or g.user["id"] in crew_ids(w["id"])

def decorate(w):
    w["overdue"] = w["status"] in ("issued", "assigned") and \
        w["scheduled_at"] < datetime.now().strftime(FMT)
    return w

def check_overdue():
    """No background scheduler: runs whenever requests or notifications are loaded."""
    now = datetime.now().strftime(FMT)
    for w in q_all("""SELECT * FROM work_requests WHERE status IN ('issued','assigned')
                      AND overdue_notified=0 AND scheduled_at<?""", (now,)):
        db().execute("UPDATE work_requests SET overdue_notified=1 WHERE id=?", (w["id"],))
        log_wr(w["id"], "overdue", system=True)
        notify([w["leader_id"]] + ids_of("superintendent"),
               f"OVERDUE: {w['code']} was not started by its scheduled time", w["id"], skip_self=False)
    db().commit()

def crew_options(w):
    busy = {r["user_id"] for r in q_all("""SELECT c.user_id FROM wr_crew c
        JOIN work_requests x ON x.id=c.wr_id WHERE x.status IN ('assigned','in_progress')
        AND substr(x.scheduled_at,1,10)=? AND x.id<>?""", (w["scheduled_at"][:10], w["id"]))}
    techs = q_all("""SELECT id,name,is_density FROM users WHERE role='technician' AND active=1
                     AND shift_group IS NULL ORDER BY name""")
    if w["instrument_tag"].startswith("DNT"):
        techs = [t for t in techs if t["is_density"]]
    asst = q_all("SELECT id,name FROM users WHERE role='assistant' AND active=1 ORDER BY name")
    for x in techs + asst:
        x["available"] = x["id"] not in busy
    return techs, asst

# ---------- issue / list / detail ----------
@app.post("/api/work-requests")
@login_required
def add_wr():
    j = request.get_json(silent=True) or {}
    u = g.user
    shift = u["role"] == "technician" and u["shift_group"]
    emergency = j.get("priority") == "emergency"
    ok = (u["is_admin"] or u["role"] in ("engineer", "supervisor")) if emergency \
        else (u["is_admin"] or u["role"] == "superintendent" or shift)
    if not ok:
        return err("not allowed to issue this kind of request", 403)
    tag = (j.get("instrument_tag") or "").strip().upper()
    if not q_one("SELECT 1 x FROM instruments WHERE tag=? AND active=1", (tag,)):
        return err("instrument tag not found")
    if not opt_ok("job_title", j.get("job_title")) or not opt_ok("work_needed", j.get("work_needed")):
        return err("job title and work needed must be chosen from the lists")
    dt = parse_dt(j["scheduled_at"]) if j.get("scheduled_at") else datetime.now()
    if not dt:
        return err("scheduled_at must look like 2026-11-15 08:00")
    if not emergency and not shift and dt.weekday() in (4, 5):
        return err("working days are Sunday to Thursday")
    leader = q_one("SELECT * FROM users WHERE id=? AND is_leader=1 AND active=1",
                   (u["id"] if emergency else j.get("leader_id"),))
    if not leader:
        return err("a team leader is required")
    if tag.startswith("DNT") and not (leader["is_density"] and (not shift or u["is_density"])):
        return err("density meters can only be handled by density staff")
    cur = db().execute("""INSERT INTO work_requests(priority,instrument_tag,job_title,work_needed,
        details,scheduled_at,status,leader_id,created_by) VALUES(?,?,?,?,?,?,?,?,?)""",
        ("emergency" if emergency else "normal", tag, j["job_title"], j["work_needed"],
         j.get("details"), dt.strftime(FMT), "assigned" if shift else "issued",
         leader["id"], u["id"]))
    wid = cur.lastrowid
    code = f"{'EM' if emergency else 'WR'}-{datetime.now().year}-{wid:04d}"
    db().execute("UPDATE work_requests SET code=? WHERE id=?", (code, wid))
    log_wr(wid, "issued")
    if shift:
        db().execute("INSERT INTO wr_crew VALUES(?,?,'technician')", (wid, u["id"]))
        log_wr(wid, "assigned", "auto-assigned to creator")
    notify([leader["id"]], f"New work request {code} for {tag}", wid)
    db().commit()
    return jsonify(id=wid, code=code), 201

@app.get("/api/work-requests")
@login_required
def list_wr():
    check_overdue()
    u = g.user
    q, a = """SELECT w.*, l.name AS leader_name, i.area FROM work_requests w
        JOIN users l ON l.id=w.leader_id LEFT JOIN instruments i ON i.tag=w.instrument_tag
        WHERE """, []
    if u["role"] == "superintendent" or (u["is_admin"] and request.args.get("all") == "1"):
        q += "1=1"
    else:  # a request only appears for its leader, its creator and its crew
        q += """(w.leader_id=? OR w.created_by=? OR
                 EXISTS(SELECT 1 FROM wr_crew c WHERE c.wr_id=w.id AND c.user_id=?))"""
        a += [u["id"]] * 3
    for f, col in (("status", "w.status"), ("tag", "w.instrument_tag"), ("priority", "w.priority")):
        if request.args.get(f):
            q += f" AND {col}=?"
            a.append(request.args[f].upper() if f == "tag" else request.args[f])
    if request.args.get("from"):
        q += " AND w.scheduled_at>=?"
        a.append(request.args["from"])
    if request.args.get("to"):
        q += " AND w.scheduled_at<=?"
        a.append(request.args["to"] + " 23:59")
    return jsonify(requests=[decorate(r) for r in q_all(q + " ORDER BY w.scheduled_at DESC", a)])

@app.get("/api/work-requests/<int:wid>")
@login_required
def get_wr_detail(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not can_touch(w):
        return err("not allowed", 403)
    w["crew"] = q_all("""SELECT u.id,u.name,c.crew_role FROM wr_crew c JOIN users u ON u.id=c.user_id
                         WHERE c.wr_id=?""", (wid,))
    w["events"] = q_all("""SELECT e.event,e.note,e.created_at,u.name AS by_name FROM wr_events e
                           LEFT JOIN users u ON u.id=e.user_id WHERE wr_id=? ORDER BY e.id""", (wid,))
    w["notes"] = q_all("""SELECT n.text,n.created_at,u.name AS by_name FROM wr_notes n
                          LEFT JOIN users u ON u.id=n.user_id WHERE wr_id=? ORDER BY n.id""", (wid,))
    w["files"] = q_all("SELECT id,filename,created_at FROM wr_files WHERE wr_id=? ORDER BY id", (wid,))
    w["parts"] = q_all("""SELECT r.id,s.name,r.qty,r.status FROM reservations r
                          JOIN stock_items s ON s.id=r.item_id WHERE r.ref=?""", (w["code"],))
    return jsonify(request=decorate(w))

@app.get("/api/instruments/<tag>/history")
@login_required
def instrument_history(tag):
    q = """SELECT w.id,w.code,w.job_title,w.work_needed,w.scheduled_at,w.status,w.priority,
        l.name AS leader_name,
        (SELECT group_concat(u.name,', ') FROM wr_crew c JOIN users u ON u.id=c.user_id
         WHERE c.wr_id=w.id) AS crew
        FROM work_requests w JOIN users l ON l.id=w.leader_id WHERE w.instrument_tag=?"""
    a = [tag.upper()]
    if request.args.get("code"):
        q += " AND w.code LIKE ?"
        a.append(f"%{request.args['code']}%")
    if request.args.get("from"):
        q += " AND w.scheduled_at>=?"
        a.append(request.args["from"])
    if request.args.get("to"):
        q += " AND w.scheduled_at<=?"
        a.append(request.args["to"] + " 23:59")
    if request.args.get("leader_id"):
        q += " AND w.leader_id=?"
        a.append(request.args["leader_id"])
    if request.args.get("technician_id"):
        q += " AND EXISTS(SELECT 1 FROM wr_crew c WHERE c.wr_id=w.id AND c.user_id=?)"
        a.append(request.args["technician_id"])
    return jsonify(history=q_all(q + " ORDER BY w.scheduled_at DESC", a))

# ---------- crew assignment ----------
@app.get("/api/work-requests/<int:wid>/available-crew")
@login_required
def available_crew(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not is_leader_of(w):
        return err("only the assigned team leader can pick the crew", 403)
    techs, asst = crew_options(w)
    return jsonify(technicians=techs, assistants=asst)

@app.post("/api/work-requests/<int:wid>/assign")
@login_required
def assign_crew(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not is_leader_of(w):
        return err("only the assigned team leader can pick the crew", 403)
    if w["status"] not in ("issued", "assigned"):
        return err("crew can only be changed before work starts", 409)
    j = request.get_json(silent=True) or {}
    techs, asst = crew_options(w)
    t = next((x for x in techs if x["id"] == j.get("technician_id")), None)
    if not t:
        return err("choose an eligible technician")
    a = next((x for x in asst if x["id"] == j.get("assistant_id")), None) if j.get("assistant_id") else None
    if j.get("assistant_id") and not a:
        return err("choose a valid assistant")
    for x in (t, a):
        if x and not x["available"]:
            return err(f"{x['name']} is already on another job on that day", 409)
    db().execute("DELETE FROM wr_crew WHERE wr_id=?", (wid,))
    db().execute("INSERT INTO wr_crew VALUES(?,?,'technician')", (wid, t["id"]))
    if a:
        db().execute("INSERT INTO wr_crew VALUES(?,?,'assistant')", (wid, a["id"]))
    db().execute("UPDATE work_requests SET status='assigned' WHERE id=?", (wid,))
    log_wr(wid, "assigned")
    notify([t["id"]] + ([a["id"]] if a else []),
           f"You are assigned to {w['code']} on {w['scheduled_at']}", wid)
    db().commit()
    return jsonify(ok=True)

# ---------- life cycle ----------
# action: (allowed from, new status, who may do it, who gets notified)
ACTIONS = {
    "start": (("assigned",), "in_progress", "crew", "leader"),
    "request-completion": (("in_progress",), "completion_requested", "crew", "leader"),
    "hold": (("assigned", "in_progress"), "on_hold", "mgr", "all"),
    "resume": (("on_hold",), None, "mgr", "all"),
    "cancel": (("issued", "assigned", "in_progress", "on_hold"), "cancelled", "mgr", "all"),
}

@app.post("/api/work-requests/<int:wid>/<action>")
@login_required
def wr_action(wid, action):
    if action not in ACTIONS:
        return err("unknown action", 404)
    frm, new, who, tgt = ACTIONS[action]
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not (is_mgr(w) if who == "mgr" else (is_mgr(w) or g.user["id"] in crew_ids(wid))):
        return err("not allowed", 403)
    if w["status"] not in frm:
        return err(f"cannot {action} a request that is {w['status']}", 409)
    if action == "resume":
        started = q_one("SELECT 1 x FROM wr_events WHERE wr_id=? AND event='started'", (wid,))
        new = "in_progress" if started else "assigned"
    note = (request.get_json(silent=True) or {}).get("note")
    db().execute("UPDATE work_requests SET status=? WHERE id=?", (new, wid))
    ev = {"start": "started", "request-completion": "completion_requested", "hold": "on_hold",
          "resume": "resumed", "cancel": "cancelled"}[action]
    log_wr(wid, ev, note)
    if action == "cancel":
        db().execute("UPDATE reservations SET status='released', closed_at=CURRENT_TIMESTAMP "
                     "WHERE ref=? AND status='active'", (w["code"],))
    people = [w["leader_id"]] if tgt == "leader" else \
        [w["leader_id"]] + crew_ids(wid) + ids_of("superintendent")
    notify(people, f"{w['code']}: {ev.replace('_', ' ')}", wid)
    db().commit()
    return jsonify(status=new)

@app.post("/api/work-requests/<int:wid>/review")
@login_required
def review_completion(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not is_leader_of(w):
        return err("only the assigned team leader can review completion", 403)
    if w["status"] != "completion_requested":
        return err("no completion request to review", 409)
    j = request.get_json(silent=True) or {}
    ok = bool(j.get("approve"))
    new = "completed" if ok else "in_progress"
    db().execute("UPDATE work_requests SET status=? WHERE id=?", (new, wid))
    log_wr(wid, "completed" if ok else "returned", j.get("note"))
    notify(crew_ids(wid) + (ids_of("superintendent") if ok else []),
           f"{w['code']}: {'completion approved' if ok else 'sent back for more work'}", wid)
    db().commit()
    return jsonify(status=new)

# ---------- parts, notes, attachments ----------
@app.post("/api/work-requests/<int:wid>/parts")
@login_required
def request_parts(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not can_touch(w):
        return err("not allowed", 403)
    if w["status"] not in ("assigned", "in_progress", "on_hold"):
        return err("parts can only be requested on an active request", 409)
    j = request.get_json(silent=True) or {}
    it, qty = get_item(j.get("item_id")), num(j.get("qty"))
    if not it or not qty:
        return err("valid item_id and qty are required")
    if qty > it["qty_on_hand"] - it["reserved"]:
        return err("not enough available stock", 409)
    cur = db().execute("INSERT INTO reservations(item_id,qty,ref,requested_by) VALUES(?,?,?,?)",
                       (it["id"], qty, w["code"], g.user["id"]))
    log_wr(wid, "parts_requested", f"{it['name']} x{qty:g}")
    notify(ids_of("stock_keeper"), f"{w['code']}: parts requested - {it['name']} x{qty:g}", wid)
    db().commit()
    return jsonify(reservation_id=cur.lastrowid), 201

@app.post("/api/work-requests/<int:wid>/notes")
@login_required
def add_note(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not can_touch(w):
        return err("not allowed", 403)
    t = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not t:
        return err("text is required")
    db().execute("INSERT INTO wr_notes(wr_id,text,user_id) VALUES(?,?,?)", (wid, t, g.user["id"]))
    db().commit()
    return jsonify(ok=True), 201

@app.post("/api/work-requests/<int:wid>/files")
@login_required
def add_file(wid):
    w = get_wr(wid)
    if not w:
        return err("not found", 404)
    if not can_touch(w):
        return err("not allowed", 403)
    f = request.files.get("file")
    if not f or not f.filename:
        return err("file is required")
    stored = save_upload(f)
    if not stored:
        return err("file type not allowed")
    db().execute("INSERT INTO wr_files(wr_id,filename,stored,user_id) VALUES(?,?,?,?)",
                 (wid, f.filename, stored, g.user["id"]))
    db().commit()
    return jsonify(ok=True), 201

@app.get("/api/files/<int:fid>")
@login_required
def download_file(fid):
    f = q_one("SELECT * FROM wr_files WHERE id=?", (fid,))
    w = get_wr(f["wr_id"]) if f else None
    if not w:
        return err("not found", 404)
    if not can_touch(w):
        return err("not allowed", 403)
    return send_from_directory(UPLOAD_DIR, f["stored"], as_attachment=True,
                               download_name=f["filename"])

# ---------- weekly plan (Sunday to Thursday) ----------
@app.get("/api/weekly-plan")
@roles_required(*ENG)
def weekly_plan():
    if request.args.get("week_start"):
        ws = parse_dt(request.args["week_start"] + " 00:00")
        if not ws or ws.weekday() != 6:
            return err("week_start must be a Sunday, like 2026-11-15")
    else:  # default: next week
        t = date.today()
        ws = datetime.combine(t - timedelta(days=(t.weekday() + 1) % 7), datetime.min.time()) \
            + timedelta(days=7)
    rows = q_all("""SELECT w.id,w.code,w.instrument_tag,i.area,w.work_needed,w.job_title,
        w.scheduled_at,w.status,w.priority,l.name AS leader_name FROM work_requests w
        JOIN users l ON l.id=w.leader_id LEFT JOIN instruments i ON i.tag=w.instrument_tag
        WHERE w.scheduled_at>=? AND w.scheduled_at<? AND w.status<>'cancelled'
        ORDER BY w.scheduled_at""",
        (ws.strftime(FMT), (ws + timedelta(days=5)).strftime(FMT)))
    return jsonify(week_start=ws.strftime("%Y-%m-%d"), requests=rows)

# ---------- notifications ----------
@app.get("/api/notifications")
@login_required
def list_notifications():
    check_overdue()
    q = "SELECT * FROM notifications WHERE user_id=?"
    if request.args.get("unread") == "1":
        q += " AND is_read=0"
    rows = q_all(q + " ORDER BY id DESC LIMIT 100", (g.user["id"],))
    unread = q_one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",
                   (g.user["id"],))["n"]
    return jsonify(notifications=rows, unread=unread)

@app.post("/api/notifications/<int:nid>/read")
@login_required
def read_notification(nid):
    db().execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (nid, g.user["id"]))
    db().commit()
    return jsonify(ok=True)

@app.post("/api/notifications/read-all")
@login_required
def read_all_notifications():
    db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
    db().commit()
    return jsonify(ok=True)

# ================= step 4: leave, shift schedule, follow-up, evaluation =================
import statistics

# requester role -> roles that may approve (nobody approves their own)
APPROVER = {"technician": ("engineer",), "assistant": ("supervisor",),
            "engineer": ("superintendent",), "supervisor": ("superintendent",)}
LEAVE_TYPES = ("annual", "partial", "sick")
SHIFT_CODES = ("M", "A", "N", "O")
SHIFT_GROUPS_OK = ("A", "B", "C", "D")
EVAL_W = {"work": 40, "speed": 30, "annual": 15, "sick": 15}   # score weights (total 100)
EVAL_CAP = {"annual": 30, "sick": 15}   # leave days at which that component reaches 0

def leave_days(u, d1, d2):
    """Days off counted: Sun-Thu for regular staff; for shift technicians every day not coded O."""
    n, d = 0, d1
    while d <= d2:
        if u["shift_group"]:
            r = q_one("SELECT code FROM shift_schedule WHERE day=? AND shift_group=?",
                      (d.isoformat(), u["shift_group"]))
            n += 0 if r and r["code"] == "O" else 1
        else:
            n += 0 if d.weekday() in (4, 5) else 1
        d += timedelta(days=1)
    return n

def leave_clash(uid, s, e, partial):
    q = """SELECT 1 x FROM leave_requests WHERE user_id=? AND start_date<=? AND end_date>=?
           AND status IN ('awaiting_replacement','pending','approved')"""
    if partial:
        q += " AND type<>'partial'"
    return bool(q_one(q, (uid, e, s)))

def approver_ids(requester_role):
    return [i for r in APPROVER[requester_role] for i in ids_of(r)]

def can_decide(l_user_role, owner_id):
    return g.user["role"] in APPROVER.get(l_user_role, ()) and g.user["id"] != owner_id

def get_leave(lid):
    return q_one("""SELECT l.*, e.name AS employee, e.role AS employee_role
        FROM leave_requests l JOIN users e ON e.id=l.user_id WHERE l.id=?""", (lid,))

@app.post("/api/leave")
@roles_required("technician", "assistant", "engineer", "supervisor")
def apply_leave():
    j = request.get_json(silent=True) or {}
    u, t = g.user, j.get("type")
    if t not in LEAVE_TYPES:
        return err("type must be annual, partial or sick")
    d1 = parse_dt((j.get("start_date") or "") + " 00:00")
    d2 = parse_dt((j.get("end_date") or j.get("start_date") or "") + " 00:00")
    if not d1 or not d2 or d2 < d1:
        return err("valid start_date and end_date (YYYY-MM-DD) are required")
    s, e = d1.date().isoformat(), d2.date().isoformat()
    days = hours = 0
    st = et = None
    if t == "partial":
        a = parse_dt(f"{s} {j.get('start_time')}")
        b = parse_dt(f"{s} {j.get('end_time')}")
        if s != e or not a or not b or b <= a:
            return err("partial leave needs one date with start_time and end_time (HH:MM)")
        hours, st, et = (b - a).total_seconds() / 3600, a.strftime("%H:%M"), b.strftime("%H:%M")
    else:
        days = leave_days(u, d1.date(), d2.date())
    if leave_clash(u["id"], s, e, t == "partial"):
        return err("you already have leave on these dates", 409)
    shift = u["role"] == "technician" and u["shift_group"]
    rep = None
    if shift:  # shift technicians must name a replacement who confirms before approval
        rep = q_one("SELECT * FROM users WHERE id=? AND role='technician' AND active=1 AND id<>?",
                    (j.get("replacement_id"), u["id"]))
        if not rep:
            return err("a replacement technician is required")
        if leave_clash(rep["id"], s, e, t == "partial"):
            return err("the replacement is on leave on these dates", 409)
    cur = db().execute("""INSERT INTO leave_requests(user_id,type,start_date,end_date,start_time,
        end_time,days,hours,reason,replacement_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (u["id"], t, s, e, st, et, days, hours, j.get("reason"), rep["id"] if rep else None,
         "awaiting_replacement" if shift else "pending"))
    if shift:
        notify([rep["id"]], f"{u['name']} asks you to cover {t} leave {s} to {e}")
    else:
        notify(approver_ids(u["role"]), f"{u['name']} requested {t} leave {s} to {e}")
    db().commit()
    return jsonify(id=cur.lastrowid, days=days, hours=hours), 201

@app.get("/api/leave")
@login_required
def list_leave():
    u = g.user
    approvable = [k for k, v in APPROVER.items() if u["role"] in v]
    conds, a = ["l.user_id=?", "l.replacement_id=?"], [u["id"], u["id"]]
    if approvable and request.args.get("mine") != "1":
        conds.append(f"e.role IN ({','.join('?' * len(approvable))})")
        a += approvable
    q = """SELECT l.*, e.name AS employee, e.role AS employee_role, r.name AS replacement_name
        FROM leave_requests l JOIN users e ON e.id=l.user_id
        LEFT JOIN users r ON r.id=l.replacement_id WHERE (""" + " OR ".join(conds) + ")"
    for f in ("status", "user_id", "type"):
        if request.args.get(f):
            q += f" AND l.{'user_id' if f == 'user_id' else f}=?"
            a.append(request.args[f])
    rows = q_all(q + " ORDER BY l.start_date DESC", a)
    for r in rows:
        r["has_report"] = bool(r.pop("report_stored"))
    return jsonify(leave=rows)

@app.post("/api/leave/<int:lid>/confirm")
@login_required
def confirm_cover(lid):
    l = get_leave(lid)
    if not l or l["replacement_id"] != g.user["id"]:
        return err("not found", 404)
    if l["status"] != "awaiting_replacement":
        return err("nothing to confirm", 409)
    ok = bool((request.get_json(silent=True) or {}).get("accept"))
    db().execute("UPDATE leave_requests SET status=? WHERE id=?",
                 ("pending" if ok else "replacement_declined", lid))
    if ok:
        notify(approver_ids(l["employee_role"]),
               f"{l['employee']} requested {l['type']} leave {l['start_date']} to {l['end_date']} "
               f"(replacement confirmed)")
    else:
        notify([l["user_id"]], f"{g.user['name']} cannot cover your leave; submit a new request")
    db().commit()
    return jsonify(status="pending" if ok else "replacement_declined")

@app.post("/api/leave/<int:lid>/decide")
@login_required
def decide_leave(lid):
    l = get_leave(lid)
    if not l:
        return err("not found", 404)
    if not can_decide(l["employee_role"], l["user_id"]):
        return err("not allowed to decide this leave", 403)
    if l["status"] != "pending":
        return err("leave is not waiting for approval", 409)
    j = request.get_json(silent=True) or {}
    st = "approved" if j.get("approve") else "rejected"
    db().execute("""UPDATE leave_requests SET status=?, decided_by=?, decision_note=?,
                    decided_at=datetime('now','localtime') WHERE id=?""",
                 (st, g.user["id"], j.get("note"), lid))
    notify([l["user_id"]] + ([l["replacement_id"]] if st == "approved" and l["replacement_id"] else []),
           f"Leave {l['start_date']} to {l['end_date']} for {l['employee']}: {st}")
    db().commit()
    return jsonify(status=st)

@app.post("/api/leave/<int:lid>/cancel")
@login_required
def cancel_leave(lid):
    l = get_leave(lid)
    if not l or l["user_id"] != g.user["id"]:
        return err("not found", 404)
    ok = l["status"] in ("awaiting_replacement", "pending") or \
        (l["status"] == "approved" and l["start_date"] > date.today().isoformat())
    if not ok:
        return err("this leave can no longer be cancelled", 409)
    db().execute("UPDATE leave_requests SET status='cancelled' WHERE id=?", (lid,))
    db().commit()
    return jsonify(ok=True)

@app.post("/api/leave/<int:lid>/report")
@login_required
def upload_report(lid):
    l = get_leave(lid)
    if not l or l["user_id"] != g.user["id"]:
        return err("not found", 404)
    if l["type"] != "sick":
        return err("only sick leave takes a doctor report")
    f = request.files.get("file")
    stored = save_upload(f) if f and f.filename else None
    if not stored:
        return err("a file of an allowed type is required")
    db().execute("UPDATE leave_requests SET report_name=?, report_stored=? WHERE id=?",
                 (f.filename, stored, lid))
    db().commit()
    return jsonify(ok=True)

@app.get("/api/leave/<int:lid>/report")
@login_required
def download_report(lid):
    l = get_leave(lid)
    if not l or not l["report_stored"]:
        return err("not found", 404)
    if not (l["user_id"] == g.user["id"] or can_decide(l["employee_role"], l["user_id"])):
        return err("not allowed", 403)
    return send_from_directory(UPLOAD_DIR, l["report_stored"], as_attachment=True,
                               download_name=l["report_name"])

# ---------- shift schedule ----------
@app.get("/api/shifts")
@login_required
def get_shifts():
    try:
        a = request.args.get("from") or date.today().replace(day=1).isoformat()
        b = request.args.get("to") or (date.fromisoformat(a) + timedelta(days=31)).isoformat()
    except ValueError:
        return err("dates must look like 2026-11-01")
    rows = q_all("SELECT day,shift_group,code FROM shift_schedule WHERE day>=? AND day<=? "
                 "ORDER BY day,shift_group", (a, b))
    people = {r["shift_group"]: r["name"] for r in
              q_all("SELECT shift_group,name FROM users WHERE shift_group IS NOT NULL AND active=1")}
    return jsonify(people=people, rows=rows)

@app.post("/api/shifts/generate")
@roles_required("superintendent")
def generate_shifts():
    """Builds a year from a repeating cycle. pattern: e.g. ["M","M","A","A","N","N","O","O"];
    offsets: where each shift is in that cycle on 1 January, e.g. {"A":0,"B":2,"C":4,"D":6}."""
    j = request.get_json(silent=True) or {}
    pat, off = j.get("pattern"), j.get("offsets")
    try:
        year = int(j.get("year"))
        ok = isinstance(pat, list) and pat and all(c in SHIFT_CODES for c in pat) and \
            isinstance(off, dict) and off and all(k in SHIFT_GROUPS_OK and isinstance(v, int)
                                                  for k, v in off.items())
    except (TypeError, ValueError):
        ok = False
    if not ok:
        return err("year, pattern (codes M/A/N/O) and offsets (shifts A-D) are required")
    con, d = db(), date(year, 1, 1)
    while d.year == year:
        for grp, o in off.items():
            con.execute("INSERT OR REPLACE INTO shift_schedule VALUES(?,?,?)",
                        (d.isoformat(), grp, pat[(d.timetuple().tm_yday - 1 + o) % len(pat)]))
        d += timedelta(days=1)
    con.commit()
    return jsonify(ok=True, year=year)

@app.post("/api/shifts/import")
@roles_required("superintendent")
def import_shifts():
    rows = (request.get_json(silent=True) or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return err("rows is required: [{day, shift_group, code}]")
    for r in rows:
        try:
            date.fromisoformat(r["day"])
        except (KeyError, TypeError, ValueError):
            return err("every row needs a day like 2026-11-01")
        if r.get("shift_group") not in SHIFT_GROUPS_OK or r.get("code") not in SHIFT_CODES:
            return err("every row needs shift_group A-D and code M/A/N/O")
    for r in rows:
        db().execute("INSERT OR REPLACE INTO shift_schedule VALUES(?,?,?)",
                     (r["day"], r["shift_group"], r["code"]))
    db().commit()
    return jsonify(ok=True, rows=len(rows))

@app.put("/api/shifts/<day>/<grp>")
@roles_required("superintendent")
def set_shift(day, grp):
    code = (request.get_json(silent=True) or {}).get("code")
    try:
        date.fromisoformat(day)
    except ValueError:
        return err("day must look like 2026-11-01")
    if grp not in SHIFT_GROUPS_OK or code not in SHIFT_CODES:
        return err("shift A-D and code M/A/N/O are required")
    db().execute("INSERT OR REPLACE INTO shift_schedule VALUES(?,?,?)", (day, grp, code))
    db().commit()
    return jsonify(ok=True)

# ---------- employee follow-up and evaluation ----------
@app.get("/api/followup")
@roles_required(*ENG)
def followup():
    year = request.args.get("year") or str(date.today().year)
    rows = q_all("""SELECT u.id,u.name,u.role,u.shift_group,
        COALESCE(SUM(CASE WHEN l.type='annual' THEN l.days END),0) AS annual_days,
        COALESCE(SUM(CASE WHEN l.type='sick' THEN l.days END),0) AS sick_days,
        COALESCE(SUM(CASE WHEN l.type='partial' THEN l.hours END),0) AS partial_hours
        FROM users u LEFT JOIN leave_requests l ON l.user_id=u.id AND l.status='approved'
          AND substr(l.start_date,1,4)=?
        WHERE u.active=1 AND u.role IN ('technician','assistant','engineer','supervisor')
        GROUP BY u.id ORDER BY u.name""", (year,))
    today = date.today().isoformat()
    on_leave = q_all("""SELECT u.id,u.name,l.type FROM leave_requests l JOIN users u ON u.id=l.user_id
        WHERE l.status='approved' AND l.start_date<=? AND l.end_date>=?""", (today, today))
    return jsonify(year=year, employees=rows, on_leave_today=on_leave)

def _t(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S") if s else None

@app.get("/api/evaluation")
@roles_required(*ENG)
def evaluation():
    y = date.today().year
    d1, d2 = request.args.get("from") or f"{y}-01-01", request.args.get("to") or f"{y}-12-31"
    jobs = q_all("""SELECT w.id, w.work_needed, c.user_id,
        (SELECT MIN(created_at) FROM wr_events e WHERE e.wr_id=w.id AND e.event='started') AS started,
        (SELECT MAX(created_at) FROM wr_events e WHERE e.wr_id=w.id AND e.event='completion_requested') AS done_req,
        (SELECT MAX(created_at) FROM wr_events e WHERE e.wr_id=w.id AND e.event='completed') AS completed
        FROM work_requests w JOIN wr_crew c ON c.wr_id=w.id WHERE w.status='completed'""")
    per_job = {}
    for r in jobs:
        a, b = _t(r["started"]), _t(r["done_req"])
        r["hours"] = (b - a).total_seconds() / 3600 if a and b and b >= a else None
        per_job[r["id"]] = (r["work_needed"], r["hours"])
    med = {}   # typical duration per type of work, from all completed jobs
    for wn in {w for w, _ in per_job.values()}:
        hs = [h for w, h in per_job.values() if w == wn and h is not None]
        if hs:
            med[wn] = statistics.median(hs)
    stats = {}
    for r in jobs:
        if not (r["completed"] and d1 <= r["completed"][:10] <= d2):
            continue
        s = stats.setdefault(r["user_id"], {"jobs": 0, "speed": []})
        s["jobs"] += 1
        h, m = r["hours"], med.get(r["work_needed"])
        if h is not None and m is not None:
            s["speed"].append(1 if h <= m else m / h)
    leave = {(r["user_id"], r["type"]): r["d"] for r in q_all(
        """SELECT user_id, type, SUM(days) d FROM leave_requests WHERE status='approved'
           AND start_date>=? AND start_date<=? GROUP BY user_id, type""", (d1, d2))}
    top = max([s["jobs"] for s in stats.values()] or [1])
    out = []
    for u in q_all("SELECT id,name,role FROM users WHERE active=1 AND role IN ('technician','assistant')"):
        s = stats.get(u["id"], {"jobs": 0, "speed": []})
        ann, sick = leave.get((u["id"], "annual"), 0), leave.get((u["id"], "sick"), 0)
        comp = {
            "work": EVAL_W["work"] * s["jobs"] / top,
            "speed": EVAL_W["speed"] * (sum(s["speed"]) / len(s["speed"]) if s["speed"] else 0),
            "annual": EVAL_W["annual"] * max(0, 1 - ann / EVAL_CAP["annual"]),
            "sick": EVAL_W["sick"] * max(0, 1 - sick / EVAL_CAP["sick"]),
        }
        out.append({**u, "jobs_completed": s["jobs"], "annual_days": ann, "sick_days": sick,
                    "components": {k: round(v, 1) for k, v in comp.items()},
                    "score": round(sum(comp.values()), 1)})
    out.sort(key=lambda x: -x["score"])
    return jsonify(**{"from": d1, "to": d2}, weights=EVAL_W, caps=EVAL_CAP, employees=out)

# ================= step 5: PM schedules, reports, overview =================
import io
from flask import send_file

# ---------- preventive maintenance (superintendent sets plans/time, engineers add instruments) ----------
def pm_check(j, full):
    if full and not all(k in j for k in ("name", "job_title", "work_needed", "interval_days", "next_due")):
        return "name, job_title, work_needed, interval_days and next_due are required"
    if ("job_title" in j and not opt_ok("job_title", j["job_title"])) or \
       ("work_needed" in j and not opt_ok("work_needed", j["work_needed"])):
        return "job title and work needed must be chosen from the lists"
    try:
        if "interval_days" in j and int(j["interval_days"]) < 1:
            return "interval_days must be at least 1"
        if "next_due" in j:
            date.fromisoformat(j["next_due"])
    except (TypeError, ValueError):
        return "interval_days must be a number and next_due must look like 2026-11-15"
    if "time_of_day" in j and not parse_dt(f"2000-01-01 {j['time_of_day']}"):
        return "time_of_day must look like 07:00"
    return None

@app.get("/api/pm/plans")
@login_required
def list_pm():
    rows = q_all("""SELECT p.*, (SELECT group_concat(instrument_tag,',') FROM pm_instruments
        WHERE plan_id=p.id) AS tags FROM pm_plans p ORDER BY p.next_due""")
    for r in rows:
        r["instruments"] = r.pop("tags").split(",") if r["tags"] else []
    return jsonify(plans=rows)

@app.post("/api/pm/plans")
@roles_required("superintendent")
def add_pm():
    j = request.get_json(silent=True) or {}
    m = pm_check(j, True)
    if m:
        return err(m)
    cur = db().execute("""INSERT INTO pm_plans(name,job_title,work_needed,interval_days,next_due,
        time_of_day) VALUES(?,?,?,?,?,?)""", (j["name"], j["job_title"], j["work_needed"],
        int(j["interval_days"]), j["next_due"], j.get("time_of_day") or "07:00"))
    db().commit()
    return jsonify(id=cur.lastrowid), 201

@app.patch("/api/pm/plans/<int:pid>")
@roles_required("superintendent")
def edit_pm(pid):
    j = request.get_json(silent=True) or {}
    s = {k: j[k] for k in ("name", "job_title", "work_needed", "interval_days", "next_due",
                           "time_of_day", "active") if k in j}
    m = pm_check(s, False) if s else "nothing to update"
    if m:
        return err(m)
    if "active" in s:
        s["active"] = int(bool(s["active"]))
    cur = db().execute(f"UPDATE pm_plans SET {','.join(k + '=?' for k in s)} WHERE id=?",
                       (*s.values(), pid))
    db().commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)

@app.post("/api/pm/plans/<int:pid>/instruments")
@roles_required("engineer", "superintendent")
def pm_add_instruments(pid):
    if not q_one("SELECT 1 x FROM pm_plans WHERE id=?", (pid,)):
        return err("not found", 404)
    tags = [str(t).strip().upper() for t in ((request.get_json(silent=True) or {}).get("tags") or [])]
    if not tags:
        return err("tags is required")
    for t in tags:
        if not q_one("SELECT 1 x FROM instruments WHERE tag=? AND active=1", (t,)):
            return err(f"instrument {t} not found")
    for t in tags:
        db().execute("INSERT OR IGNORE INTO pm_instruments VALUES(?,?)", (pid, t))
    db().commit()
    return jsonify(ok=True)

@app.delete("/api/pm/plans/<int:pid>/instruments/<tag>")
@roles_required("engineer", "superintendent")
def pm_remove_instrument(pid, tag):
    cur = db().execute("DELETE FROM pm_instruments WHERE plan_id=? AND instrument_tag=?",
                       (pid, tag.upper()))
    db().commit()
    return jsonify(ok=True) if cur.rowcount else err("not found", 404)

@app.get("/api/pm/due")
@login_required
def pm_due():
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        return err("days must be a number")
    lim = (date.today() + timedelta(days=days)).isoformat()
    return jsonify(plans=q_all("SELECT * FROM pm_plans WHERE active=1 AND next_due<=? ORDER BY next_due",
                               (lim,)))

@app.post("/api/pm/plans/<int:pid>/generate")
@roles_required("superintendent")
def generate_pm(pid):
    """Issues one work request per instrument. Pass tags to run only some instruments
    (e.g. density meters with a density leader); next_due advances only on a full run."""
    p = q_one("SELECT * FROM pm_plans WHERE id=? AND active=1", (pid,))
    if not p:
        return err("not found", 404)
    j = request.get_json(silent=True) or {}
    leader = q_one("SELECT * FROM users WHERE id=? AND is_leader=1 AND active=1", (j.get("leader_id"),))
    if not leader:
        return err("a team leader is required")
    partial = bool(j.get("tags"))
    tags = [str(t).upper() for t in j["tags"]] if partial else \
        [r["instrument_tag"] for r in q_all("SELECT instrument_tag FROM pm_instruments WHERE plan_id=?", (pid,))]
    if not tags:
        return err("this plan has no instruments")
    base = date.fromisoformat(p["next_due"])
    due = base
    while due.weekday() in (4, 5):   # move Fri/Sat to Sunday
        due += timedelta(days=1)
    dt = parse_dt(f"{due} {p['time_of_day']}")
    made, skipped = [], []
    for t in tags:
        if t.startswith("DNT") and not leader["is_density"]:
            skipped.append(t)
            continue
        cur = db().execute("""INSERT INTO work_requests(priority,instrument_tag,job_title,work_needed,
            details,scheduled_at,status,leader_id,created_by) VALUES('normal',?,?,?,?,?,'issued',?,?)""",
            (t, p["job_title"], p["work_needed"], f"PM plan: {p['name']}", dt.strftime(FMT),
             leader["id"], g.user["id"]))
        code = f"WR-{datetime.now().year}-{cur.lastrowid:04d}"
        db().execute("UPDATE work_requests SET code=? WHERE id=?", (code, cur.lastrowid))
        log_wr(cur.lastrowid, "issued", f"preventive maintenance: {p['name']}")
        made.append(code)
    if made:
        notify([leader["id"]], f"{len(made)} PM work requests issued for {p['name']}")
    if not partial:
        db().execute("UPDATE pm_plans SET next_due=?, last_generated=? WHERE id=?",
                     ((base + timedelta(days=p["interval_days"])).isoformat(),
                      date.today().isoformat(), pid))
    db().commit()
    return jsonify(created=made, skipped_need_density_leader=skipped)

# ---------- daily report (Excel) ----------
STATUS_LABEL = {"issued": "Issued", "assigned": "Assigned", "in_progress": "In progress",
                "completion_requested": "Completion requested", "completed": "Completed",
                "on_hold": "On hold"}

@app.get("/api/reports/daily")
@roles_required(*ENG)
def daily_report():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return err("install openpyxl on the server: pip install openpyxl", 500)
    try:
        d = date.fromisoformat(request.args.get("date") or date.today().isoformat())
    except ValueError:
        return err("date must look like 2026-11-11")
    ds = d.isoformat()
    rows = q_all("""SELECT w.*, i.area, l.name AS leader_name FROM work_requests w
        LEFT JOIN instruments i ON i.tag=w.instrument_tag JOIN users l ON l.id=w.leader_id
        WHERE w.status<>'cancelled' AND (substr(w.scheduled_at,1,10)=? OR
              (w.status IN ('in_progress','on_hold') AND substr(w.scheduled_at,1,10)<?))
        ORDER BY w.scheduled_at""", (ds, ds))
    areas = [r["value"] for r in q_all("SELECT value FROM options WHERE category='area' ORDER BY sort,value")]
    groups, other = {a: [] for a in areas}, []
    for r in rows:
        (groups[r["area"]] if r["area"] in groups else other).append(r)
    wb = Workbook()
    ws = wb.active
    ws.title = "Daily report"
    ws.merge_cells("A1:D1")
    ws["A1"] = f"CCP's Instrument department daily work report {d:%d-%m-%Y}"
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Assignment", "Assigned to", "Status", "Notes"])
    for c in ws[2]:
        c.font = Font(bold=True)
    for plant, items in list(groups.items()) + [("OTHER", other)]:
        if not items:
            continue
        ws.append([plant])
        r = ws.max_row
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        ws.cell(r, 1).font = Font(bold=True)
        ws.cell(r, 1).fill = PatternFill("solid", fgColor="D9E1F2")
        for w in items:
            crew = ", ".join(x["name"] for x in q_all(
                "SELECT u.name FROM wr_crew c JOIN users u ON u.id=c.user_id WHERE c.wr_id=?", (w["id"],)))
            notes = "; ".join(n["text"] for n in q_all(
                "SELECT text FROM wr_notes WHERE wr_id=? ORDER BY id DESC LIMIT 3", (w["id"],)))
            ws.append([f"{w['instrument_tag']} - {w['work_needed']}",
                       crew or f"{w['leader_name']} (leader)",
                       STATUS_LABEL.get(w["status"], w["status"]), notes])
    for col, wd in zip("ABCD", (45, 30, 22, 50)):
        ws.column_dimensions[col].width = wd
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"daily_report_{ds}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- weekly report (PowerPoint) ----------
IMAGE_EXT = ("png", "jpg", "jpeg", "gif")

def week_start_arg(s):
    """Sunday of the given week (default: the current week), or None if the date is not a Sunday."""
    if s:
        d = parse_dt(s + " 00:00")
        return d if d and d.weekday() == 6 else None
    t = date.today()
    return datetime.combine(t - timedelta(days=(t.weekday() + 1) % 7), datetime.min.time())

def first_image(wid):
    for f in q_all("SELECT stored FROM wr_files WHERE wr_id=? ORDER BY id", (wid,)):
        if f["stored"].rsplit(".", 1)[-1] in IMAGE_EXT:
            return os.path.join(UPLOAD_DIR, f["stored"])
    return None

def add_fit(slide, path, x, y, w, h):
    pic = slide.shapes.add_picture(path, x, y)
    r = min(w / pic.width, h / pic.height)
    pic.width, pic.height = int(pic.width * r), int(pic.height * r)
    pic.left = x + (w - pic.width) // 2

def build_weekly_pptx(path, week_no, ws, items):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank)
    tf = s.shapes.add_textbox(Inches(1), Inches(2.3), Inches(11.3), Inches(3)).text_frame
    tf.word_wrap = True
    lines = ["CCPs Instrument. Major jobs", f"Week No. {week_no:02d}",
             f"{ws:%d.%m.%Y} - {ws + timedelta(days=4):%d.%m.%Y}"]
    for i, t in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text, run.font.size, run.font.bold = t, Pt(40 if i == 0 else 28), i == 0
    per = 4
    for k in range(0, len(items), per):
        s = prs.slides.add_slide(blank)
        run = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12), Inches(0.8)) \
            .text_frame.paragraphs[0].add_run()
        run.text, run.font.size, run.font.bold = "CCPs INST. Major Activities", Pt(30), True
        lst = s.shapes.add_textbox(Inches(0.5), Inches(1.3), Inches(6), Inches(5.6)).text_frame
        lst.word_wrap = True
        for idx, it in enumerate(items[k:k + per]):
            n = k + idx + 1
            p = lst.paragraphs[0] if idx == 0 else lst.add_paragraph()
            p.space_after = Pt(14)
            run = p.add_run()
            run.text, run.font.size = f"{n}. {it['instrument_tag']} - {it['work_needed']}", Pt(20)
            x, y = Inches(7 + (idx % 2) * 3.2), Inches(1.3 + (idx // 2) * 3.0)
            if it["photo"]:
                try:
                    add_fit(s, it["photo"], x, y, Inches(3.0), Inches(2.4))
                except Exception:
                    pass   # unreadable image: leave the slot empty
            cap = s.shapes.add_textbox(x, y + Inches(2.45), Inches(3.0), Inches(0.4)).text_frame
            cap.word_wrap = True
            run = cap.paragraphs[0].add_run()
            run.text, run.font.size = f"{n}. {it['instrument_tag']}", Pt(12)
    prs.save(path)

@app.get("/api/weekly-report/candidates")
@roles_required(*ENG)
def weekly_candidates():
    ws = week_start_arg(request.args.get("week_start"))
    if not ws:
        return err("week_start must be a Sunday, like 2026-11-15")
    rows = q_all("""SELECT w.id,w.code,w.instrument_tag,i.area,w.job_title,w.work_needed,
        w.scheduled_at,w.status,(SELECT COUNT(*) FROM wr_files f WHERE f.wr_id=w.id) AS files
        FROM work_requests w LEFT JOIN instruments i ON i.tag=w.instrument_tag
        WHERE w.status<>'cancelled' AND ((w.scheduled_at>=? AND w.scheduled_at<?) OR
              (substr(w.created_at,1,10)>=? AND substr(w.created_at,1,10)<?))
        ORDER BY w.scheduled_at""",
        (ws.strftime(FMT), (ws + timedelta(days=5)).strftime(FMT),
         ws.strftime("%Y-%m-%d"), (ws + timedelta(days=7)).strftime("%Y-%m-%d")))
    return jsonify(week_start=ws.strftime("%Y-%m-%d"), requests=rows)

@app.post("/api/weekly-report")
@roles_required(*ENG)
def make_weekly_report():
    try:
        import pptx  # noqa: F401
    except ImportError:
        return err("install python-pptx on the server: pip install python-pptx", 500)
    j = request.get_json(silent=True) or {}
    ws = week_start_arg(j.get("week_start"))
    if not ws:
        return err("week_start must be a Sunday, like 2026-11-15")
    if not isinstance(j.get("request_ids"), list) or not j["request_ids"]:
        return err("request_ids is required: choose the jobs to include")
    items = []
    for i in j["request_ids"]:
        r = q_one("SELECT id,instrument_tag,work_needed FROM work_requests WHERE id=? AND status<>'cancelled'", (i,))
        if r:
            r["photo"] = first_image(r["id"])
            items.append(r)
    if not items:
        return err("none of the chosen requests were found")
    try:
        wn = int(j.get("week_no") or ws.strftime("%U"))
    except ValueError:
        return err("week_no must be a number")
    stored = secrets.token_hex(16) + ".pptx"
    build_weekly_pptx(os.path.join(UPLOAD_DIR, stored), wn, ws, items)
    name = f"Instrument_Report_CCPs_week_{wn:02d}.pptx"
    cur = db().execute("INSERT INTO generated_reports(kind,period,filename,stored,created_by) "
                       "VALUES('weekly',?,?,?,?)", (ws.strftime("%Y-%m-%d"), name, stored, g.user["id"]))
    db().commit()
    return jsonify(id=cur.lastrowid, filename=name), 201

@app.get("/api/reports")
@roles_required(*ENG)
def list_reports():
    return jsonify(reports=q_all("""SELECT r.id,r.kind,r.period,r.filename,r.created_at,u.name AS by_name
        FROM generated_reports r LEFT JOIN users u ON u.id=r.created_by ORDER BY r.id DESC"""))

@app.get("/api/reports/<int:rid>/download")
@roles_required(*ENG)
def download_report_file(rid):
    r = q_one("SELECT * FROM generated_reports WHERE id=?", (rid,))
    if not r:
        return err("not found", 404)
    return send_from_directory(UPLOAD_DIR, r["stored"], as_attachment=True, download_name=r["filename"])

# ---------- current overview (dashboard counts) ----------
@app.get("/api/overview")
@roles_required(*ENG)
def overview():
    check_overdue()
    n = lambda sql, a=(): q_one(sql, a)["n"]
    today = date.today().isoformat()
    appr = [k for k, v in APPROVER.items() if g.user["role"] in v]
    return jsonify(
        requests_by_status={r["status"]: r["n"] for r in
                            q_all("SELECT status, COUNT(*) n FROM work_requests GROUP BY status")},
        overdue=n("SELECT COUNT(*) n FROM work_requests WHERE status IN ('issued','assigned') "
                  "AND scheduled_at<?", (datetime.now().strftime(FMT),)),
        open_emergency=n("SELECT COUNT(*) n FROM work_requests WHERE priority='emergency' "
                         "AND status NOT IN ('completed','cancelled')"),
        low_stock=n("""SELECT COUNT(*) n FROM (SELECT s.min_qty, s.qty_on_hand - COALESCE((SELECT SUM(qty)
                       FROM reservations r WHERE r.item_id=s.id AND r.status='active'),0) AS av
                       FROM stock_items s WHERE s.active=1) WHERE av<=min_qty"""),
        purchase_pending=n("SELECT COUNT(*) n FROM purchase_requests WHERE status='pending'"),
        leave_to_decide=n(f"""SELECT COUNT(*) n FROM leave_requests l JOIN users e ON e.id=l.user_id
            WHERE l.status='pending' AND l.user_id<>? AND e.role IN ({','.join('?' * len(appr)) or "''"})""",
            (g.user["id"], *appr)) if appr else 0,
        on_leave_today=n("SELECT COUNT(*) n FROM leave_requests WHERE status='approved' "
                         "AND start_date<=? AND end_date>=?", (today, today)),
        pm_due_7_days=n("SELECT COUNT(*) n FROM pm_plans WHERE active=1 AND next_due<=?",
                        ((date.today() + timedelta(days=7)).isoformat(),)))

@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")

init_db()

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8100")))
