import os
import logging
import requests
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from dotenv import load_dotenv
import asyncio

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
TOKEN_MINT = os.getenv("SPL_TOKEN_ADDRESS")
RPC_URL = os.getenv("RPC_URL")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
BOT_WALLET_ADDRESS = os.getenv("BOT_WALLET_ADDRESS")
BURN_ADDRESS = "11111111111111111111111111111111"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())
logging.basicConfig(level=logging.INFO)

user_sessions = {}
premium_users = {}  # telegram_user_id -> expiry datetime
whale_alert_subs = set()
verified_users = {}  # telegram_user_id -> wallet_address

async def ensure_verified(message: types.Message):
    user_id = message.from_user.id
    if user_id in verified_users:
        wallet = verified_users[user_id]
        if check_token_holding(wallet):
            return True
        else:
            verified_users.pop(user_id, None)
            await message.reply("❌ Deine Wallet hält aktuell weniger als 10.000 Tokens. Bitte erneut /start nutzen, wenn du später wieder Zugang möchtest.")
            return False
    else:
        await message.reply("Bitte starte mit /start, um deine Wallet zu verifizieren.")
        return False

def check_token_holding(wallet_address: str, min_amount: int = 10_000) -> bool:
    url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/balances?api-key={HELIUS_API_KEY}"
    resp = requests.get(url)
    if resp.status_code != 200:
        logging.warning("Token check failed for %s with status %s", wallet_address, resp.status_code)
        return False
    tokens = resp.json().get("tokens", [])
    for token in tokens:
        if token.get("mint") == TOKEN_MINT:
            try:
                raw_amount = int(token.get("amount", 0))
                decimals = int(token.get("decimals", 0))
                real_amount = raw_amount / (10 ** decimals)
                logging.info("Wallet %s holds %.2f tokens", wallet_address, real_amount)
                return real_amount >= min_amount
            except Exception as e:
                logging.error("Error parsing token amount: %s", e)
    logging.info("No matching token found in wallet %s", wallet_address)
    return False

def check_burn_transaction(tx_hash: str, wallet_address: str) -> bool:
    url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
    response = requests.post(url, json={"transactions": [tx_hash]})
    if response.status_code != 200:
        logging.warning(f"Burn tx check failed for tx {tx_hash}")
        return False
    tx = response.json()[0]
    for transfer in tx.get("tokenTransfers", []):
        if (
            transfer.get("mint") == TOKEN_MINT and
            transfer.get("fromUserAccount") == wallet_address and
            transfer.get("toUserAccount") == BURN_ADDRESS
        ):
            amount = int(transfer.get("tokenAmount", 0))
            return amount >= 100000
    return False

@dp.message_handler(commands=['start', 'menu'])
async def handle_start(message: types.Message):
    user_id = message.from_user.id
    if user_id in verified_users:
        wallet = verified_users[user_id]
        if not check_token_holding(wallet):
            verified_users.pop(user_id, None)
            await message.reply("❌ Deine Wallet hält aktuell weniger als 10.000 Tokens. Bitte erneut /start nutzen, wenn du später wieder Zugang möchtest.")
            return
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("📊 Balance anzeigen", callback_data="balance"),
            InlineKeyboardButton("🔥 Premiumstatus", callback_data="premium_status"),
            InlineKeyboardButton("🚨 Whale Alerts", callback_data="alerts_toggle")
        )
        await message.reply(f"✅ Willkommen zurück! Deine Wallet `{wallet}` ist verifiziert.", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    else:
        await message.reply("Bitte sende deine Wallet-Adresse zur Verifizierung:")
        user_sessions[user_id] = {"stage": "awaiting_wallet"}

@dp.message_handler(commands=["burn"])
async def start_burn(message: types.Message):
    await message.reply(
        f"""🔥 Um 7 Tage Premium zu aktivieren, sende **100.000 Tokens** an folgende Burn-Adresse:

🔹 Burn-Adresse:
`{BURN_ADDRESS}`

➡️ Danach sende den **TX-Hash** dieser Transaktion hier rein.""",
        parse_mode=ParseMode.MARKDOWN
    )
    user_sessions[message.from_user.id] = {"stage": "awaiting_burn_tx"}

@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    session = user_sessions.get(user_id, {})
    text = message.text.strip()

    if session.get("stage") == "awaiting_wallet":
        if len(text) < 32 or len(text) > 44:
            await message.reply("❌ Ungültige Wallet-Adresse.")
            return
        if not check_token_holding(text):
            await message.reply("❌ Deine Wallet hält nicht genug Tokens (min. 10.000).")
            return
        verified_users[user_id] = text
        await message.reply(f"✅ Wallet `{text}` erfolgreich verifiziert! Du kannst nun /menu verwenden.", parse_mode=ParseMode.MARKDOWN)
        user_sessions.pop(user_id, None)

    elif session.get("stage") == "awaiting_burn_tx":
        wallet = verified_users.get(user_id)
        if not wallet:
            await message.reply("❌ Wallet nicht gefunden. Bitte mit /start erneut verifizieren.")
            return
        if check_burn_transaction(text, wallet):
            premium_users[user_id] = datetime.utcnow() + timedelta(days=7)
            await message.reply("✅ Premium für 7 Tage aktiviert. Viel Spaß!")
        else:
            await message.reply("❌ Ungültige Transaktion. Stelle sicher, dass du 100k Tokens an die Burn-Adresse gesendet hast.")
        user_sessions.pop(user_id, None)
    else:
        await message.reply("❓ Bitte nutze /start oder /menu.")

@dp.callback_query_handler(lambda c: c.data == "balance")
async def balance_cb(call: types.CallbackQuery):
    wallet = verified_users.get(call.from_user.id)
    if not wallet:
        await call.message.answer("❌ Wallet nicht gefunden. Bitte erneut verifizieren.")
        return
    url = f"https://api.helius.xyz/v0/addresses/{wallet}/balances?api-key={HELIUS_API_KEY}"
    resp = requests.get(url)
    if resp.status_code != 200:
        await call.message.answer("Fehler beim Abrufen der Wallet-Daten.")
        return
    tokens = resp.json().get("tokens", [])
    for token in tokens:
        if token.get("mint") == TOKEN_MINT:
            raw_amount = int(token["amount"])
            decimals = int(token.get("decimals", 0))
            amount = raw_amount / (10 ** decimals)
            await call.message.answer(f"📊 Deine Balance: {amount:.2f} Token")
            return
    await call.message.answer("Keine Token gefunden.")

@dp.callback_query_handler(lambda c: c.data == "premium_status")
async def premium_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    expiry = premium_users.get(user_id)
    if expiry and expiry > datetime.utcnow():
        remaining = expiry - datetime.utcnow()
        await call.message.answer(f"✅ Dein Premium ist aktiv für noch {remaining.days} Tage und {remaining.seconds//3600} Stunden.")
    else:
        await call.message.answer("🔓 Kein aktives Premium. Verwende /burn für Zugang.")

@dp.callback_query_handler(lambda c: c.data == "alerts_toggle")
async def toggle_alerts_cb(call: types.CallbackQuery):
    user_id = call.from_user.id
    if user_id in whale_alert_subs:
        whale_alert_subs.remove(user_id)
        await call.message.answer("🚫 Whale Alerts deaktiviert.")
    else:
        whale_alert_subs.add(user_id)
        await call.message.answer("✅ Whale Alerts aktiviert. Du wirst benachrichtigt, wenn große Käufe stattfinden.")

async def whale_alert_job():
    seen_signatures = set()
    while True:
        try:
            tx_url = f"https://api.helius.xyz/v0/addresses/{BOT_WALLET_ADDRESS}/transactions?api-key={HELIUS_API_KEY}"
            resp = requests.get(tx_url)
            if resp.status_code != 200:
                logging.warning("Failed to fetch transactions")
                await asyncio.sleep(60)
                continue

            transactions = resp.json()
            now = datetime.utcnow()

            for tx in transactions:
                sig = tx.get("signature")
                if not sig or sig in seen_signatures:
                    continue

                seen_signatures.add(sig)

                if 'tokenTransfers' not in tx:
                    continue

                for transfer in tx['tokenTransfers']:
                    if transfer.get("tokenStandard") != "Fungible":
                        continue

                    mint = transfer.get("mint")
                    if not mint:
                        continue

                    volume = float(transfer.get("amount", 0))
                    if volume < 4:
                        continue

                    # Mint-Zeit ermitteln
                    mint_tx_url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions?api-key={HELIUS_API_KEY}"
                    mint_tx_resp = requests.get(mint_tx_url)
                    if mint_tx_resp.status_code != 200:
                        continue
                    mint_txs = mint_tx_resp.json()
                    if not mint_txs:
                        continue
                    mint_time_raw = mint_txs[-1].get("timestamp")
                    if not mint_time_raw:
                        continue
                    mint_time = datetime.fromisoformat(mint_time_raw.replace("Z", ""))
                    age_minutes = (now - mint_time).total_seconds() / 60
                    if age_minutes > 60:
                        continue

                    # Token-Metadaten
                    meta_url = f"https://api.helius.xyz/v0/tokens/metadata?api-key={HELIUS_API_KEY}"
                    meta_resp = requests.post(meta_url, json={"mintAccounts": [mint]})
                    if meta_resp.status_code != 200 or not meta_resp.json():
                        continue
                    meta = meta_resp.json()[0]
                    update_authority = meta.get("updateAuthority", "")
                    # ✅ Feste Pump.fun Authority
                    if update_authority != "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM":
                        continue

                    symbol = meta.get("symbol") or mint[:6]
                    buyer = tx.get("feePayer") or "Unbekannt"

                    fire = '🔥' * min(int(volume), 5)
                    msg = f"""🐋 *Whale Alert*
Token: `{symbol}`
Gekauft von: `{buyer}`
Menge: {volume:.2f} SOL
⏱️ Token ist {int(age_minutes)} Minuten alt
{fire}"""

                    for uid in whale_alert_subs:
                        try:
                            await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN)
                        except Exception as e:
                            logging.error(f"Send error to {uid}: {e}")

        except Exception as e:
            logging.error(f"Whale job error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(whale_alert_job())
    executor.start_polling(dp, skip_updates=True)
