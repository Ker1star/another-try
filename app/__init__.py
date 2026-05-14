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
    tables = set(inspector.get_table_names())
    alter_statements = []

    if 'menu_items' in tables:
        cols = {c['name'] for c in inspector.get_columns('menu_items')}
        if 'presto_id' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN presto_id INTEGER")
        if 'external_id' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN external_id VARCHAR(64)")
        if 'nom_number' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN nom_number VARCHAR(128)")
        if 'available_for_delivery' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN available_for_delivery BOOLEAN NOT NULL DEFAULT TRUE")
        if 'in_restaurant' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN in_restaurant BOOLEAN NOT NULL DEFAULT TRUE")
        if 'in_family' not in cols:
            alter_statements.append("ALTER TABLE menu_items ADD COLUMN in_family BOOLEAN NOT NULL DEFAULT FALSE")

    if 'pending_orders' in tables:
        cols = {c['name'] for c in inspector.get_columns('pending_orders')}
        if 'tracking_id' not in cols:
            alter_statements.append("ALTER TABLE pending_orders ADD COLUMN tracking_id VARCHAR(36)")
            alter_statements.append("CREATE UNIQUE INDEX IF NOT EXISTS ix_pending_orders_tracking_id ON pending_orders (tracking_id)")
        if 'status' not in cols:
            alter_statements.append("ALTER TABLE pending_orders ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending'")
            alter_statements.append("CREATE INDEX IF NOT EXISTS ix_pending_orders_status ON pending_orders (status)")
        if 'error' not in cols:
            alter_statements.append("ALTER TABLE pending_orders ADD COLUMN error TEXT")
        if 'updated_at' not in cols:
            alter_statements.append("ALTER TABLE pending_orders ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE")

    for statement in alter_statements:
        if connection is not None:
            connection.execute(text(statement))
        else:
            db.session.execute(text(statement))

    if alter_statements and connection is None:
        db.session.commit()


def send_telegram(text):
    """Send a message to the admin chat. Returns True on success."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return False
    proxy_url = os.getenv('TELEGRAM_PROXY')
    proxies = {'https': proxy_url, 'http': proxy_url} if proxy_url else None
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'},
            timeout=10,
            proxies=proxies,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


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

    @app.route('/family')
    def family_page():
        return render_template('family.html')

    @app.route('/family.html')
    def family_page_legacy():
        return render_template('family.html')

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

    @app.route('/imgx/<path:filename>')
    def imgx(filename):
        from flask import send_file, abort as _abort
        import re

        if not re.match(r'^images/[\w\-. ()/]+$', filename):
            _abort(404)

        static_root = os.path.realpath(app.static_folder)
        src_path = os.path.realpath(os.path.join(static_root, filename))
        if not src_path.startswith(static_root) or not os.path.isfile(src_path):
            _abort(404)

        w = request.args.get('w', default=1200, type=int)
        w = max(100, min(w, 2400))

        cache_dir = os.path.join(static_root, '.imgcache')
        cache_name = filename.replace('/', '__').replace(' ', '_') + f'_{w}.webp'
        cache_path = os.path.join(cache_dir, cache_name)

        if not os.path.exists(cache_path):
            try:
                from PIL import Image
                os.makedirs(cache_dir, exist_ok=True)
                with Image.open(src_path) as img:
                    if img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
                    elif img.mode == 'RGBA':
                        img = img.convert('RGB')
                    if img.width > w:
                        img = img.resize(
                            (w, round(img.height * w / img.width)),
                            Image.LANCZOS,
                        )
                    img.save(cache_path, 'WEBP', quality=82, method=4)
            except Exception as exc:
                app.logger.error('imgx resize failed for %s: %s', filename, exc)
                return send_file(src_path)

        return send_file(cache_path, mimetype='image/webp',
                         max_age=86400 * 30, conditional=True)

    @app.route('/reserve', methods=['POST'])
    def reserve():
        from app.models import Reservation

        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()[:120]
        phone = (data.get('phone') or '').strip()[:40]
        date = (data.get('date') or '').strip()[:20]
        time_ = (data.get('time') or '').strip()[:10]
        guests = (data.get('guests') or '').strip()[:10] or None
        comment = (data.get('comment') or '').strip()[:1000] or None

        if not name or not phone or not date or not time_:
            return jsonify({'ok': False, 'error': 'Заполните обязательные поля'}), 400

        if not app.config.get('DATABASE_AVAILABLE'):
            app.logger.error('Reservation skipped — DB unavailable')
            return jsonify({'ok': False, 'error': 'Сервис временно недоступен'}), 503

        try:
            res = Reservation(
                name=name, phone=phone, date=date, time=time_,
                guests=guests, comment=comment,
            )
            db.session.add(res)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.error('Reservation DB save failed: %s', exc)
            send_telegram(f'⚠️ Marta: ошибка сохранения брони в БД: {exc}')
            return jsonify({'ok': False, 'error': 'Не удалось сохранить заявку. Позвоните нам: +7 (8212) 29-12-47'}), 500

        lines = [
            '\U0001f4c5 *Заявка на бронирование стола*',
            f'\U0001f194 #{res.id}',
            f'\U0001f464 Имя: {name}',
            f'\U0001f4de Телефон: {phone}',
            f'\U0001f4c6 Дата: {date}',
            f'\U0001f550 Время: {time_}',
        ]
        if guests:
            lines.append(f'\U0001f465 Гостей: {guests}')
        if comment:
            lines.append(f'\U0001f4ac Комментарий: {comment}')

        if send_telegram('\n'.join(lines)):
            res.telegram_sent = True
            db.session.commit()
        else:
            app.logger.warning('Reservation #%s saved, Telegram notification failed', res.id)

        return jsonify({'ok': True})

    @app.errorhandler(404)
    def not_found(_):
        return render_template('404.html'), 404

    @app.cli.command("update-menu")
    @click.argument('point_id', required=False, default=None, type=int)
    @click.argument('price_list_id', required=False, default=None, type=int)
    def update_menu(point_id, price_list_id):
        from app.services.menu import upsert_menu
        from app.services.presto_config import (
            get_point_id,
            get_price_list_id,
            get_price_list_id_delivery,
            get_price_list_id_family,
        )

        point_id = point_id or get_point_id()
        price_list_id = price_list_id or get_price_list_id()
        upsert_menu(
            point_id=point_id,
            price_list_id=price_list_id,
            price_list_id_delivery=get_price_list_id_delivery(),
            price_list_id_family=get_price_list_id_family(),
        )
        click.echo("Menu updated successfully")

    return app
