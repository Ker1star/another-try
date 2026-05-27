import os

from flask import Blueprint, Response, abort, current_app, jsonify, request
import requests

from app import db
from app.models import Category, MenuItem
from app.services.auth import auth as fetch_token
from app.services.delivery_hours import (
    get_delivery_status,
    get_pickup_slots,
    is_delivery_open,
    is_pickup_time_valid,
    parse_pickup_time,
)
from app.services.menu import upsert_menu
from app.services.order import PrestoOrderError, create_order
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


def _resolve_menu_mode():
    mode = (request.args.get('mode') or 'restaurant').strip().lower()
    if mode not in {'restaurant', 'delivery', 'family'}:
        mode = 'restaurant'
    return mode


def _item_visible_for_mode(item, mode):
    if not item.published:
        return False
    if mode == 'family':
        return bool(item.in_family)
    if mode == 'delivery':
        return bool(item.available_for_delivery) and not bool(item.in_family)
    # restaurant
    return bool(item.in_restaurant) and not bool(item.in_family)


def _sort_by_name(entity):
    return (entity.name or '').casefold()


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
        visible_items.extend(_collect_visible_items(child, children_by_parent, mode, visited.copy()))

    return visible_items


def _serialize_menu(mode):
    data = []
    categories = Category.query.order_by(Category.name).all()
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

    token = fetch_token()
    sbis_url = "https://api.sbis.ru/retail/img"
    sbis_resp = requests.get(
        sbis_url,
        headers={"X-SBISAccessToken": token},
        params={'params': params},
        stream=True,
        timeout=30,
    )

    response = Response(
        sbis_resp.raw.read(),
        status=sbis_resp.status_code,
        content_type=sbis_resp.headers.get('Content-Type', 'image/jpeg')
    )
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response
