import os
from urllib.parse import quote

from app import db
from app.models import Category, MenuItem
from app.services.auth import get_menu as fetch_sbis_menu
from app.services.presto_config import get_point_id, get_price_list_id


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


def upsert_menu(point_id: int | None = None, price_list_id: int | None = None):
    point_id = point_id or get_point_id()
    price_list_id = price_list_id or get_price_list_id()
    items = fetch_sbis_menu(point_id=point_id, price_list_id=price_list_id)

    existing_cats = {category.sbis_id: category for category in Category.query.all()}
    existing_items = {item.sbis_id: item for item in MenuItem.query.all()}

    for entry in items:
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

    for entry in items:
        if entry['isParent']:
            continue

        sbis_id = entry['hierarchicalId']
        presto_id = entry.get('id')
        external_id = entry.get('externalId')
        nom_number = entry.get('nomNumber')
        name = entry['name']
        parent_id = entry['hierarchicalParent']
        category = existing_cats.get(parent_id)
        if category is None:
            continue

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
                available_for_delivery=_default_delivery_available(),
            )
            db.session.add(item)

        existing_items[sbis_id] = item

    db.session.commit()
    print(f"[DONE] Updated menu: {len(existing_items)} items, {len(existing_cats)} categories.")
