"""Диагностика: печатает ВСЕ тосты Windows с именами приложений.

Запусти, попроси кого-нибудь написать в MAX, смотри консоль:
  - появилась строка с MAX -> проблема в фильтре/настройках, скажи какое имя;
  - вообще ничего от MAX -> приложение рисует всплывашки само, мимо
    центра уведомлений, нужен план Б.

    pip install winsdk
"""

import asyncio

from winsdk.windows.ui.notifications import NotificationKinds
from winsdk.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)


async def main():
    listener = UserNotificationListener.current
    status = await listener.request_access_async()
    print('Доступ:', status)
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        return

    seen = set()
    print('Жду тосты (Ctrl+C для выхода). Напиши что-нибудь в MAX...')
    while True:
        for n in await listener.get_notifications_async(NotificationKinds.TOAST):
            if n.id in seen:
                continue
            seen.add(n.id)
            app = ''
            try:
                app = n.app_info.display_info.display_name
            except Exception:
                pass
            texts = []
            templates = []
            try:
                for binding in n.notification.visual.bindings:
                    templates.append(binding.template)
                    texts.extend(t.text for t in binding.get_text_elements())
            except Exception as exc:
                texts.append(f'<ошибка извлечения: {exc}>')
            print(f'[{app!r}] шаблоны={templates} тексты={texts}')
        await asyncio.sleep(2)


asyncio.run(main())
