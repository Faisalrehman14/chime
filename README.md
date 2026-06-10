# CHIMME — Chime Pay Anyone Auto-Claimer

Automatically monitors your Gmail for **Chime Pay Anyone** emails, extracts the **Claim your money** link, fills in your debit card, and logs everything so you never have to check mail manually again.

## Kya karta hai? (What it does)

1. Gmail check karta hai har 5 minute (configurable)
2. Emails detect karta hai: `You got $X from ... See how to claim`
3. **Claim your money** link nikalta hai
4. Browser se card details fill karke claim karta hai
5. SQLite database mein sab record rakhta hai
6. Optional Telegram notification bhejta hai

## Setup (pehli dafa)

### 1. Python environment

```bash
cd /home/fiasal/Downloads/CHIMME
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Gmail API (Google Cloud)

1. [Google Cloud Console](https://console.cloud.google.com/) par jao
2. New project banao → **APIs & Services** → **Enable Gmail API**
3. **OAuth consent screen** configure karo (External, add your Gmail)
4. **Credentials** → **Create OAuth Client ID** → Desktop app
5. Download JSON ko save karo as: `credentials/credentials.json`

### 3. Gmail connect

```bash
python setup_gmail.py
```

Browser khulega — apna Gmail login karo. Token `credentials/token.json` mein save ho jayega.

### 4. Card details (.env)

```bash
cp .env.example .env
nano .env
```

Fill in your real debit card (same card you use manually to claim):

```
CARD_NUMBER=4242424242424242
CARD_EXPIRY=12/28
CARD_CVV=123
CARD_ZIP=10001
CARDHOLDER_NAME=Your Name
```

Optional Telegram alerts:

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Usage

### Web UI (recommended — easy)

```bash
python main.py web
```

Browser mein kholo: **http://127.0.0.1:8787**

- Dashboard: total claimed, status, recent activity
- **Check Now** button — foran Gmail check
- **Start Background** — har 5 min auto check
- **Settings** tab — card details yahan se save karo

### CLI (optional)

```bash
# Ek dafa check + claim
python main.py once

# Background daemon (no UI)
python main.py watch

# History / stats dekho
python main.py status
```

## Background service (optional)

```bash
# ~/.config/systemd/user/chimme.service
[Unit]
Description=CHIMME Chime Auto Claimer
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/fiasal/Downloads/CHIMME
ExecStart=/home/fiasal/Downloads/CHIMME/.venv/bin/python main.py watch
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now chimme.service
```

## Security

- **Never commit** `.env` or `credentials/` — already in `.gitignore`
- Card details sirf local `.env` mein rakho
- Gmail token bhi local rehta hai

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Missing credentials.json` | Google Cloud se OAuth JSON download karo |
| `Could not find card number field` | Chime page layout change hua — `HEADLESS=false` set karo aur browser dekho |
| `no_link` status | Email HTML mein link nahi mila — forward sample email for parser update |
| Claim fails | Same card use karo jo manually kaam karta hai |

## Files

```
CHIMME/
├── main.py              # once | watch | status
├── setup_gmail.py       # Gmail OAuth
├── src/
│   ├── gmail_watcher.py # Gmail API
│   ├── email_parser.py  # Link + amount extract
│   ├── chime_claimer.py # Playwright auto-claim
│   ├── database.py      # SQLite logs
│   └── notifier.py      # Console + Telegram
└── data/claims.db       # Auto-created history
```
