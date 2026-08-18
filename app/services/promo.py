"""Промокоды: поиск, валидация, расчёт скидки.

Скидка применяется только к стоимости блюд (не к доставке) и
распределяется пропорционально между позициями чека — ЮKassa не
принимает отрицательную строку в чеке (проверено на реальном API,
код ошибки invalid_request на items.amount.value), поэтому единственный
рабочий способ дать скидку — уменьшить цену самих позиций.

Округление: все позиции, кроме последней, получают свою долю скидки с
округлением до копейки; последней достаётся остаток, чтобы сумма всегда
сходилась. Итоговая (фактическая) скидка считается от уже округлённых
цен позиций, а не от исходного процента/суммы — так гарантированно нет
расхождения в копейку между чеком и списанной суммой.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app import db
from app.models import PromoCode, PromoRedemption


class PromoError(ValueError):
    """Промокод нельзя применить — текст ошибки уже готов для показа клиенту."""


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    """SQLite не хранит таймзону — DateTime(timezone=True) на нём возвращает
    наивные datetime, из-за чего сравнение с aware-now падает. Postgres (прод)
    этим не страдает, но локальная разработка/тесты идут на SQLite."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def find_promo(code: str) -> PromoCode | None:
    code = (code or '').strip().upper()
    if not code:
        return None
    return PromoCode.query.filter(db.func.upper(PromoCode.code) == code).first()


def _redemptions_count(promo: PromoCode, phone: str | None = None) -> int:
    query = PromoRedemption.query.filter_by(promo_code_id=promo.id)
    if phone:
        query = query.filter_by(phone=phone)
    return query.count()


def validate_promo(code: str, subtotal: float, phone: str | None = None) -> PromoCode:
    """Возвращает PromoCode либо кидает PromoError с текстом для пользователя."""
    promo = find_promo(code)
    if not promo or not promo.is_active:
        raise PromoError('Промокод не найден.')

    now = _now()
    if promo.valid_from and now < _aware(promo.valid_from):
        raise PromoError('Промокод ещё не активен.')
    if promo.valid_until and now > _aware(promo.valid_until):
        raise PromoError('Срок действия промокода истёк.')

    if promo.min_order_amount and subtotal < float(promo.min_order_amount):
        raise PromoError(f'Промокод действует при заказе от {float(promo.min_order_amount):.0f} ₽.')

    if promo.usage_limit is not None and _redemptions_count(promo) >= promo.usage_limit:
        raise PromoError('Промокод больше не действует — лимит использований исчерпан.')

    if phone and promo.max_uses_per_customer is not None:
        if _redemptions_count(promo, phone=phone) >= promo.max_uses_per_customer:
            raise PromoError('Вы уже использовали этот промокод.')

    return promo


def compute_discount(promo: PromoCode, subtotal: float) -> Decimal:
    """Номинальная скидка от процента/суммы, без учёта округления по позициям."""
    subtotal_d = Decimal(str(subtotal))
    if promo.discount_type == 'percent':
        raw = subtotal_d * Decimal(str(promo.discount_value)) / Decimal('100')
    else:
        raw = Decimal(str(promo.discount_value))
    raw = raw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return max(Decimal('0'), min(raw, subtotal_d))


def apply_discount_to_lines(lines: list[dict], discount_amount: Decimal) -> tuple[dict, Decimal]:
    """Пропорционально распределяет discount_amount между строками заказа.

    lines: [{'key': произвольный ключ, 'qty': int, 'unit_price': Decimal}, ...]
    Возвращает (key -> новая цена за штуку, фактическая скидка).
    """
    priced_lines = [{**line, 'line_total': line['unit_price'] * line['qty']} for line in lines]
    subtotal = sum((line['line_total'] for line in priced_lines), Decimal('0'))

    if discount_amount <= 0 or subtotal <= 0 or not priced_lines:
        return {line['key']: line['unit_price'] for line in priced_lines}, Decimal('0')

    discount_amount = min(discount_amount, subtotal)
    allocated = Decimal('0')
    new_unit_prices = {}
    new_subtotal = Decimal('0')

    for i, line in enumerate(priced_lines):
        is_last = i == len(priced_lines) - 1
        if is_last:
            line_discount = discount_amount - allocated
        else:
            line_discount = (discount_amount * line['line_total'] / subtotal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            allocated += line_discount

        new_line_total = max(Decimal('0'), line['line_total'] - line_discount)
        new_unit_price = (new_line_total / line['qty']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        new_unit_prices[line['key']] = new_unit_price
        new_subtotal += new_unit_price * line['qty']

    actual_discount = subtotal - new_subtotal
    return new_unit_prices, actual_discount


def record_redemption(promo: PromoCode, *, phone: str, discount_amount, pending_order_id: int | None):
    db.session.add(PromoRedemption(
        promo_code_id=promo.id,
        pending_order_id=pending_order_id,
        phone=phone,
        discount_amount=discount_amount,
    ))
