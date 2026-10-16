
import os
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

# Use an environment variable online, with a local fallback for development.
app.secret_key = os.environ.get(
    "SECRET_KEY", "local-development-key-change-before-deployment"
)

database_url = os.environ.get("DATABASE_URL")

if database_url:
    # Render may provide a postgres:// URL.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///queueflow.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# DATABASE TABLES

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class QueueEntry(db.Model):
    __tablename__ = "queue_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    ticket_number = db.Column(db.Integer, nullable=False)
    visitor_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="waiting")
    created_at = db.Column(db.DateTime, server_default=func.now())


# REQUIRE LOGIN FOR PROTECTED PAGES

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


# REGISTRATION

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please fill in all fields.")
            return redirect(url_for("register"))

        if len(username) > 50:
            flash("Username must be 50 characters or fewer.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            flash("That username is already taken.")
            return redirect(url_for("register"))

        user = User(
            username=username,
            password=generate_password_hash(password)
        )

        db.session.add(user)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Registration failed")
            flash("Could not create the account. Please try again.")
            return redirect(url_for("register"))

        flash("Account created! You can now log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


# LOGIN

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(url_for("dashboard"))

        flash("Incorrect username or password.")

    return render_template("login.html")


# LOGOUT

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# DASHBOARD

@app.route("/")
@login_required
def dashboard():
    user_id = session["user_id"]

    waiting = (
        QueueEntry.query
        .filter_by(user_id=user_id, status="waiting")
        .order_by(QueueEntry.id.asc())
        .all()
    )

    served = (
        QueueEntry.query
        .filter_by(user_id=user_id, status="served")
        .order_by(QueueEntry.id.desc())
        .first()
    )

    served_count = QueueEntry.query.filter_by(
        user_id=user_id, status="served"
    ).count()

    return render_template(
        "dashboard.html",
        waiting=waiting,
        served=served,
        served_count=served_count,
        username=session["username"]
    )


# ENQUEUE: ADD A VISITOR TO THE END

@app.route("/add", methods=["POST"])
@login_required
def add_visitor():
    name = request.form.get("visitor_name", "").strip()

    if not name:
        flash("Please enter a visitor name.")
        return redirect(url_for("dashboard"))

    if len(name) > 100:
        flash("Visitor name must be 100 characters or fewer.")
        return redirect(url_for("dashboard"))

    user_id = session["user_id"]

    last_ticket = db.session.query(
        func.max(QueueEntry.ticket_number)
    ).filter_by(user_id=user_id).scalar()

    ticket_number = (last_ticket or 0) + 1

    visitor = QueueEntry(
        user_id=user_id,
        ticket_number=ticket_number,
        visitor_name=name,
        status="waiting"
    )

    db.session.add(visitor)
    db.session.commit()

    flash(f"Visitor added! Ticket number: {ticket_number}")
    return redirect(url_for("dashboard"))


# DEQUEUE: SERVE THE FIRST PERSON WHO JOINED

@app.route("/serve", methods=["POST"])
@login_required
def serve_next():
    user_id = session["user_id"]

    first = (
        QueueEntry.query
        .filter_by(user_id=user_id, status="waiting")
        .order_by(QueueEntry.id.asc())
        .first()
    )

    if first:
        first.status = "served"
        db.session.commit()
        flash(f"Ticket #{first.ticket_number} has been served.")
    else:
        flash("There is nobody waiting in the queue.")

    return redirect(url_for("dashboard"))


# CREATE TABLES AND START THE APP

with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
