"""Delivery zones: map an address coordinate to a pricing zone.

Zones are stored as a GeoJSON FeatureCollection in app/config/delivery_zones.geojson
(exported from Яндекс.Конструктор). GeoJSON rings come as [lon, lat]; we normalize to
internal [lat, lon] on load. Pricing lives in each feature's `properties`.

No external geo dependency: point-in-polygon is a plain ray-casting test.
"""

import json
import os

ZONES_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'delivery_zones.geojson')

_cache = {'mtime': None, 'zones': []}


def _normalize_ring(ring):
    """GeoJSON ring is a list of [lon, lat]; return list of (lat, lon) tuples."""
    return [(float(point[1]), float(point[0])) for point in ring if len(point) >= 2]


def _parse_feature(feature):
    geometry = feature.get('geometry') or {}
    if geometry.get('type') != 'Polygon':
        return None
    rings = geometry.get('coordinates') or []
    if not rings or not rings[0]:
        return None

    props = feature.get('properties') or {}
    free_from = props.get('freeFrom')
    return {
        'name': props.get('name') or props.get('description') or 'Зона доставки',
        'deliveryCost': float(props.get('deliveryCost', 0) or 0),
        'minOrder': float(props.get('minOrder', 0) or 0),
        'freeFrom': float(free_from) if free_from not in (None, '') else None,
        'etaMinutes': props.get('etaMinutes'),
        'ring': _normalize_ring(rings[0]),  # outer ring; holes are ignored
    }


def _load_zones():
    """Load and cache zones, reloading only when the file changes on disk."""
    try:
        mtime = os.path.getmtime(ZONES_PATH)
    except OSError:
        _cache['mtime'] = None
        _cache['zones'] = []
        return []

    if _cache['mtime'] != mtime:
        with open(ZONES_PATH, encoding='utf-8') as handle:
            data = json.load(handle)
        features = data.get('features') or []
        _cache['zones'] = [zone for feature in features if (zone := _parse_feature(feature))]
        _cache['mtime'] = mtime

    return _cache['zones']


def _point_in_ring(lat, lon, ring):
    """Ray-casting point-in-polygon. Treats x=lon, y=lat."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = ring[i]
        lat_j, lon_j = ring[j]
        # When the edge is horizontal at this latitude the parity test is False,
        # so we never reach the division (lat_j - lat_i == 0) below.
        if ((lat_i > lat) != (lat_j > lat)) and \
                (lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i):
            inside = not inside
        j = i
    return inside


def find_zone(lat, lon):
    """Return the first zone containing the point, or None if outside all zones."""
    for zone in _load_zones():
        if _point_in_ring(lat, lon, zone['ring']):
            return zone
    return None


def quote(lat, lon, subtotal):
    """Delivery quote for a coordinate given the cart subtotal (in rubles)."""
    zone = find_zone(lat, lon)
    if zone is None:
        return {'inZone': False}

    free_from = zone['freeFrom']
    is_free = free_from is not None and subtotal >= free_from
    return {
        'inZone': True,
        'zoneName': zone['name'],
        'deliveryCost': 0.0 if is_free else zone['deliveryCost'],
        'minOrder': zone['minOrder'],
        'belowMin': subtotal < zone['minOrder'],
        'freeFrom': free_from,
        'etaMinutes': zone['etaMinutes'],
    }
