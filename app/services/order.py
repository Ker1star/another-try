import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from app.models import MenuItem
from app.services.presto_config import get_point_id as resolve_point_id, get_price_list_id as resolve_price_list_id
from app.services.auth import auth as fetch_token
from app.services.delivery_zones import quote as zone_quote
from app.services.menu import upsert_menu

load_dotenv()

logger = logging.getLogger(__name__)

PRESTO_ORDER_URL = os.getenv('PRESTO_ORDER_URL', 'https://api.sbis.ru/retail/order/create')
PRESTO_DELIVERY_COST_URL = os.getenv('PRESTO_DELIVERY_COST_URL', 'https://api.sbis.ru/retail/delivery/cost')
ORDER_LEAD_MINUTES = int(os.getenv('ORDER_LEAD_MINUTES', '15'))
ORDER_TIMEZONE = os.getenv('ORDER_TIMEZONE', 'Europe/Moscow')
ORDER_FALLBACK_UTC_OFFSET_HOURS = int(os.getenv('ORDER_FALLBACK_UTC_OFFSET_HOURS', '3'))
YANDEX_GEOCODER_KEY = os.getenv('YANDEX_GEOCODER_KEY')
YANDEX_GEOCODER_URL = os.getenv('YANDEX_GEOCODER_URL', 'https://geocode-maps.yandex.ru/1.x/')
YANDEX_SUGGEST_KEY = os.getenv('YANDEX_SUGGEST_KEY')
YANDEX_SUGGEST_URL = os.getenv('YANDEX_SUGGEST_URL', 'https://suggest-maps.yandex.ru/v1/suggest')
ORDER_CITY = os.getenv('ORDER_CITY', 'Сыктывкар')


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
    city = (address.get('city') or '').strip() or ORDER_CITY
    street = (address.get('street') or '').strip()
    house = (address.get('house') or '').strip()
    apartment = (address.get('apartment') or '').strip()

    if not street or not house:
        raise ValueError('Для доставки заполните улицу и дом.')

    parts = [city, street, house]
    if apartment:
        parts.append(f'кв. {apartment}')
    return ', '.join(parts)


def _geocode_string(payload):
    """Address string for geocoding: city + street + house, WITHOUT the apartment
    (the flat number only confuses the geocoder)."""
    address = payload.get('address') or {}
    city = (address.get('city') or '').strip() or ORDER_CITY
    street = (address.get('street') or '').strip()
    house = (address.get('house') or '').strip()
    if not street or not house:
        raise ValueError('Для доставки заполните улицу и дом.')
    return ', '.join([city, street, house])


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


def _geocode_address(address_full):
    """Server-side geocode via Yandex HTTP Geocoder. Returns (lat, lon) or None.

    Returns None when no key is configured or the request fails, so callers can
    fall back to client-supplied coordinates.
    """
    if not YANDEX_GEOCODER_KEY:
        return None
    try:
        response = requests.get(
            YANDEX_GEOCODER_URL,
            params={
                'apikey': YANDEX_GEOCODER_KEY,
                'geocode': address_full,
                'format': 'json',
                'results': 1,
            },
            timeout=10,
        )
        response.raise_for_status()
        members = response.json()['response']['GeoObjectCollection']['featureMember']
        if not members:
            return None
        # Yandex Point.pos is "lon lat"; we return (lat, lon).
        lon, lat = (float(value) for value in members[0]['GeoObject']['Point']['pos'].split())
        return (lat, lon)
    except (requests.RequestException, KeyError, ValueError, IndexError):
        logger.warning("Server geocode failed for address=%r", address_full)
        return None


def resolve_delivery_pricing(payload, subtotal):
    """Server-authoritative delivery zone + price for a delivery order.

    Coordinates come from server-side geocoding of the textual address (trusted),
    falling back to client-supplied lat/lon only when the geocoder is unavailable.

    Returns the zone quote dict augmented with resolved lat/lon, or None when the
    coordinates cannot be determined at all (no geocoder key and no client coords) —
    in that case the caller degrades to the pre-zone behaviour instead of blocking
    the order, so a missing key never breaks checkout.

    Raises ValueError only when coordinates ARE known and the address is outside all
    zones or below the zone minimum.
    """
    try:
        geocode_str = _geocode_string(payload)
    except ValueError:
        geocode_str = None

    coords = _geocode_address(geocode_str) if geocode_str else None
    if coords is None:
        try:
            coords = (float(payload['lat']), float(payload['lon']))
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Delivery zone undetermined (no geocoder key and no client coords); "
                "skipping zone pricing for this order."
            )
            return None

    lat, lon = coords
    quote = zone_quote(lat, lon, subtotal)
    if not quote.get('inZone'):
        raise ValueError('Этот адрес вне зоны доставки. Пожалуйста, оформите самовывоз.')
    if quote.get('belowMin'):
        raise ValueError(f'Минимальная сумма заказа для доставки — {quote["minOrder"]:.0f} ₽.')

    return {**quote, 'lat': lat, 'lon': lon}


def geocode_quote(address, subtotal):
    """Live delivery preview for the order form: server-geocode the address, then
    zone-quote. Never raises — returns a status dict the frontend renders directly.

    `reason` distinguishes the failure modes so the frontend can act correctly:
      - 'incomplete'  — city/street/house not filled in yet
      - 'no_geocoder' — geocoder key not configured (degrade: order still allowed)
      - 'not_found'   — geocoder ran but couldn't resolve the address (fix address)
    """
    try:
        geocode_str = _geocode_string({'address': address})
    except ValueError as exc:
        return {'found': False, 'reason': 'incomplete', 'error': str(exc)}

    if not YANDEX_GEOCODER_KEY:
        return {'found': False, 'reason': 'no_geocoder'}

    coords = _geocode_address(geocode_str)
    if coords is None:
        return {
            'found': False,
            'reason': 'not_found',
            'error': 'Не удалось определить адрес. Проверьте улицу и дом.',
        }

    lat, lon = coords
    return {'found': True, 'lat': lat, 'lon': lon, **zone_quote(lat, lon, subtotal)}


def suggest_address(query):
    """Street/address autocomplete via Yandex Suggest API, biased to the delivery
    city. Returns a list of {title, subtitle} dicts; [] when no key or on error."""
    query = (query or '').strip()
    if not query or not YANDEX_SUGGEST_KEY:
        return []
    try:
        response = requests.get(
            YANDEX_SUGGEST_URL,
            params={
                'apikey': YANDEX_SUGGEST_KEY,
                'text': f'{ORDER_CITY}, {query}',
                'lang': 'ru_RU',
                'results': 7,
            },
            timeout=8,
        )
        response.raise_for_status()
        results = response.json().get('results', [])
    except (requests.RequestException, ValueError):
        logger.warning("Suggest request failed for query=%r", query)
        return []

    suggestions = []
    for item in results:
        title = (item.get('title') or {}).get('text') or ''
        subtitle = (item.get('subtitle') or {}).get('text') or ''
        if title:
            suggestions.append({'title': title, 'subtitle': subtitle})
    return suggestions


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

    service_type = (payload.get('serviceType') or 'delivery').strip().lower()
    is_pickup = service_type == 'pickup'

    if is_pickup:
        delivery = {
            'isPickup': True,
            'paymentType': payment_type,
        }
        order_datetime = _format_order_datetime(payload.get('pickupTime') or payload.get('datetime'))
    else:
        address_full = _build_address_full(payload)
        address_json = payload.get('addressJson')
        if isinstance(address_json, str):
            address_json = address_json.strip() or None
            if address_json:
                try:
                    address_json = json.loads(address_json)
                except json.JSONDecodeError:
                    raise ValueError('Некорректный addressJson для доставки.')

        subtotal = sum(
            float(menu_map[item['id']].price or 0) * max(1, int(item.get('qty') or 1))
            for item in raw_items
            if item.get('id') is not None
        )
        pricing = resolve_delivery_pricing(payload, subtotal)

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
        if pricing is not None:
            # TENTATIVE Saby field name — verify on the first real server order whether
            # Saby honours it on the receipt/courier sheet; YooKassa charge is authoritative.
            delivery['deliveryCost'] = pricing['deliveryCost']

        if address_json:
            delivery['addressJSON'] = json.dumps(address_json, ensure_ascii=False)

        order_datetime = _format_order_datetime(payload.get('datetime'))

    change_amount = payload.get('changeAmount')
    if payment_type == 'cash' and change_amount:
        delivery['changeAmount'] = float(change_amount)

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
        'datetime': order_datetime,
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
