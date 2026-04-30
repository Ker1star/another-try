import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from app.models import MenuItem
from app.services.presto_config import get_point_id as resolve_point_id, get_price_list_id as resolve_price_list_id
from app.services.auth import auth as fetch_token
from app.services.menu import upsert_menu

load_dotenv()

logger = logging.getLogger(__name__)

PRESTO_ORDER_URL = os.getenv('PRESTO_ORDER_URL', 'https://api.sbis.ru/retail/order/create')
PRESTO_DELIVERY_COST_URL = os.getenv('PRESTO_DELIVERY_COST_URL', 'https://api.sbis.ru/retail/delivery/cost')
ORDER_LEAD_MINUTES = int(os.getenv('ORDER_LEAD_MINUTES', '15'))
ORDER_TIMEZONE = os.getenv('ORDER_TIMEZONE', 'Europe/Moscow')
ORDER_FALLBACK_UTC_OFFSET_HOURS = int(os.getenv('ORDER_FALLBACK_UTC_OFFSET_HOURS', '3'))


class PrestoOrderError(Exception):
    def __init__(self, message, *, details=None, status_code=502):
        super().__init__(message)
        self.details = details
        self.status_code = status_code


def get_point_id():
    return resolve_point_id()


def get_price_list_id():
    return resolve_price_list_id()


def _get_order_timezone():
    try:
        return ZoneInfo(ORDER_TIMEZONE)
    except Exception:
        logger.warning(
            "Invalid ORDER_TIMEZONE=%s, falling back to UTC%+d",
            ORDER_TIMEZONE,
            ORDER_FALLBACK_UTC_OFFSET_HOURS,
        )
        return timezone(timedelta(hours=ORDER_FALLBACK_UTC_OFFSET_HOURS))


def _now_in_order_timezone():
    return datetime.now(_get_order_timezone())


def _compact(data):
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            compacted = _compact(value)
            if compacted is not None and compacted != '' and compacted != []:
                result[key] = compacted
        return result

    if isinstance(data, list):
        return [c for item in data if (c := _compact(item)) is not None]

    return data


def _extract_saby_error_message(response_data):
    if not isinstance(response_data, dict):
        if isinstance(response_data, str):
            return response_data
        return None

    error = response_data.get('error')
    if not isinstance(error, dict):
        raw = response_data.get('raw')
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    return error.get('details') or error.get('message')


def _normalize_phone(phone):
    phone = (phone or '').strip()
    if not phone:
        raise ValueError('Укажите телефон клиента.')
    return phone


def _build_address_full(payload):
    address = payload.get('address') or {}
    city = (address.get('city') or '').strip()
    street = (address.get('street') or '').strip()
    house = (address.get('house') or '').strip()
    apartment = (address.get('apartment') or '').strip()

    if not city or not street or not house:
        raise ValueError('Для доставки заполните город, улицу и дом.')

    parts = [city, street, house]
    if apartment:
        parts.append(f'кв. {apartment}')
    return ', '.join(parts)


def _format_order_datetime(raw_value):
    if raw_value:
        try:
            order_datetime = datetime.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError('Некорректная дата заказа.') from exc

        if order_datetime.tzinfo is None:
            order_datetime = order_datetime.replace(tzinfo=_get_order_timezone())
        else:
            order_datetime = order_datetime.astimezone(_get_order_timezone())

        if order_datetime <= _now_in_order_timezone():
            raise ValueError('Время заказа должно быть позже текущего.')

        return order_datetime.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')

    return (_now_in_order_timezone() + timedelta(minutes=ORDER_LEAD_MINUTES)).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')


def _request_headers():
    return {
        'Content-Type': 'application/json',
        'X-SBISAccessToken': fetch_token(),
    }


def _fetch_delivery_context(point_id, address_full, address_json=None):
    address_payload = address_json if address_json is not None else address_full
    params = {
        'pointId': point_id,
        'address': json.dumps(address_payload, ensure_ascii=False) if isinstance(address_payload, dict) else address_payload,
    }
    response = requests.get(
        PRESTO_DELIVERY_COST_URL,
        headers={'X-SBISAccessToken': fetch_token()},
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _load_menu_items(raw_items):
    item_ids = [item.get('id') for item in raw_items if item.get('id') is not None]
    if not item_ids:
        raise ValueError('Корзина пуста.')

    menu_items = MenuItem.query.filter(MenuItem.sbis_id.in_(item_ids)).all()
    menu_map = {item.sbis_id: item for item in menu_items}
    missing_ids = [item_id for item_id in item_ids if item_id not in menu_map]
    if missing_ids:
        raise ValueError('Часть позиций из корзины не найдена в локальном меню. Обновите меню и повторите попытку.')
    unavailable = [
        item.name for item in menu_items
        if not item.published or not item.available_for_delivery
    ]
    if unavailable:
        names = ', '.join(unavailable[:3])
        suffix = ' и другие позиции' if len(unavailable) > 3 else ''
        raise ValueError(f'Эти позиции недоступны для доставки: {names}{suffix}.')
    return menu_map


def _refresh_identifiers_if_needed(raw_items, menu_map, point_id, price_list_id):
    needs_refresh = False
    for item in raw_items:
        menu_item = menu_map[item['id']]
        has_identifier = any([
            item.get('prestoId'),
            item.get('externalId'),
            item.get('nomNumber'),
            menu_item.presto_id,
            menu_item.external_id,
            menu_item.nom_number,
        ])
        if not has_identifier:
            needs_refresh = True
            break

    if not needs_refresh:
        return menu_map

    upsert_menu(point_id=point_id, price_list_id=price_list_id)
    return _load_menu_items(raw_items)


def _build_nomenclatures(raw_items, menu_map, price_list_id):
    nomenclatures = []

    for item in raw_items:
        menu_item = menu_map[item['id']]
        count = item.get('qty') or 1
        if count <= 0:
            raise ValueError('Количество позиции должно быть больше нуля.')

        presto_id = item.get('prestoId') or menu_item.presto_id
        external_id = item.get('externalId') or menu_item.external_id
        nom_number = item.get('nomNumber') or menu_item.nom_number
        if not any([presto_id, external_id, nom_number]):
            raise ValueError(f'Не удалось определить идентификатор товара "{menu_item.name}" для заказа в Saby.')

        nomenclature = {
            'count': float(count),
            'cost': float(item.get('price') or menu_item.price or 0),
            'name': menu_item.name,
            'priceListId': price_list_id,
            'hierarchicalId': item.get('hierarchicalId') or menu_item.sbis_id,
        }
        if presto_id is not None:
            nomenclature['id'] = presto_id
        elif nom_number:
            nomenclature['nomNumber'] = nom_number
        else:
            nomenclature['externalId'] = external_id

        nomenclatures.append(nomenclature)

    return nomenclatures


def calculate_order_total(raw_items: list) -> float:
    """Validate cart items and return total using DB prices (not client-submitted prices)."""
    menu_map = _load_menu_items(raw_items)
    return sum(
        float(menu_map[item['id']].price or 0) * max(1, int(item.get('qty') or 1))
        for item in raw_items
        if item.get('id') is not None
    )


def build_order_payload(payload, *, base_url=None):
    raw_items = payload.get('items') or []
    point_id = get_point_id()
    price_list_id = get_price_list_id()
    menu_map = _load_menu_items(raw_items)
    menu_map = _refresh_identifiers_if_needed(raw_items, menu_map, point_id, price_list_id)

    customer_name = (payload.get('customerName') or '').strip()
    if not customer_name:
        raise ValueError('Укажите имя клиента.')

    payment_type = (payload.get('paymentType') or 'cash').strip()
    if payment_type not in {'cash', 'card', 'online'}:
        raise ValueError('Неподдерживаемый способ оплаты.')

    address_full = _build_address_full(payload)
    address_json = payload.get('addressJson')
    if isinstance(address_json, str):
        address_json = address_json.strip() or None
        if address_json:
            try:
                address_json = json.loads(address_json)
            except json.JSONDecodeError:
                raise ValueError('Некорректный addressJson для доставки.')

    delivery_context = {}
    try:
        delivery_context = _fetch_delivery_context(point_id, address_full, address_json)
    except requests.RequestException:
        delivery_context = {}

    delivery = {
        'isPickup': False,
        'addressFull': address_full,
        'paymentType': payment_type,
        'persons': payload.get('persons'),
        'district': payload.get('district') or delivery_context.get('district'),
    }

    change_amount = payload.get('changeAmount')
    if payment_type == 'cash' and change_amount:
        delivery['changeAmount'] = float(change_amount)

    if address_json:
        delivery['addressJSON'] = json.dumps(address_json, ensure_ascii=False)

    if payment_type == 'online' and base_url:
        delivery['shopURL'] = base_url
        delivery['successURL'] = f'{base_url}/order?payment=success'
        delivery['errorURL'] = f'{base_url}/order?payment=error'

    order_payload = {
        'product': 'delivery',
        'pointId': point_id,
        'comment': (payload.get('comment') or '').strip(),
        'customer': {
            'externalId': str(payload.get('customerExternalId') or uuid.uuid4()),
            'name': customer_name,
            'phone': _normalize_phone(payload.get('phone')),
            'email': (payload.get('email') or '').strip(),
            'lastname': (payload.get('lastName') or '').strip(),
            'patronymic': (payload.get('patronymic') or '').strip(),
        },
        'datetime': _format_order_datetime(payload.get('datetime')),
        'nomenclatures': _build_nomenclatures(raw_items, menu_map, price_list_id),
        'delivery': delivery,
    }

    return _compact(order_payload)


def create_order(payload, *, base_url=None):
    order_payload = build_order_payload(payload, base_url=base_url)
    logger.info(
        "Sending order to Saby with datetime=%s timezone=%s local_now=%s",
        order_payload.get('datetime'),
        ORDER_TIMEZONE,
        _now_in_order_timezone().isoformat(),
    )
    try:
        response = requests.post(
            PRESTO_ORDER_URL,
            headers=_request_headers(),
            json=order_payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.exception("Order request to Saby failed")
        raise PrestoOrderError(
            f'Не удалось отправить заказ в Saby: {exc}',
            details={'requestError': str(exc)},
            status_code=502,
        ) from exc

    try:
        response_data = response.json()
    except ValueError:
        response_data = {'raw': response.text}

    if response.status_code >= 400:
        logger.error("Saby order create failed with status %s: %s", response.status_code, response_data)
        raise PrestoOrderError(
            _extract_saby_error_message(response_data) or 'Saby вернул ошибку при создании заказа.',
            details=response_data,
            status_code=502,
        )

    if isinstance(response_data, dict) and response_data.get('error'):
        logger.error("Saby order create returned error payload: %s", response_data)
        raise PrestoOrderError(
            _extract_saby_error_message(response_data) or 'Saby вернул ошибку при создании заказа.',
            details=response_data,
            status_code=502,
        )

    return response_data
