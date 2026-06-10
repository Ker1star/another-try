"""Tests for delivery zone lookup and quoting.

Runs against the real Syktyvkar zone in app/config/delivery_zones.geojson
(name "Сыктывкар": deliveryCost 200, minOrder 800, freeFrom 1500).

Run via pytest, or standalone: `python tests/test_delivery_zones.py`
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.delivery_zones import find_zone, quote  # noqa: E402
import app.services.order as order_mod  # noqa: E402

# Force the client-coords fallback so resolve tests never hit the network,
# regardless of whether YANDEX_GEOCODER_KEY is configured locally.
order_mod._geocode_address = lambda address_full: None

INSIDE = (61.66, 50.84)      # central Syktyvkar, inside the zone
OUTSIDE_NW = (61.72, 50.70)  # northwest, outside the polygon
OUTSIDE_FAR = (60.00, 50.00)  # far away


def test_point_inside_zone():
    zone = find_zone(*INSIDE)
    assert zone is not None
    assert zone['name'] == 'Сыктывкар'


def test_point_outside_zone():
    assert find_zone(*OUTSIDE_NW) is None
    assert find_zone(*OUTSIDE_FAR) is None


def test_quote_charges_delivery_below_free_threshold():
    result = quote(*INSIDE, subtotal=1000)  # below freeFrom 1500
    assert result['inZone'] is True
    assert result['deliveryCost'] == 200
    assert result['belowMin'] is False  # 1000 >= minOrder 800


def test_quote_is_free_above_threshold():
    result = quote(*INSIDE, subtotal=1500)  # at freeFrom 1500
    assert result['inZone'] is True
    assert result['deliveryCost'] == 0.0


def test_quote_below_min_order_flagged():
    result = quote(*INSIDE, subtotal=500)  # below minOrder 800
    assert result['belowMin'] is True


def test_quote_outside_zone_reports_not_in_zone():
    result = quote(*OUTSIDE_FAR, subtotal=2000)
    assert result == {'inZone': False}


# --- resolve_delivery_pricing (server-authoritative) ---

_ADDR = {'city': 'Сыктывкар', 'street': 'Ленина', 'house': '1'}


def test_resolve_uses_client_coords_in_zone():
    payload = {'address': _ADDR, 'lat': INSIDE[0], 'lon': INSIDE[1]}
    result = order_mod.resolve_delivery_pricing(payload, subtotal=1000)
    assert result['inZone'] is True
    assert result['deliveryCost'] == 200
    assert result['lat'] == INSIDE[0]


def test_resolve_rejects_out_of_zone():
    payload = {'address': _ADDR, 'lat': OUTSIDE_FAR[0], 'lon': OUTSIDE_FAR[1]}
    try:
        order_mod.resolve_delivery_pricing(payload, subtotal=2000)
        assert False, 'expected ValueError for out-of-zone address'
    except ValueError as exc:
        assert 'вне зоны' in str(exc)


def test_resolve_rejects_below_min():
    payload = {'address': _ADDR, 'lat': INSIDE[0], 'lon': INSIDE[1]}
    try:
        order_mod.resolve_delivery_pricing(payload, subtotal=500)
        assert False, 'expected ValueError for below-minimum order'
    except ValueError as exc:
        assert 'Минимальная' in str(exc)


def test_resolve_degrades_to_none_without_coords_or_geocoder():
    # No lat/lon and geocoder patched to None: must degrade gracefully (return None),
    # not raise — so a missing key never blocks checkout.
    payload = {'address': _ADDR}
    assert order_mod.resolve_delivery_pricing(payload, subtotal=1000) is None


# --- geocode_quote (live preview for the order form) ---

def test_geocode_quote_incomplete_address():
    result = order_mod.geocode_quote({'city': 'Сыктывкар'}, subtotal=1000)  # no street/house
    assert result['found'] is False
    assert result['reason'] == 'incomplete'


def test_geocode_quote_no_geocoder_key():
    saved = order_mod.YANDEX_GEOCODER_KEY
    order_mod.YANDEX_GEOCODER_KEY = None
    try:
        result = order_mod.geocode_quote(_ADDR, subtotal=1000)
        assert result['found'] is False
        assert result['reason'] == 'no_geocoder'
    finally:
        order_mod.YANDEX_GEOCODER_KEY = saved


def test_geocode_quote_found_in_zone():
    saved_key = order_mod.YANDEX_GEOCODER_KEY
    saved_fn = order_mod._geocode_address
    order_mod.YANDEX_GEOCODER_KEY = 'dummy'
    order_mod._geocode_address = lambda address_full: INSIDE
    try:
        result = order_mod.geocode_quote(_ADDR, subtotal=1000)
        assert result['found'] is True
        assert result['inZone'] is True
        assert result['deliveryCost'] == 200
        assert result['lat'] == INSIDE[0]
    finally:
        order_mod.YANDEX_GEOCODER_KEY = saved_key
        order_mod._geocode_address = saved_fn


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc}')
    print('---')
    print('OK' if failures == 0 else f'{failures} FAILED')
    sys.exit(1 if failures else 0)
