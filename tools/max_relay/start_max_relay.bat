@echo off
rem Автозапуск перехватчика MAX -> Telegram. Положить ярлык в shell:startup.
rem Впиши реальные значения и путь к скрипту.
set MAX_RELAY_URL=https://ДОМЕН/api/relay/max
set MAX_RELAY_SECRET=СЕКРЕТ_КАК_НА_СЕРВЕРЕ
rem MAX Web в Edge: тосты приходят от имени "Microsoft Edge"
set MAX_APP_FILTER=edge
start "max-relay" /min py -3.12 "%~dp0max_notify_win.py"
