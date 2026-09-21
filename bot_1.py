import sys
import asyncio
import random
import urllib.parse
import logging
from typing import Dict, Any

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
BOT_ID = "bot_1" 

# Screenshot State Manager
USER_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# UI BUILDERS (Specific to Bot 1 Design)
# ==========================================
def btn(text: str, data: str = None, url: str = None) -> InlineKeyboardButton:
    if url: return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)

async def build_main_menu() -> InlineKeyboardMarkup:
    """Bot 1 Specific: Inline Main Menu"""
    support_link = await get_bot_setting(BOT_ID, "support_link", "https://t.me/your_username")
    
    return InlineKeyboardMarkup([
        [btn("🛍️ Buy Premium", "buy_menu")],
        [btn("👤 My Membership", "my_membership")],
        [btn("🎧 Support", url=support_link)],
        [btn("❌ Close", "close_msg")]
    ])

async def categories_keyboard() -> InlineKeyboardMarkup:
    cats = await db.categories.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(c["name"], f"cat:{c['id']}")] for c in cats]
    rows.append([btn("🔙 Back to Main Menu", "start_back")])
    return InlineKeyboardMarkup(rows)

async def plans_keyboard(category_id: int) -> InlineKeyboardMarkup:
    plans = await db.plans.find({"category_id": category_id, "is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(f"{p['button_name']} - ₹{p['price']}", f"plan_prompt:{p['id']}")] for p in plans]
    rows.append([btn("🔙 Back to Channels", "buy_menu")])
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

    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome to Premium Services!")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400") # Default Photo

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

    # 1. Close Menu
    if data == "close_msg":
        await query.message.delete()
        return

    # 2. Back to Start Menu
    if data == "start_back":
        welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome to Premium Services!")
        start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")
        kb = await build_main_menu()
        
        try:
            # Check if message has media, if yes edit caption, else edit text
            if query.message.photo or query.message.animation or query.message.video:
                await query.edit_message_caption(caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 3. Buy Premium (Show Channels)
    if data == "buy_menu":
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "🛒 <b>Select a Premium Channel:</b>")
        kb = await categories_keyboard()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 4. My Membership
    if data == "my_membership":
        user = query.from_user
        name = user.first_name
        username = f"@{user.username}" if user.username else "None"
        
        # Check active subscriptions for this user
        purchases = await db.purchases.find({
            "bot_id": BOT_ID, 
            "user_id": user_id, 
            "status": "active"
        }).to_list(length=None)
        
        status_text = "🟢 Active VIP" if purchases else "🔴 Inactive (Free User)"
        
        info = f"""
<blockquote>👤 <b>MY MEMBERSHIP PROFILE</b></blockquote>

<b>Name:</b> {name}
<b>Username:</b> {username}
<b>Telegram ID:</b> <code>{user_id}</code>
<b>Premium Status:</b> {status_text}
"""
        if purchases:
            info += "\n<b>📦 Active Plans:</b>\n"
            for p in purchases:
                info += f"🔹 Channel ID: <code>{p['category_id']}</code> (Active)\n"
                
        kb = InlineKeyboardMarkup([[btn("🔙 Back to Main Menu", "start_back")]])
        
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 5. Show Plans for Channel
    if data.startswith("cat:"):
        cid = int(data.split(":")[1])
        c = await db.categories.find_one({"id": cid})
        if not c: return
        text = f"<blockquote>{c['name']}</blockquote>\n\nSelect a duration plan below:"
        
        kb = await plans_keyboard(cid)
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 6. Show QR Code & Payment Details
    if data.startswith("plan_prompt:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        amount = float(plan['price'])
        payment_id = await get_next_sequence_value(BOT_ID, "payment_id")
        trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
        
        await db.payments.insert_one({
            "id": payment_id, "bot_id": BOT_ID, "user_id": user_id,
            "category_id": plan["category_id"], "plan_id": pid,
            "amount": amount, "method": "UPI", "status": 'awaiting_screenshot',
            "trx_id": trx_id, "created_at": now_iso()
        })

        # Fetch unique UPI for Bot 1
        upi_id = await get_bot_setting(BOT_ID, "upi_id", "default@upi")
        pay_name = await get_bot_setting(BOT_ID, "payment_name", "Enterprise Payment")
        note = await get_bot_setting(BOT_ID, 'payment_note', "Scan exact amount.")
        
        encoded_name = urllib.parse.quote(pay_name)
        upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={trx_id}"
        dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
        
        text = f"""<b>Plan Selected:</b> {plan['button_name']}
<b>Total Amount:</b> ₹{amount:.2f}
<b>UPI ID:</b> <code>{upi_id}</code>

<blockquote>{note}</blockquote>"""
        
        kb = InlineKeyboardMarkup([
            [btn("✅ I HAVE PAID", f"paid:{payment_id}")],
            [btn("🔙 Cancel", f"cat:{plan['category_id']}")]
        ])
        
        await query.message.delete()
        await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 7. Ask for Screenshot
    if data.startswith("paid:"):
        payment_id = int(data.split(":")[1])
        USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id}
        
        kb = InlineKeyboardMarkup([[btn("🔙 Cancel Payment", f"cancel_pay:{payment_id}")]])
        await query.message.reply_text("📸 <b>FINAL STEP: UPLOAD SCREENSHOT</b>\n\nPlease send your clear payment screenshot.", parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 8. Cancel Payment
    if data.startswith("cancel_pay:"):
        payment_id = int(data.split(":")[1])
        USER_STATES.pop(user_id, None)
        await db.payments.update_one({"id": payment_id, "bot_id": BOT_ID}, {"$set": {"status": "cancelled"}})
        await query.message.delete()
        await query.message.reply_text("❌ Payment process cancelled. Send /start to open menu again.")
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
    
    await update.message.reply_text("<blockquote>✅ Sent to Admin for Verification</blockquote>\n\nYour receipt has been securely sent. Once verified, you will receive a 1-Time unique joining link right here.", parse_mode=ParseMode.HTML)

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

    logger.info(f"✅ {BOT_ID.upper()} Custom Inline UI Started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
