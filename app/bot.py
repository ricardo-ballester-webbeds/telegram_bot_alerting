import threading
import time
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import CommandHandler, ContextTypes, Application, MessageHandler, filters
import os
from dotenv import load_dotenv
from datetime import datetime
import asyncio
import boto3
from botocore.exceptions import ClientError
import json

def get_secret():
    secret_name = "telegram/bot/credentials"
    region_name = "eu-west-3"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    secret = json.loads(get_secret_value_response['SecretString'])
    return secret

secrets = get_secret()

# Cargar variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# Running locally
# TOKEN = os.getenv("TELEGRAM_TOKEN")
# CHANNEL_ID = os.getenv("TELEGRAM_CHAT_ID") # os.getenv("TELEGRAM_CHANNEL_ID")

# Running in AWS
TOKEN = secrets["TELEGRAM_TOKEN"]
CHANNEL_ID = secrets["TELEGRAM_CHAT_ID"] # secrets["TELEGRAM_CHANNEL_ID"]

active_alert = True
# repeat = True
start_time = None
end_time = None

bot = Bot(token=TOKEN)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# Construcción de la app
application = Application.builder().token(TOKEN).build()
repeat_event = threading.Event()

async def setup_application():
    await application.initialize()
    print("✅ Application initialized")

# Inicializar la aplicación de forma asíncrona
loop.run_until_complete(setup_application())

asyncio.run_coroutine_threadsafe(
    application.bot.send_message(chat_id=CHANNEL_ID, text='🚨 BOT Started!'),
    loop
)

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_loop, args=(loop,), daemon=True).start()

def while_in_time():
    if start_time is None or end_time is None:
        return False
    now = datetime.now().hour
    if start_time == end_time:
        return True  # Full 24h coverage
    if start_time < end_time:
        return start_time <= now < end_time
    else:
        return now >= start_time or now < end_time  # Crossing midnight

def repeat_alerts(loop):
    while True:
        if active_alert and repeat_event.is_set() and while_in_time():
            print(f'{datetime.now()}: Sending alert reminder')
            asyncio.run_coroutine_threadsafe(
                application.bot.send_message(chat_id=CHANNEL_ID, text='🔔 Alert Reminder!'),
                loop
            )
        time.sleep(5)  # (180)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_alert, repeat_event
    await update.message.reply_text('🛑 Stopped manually.')
    repeat_event.clear()  # Set the event to stop the repeat loop
    active_alert = False
    print("🔴 Alert stopped by user command")

async def break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global start_time, repeat_event
    now = datetime.now().hour
    start_time = (now + 1) % 24  # Set start_time to the next hour
    repeat_event.clear()  # Clear the event to stop the repeat loop
    await update.message.reply_text(f"⏸️ Paused alerts until {start_time:02d}:00. End at {end_time:02d}:00 UTC.")
    print(f"🛑 Break activated — new start_time: {start_time}. End time at {end_time:02d}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🔍 /start command triggered")
    args = context.args
    now_hour = datetime.now().hour
    global active_alert, start_time, end_time
    print(f"📩 Raw message: {update.message.text}")
    print(f'Context args: {args}')
    
    if not args: # If no arguments are provided, set default start and end times
        start_time = now_hour
        end_time = now_hour
        active_alert = True
        await update.message.reply_text(f'✅ Active undefinied hours.\nCovering 24 hours alerts from now.\nRemember schedule alerts with /start HH-HH.')
    elif len(args) == 1 and '-' in args[0]: # If one argument is provided with a dash
        try:
            parts = args[0].split('-')
            start_time = int(parts[0]) % 24
            end_time = int(parts[1]) % 24
            active_alert = True
            print(f"active_alert: {active_alert}, repeat: {repeat_event.is_set()}, start_time: {start_time}, end_time: {end_time}, while_in_time: {while_in_time()}")
            await update.message.reply_text(f'✅ Active from {start_time:02d}:00 until {end_time:02d}:00 UTC.')
        except:
            await update.message.reply_text('❌ Wrong hour interpretation. Use format HH-HH.')
    else:
        await update.message.reply_text('❌ Wrong Format. Use "/start 21-07" to set alert from 21:00 to 07:00 UTC or /start for 24h Cover.')
        return

application.add_handler(CommandHandler('stop', stop))
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('break', break_command))
print("✅ Handlers for /start and /stop added")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    print(f"[TELEGRAM WEBHOOK] Payload received: {data}")
    text = data.get("message", "No message")
    print(f"Webhook received: {text}")
    try:
        if active_alert and while_in_time():
            repeat_event.set()  # Set the event to allow the repeat loop to run
            asyncio.run_coroutine_threadsafe(message_sending(str(text)), loop)
            print(f'{datetime.now()}: Sending alert reminder')
            return jsonify({"status": "This alert is received and acknowledged"}), 200
        else:
            print(f'{datetime.now()}: No active alert or outside time range')
            return jsonify({"status": "No active alert or outside time range"}), 425
    except Exception as e:
        print("Error en webhook:", e)
        return jsonify({"error": str(e)}), 500

async def message_sending(text):
    print(f'📤 Sending message to group')
    await application.bot.send_message(chat_id=CHANNEL_ID, text=f'🚨 New Alert received! \n{text}')

@app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    json_data = request.get_json(force=True)
    print("▶️ Update received in Webhook: [PAYLOAD]", json_data)
    update = Update.de_json(json_data, application.bot)
    print(f"Update message text: {update.message.text if update.message else 'No message'}")

    future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    print("▶️ Dispatched update to application.process_update()")
    print(f'The update is: ', update)
    
    try:
        result = future.result(timeout=10)  # Wait up to 10 seconds for the result
        if result is not None:
            print(f"✅ Update processed with result: {result}")
        else:
            print("✅ Update processed with no result.")
    except asyncio.TimeoutError:
        timeout_message = f"⚠️ Timeout while processing update: {update}"
        print(timeout_message)
        send_timeout_message = asyncio.run_coroutine_threadsafe(
            application.bot.send_message(chat_id=CHANNEL_ID, text='⚠️ Timeout while processing update.'),
            loop
        )
        send_timeout_message.result()
    except Exception as e:
        # Handle any other exceptions that occur during processing
        send_error_message = asyncio.run_coroutine_threadsafe(
            application.bot.send_message(chat_id=CHANNEL_ID, text=f'❌ Error processing update: {e}'),
            loop
        )
        send_error_message.result()
        # Log the error and traceback
        print(f"❌ Error processing update: {e}")
        import traceback
        print("🔴 Traceback:")
        traceback.print_exc()
    
    return 'ok, app received your webhook'

if __name__ == '__main__':
    threading.Thread(target=repeat_alerts, args=(loop,), daemon=True).start()
    app.run(port=5000)
    send_finish_message = asyncio.run_coroutine_threadsafe(
        application.bot.send_message(chat_id=CHANNEL_ID, text='❌ BOT Stopped! ❌'),
        loop
    )
    send_finish_message.result()  # Wait for the message to be sent
    loop.stop()
    print("🚀 Flask app stopped listening on port 5000")