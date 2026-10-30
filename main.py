import os
import re
import uuid
import time
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN")
VERCEL_API_URL = os.environ.get("VERCEL_API_URL")
CLOUDFLARE_URL = os.environ.get("CLOUDFLARE_URL")
TG_ADMIN_CHAT_ID = os.environ.get("TG_ADMIN_CHAT_ID")
PORT = int(os.environ.get("PORT", 5000))

# threaded=False is required for Render/Gunicorn to properly reply to webhooks
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

DOWNLOAD_CACHE = {}
KNOWN_USERS = set()  # Tracks users who started the bot to avoid duplicate admin alerts

# Set Webhook globally so it registers when Gunicorn boots the worker
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
if RENDER_URL:
    RENDER_URL = RENDER_URL.rstrip('/')
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")

def notify_admin_new_user(user):
    if not TG_ADMIN_CHAT_ID:
        return
        
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else "No Username"
    
    caption = (
        f"🆕 <b>New User Started Bot</b>\n\n"
        f"👤 <b>Name:</b> {full_name}\n"
        f"📛 <b>Username:</b> {username}\n"
        f"🆔 <b>Chat ID:</b> <code>{user.id}</code>"
    )
    
    try:
        photos = bot.get_user_profile_photos(user.id)
        if photos.total_count > 0:
            photo_id = photos.photos[0][-1].file_id
            bot.send_photo(TG_ADMIN_CHAT_ID, photo=photo_id, caption=caption, parse_mode="HTML")
        else:
            bot.send_message(TG_ADMIN_CHAT_ID, text=caption, parse_mode="HTML")
    except Exception as e:
        print(f"Admin notification failed: {e}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if user_id not in KNOWN_USERS:
        KNOWN_USERS.add(user_id)
        notify_admin_new_user(message.from_user)
        
    bot.reply_to(message, "👋 Welcome! Send me a Faphouse URL to extract the video.")

@bot.message_handler(func=lambda message: True)
def handle_url(message):
    url = message.text.strip()
    user = message.from_user
    
    if not re.search(r'faphouse\.com|faphouse2\.com', url):
        bot.reply_to(message, "❌ Invalid URL. Only faphouse.com and faphouse2.com are supported.")
        return

    # Notify admin about the link extraction
    if TG_ADMIN_CHAT_ID:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = f"@{user.username}" if user.username else "No Username"
        admin_alert = (
            f"📥 <b>Video Extraction Requested</b>\n\n"
            f"👤 <b>By:</b> {full_name} ({username})\n"
            f"🆔 <b>Chat ID:</b> <code>{user.id}</code>\n"
            f"🔗 <b>Link:</b> {url}"
        )
        try:
            bot.send_message(TG_ADMIN_CHAT_ID, text=admin_alert, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass

    msg = bot.reply_to(message, "⏳ Extracting video data...")

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
        if master_url:
            master_url = master_url.strip("'\" ")
            
        streams = data.get("streams", {})
        clean_streams = {str(res): str(link).strip("'\" ") for res, link in streams.items()}

        cache_id = str(uuid.uuid4())[:8]
        DOWNLOAD_CACHE[cache_id] = {
            "master": master_url,
            "streams": clean_streams
        }

        caption = (
            f"🎬 <b>Title:</b> {title}\n"
            f"📺 <b>Quality:</b> {quality}\n"
            f"⏳ <b>Duration:</b> {duration}"
        )

        markup = InlineKeyboardMarkup()
        if master_url:
            play_url = f"{CLOUDFLARE_URL}?url={master_url}"
            markup.add(InlineKeyboardButton("▶️ Play Video", web_app=WebAppInfo(url=play_url)))
            
        markup.add(InlineKeyboardButton("⬇️ Download Video", callback_data=f"dl_{cache_id}"))

        if thumb:
            bot.send_photo(message.chat.id, photo=thumb, caption=caption, parse_mode="HTML", reply_markup=markup)
            bot.delete_message(message.chat.id, msg.message_id)
        else:
            bot.edit_message_text(caption, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="HTML", reply_markup=markup)

    except Exception:
        bot.edit_message_text("❌ Failed to communicate with extraction server.", chat_id=message.chat.id, message_id=msg.message_id)

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

    if video_data.get('master'):
        text += f"Master (Auto):\n<code>{video_data['master']}</code>\n\n"

    for res, link in video_data.get('streams', {}).items():
        text += f"{res}p:\n<code>{link}</code>\n\n"

    bot.send_message(call.message.chat.id, text, parse_mode="HTML", disable_web_page_preview=True)
    bot.answer_callback_query(call.id)

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Forbidden', 403

@app.route('/')
def index():
    return "Bot is running on Render!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
