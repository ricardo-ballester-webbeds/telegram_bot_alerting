import os
import asyncio
import signal
import sys
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- AWS Imports (para futuro uso con Secrets Manager) ---
# import boto3
# from botocore.exceptions import ClientError
# import json


# =========================================================
# 🔑 Credentials
# =========================================================

# --- Option 1: Environment variables (ACTIVE for local testing) ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = int(os.getenv("TELEGRAM_LOG_CHAT_ID"))
GRAFANA_BOT_ID = int(os.getenv("GRAFANA_BOT_ID"))  # ID of Grafana bot

# --- Option 2: Secrets Manager (commented for now) ---
"""
def get_secret():
    secret_name = "telegram/bot/credentials"
    region_name = "eu-west-3"
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise e
    secret = json.loads(get_secret_value_response["SecretString"])
    return secret

secrets = get_secret()
TOKEN = secrets["TELEGRAM_TOKEN"]
CHANNEL_ID = int(secrets["TELEGRAM_CHAT_ID"])
GRAFANA_BOT_ID = int(secrets["GRAFANA_BOT_ID"])
"""


# =========================================================
# ⚙️ Global variables
# =========================================================
active_alert = False
stopped = False
repeat_event = asyncio.Event()
last_alert_text = None


# =========================================================
# 🔁 Reminder job (using JobQueue instead of threading)
# =========================================================
async def repeat_alerts(context: ContextTypes.DEFAULT_TYPE):
    if active_alert and repeat_event.is_set():
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text="🔔 Alert Reminder!"
        )


# =========================================================
# 📲 Commands
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_alert, stopped
    active_alert = True
    stopped = False
    repeat_event.set()
    await update.message.reply_text("✅ Alerts activated. Reminders every 2 minutes.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_alert, stopped
    active_alert = False
    stopped = True  # ignore new alerts until someone sends /start
    repeat_event.clear()
    await update.message.reply_text("🛑 Alerts fully stopped. Use /start to reactivate.")


async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_alert, stopped
    active_alert = False
    stopped = False  # only pause, will resume with next Grafana alert
    repeat_event.clear()
    await update.message.reply_text("⏸️ Alerts paused until next Grafana alert.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 Help:\n"
        "/start - Manually start reminders every 2 minutes.\n"
        "/break - Pause reminders until next Grafana alert.\n"
        "/stop - Stop reminders completely."
    )
    await update.message.reply_text(help_text)


# =========================================================
# 📩 Message handler (Grafana Bot)
# =========================================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_alert, stopped, last_alert_text
    message = update.message

    # Ignore messages from our own bot
    if message.from_user.id == context.bot.id:
        return

    # Only activate if the message comes from Grafana bot
    if message.from_user.id == GRAFANA_BOT_ID and not stopped:
        last_alert_text = message.text or "<No text>"
        active_alert = True
        repeat_event.set()
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🚨 New Alert received!\n{last_alert_text}",
        )


# =========================================================
# 🛑 Controlled shutdown
# =========================================================
def shutdown(application):
    async def _shutdown():
        await application.bot.send_message(chat_id=CHANNEL_ID, text="❌ Bot stopped! ❌")
        await application.shutdown()
        await application.stop()
        sys.exit(0)

    asyncio.run_coroutine_threadsafe(_shutdown(), application.bot.loop)


# =========================================================
# 🚀 Main
# =========================================================
def main():
    async def on_startup(app: Application):
        await app.bot.send_message(chat_id=CHANNEL_ID, text="🚀 Bot started and alerts active.")

    application = Application.builder().token(TOKEN).post_init(on_startup).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("break", break_command))
    application.add_handler(CommandHandler("help", help_command))

    # Normal message handler
    application.add_handler(MessageHandler(filters.ALL, handle_messages))

    # Reminder job every 2 minutes
    application.job_queue.run_repeating(repeat_alerts, interval=120, first=120)

    # Start as if /start was already called
    global active_alert, stopped
    active_alert = True
    stopped = False
    repeat_event.set()

    # Capture stop signals
    signal.signal(signal.SIGINT, lambda s, f: shutdown(application))
    signal.signal(signal.SIGTERM, lambda s, f: shutdown(application))

    print("✅ Bot started and polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
