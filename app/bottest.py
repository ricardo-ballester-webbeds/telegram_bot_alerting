import os
import signal
import sys
import asyncio
from dotenv import load_dotenv
# from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue,
)

# from telegram_bot_alerting.app.bot_copy import BotState

# =========================================================
# 🔑 Credentials loading
# =========================================================
load_dotenv()
TOKEN = os.getenv("ALERT_REMINDER_BOT_API")
# CHANNEL_ID = int(os.getenv("TELEGRAM_LOG_CHAT_ID"))
# LOG_CHANNEL_ID = int(os.getenv("OLD_ALERTS_CHANNEL_ID"))
# GRAFANA_BOT_ID = int(os.getenv("GRAFANA_BOT_ID"))

# =========================================================
# 🛠️ Helpers
# =========================================================
# async def log_event(application: Application, text: str):
#     """Send logs both to console and log channel."""
#     timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     log_text = f"[{timestamp}] {text}"
#     print(log_text)
#     try:
#         await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)
#     except Exception as e:
#         print(f"[ERROR] Failed to send log to channel: {e}")

# =========================================================
# 🔁 Reminder loop
# =========================================================
# async def repeat_alerts(context: ContextTypes.DEFAULT_TYPE):
#     state: BotState = context.application.bot_data["state"]
#     if state.active_alert and state.last_alert_text:
#         msg = f"🔔 Alert Reminder!\n{state.last_alert_text}"
#         try:
#             await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
#             await log_event(context.application, f"Reminder sent: {state.last_alert_text}")
#         except Exception as e:
#             await log_event(context.application, f"Error sending reminder: {e}", level="error")
#     else:
#         await log_event(
#             context.application,
#             f"Reminder job executed but skipped (active_alert={state.active_alert}, last_alert_text={state.last_alert_text})"
#         )

# =========================================================
# ⏰ Keepalive
# =========================================================
# async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
#     await log_event(context.application, "Keep-alive check: Bot is running fine. Next reminder in 30 min.")

# =========================================================
# 📲 Commands
# =========================================================
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     state: BotState = context.application.bot_data["state"]
#     state.active_alert = False
#     state.stopped = False
#     state.save()
#     await update.message.reply_text("✅ Alerts activated. Waiting for next Grafana alert.")
#     await log_event(context.application, "/start received → Alerts activated.")

# async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     state: BotState = context.application.bot_data["state"]
#     state.active_alert = False
#     state.stopped = True
#     state.save()
#     await update.message.reply_text("🛑 Alerts fully stopped. Use /start to reactivate.")
#     await log_event(context.application, "/stop received → Alerts fully stopped.")

# async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     state: BotState = context.application.bot_data["state"]
#     state.active_alert = False
#     state.stopped = False
#     state.save()
#     await update.message.reply_text("⏸️ Alerts paused until next Grafana alert.")
#     await log_event(context.application, "/break received → Alerts paused.")

# async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     help_text = (
#         "🆘 Help:\n"
#         "/start - Activate reminders (waits for next Grafana alert).\n"
#         "/break - Pause reminders until next Grafana alert.\n"
#         "/stop - Stop reminders completely."
#     )
#     await update.message.reply_text(help_text)

# =========================================================
# 📩 Message handler (Grafana bot)
# =========================================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG RAW UPDATE:", update.to_dict())  # 👈 imprimimos todo el update que llega

# =========================================================
# 🛑 Controlled shutdown
# =========================================================
def shutdown(application: Application):
    async def _shutdown():
        # await log_event(application, "❌ Bot shutting down...")
        await application.stop()
        await application.shutdown()
        sys.exit(0)

    asyncio.run_coroutine_threadsafe(_shutdown(), asyncio.get_event_loop())

# =========================================================
# 🚀 Main
# =========================================================
def main():
    # async def on_startup(app: Application):
    #     await app.bot.send_message(chat_id=CHANNEL_ID, text="🚀 Bot started and alerts active.")
    #     await log_event(app, "Bot started successfully.")

    application = (
        Application.builder()
        .token(TOKEN)
        # .post_init(on_startup)
        .job_queue(JobQueue())
        .build()
    )

    # application.bot_data["state"] = state

    # Command handlers
    # application.add_handler(CommandHandler("start", start))
    # application.add_handler(CommandHandler("stop", stop))
    # application.add_handler(CommandHandler("break", break_command))
    # application.add_handler(CommandHandler("help", help_command))

    # Message handler (coger TODO lo que llegue)
    application.add_handler(MessageHandler(filters.ALL, handle_messages))

    # Job queue: reminders every 2 min
    # application.job_queue.run_repeating(repeat_alerts, interval=120, first=10)

    # Job queue: keep-alive every 30 min
    # application.job_queue.run_repeating(keep_alive, interval=1800, first=18)

    # Capture shutdown signals
    signal.signal(signal.SIGINT, lambda s, f: shutdown(application))
    signal.signal(signal.SIGTERM, lambda s, f: shutdown(application))

    print("✅ Bot started and polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
