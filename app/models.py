from datetime import datetime, timezone
from app import db


class PendingOrder(db.Model):
    __tablename__ = 'pending_orders'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    tracking_id = db.Column(db.String(36), unique=True, nullable=True, index=True)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    error = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Reservation(db.Model):
    __tablename__ = 'reservations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=False)
    guests = db.Column(db.String(10), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    telegram_sent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    sbis_id = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    parent_sbis_id = db.Column(db.Integer, db.ForeignKey('categories.sbis_id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    id = db.Column(db.Integer, primary_key=True)
    sbis_id = db.Column(db.Integer, unique=True, nullable=False)
    presto_id = db.Column(db.Integer, nullable=True)
    external_id = db.Column(db.String(64), nullable=True)
    nom_number = db.Column(db.String(128), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    out_quantity = db.Column(db.String(50), nullable=True)
    description_simple = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(512), nullable=True)
    price = db.Column(db.Numeric(10,2), nullable=True)
    published = db.Column(db.Boolean, default=True)
    available_for_delivery = db.Column(db.Boolean, default=True, nullable=False)
    in_restaurant = db.Column(db.Boolean, default=True, nullable=False)
    in_family = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    category = db.relationship('Category', backref='items')
