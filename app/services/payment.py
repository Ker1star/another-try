import json
import logging
import os
import uuid
from decimal import Decimal
from ipaddress import ip_address, ip_network

from yookassa import Configuration, Payment

from app import db
from app.models import PendingOrder
from app.services import promo as promo_service
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
    ip_network('77.75.154.128/25'),
    ip_network('77.75.156.11/32'),
    ip_network('77.75.156.35/32'),
    ip_network('2a02:5180::/32'),
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


def _build_receipt(payload: dict, menu_map: dict, delivery_cost: float = 0.0) -> dict:
    """Build YooKassa receipt object for 54-FZ fiscalization.

    The receipt items must sum to the charged amount, so the delivery line is
    included here whenever a delivery fee is charged. If an item carries a
    'price' override (used to apply a promo-code discount — see
    apply_promo_to_items), that price is used instead of the DB price, same
    convention as _build_nomenclatures in order.py.
    """
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
        price = float(item['price']) if item.get('price') is not None else float(menu_item.price or 0)
        items.append({
            'description': menu_item.name[:128],
            'quantity': f'{qty:.3f}',
            'amount': {'value': f'{price:.2f}', 'currency': 'RUB'},
            'vat_code': YOOKASSA_VAT_CODE,
            'payment_mode': 'full_payment',
            'payment_subject': 'commodity',
        })

    if delivery_cost and delivery_cost > 0:
        items.append({
            'description': 'Доставка',
            'quantity': '1.000',
            'amount': {'value': f'{delivery_cost:.2f}', 'currency': 'RUB'},
            'vat_code': YOOKASSA_VAT_CODE,
            'payment_mode': 'full_payment',
            'payment_subject': 'service',
        })

    return {'customer': customer, 'items': items}


def _apply_promo(raw_items: list, menu_map: dict, payload: dict, subtotal: float):
    """Validates payload['promoCode'] (if any) and mutates raw_items in place,
    setting item['price'] to the discounted per-unit price. Both the YooKassa
    receipt (_build_receipt) and the SBIS order (_build_nomenclatures in
    order.py) already prefer item['price'] over the DB price when present, so
    this one mutation is enough to keep the charge, the fiscal receipt and the
    kassa order all consistent.

    Returns (promo_or_None, actual_discount: Decimal).
    """
    code = (payload.get('promoCode') or '').strip()
    if not code:
        return None, Decimal('0')

    phone = (payload.get('phone') or '').strip() or None
    promo = promo_service.validate_promo(code, subtotal, phone=phone)
    nominal_discount = promo_service.compute_discount(promo, subtotal)

    lines = [
        {
            'key': item['id'],
            'qty': max(1, int(item.get('qty') or 1)),
            'unit_price': Decimal(str(menu_map[item['id']].price or 0)),
        }
        for item in raw_items
        if item.get('id') is not None
    ]
    new_unit_prices, actual_discount = promo_service.apply_discount_to_lines(lines, nominal_discount)

    for item in raw_items:
        if item.get('id') in new_unit_prices:
            item['price'] = float(new_unit_prices[item['id']])

    return promo, actual_discount


def create_payment(payload: dict, *, base_url: str) -> dict:
    _configure()

    raw_items = payload.get('items') or []
    # Load menu items once — used both for total calculation and receipt building.
    # _load_menu_items also validates availability for delivery.
    menu_map = _load_menu_items(raw_items)

    subtotal = sum(
        float(menu_map[item['id']].price or 0) * max(1, int(item.get('qty') or 1))
        for item in raw_items
        if item.get('id') is not None
    )
    if subtotal <= 0:
        raise ValueError('Сумма заказа должна быть больше нуля.')

    # Промокод (если есть) проверяется и применяется здесь — раньше, чем
    # цены попадут в чек ЮKassa и в сохранённый payload для будущего заказа
    # в Saby. См. _apply_promo и app/services/promo.py.
    promo, discount_amount = _apply_promo(raw_items, menu_map, payload, subtotal)
    total = subtotal - float(discount_amount)

    # Full order validation (address, phone, zone, min-order) — payment type forced to card.
    # The returned payload carries the server-computed delivery cost we must charge.
    order_payload = build_order_payload({**payload, 'paymentType': 'card'}, base_url=base_url)
    delivery_cost = float((order_payload.get('delivery') or {}).get('deliveryCost') or 0)
    charge_total = total + delivery_cost
    if charge_total <= 0:
        raise ValueError('Сумма заказа со скидкой должна быть больше нуля.')

    tracking_id = str(uuid.uuid4())

    payment = Payment.create(
        {
            'amount': {'value': f'{charge_total:.2f}', 'currency': 'RUB'},
            'confirmation': {
                'type': 'redirect',
                'return_url': f'{base_url}/order?payment=success&id={tracking_id}',
            },
            'capture': True,
            'description': 'Заказ в ресторане Marta',
            'metadata': {'base_url': base_url, 'tracking_id': tracking_id},
            'receipt': _build_receipt(payload, menu_map, delivery_cost=delivery_cost),
        },
        str(uuid.uuid4()),
    )

    pending = PendingOrder(
        payment_id=payment.id,
        tracking_id=tracking_id,
        status='pending',
        promo_code=promo.code if promo else None,
        discount_amount=discount_amount if promo else None,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.session.add(pending)
    db.session.commit()

    logger.info(
        "Payment created: id=%s tracking=%s items=%.2f discount=%s delivery=%.2f total=%.2f promo=%s",
        payment.id, tracking_id, subtotal, discount_amount, delivery_cost, charge_total, promo.code if promo else None,
    )
    return {
        'paymentId': payment.id,
        'trackingId': tracking_id,
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
        logger.warning("PendingOrder not found for payment_id=%s", payment_id)
        return {'status': 'ok', 'note': 'unknown_payment'}

    if pending.status == 'paid':
        # Idempotency: duplicate webhook for already-processed payment
        logger.info("Duplicate webhook for payment_id=%s (already paid)", payment_id)
        return {'status': 'ok', 'note': 'already_processed'}

    payload = json.loads(pending.payload_json)
    payload['paymentType'] = 'card'
    base_url = (obj.get('metadata') or {}).get('base_url', '')

    from datetime import datetime, timezone

    try:
        result = create_order(payload, base_url=base_url)
    except Exception as exc:
        pending.status = 'failed'
        pending.error = str(exc)[:1000]
        pending.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        logger.error("SBIS order failed for payment_id=%s: %s", payment_id, exc)
        raise

    pending.status = 'paid'
    pending.order_number = str(result.get('orderNumber') or result.get('number') or '') or None
    pending.updated_at = datetime.now(timezone.utc)

    # Промокод считается использованным только на успешном заказе — не на
    # попытке оплаты, — иначе брошенные на середине оплаты корзины съедали
    # бы лимит использований впустую.
    if pending.promo_code:
        promo = promo_service.find_promo(pending.promo_code)
        if promo:
            promo_service.record_redemption(
                promo,
                phone=_normalize_phone_e164((payload.get('phone') or '').strip()),
                discount_amount=pending.discount_amount or 0,
                pending_order_id=pending.id,
            )

    db.session.commit()
    logger.info("SBIS order created for payment_id=%s", payment_id)

    return {'status': 'ok', 'order': result}
