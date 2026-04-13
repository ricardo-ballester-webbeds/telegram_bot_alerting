import os
import signal
import sys
import asyncio
import json
from dotenv import load_dotenv
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue,
)

# ---------------------------------------------------------
# Simple BotState local (cambiar a S3 si quieres)
# ---------------------------------------------------------
class BotState:
    def __init__(self, active_alert=False, stopped=False, last_alert_text=None, state_file="bot_state.json"):
        self.active_alert = active_alert
        self.stopped = stopped
        self.last_alert_text = last_alert_text
        self.state_file = state_file

    def save(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "active_alert": self.active_alert,
                    "stopped": self.stopped,
                    "last_alert_text": self.last_alert_text,
                }, f, ensure_ascii=False)
        except Exception as e:
            # no raise: log and continue
            print(f"[ERROR] BotState.save() failed: {e}", file=sys.stderr)

    def load(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.active_alert = data.get("active_alert", False)
                self.stopped = data.get("stopped", False)
                self.last_alert_text = data.get("last_alert_text", None)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[ERROR] BotState.load() failed: {e}", file=sys.stderr)

# =========================================================
# Config
# =========================================================
load_dotenv()
TOKEN = os.getenv("ALERT_REMINDER_BOT_API")
CHANNEL_ID = int(os.getenv("TELEGRAM_LOG_CHAT_ID"))
LOG_CHANNEL_ID = int(os.getenv("OLD_ALERTS_CHANNEL_ID"))
GRAFANA_BOT_ID = int(os.getenv("GRAFANA_BOT_ID"))

# =========================================================
# Helpers: log_event (to channel) + debug print (console only)
# =========================================================
async def log_event(application: Application, text: str, level: str = "info"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_text = f"[{timestamp}] {text}"
    print(log_text)
    try:
        await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)
    except Exception as e:
        print(f"[ERROR] Failed to send log to channel: {e}", file=sys.stderr)

def debug_print(text: str):
    """Minimal console-only debug (no spam to Telegram channel)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DEBUG {timestamp}] {text}")

# =========================================================
# Job: repeat_alerts (safe)
# =========================================================
async def repeat_alerts(context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data.get("state")
    if not state:
        await log_event(context.application, "repeat_alerts skipped: state not initialized", level="warning")
        return

    if state.active_alert and state.last_alert_text:
        msg = f"🔔 Alert Reminder!\n{state.last_alert_text}"
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
            await log_event(context.application, f"Reminder sent: {state.last_alert_text}")
        except Exception as e:
            await log_event(context.application, f"Error sending reminder: {e}", level="error")
    else:
        await log_event(
            context.application,
            f"Reminder job executed but skipped (active_alert={state.active_alert}, last_alert_text={state.last_alert_text})"
        )

# =========================================================
# Keep-alive
# =========================================================
async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    await log_event(context.application, "✅ Keep-alive: Bot is running fine. Next reminder in 30 min.")

# =========================================================
# Commands
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = False
    state.save()
    await update.message.reply_text("✅ Alerts activated. Waiting for next Grafana alert.")
    await log_event(context.application, "/start received → Alerts activated.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = True
    state.save()
    await update.message.reply_text("🛑 Alerts fully stopped. Use /start to reactivate.")
    await log_event(context.application, "/stop received → Alerts fully stopped.")

async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    state.active_alert = False
    state.stopped = False
    state.save()
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
# Message handler (robust sender detection + debug)
# =========================================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG RAW UPDATE:", update.to_dict())  # 👈 imprimimos todo lo que llega
    state: BotState = context.application.bot_data.get("state")
    if not state:
        # shouldn't happen, but safe guard
        debug_print("handle_messages called but state not initialized.")
        return

    message = update.effective_message
    if not message:
        debug_print("handle_messages: update has no effective_message, ignoring.")
        return

    # Collect possible sender identifiers
    from_user = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)       # channel as sender
    forward_from = getattr(message, "forward_from", None)     # forwarded original sender
    via_bot = getattr(message, "via_bot", None)               # inline via bot
    chat = getattr(message, "chat", None)

    # Message text detection (text or caption)
    text_content = message.text if getattr(message, "text", None) else getattr(message, "caption", None)
    text_content = text_content or "<no-text>"

    # Debug print: show *all* candidate ids so you can inspect what Grafana actually sent
    candidate_ids = {
        "from_user_id": getattr(from_user, "id", None),
        "sender_chat_id": getattr(sender_chat, "id", None),
        "forward_from_id": getattr(forward_from, "id", None),
        "via_bot_id": getattr(via_bot, "id", None),
        "chat_id": getattr(chat, "id", None),
    }
    debug_print(f"DEBUG INCOMING: candidate_ids={candidate_ids}, text={repr(text_content)}")

    # Build a list of ids to compare with GRAFANA_BOT_ID
    ids_to_check = set()
    for v in candidate_ids.values():
        if isinstance(v, int):
            ids_to_check.add(v)

    # If none match, ignore but print for debugging
    if GRAFANA_BOT_ID not in ids_to_check:
        debug_print(f"Ignored incoming message: Grafana ID {GRAFANA_BOT_ID} not in {ids_to_check}")
        return

    # At this point, it's a Grafana message we want to process
    if state.stopped:
        await log_event(context.application, f"Ignored Grafana alert (stopped): {text_content}")
        return

    state.last_alert_text = text_content
    state.active_alert = True
    try:
        state.save()
    except Exception as e:
        await log_event(context.application, f"Warning: saving state failed: {e}", level="warning")

    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"🚨 New Alert received!\n{state.last_alert_text}")
        await log_event(context.application, f"Grafana alert received: {state.last_alert_text}")
    except Exception as e:
        await log_event(context.application, f"Error sending Grafana alert: {e}", level="error")

# =========================================================
# Shutdown
# =========================================================
def shutdown(application: Application):
    async def _shutdown():
        await log_event(application, "❌ Bot shutting down...")
        await application.stop()
        await application.shutdown()
        sys.exit(0)
    asyncio.run_coroutine_threadsafe(_shutdown(), asyncio.get_event_loop())

# =========================================================
# Main
# =========================================================
def main():
    async def on_startup(app: Application):
        await app.bot.send_message(chat_id=CHANNEL_ID, text="🚀 Bot started and alerts active.")
        await log_event(app, "Bot started successfully.")

    # Init state
    state = BotState()
    state.load()

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(on_startup)
        .job_queue(JobQueue())
        .build()
    )

    # store state BEFORE jobs/handlers
    application.bot_data["state"] = state

    # handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("break", break_command))
    application.add_handler(CommandHandler("help", help_command))

    # Keep your filter as TEXT & ~COMMAND (unchanged)
    # application.add_handler(MessageHandler(filters.ALL, handle_messages))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
    application.add_handler(MessageHandler(filters.ALL, handle_messages), group=-1)


    # Jobs
    application.job_queue.run_repeating(repeat_alerts, interval=120, first=10)
    application.job_queue.run_repeating(keep_alive, interval=1800, first=18)

    # signals
    signal.signal(signal.SIGINT, lambda s, f: shutdown(application))
    signal.signal(signal.SIGTERM, lambda s, f: shutdown(application))

    print("✅ Bot started and polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
