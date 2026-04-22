import os

from flask import Blueprint, Response, abort, current_app, jsonify, request
import requests

from app.models import Category
from app.services.auth import auth as fetch_token
from app.services.menu import upsert_menu
from app.services.order import PrestoOrderError, create_order
from app.services.presto_config import get_point_id, get_price_list_id

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
        return True

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


@api_bp.route('/menu', methods=['GET'])
def menu_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    data = []
    parents = Category.query.filter_by(parent_sbis_id=None).order_by(Category.name).all()
    for cat in parents:
        data.append({
            'id': cat.sbis_id,
            'name': cat.name,
            'isParent': True,
            'hierarchicalId': cat.sbis_id,
            'hierarchicalParent': None
        })
        for item in cat.items:
            data.append({
                'id': item.sbis_id,
                'prestoId': item.presto_id,
                'externalId': item.external_id,
                'nomNumber': item.nom_number,
                'name': item.name,
                'isParent': False,
                'hierarchicalId': item.sbis_id,
                'hierarchicalParent': cat.sbis_id,
                'price': float(item.price or 0),
                'description_simple': item.description_simple,
                'images': _serialize_image_path(item.image_path),
                'attributes': {'outQuantity': item.out_quantity}
            })
    return jsonify({'data': data})


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
    upsert_menu(point_id=point_id, price_list_id=price_list_id)
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
    upsert_menu(point_id=point_id, price_list_id=price_list_id)
    return jsonify({
        'status': 'ok',
        'pointId': point_id,
        'priceListId': price_list_id,
    })


@api_bp.route('/orders', methods=['POST'])
def create_order_route():
    unavailable_response = _require_database()
    if unavailable_response:
        return unavailable_response

    payload = request.get_json(silent=True) or {}
    try:
        result = create_order(payload, base_url=request.host_url.rstrip('/'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except PrestoOrderError as exc:
        return jsonify({'error': str(exc), 'details': exc.details}), exc.status_code

    return jsonify({'status': 'ok', 'order': result})


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
