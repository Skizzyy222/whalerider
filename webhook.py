from fastapi import FastAPI, Header, HTTPException
import requests
from datetime import datetime, timezone
import os
import logging
import threading
from aiogram import Bot
from storage import load_users  # dynamische Nutzerverwaltung

<<<<<<< HEAD
# Initialisierung
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
=======
bot = Bot(token=os.getenv("TELEGRAM_API_TOKEN"))
>>>>>>> 02994a5a4f99903d71bebb8375bb549011982a90
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# Konfiguration
PUMP_AUTH = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"
TELEGRAM_USERS = load_users()
recent_alerts = set()  # Zum Deduplizieren von Alerts (Token+Käufer)

def get_mint_timestamp(mint):
    """Ruft den Mint-Zeitpunkt eines Tokens ab"""
    try:
        url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions?api-key={os.getenv('HELIUS_API_KEY')}"
        txs = requests.get(url).json()
        ts = datetime.fromisoformat(txs[-1]["timestamp"].replace("Z", "+00:00"))
        return ts
    except Exception as e:
        logging.warning(f"Fehler bei get_mint_timestamp für {mint}: {e}")
        return datetime.now(timezone.utc)

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

    # Spam-Schutz: Duplikat-Check
    alert_key = f"{mint}_{buyer}"
    if alert_key in recent_alerts:
        return {"status": "duplicate"}
    recent_alerts.add(alert_key)
    threading.Timer(300, lambda: recent_alerts.discard(alert_key)).start()  # 5 Min Cooldown

    fire = "🔥" * min(int(sol_sent), 5)
    msg = (
        f"🐋 *Whale Alert*\n"
        f"Token: `{symbol}`\n"
        f"Gekauft von: `{buyer}`\n"
        f"Betrag: {sol_sent:.2f} SOL\n"
        f"⏱️ Alter: {int(age)} Minuten\n"
        f"{fire}"
    )

    # Nachricht an alle gespeicherten User
    for uid in TELEGRAM_USERS:
        try:
            await bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Fehler beim Senden an {uid}: {e}")

    return {"status": "sent"}
