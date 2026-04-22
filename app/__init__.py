import os

import click
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

load_dotenv()

db = SQLAlchemy()


def _ensure_runtime_schema(connection=None):
    bind = connection or db.engine
    inspector = inspect(bind)
    if 'menu_items' not in inspector.get_table_names():
        return

    existing_columns = {column['name'] for column in inspector.get_columns('menu_items')}
    alter_statements = []

    if 'presto_id' not in existing_columns:
        alter_statements.append("ALTER TABLE menu_items ADD COLUMN presto_id INTEGER")
    if 'external_id' not in existing_columns:
        alter_statements.append("ALTER TABLE menu_items ADD COLUMN external_id VARCHAR(64)")
    if 'nom_number' not in existing_columns:
        alter_statements.append("ALTER TABLE menu_items ADD COLUMN nom_number VARCHAR(128)")

    for statement in alter_statements:
        if connection is not None:
            connection.execute(text(statement))
        else:
            db.session.execute(text(statement))

    if alter_statements and connection is None:
        db.session.commit()


def _resolve_database_url():
    database_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    if database_url:
        return database_url

    if os.getenv('VERCEL'):
        raise RuntimeError('DATABASE_URL is required for Vercel deployments.')

    instance_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'menu.db'))
    os.makedirs(os.path.dirname(instance_path), exist_ok=True)
    return f"sqlite:///{instance_path}"


def _resolve_static_folder():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    public_static = os.path.join(project_root, 'public', 'static')
    if os.path.isdir(public_static):
        return public_static

    return os.path.join(os.path.dirname(__file__), 'static')


def _initialize_schema():
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        db.create_all()
        _ensure_runtime_schema()
        return

    lock_id = 48270124
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {'lock_id': lock_id})
        try:
            db.metadata.create_all(bind=connection)
            _ensure_runtime_schema(connection)
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {'lock_id': lock_id})


def create_app():
    app = Flask(
        __name__,
        static_folder=_resolve_static_folder(),
        static_url_path='/static',
        template_folder=os.path.join(os.path.dirname(__file__), 'templates')
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = _resolve_database_url()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
    }
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or 'dev-secret-key'

    db.init_app(app)
    Migrate(app, db)

    with app.app_context():
        from app import models  # noqa: F401

        _initialize_schema()

    from app.routes import api_bp, presto_bp

    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(presto_bp, url_prefix='/api')

    @app.route('/menu')
    def menu_page():
        return render_template('menu.html')

    @app.route('/menu.html')
    def menu_page_legacy():
        return render_template('menu.html')

    @app.route('/order')
    def order_page():
        return render_template('order.html')

    @app.route('/api/test-auth')
    def test_auth():
        from app.services.auth import auth as prest_auth

        try:
            token = prest_auth()
            return jsonify({'access_token': token})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.cli.command("update-menu")
    @click.argument('point_id', required=False, default=None, type=int)
    @click.argument('price_list_id', required=False, default=None, type=int)
    def update_menu(point_id, price_list_id):
        from app.services.menu import upsert_menu
        from app.services.presto_config import get_point_id, get_price_list_id

        point_id = point_id or get_point_id()
        price_list_id = price_list_id or get_price_list_id()
        upsert_menu(point_id=point_id, price_list_id=price_list_id)
        click.echo("Menu updated successfully")

    return app
