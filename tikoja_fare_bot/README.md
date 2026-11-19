# TIKOJA Flight Fare Intelligence — Website + WhatsApp starter

This project includes a responsive agent website, a country selector containing all 249 ISO-listed countries/territories, date selection, passenger/cabin/trip preferences, a transparent fare scenario calculator, FastAPI backend, fare-history storage, TripJack adapter placeholders, and a Meta WhatsApp Cloud API webhook scaffold.

## What works now
- Website form: origin/destination countries, city/airport/IATA text, departure/return dates, adults/children/infants, cabin, currency, airline preference, stops, direct/refundable preferences.
- Estimate API and low/expected/high scenario calculations.
- SQLite fare observation history.
- Health endpoint.
- WhatsApp webhook verification, basic text parsing (`AMD PQC YYYY-MM-DD passengers`) and outbound message function when Meta credentials are configured.
- Protected server-side TripJack pass-through endpoints for the exact documented supplier payload.

## What is NOT live yet
TripJack live search and repricing are not enabled until Tikoja supplies its account-specific flight API collection and UAT credentials. The code intentionally does not invent TripJack endpoint paths, auth headers, payload schemas, or response fields. The website's live-search button explains this status rather than fabricating live prices. The WhatsApp assistant can receive and reply once Meta is configured, but does not yet return flight results until TripJack's exact search/repricing mapping is implemented.

## Run locally
1. Install Python 3.10+.
2. `cd backend`
3. `python -m venv .venv` and activate it.
4. `pip install -r requirements.txt`
5. Copy `.env.example` to `.env`; keep credentials private.
6. Start backend: `uvicorn main:app --reload --port 8000`
7. Serve the frontend folder with a static server, e.g. from `frontend`: `python -m http.server 5500`. Open `http://localhost:5500`.
8. API docs: `http://localhost:8000/docs`.

If the frontend is hosted elsewhere, set `localStorage.setItem('tikoja_api_url','https://YOUR-BACKEND-DOMAIN')` in browser developer console or change the `API` constant in `index.html`. Configure `CORS_ORIGINS` to your actual frontend domain before deployment.

## TripJack activation checklist
Obtain from TripJack: (a) flight API Postman collection/OpenAPI pack, (b) UAT base URL and credentials, (c) search request/response examples, (d) fare quote/revalidation examples, (e) fare rules and booking-class/inventory fields, (f) IP allowlisting and certification requirements. Map these exact contracts into `/tripjack/flights/search` and `/tripjack/flights/revalidate`; then normalize supplier results for the UI and WhatsApp. A requested passenger count being available at a fare does not prove the next fare bucket. Revalidate before quote/booking.

## WhatsApp activation checklist
Create/configure a Meta developer app and WhatsApp Business Cloud API phone number. Set `META_WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET`, and a strong `META_VERIFY_TOKEN` in backend `.env`. Configure the Meta webhook callback URL as `https://YOUR-DOMAIN/whatsapp/webhook`, subscribe to `messages`, and set the same verify token. Use HTTPS in production. Test inbound/outbound messaging with an approved test recipient. Ensure your WhatsApp templates/24-hour customer-service-window rules comply with Meta policy.

## Security / production notes
- Never put TripJack or Meta secrets in frontend code or send them in chat.
- Use HTTPS, a secret manager, restrictive CORS, authentication/roles for agents, rate limiting, audit logs, backups and privacy/consent notices before public launch.
- The WhatsApp webhook verifies Meta signatures when `META_APP_SECRET` is set; do not disable this in production.
- Country selection is country-level only. The user must enter a city, airport or IATA code because country names do not uniquely identify airports.
- The fare uplift calculator is a scenario model, not a trained prediction model. Calibrate it with timestamped fare observations and test on held-out historical data before presenting confidence scores.
