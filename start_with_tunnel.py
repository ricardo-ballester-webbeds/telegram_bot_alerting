import subprocess
import requests
import time
import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import json
import asyncio
from telegram import Bot
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters


def get_secret():
    secret_name = "telegram/bot/credentials"
    region_name = "eu-west-3"

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
TOKEN = secrets["TELEGRAM_TOKEN"]
CHANNEL_ID = secrets["TELEGRAM_CHAT_ID"]  # secrets["TELEGRAM_CHANNEL_ID"]
bot = Bot(token=TOKEN)

if not TOKEN:
    print("❌ TELEGRAM_TOKEN not found in environment variables or secrets.")
    exit(1) 
print("🚀 Starting on Port 8000...")
lt_process = subprocess.Popen(
    ["npx", "localtunnel", "--port", "8000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

public_url = None
for line in lt_process.stdout:
    print(f"[lt] {line.strip()}")
    if "your url is" in line:
        public_url = line.strip().split(" ")[-1]
    if public_url:
        print(f"🌐 LocalTunnel URL detected: {public_url}")
        break
    if "error" in line.lower() or not public_url:
        print(f"❌ Error in LocalTunnel: {line.strip()}")
        lt_process.terminate()
        exit(1)
time.sleep(5)

if not public_url:
    print("❌ Could not detect public URL from LocalTunnel. Please check if LocalTunnel is running correctly.")
    lt_process.terminate()
    exit(1)
print(f"✅ Detected URL: {public_url}")
webhook_url = f"{public_url}"

set_webhook_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
response = requests.post(set_webhook_url, json={"url": f"{webhook_url}/{TOKEN}"})

application = Application.builder().token(TOKEN).build()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(asyncio.sleep(0))  # Ensure the event loop is running

async def notify():
    if response.status_code == 200 and response.json().get("ok"):
        print(f"✅ Webhook configured: {webhook_url}")
        await bot.send_message(chat_id=CHANNEL_ID, text='Webhook configured successfully! 🚀\rBot is still not running.')
    else:
        print(f"❌ Error configuring webhook: {response.text}")
        await bot.send_message(chat_id=CHANNEL_ID, text='Webhook configuration failed. Please check LocalTunnel and try again. ❌')
        lt_process.terminate()
        exit(1)
    print("📡 Awaiting Bot. Ctrl+C to stop.")

asyncio.run_coroutine_threadsafe(notify(), loop)

try:
    lt_process.wait()
except KeyboardInterrupt:
    print("🛑 Stopping LocalTunnel...")
    lt_process.terminate()
