from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
import sqlite3
from datetime import datetime
import csv
import io
import os
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, 'database.db')

app = Flask(__name__)
app.secret_key = 'CHANGE_THIS_TO_A_RANDOM_SECRET'  # change in production

# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','seller')),
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        stock INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER,
        items TEXT,
        total REAL,
        created_at TEXT,
        FOREIGN KEY(seller_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()

def create_default_accounts():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                    ("admin", generate_password_hash("admin123"), "admin", datetime.utcnow().isoformat()))
    except:
        pass
    for i in range(1,5):
        uname = f"seller{i}"
        try:
            cur.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                        (uname, generate_password_hash("1234"), "seller", datetime.utcnow().isoformat()))
        except:
            pass
    conn.commit()
    conn.close()

# init
if not os.path.exists(DB_PATH):
    init_db()
create_default_accounts()

# ---------------- Auth helpers ----------------
def current_user():
    if 'user_id' not in session:
        return None
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id,username,role FROM users WHERE id=?", (session['user_id'],))
    u = cur.fetchone()
    conn.close()
    return u

def login_user(user_row):
    session['user_id'] = user_row['id']

def logout_user():
    session.pop('user_id', None)

# ---------------- Routes ----------------
@app.route('/')
def index():
    u = current_user()
    if not u:
        return redirect(url_for('login'))
    if u['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('pos'))

# ---------- AUTH ----------
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            login_user(user)
            flash("Kirish muvaffaqiyatli", "success")
            return redirect(url_for('index'))
        else:
            flash("Login yoki parol noto'g'ri", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# ---------- ADMIN: dashboard, products, users, sales, export ----------
@app.route('/admin')
def admin_dashboard():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT s.id, s.total, s.created_at, u.username as seller FROM sales s LEFT JOIN users u ON s.seller_id=u.id ORDER BY s.id DESC LIMIT 50")
    sales = cur.fetchall()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.execute("SELECT id,username,role FROM users ORDER BY id")
    users = cur.fetchall()
    conn.close()
    return render_template('admin.html', sales=sales, products=products, users=users)

# Products CRUD
@app.route('/admin/products/new', methods=['GET','POST'])
def admin_product_new():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        sku = request.form.get('sku','').strip()
        name = request.form['name'].strip()
        description = request.form.get('description','').strip()
        price = float(request.form['price'] or 0)
        stock = int(request.form.get('stock') or 0)
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO products (sku,name,description,price,stock,created_at) VALUES (?,?,?,?,?,?)",
                    (sku,name,description,price,stock,datetime.utcnow().isoformat()))
        conn.commit(); conn.close()
        return redirect(url_for('admin_dashboard'))
    return render_template('product_form.html', product=None)

@app.route('/admin/products/edit/<int:pid>', methods=['GET','POST'])
def admin_product_edit(pid):
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id=?", (pid,))
    product = cur.fetchone()
    if not product:
        conn.close(); return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        sku = request.form.get('sku','').strip()
        name = request.form['name'].strip()
        description = request.form.get('description','').strip()
        price = float(request.form['price'] or 0)
        stock = int(request.form.get('stock') or 0)
        cur.execute("UPDATE products SET sku=?,name=?,description=?,price=?,stock=? WHERE id=?",
                    (sku,name,description,price,stock,pid))
        conn.commit(); conn.close()
        return redirect(url_for('admin_dashboard'))
    conn.close()
    return render_template('product_form.html', product=product)

@app.route('/admin/products/delete/<int:pid>', methods=['POST'])
def admin_product_delete(pid):
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))

# Users management (create new seller)
@app.route('/admin/users/new', methods=['GET','POST'])
def admin_user_new():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role = request.form.get('role','seller')
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?,?,?)",
                    (username, generate_password_hash(password), role, datetime.utcnow().isoformat()))
        conn.commit(); conn.close()
        return redirect(url_for('admin_dashboard'))
    return render_template('user_form.html', user=None)

@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
def admin_user_delete(uid):
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=? AND role!='admin'", (uid,))
    conn.commit(); conn.close()
    return redirect(url_for('admin_dashboard'))

# Sales export
@app.route('/admin/export/sales')
def admin_export_sales():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT s.id, s.created_at, u.username as seller, s.total, s.items FROM sales s LEFT JOIN users u ON s.seller_id=u.id ORDER BY s.id")
    rows = cur.fetchall()
    conn.close()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['id','created_at','seller','total','items'])
    for r in rows:
        cw.writerow([r['id'], r['created_at'], r['seller'], r['total'], r['items']])
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/csv', download_name='sales_export.csv', as_attachment=True)

# ---------- POS for sellers ----------
@app.route('/pos', methods=['GET','POST'])
def pos():
    u = current_user()
    if not u or u['role'] != 'seller':
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY name")
    products = cur.fetchall()
    if request.method == 'POST':
        pid = int(request.form['product_id'])
        qty = int(request.form.get('qty',1))
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        prod = cur.fetchone()
        if not prod:
            flash("Mahsulot topilmadi", "danger")
        else:
            total = float(prod['price']) * qty
            items_text = f"{pid}:{qty}"
            cur.execute("INSERT INTO sales (seller_id, items, total, created_at) VALUES (?,?,?,?)",
                        (u['id'], items_text, total, datetime.utcnow().isoformat()))
            cur.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, pid))
            conn.commit()
            flash("Sotuv muvaffaqiyatli yozildi", "success")
    cur.execute("SELECT * FROM sales WHERE seller_id=? ORDER BY id DESC LIMIT 10", (u['id'],))
    sales = cur.fetchall()
    conn.close()
    return render_template('pos.html', products=products, sales=sales)

# API-ish: quick product search (used by JS)
@app.route('/api/products')
def api_products():
    q = request.args.get('q','').strip()
    conn = get_db(); cur = conn.cursor()
    if q:
        cur.execute("SELECT * FROM products WHERE name LIKE ? OR sku LIKE ? ORDER BY id DESC", (f'%{q}%', f'%{q}%'))
    else:
        cur.execute("SELECT * FROM products ORDER BY id DESC LIMIT 200")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({'id': r['id'], 'name': r['name'], 'price': r['price'], 'stock': r['stock']})
    return {"products": out}

@app.route('/setup')
def setup_info():
    return {
        "note":"Remove /setup in production",
        "admin":"admin / admin123",
        "sellers":["seller1..seller4 with password 1234"]
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
