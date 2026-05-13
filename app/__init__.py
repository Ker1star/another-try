import os

import click
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
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
    if 'available_for_delivery' not in existing_columns:
        alter_statements.append("ALTER TABLE menu_items ADD COLUMN available_for_delivery BOOLEAN NOT NULL DEFAULT TRUE")

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
    if os.getenv('VERCEL'):
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
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY') or 'dev-secret-key'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
    }
    app.config['DATABASE_AVAILABLE'] = False
    app.config['DATABASE_ERROR'] = None

    try:
        app.config['SQLALCHEMY_DATABASE_URI'] = _resolve_database_url()
        db.init_app(app)
        Migrate(app, db)

        with app.app_context():
            from app import models  # noqa: F401

            _initialize_schema()

        app.config['DATABASE_AVAILABLE'] = True
    except Exception as exc:
        app.config['DATABASE_ERROR'] = str(exc)
        app.logger.exception("Database initialization failed")

    from app.routes import api_bp, presto_bp

    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(presto_bp, url_prefix='/api')

    @app.route('/menu')
    def menu_page():
        return render_template('menu.html')

    @app.route('/menu.html')
    def menu_page_legacy():
        return render_template('menu.html')

    @app.route('/delivery')
    def delivery_page():
        return render_template('delivery.html')

    @app.route('/delivery.html')
    def delivery_page_legacy():
        return render_template('delivery.html')

    @app.route('/order')
    def order_page():
        return render_template('order.html')

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/about')
    def about_page():
        return render_template('about.html')

    @app.route('/privacy')
    def privacy_page():
        return render_template('privacy.html')

    @app.route('/reserve', methods=['POST'])
    def reserve():
        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or '').strip()
        date = (data.get('date') or '').strip()
        time_ = (data.get('time') or '').strip()
        guests = (data.get('guests') or '').strip()
        comment = (data.get('comment') or '').strip()

        if not name or not phone or not date or not time_:
            return jsonify({'ok': False, 'error': 'Заполните обязательные поля'}), 400

        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if not token or not chat_id:
            app.logger.warning('Telegram credentials not configured')
            return jsonify({'ok': False, 'error': 'Сервис временно недоступен'}), 503

        lines = [
            '\U0001f4c5 *Заявка на бронирование стола*',
            f'\U0001f464 Имя: {name}',
            f'\U0001f4de Телефон: {phone}',
            f'\U0001f4c6 Дата: {date}',
            f'\U0001f550 Время: {time_}',
        ]
        if guests:
            lines.append(f'\U0001f465 Гостей: {guests}')
        if comment:
            lines.append(f'\U0001f4ac Комментарий: {comment}')

        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': '\n'.join(lines), 'parse_mode': 'Markdown'},
                timeout=5,
            )
            resp.raise_for_status()
        except Exception as exc:
            app.logger.error('Telegram sendMessage failed: %s', exc)
            return jsonify({'ok': False, 'error': 'Не удалось отправить заявку. Позвоните нам: +7 (8212) 29-12-47'}), 502

        return jsonify({'ok': True})

    @app.errorhandler(404)
    def not_found(_):
        return render_template('404.html'), 404

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
