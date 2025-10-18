# TrendMerch (Flask + Tailwind)

TrendMerch is a print-on-demand e-commerce store for trending phrases, fads, and memes. It integrates with Gelato (POD), Stripe for payments, and exposes a Google Shopping feed. Trends ingestion uses Google Trends via pytrends, with manual admin approval before publishing products.

## Local Setup

1) Create a Python virtual environment and install dependencies:

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1  # Windows PowerShell
pip install -r requirements.txt
```

2) Create a `.env` file with the variables below (see Environment Variables section).

3) Run the dev server:

```bash
flask --app app run --debug
```

4) Tailwind CSS (Dev):

```bash
npm install
npm run dev:css
```

Open http://localhost:5000

## Environment Variables (.env)

FLASK_ENV=development
SECRET_KEY=dev-secret
DATABASE_URL=sqlite:///trendmerch.db
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
GELATO_API_KEY=
MARKUP_PERCENT=35
STORE_CURRENCY=USD
BASE_URL=http://localhost:5000

## Deployment (Heroku)

- Set config vars as above
- `Procfile` and `runtime.txt` are included

## Notes

- Pricing uses a 35% markup over Gelato base costs
- Stripe uses the embedded Payment Element checkout
- Auto-generated products from trends require manual admin approval before publishing
- Design generation can start text-only; AI images can be added later
