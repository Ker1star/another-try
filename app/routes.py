import hashlib
import json
import os
import time

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, session
import requests

from app import db
from app.models import Category, MenuItem, PendingOrder
from app.services.auth import auth as fetch_token
from app.services.delivery_hours import (
    get_delivery_status,
    get_pickup_slots,
    is_delivery_open,
    is_pickup_time_valid,
    parse_pickup_time,
)
from app.services.menu import upsert_menu
from app.services.order import (
    PrestoOrderError,
    calculate_order_total,
    create_order,
    geocode_quote,
    lunch_window,
    suggest_address,
)
from app.services.payment import create_payment, handle_webhook
from app.services.presto_config import (
    get_point_id,
    get_price_list_id,
    get_price_list_id_delivery,
    get_price_list_id_family,
)

api_bp = Blueprint('api', __name__)
presto_bp = Blueprint('presto', __name__)


def _serialize_image_path(image_path):
    if not image_path:
        return []
    if image_path.startswith('http://') or image_path.startswith('https://') or image_path.startswith('/'):
        return [image_path]
    if image_path.startswith('images/'):
        return [f'/imgx/{image_path}?w=640']
    return [f'/static/{image_path}']


def _authorize_internal_task():
    cron_secret = os.getenv('CRON_SECRET')
    if not cron_secret:
        current_app.logger.error('CRON_SECRET not configured — refusing internal task')
        return False

    auth_header = request.headers.get('Authorization', '')
    return auth_header == f'Bearer {cron_secret}'


def _database_error_response():
    return jsonify({
        'error': 'Database is not available.',
        'details': current_app.config.get('DATABASE_ERROR'),
    }), 503


def _require_database():
    if current_app.config.get('DATABASE_AVAILABLE'):
        return None

    return _database_error_response()


def _require_admin():
    """Returns None when the admin session is active, else a 401 response."""
    if session.get('admin') is True:
        return None
    return jsonify({'error': 'Unauthorized'}), 401


def _resolve_menu_mode():
    mode = (request.args.get('mode') or 'restaurant').strip().lower()
    if mode not in {'restaurant', 'delivery', 'family'}:
        mode = 'restaurant'
    return mode


def _item_in_mode(item, mode):
    """Price-list membership for a mode (published + flag), ignoring admin hidden."""
    if not item.published:
        return False
    if mode == 'family':
        return bool(item.in_family)
    if mode == 'delivery':
        return bool(item.available_for_delivery) and not bool(item.in_family)
    # restaurant
    return bool(item.in_restaurant) and not bool(item.in_family)


def _item_visible_for_mode(item, mode):
    return _item_in_mode(item, mode) and not getattr(item, 'hidden', False)


def _sort_by_name(entity):
    # Admin sort_order first, then name as a stable tiebreaker.
    return (getattr(entity, 'sort_order', 0) or 0, (entity.name or '').casefold())


def _serialize_menu_item(item, parent_sbis_id):
    return {
        'id': item.sbis_id,
        'prestoId': item.presto_id,
        'externalId': item.external_id,
        'nomNumber': item.nom_number,
        'name': item.name,
        'isParent': False,
        'hierarchicalId': item.sbis_id,
        'hierarchicalParent': parent_sbis_id,
        'price': float(item.price or 0),
        'description_simple': item.description_simple,
        'images': _serialize_image_path(item.image_path),
        'availableForDelivery': bool(item.available_for_delivery),
        'attributes': {'outQuantity': item.out_quantity}
    }


def _collect_visible_items(category, children_by_parent, mode, visited=None):
    visited = visited or set()
    if category.sbis_id in visited:
        return []

    visited.add(category.sbis_id)
    visible_items = [
        item for item in sorted(category.items, key=_sort_by_name)
        if _item_visible_for_mode(item, mode)
    ]

    for child in sorted(children_by_parent.get(category.sbis_id, []), key=_sort_by_name):
        if getattr(child, 'hidden', False):
            continue
        visible_items.extend(_collect_visible_items(child, children_by_parent, mode, visited.copy()))

    return visible_items


def _serialize_menu(mode):
    data = []
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    category_ids = {category.sbis_id for category in categories}
    children_by_parent = {}
    for category in categories:
        if category.parent_sbis_id is not None:
            children_by_parent.setdefault(category.parent_sbis_id, []).append(category)

    parents = [
        category for category in categories
        if category.parent_sbis_id is None or category.parent_sbis_id not in category_ids
    ]

    for cat in sorted(parents, key=_sort_by_name):
        if getattr(cat, 'hidden', False):
            continue
        visible_items = _collect_visible_items(cat, children_by_parent, mode)
        if not visible_items:
            continue

        data.append({
            'id': cat.sbis_id,
            'name': cat.name,
            'isParent': True,
            'hierarchicalId': cat.sbis_id,
            'hierarchicalParent': None
        })
        for item in visible_items:
            data.append(_serialize_menu_item(item, cat.sbis_id))
    return data


@api_bp.route('/menu', methods=['GET'])
def menu_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    mode = _resolve_menu_mode()
    return jsonify({'mode': mode, 'data': _serialize_menu(mode)})


# --- Admin (single-password session) ---

def _collect_admin_items(category, children_by_parent, mode, visited=None):
    """Items of a top-level category for a mode, flattening children like the public
    menu — but INCLUDING hidden items so admin can toggle them back."""
    visited = visited or set()
    if category.sbis_id in visited:
        return []
    visited.add(category.sbis_id)
    items = [item for item in sorted(category.items, key=_sort_by_name) if _item_in_mode(item, mode)]
    for child in sorted(children_by_parent.get(category.sbis_id, []), key=_sort_by_name):
        items.extend(_collect_admin_items(child, children_by_parent, mode, visited.copy()))
    return items


def _serialize_admin_menu(mode):
    """Same grouping as the public site for the given mode, but with hidden items
    included and flagged, so the admin view matches what customers see."""
    categories = Category.query.order_by(Category.sort_order, Category.name).all()
    category_ids = {c.sbis_id for c in categories}
    children_by_parent = {}
    for c in categories:
        if c.parent_sbis_id is not None:
            children_by_parent.setdefault(c.parent_sbis_id, []).append(c)
    parents = [c for c in categories if c.parent_sbis_id is None or c.parent_sbis_id not in category_ids]

    data = []
    for cat in sorted(parents, key=_sort_by_name):
        items = _collect_admin_items(cat, children_by_parent, mode)
        if not items:
            continue
        data.append({
            'id': cat.sbis_id,
            'name': cat.name,
            'hidden': bool(cat.hidden),
            'items': [
                {'id': i.sbis_id, 'name': i.name, 'hidden': bool(i.hidden), 'price': float(i.price or 0)}
                for i in items
            ],
        })
    return data


@api_bp.route('/admin/menu', methods=['GET'])
def admin_menu_route():
    unauth = _require_admin()
    if unauth:
        return unauth
    db_unavailable = _require_database()
    if db_unavailable:
        return db_unavailable

    mode = (request.args.get('mode') or 'restaurant').strip().lower()
    if mode not in {'restaurant', 'delivery', 'family'}:
        mode = 'restaurant'
    return jsonify({'mode': mode, 'categories': _serialize_admin_menu(mode)})


@api_bp.route('/admin/save', methods=['POST'])
def admin_save_route():
    unauth = _require_admin()
    if unauth:
        return unauth
    db_unavailable = _require_database()
    if db_unavailable:
        return db_unavailable

    payload = request.get_json(silent=True) or {}
    categories = payload.get('categories') or []
    cat_map = {c.sbis_id: c for c in Category.query.all()}
    item_map = {i.sbis_id: i for i in MenuItem.query.all()}

    for cat_index, cat_entry in enumerate(categories):
        cat = cat_map.get(cat_entry.get('id'))
        if cat is not None:
            cat.sort_order = cat_index
            cat.hidden = bool(cat_entry.get('hidden'))
        for item_index, item_entry in enumerate(cat_entry.get('items') or []):
            item = item_map.get(item_entry.get('id'))
            if item is not None:
                item.sort_order = item_index
                item.hidden = bool(item_entry.get('hidden'))

    db.session.commit()
    return jsonify({'status': 'ok'})


@api_bp.route('/admin/orders', methods=['GET'])
def admin_orders_route():
    unauth = _require_admin()
    if unauth:
        return unauth
    db_unavailable = _require_database()
    if db_unavailable:
        return db_unavailable

    orders = PendingOrder.query.order_by(PendingOrder.created_at.desc()).limit(50).all()
    out = []
    for order in orders:
        try:
            p = json.loads(order.payload_json)
        except Exception:
            p = {}
        addr = p.get('address') or {}
        out.append({
            'id': order.id,
            'status': order.status,
            'created': order.created_at.isoformat() if order.created_at else None,
            'service': p.get('serviceType'),
            'name': p.get('customerName'),
            'phone': p.get('phone'),
            'address': ', '.join(x for x in [addr.get('street'), addr.get('house')] if x),
        })
    return jsonify({'orders': out})


@api_bp.route('/menu/delivery-availability', methods=['POST'])
def update_delivery_availability_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    if not _authorize_internal_task():
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    item_ids = payload.get('ids') or []
    available_for_delivery = payload.get('availableForDelivery')

    if not isinstance(item_ids, list) or not item_ids:
        return jsonify({'error': 'ids must be a non-empty array'}), 400
    if not isinstance(available_for_delivery, bool):
        return jsonify({'error': 'availableForDelivery must be boolean'}), 400

    updated = MenuItem.query.filter(MenuItem.sbis_id.in_(item_ids)).update(
        {'available_for_delivery': available_for_delivery},
        synchronize_session=False,
    )
    db.session.commit()
    return jsonify({
        'status': 'ok',
        'updated': updated,
        'availableForDelivery': available_for_delivery,
    })


@api_bp.route('/update-menu', methods=['POST'])
def update_menu_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    if not _authorize_internal_task():
        return jsonify({'error': 'Unauthorized'}), 401

    json_data = request.get_json(silent=True) or {}
    point_id = json_data.get('point_id', get_point_id())
    price_list_id = json_data.get('price_list_id', get_price_list_id())
    price_list_id_delivery = json_data.get('price_list_id_delivery', get_price_list_id_delivery())
    price_list_id_family = json_data.get('price_list_id_family', get_price_list_id_family())
    try:
        upsert_menu(
            point_id=point_id,
            price_list_id=price_list_id,
            price_list_id_delivery=price_list_id_delivery,
            price_list_id_family=price_list_id_family,
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    return jsonify({'status': 'ok'})


@api_bp.route('/tasks/sync-menu', methods=['GET'])
def sync_menu_task():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    if not _authorize_internal_task():
        return jsonify({'error': 'Unauthorized'}), 401

    point_id = get_point_id()
    price_list_id = get_price_list_id()
    price_list_id_delivery = get_price_list_id_delivery()
    price_list_id_family = get_price_list_id_family()
    try:
        upsert_menu(
            point_id=point_id,
            price_list_id=price_list_id,
            price_list_id_delivery=price_list_id_delivery,
            price_list_id_family=price_list_id_family,
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    return jsonify({
        'status': 'ok',
        'pointId': point_id,
        'priceListId': price_list_id,
        'priceListIdDelivery': price_list_id_delivery,
        'priceListIdFamily': price_list_id_family,
    })


@api_bp.route('/delivery/status', methods=['GET'])
def delivery_status_route():
    return jsonify(get_delivery_status())


@api_bp.route('/lunch/status', methods=['GET'])
def lunch_status_route():
    return jsonify(lunch_window())


@api_bp.route('/pickup/slots', methods=['GET'])
def pickup_slots_route():
    status = get_delivery_status()
    return jsonify({
        'available': status['available'],
        'opensAt': status['opensAt'],
        'closesAt': status['closesAt'],
        'leadMinutes': status['pickupLeadMinutes'],
        'slots': get_pickup_slots() if status['available'] else [],
    })


@api_bp.route('/delivery/quote', methods=['POST'])
def delivery_quote_route():
    payload = request.get_json(silent=True) or {}
    try:
        subtotal = calculate_order_total(payload.get('items') or [])
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify(geocode_quote(payload.get('address') or {}, subtotal))


@api_bp.route('/suggest', methods=['GET'])
def suggest_route():
    return jsonify(suggest_address(request.args.get('q', '')))


def _validate_service(payload):
    """Returns (service_type, error_response_or_none)."""
    service_type = (payload.get('serviceType') or 'delivery').strip().lower()
    if service_type not in {'delivery', 'pickup'}:
        return service_type, (jsonify({'error': 'Неизвестный тип заказа.'}), 400)

    if not is_delivery_open():
        status = get_delivery_status()
        return service_type, (jsonify({
            'error': f'Заказы принимаются с {status["opensAt"]} до {status["closesAt"]}. Загляните в рабочие часы.',
            'deliveryStatus': status,
        }), 400)

    if service_type == 'pickup':
        pickup_dt = parse_pickup_time(payload.get('pickupTime'))
        if not is_pickup_time_valid(pickup_dt):
            status = get_delivery_status()
            return service_type, (jsonify({
                'error': f'Выберите время самовывоза не раньше чем через {status["pickupLeadMinutes"]} минут и до {status["closesAt"]}.',
                'deliveryStatus': status,
            }), 400)

    return service_type, None


@api_bp.route('/orders', methods=['POST'])
def create_order_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    payload = request.get_json(silent=True) or {}
    _, err = _validate_service(payload)
    if err:
        return err
    try:
        result = create_order(payload, base_url=request.host_url.rstrip('/'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except PrestoOrderError as exc:
        current_app.logger.error("Order create failed: %s | details=%s", exc, exc.details)
        return jsonify({'error': str(exc), 'details': exc.details}), exc.status_code

    return jsonify({'status': 'ok', 'order': result})


@api_bp.route('/payments', methods=['POST'])
def create_payment_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    payload = request.get_json(silent=True) or {}
    _, err = _validate_service(payload)
    if err:
        return err
    try:
        result = create_payment(payload, base_url=request.host_url.rstrip('/'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except RuntimeError as exc:
        current_app.logger.error("Payment setup error: %s", exc)
        return jsonify({'error': 'Онлайн-оплата временно недоступна.'}), 503

    return jsonify(result)


@api_bp.route('/payments/webhook', methods=['POST'])
def payment_webhook_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    remote_ip = (
        request.headers.get('X-Real-IP')
        or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        or request.remote_addr
    )

    from app import send_telegram

    try:
        result = handle_webhook(request.get_data(), remote_ip=remote_ip)
    except PermissionError as exc:
        current_app.logger.warning("Webhook rejected: %s", exc)
        return jsonify({'error': 'Forbidden'}), 403
    except ValueError as exc:
        current_app.logger.error("Webhook payload error: %s", exc)
        return jsonify({'error': str(exc)}), 400
    except PrestoOrderError as exc:
        current_app.logger.error("SBIS order failed in webhook: %s | details=%s", exc, exc.details)
        send_telegram(f'🚨 *Marta: оплата прошла, заказ НЕ создан в Saby*\nОшибка: `{exc}`\nДетали: `{exc.details}`\n\nПроверьте PendingOrder в БД и создайте вручную.')
        return jsonify({'error': str(exc)}), 500
    except Exception as exc:
        current_app.logger.exception("Unexpected webhook error")
        send_telegram(f'🚨 *Marta: непредвиденная ошибка webhook ЮКассы*\n`{type(exc).__name__}: {exc}`')
        return jsonify({'error': 'Internal error'}), 500

    return jsonify(result)


@api_bp.route('/payments/<tracking_id>/status', methods=['GET'])
def payment_status_route(tracking_id):
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    from app.models import PendingOrder
    pending = PendingOrder.query.filter_by(tracking_id=tracking_id).first()
    if not pending:
        return jsonify({'status': 'unknown'}), 404
    response = {'status': pending.status}
    if pending.status == 'failed' and pending.error:
        response['error'] = pending.error
    return jsonify(response)


@api_bp.route('/relay/max', methods=['POST'])
def max_relay_route():
    """Приём уведомлений MAX с офисного ПК и пересылка в Telegram.

    Комп без VPN не достучится до api.telegram.org напрямую, поэтому шлёт
    сюда обычным HTTPS, а сервер отправляет через send_telegram (с прокси).
    """
    secret = os.getenv('NOTIFY_RELAY_SECRET')
    auth = request.headers.get('Authorization', '')
    if not secret or auth != f'Bearer {secret}':
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    _touch_relay_heartbeat()  # любой контакт с компа = комп жив

    if payload.get('heartbeat'):
        return jsonify({'ok': True})

    title = (payload.get('title') or '').strip()
    text = (payload.get('text') or '').strip()
    if not title and not text:
        return jsonify({'error': 'empty'}), 400

    from app import send_telegram

    message = f'📨 MAX — {title}\n{text}'.strip()[:4000]
    chat_id = os.getenv('MAX_RELAY_CHAT_ID')  # ТГ получателя; без него — TELEGRAM_CHAT_ID
    ok = send_telegram(message, chat_id=chat_id, parse_mode=None)
    return jsonify({'ok': ok}), 200 if ok else 502


def _relay_state_path():
    return os.path.join(current_app.instance_path, 'max_relay_heartbeat.json')


def _touch_relay_heartbeat():
    try:
        state = _read_relay_state()
        state['ts'] = time.time()
        os.makedirs(current_app.instance_path, exist_ok=True)
        with open(_relay_state_path(), 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
    except Exception:
        current_app.logger.exception('relay heartbeat write failed')


def _read_relay_state():
    try:
        with open(_relay_state_path(), encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return {}


@api_bp.route('/tasks/relay-watchdog', methods=['GET'])
def relay_watchdog_task():
    """Крон-проверка: если комп с реле MAX молчит дольше порога — алерт в ТГ.

    crontab на VDS: */10 * * * * curl -s -H "Authorization: Bearer $CRON_SECRET" \
        https://ДОМЕН/api/tasks/relay-watchdog
    """
    if not _authorize_internal_task():
        return jsonify({'error': 'Unauthorized'}), 401

    state = _read_relay_state()
    if not state.get('ts'):
        # Реле ещё ни разу не выходило на связь — нечего сторожить.
        return jsonify({'status': 'no-heartbeat-yet'})

    from app import send_telegram

    timeout_minutes = int(os.getenv('MAX_RELAY_TIMEOUT_MIN', '15'))
    silence_minutes = (time.time() - state['ts']) / 60
    alerted = bool(state.get('alerted'))

    if silence_minutes > timeout_minutes and not alerted:
        send_telegram(
            f'🔌 Реле MAX молчит {silence_minutes:.0f} мин — проверь дежурный комп '
            '(питание, Edge, скрипт). Уведомления из MAX сейчас НЕ пересылаются!',
            parse_mode=None,
        )
        state['alerted'] = True
    elif silence_minutes <= timeout_minutes and alerted:
        send_telegram('✅ Реле MAX снова на связи.', parse_mode=None)
        state['alerted'] = False
    else:
        return jsonify({'status': 'ok', 'silenceMinutes': round(silence_minutes, 1), 'alerted': alerted})

    try:
        with open(_relay_state_path(), 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
    except Exception:
        current_app.logger.exception('relay watchdog state write failed')
    return jsonify({'status': 'ok', 'silenceMinutes': round(silence_minutes, 1), 'alerted': state['alerted']})


@api_bp.route('/health', methods=['GET'])
def health_route():
    database_available = current_app.config.get('DATABASE_AVAILABLE')
    payload = {
        'status': 'ok' if database_available else 'degraded',
        'databaseAvailable': database_available,
    }
    if not database_available:
        payload['databaseError'] = current_app.config.get('DATABASE_ERROR')
    return jsonify(payload), 200 if database_available else 503


@presto_bp.route('/img')
def proxy_image():
    params = request.args.get('params')
    if not params:
        abort(400, "Missing params")

    width = max(100, min(request.args.get('w', default=640, type=int), 1600))
    cache_dir = os.path.join(current_app.static_folder, '.imgcache', 'sbis')
    cache_key = hashlib.sha1(params.encode('utf-8')).hexdigest()
    cache_path = os.path.join(cache_dir, f'{cache_key}_{width}.webp')

    if os.path.isfile(cache_path):
        return send_file(cache_path, mimetype='image/webp',
                         max_age=86400 * 30, conditional=True)

    token = fetch_token()
    sbis_url = "https://api.sbis.ru/retail/img"
    sbis_resp = requests.get(
        sbis_url,
        headers={"X-SBISAccessToken": token},
        params={'params': params},
        stream=True,
        timeout=30,
    )
    body = sbis_resp.raw.read()

    if sbis_resp.status_code == 200 and body:
        try:
            from io import BytesIO

            from PIL import Image

            os.makedirs(cache_dir, exist_ok=True)
            with Image.open(BytesIO(body)) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                if img.width > width:
                    img = img.resize(
                        (width, round(img.height * width / img.width)),
                        Image.LANCZOS,
                    )
                img.save(cache_path, 'WEBP', quality=82, method=4)
            return send_file(cache_path, mimetype='image/webp',
                             max_age=86400 * 30, conditional=True)
        except Exception as exc:
            current_app.logger.error('sbis img resize failed: %s', exc)

    response = Response(
        body,
        status=sbis_resp.status_code,
        content_type=sbis_resp.headers.get('Content-Type', 'image/jpeg')
    )
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response
