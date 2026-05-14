from __future__ import annotations

import logging
import os
from urllib.parse import quote

from app import db
from app.models import Category, MenuItem
from app.services.auth import get_menu as fetch_sbis_menu
from app.services.presto_config import (
    get_point_id,
    get_price_list_id,
    get_price_list_id_delivery,
    get_price_list_id_family,
)

logger = logging.getLogger(__name__)


def _default_delivery_available() -> bool:
    return (os.getenv('DEFAULT_DELIVERY_AVAILABLE') or 'true').strip().lower() in {'1', 'true', 'yes', 'on'}


def build_image_proxy_path(image_param: str | None) -> str:
    if not image_param:
        return 'images/logo-heart.jpg'

    if image_param.startswith('/img?'):
        return f"/api{image_param}"

    if image_param.startswith('http://') or image_param.startswith('https://') or image_param.startswith('/'):
        return image_param

    return f"/api/img?params={quote(image_param, safe='')}"


def _fetch_price_list_ids(point_id: int, price_list_id: int | None) -> set:
    """Fetch a price list and return the set of leaf item sbis_ids."""
    if price_list_id is None:
        return set()
    items = fetch_sbis_menu(point_id=point_id, price_list_id=price_list_id)
    return {entry['hierarchicalId'] for entry in items if not entry['isParent']}


def upsert_menu(
    point_id: int | None = None,
    price_list_id: int | None = None,
    price_list_id_delivery: int | None = None,
    price_list_id_family: int | None = None,
):
    point_id = point_id or get_point_id()
    price_list_id = price_list_id or get_price_list_id()
    if price_list_id_delivery is None:
        price_list_id_delivery = get_price_list_id_delivery()
    if price_list_id_family is None:
        price_list_id_family = get_price_list_id_family()

    restaurant_items = fetch_sbis_menu(point_id=point_id, price_list_id=price_list_id)
    restaurant_ids = {entry['hierarchicalId'] for entry in restaurant_items if not entry['isParent']}

    delivery_ids: set | None = None
    if price_list_id_delivery is not None:
        delivery_ids = _fetch_price_list_ids(point_id, price_list_id_delivery)
        logger.info("Delivery price list fetched: %d items.", len(delivery_ids))

    family_items: list = []
    family_ids: set = set()
    if price_list_id_family is not None:
        family_items = fetch_sbis_menu(point_id=point_id, price_list_id=price_list_id_family)
        family_ids = {entry['hierarchicalId'] for entry in family_items if not entry['isParent']}
        logger.info("Family price list fetched: %d items.", len(family_ids))

    # We may also need to pull delivery items as a source (delivery-exclusive positions).
    delivery_items: list = []
    if price_list_id_delivery is not None and price_list_id_delivery != price_list_id:
        delivery_items = fetch_sbis_menu(point_id=point_id, price_list_id=price_list_id_delivery)

    existing_cats = {category.sbis_id: category for category in Category.query.all()}
    existing_items = {item.sbis_id: item for item in MenuItem.query.all()}

    # Pass 1: upsert all categories across all three price lists.
    for entry in restaurant_items + delivery_items + family_items:
        if not entry['isParent']:
            continue

        sbis_id = entry['hierarchicalId']
        name = entry['name']
        parent_sbis_id = entry.get('hierarchicalParent')

        if sbis_id in existing_cats:
            category = existing_cats[sbis_id]
            category.name = name
            category.parent_sbis_id = parent_sbis_id
        else:
            category = Category(sbis_id=sbis_id, name=name, parent_sbis_id=parent_sbis_id)
            db.session.add(category)

        existing_cats[sbis_id] = category

    db.session.flush()

    # Pass 2: upsert items. Restaurant price list takes priority for field values
    # (name, price, description, image) — its data wins. Other price lists only
    # contribute their flag and can fill in fields for positions exclusive to them.
    seen_item_ids: set = set()

    def _upsert_item(entry):
        sbis_id = entry['hierarchicalId']
        seen_item_ids.add(sbis_id)
        presto_id = entry.get('id')
        external_id = entry.get('externalId')
        nom_number = entry.get('nomNumber')
        name = entry['name']
        parent_id = entry['hierarchicalParent']
        category = existing_cats.get(parent_id)
        if category is None:
            return

        price = entry.get('cost')
        descr = entry.get('description_simple')
        out_qty = entry.get('attributes', {}).get('outQuantity')
        imgs = entry.get('images') or []
        image_path = build_image_proxy_path(imgs[0] if imgs else None)

        if sbis_id in existing_items:
            item = existing_items[sbis_id]
            item.presto_id = presto_id
            item.external_id = external_id
            item.nom_number = nom_number
            item.name = name
            item.category = category
            item.price = price
            item.description_simple = descr
            item.out_quantity = out_qty
            item.image_path = image_path
        else:
            item = MenuItem(
                sbis_id=sbis_id,
                presto_id=presto_id,
                external_id=external_id,
                nom_number=nom_number,
                name=name,
                category=category,
                price=price,
                description_simple=descr,
                out_quantity=out_qty,
                image_path=image_path,
            )
            db.session.add(item)
            existing_items[sbis_id] = item

        return existing_items[sbis_id]

    # Process delivery and family first, then restaurant — so restaurant data wins.
    for entry in delivery_items:
        if not entry['isParent']:
            _upsert_item(entry)

    for entry in family_items:
        if not entry['isParent']:
            _upsert_item(entry)

    for entry in restaurant_items:
        if not entry['isParent']:
            _upsert_item(entry)

    # Pass 3: set the three flags on every known item based on price list membership.
    for sbis_id, item in existing_items.items():
        item.in_restaurant = sbis_id in restaurant_ids
        item.in_family = sbis_id in family_ids
        if delivery_ids is not None:
            item.available_for_delivery = sbis_id in delivery_ids
        elif sbis_id not in seen_item_ids:
            # Item is stale (no longer in any price list) — leave its flag alone.
            pass
        else:
            item.available_for_delivery = _default_delivery_available()

    db.session.commit()
    logger.info(
        "Menu sync complete: %d items, %d categories. restaurant=%d delivery=%s family=%d",
        len(existing_items),
        len(existing_cats),
        len(restaurant_ids),
        len(delivery_ids) if delivery_ids is not None else 'n/a',
        len(family_ids),
    )
