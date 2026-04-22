import os
import time
import requests
from dotenv import load_dotenv
from app.services.presto_config import get_point_id, get_price_list_id
load_dotenv()

_access_token = None
_token_obtained_at = 0.0
_token_ttl_seconds = 50 * 60  # SBIS tokens are typically valid for 1 hour; refresh a bit earlier


def _get_auth_settings():
    return {
        'auth_url': os.getenv('AUTH_URL'),
        'app_client_id': os.getenv('APP_CLIENT_ID'),
        'app_secret': os.getenv('APP_SECRET'),
        'secret_key': os.getenv('SECRET_KEY') or os.getenv('FLASK_SECRET_KEY'),
    }

def auth():
    """Return cached SBIS access token or request a new one."""
    global _access_token, _token_obtained_at
    settings = _get_auth_settings()

    if not settings['auth_url'] or not settings['app_client_id'] or not settings['app_secret'] or not settings['secret_key']:
        raise RuntimeError(
            "SBIS auth env vars are not configured: AUTH_URL, APP_CLIENT_ID, APP_SECRET, SECRET_KEY "
            "(or FLASK_SECRET_KEY as fallback)"
        )

    now = time.time()
    if _access_token and (now - _token_obtained_at) < _token_ttl_seconds:
        return _access_token

    response = requests.post(
        settings['auth_url'],
        headers={'Content-Type': 'application/json'},
        json={
            "app_client_id": settings['app_client_id'],
            "app_secret": settings['app_secret'],
            "secret_key": settings['secret_key']
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise Exception(f"Auth Error: {response.status_code} — {response.text}")

    data = response.json()
    token = data.get('access_token')
    if not token:
        raise Exception(f"Не получили access_token в теле ответа: {response.text}")
    _access_token = token
    _token_obtained_at = now
    return _access_token

def get_menu(point_id: int | None = None, price_list_id: int | None = None):
    """
    Тянем все страницы каталога, пока не закончится pagination.
    """
    point_id = point_id or get_point_id()
    price_list_id = price_list_id or get_price_list_id()
    headers = {"X-SBISAccessToken": auth()}
    url     = 'https://api.sbis.ru/retail/v2/nomenclature/list'
    params = {
        'pointId': point_id,
        'priceListId': price_list_id,
        'onlyPublished': True,
        'page': 0,
        'pageSize': 100  # можно увеличить, но лучше запарсить все страницы
    }

    all_items = []
    while True:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Собираем номенклатуры
        batch = data.get('nomenclatures', [])
        all_items.extend(batch)

        # Проверяем, есть ли следующая страница
        outcome = data.get('outcome', {})
        if not outcome.get('hasMore'):
            break

        # Идём на следующую страницу
        params['page'] += 1

    return all_items
    
