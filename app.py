from datetime import datetime, date
from flask import Flask, request, render_template, redirect
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production")  
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def init_db():
    conn = sqlite3.connect(os.path.join(BASE_DIR, 'warehouse.db'))
    conn.execute("""CREATE TABLE IF NOT EXISTS products (
        sku TEXT PRIMARY KEY NOT NULL,
        name TEXT NOT NULL,
        brand TEXT NOT NULL,
        category TEXT NOT NULL,
        unit TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS warehouses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        transit_days INT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS batches (
        batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_sku TEXT NOT NULL,
        warehouse_id INT NOT NULL DEFAULT 1,
        quantity INT NOT NULL,
        expiration_date DATE NOT NULL,
        received_date DATE NOT NULL,
        status TEXT NOT NULL DEFAULT 'in_stock'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sales (
        sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER NOT NULL,
        product_sku TEXT NOT NULL,
        quantity_sold INT NOT NULL,
        sale_date DATE NOT NULL,
        warehouse_id INT NOT NULL DEFAULT 1
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS transfers (
        transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_sku TEXT NOT NULL,
        quantity_transferred INT NOT NULL,
        transfer_date DATE NOT NULL,
        source_warehouse_id INT NOT NULL,
        destination_warehouse_id INT NOT NULL
    )""")
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_db():
    conn = sqlite3.connect(os.path.join(BASE_DIR, 'warehouse.db'))
    conn.row_factory = sqlite3.Row
    return conn

# ── HOME ──────────────────────────────────────────────
@app.route("/")
def home():
    return redirect("/dashboard")

# ── DASHBOARD ─────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    conn = get_db()
    batches = conn.execute("""
        SELECT b.*, p.name, p.brand
        FROM batches b
        JOIN products p ON b.product_sku = p.sku
        WHERE b.status = 'in_stock'
        ORDER BY b.expiration_date ASC
    """).fetchall()
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_batches  = conn.execute("SELECT COUNT(*) FROM batches WHERE status='in_stock'").fetchone()[0]
    total_sold     = conn.execute("SELECT COALESCE(SUM(quantity_sold),0) FROM sales").fetchone()[0]
    conn.close()

    today = date.today()
    categorized = {"expired": [], "critical": [], "warning": [], "safe": []}

    for batch in batches:
        expiry = datetime.strptime(batch["expiration_date"], "%Y-%m-%d").date()
        days_left = (expiry - today).days
        b = dict(batch)
        b["days_left"] = days_left
        if days_left < 0:
            categorized["expired"].append(b)
        elif days_left <= 3:
            categorized["critical"].append(b)
        elif days_left <= 7:
            categorized["warning"].append(b)
        else:
            categorized["safe"].append(b)

    return render_template("dashboard.html", data=categorized, today=today,
                           total_products=total_products,
                           total_batches=total_batches,
                           total_sold=total_sold)

# ── PRODUCTS ──────────────────────────────────────────
@app.route("/products")
def view_products():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return render_template("products.html", products=products)

@app.route("/products/add", methods=["POST"])
def add_product():
    sku      = request.form.get("sku", "").strip()
    name     = request.form.get("name", "").strip()
    brand    = request.form.get("brand", "").strip()
    category = request.form.get("category", "").strip()
    unit     = request.form.get("unit", "").strip()

    if not all([sku, name, brand, category, unit]):
        return "All fields are required.", 400
    if len(sku) > 50:
        return "SKU too long.", 400

    conn = get_db()
    if conn.execute("SELECT sku FROM products WHERE sku=?", (sku,)).fetchone():
        conn.close()
        return "SKU already exists.", 400

    conn.execute("INSERT INTO products (sku,name,brand,category,unit) VALUES (?,?,?,?,?)",
                 (sku, name, brand, category, unit))
    conn.commit()
    conn.close()
    return redirect("/products")

# ── BATCHES ───────────────────────────────────────────
@app.route("/batches/add", methods=["POST"])
def add_batch():
    product_sku   = request.form.get("product_sku", "").strip()
    quantity      = request.form.get("quantity", "").strip()
    expiry_date   = request.form.get("expiry_date", "").strip()
    received_date = request.form.get("received_date", "").strip()

    if not all([product_sku, quantity, expiry_date, received_date]):
        return "All fields are required.", 400

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        return "Quantity must be a positive number.", 400
    try:
        datetime.strptime(expiry_date, "%Y-%m-%d")
        datetime.strptime(received_date, "%Y-%m-%d")
    except ValueError:
        return "Invalid date format.", 400
    

    conn = get_db()
    if not conn.execute("SELECT sku FROM products WHERE sku=?", (product_sku,)).fetchone():
        conn.close()
        return "Product SKU not found.", 404

    conn.execute("""INSERT INTO batches
        (product_sku, warehouse_id, quantity, expiration_date, received_date, status)
        VALUES (?,1,?,?,?,'in_stock')""",
        (product_sku, quantity, expiry_date, received_date))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

# ── SALES ─────────────────────────────────────────────
@app.route("/sales/add", methods=["POST"])
def add_sale():
    batch_id      = request.form.get("batch_id", "").strip()
    quantity_sold = request.form.get("quantity_sold", "").strip()
    sale_date     = request.form.get("sale_date", "").strip()

    if not all([batch_id, quantity_sold, sale_date]):
        return "All fields are required.", 400

    try:
        quantity_sold = int(quantity_sold)
        batch_id      = int(batch_id)
        if quantity_sold <= 0:
            raise ValueError
    except ValueError:
        return "Invalid input.", 400

    conn = get_db()
    batch = conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
    if not batch:
        conn.close()
        return "Batch not found.", 404
    if quantity_sold > batch["quantity"]:
        conn.close()
        return f"Only {batch['quantity']} units available.", 400

    new_qty = batch["quantity"] - quantity_sold
    new_status = "dispatched" if new_qty == 0 else "in_stock"

    conn.execute("UPDATE batches SET quantity=?, status=? WHERE batch_id=?",
                 (new_qty, new_status, batch_id))
    conn.execute("""INSERT INTO sales
        (batch_id, product_sku, quantity_sold, sale_date, warehouse_id)
        VALUES (?,?,?,?,1)""",
        (batch_id, batch["product_sku"], quantity_sold, sale_date))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

if __name__ == "__main__":
    init_db()
    app.run(debug=False)
