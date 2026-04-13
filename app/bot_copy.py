import os
import sys
import signal
import asyncio
import logging
from dotenv import load_dotenv
from datetime import datetime
from dataclasses import dataclass, asdict, field
import json

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue,
)

# =========================================================
# 🔑 Credentials loading
# =========================================================
load_dotenv()
TOKEN = os.getenv("ALERT_REMINDER_BOT_API")
CHANNEL_ID = int(os.getenv("TELEGRAM_LOG_CHAT_ID"))
LOG_CHANNEL_ID = int(os.getenv("OLD_ALERTS_CHANNEL_ID"))
GRAFANA_BOT_ID = int(os.getenv("GRAFANA_BOT_ID"))

# =========================================================
# 📦 Bot State
# =========================================================
@dataclass
class BotState:
    active_alert: bool = False
    stopped: bool = False
    last_alert_text: str = None
    # Para persistencia opcional:
    # state_file: str = "bot_state.json"

    def save(self):
        """Guardar estado a JSON (opcional)."""
        # with open(self.state_file, "w") as f:
        #     json.dump(asdict(self), f)
        pass

    def load(self):
        """Cargar estado desde JSON (opcional)."""
        # if os.path.exists(self.state_file):
        #     with open(self.state_file, "r") as f:
        #         data = json.load(f)
        #         self.active_alert = data.get("active_alert", False)
        #         self.stopped = data.get("stopped", False)
        #         self.last_alert_text = data.get("last_alert_text")
        pass


# =========================================================
# ⚙️ Logging setup
# =========================================================
logger = logging.getLogger("AlertBot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


async def log_event(application: Application, text: str, level: str = "info"):
    """Send logs to console and log channel."""
    getattr(logger, level)(text)
    try:
        await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}")
    except Exception as e:
        logger.error(f"Failed to send log to channel: {e}")


# =========================================================
# 🔁 Reminder loop
# =========================================================
async def repeat_alerts(context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    if state.active_alert:
        msg = f"🔔 Alert Reminder!\n{state.last_alert_text}"
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
            await log_event(context.application, f"Reminder sent: {state.last_alert_text}")
        except Exception as e:
            await log_event(context.application, f"Error sending reminder: {e}", level="error")
    else:
        await log_event(context.application, "Reminder skipped (no active alert).")


# =========================================================
# ⏰ Keepalive
# =========================================================
async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    await log_event(context.application, "✅ Keep-alive: Bot is running fine.")


# =========================================================
# 📲 Commands
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = False
    await update.message.reply_text("✅ Alerts activated. Waiting for next Grafana alert.")
    await log_event(context.application, "/start received → Alerts activated.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = True
    await update.message.reply_text("🛑 Alerts fully stopped. Use /start to reactivate.")
    await log_event(context.application, "/stop received → Alerts fully stopped.")


async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = False
    await update.message.reply_text("⏸️ Alerts paused until next Grafana alert.")
    await log_event(context.application, "/break received → Alerts paused.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 Help:\n"
        "/start - Activate reminders (waits for next Grafana alert).\n"
        "/break - Pause reminders until next Grafana alert.\n"
        "/stop - Stop reminders completely."
    )
    await update.message.reply_text(help_text)


# =========================================================
# 📩 Message handler (Grafana bot)
# =========================================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    message = update.message

    if message.from_user.id == context.bot.id:
        return

    if message.from_user.id == GRAFANA_BOT_ID:
        if state.stopped:
            await log_event(context.application, f"Ignored Grafana alert (stopped): {message.text}")
            return

        state.last_alert_text = message.text or "<No text>"
        state.active_alert = True
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 New Alert received!\n{state.last_alert_text}",
            )
            await log_event(context.application, f"Grafana alert received: {state.last_alert_text}")
        except Exception as e:
            await log_event(context.application, f"Error sending Grafana alert: {e}", level="error")


# =========================================================
# 🛑 Controlled shutdown
# =========================================================
def shutdown(application: Application):
    async def _shutdown():
        await log_event(application, "❌ Bot shutting down...")
        await application.stop()
        await application.shutdown()
        sys.exit(0)

    try:
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(_shutdown(), loop)
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        sys.exit(1)


# =========================================================
# 🚀 Main
# =========================================================
def main():
    async def on_startup(app: Application):
        await app.bot.send_message(chat_id=CHANNEL_ID, text="🚀 Bot started and alerts active.")
        await log_event(app, "Bot started successfully.")

    state = BotState()
    state.load()  # opcional

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(on_startup)
        .job_queue(JobQueue())
        .build()
    )

    # Guardar el estado en bot_data para acceso global
    application.bot_data["state"] = state

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("break", break_command))
    application.add_handler(CommandHandler("help", help_command))

    # Message handler
    application.add_handler(MessageHandler(filters.ALL, handle_messages))

    # Job queue: reminders every 2 min
    application.job_queue.run_repeating(repeat_alerts, interval=120, first=120)
    # Job queue: keep-alive every 30 min
    application.job_queue.run_repeating(keep_alive, interval=1800, first=1800)

    # Capture shutdown signals
    signal.signal(signal.SIGINT, lambda s, f: shutdown(application))
    signal.signal(signal.SIGTERM, lambda s, f: shutdown(application))

    print("✅ Bot started and polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
