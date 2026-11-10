# -*- coding: utf-8 -*-
"""
نسخة بوت تيليجرام المخصصة لتطبيق تيرموكس (Termux على أندرويد)
- تعمل في خلفية الهاتف 24/7 دون الحاجة للكمبيوتر
- مزودة برمز فيسبوك الدائم (Never Expires)
- تدعم تصميم البوسترات، الكروت الإخبارية، وختم الشعار على الصور والفيديو
"""
import os
import sys
import io
import re
import time
import json
import logging
import asyncio
import textwrap
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import requests
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from telegram.request import HTTPXRequest
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------- الإعدادات -----------------
import base64 as _b64
_DEFAULT_TG = _b64.b64decode("OTAzMzIzOTc2NzpBQUd3Ym9pSmo5TnVHeXdWM2ItZDdzWlZRdDVfX1hhN1BmOA==").decode()
_DEFAULT_FB = _b64.b64decode("RUFBWkE0Y1JLYW5mTUJTemkyeWNaQUNrMXBwWFpCenJIbkVuc0w2UlpCTXpsMGFxTjFFclN0NVlSSk1JenZkTDZkbUZGOTZZV25oZnVxdXJyTWFodmdST2pqblZERlREMXd6bnhiNFFaQjNqZFZTaUJPMWVPN2Q5MFVvSTRIbEVaQjZTeUxXWEZpQVJ3ZENaQmhIeWF0cTZaQ05qUmZQMUN4TWRSYlhsRWQ0b3FqSXFJY0FoUkpjMTJmMGV0czZUajU5V3dKcnhv").decode()

TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or _DEFAULT_TG)
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "6181150735"))

FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "902750569586784").strip()
FACEBOOK_PAGE_TOKEN = (os.environ.get("FACEBOOK_PAGE_TOKEN", "").strip() or _DEFAULT_FB)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
FONT_FILE = os.path.join(BASE_DIR, "font.otf")
if not os.path.exists(FONT_FILE):
    FONT_FILE = os.path.join(BASE_DIR, "font.ttf")

FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

OFFICIAL_HASHTAGS = "\n\n#منسيون_خلف_القضبان #الحرية_للمختطفين #اليمن"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

drafts = {}
user_states = {}

# تحميل خط عربي تلقائياً إذا لم يتوفر
def ensure_font():
    pass

# لوحة المفاتيح التفاعلية الدائمة أسفل الشاشة
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📰 أحدث الأخبار (48 ساعة)"), KeyboardButton("🎨 تصميم بوستر حقوقي")],
        [KeyboardButton("🚨 نداء عاجل ومناشدة"), KeyboardButton("🤖 توليد مشهد بالذكاء")],
        [KeyboardButton("ℹ️ طريقة الاستخدام والأوامر")]
    ],
    resize_keyboard=True,
    is_persistent=True
)

def format_arabic(text: str) -> str:
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def format_news(raw_text: str) -> str:
    text = raw_text.strip()
    if "#منسيون_خلف_القضبان" not in text:
        text += OFFICIAL_HASHTAGS
    return text

def is_authorized(user_id: int) -> bool:
    return user_id == AUTHORIZED_USER_ID

def apply_watermark(image_bytes: bytes) -> bytes:
    if not os.path.exists(LOGO_PATH):
        return image_bytes

    try:
        base_img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        logo_img = Image.open(LOGO_PATH).convert("RGBA")

        bbox = logo_img.getbbox()
        if bbox:
            logo_img = logo_img.crop(bbox)

        base_w, base_h = base_img.size
        target_logo_w = int(base_w * 0.16)
        w_percent = target_logo_w / float(logo_img.size[0])
        target_logo_h = int(float(logo_img.size[1]) * float(w_percent))
        
        logo_resized = logo_img.resize((target_logo_w, target_logo_h), Image.Resampling.LANCZOS)

        margin_x = int(base_w * 0.04)
        margin_y = int(base_h * 0.04)
        position = (margin_x, base_h - target_logo_h - margin_y)

        watermarked = base_img.copy()
        watermarked.paste(logo_resized, position, logo_resized)

        output = io.BytesIO()
        watermarked.convert("RGB").save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"Error applying watermark: {e}")
        return image_bytes

def apply_video_watermark(input_video_bytes: bytes) -> bytes:
    if not os.path.exists(LOGO_PATH):
        return input_video_bytes

    try:
        logo_img = Image.open(LOGO_PATH).convert("RGBA")
        bbox = logo_img.getbbox()
        if bbox:
            logo_img = logo_img.crop(bbox)
        
        timestamp = int(time.time() * 1000)
        temp_logo = os.path.join(BASE_DIR, f"temp_logo_{timestamp}.png")
        logo_img.save(temp_logo, format="PNG")

        temp_in = os.path.join(BASE_DIR, f"temp_in_{timestamp}.mp4")
        temp_out = os.path.join(BASE_DIR, f"temp_out_{timestamp}.mp4")

        with open(temp_in, "wb") as f:
            f.write(input_video_bytes)

        w, h = 1280, 720
        try:
            probe_cmd = [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", temp_in]
            out = subprocess.check_output(probe_cmd, timeout=10).decode().strip()
            if "x" in out:
                parts = out.split("x")
                w, h = int(parts[0]), int(parts[1])
        except Exception:
            pass

        logo_w = max(80, int(w * 0.16))
        margin_x = max(15, int(w * 0.04))
        margin_y = max(15, int(h * 0.04))

        filter_str = f"[1:v]scale={logo_w}:-1[logo_s];[0:v][logo_s]overlay={margin_x}:main_h-overlay_h-{margin_y}"

        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", temp_in,
            "-i", temp_logo,
            "-filter_complex", filter_str,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "copy",
            temp_out
        ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode == 0 and os.path.exists(temp_out):
            with open(temp_out, "rb") as f:
                output_bytes = f.read()
        else:
            output_bytes = input_video_bytes

        for p in (temp_in, temp_out, temp_logo):
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass

        return output_bytes
    except Exception as e:
        print(f"Error watermarking video: {e}")
        return input_video_bytes

def paste_logo(card: Image.Image, pad: int = 60, target_w: int = 175) -> None:
    if not os.path.exists(LOGO_PATH):
        return
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        logo_h = int(target_w * (logo.size[1] / logo.size[0]))
        logo_resized = logo.resize((target_w, logo_h), Image.Resampling.LANCZOS)
        card.paste(logo_resized, (pad + 15, card.height - logo_h - 40), logo_resized)
    except Exception as e:
        print(f"Error drawing logo: {e}")

def get_font(size: int):
    candidates = [
        os.path.join(BASE_DIR, "font.otf"),
        os.path.join(BASE_DIR, "font.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()

# ----------------- قوالب التصاميم -----------------
def generate_news_card(text_content: str) -> bytes:
    width, height = 1080, 1080
    card = Image.new("RGB", (width, height), color=(18, 22, 28))
    draw = ImageDraw.Draw(card)
    draw.rectangle([(0, 0), (width, 16)], fill=(158, 27, 34))

    pad = 60
    draw.rounded_rectangle([(pad, 60), (width - pad, height - 160)], radius=24, fill=(28, 34, 44), outline=(45, 54, 70), width=3)
    draw.rounded_rectangle([(width - pad - 20, 90), (width - pad - 10, height - 190)], radius=4, fill=(158, 27, 34))

    clean_lines = [l.strip() for l in text_content.splitlines() if l.strip() and not l.startswith("#")]
    body_summary = " ".join(clean_lines[:6])
    text_len = len(body_summary)

    font_size = 48 if text_len < 70 else (38 if text_len < 150 else 30)
    line_spacing = 74 if text_len < 70 else (62 if text_len < 150 else 50)
    wrap_width = 24 if text_len < 70 else (32 if text_len < 150 else 38)

    font_badge = get_font(28)
    font_body = get_font(font_size)
    font_footer = get_font(24)

    draw.text((width - pad - 50, 100), format_arabic("تغطية إخبارية | منسيون خلف القضبان"), fill=(212, 160, 23), font=font_badge, anchor="ra")

    wrapped = textwrap.wrap(body_summary, width=wrap_width)
    total_text_h = len(wrapped[:8]) * line_spacing
    box_top, box_bottom = 160, height - 190
    y_offset = box_top + max(20, ((box_bottom - box_top) - total_text_h) // 2)

    for line in wrapped[:8]:
        draw.text((width - pad - 50, y_offset), format_arabic(line), fill=(255, 255, 255), font=font_body, anchor="ra")
        y_offset += line_spacing

    paste_logo(card, pad=pad)
    draw.text((width - pad - 20, height - 80), format_arabic("#منسيون_خلف_القضبان  #الحرية_للمختطفين  #اليمن"), fill=(160, 175, 195), font=font_footer, anchor="ra")

    output = io.BytesIO()
    card.save(output, format="JPEG", quality=95)
    return output.getvalue()

def generate_advocacy_poster(text_content: str, header_title: str = "صوت من خلف القضبان") -> bytes:
    width, height = 1080, 1080
    card = Image.new("RGB", (width, height), color=(12, 15, 20))
    draw = ImageDraw.Draw(card)

    pad = 50
    draw.rounded_rectangle([(pad, pad), (width - pad, height - pad)], radius=28, outline=(40, 50, 68), width=3)
    draw.rounded_rectangle([(pad + 12, pad + 12), (width - pad - 12, height - pad - 12)], radius=20, outline=(158, 27, 34), width=2)

    header_box_w, header_box_h = 480, 60
    header_x = (width - header_box_w) // 2
    draw.rounded_rectangle([(header_x, pad + 25), (header_x + header_box_w, pad + 25 + header_box_h)], radius=15, fill=(158, 27, 34))

    clean_lines = [l.strip() for l in text_content.splitlines() if l.strip() and not l.startswith("#")]
    body_summary = " ".join(clean_lines[:6])
    text_len = len(body_summary)

    font_size = 46 if text_len < 80 else (36 if text_len < 160 else 28)
    line_spacing = 72 if text_len < 80 else (60 if text_len < 160 else 48)
    wrap_width = 25 if text_len < 80 else (33 if text_len < 160 else 40)

    font_title = get_font(28)
    font_body = get_font(font_size)
    font_footer = get_font(24)

    draw.text((width // 2, pad + 40), format_arabic(header_title), fill=(255, 255, 255), font=font_title, anchor="mm")

    wrapped = textwrap.wrap(body_summary, width=wrap_width)
    total_text_h = len(wrapped[:8]) * line_spacing
    box_top, box_bottom = pad + 140, height - pad - 140
    y_offset = box_top + max(10, ((box_bottom - box_top) - total_text_h) // 2)

    for line in wrapped[:8]:
        draw.text((width // 2, y_offset), format_arabic(line), fill=(245, 245, 245), font=font_body, anchor="mm")
        y_offset += line_spacing

    draw.line([(pad + 60, height - pad - 120), (width - pad - 60, height - pad - 120)], fill=(40, 50, 68), width=2)
    paste_logo(card, pad=pad, target_w=170)
    draw.text((width - pad - 20, height - pad - 50), format_arabic("#منسيون_خلف_القضبان  #الحرية_للمختطفين  #اليمن"), fill=(212, 160, 23), font=font_footer, anchor="ra")

    output = io.BytesIO()
    card.save(output, format="JPEG", quality=95)
    return output.getvalue()

def generate_urgent_card(text_content: str) -> bytes:
    width, height = 1080, 1080
    card = Image.new("RGB", (width, height), color=(15, 15, 18))
    draw = ImageDraw.Draw(card)

    pad = 55
    draw.rectangle([(0, 0), (width, 100)], fill=(185, 28, 28))
    
    font_alert = get_font(40)
    font_body = get_font(38)
    font_footer = get_font(24)

    draw.text((width // 2, 50), format_arabic("⚠️  نداء عاجل ومناشدة حقوقية  ⚠️"), fill=(255, 255, 255), font=font_alert, anchor="mm")
    draw.rounded_rectangle([(pad, 130), (width - pad, height - 160)], radius=20, fill=(25, 28, 36), outline=(185, 28, 28), width=3)

    clean_lines = [l.strip() for l in text_content.splitlines() if l.strip() and not l.startswith("#")]
    body_summary = " ".join(clean_lines[:6])
    wrapped = textwrap.wrap(body_summary, width=32)
    line_spacing = 62
    total_h = len(wrapped[:8]) * line_spacing
    y_offset = 180 + max(20, ((height - 350) - total_h) // 2)

    for line in wrapped[:8]:
        draw.text((width // 2, y_offset), format_arabic(line), fill=(255, 255, 255), font=font_body, anchor="mm")
        y_offset += line_spacing

    paste_logo(card, pad=pad)
    draw.text((width - pad - 20, height - 80), format_arabic("#منسيون_خلف_القضبان  #الحرية_للمختطفين  #اليمن"), fill=(200, 200, 210), font=font_footer, anchor="ra")

    output = io.BytesIO()
    card.save(output, format="JPEG", quality=95)
    return output.getvalue()

def generate_ai_artwork(prompt_text: str) -> bytes:
    keywords = "freedom, dramatic lighting, human rights, prisoners of conscience, hope, broken chains, dove, cinematic, 8k, emotional, realistic digital art"
    clean_p = prompt_text.replace("صمم", "").replace("ولد", "").replace("صورة", "").strip()
    english_query = f"{clean_p}, {keywords}"
    encoded = urllib.parse.quote(english_query)
    seed = int(time.time()) % 100000
    ai_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}"
    req = urllib.request.Request(ai_url, headers={'User-Agent': 'Mozilla/5.0'})
    raw_img = urllib.request.urlopen(req, timeout=30).read()
    return apply_watermark(raw_img)

# ----------------- أوامر البوت -----------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("⛔ عذراً، هذا البوت مخصص لإدارة صفحة 'منسيون خلف القضبان' فقط.")
        return

    welcome_text = (
        f"أهلاً بك يا {user.first_name} في بوت **منسيون خلف القضبان** (يعمل من تيرموكس على هاتفك) 🕊️📱\n\n"
        "البوت متصل بالرمز الدائم ويعمل 24 ساعة مباشرة من هاتفك!\n"
        "استخدم الأزرار التفاعلية أدناه:"
    )
    await update.message.reply_text(welcome_text, reply_markup=MAIN_MENU_KEYBOARD)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💡 **دليل البوت السريع:**\n\n"
        "• أرسل نصاً ⬅️ يتيح لك تصميمه (بوستر / كرت / نداء عاجل) أو نشره.\n"
        "• أرسل صورة ⬅️ يتيح لك نشرها بالشعار أو بدون شعار.\n"
        "• أرسل فيديو ⬅️ يتيح لك نشره بالشعار أو بدون شعار.\n"
        "• الأزرار السفلية ⬅️ وصول فوري لكل الخدمات."
    )
    await update.message.reply_text(help_text, reply_markup=MAIN_MENU_KEYBOARD)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    wait_msg = await update.message.reply_text("🔍 جاري جلب أحدث أخبار المختطفين خلال آخر 48 ساعة...")
    try:
        url = "https://news.google.com/rss/search?q=%D8%A7%D9%84%D9%85%D8%AE%D8%AA%D8%B7%D9%81%D9%8A%D9%86+%D8%A7%D9%84%D9%8A%D9%85%D9%86+when:3d&hl=ar&gl=YE&ceid=YE:ar"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=8)
        root = ET.fromstring(res.read())
        items = root.findall('.//item')[:3]

        if not items:
            await wait_msg.edit_text("لا توجد أخبار جديدة خلال 48 ساعة.")
            return

        try: await wait_msg.delete()
        except Exception: pass

        for idx, item in enumerate(items, 1):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            clean_title = title.split(" - ")[0] if " - " in title else title
            formatted = f"🚨 {clean_title}\n\n📅 التاريخ: {pub_date[:16]}\n\nللمزيد:{OFFICIAL_HASHTAGS}\n{link}"

            draft_id = f"auto_{idx}_{int(time.time()*1000)}"
            drafts[draft_id] = {"type": "text", "content": formatted, "raw": clean_title}

            keyboard = [
                [
                    InlineKeyboardButton("🎨 تصميم بوستر حقوقي", callback_data=f"style_advocacy_{draft_id}"),
                    InlineKeyboardButton("📰 كرت إخباري", callback_data=f"style_news_{draft_id}")
                ],
                [
                    InlineKeyboardButton("📝 نشر كنص", callback_data=f"publish_{draft_id}"),
                    InlineKeyboardButton("❌ تخطي", callback_data=f"cancel_{draft_id}")
                ]
            ]
            await update.message.reply_text(f"📰 **خبر ({idx}):**\n\n{formatted}", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
    except Exception as e:
        await wait_msg.edit_text(f"❌ تعذر جلب الأخبار: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    raw_text = update.message.text.strip()

    if raw_text == "📰 أحدث الأخبار (48 ساعة)":
        await news_command(update, context)
        return
    elif raw_text == "🎨 تصميم بوستر حقوقي":
        user_states[user_id] = "waiting_for_poster"
        await update.message.reply_text("✍️ أرسل الآن نص أو فكرة البوستر الذي تريده:")
        return
    elif raw_text == "🚨 نداء عاجل ومناشدة":
        user_states[user_id] = "waiting_for_urgent"
        await update.message.reply_text("⚠️ أرسل الآن نص النداء الإنساني العاجل:")
        return
    elif raw_text == "🤖 توليد مشهد بالذكاء":
        user_states[user_id] = "waiting_for_ai"
        await update.message.reply_text("🤖 صف المشهد الذي تود رسمه بالذكاء الاصطناعي:")
        return
    elif raw_text == "ℹ️ طريقة الاستخدام والأوامر":
        await help_command(update, context)
        return

    state = user_states.pop(user_id, None)
    if state == "waiting_for_poster":
        card_bytes = generate_advocacy_poster(raw_text)
        draft_id = f"custom_{int(time.time()*1000)}"
        drafts[draft_id] = {"type": "photo", "bytes": card_bytes, "caption": format_news(raw_text)}
        kb = [[InlineKeyboardButton("✅ نشر البوستر على فيسبوك", callback_data=f"publish_{draft_id}"), InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]]
        await update.message.reply_photo(photo=io.BytesIO(card_bytes), caption=f"✨ **تم تصميم البوستر بنجاح!**\n\n{format_news(raw_text)}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "waiting_for_urgent":
        card_bytes = generate_urgent_card(raw_text)
        draft_id = f"urgent_{int(time.time()*1000)}"
        drafts[draft_id] = {"type": "photo", "bytes": card_bytes, "caption": format_news(raw_text)}
        kb = [[InlineKeyboardButton("✅ نشر النداء على فيسبوك", callback_data=f"publish_{draft_id}"), InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]]
        await update.message.reply_photo(photo=io.BytesIO(card_bytes), caption=f"🚨 **تم إعداد النداء العاجل!**\n\n{format_news(raw_text)}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "waiting_for_ai" or re.match(r'^(ولد|ارسم|توليد|صورة\s+ذكاء)', raw_text, flags=re.IGNORECASE):
        await update.message.reply_text("🤖 جاري توليد المشهد بالذكاء الاصطناعي...")
        try:
            ai_bytes = generate_ai_artwork(raw_text)
            draft_id = f"ai_{int(time.time()*1000)}"
            drafts[draft_id] = {"type": "photo", "bytes": ai_bytes, "caption": format_news(raw_text)}
            kb = [
                [InlineKeyboardButton("✅ نشر الصورة على فيسبوك", callback_data=f"publish_{draft_id}")],
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"ai_regen_{draft_id}"), InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]
            ]
            await update.message.reply_photo(photo=io.BytesIO(ai_bytes), caption=f"🤖 **مشهد الذكاء الاصطناعي مع الشعار:**\n\n{format_news(raw_text)}", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            await update.message.reply_text(f"❌ تعذر التوليد: {e}")
        return

    formatted_text = format_news(raw_text)
    draft_id = f"text_{int(time.time()*1000)}"
    drafts[draft_id] = {"type": "text", "content": formatted_text, "raw": raw_text}

    keyboard = [
        [
            InlineKeyboardButton("🎨 بوستر حقوقي", callback_data=f"style_advocacy_{draft_id}"),
            InlineKeyboardButton("📰 كرت إخباري", callback_data=f"style_news_{draft_id}")
        ],
        [
            InlineKeyboardButton("🚨 نداء عاجل", callback_data=f"style_urgent_{draft_id}"),
            InlineKeyboardButton("📝 نشر كنص مباشر", callback_data=f"publish_{draft_id}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]
    ]

    await update.message.reply_text(
        f"📝 **معاينة المنشور:**\n━━━━━━━━━━━━━━━━━━━━━\n{formatted_text}\n━━━━━━━━━━━━━━━━━━━━━\nاختر قالب التصميم أو انشره مباشرة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    status_msg = await update.message.reply_text("🎨 جاري معالجة الصورة وتجهيز الخيارات...")

    try:
        photo = update.message.photo[-1]
        caption = update.message.caption or "الحرية للمختطفين والمخفيين قسراً.. أصواتهم لن تُنسى."
        formatted_caption = format_news(caption)

        file = await photo.get_file(read_timeout=30.0)
        raw_bytes = await file.download_as_bytearray(read_timeout=30.0)
        processed_bytes = apply_watermark(bytes(raw_bytes))

        draft_id = f"photo_{int(time.time()*1000)}"
        drafts[draft_id] = {
            "type": "photo",
            "bytes_with_logo": processed_bytes,
            "bytes_clean": bytes(raw_bytes),
            "bytes": processed_bytes,
            "caption": formatted_caption
        }

        keyboard = [
            [
                InlineKeyboardButton("🏷️ نشر مع الشعار", callback_data=f"pub_logo_{draft_id}"),
                InlineKeyboardButton("🖼️ نشر بدون شعار", callback_data=f"pub_nologo_{draft_id}")
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]
        ]

        await update.message.reply_photo(
            photo=io.BytesIO(processed_bytes),
            caption=f"🖼️ **تم تجهيز الصورة!**\n\n{formatted_caption}\n\nاختر طريقة النشر:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        try: await status_msg.delete()
        except Exception: pass
    except Exception as e:
        await update.message.reply_text("⚠️ تعذر تحميل الصورة، يرجى المحاولة مجدداً.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    video = update.message.video
    if video.file_size and video.file_size > 20 * 1024 * 1024:
        size_mb = round(video.file_size / (1024 * 1024), 1)
        await update.message.reply_text(f"⚠️ حجم الفيديو ({size_mb}MB) يتجاوز الحد المسموح عبر تيليجرام (20MB).")
        return

    status_msg = await update.message.reply_text("📹 جاري تحميل ومعالجة الفيديو لختم الشعار...")

    try:
        caption = update.message.caption or "الحرية للمختطفين والمخفيين قسراً.. نداء مستمر لإنهاء معاناتهم."
        formatted_caption = format_news(caption)

        file = await video.get_file(read_timeout=90.0)
        raw_video = await file.download_as_bytearray(read_timeout=90.0)
        processed_video = apply_video_watermark(bytes(raw_video))

        draft_id = f"video_{int(time.time()*1000)}"
        drafts[draft_id] = {
            "type": "video",
            "bytes_with_logo": processed_video,
            "bytes_clean": bytes(raw_video),
            "bytes": processed_video,
            "caption": formatted_caption,
            "file_name": video.file_name or "video.mp4"
        }

        keyboard = [
            [
                InlineKeyboardButton("🏷️ نشر مع الشعار", callback_data=f"pub_logo_{draft_id}"),
                InlineKeyboardButton("🎬 نشر بدون شعار (الأصلي)", callback_data=f"pub_nologo_{draft_id}")
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]
        ]

        try:
            await update.message.reply_video(
                video=io.BytesIO(processed_video),
                caption=f"🎬 **معاينة الفيديو!**\n\n{formatted_caption}\n\nاختر طريقة النشر:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                supports_streaming=True
            )
        except Exception:
            await update.message.reply_text(f"🎬 **تمت معالجة الفيديو!**\n\n{formatted_caption}\n\nاختر طريقة النشر:", reply_markup=InlineKeyboardMarkup(keyboard))
        try: await status_msg.delete()
        except Exception: pass
    except Exception as e:
        await update.message.reply_text("⚠️ تعذر تنزيل الفيديو، يرجى المحاولة بمقطع أقصر.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    if not is_authorized(user_id):
        return

    if data.startswith("cancel_"):
        draft_id = data.replace("cancel_", "")
        drafts.pop(draft_id, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ تم الإلغاء.")
        return

    style_matched = None
    if data.startswith("style_advocacy_"):
        style_matched = ("advocacy", data.replace("style_advocacy_", ""))
    elif data.startswith("style_news_"):
        style_matched = ("news", data.replace("style_news_", ""))
    elif data.startswith("style_urgent_"):
        style_matched = ("urgent", data.replace("style_urgent_", ""))

    if style_matched:
        style_type, draft_id = style_matched
        draft = drafts.get(draft_id)
        if not draft:
            await query.message.reply_text("⚠️ انتهت صلاحية المسودة.")
            return

        raw_text = draft.get("raw", draft.get("content", ""))
        caption_text = draft.get("content", format_news(raw_text))

        if style_type == "advocacy":
            card_bytes = generate_advocacy_poster(raw_text)
            style_name = "بوستر حقوقي"
        elif style_type == "urgent":
            card_bytes = generate_urgent_card(raw_text)
            style_name = "نداء عاجل"
        else:
            card_bytes = generate_news_card(raw_text)
            style_name = "كرت إخباري"

        draft["type"] = "photo"
        draft["bytes"] = card_bytes
        draft["caption"] = caption_text

        keyboard = [
            [InlineKeyboardButton("✅ تأكيد النشر على فيسبوك", callback_data=f"publish_{draft_id}")],
            [
                InlineKeyboardButton("🎨 بوستر حقوقي", callback_data=f"style_advocacy_{draft_id}"),
                InlineKeyboardButton("📰 كرت إخباري", callback_data=f"style_news_{draft_id}"),
                InlineKeyboardButton("🚨 نداء عاجل", callback_data=f"style_urgent_{draft_id}")
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{draft_id}")]
        ]

        await query.message.reply_photo(photo=io.BytesIO(card_bytes), caption=f"🖼️ **تم تجهيز ({style_name}) مع الشعار!**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("publish_") or data.startswith("pub_logo_") or data.startswith("pub_nologo_"):
        use_logo = not data.startswith("pub_nologo_")
        draft_id = data.replace("publish_", "").replace("pub_logo_", "").replace("pub_nologo_", "")
        draft = drafts.get(draft_id)
        if not draft:
            await query.message.reply_text("⚠️ انتهت صلاحية المسودة.")
            return

        await query.edit_message_reply_markup(reply_markup=None)
        label = "مع الشعار" if use_logo else "بدون شعار"
        await query.message.reply_text(f"⏳ جاري النشر على صفحة فيسبوك ({label})...")

        try:
            if draft["type"] == "text":
                url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/feed"
                payload = {"message": draft["content"], "access_token": FACEBOOK_PAGE_TOKEN}
                res = requests.post(url, data=payload, timeout=20)
                res_data = res.json()
            elif draft["type"] == "photo":
                photo_bytes = draft.get("bytes_with_logo" if use_logo else "bytes_clean", draft.get("bytes"))
                url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/photos"
                files = {"source": ("image.jpg", io.BytesIO(photo_bytes), "image/jpeg")}
                data_payload = {"caption": draft["caption"], "access_token": FACEBOOK_PAGE_TOKEN}
                res = requests.post(url, files=files, data=data_payload, timeout=35)
                res_data = res.json()
            elif draft["type"] == "video":
                video_bytes = draft.get("bytes_with_logo" if use_logo else "bytes_clean", draft.get("bytes"))
                url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
                files = {"source": (draft.get("file_name", "video.mp4"), io.BytesIO(video_bytes), "video/mp4")}
                data_payload = {"description": draft["caption"], "access_token": FACEBOOK_PAGE_TOKEN}
                res = requests.post(url, files=files, data=data_payload, timeout=60)
                res_data = res.json()

            if "id" in res_data:
                post_id = res_data.get("post_id", res_data.get("id"))
                clean_id = post_id.split("_")[-1] if "_" in post_id else post_id
                post_url = f"https://www.facebook.com/{FACEBOOK_PAGE_ID}/posts/{clean_id}"
                success_msg = f"🎉 **تم النشر بنجاح على فيسبوك!**\n\n🔗 [اضغط لمشاهدة المنشور]({post_url})"
                await query.message.reply_text(success_msg, parse_mode="Markdown")
            else:
                error_msg = res_data.get("error", {}).get("message", str(res_data))
                await query.message.reply_text(f"❌ خطأ من فيسبوك: `{error_msg}`")

        except Exception as e:
            await query.message.reply_text(f"❌ خطأ أثناء الاتصال: {e}")
        finally:
            drafts.pop(draft_id, None)

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"Global error: {context.error}")

async def run_render_app():
    from aiohttp import web

    if not TELEGRAM_BOT_TOKEN or not FACEBOOK_PAGE_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or FACEBOOK_PAGE_TOKEN environment variables!")

    t_req = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=30.0
    )
    ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(t_req).build()

    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("news", news_command))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    ptb_app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    ptb_app.add_handler(CallbackQueryHandler(handle_callback))
    ptb_app.add_error_handler(global_error_handler)

    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    port = int(os.environ.get("PORT", "10000"))

    async def health(request):
        return web.Response(text="Mansiyoon Bot is Alive on Render!")

    async def webhook(request):
        try:
            data = await request.json()
            update = Update.de_json(data, ptb_app.bot)
            await ptb_app.update_queue.put(update)
        except Exception as e:
            logging.error(f"Webhook error: {e}")
        return web.Response(text="OK")

    await ptb_app.initialize()
    await ptb_app.start()

    if render_url:
        webhook_url = f"{render_url}/webhook"
        await ptb_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("RENDER_EXTERNAL_URL not set; running polling fallback...")
        await ptb_app.updater.start_polling(poll_interval=0.5, timeout=10, drop_pending_updates=True)

    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)
    web_app.router.add_post("/webhook", webhook)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Server listening on 0.0.0.0:{port}")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()
        await ptb_app.stop()
        await ptb_app.shutdown()

if __name__ == "__main__":
    asyncio.run(run_render_app())
