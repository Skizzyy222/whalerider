import os
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException
from aiogram import Bot
import requests
import asyncio

# Initialisierung
logging.basicConfig(level=logging.INFO)
bot = Bot(token=os.getenv("TELEGRAM_API_TOKEN"))
app = FastAPI()

PUMP_AUTH = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
RATE_LIMIT_SECONDS = 30  # mindestens 30 Sekunden Pause zwischen Alerts pro Token
last_alert_time = {}     # mint -> datetime


def load_telegram_users():
    try:
        with open("whale_users.txt", "r") as f:
            return [int(line.strip()) for line in f if line.strip().isdigit()]
    except FileNotFoundError:
        return []


def get_mint_timestamp(mint):
    url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions?api-key={os.getenv('HELIUS_API_KEY')}"
    txs = requests.get(url).json()
    ts = datetime.fromisoformat(txs[-1]["timestamp"].replace("Z", "+00:00"))
    return ts


@app.post("/pumpwhale")
async def pump_webhook(payload: dict, authorization: str = Header(None)):
    if authorization != os.getenv("AUTH_HEADER"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    tx_type = payload.get("type")
    if tx_type not in ("BUY", "SWAP"):
        return {"status": "ignored"}

    token_transfers = payload.get("tokenTransfers", [])
    if not token_transfers:
        return {"status": "no token transfers"}

    mint = token_transfers[0].get("mint")
    if not mint:
        return {"status": "no mint"}

    # Ratenbegrenzung
    now = datetime.now(timezone.utc)
    last_sent = last_alert_time.get(mint)
    if last_sent and (now - last_sent).total_seconds() < RATE_LIMIT_SECONDS:
        return {"status": "rate limited"}

    # Volumen prüfen
    native_transfers = payload.get("nativeTransfers", [])
    sol_sent = sum(t.get("amount", 0) for t in native_transfers) / 1e9
    if sol_sent < 10:
        return {"status": "unter 10 SOL"}

    # Alter prüfen
    try:
        mint_time = get_mint_timestamp(mint)
    except Exception as e:
        logging.warning(f"Mint-Zeit konnte nicht ermittelt werden: {e}")
        return {"status": "mint lookup failed"}

    age = (now - mint_time).total_seconds() / 60
    if age > 60:
        return {"status": "Token zu alt"}

    # Metadaten holen
    try:
        meta = requests.post(
            f"https://api.helius.xyz/v0/tokens/metadata?api-key={os.getenv('HELIUS_API_KEY')}",
            json={"mintAccounts": [mint]}
        ).json()[0]
    except Exception as e:
        logging.warning(f"Metadatenfehler: {e}")
        return {"status": "meta fetch failed"}

    if meta.get("updateAuthority") != PUMP_AUTH:
        return {"status": "nicht Pump.fun"}

    symbol = meta.get("symbol", mint[:6])
    buyer = payload.get("feePayer", "Unbekannt")
    fire = "🔥" * min(int(sol_sent), 5)

    msg = (
        f"🐋 *Whale Alert*\n"
        f"Token: `{symbol}`\n"
        f"Gekauft von: `{buyer}`\n"
        f"Betrag: {sol_sent:.2f} SOL\n"
        f"⏱️ Alter: {int(age)} Minuten\n"
        f"{fire}"
    )

    TELEGRAM_USERS = load_telegram_users()

    for uid in TELEGRAM_USERS:
        try:
            await bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            logging.warning(f"Fehler beim Senden an {uid}: {e}")

    last_alert_time[mint] = now
    return {"status": "sent"}
