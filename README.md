# another-try

Flask backend and site for menu publishing and delivery orders, prepared for deployment to Vercel.

## Local run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

By default the app uses a local SQLite database in `instance/menu.db`. For production on Vercel, set `DATABASE_URL` to Postgres.

## Vercel deploy

The repository is configured for Vercel's Python runtime:

- `app.py` is the Vercel entrypoint
- `build.py` copies `app/static` into `public/static` before each deploy
- `vercel.json` forces the `flask` framework preset, configures the build command and cron job
- `GET /api/tasks/sync-menu` is protected by `CRON_SECRET`

Required environment variables:

- `DATABASE_URL`
- `AUTH_URL`
- `PRESTO_BASE_URL`
- `APP_CLIENT_ID`
- `APP_SECRET`
- `SECRET_KEY` or `FLASK_SECRET_KEY`
- `PRESTO_POINT_ID`
- `PRESTO_PRICE_LIST_ID`
- `CRON_SECRET`

Optional environment variables:

- `PRESTO_ORDER_URL`
- `PRESTO_DELIVERY_COST_URL`

Deployment steps:

1. Push the repository to GitHub.
2. Import the repository into Vercel.
3. Add environment variables from `.env.example` in the Vercel project settings.
4. Ensure `Output Directory` is empty in Vercel project settings.
5. Deploy to production.

The default cron schedule is `0 5 * * *` in UTC. This is compatible with the Hobby plan. If you use a paid Vercel plan, you can change it to a more frequent schedule in `vercel.json`.

Flask zero-config deployments on Vercel are not customized through `functions.app.py` in `vercel.json`. If you need to change duration or memory for the generated function, do it in the Vercel dashboard.

## Useful endpoints

- `GET /`
- `GET /menu`
- `GET /api/health`
- `GET /api/menu`
- `POST /api/orders`
- `GET /api/tasks/sync-menu` with `Authorization: Bearer <CRON_SECRET>`
