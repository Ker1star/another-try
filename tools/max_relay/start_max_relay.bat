@echo off
rem Автозапуск перехватчика MAX -> Telegram. Положить ярлык в shell:startup.
rem Впиши реальные значения и путь к скрипту.
set MAX_RELAY_URL=https://ДОМЕН/api/relay/max
set MAX_RELAY_SECRET=СЕКРЕТ_КАК_НА_СЕРВЕРЕ
start "max-relay" /min pythonw "%~dp0max_notify_win.py"
