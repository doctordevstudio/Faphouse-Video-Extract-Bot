import os
import re
import uuid
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN")
VERCEL_API_URL = os.environ.get("VERCEL_API_URL")
CLOUDFLARE_URL = os.environ.get("CLOUDFLARE_URL")
PORT = int(os.environ.get("PORT", 5000))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Simple in-memory cache to hold streams for the download button callback
DOWNLOAD_CACHE = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Welcome! Send me a Faphouse URL to extract the video.")

@bot.message_handler(func=lambda message: True)
def handle_url(message):
    url = message.text.strip()
    
    if not re.search(r'faphouse\.com|faphouse2\.com', url):
        bot.reply_to(message, "❌ Invalid URL. Only faphouse.com and faphouse2.com are supported.")
        return

    msg = bot.reply_to(message, "⏳ Extracting video data via Vercel...")

    try:
        response = requests.get(f"{VERCEL_API_URL}?url={url}", timeout=25)
        data = response.json()

        if "error" in data:
            bot.edit_message_text(f"❌ Error: {data['error']}", chat_id=message.chat.id, message_id=msg.message_id)
            return
            
        title = data.get("title", "Unknown")
        quality = data.get("quality", "HD")
        duration = data.get("duration", "00:00")
        thumb = data.get("thumbnail_url")
        master_url = data.get("hls_master_url")
        streams = data.get("streams", {})

        # Generate unique ID for download callback cache
        cache_id = str(uuid.uuid4())[:8]
        DOWNLOAD_CACHE[cache_id] = {
            "master": master_url,
            "streams": streams
        }

        caption = (
            f"🎬 <b>Title:</b> {title}\n"
            f"📺 <b>Quality:</b> {quality}\n"
            f"⏳ <b>Duration:</b> {duration}"
        )

        markup = InlineKeyboardMarkup()
        # Play Button opens Telegram Mini App pointing to Cloudflare
        play_url = f"{CLOUDFLARE_URL}?url={master_url}"
        markup.add(InlineKeyboardButton("▶️ Play Video", web_app=WebAppInfo(url=play_url)))
        # Download Button triggers Telegram callback
        markup.add(InlineKeyboardButton("⬇️ Download Video", callback_data=f"dl_{cache_id}"))

        if thumb:
            bot.send_photo(message.chat.id, photo=thumb, caption=caption, parse_mode="HTML", reply_markup=markup)
            bot.delete_message(message.chat.id, msg.message_id)
        else:
            bot.edit_message_text(caption, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML", reply_markup=markup)

    except Exception as e:
        bot.edit_message_text("❌ Failed to communicate with Vercel backend.", chat_id=message.chat.id, message_id=msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def handle_download(call):
    cache_id = call.data.split('_')[1]
    video_data = DOWNLOAD_CACHE.get(cache_id)

    if not video_data:
        bot.answer_callback_query(call.id, "Session expired. Please send the link again.", show_alert=True)
        return

    text = (
        "<b>Steps to download video:</b>\n\n"
        "1. Download <b>Lj Video Downloader</b> from the Play Store.\n"
        "2. Copy the desired m3u8 link below.\n"
        "3. Paste the m3u8 link in the Lj Video Downloader link section to download it.\n\n"
        "<b>Available Qualities (Tap to copy):</b>\n\n"
    )

    if video_data['master']:
        text += f"Master (Auto):\n`{video_data['master']}`\n\n"

    for res, link in video_data['streams'].items():
        text += f"{res}p:\n`{link}`\n\n"

    bot.send_message(call.message.chat.id, text, parse_mode="HTML", disable_web_page_preview=True)
    bot.answer_callback_query(call.id)

# Webhook Server for Render
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '!', 200

@app.route('/')
def index():
    return "Bot is running on Render!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    # Replace with your actual Render URL
    # IMPORTANT: Ensure your Render environment variables include RENDER_EXTERNAL_URL (Render sets this automatically usually)
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", f"https://{os.environ.get('RENDER_SERVICE_NAME')}.onrender.com")
    bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=PORT)
