import os
import io
import base64
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import qrcode

app = Flask(__name__)
app.secret_key = 'aurashop_super_secret_key_change_in_prod'

# Database & Upload Config
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'store.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Admin Credentials (For Submission Deliverable)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"


# ==================== DATABASE MODELS ====================
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    image = db.Column(db.String(255), default='default.png')
    status = db.Column(db.String(20), default='Active')  # 'Active' or 'Inactive'


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    shipping_address = db.Column(db.Text, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True)


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)


# ==================== HELPER FUNCTIONS ====================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in as Admin first.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def generate_khqr_base64(amount):
    """Generates a dynamic KHQR-style QR code image encoded in base64."""
    khqr_payload = f"00020101021229370016kh.gov.nbc.bakong0113aurashop@aclb520459995303840540{amount:.2f}5802KH5908AuraShop6010Phnom Penh6304ABCD"
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(khqr_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a1a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


@app.context_processor
def inject_cart_count():
    cart = session.get('cart', {})
    total_qty = sum(cart.values())
    return dict(cart_count=total_qty, store_name="AuraShop")


# ==================== PUBLIC CUSTOMER ROUTES ====================
@app.route('/')
def index():
    products = Product.query.filter_by(status='Active').all()
    return render_template('index.html', products=products)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    product_url = request.url
    return render_template('product_detail.html', product=product, product_url=product_url)


@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = int(request.form.get('quantity', 1))

    if product.stock < quantity:
        flash('Not enough stock available!', 'danger')
        return redirect(url_for('product_detail', product_id=product_id))

    cart = session.get('cart', {})
    pid_str = str(product_id)
    cart[pid_str] = cart.get(pid_str, 0) + quantity
    session['cart'] = cart
    flash(f'Added "{product.name}" to your cart!', 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/cart')
def cart():
    cart_session = session.get('cart', {})
    cart_items = []
    total_amount = 0.0

    for pid_str, qty in cart_session.items():
        product = Product.query.get(int(pid_str))
        if product:
            subtotal = product.price * qty
            total_amount += subtotal
            cart_items.append({
                'product': product,
                'quantity': qty,
                'subtotal': subtotal
            })

    return render_template('cart.html', cart_items=cart_items, total_amount=total_amount)


@app.route('/update-cart/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    action = request.form.get('action')
    cart = session.get('cart', {})
    pid_str = str(product_id)

    if pid_str in cart:
        if action == 'remove':
            del cart[pid_str]
            flash('Item removed from cart.', 'info')
        elif action == 'update':
            new_qty = int(request.form.get('quantity', 1))
            if new_qty <= 0:
                del cart[pid_str]
            else:
                cart[pid_str] = new_qty
                flash('Cart updated.', 'success')

    session['cart'] = cart
    return redirect(url_for('cart'))


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_session = session.get('cart', {})
    if not cart_session:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('index'))

    cart_items = []
    total_amount = 0.0
    for pid_str, qty in cart_session.items():
        product = Product.query.get(int(pid_str))
        if product:
            subtotal = product.price * qty
            total_amount += subtotal
            cart_items.append({'product': product, 'quantity': qty, 'subtotal': subtotal})

    if request.method == 'POST':
        new_order = Order(
            customer_name=request.form['full_name'],
            email=request.form['email'],
            phone=request.form['phone'],
            shipping_address=request.form['shipping_address'],
            total_amount=total_amount
        )
        db.session.add(new_order)
        db.session.flush()  # Get new_order.id before commit

        for item in cart_items:
            prod = item['product']
            qty = item['quantity']
            order_item = OrderItem(
                order_id=new_order.id,
                product_name=prod.name,
                quantity=qty,
                price=prod.price
            )
            db.session.add(order_item)
            # Deduct stock
            prod.stock = max(0, prod.stock - qty)

        db.session.commit()
        session.pop('cart', None)
        return redirect(url_for('order_confirmation', order_id=new_order.id))

    khqr_img = generate_khqr_base64(total_amount)
    return render_template('checkout.html', cart_items=cart_items, total_amount=total_amount, khqr_img=khqr_img)


@app.route('/confirmation/<int:order_id>')
def order_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('confirmation.html', order=order)


# ==================== ADMIN ROUTES ====================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Welcome back, Admin!', 'success')
            return redirect(url_for('admin_products'))
        flash('Invalid username or password.', 'danger')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out of Admin panel.', 'info')
    return redirect(url_for('index'))


@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template('admin/products.html', products=products)


@app.route('/admin/products/new', methods=['GET', 'POST'])
@admin_required
def admin_product_create():
    if request.method == 'POST':
        image_filename = 'https://placehold.co/400x300?text=Product'
        file = request.files.get('image')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = f'/static/uploads/{filename}'
        elif request.form.get('image_url'):
            image_filename = request.form.get('image_url')

        new_prod = Product(
            name=request.form['name'],
            description=request.form['description'],
            price=float(request.form['price']),
            stock=int(request.form['stock']),
            image=image_filename,
            status=request.form['status']
        )
        db.session.add(new_prod)
        db.session.commit()
        flash('Product created successfully!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_form.html', product=None)


@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@admin_required
def admin_product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form['name']
        product.description = request.form['description']
        product.price = float(request.form['price'])
        product.stock = int(request.form['stock'])
        product.status = request.form['status']

        file = request.files.get('image')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            product.image = f'/static/uploads/{filename}'
        elif request.form.get('image_url'):
            product.image = request.form.get('image_url')

        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_form.html', product=product)


@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@admin_required
def admin_product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('admin_products'))


@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.order_date.desc()).all()
    return render_template('admin/orders.html', orders=orders)


@app.route('/admin/orders/<int:order_id>')
@admin_required
def admin_order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order)


# ==================== INITIALIZE DB & SEED DATA ====================
with app.app_context():
    db.create_all()
    if Product.query.count() == 0:
        sample_products = [
            Product(name="Wireless Noise-Canceling Headphones", description="Premium over-ear Bluetooth 5.3 headphones with 40-hour battery life and deep bass.", price=59.99, stock=15, image="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500", status="Active"),
            Product(name="Minimalist Smart Watch", description="Fitness & health tracker with AMOLED display, heart-rate monitor, and 10-day battery.", price=45.00, stock=20, image="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500", status="Active"),
            Product(name="Mechanical Gaming Keyboard", description="Compact 75% RGB hot-swappable mechanical keyboard with tactile switches.", price=65.50, stock=8, image="https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500", status="Active"),
            Product(name="USB-C 65W GaN Fast Charger", description="Ultra-compact dual-port GaN wall charger for laptops, tablets, and smartphones.", price=24.99, stock=30, image="https://images.unsplash.com/photo-1583863788434-e58a36330cf0?w=500", status="Active"),
        ]
        db.session.bulk_save_objects(sample_products)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)