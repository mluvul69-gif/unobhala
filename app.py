import os
import sqlite3
import requests
from flask import Response
from datetime import datetime
from functools import wraps
from cryptography.fernet import Fernet

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()
# ---------------- CONFIG ----------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
KEY_PATH = os.path.join(BASE_DIR, "secret.key")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "mp4", "mov", "webm", "pdf"}



os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max upload
# ---------------- PAYFAST CONFIG ----------------
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
MERCHANT_ID = os.environ.get("PAYFAST_MERCHANT_ID")
MERCHANT_KEY = os.environ.get("PAYFAST_MERCHANT_KEY")
PAYFAST_PASSPHRASE = os.environ.get("PAYFAST_PASSPHRASE")
ADMIN_USERNAME= os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH= os.environ.get("ADMIN_PASSWORD_HASH")



PAYFAST_ITN_VALIDATION_URL = "https://sandbox.payfast.co.za/eng/query/validate"

PAYFAST_MODE = "sandbox"  # change to "live" later

if PAYFAST_MODE == "sandbox":
    PAYFAST_URL = "https://sandbox.payfast.co.za/eng/process"
    MERCHANT_ID = "10000100"
    MERCHANT_KEY = "46f0cd694581a"
else:
    PAYFAST_URL = "https://www.payfast.co.za/eng/process"
    MERCHANT_ID = "YOUR_LIVE_ID"
    MERCHANT_KEY = "YOUR_LIVE_KEY"

PASSPHRASE = ""  # add later if you enable it in PayFast dashboard

RETURN_URL = os.environ.get("RETURN_URL", "http://127.0.0.1:5000/payment/success")
CANCEL_URL = os.environ.get("CANCEL_URL", "http://127.0.0.1:5000/payment/cancel")
NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://127.0.0.1:5000/payment/itn")



ph = PasswordHasher()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
# ---------------- ENCRYPTION KEY (AUTO FIXED) ----------------

def load_or_create_key():
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_PATH, "wb") as f:
            f.write(key)
        return key

ENCRYPTION_KEY = load_or_create_key()
cipher = Fernet(ENCRYPTION_KEY)

def encrypt_text(text):
    if not text:
        return ""
    return cipher.encrypt(text.encode()).decode()

def decrypt_text(text):
    if not text:
        return ""
    return cipher.decrypt(text.encode()).decode()

# ---------------- ADMIN ----------------



# ---------------- DATABASE ----------------
def save_file(file):
    if file and file.filename != "":
        filename = secure_filename(file.filename)
        path = os.path.join("static/uploads", filename)
        file.save(path)
        return f"uploads/{filename}"
    return None

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # VERY IMPORTANT for cascade delete
    cursor.execute("PRAGMA foreign_keys = ON")

    # ---------------- POSTS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)



    # ---------------- POST MEDIA (images + video) ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS post_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        media_type TEXT NOT NULL,
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
    )
    """)

    # ---------------- PRODUCTS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL,
        image TEXT,
        category TEXT
    )
    """)

    # ---------------- ORDERS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        customer_phone TEXT,
        delivery_method TEXT,
        delivery_address TEXT,
        subtotal REAL,
        delivery_fee REAL,
        school_amount REAL,
        supplier_amount REAL,
        courier_amount REAL,
        total_amount REAL,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ---------------- ORDER ITEMS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        product_id INTEGER,
        quantity INTEGER,
        price REAL,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    )
    """)

    # ---------------- ADMISSIONS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        learner_name TEXT,
        parent_name TEXT,
        phone TEXT,
        email TEXT,
        grade TEXT,
        amount_paid TEXT,

        birth_certificate TEXT,
        parent_id_copy TEXT,
        latest_report TEXT,
        proof_of_residence TEXT,
        message TEXT,

        payment_status TEXT DEFAULT 'unpaid',
        payment_id TEXT,

        status TEXT DEFAULT 'new',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)


    conn.commit()
    conn.close()


def seed_products():
    conn = sqlite3.connect(DB_PATH)

    existing = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if existing > 0:
        conn.close()
        return

    products = [
        ("School Maths Book", "Grade 10 Mathematics official book", 120, "maths.jpg", "Books"),
        ("Physical Sciences", "Grade 10 Physical Sciences", 135, "phy.jpg", "Books"),
        ("Life Sciences", "Biology Grade 10", 128, "life.jpg", "Books"),
        ("English Handbook", "School English guide", 95, "eng.jpg", "Books"),
        ("Calculator", "Student scientific calculator", 180, "casio.jpg", "Stationery"),
        ("Maths Study Guide", "Extra maths practice", 85, "maths.jpg", "Books"),
    ]

    conn.executemany("""
        INSERT INTO products (name, description, price, image, category)
        VALUES (?, ?, ?, ?, ?)
    """, products)

    conn.commit()
    conn.close()


init_db()
seed_products()
# ---------------- CART SAFE HELPER ----------------

def get_cart():
    cart = session.get("cart", [])
    fixed_cart = []

    for item in cart:
        if isinstance(item, dict):
            fixed_cart.append(item)

    session["cart"] = fixed_cart
    return fixed_cart

# ---------------- AUTH ----------------

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

# ---------------- ROUTES ----------------
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    # Total orders
    total_orders = cursor.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    # Total revenue
    total_revenue = cursor.execute(
        "SELECT SUM(total_amount) FROM orders WHERE status='paid'"
    ).fetchone()[0] or 0

    # New admissions
    new_admissions = cursor.execute(
        "SELECT COUNT(*) FROM admissions WHERE status='new'"
    ).fetchone()[0]

    # Total products
    total_products = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    # Posts for the dashboard (existing news posts)
    posts_db = cursor.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    posts = []
    for p in posts_db:
        media = cursor.execute(
            "SELECT file_path, media_type FROM post_media WHERE post_id=?",
            (p["id"],)
        ).fetchall()
        posts.append({
            "id": p["id"],
            "title": p["title"],
            "description": p["description"],
            "date": p["created_at"],
            "media": [dict(m) for m in media]
        })

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_orders=total_orders,
        total_revenue=total_revenue,
        new_admissions=new_admissions,
        total_products=total_products,
        posts=posts
    )



@app.route("/")
def home():
    return render_template("home.html")


@app.route("/history")
def history():
    return render_template("history.html")


@app.route("/news")
def news():
    conn = get_db()
    cursor = conn.cursor()

    posts_db = cursor.execute("""
        SELECT * FROM posts
        ORDER BY created_at DESC
    """).fetchall()

    posts = []

    for p in posts_db:
        media = cursor.execute("""
            SELECT file_path, media_type
            FROM post_media
            WHERE post_id = ?
        """, (p["id"],)).fetchall()

        posts.append({
            "id": p["id"],
            "title": p["title"],
            "description": p["description"],
            "date": p["created_at"],  # you can format in template
            "media": [dict(m) for m in media]
        })

    conn.close()

    return render_template("news.html", posts=posts)


# ---------------- CONTACT ----------------

@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------------- SHOP ----------------

@app.route("/shop")
def shop():
    q = request.args.get("q", "").strip()
    conn = get_db()

    try:
        if q:
            products = conn.execute("""
                SELECT * FROM products
                WHERE name LIKE ? OR description LIKE ? OR category LIKE ?
                ORDER BY id DESC
            """, (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        else:
            products = conn.execute(
                "SELECT * FROM products ORDER BY id DESC"
            ).fetchall()
    finally:
        conn.close()

    return render_template("shop.html", products=products, query=q)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
    finally:
        conn.close()

    if not product:
        return render_template("404.html"), 404

    return render_template("product_detail.html", product=product)


# ---------------- CART ----------------

@app.route("/cart")
def cart():
    cart_items = get_cart()

    subtotal = 0
    for item in cart_items:
        try:
            subtotal += float(item["price"]) * int(item["quantity"])
        except (KeyError, ValueError, TypeError):
            continue

    total = round(subtotal, 2)

    return render_template(
        "cart.html",
        cart_items=cart_items,
        subtotal=round(subtotal, 2),
        total=total
    )


# ---------------- ADD TO CART ----------------
@app.route("/add-to-cart/<int:product_id>", methods=["GET", "POST"])
def add_to_cart(product_id):
    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
    finally:
        conn.close()

    if not product:
        flash("Product not found", "danger")
        return redirect(url_for("shop"))

    cart = get_cart()

    for item in cart:
        if item["id"] == product["id"]:
            item["quantity"] += 1
            break
    else:
        cart.append({
            "id": product["id"],
            "name": product["name"],
            "price": float(product["price"]),
            "image": product["image"],
            "quantity": 1
        })

    session["cart"] = cart
    session.modified = True

    flash("Product added to cart", "success")
    return redirect(url_for("cart"))


# ---------------- REMOVE FROM CART ----------------
@app.route("/remove-from-cart/<int:product_id>", methods=["POST"])
def remove_from_cart(product_id):

    cart = get_cart()
    updated_cart = []

    for item in cart:
        if item["id"] == product_id:
            if item["quantity"] > 1:
                item["quantity"] -= 1
                updated_cart.append(item)
        else:
            updated_cart.append(item)

    session["cart"] = updated_cart
    session.modified = True

    flash("Cart updated", "info")
    return redirect(url_for("cart"))


# ---------------- CLEAR CART ----------------
@app.route("/clear-cart", methods=["POST"])
def clear_cart():
    session.pop("cart", None)
    session.modified = True
    flash("Cart cleared", "warning")
    return redirect(url_for("cart"))

# ---------------- CHECKOUT ----------------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():

    cart = get_cart()

    if not cart:
        flash("Your cart is empty", "warning")
        return redirect(url_for("shop"))

    conn = get_db()
    cursor = conn.cursor()

    # ---------------- SAFE TOTAL CALCULATION ----------------
    subtotal = 0
    validated_items = []

    for item in cart:
        if not isinstance(item, dict):
            continue

        product = cursor.execute(
            "SELECT id, name, price FROM products WHERE id = ?",
            (item["id"],)
        ).fetchone()

        if not product:
            continue

        quantity = max(1, int(item.get("quantity", 1)))
        price = float(product["price"])

        subtotal += price * quantity

        validated_items.append({
            "id": product["id"],
            "quantity": quantity,
            "price": price
        })

    if subtotal <= 0:
        conn.close()
        flash("Invalid cart data", "danger")
        return redirect(url_for("cart"))

    delivery_fee = 0  # Not used anymore
    total = round(subtotal + delivery_fee, 2)

    # ---------------- POST: CREATE ORDER ----------------
    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not phone:
            conn.close()
            flash("Please fill all required fields", "danger")
            return redirect(url_for("checkout"))

        try:
            # Encrypt sensitive info
            enc_name = encrypt_text(name)
            enc_phone = encrypt_text(phone)

            # Revenue split
            school_cut = round(subtotal * 0.20, 2)
            supplier_cut = round(subtotal * 0.70, 2)
            courier_cut = round(subtotal * 0.10, 2)

            # Create order without delivery
            cursor.execute("""
                INSERT INTO orders (
                    customer_name,
                    customer_phone,
                    subtotal,
                    delivery_fee,
                    school_amount,
                    supplier_amount,
                    courier_amount,
                    total_amount,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                enc_name,
                enc_phone,
                subtotal,
                delivery_fee,
                school_cut,
                supplier_cut,
                courier_cut,
                total,
                "pending"
            ))

            order_id = cursor.lastrowid

            # Insert order items (validated only)
            for item in validated_items:
                cursor.execute("""
                    INSERT INTO order_items (
                        order_id,
                        product_id,
                        quantity,
                        price
                    ) VALUES (?, ?, ?, ?)
                """, (
                    order_id,
                    item["id"],
                    item["quantity"],
                    item["price"]
                ))

            conn.commit()

        except Exception:
            conn.rollback()
            conn.close()
            flash("Checkout failed. Try again.", "danger")
            return redirect(url_for("cart"))

        conn.close()

        return redirect(url_for("payfast_checkout", order_id=order_id))

    conn.close()

    return render_template(
        "checkout.html",
        subtotal=round(subtotal, 2),
        delivery_fee=delivery_fee,
        total=total
    )


# ---------------- PAYFAST CHECKOUT ----------------

@app.route("/payfast/checkout/<int:order_id>")
def payfast_checkout(order_id):

    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ? AND status = 'pending'",
        (order_id,)
    ).fetchone()
    conn.close()

    if not order:
        return render_template("404.html"), 404

    payment_data = {
        "merchant_id": MERCHANT_ID,
        "merchant_key": MERCHANT_KEY,
        "return_url": RETURN_URL + f"?order_id={order_id}",
        "cancel_url": CANCEL_URL + f"?order_id={order_id}",
        "notify_url": NOTIFY_URL,
        "name_first": "Customer",
        "email_address": "customer@email.com",
        "m_payment_id": str(order["id"]),
        "amount": "%.2f" % float(order["total_amount"]),
        "item_name": f"School Books Order #{order['id']}",
    }

    return render_template(
        "payfast_redirect.html",
        payfast_url=PAYFAST_URL,
        payment_data=payment_data
    )


# ---------------- PAYMENT SUCCESS ----------------
@app.route("/payment/success")
def payment_success():
    order_id = request.args.get("order_id")
    if not order_id:
        return redirect(url_for("shop"))

    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=? AND status='paid'", (order_id,)).fetchone()
    conn.close()

    if not order:
        flash("Payment not verified.", "danger")
        return redirect(url_for("shop"))

    # Clear cart and show success page
    session.pop("cart", None)
    return render_template("payment_success.html", order_id=order_id)



# ---------------- PAYMENT CANCEL ----------------

@app.route("/payment/cancel")
def payment_cancel():
    order_id = request.args.get("order_id")
    flash("Payment was cancelled.", "warning")
    return redirect(url_for("cart"))


# ---------------- PAYFAST ITN (SECURE) ----------------

@app.route("/payment/itn", methods=["POST"])
def payment_itn():

    data = request.form.to_dict()

    # Step 1: Validate with PayFast
    try:
        validate_url = PAYFAST_ITN_VALIDATION_URL
        response = requests.post(validate_url, data=data, timeout=10)
        if response.text != "VALID":
            return "Invalid ITN", 400
    except Exception:
        return "Validation failed", 400

    # Step 2: Verify merchant
    if data.get("merchant_id") != MERCHANT_ID:
        return "Invalid merchant", 400

    order_id = data.get("m_payment_id")
    payment_status = data.get("payment_status")
    amount_gross = float(data.get("amount_gross", 0))

    if not order_id:
        return "No order id", 400

    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,)
    ).fetchone()

    if not order:
        conn.close()
        return "Order not found", 404

    # Step 3: Verify amount matches database
    if float(order["total_amount"]) != amount_gross:
        conn.close()
        return "Amount mismatch", 400

    # Step 4: Update order securely
    if payment_status == "COMPLETE":
        conn.execute(
            "UPDATE orders SET status = 'paid' WHERE id = ?",
            (order_id,)
        )
    elif payment_status in ["FAILED", "CANCELLED"]:
        conn.execute(
            "UPDATE orders SET status = 'failed' WHERE id = ?",
            (order_id,)
        )

    conn.commit()
    conn.close()

    return "OK", 200


# ---------------- PAYFAST ITN (ADMISSIONS) ----------------

@app.route("/payfast/itn", methods=["POST"])
def payfast_itn():

    data = request.form.to_dict()

    # Validate with PayFast server
    try:
        response = requests.post(
            PAYFAST_ITN_VALIDATION_URL,
            data=data,
            timeout=10
        )
        if response.text != "VALID":
            return "Invalid ITN", 400
    except Exception:
        return "Validation failed", 400

    if data.get("merchant_id") != MERCHANT_ID:
        return "Invalid merchant", 400

    payment_status = data.get("payment_status")
    payment_id = data.get("pf_payment_id")
    order_id = data.get("m_payment_id")
    amount = float(data.get("amount_gross", 0))

    if payment_status != "COMPLETE" or not order_id:
        return "Payment not complete", 400

    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order:
        conn.close()
        return "Order not found", 404

    if float(order["total_amount"]) != amount:
        conn.close()
        return "Amount mismatch", 400

    conn.execute("""
        UPDATE orders
        SET status='paid'
        WHERE id=?
    """, (order_id,))
    conn.commit()
    conn.close()

    return "OK", 200


# ---------------- ADMISSIONS ----------------
# This is the info page
@app.route("/admissions")
def admissions():
    return render_template("admissions.html")

# This is the route that handles the actual payment process
@app.route("/admission-payment", methods=["GET", "POST"])
def start_admission_payment():
    # Step 1: Must have paid
    if not session.get("admission_paid"):
        flash("Please pay the R150 admission fee first.", "warning")
        return redirect(url_for("admission_payment_itn"))  # page where they pay fee

    # Step 2: Handle POST submission
    if request.method == "POST":
        learner = request.form.get("learner_name", "").strip()
        parent = request.form.get("parent_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        grade = request.form.get("grade", "").strip()

        if not learner or not parent or not phone or not grade:
            flash("Please complete all required fields.", "danger")
            return redirect(url_for("admissions"))

        # Helper to save documents
        def save_doc(file):
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_name = f"{datetime.now().timestamp()}_{filename}"
                path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
                file.save(path)
                return "uploads/" + unique_name
            return ""

        # Match these to your form input names
        birth_path = save_doc(request.files.get("birth_certificate"))
        parent_id_path = save_doc(request.files.get("parent_id_copy"))
        report_path = save_doc(request.files.get("latest_report"))
        residence_path = save_doc(request.files.get("proof_of_residence"))

        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO admissions (
                    learner_name, parent_name, phone, email, grade,
                    birth_certificate, parent_id_copy, latest_report, proof_of_residence,
                    payment_status, amount_paid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                learner, parent, phone, email, grade,
                birth_path, parent_id_path, report_path, residence_path,
                "paid", "150"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            flash(f"Submission failed. Try again. Error: {str(e)}", "danger")
            return redirect(url_for("admissions"))

        # Clear session flag after submission
        session.pop("admission_paid", None)
        flash("Admission submitted successfully!", "success")
        return redirect(url_for("admission_sent"))

    # Step 3: GET → render the admission form
    return render_template("admission_form.html", paid=True)


# ---------------- CONTEXT PROCESSOR ----------------
@app.context_processor
def inject_cart_count():
    cart = session.get("cart", [])
    count = sum(item.get("quantity", 0) for item in cart if isinstance(item, dict))
    return dict(cart_count=count)


@app.route("/admission-sent")
def admission_sent():
    return render_template("admission_sent.html")

# ---------------- ADMIN ADMISSIONS ----------------

@app.route("/admin/admissions")
@admin_required
def admin_admissions():

    conn = get_db()
    admissions = conn.execute(
        "SELECT * FROM admissions ORDER BY id DESC"
    ).fetchall()
    conn.close()

    return render_template("admin_admissions.html", admissions=admissions)


@app.route("/admin/mark_paid/<int:admission_id>", methods=["POST"])
@admin_required
def mark_paid(admission_id):

    conn = get_db()
    conn.execute("""
        UPDATE admissions
        SET payment_status='paid',
            amount_paid=150
        WHERE id=?
    """, (admission_id,))
    conn.commit()
    conn.close()

    flash("Admission marked as paid.", "success")
    return redirect(url_for("admin_admissions"))


# ---------------- DELETE POST ----------------

@app.route("/admin/delete-post/<int:post_id>", methods=["POST"])
@admin_required
def delete_post(post_id):

    conn = get_db()
    cursor = conn.cursor()

    media = cursor.execute("""
        SELECT file_path FROM post_media
        WHERE post_id=?
    """, (post_id,)).fetchall()

    for m in media:
        file_path = os.path.join("static", m["file_path"])
        if os.path.exists(file_path):
            os.remove(file_path)

    cursor.execute("DELETE FROM post_media WHERE post_id=?", (post_id,))
    cursor.execute("DELETE FROM posts WHERE id=?", (post_id,))

    conn.commit()
    conn.close()

    flash("Post deleted successfully.", "info")
    return redirect(url_for("admin_news"))


# ---------------- SAVE POST MEDIA ----------------

def save_post_media(post_id, file_path, media_type):

    conn = get_db()
    conn.execute("""
        INSERT INTO post_media (post_id, file_path, media_type)
        VALUES (?, ?, ?)
    """, (post_id, file_path, media_type))
    conn.commit()
    conn.close()


# ---------------- SUBMIT ADMISSION ----------------

@app.route("/submit-admission", methods=["POST", "GET"])
def submit_admission():
    if request.method == "GET":
        return redirect(url_for("admissions"))
    
    if not session.get("admission_paid"):
        flash("Admission fee not confirmed.", "danger")
        return redirect(url_for("admissions"))

    learner = request.form.get("learner_name", "").strip()
    parent = request.form.get("parent_name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    grade = request.form.get("grade", "").strip()

    if not learner or not parent or not phone or not grade:
        flash("Please complete all required fields.", "danger")
        return redirect(url_for("admissions"))

    def save_doc(file):
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_name = f"{datetime.now().timestamp()}_{filename}"
            path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
            file.save(path)
            return "uploads/" + unique_name
        return ""

    birth_path = save_doc(request.files.get("birth_certificate"))
    parent_id_path = save_doc(request.files.get("parent_id_copy"))
    report_path = save_doc(request.files.get("latest_report"))
    residence_path = save_doc(request.files.get("proof_of_residence"))

    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO admissions (
                learner_name, parent_name, phone, email, grade,
                birth_certificate, parent_id_copy, latest_report, proof_of_residence,
                payment_status, amount_paid
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            learner, parent, phone, email, grade,
            birth_path, parent_id_path, report_path, residence_path,
            "paid", "150"
        ))
        conn.commit()
        conn.close()
    except Exception:
        flash("Submission failed. Try again.", "danger")
        return redirect(url_for("admissions"))

    session.pop("admission_paid", None)

    return render_template("admissions_sent.html")


# ---------------- ADMISSION PAYMENT SUCCESS ----------------
@app.route("/admission/success")
def admission_payment_success():
    session["admission_paid"] = True
    flash("Admission fee paid successfully. Please complete the application form.", "success")
    return redirect(url_for("admissions"))



# ---------------- ADMISSION PAYMENT ITN (SECURE) ----------------

@app.route("/admission-payment-itn", methods=["POST"])
def admission_payment_itn():

    data = request.form.to_dict()

    # Step 1: Validate with PayFast
    try:
        response = requests.post(
            PAYFAST_ITN_VALIDATION_URL,
            data=data,
            timeout=10
        )
        if response.text != "VALID":
            return "Invalid ITN", 400
    except Exception:
        return "Validation failed", 400

    if data.get("merchant_id") != MERCHANT_ID:
        return "Invalid merchant", 400

    payment_status = data.get("payment_status")
    amount = float(data.get("amount_gross", 0))

    if payment_status == "COMPLETE" and amount == 150.00:
        # Mark session as paid only after ITN validation
        session["admission_paid"] = True
        return "OK", 200

    return "Payment not complete", 400

# ---------------- ADMIN LOGIN ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            error = "Please enter both username and password."
        elif username != ADMIN_USERNAME:
            error = "Invalid username."
        else:
            try:
                # Verify password using argon2
                ph.verify(ADMIN_PASSWORD_HASH, password)
                # Login success
                session["admin_logged_in"] = True
                flash("Logged in successfully!", "success")
                return redirect(url_for("admin_dashboard"))
            except:
                error = "Invalid password."

    return render_template("admin_login.html", error=error)


# ---------------- ADMIN LOGOUT ----------------
@app.route("/admin/logout")
@admin_required
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin/book-orders", methods=["GET", "POST"])
def admin_bookorders():
    # --- Admin-only check ---
    if not session.get("admin_logged_in"):
        flash("Admin access required.", "danger")
        return redirect(url_for("admin_login"))

    conn = get_db()
    cursor = conn.cursor()

    # Filter inputs from the form
    name_filter = ""
    phone_filter = ""
    if request.method == "POST":
        name_filter = request.form.get("name", "").strip()
        phone_filter = request.form.get("phone", "").strip()

    # Build query for orders
    query = "SELECT * FROM orders"
    params = []
    filters = []

    if name_filter:
        filters.append("customer_name LIKE ?")
        params.append(f"%{name_filter}%")
    if phone_filter:
        filters.append("customer_phone LIKE ?")
        params.append(f"%{phone_filter}%")

    if filters:
        query += " WHERE " + " AND ".join(filters)

    query += " ORDER BY id DESC"  # latest orders first

    orders = cursor.execute(query, params).fetchall()

    # Fetch ordered books for each order
    orders_with_items = []
    for order in orders:
        items = cursor.execute("""
            SELECT p.name AS book_name, oi.quantity, oi.price
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        """, (order["id"],)).fetchall()

        orders_with_items.append({
            "order": order,
            "items": items
        })

    conn.close()

    return render_template(
        "admin_bookorders.html",
        orders_with_items=orders_with_items,
        name_filter=name_filter,
        phone_filter=phone_filter
    )

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

