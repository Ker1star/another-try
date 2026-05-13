# Бэкапы БД

Ежедневный дамп Postgres локально (плюс опционально загрузка в облако).

## 1. Скрипт `/usr/local/bin/marta-backup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Загружаем DATABASE_URL из .env приложения
set -a
source /var/www/marta/.env
set +a

BACKUP_DIR=/var/backups/marta
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/marta_${TS}.sql.gz"

pg_dump "$DATABASE_URL" | gzip -9 > "$OUT"

# Чистим старые
find "$BACKUP_DIR" -name 'marta_*.sql.gz' -mtime +$KEEP_DAYS -delete

echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
```

```bash
chmod +x /usr/local/bin/marta-backup.sh
mkdir -p /var/backups/marta
apt install -y postgresql-client   # если pg_dump ещё не стоит
```

## 2. Cron — каждый день в 04:00

```bash
crontab -e
```

```
0 4 * * * /usr/local/bin/marta-backup.sh >> /var/log/marta-backup.log 2>&1
```

## 3. Проверка восстановления (раз в месяц)

```bash
# Распаковать последний дамп в тестовую БД
LAST=$(ls -t /var/backups/marta/marta_*.sql.gz | head -1)
createdb marta_restore_test
gunzip -c "$LAST" | psql marta_restore_test
# Проверить что таблицы на месте, потом удалить
dropdb marta_restore_test
```

## 4. Опционально — копия в облако

Если ставите rclone (есть Яндекс.Диск, S3, Google Drive, и т.д.):

```bash
# В конце marta-backup.sh добавить:
rclone copy "$OUT" yandex:marta-backups/ --quiet
```

Или просто `scp` на любой второй сервер.

## Что хранится в `/var/backups/marta/`

- Полный дамп Postgres (все таблицы, индексы, данные)
- Включает: меню, заказы, бронирования, PendingOrder
- НЕ включает: `.env`, фото в `static/images/`, кеш изображений

Фото из `static/images/marta/` отдельно бэкапить не обязательно — они уже в git.

## Восстановление

```bash
gunzip -c /var/backups/marta/marta_20260513_040000.sql.gz | psql "$DATABASE_URL"
```
