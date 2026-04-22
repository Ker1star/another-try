# Vercel Deploy

## Files already prepared

- `app.py` is the Vercel entrypoint
- `build.py` copies `app/static` into `public/static`
- `vercel.json` configures the build command, function duration and cron
- `DATABASE_URL` is used for Neon/Postgres
- `/api/tasks/sync-menu` is a protected cron endpoint

## Required environment variables

- `DATABASE_URL`
- `AUTH_URL`
- `PRESTO_BASE_URL`
- `PRESTO_ORDER_URL` optional
- `PRESTO_DELIVERY_COST_URL` optional
- `APP_CLIENT_ID`
- `APP_SECRET`
- `SECRET_KEY` or `FLASK_SECRET_KEY`
- `PRESTO_POINT_ID`
- `PRESTO_PRICE_LIST_ID`
- `CRON_SECRET`

## Vercel setup

1. Push the project to GitHub.
2. Import the repository into Vercel.
3. In `Settings -> Environment Variables`, add all variables from `.env.example`.
4. Set `CRON_SECRET` to a long random string.
5. Deploy.

## After first deploy

Run one protected sync request to ensure the production environment can refresh menu data:

```bash
curl -H "Authorization: Bearer YOUR_CRON_SECRET" https://YOUR-PROJECT.vercel.app/api/tasks/sync-menu
```

## Cron behavior

- Vercel cron calls `GET /api/tasks/sync-menu`
- Schedule is defined in `vercel.json`
- Current default schedule: `0 5 * * *` in UTC
- This schedule is chosen to stay compatible with the Vercel Hobby plan
- If you use a paid Vercel plan, you can increase the frequency later

## Useful endpoints

- `GET /api/health`
- `GET /api/menu`
- `POST /api/orders`
- `GET /api/tasks/sync-menu` with `Authorization: Bearer <CRON_SECRET>`
