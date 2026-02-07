# DataTalk Events

Automated event aggregation and notification service for [DataTalk.cz](https://datatalk.cz). Scrapes upcoming events, enriches them with AI-generated summaries, and delivers notifications via email and Telegram.

## Quick Start

1. Copy the example environment file and fill in your keys:

```bash
cp .env.example .env
```

2. Start the application:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`.

## Development

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run tests:

```bash
python -m pytest tests/ -v
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | DataTalk Events | Application display name |
| `DEBUG` | false | Enable debug mode |
| `DATABASE_URL` | sqlite:///data/app.db | Database connection string |
| `SCRAPE_URL` | https://datatalk.cz/kalendar-akci/ | URL to scrape events from |
| `SCRAPE_SCHEDULE` | 0 8 * * 1 | Cron schedule for scraping |
| `OPENAI_API_KEY` | | OpenAI API key for AI summaries |
| `OPENAI_MODEL` | gpt-4o-mini | OpenAI model to use |
| `EMAIL_PROVIDER` | resend | Email provider (resend or sendgrid) |
| `RESEND_API_KEY` | | Resend API key |
| `SENDGRID_API_KEY` | | SendGrid API key |
| `EMAIL_FROM` | events@datatalk.cz | Sender email address |
| `TELEGRAM_BOT_TOKEN` | | Telegram bot token |
| `SECRET_KEY` | | Secret key for signing (required in production) |
| `WEBHOOK_URL` | http://localhost:8000 | Public webhook URL |
| `ADMIN_USERNAME` | admin | Admin panel username |
| `ADMIN_PASSWORD` | | Admin panel password (required in production) |
