import sys
import asyncio
import random
import urllib.parse
import logging
from typing import Dict, Any, Optional

from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes, 
    filters
)

# Shared Database Logic
from database import db, get_bot_setting, get_next_sequence_value, now_iso

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded for this specific bot UI file
BOT_ID = "bot_3" 

# Screenshot State Manager
USER_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# BUTTON COLOR STYLING ENGINE
# ==========================================
def normalize_style(value: str) -> str:
    """Normalizes color string for Telegram inline buttons (Blue, Green, Red)."""
    value = (value or "").strip().lower()
    if value in {"success", "green", "paid"}: return "success"  # Green
    if value in {"danger", "red", "delete", "cancel"}: return "danger" # Red
    if value in {"default", "gray", "grey", "back"}: return "default" # Gray
    return "primary" # Blue

def btn(text: str, data: Optional[str] = None, url: Optional[str] = None, style: str = "primary") -> InlineKeyboardButton:
    """Creates a colored Inline Button."""
    kwargs = {"api_kwargs": {"style": normalize_style(style)}}
    if url: return InlineKeyboardButton(text=text, url=url, **kwargs)
    return InlineKeyboardButton(text=text, callback_data=data, **kwargs)

# ==========================================
# UI BUILDERS (Specific to Bot 3 Flow)
# ==========================================
async def build_main_menu() -> InlineKeyboardMarkup:
    """Bot 3 Specific: Colored Main Menu"""
    return InlineKeyboardMarkup([
        [btn("💎 Get Premium", "get_premium", style="success")],
        [btn("👤 My Profile", "my_profile", style="primary")]
    ])

async def channels_keyboard() -> InlineKeyboardMarkup:
    cats = await db.categories.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(c["name"], f"cat:{c['id']}", style="primary")] for c in cats]
    rows.append([btn("🏠 Home", "start_back", style="back")])
    return InlineKeyboardMarkup(rows)

async def plans_keyboard(category_id: int) -> InlineKeyboardMarkup:
    plans = await db.plans.find({"category_id": category_id, "is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(f"{p['button_name']} - ₹{p['price']}", f"plan_prompt:{p['id']}", style="success")] for p in plans]
    rows.append([btn("🔙 Back to Channels", "get_premium", style="back"), btn("🏠 Home", "start_back", style="back")])
    return InlineKeyboardMarkup(rows)

# ==========================================
# CORE HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command"""
    user = update.effective_user
    await db.users.update_one(
        {"bot_id": BOT_ID, "user_id": user.id},
        {"$set": {"username": user.username, "first_name": user.first_name, "last_seen": now_iso()}},
        upsert=True
    )
    
    status = await get_bot_setting(BOT_ID, "status", "stopped")
    if status != "active":
        await update.message.reply_text("⏳ This bot is currently under maintenance.")
        return

    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome! Select an option below:")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")

    kb = await build_main_menu()

    try:
        if start_media.startswith("http"):
            await context.bot.send_photo(update.message.chat_id, photo=start_media, caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await context.bot.send_message(update.message.chat_id, text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)

# ==========================================
# CALLBACK ROUTER (Button Clicks)
# ==========================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    
    try: await query.answer()
    except Exception: pass

    # 1. Home / Back to Start
    if data == "start_back":
        welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome! Select an option below:")
        kb = await build_main_menu()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 2. My Profile (Stats)
    if data == "my_profile":
        user = query.from_user
        purchases = await db.purchases.find({"bot_id": BOT_ID, "user_id": user_id, "status": "active"}).to_list(length=None)
        
        status_text = "🟢 Premium VIP" if purchases else "🆓 Free User"
        info = f"<blockquote>👤 <b>YOUR PROFILE STATS</b></blockquote>\n\n<b>Name:</b> {user.first_name}\n<b>ID:</b> <code>{user_id}</code>\n<b>Status:</b> {status_text}\n"
        
        if purchases:
            info += "\n<b>📦 Active Access:</b>\n"
            for p in purchases:
                info += f"🔹 Category ID: {p['category_id']}\n"
                
        kb = InlineKeyboardMarkup([[btn("🏠 Home", "start_back", style="back")]])
        
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 3. Get Premium (Show Channels)
    if data == "get_premium":
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "🛒 <b>Select a Channel Category:</b>")
        kb = await channels_keyboard()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 4. Show Plans inside Channel
    if data.startswith("cat:"):
        cid = int(data.split(":")[1])
        c = await db.categories.find_one({"id": cid})
        if not c: return
        text = f"<blockquote>{c['name']}</blockquote>\n\nSelect a subscription plan:"
        
        kb = await plans_keyboard(cid)
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 5. Direct QR Code (UPI Default) & Options
    if data.startswith("plan_prompt:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        amount = float(plan['price'])
        payment_id = await get_next_sequence_value(BOT_ID, "payment_id")
        trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
        
        # Create initial payment intent as UPI
        await db.payments.insert_one({
            "id": payment_id, "bot_id": BOT_ID, "user_id": user_id,
            "category_id": plan["category_id"], "plan_id": pid,
            "amount": amount, "method": "UPI", "status": 'awaiting_screenshot',
            "trx_id": trx_id, "created_at": now_iso()
        })

        upi_id = await get_bot_setting(BOT_ID, "upi_id", "default@upi")
        pay_name = await get_bot_setting(BOT_ID, "payment_name", "VIP Gateway")
        note = await get_bot_setting(BOT_ID, 'payment_note', "Scan exact amount.")
        
        encoded_name = urllib.parse.quote(pay_name)
        upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={trx_id}"
        dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
        
        text = f"""<b>Plan:</b> {plan['button_name']}
<b>Amount:</b> ₹{amount:.2f}
<b>UPI ID:</b> <code>{upi_id}</code>

<blockquote>{note}</blockquote>"""
        
        kb = InlineKeyboardMarkup([
            [btn("✅ Check Payment", f"check_pay:{payment_id}", style="success")],
            [btn("🪙 Pay by USDT", f"usdt_pay:{payment_id}:{pid}", style="primary")],
            [btn("🔙 Back", f"cat:{plan['category_id']}", style="back"), btn("🏠 Home", "start_back", style="back")]
        ])
        
        await query.message.delete()
        await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 6. Switch to USDT Payment
    if data.startswith("usdt_pay:"):
        _, payment_id, pid = data.split(":")
        payment_id, pid = int(payment_id), int(pid)
        
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        # Update existing payment intent to USDT
        await db.payments.update_one({"id": payment_id, "bot_id": BOT_ID}, {"$set": {"method": "USDT"}})

        amount = float(plan['price'])
        usdt_address = await get_bot_setting(BOT_ID, "usdt_address", "YourUSDTAddressHere")
        usdt_amount = round(amount / 85.0, 2)
        note = await get_bot_setting(BOT_ID, 'payment_note', "Send exact USDT amount.")
        
        text = f"""<b>Plan:</b> {plan['button_name']}
<b>Amount:</b> {usdt_amount} USDT (TRC20)
<b>Wallet Address:</b>
<code>{usdt_address}</code>

<blockquote>{note}</blockquote>"""
        
        kb = InlineKeyboardMarkup([
            [btn("✅ Check Payment", f"check_pay:{payment_id}", style="success")],
            [btn("🔙 Back to UPI", f"plan_prompt:{pid}", style="back"), btn("🏠 Home", "start_back", style="back")]
        ])
        
        # We delete the QR photo and send just text for Crypto address
        await query.message.delete()
        await context.bot.send_message(query.message.chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 7. Check Payment (Request Screenshot)
    if data.startswith("check_pay:"):
        payment_id = int(data.split(":")[1])
        USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id}
        
        kb = InlineKeyboardMarkup([[btn("❌ Cancel Process", "start_back", style="danger")]])
        await query.message.reply_text("📸 <b>SCREENSHOT REQUIRED</b>\n\nPlease upload the screenshot of your successful transaction here.", parse_mode=ParseMode.HTML, reply_markup=kb)
        return

# ==========================================
# SCREENSHOT HANDLER
# ==========================================
async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    state = USER_STATES.get(user.id)
    
    if not state or state.get("state") != "awaiting_payment_screenshot":
        return 
        
    file_id = None
    if update.message.photo: file_id = update.message.photo[-1].file_id
    elif update.message.document: file_id = update.message.document.file_id
        
    if not file_id:
        await update.message.reply_text("❌ Please send a valid image.")
        return

    payment_id = state["payment_id"]
    await db.payments.update_one({"id": payment_id, "bot_id": BOT_ID}, {"$set": {"screenshot_file_id": file_id, "status": "pending"}})
    USER_STATES.pop(user.id, None)
    
    await update.message.reply_text("<blockquote>✅ Payment in Review</blockquote>\n\nYour screenshot has been submitted and is currently pending admin review. You will receive your access link soon.", parse_mode=ParseMode.HTML)

# ==========================================
# APP LAUNCHER
# ==========================================
def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    token = loop.run_until_complete(get_bot_setting(BOT_ID, "bot_token", ""))

    if not token:
        logger.error(f"🚨 Token for {BOT_ID} not found in DB! Add it via Master Panel.")
        sys.exit(1)

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_screenshot))

    logger.info(f"✅ {BOT_ID.upper()} Custom Colored UI Started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
