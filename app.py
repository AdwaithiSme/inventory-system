# Basic Inventory Management System
# Using Flask, SQLAlchemy, and SQLite database

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
from datetime import datetime
import os

# Initialize Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Define database models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(15))
    address = db.Column(db.String(200))

    # Define the reverse relationship using back_populates
    transactions = db.relationship('Transaction', back_populates='customer')  # Use back_populates

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))  # New foreign key
    quantity = db.Column(db.Integer, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'in' or 'out'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    
    product = db.relationship('Product', backref=db.backref('transactions', lazy=True))
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))
    customer = db.relationship('Customer', back_populates='transactions')  # Use back_populates

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('You do not have permission to access this page', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

from sqlalchemy import func


@app.route('/dashboard')
@login_required
def dashboard():
    # Existing data
    recent_transactions = Transaction.query.order_by(Transaction.timestamp.desc()).limit(10).all()
    low_stock = Product.query.filter(Product.quantity < 10).all()
    product_count = Product.query.count()
    total_value = db.session.query(db.func.sum(Product.price * Product.quantity)).scalar() or 0

    # Top-selling products (by total quantity 'out')
    top_selling = (
        db.session.query(
            Product.name,
            func.sum(Transaction.quantity).label('total_sold')
        )
        .join(Transaction, Product.id == Transaction.product_id)
        .filter(Transaction.transaction_type == 'out')
        .group_by(Product.name)
        .order_by(func.sum(Transaction.quantity).desc())
        .limit(5)
        .all()
    )

    # 📊 Category-wise inventory distribution
    category_data_query = db.session.query(
        Product.category,
        func.sum(Product.quantity)
    ).group_by(Product.category).all()

    category_data = {category: qty for category, qty in category_data_query}

    return render_template('dashboard.html',
                           recent_transactions=recent_transactions,
                           low_stock=low_stock,
                           product_count=product_count,
                           total_value=total_value,
                           top_selling=top_selling,
                           category_data=category_data,
                           now=datetime.now())



def calculate_stock_turnover(product_id, start_date, end_date):
    out_transactions = Transaction.query.filter_by(
        product_id=product_id, transaction_type='out'
    ).filter(Transaction.timestamp.between(start_date, end_date)).all()

    total_out = sum(tx.quantity for tx in out_transactions)

    product = Product.query.get(product_id)
    avg_stock = product.quantity if product.quantity > 0 else 1  # Avoid div by zero

    return round(total_out / avg_stock, 2)

@app.route('/products')
@login_required
def products():
    search_query = request.args.get('search', '')
    category_filter = request.args.get('category', '')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = Product.query

    if search_query:
        query = query.filter(Product.name.ilike(f"%{search_query}%"))
    if category_filter:
        query = query.filter_by(category=category_filter)

    products = query.all()
    categories = db.session.query(Product.category).distinct().all()

    turnover_data = {}
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            for product in products:
                turnover_data[product.id] = calculate_stock_turnover(product.id, start, end)
        except ValueError:
            flash("Invalid date format", "danger")

    return render_template(
        'products.html',
        products=products,
        categories=categories,
        turnover_data=turnover_data,
        start_date=start_date,
        end_date=end_date
    )

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        price = float(request.form.get('price'))
        quantity = int(request.form.get('quantity', 0))
        
        product = Product(name=name, description=description, category=category, price=price, quantity=quantity)
        db.session.add(product)
        db.session.commit()  # Commit first to get the product ID
        
        # Add initial inventory transaction if quantity > 0
        if quantity > 0:
            transaction = Transaction(
                product_id=product.id,  # Now product.id is available
                user_id=session['user_id'],
                quantity=quantity,
                transaction_type='in',
                notes='Initial inventory'
            )
            db.session.add(transaction)
            db.session.commit()  # Commit the transaction
        
        flash('Product added successfully', 'success')
        return redirect(url_for('products'))
    
    # Handle GET request by rendering the form template
    return render_template('add_product.html')

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.description = request.form.get('description')
        product.category = request.form.get('category')
        product.price = float(request.form.get('price'))
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('products'))
    
    return render_template('edit_product.html', product=product)

@app.route('/transactions')
@login_required
def transactions():
    transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    return render_template('transactions.html', transactions=transactions)

@app.route('/inventory/add', methods=['GET', 'POST'])
@login_required
def add_inventory():
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = int(request.form.get('quantity'))
        notes = request.form.get('notes')
        
        product = Product.query.get_or_404(product_id)
        product.quantity += quantity
        
        transaction = Transaction(
            product_id=product_id,
            user_id=session['user_id'],
            quantity=quantity,
            transaction_type='in',
            notes=notes
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        flash('Inventory added successfully', 'success')
        return redirect(url_for('products'))
    
    products = Product.query.all()
    return render_template('add_inventory.html', products=products)

@app.route('/inventory/remove', methods=['GET', 'POST'])
@login_required
def remove_inventory():
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = int(request.form.get('quantity'))
        notes = request.form.get('notes')
        
        product = Product.query.get_or_404(product_id)
        
        if product.quantity < quantity:
            flash('Not enough inventory available', 'danger')
            return redirect(url_for('remove_inventory'))
        
        product.quantity -= quantity
        
        transaction = Transaction(
            product_id=product_id,
            user_id=session['user_id'],
            quantity=quantity,
            transaction_type='out',
            notes=notes
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        flash('Inventory removed successfully', 'success')
        return redirect(url_for('products'))
    
    products = Product.query.all()
    return render_template('remove_inventory.html', products=products)

@app.route('/users')
@login_required
@admin_required
def users():
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists', 'danger')
            return redirect(url_for('add_user'))
        
        hashed_password = generate_password_hash(password)
        user = User(username=username, password=hashed_password, is_admin=is_admin)
        
        db.session.add(user)
        db.session.commit()
        
        flash('User added successfully', 'success')
        return redirect(url_for('users'))
    
    return render_template('add_user.html')

@app.route('/customers')
def customers():
    # Fetch all customers from the database
    customers = Customer.query.all()  # Assuming Customer is your model
    return render_template('customers.html', customers=customers)


@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')

        customer = Customer(name=name, email=email, phone=phone, address=address)
        db.session.add(customer)
        db.session.commit()
        
        flash('Customer added successfully', 'success')
        return redirect(url_for('customers'))
    
    return render_template('add_customer.html')

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'POST':
        customer.name = request.form.get('name')
        customer.email = request.form.get('email')
        customer.phone = request.form.get('phone')
        customer.address = request.form.get('address')

        db.session.commit()
        flash('Customer updated successfully', 'success')
        return redirect(url_for('customers'))
    
    return render_template('edit_customer.html', customer=customer)


# Initialize the database and create an admin user if it doesn't exist
def initialize_db():
    with app.app_context():
        db.create_all()
        
        # Check if admin user exists, if not create one
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            hashed_password = generate_password_hash('admin')
            admin = User(username='admin', password=hashed_password, is_admin=True)
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    initialize_db()
    app.run(debug=True)


