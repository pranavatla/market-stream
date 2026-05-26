# NIFTY Options Console

Python (FastAPI) execution + risk backend **and** a browser dashboard, combined.
Buys NIFTY index options (CE/PE) intraday through Angel One SmartAPI, with a
hard risk engine, a manual-confirm step, a kill switch, and an optional Claude
advisory layer that gives a second opinion (it never places orders).

```
WebSocket / REST feed ──► Risk engine (hard limits) ──► you confirm ──► SmartAPI
                                  ▲
                          Claude advisory (optional, read-only)
```

## Setup

```bash
cd nifty
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your 4 Angel creds
```

## Keys you need (and how to fetch them)

Fill `nifty/.env` (start from `nifty/.env.example`):

- `ANGEL_API_KEY` (required)
  - SmartAPI developer portal (`smartapi.angelbroking.com`) → create an app → copy the API Key shown for that app.
  - SmartAPI may also show a “Secret Key”; this project does not use it, but keep it safe anyway.
- `ANGEL_CLIENT_ID` (required)
  - Your Angel One **Client Code** (same ID you use to log in; visible in the Angel One app/web profile).
- `ANGEL_MPIN` (required)
  - Your Angel One trading MPIN/PIN (the one you log in with).
- `ANGEL_TOTP_SEED` (required)
  - Enable TOTP/2FA for SmartAPI, then capture the Base32 secret from the QR / setup key.
  - If your authenticator QR contains an `otpauth://...secret=XXXX...` URL, set `ANGEL_TOTP_SEED=XXXX` (not the 6‑digit code).
  - Tip: if you can copy the `otpauth://...` URL somewhere, you can extract the secret like this:
    - `python3 - <<'PY'\nfrom urllib.parse import urlparse, parse_qs\nu=input('otpauth url: ').strip()\nq=parse_qs(urlparse(u).query)\nprint(q.get('secret',[None])[0])\nPY`
- `ANTHROPIC_API_KEY` (optional)
  - Only needed for the read-only Claude advisory panel (`/analyze`). If unset, the app still trades; advisory will show an error.
- `ANTHROPIC_MODEL` (optional)
  - Defaults to `claude-3-5-sonnet-latest`.

## Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — the dashboard is served by the backend.

## Trade flow (manual mode)

1. Enter symbol / expiry (e.g. `29MAY2025`) / strike / lots
2. **Quote CE** or **Quote PE** → see live LTP, qty, max premium outlay
3. (optional) **Run Advisory** → Claude's risk read of your thesis
4. **Prepare Order** → dry-run; risk engine vets it and returns the exact order
5. **Execute Live Order** → only this step actually sends to Angel One
6. **Square Off All** / **KILL** are always one click away

## Safety defaults baked in

- **Buying options only.** Naked selling is disabled in `orders.py`.
- Per-trade and per-day loss caps; auto kill-switch on daily loss breach.
- Entry window + forced square-off time.
- Max lots / open positions / orders-per-day caps.
- Manual confirm before every live order (`CONFIRM_MODE=manual`).

## Before going live — checklist

- [ ] Verify `NIFTY_LOT_SIZE` against the current exchange contract spec
- [ ] Test the full flow during market hours with **1 lot** and tight caps
- [ ] Confirm expiry string format matches the scrip master (`29MAY2025`)
- [ ] Keep `.env` out of git (already gitignored)
- [ ] Watch the first few fills manually before trusting auto mode

## What this is not

This is execution + risk plumbing with a human (you) in the loop. The signal
logic is intentionally **yours** to define — the Claude layer reviews setups,
it does not predict direction or fire trades. Encode your own edge in the entry
rules before flipping `CONFIRM_MODE` to `auto`.

> Trading index options carries real risk of loss. Test small. The kill switch
> exists for a reason.
