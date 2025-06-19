from fastapi import FastAPI, Request, Header, HTTPException
import requests
from datetime import datetime, timezone
import os
from aiogram import Bot

bot = Bot(token=os.getenv("TELEGRAM_API_TOKEN"))
app = FastAPI()

PUMP_AUTH = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
TELEGRAM_USERS = []  # TODO: dynamisch füllen oder testen mit eigener Telegram-ID

def get_mint_timestamp(mint):
    url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions?api-key={os.getenv('HELIUS_API_KEY')}"
    txs = requests.get(url).json()
    ts = datetime.fromisoformat(txs[-1]["timestamp"].replace("Z", "+00:00"))
    return ts

@app.post("/pumpwhale")
async def pump_webhook(payload: dict, authorization: str = Header(None)):
    if authorization != os.getenv("AUTH_HEADER"):
        raise HTTPException(401)

    tx_type = payload.get("type")
    if tx_type not in ("BUY", "SWAP"):
        return {"status": "ignored"}

    token_transfers = payload.get("tokenTransfers", [])
    if not token_transfers:
        return {"status": "no token transfers"}

    mint = token_transfers[0].get("mint")
    if not mint:
        return {"status": "no mint"}

    # Volumen prüfen
    native_transfers = payload.get("nativeTransfers", [])
    sol_sent = sum(t.get("amount", 0) for t in native_transfers) / 1e9
    if sol_sent < 4:
        return {"status": "unter 4 SOL"}

    # Alter des Tokens prüfen
    mint_time = get_mint_timestamp(mint)
    now = datetime.now(timezone.utc)
    age = (now - mint_time).total_seconds() / 60
    if age > 60:
        return {"status": "Token zu alt"}

    # Token-Metadaten prüfen
    meta = requests.post(
        f"https://api.helius.xyz/v0/tokens/metadata?api-key={os.getenv('HELIUS_API_KEY')}",
        json={"mintAccounts": [mint]}
    ).json()[0]

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

    for uid in TELEGRAM_USERS:
        await bot.send_message(uid, msg, parse_mode="Markdown")

    return {"status": "sent"}
