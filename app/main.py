import os, uuid, datetime,json
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

# -------------------- Setup --------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_folder = os.path.join(project_root, "templates")
app = Flask(__name__, template_folder=template_folder)

# -------- Config --------
load_dotenv()

GOOGLE_SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
creds_json = os.getenv("GOOGLE_APP_CREDS_JSON")
creds_dict = json.loads(creds_json)
#GOOGLE_APP_CREDS = os.getenv("GOOGLE_APP_CREDS")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY","allaboutourpeppers")

if not GOOGLE_SPREADSHEET_ID:
    raise RuntimeError("SPREADSHEET_ID is required in .env")
#if not GOOGLE_APP_CREDS or not os.path.exists(GOOGLE_APP_CREDS):
    raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS path invalid or missing.")

if not creds_dict:
    raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS path invalid or missing.")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
#creds = Credentials.from_service_account_file(GOOGLE_APP_CREDS, scopes=SCOPES)
gc = gspread.authorize(creds)
ss = gc.open_by_key(GOOGLE_SPREADSHEET_ID)

# -------------------- Sheet Utilities --------------------
def get_or_create_ws(sheetname, headers):
    try:
        ws = ss.worksheet(sheetname)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=sheetname, rows=1000, cols=len(headers))
        ws.append_row(headers)
        return ws
    # ensure headers
    existing = ws.row_values(1)
    if [h.lower() for h in existing] != [h.lower() for h in headers]:
        if existing:
            ws.delete_rows(1)
        ws.insert_row(headers, 1)
    return ws

# -------------------- Headers --------------------
CUSTOMER_SHEET_HEADERS = ["username","email","password_hash","role","created_at"]
PRODUCE_SHEET_HEADERS = ["item","unit_price"]
ORDERS_SHEET_HEADERS = ["order_id","username","item","quantity","unit_price","line_total","created_at","updated_at"]

customer_ws = get_or_create_ws("customers", CUSTOMER_SHEET_HEADERS)
produce_ws = get_or_create_ws("produce", PRODUCE_SHEET_HEADERS)
orders_ws = get_or_create_ws("orders", ORDERS_SHEET_HEADERS)

# -------------------- Helpers --------------------
def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat() + "Z"

def ws_rows_to_dicts(ws, headers):
    vals = ws.get_all_values()
    if not vals:
        return []
    hdr = [h.strip() for h in vals[0]]
    rows = []
    for r in vals[1:]:
        d = {}
        for i, h in enumerate(hdr):
            d[h] = r[i] if i < len(r) else ""
        rows.append(d)
    return rows

def index_rows_by(ws, key, headers):
    rows = ws.get_all_values()
    if not rows:
        return {}, {}
    hdr = [h.strip() for h in rows[0]]
    idx = {h:i for i,h in enumerate(hdr)}
    data = {}
    for ri, r in enumerate(rows[1:], start=2):
        k = r[idx[key]] if idx.get(key) is not None and idx[key] < len(r) else ""
        data[k] = (ri, r)
    return data, idx

def read_produce_catalog():
    items = ws_rows_to_dicts(produce_ws, PRODUCE_SHEET_HEADERS)
    return {row["item"]: float(row["unit_price"] or 0) for row in items if row.get("item")}

def compute_line_total(item, qty):
    catalog = read_produce_catalog()
    unit = float(catalog.get(item, 0))
    qty = float(qty)
    return unit, qty * unit

# -------------------- Flask Setup --------------------
app.secret_key = FLASK_SECRET_KEY
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, username, role="Customer"):
        self.id = username
        self.role = role

    @property
    def is_admin(self):
        return self.role.lower() == "admin"

@login_manager.user_loader
def load_user(username):
    rows = ws_rows_to_dicts(customer_ws, CUSTOMER_SHEET_HEADERS)
    for u in rows:
        if u["username"].lower() == username.lower():
            return User(u["username"], u.get("role","Customer"))
    return None

@app.context_processor
def inject_now():
    return {'datetime': datetime.datetime}

# -------------------- Routes: Auth --------------------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip().lower()
        pw = request.form.get("password","")
        confirm_pw = request.form.get("confirm_password","")

        if not username or not pw or not confirm_pw:
            flash("Username and password required","error")
            return redirect(url_for("register"))
        if pw != confirm_pw:
            flash("Passwords do not match","error")
            return redirect(url_for("register"))

        existing = ws_rows_to_dicts(customer_ws, CUSTOMER_SHEET_HEADERS)
        if any(u["username"].lower() == username.lower() for u in existing):
            flash("Username already taken","error")
            return redirect(url_for("register"))

        role = "Customer"  # default role
        customer_ws.append_row([username, email, generate_password_hash(pw), role, now_iso()])
        flash("Registration successful. Please login.","success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        pw = request.form.get("password","")
        rows = ws_rows_to_dicts(customer_ws, CUSTOMER_SHEET_HEADERS)
        for u in rows:
            if u["username"].lower() == username.lower():
                if check_password_hash(u["password_hash"], pw):
                    user = User(u["username"], u.get("role","Customer"))
                    login_user(user)
                    flash("Logged in","success")
                    return redirect(url_for("index"))
                break
        flash("Invalid credentials","error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out","success")
    return redirect(url_for("login"))

# -------------------- Routes: Orders --------------------
@app.route("/", methods=["GET"])
@login_required
def index():
    catalog = read_produce_catalog()
    my_orders = [o for o in ws_rows_to_dicts(orders_ws, ORDERS_SHEET_HEADERS) if o["username"].lower() == current_user.id.lower()]
    total_amount = sum(float(o.get("line_total", 0) or 0) for o in my_orders)
    my_orders.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return render_template("index.html", catalog=catalog, orders=my_orders, total_amount=total_amount)

@app.route("/orders", methods=["POST"])
@login_required
def create_order():
    item = request.form.get("item","")
    qty = request.form.get("quantity","1")
    if not item:
        flash("Item required","error")
        return redirect(url_for("index"))
    try:
        unit, total = compute_line_total(item, qty)
    except Exception:
        flash("Invalid quantity or item","error")
        return redirect(url_for("index"))

    now = now_iso()
    orders_ws.append_row([
        str(uuid.uuid4()), current_user.id, item, str(int(float(qty))), f"{unit:.2f}", f"{total:.2f}", now, now
    ])
    flash("Order saved","success")
    return redirect(url_for("index"))

@app.route("/orders/<order_id>/edit", methods=["POST"])
@login_required
def edit_order(order_id):
    action = request.form.get("action")
    row_map, idx = index_rows_by(orders_ws, "order_id", ORDERS_SHEET_HEADERS)
    if order_id not in row_map:
        flash("Order not found","error"); return redirect(url_for("index"))
    row_num, raw = row_map[order_id]
    owner = raw[idx["username"]]
    if (owner or "").lower() != current_user.id.lower() and not current_user.is_admin:
        flash("Not allowed","error"); return redirect(url_for("index"))

    d = {h: (raw[idx[h]] if idx[h]<len(raw) else "") for h in ORDERS_SHEET_HEADERS}
    qty = int(d.get("quantity","1") or "1")
    if action == "inc":
        qty += 1
    elif action == "dec":
        qty = max(1, qty-1)

    unit, total = compute_line_total(d.get("item",""), qty)
    d["quantity"] = str(qty)
    d["unit_price"] = f"{unit:.2f}"
    d["line_total"] = f"{total:.2f}"
    d["updated_at"] = now_iso()

    new_row = [d.get(h,"") for h in ORDERS_SHEET_HEADERS]
    orders_ws.update(f"A{row_num}:H{row_num}", [new_row])
    flash("Order updated","success")
    return redirect(url_for("index"))

@app.route("/orders/<order_id>/delete", methods=["POST"])
@login_required
def delete_order(order_id):
    row_map, idx = index_rows_by(orders_ws, "order_id", ORDERS_SHEET_HEADERS)
    if order_id not in row_map:
        flash("Order not found","error"); return redirect(url_for("index"))
    row_num, raw = row_map[order_id]
    owner = raw[idx["username"]]
    if (owner or "").lower() != current_user.id.lower() and not current_user.is_admin:
        flash("Not allowed","error"); return redirect(url_for("index"))
    orders_ws.delete_rows(row_num)
    flash("Order deleted","success")
    return redirect(url_for("index"))

# -------------------- Routes: Admin --------------------
@app.route("/admin/report")
@login_required
def admin_report():
    if not current_user.is_admin:
        flash("Admin only","error")
        return redirect(url_for("index"))
    orders = ws_rows_to_dicts(orders_ws, ORDERS_SHEET_HEADERS)
    for o in orders:
        o["quantity"] = int(float(o.get("quantity","0") or "0"))
        o["unit_price"] = float(o.get("unit_price","0") or "0")
        o["line_total"] = float(o.get("line_total","0") or "0")
    totals_by_user = {}
    for o in orders:
        totals_by_user[o["username"]] = totals_by_user.get(o["username"], 0.0) + float(o["line_total"])
    grand_total = sum(totals_by_user.values())
    orders.sort(key=lambda x: (x.get("username",""), x.get("created_at","")), reverse=False)
    return render_template("admin_report.html", orders=orders, totals_by_customer=totals_by_user, grand_total=grand_total)

if __name__ == "__main__":
    app.logger.debug("Templates folder: %s", app.template_folder)
    app.run(debug=True,use_reloader=False)
