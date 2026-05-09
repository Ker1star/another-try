import json
import logging
import os
import uuid
from ipaddress import ip_address, ip_network

from yookassa import Configuration, Payment

from app import db
from app.models import PendingOrder
from app.services.order import (
    PrestoOrderError,
    _load_menu_items,
    build_order_payload,
    create_order,
)

logger = logging.getLogger(__name__)

YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID')
YOOKASSA_SECRET_KEY = os.getenv('YOOKASSA_SECRET_KEY')
# 1 = без НДС (УСН), 2 = НДС 0%, 4 = НДС 20% (ОСНО)
YOOKASSA_VAT_CODE = int(os.getenv('YOOKASSA_VAT_CODE', '1'))

_YOOKASSA_NETWORKS = [
    ip_network('185.71.76.0/27'),
    ip_network('185.71.77.0/27'),
    ip_network('77.75.153.0/25'),
    ip_network('77.75.156.11/32'),
    ip_network('77.75.156.35/32'),
]


def _configure():
    shop_id = YOOKASSA_SHOP_ID or os.getenv('YOOKASSA_SHOP_ID')
    secret_key = YOOKASSA_SECRET_KEY or os.getenv('YOOKASSA_SECRET_KEY')
    if not shop_id or not secret_key:
        raise RuntimeError('YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY должны быть заданы.')
    Configuration.account_id = shop_id
    Configuration.secret_key = secret_key


def _is_trusted_ip(remote_ip: str) -> bool:
    if os.getenv('YOOKASSA_SKIP_IP_CHECK', '').lower() in {'1', 'true', 'yes'}:
        return True
    try:
        addr = ip_address(remote_ip)
        return any(addr in net for net in _YOOKASSA_NETWORKS)
    except ValueError:
        return False


def _normalize_phone_e164(phone: str) -> str:
    """Convert any Russian phone format to E.164 (+7XXXXXXXXXX)."""
    digits = ''.join(c for c in phone if c.isdigit())
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    return f'+{digits}'


def _build_receipt(payload: dict, menu_map: dict) -> dict:
    """Build YooKassa receipt object for 54-FZ fiscalization."""
    raw_items = payload.get('items') or []
    phone = _normalize_phone_e164((payload.get('phone') or '').strip())
    email = (payload.get('email') or '').strip()
    if not email:
        raise ValueError('Укажите электронную почту — на неё ЮКасса отправит чек.')

    customer = {'phone': phone, 'email': email}

    items = []
    for item in raw_items:
        if item.get('id') is None:
            continue
        menu_item = menu_map[item['id']]
        qty = max(1, int(item.get('qty') or 1))
        price = float(menu_item.price or 0)
        items.append({
            'description': menu_item.name[:128],
            'quantity': f'{qty:.3f}',
            'amount': {'value': f'{price:.2f}', 'currency': 'RUB'},
            'vat_code': YOOKASSA_VAT_CODE,
            'payment_mode': 'full_payment',
            'payment_subject': 'commodity',
        })

    return {'customer': customer, 'items': items}


def create_payment(payload: dict, *, base_url: str) -> dict:
    _configure()

    raw_items = payload.get('items') or []
    # Load menu items once — used both for total calculation and receipt building.
    # _load_menu_items also validates availability for delivery.
    menu_map = _load_menu_items(raw_items)

    total = sum(
        float(menu_map[item['id']].price or 0) * max(1, int(item.get('qty') or 1))
        for item in raw_items
        if item.get('id') is not None
    )
    if total <= 0:
        raise ValueError('Сумма заказа должна быть больше нуля.')

    # Full order validation (address, phone, name, etc.) — payment type forced to card
    build_order_payload({**payload, 'paymentType': 'card'}, base_url=base_url)

    payment = Payment.create(
        {
            'amount': {'value': f'{total:.2f}', 'currency': 'RUB'},
            'confirmation': {
                'type': 'redirect',
                'return_url': f'{base_url}/order?payment=success',
            },
            'capture': True,
            'description': 'Заказ в ресторане Marta',
            'metadata': {'base_url': base_url},
            'receipt': _build_receipt(payload, menu_map),
        },
        str(uuid.uuid4()),
    )

    pending = PendingOrder(
        payment_id=payment.id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.session.add(pending)
    db.session.commit()

    logger.info("Payment created: id=%s total=%.2f", payment.id, total)
    return {
        'paymentId': payment.id,
        'confirmationUrl': payment.confirmation.confirmation_url,
    }


def handle_webhook(body: bytes, *, remote_ip: str) -> dict:
    if not _is_trusted_ip(remote_ip):
        raise PermissionError(f'Webhook from untrusted IP: {remote_ip}')

    _configure()

    try:
        data = json.loads(body)
    except Exception as exc:
        raise ValueError(f'Invalid webhook JSON: {exc}') from exc

    event = data.get('event', '')
    obj = data.get('object', {})
    payment_id = obj.get('id')

    if event != 'payment.succeeded':
        logger.info("Ignored webhook event=%s payment_id=%s", event, payment_id)
        return {'status': 'ignored'}

    pending = PendingOrder.query.filter_by(payment_id=payment_id).first()
    if not pending:
        # Duplicate webhook — order already processed
        logger.warning("PendingOrder not found for payment_id=%s", payment_id)
        return {'status': 'ok', 'note': 'already_processed'}

    payload = json.loads(pending.payload_json)
    payload['paymentType'] = 'card'
    base_url = (obj.get('metadata') or {}).get('base_url', '')

    # If create_order raises, the exception propagates and pending_order is NOT deleted,
    # so YooKassa will retry the webhook and we can attempt again.
    result = create_order(payload, base_url=base_url)
    logger.info("SBIS order created for payment_id=%s", payment_id)

    db.session.delete(pending)
    db.session.commit()

    return {'status': 'ok', 'order': result}
