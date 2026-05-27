import os
from datetime import datetime, time, timedelta

from app.services.order import _get_order_timezone, _now_in_order_timezone


DEFAULT_START = '12:00'
DEFAULT_END = '21:30'
DEFAULT_PICKUP_LEAD_MINUTES = 25
PICKUP_SLOT_MINUTES = 15


def _parse_hhmm(value, fallback):
    raw = (value or '').strip()
    if not raw:
        raw = fallback
    hours, _, minutes = raw.partition(':')
    return time(hour=int(hours), minute=int(minutes or 0))


def _bounds():
    start = _parse_hhmm(os.getenv('DELIVERY_HOURS_START'), DEFAULT_START)
    end = _parse_hhmm(os.getenv('DELIVERY_HOURS_END'), DEFAULT_END)
    return start, end


def _pickup_lead_minutes():
    raw = (os.getenv('PICKUP_LEAD_MINUTES') or '').strip()
    if not raw:
        return DEFAULT_PICKUP_LEAD_MINUTES
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_PICKUP_LEAD_MINUTES


def is_delivery_open(now=None):
    start, end = _bounds()
    now = now or _now_in_order_timezone()
    current = now.time().replace(second=0, microsecond=0)
    return start <= current < end


def get_delivery_status(now=None):
    start, end = _bounds()
    now = now or _now_in_order_timezone()
    tz = _get_order_timezone()
    opens_today = datetime.combine(now.date(), start, tzinfo=tz)
    closes_today = datetime.combine(now.date(), end, tzinfo=tz)

    if now < opens_today:
        next_open = opens_today
    elif now < closes_today:
        next_open = opens_today
    else:
        next_open = opens_today + timedelta(days=1)

    return {
        'available': opens_today <= now < closes_today,
        'now': now.isoformat(),
        'opensAt': start.strftime('%H:%M'),
        'closesAt': end.strftime('%H:%M'),
        'nextOpenAt': next_open.isoformat(),
        'timezone': os.getenv('ORDER_TIMEZONE', 'Europe/Moscow'),
        'pickupLeadMinutes': _pickup_lead_minutes(),
    }


def _round_up_to_slot(dt):
    minute = dt.minute
    delta = (PICKUP_SLOT_MINUTES - (minute % PICKUP_SLOT_MINUTES)) % PICKUP_SLOT_MINUTES
    if delta == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    return (dt + timedelta(minutes=delta)).replace(second=0, microsecond=0)


def get_pickup_slots(now=None):
    """Return list of available pickup slots for today.

    Each slot represents the time the customer arrives. Earliest slot is now + lead,
    rounded up to the next 15-min boundary. Latest slot is closesAt (so closing
    time itself is reachable, no further slots after that).
    """
    start, end = _bounds()
    lead = _pickup_lead_minutes()
    now = now or _now_in_order_timezone()
    tz = _get_order_timezone()

    opens_today = datetime.combine(now.date(), start, tzinfo=tz)
    closes_today = datetime.combine(now.date(), end, tzinfo=tz)

    if now >= closes_today:
        return []

    earliest = _round_up_to_slot(max(now + timedelta(minutes=lead), opens_today))
    if earliest > closes_today:
        return []

    slots = []
    cursor = earliest
    while cursor <= closes_today:
        slots.append({
            'value': cursor.isoformat(),
            'label': cursor.strftime('%H:%M'),
        })
        cursor += timedelta(minutes=PICKUP_SLOT_MINUTES)
    return slots


def parse_pickup_time(raw):
    """Validate user-supplied pickup time. Returns aware datetime in order TZ or None."""
    if not raw:
        return None
    tz = _get_order_timezone()
    try:
        dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def is_pickup_time_valid(pickup_dt, now=None):
    """Pickup must be inside today's window and >= now + lead time."""
    if pickup_dt is None:
        return False
    start, end = _bounds()
    lead = _pickup_lead_minutes()
    now = now or _now_in_order_timezone()
    tz = _get_order_timezone()
    opens_today = datetime.combine(now.date(), start, tzinfo=tz)
    closes_today = datetime.combine(now.date(), end, tzinfo=tz)
    earliest = now + timedelta(minutes=lead) - timedelta(seconds=30)
    return opens_today <= pickup_dt <= closes_today and pickup_dt >= earliest
