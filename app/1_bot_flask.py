import os
import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import threading
from dotenv import load_dotenv

# ===========================
# 🔐 Load credentials
# ===========================
if os.getenv("LOCAL_DEV"):
    load_dotenv()

TOKEN = os.getenv("ALERT_REMINDER_BOT_API")
CHANNEL_ID = os.getenv("TELEGRAM_LOG_CHAT_ID")
LOG_CHANNEL_ID = os.getenv("OLD_ALERTS_CHANNEL_ID")

# ===========================
# 📦 BotState with persistence
# ===========================
class BotState:
    def __init__(self):
        self.active_alert = False
        self.stopped = False
        self.last_alert_text = None

    def save(self, path="bot_state.json"):
        with open(path, "w") as f:
            json.dump(self.__dict__, f)

    def load(self, path="bot_state.json"):
        try:
            with open(path) as f:
                self.__dict__.update(json.load(f))
        except FileNotFoundError:
            pass

state = BotState()
state.load()

# ===========================
# 🌐 FastAPI
# ===========================
app = FastAPI()

# ===========================
# 🤖 Telegram Bot
# ===========================
application = Application.builder().token(TOKEN).build()

# ===========================
# 🛠 Helpers
# ===========================
async def log_event(text: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_text = f"[{timestamp}] {text}"
    print(log_text)
    try:
        await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)
    except Exception as e:
        print(f"[ERROR] Failed to send log to LOG_CHANNEL_ID: {e}")

# ===========================
# 🔁 Reminder & Keep-alive loops
# ===========================
async def repeat_alerts_loop():
    while True:
        if state.active_alert and state.last_alert_text:
            msg = f"🔔 Reminder!\n{state.last_alert_text}"
            try:
                await application.bot.send_message(chat_id=CHANNEL_ID, text=msg)
                await log_event(f"Reminder sent: {state.last_alert_text}")
            except Exception as e:
                await log_event(f"Error sending reminder: {e}")
        elif state.stopped and state.last_alert_text:
            # Only log once per webhook when stopped
            await log_event(
                f"Reminder skipped (active_alert=False, stopped=True, last_alert_text={state.last_alert_text})"
            )
            state.last_alert_text = None  # prevent repeated logs
        await asyncio.sleep(120)  # 2 minutes

async def keep_alive_loop():
    while True:
        await log_event("✅ Keep-alive: Bot is running fine. Next reminder in 30 min.")
        await asyncio.sleep(1800)  # 30 minutes

# ===========================
# ⏩ Telegram Commands
# ===========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.active_alert = False
    state.stopped = False
    state.save()
    await update.message.reply_text("✅ Alerts activated. Waiting for next Grafana alert.")
    await log_event("/start received → Alerts activated.")

async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.active_alert = False
    state.stopped = False
    state.save()
    await update.message.reply_text("⏸️ Alerts paused until next Grafana alert.")
    await log_event("/break received → Alerts paused until next Grafana alert.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state.active_alert = False
    state.stopped = True
    state.save()
    await update.message.reply_text("🛑 Alerts fully stopped. Use /start to reactivate.")
    await log_event("/stop received → Alerts fully stopped.")

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("break", break_command))
application.add_handler(CommandHandler("stop", stop))

# ===========================
# 📩 Grafana webhook
# ===========================
@app.post("/grafana-webhook")
async def grafana_webhook(request: Request):
    payload = await request.json()
    await log_event(f"🎁 Webhook received: {payload}")
    try:
        alert = payload["alerts"][0]
        alert_name = alert["labels"].get("alertname", "Unknown")
        summary = alert["annotations"].get("summary", "No summary")
        text = f"🚨 Grafana Alert 🚨\nAlert: {alert_name}\nSummary: {summary}"

        if not state.stopped:
            state.active_alert = True
            state.last_alert_text = text
            state.save()
            await application.bot.send_message(chat_id=CHANNEL_ID, text=text)
            await log_event(f"Alert sent to channel: {alert_name}")
            return {"status": "Alert sent"}
        else:
            state.last_alert_text = text  # store for skipped log
            return {"status": "Alert received but ignored (stopped)"}
    except Exception as e:
        await log_event(f"Error processing webhook: {e}")
        return {"error": str(e)}
    
# ===========================
# Command handler (Telegram webhook)
# ===========================
@app.post(f"/{TOKEN}")
async def telegram_webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, application.bot)
    asyncio.create_task(application.process_update(update))
    return {"status": "ok"}

# ===========================
# 🛑 Startup & Shutdown events
# ===========================
@app.on_event("startup")
async def on_startup():
    await application.initialize()
    await application.start()
    await application.bot.send_message(chat_id=CHANNEL_ID, text="🚀 Bot started and alerts active.")
    await log_event("Bot started successfully.")

    # Start background loops
    asyncio.create_task(repeat_alerts_loop())
    asyncio.create_task(keep_alive_loop())

@app.on_event("shutdown")
async def on_shutdown():
    # Aviso al canal de logs
    await log_event("❌ Bot shutting down...")

    # Aviso al canal principal ANTES de parar el bot
    try:
        await application.bot.send_message(chat_id=CHANNEL_ID, text="❌ BOT Stopped!")
    except Exception as e:
        print(f"[ERROR] Could not send shutdown notice: {e}")

    # Ahora sí, paramos el bot
    await application.stop()
    await application.shutdown()

# ===========================
# 🚀 Main
# ===========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
