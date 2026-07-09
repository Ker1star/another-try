"""Перехват уведомлений MAX на Windows и пересылка на сервер Марты.

Как работает: слушает центр уведомлений Windows (UserNotificationListener),
фильтрует тосты от приложения MAX и шлёт их POST'ом на /api/relay/max —
сервер уже пересылает в Telegram (у компа нет VPN, до api.telegram.org
ему не достучаться, а до своего сайта — легко).

Установка на офисном ПК (Windows 10/11, Python 3.9+):
    pip install winsdk requests

Настройка (переменные окружения или правь константы ниже):
    MAX_RELAY_URL    — https://<домен>/api/relay/max
    MAX_RELAY_SECRET — тот же секрет, что NOTIFY_RELAY_SECRET на сервере

Обязательно на этом ПК:
    1. Десктопный MAX залогинен под нужным аккаунтом, уведомления включены.
    2. Windows: Параметры → Система → Уведомления — включены; фокус-режим выключен.
    3. Не давать компу спать:  powercfg -change standby-timeout-ac 0
       (монитор гасить можно:  powercfg -change monitor-timeout-ac 10)
    4. Автозапуск: положить start_max_relay.bat в shell:startup.

Первый запуск может спросить разрешение на доступ к уведомлениям —
если статус Denied, включи доступ в Параметры → Конфиденциальность →
(Доступ к уведомлениям) и перезапусти скрипт.
"""

import asyncio
import os
import sys
import time

import requests
from winsdk.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
from winsdk.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)

RELAY_URL = os.getenv('MAX_RELAY_URL', 'https://example.com/api/relay/max')
RELAY_SECRET = os.getenv('MAX_RELAY_SECRET', '')
APP_FILTER = os.getenv('MAX_APP_FILTER', 'max')  # подстрока имени приложения, без регистра
POLL_SECONDS = 3


def _notification_texts(notification):
    """Заголовок и текст тоста; у MAX это «отправитель» и «сообщение»."""
    try:
        binding = notification.notification.visual.get_binding(
            KnownNotificationBindings.get_toast_generic()
        )
        if binding is None:
            return '', ''
        texts = [t.text for t in binding.get_text_elements()]
        return (texts[0] if texts else ''), '\n'.join(texts[1:])
    except Exception:
        return '', ''


def _app_name(notification):
    try:
        return notification.app_info.display_info.display_name or ''
    except Exception:
        return ''


def _send(title, text):
    try:
        response = requests.post(
            RELAY_URL,
            json={'title': title, 'text': text},
            headers={'Authorization': f'Bearer {RELAY_SECRET}'},
            timeout=15,
        )
        print(time.strftime('%H:%M:%S'), '->', response.status_code, title)
        return response.ok
    except Exception as exc:
        print(time.strftime('%H:%M:%S'), 'send failed:', exc)
        return False


async def main():
    listener = UserNotificationListener.current
    status = await listener.request_access_async()
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        sys.exit(
            f'Нет доступа к уведомлениям ({status}). Включи доступ в параметрах '
            'Windows и перезапусти.'
        )

    seen = set()
    first_pass = True  # не пересылать то, что висело в центре до запуска

    print(f'Слежу за уведомлениями «{APP_FILTER}» → {RELAY_URL}')
    while True:
        try:
            notifications = await listener.get_notifications_async(NotificationKinds.TOAST)
            for notification in notifications:
                if notification.id in seen:
                    continue
                seen.add(notification.id)
                if first_pass:
                    continue
                if APP_FILTER not in _app_name(notification).lower():
                    continue
                title, text = _notification_texts(notification)
                if title or text:
                    _send(title, text)
            first_pass = False
            if len(seen) > 5000:
                seen.clear()
        except Exception as exc:
            print(time.strftime('%H:%M:%S'), 'poll error:', exc)
        await asyncio.sleep(POLL_SECONDS)


if __name__ == '__main__':
    asyncio.run(main())
