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

# Shared Database Logic[span_0](start_span)[span_0](end_span)
from database import db, get_bot_setting, get_next_sequence_value, now_iso

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded for this specific bot UI file
BOT_ID = "bot_4" 

# Screenshot State Manager[span_1](start_span)[span_1](end_span)
USER_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# BUTTON COLOR STYLING ENGINE
# ==========================================
def normalize_style(value: str) -> str:
    """Normalizes color string for Telegram inline buttons."""
    value = (value or "").strip().lower()
    if value in {"success", "green", "paid"}: return "success"
    if value in {"danger", "red", "cancel"}: return "danger"
    if value in {"default", "gray", "back"}: return "default"
    return "primary"

def btn(text: str, data: Optional[str] = None, url: Optional[str] = None, style: str = "primary") -> InlineKeyboardButton:
    """Creates a colored Inline Button."""
    kwargs = {"api_kwargs": {"style": normalize_style(style)}}
    if url: return InlineKeyboardButton(text=text, url=url, **kwargs)
    return InlineKeyboardButton(text=text, callback_data=data, **kwargs)

# ==========================================
# UI BUILDERS (Premium Dashboard Layout)
# ==========================================
async def build_dashboard_menu() -> InlineKeyboardMarkup:
    """Bot 4 Specific: 2x2 Grid Portal Menu"""
    support_link = await get_bot_setting(BOT_ID, "support_link", "https://t.me/your_support")
    
    return InlineKeyboardMarkup([
        [btn("🛍️ Browse Packages", "browse_packages", style="primary")],
        [btn("🎁 Flash Sale", "flash_sale", style="success"), btn("👤 My Portal", "my_portal", style="default")],
        [btn("🎧 Help Desk", url=support_link, style="default")]
    ])

async def categories_keyboard() -> InlineKeyboardMarkup:
    cats = await db.categories.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(f"📁 {c['name']}", f"cat:{c['id']}", style="primary")] for c in cats]
    rows.append([btn("🏠 Back to Portal", "dash_main", style="back")])
    return InlineKeyboardMarkup(rows)

async def plans_keyboard(category_id: int) -> InlineKeyboardMarkup:
    plans = await db.plans.find({"category_id": category_id, "is_active": 1}).sort("id", 1).to_list(length=None)
    rows = [[btn(f"🛒 {p['button_name']} - ₹{p['price']}", f"invoice:{p['id']}", style="success")] for p in plans]
    rows.append([btn("🔙 Categories", "browse_packages", style="back"), btn("🏠 Portal", "dash_main", style="back")])
    return InlineKeyboardMarkup(rows)

async def flash_sale_keyboard() -> InlineKeyboardMarkup:
    """Pulls all plans directly for quick buying."""
    plans = await db.plans.find({"is_active": 1}).sort("id", 1).limit(5).to_list(length=None)
    rows = [[btn(f"🔥 SALE: {p['button_name']} @ ₹{p['price']}", f"invoice:{p['id']}", style="success")] for p in plans]
    rows.append([btn("🏠 Back to Portal", "dash_main", style="back")])
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
        await update.message.reply_text("⏳ Portal is under maintenance.")
        return

    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "<b>ENTERPRISE PORTAL</b>\n\nWelcome to your dashboard.")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")

    kb = await build_dashboard_menu()

    try:
        if start_media.startswith("http"):
            await context.bot.send_photo(update.message.chat_id, photo=start_media, caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await context.bot.send_message(update.message.chat_id, text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)

# ==========================================
# CALLBACK ROUTER (Dashboard & Checkout)
# ==========================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    
    try: await query.answer()
    except Exception: pass

    # 1. Back to Dashboard
    if data == "dash_main":
        welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "<b>ENTERPRISE PORTAL</b>\n\nWelcome to your dashboard.")
        kb = await build_dashboard_menu()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 2. Browse Packages (Categories)
    if data == "browse_packages":
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "📂 <b>Channel Categories</b>\n\nPlease select a section:")
        kb = await categories_keyboard()
        try:
            if query.message.photo: await query.edit_message_caption(caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else: await query.edit_message_text(text=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception: pass
        return

    # 3. Flash Sale (Direct Plans)
    if data == "flash_sale":
        sale_text = "<blockquote>🎁 <b>FLASH SALE ACTIVE</b></blockquote>\n\nGrab these packages before the timer ends!"
        kb = await flash_sale_keyboard()
        try:
            if query.message.photo: await query.edit_message_caption(caption=sale_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else: await query.edit_message_text(text=sale_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception: pass
        return

    # 4. My Portal (Account Stats)
    if data == "my_portal":
        user = query.from_user
        purchases = await db.purchases.find({"bot_id": BOT_ID, "user_id": user_id, "status": "active"}).to_list(length=None)
        
        status_text = "🟢 Premium VIP" if purchases else "🆓 Free User"
        info = f"<blockquote>👤 <b>ACCOUNT DASHBOARD</b></blockquote>\n\n<b>Client Name:</b> {user.first_name}\n<b>Client ID:</b> <code>{user_id}</code>\n<b>Clearance:</b> {status_text}\n"
        
        if purchases:
            info += "\n<b>📦 Active Licenses:</b>\n"
            for p in purchases:
                info += f"🔹 License (Cat ID {p['category_id']}): ACTIVE\n"
                
        kb = InlineKeyboardMarkup([[btn("🏠 Back to Portal", "dash_main", style="back")]])
        
        try:
            if query.message.photo: await query.edit_message_caption(caption=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
            else: await query.edit_message_text(text=info.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception: pass
        return

    # 5. Show Plans inside Category
    if data.startswith("cat:"):
        cid = int(data.split(":")[1])
        c = await db.categories.find_one({"id": cid})
        if not c: return
        text = f"<blockquote>📂 {c['name']}</blockquote>\n\nSelect a package from this category:"
        
        kb = await plans_keyboard(cid)
        try:
            if query.message.photo: await query.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else: await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception: pass
        return

    # 6. Pre-Payment Invoice (NEW UX)
    if data.startswith("invoice:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        cat = await db.categories.find_one({"id": plan["category_id"]})
        cat_name = cat["name"] if cat else "Unknown"
        
        invoice_text = f"""
🧾 <b>PROFORMA INVOICE</b>
━━━━━━━━━━━━━━━━━━
<b>Item:</b> {plan['button_name']}
<b>Category:</b> {cat_name}
<b>Validity:</b> {plan.get('duration_days', 30)} Days

💰 <b>Total Payable:</b> ₹{plan['price']}
━━━━━━━━━━━━━━━━━━
<i>Please select your preferred payment gateway to generate the billing address.</i>
"""
        kb = InlineKeyboardMarkup([
            [btn("💳 Gateway 1: UPI / QR Code", f"gate_upi:{pid}", style="primary")],
            [btn("🪙 Gateway 2: Crypto (USDT)", f"gate_crypto:{pid}", style="primary")],
            [btn("❌ Cancel Checkout", "dash_main", style="danger")]
        ])
        
        try:
            if query.message.photo: await query.edit_message_caption(caption=invoice_text.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
            else: await query.edit_message_text(text=invoice_text.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception: pass
        return

    # 7. Gateway: UPI
    if data.startswith("gate_upi:"):
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

        upi_id = await get_bot_setting(BOT_ID, "upi_id", "default@upi")
        pay_name = await get_bot_setting(BOT_ID, "payment_name", "Enterprise Payment")
        note = await get_bot_setting(BOT_ID, 'payment_note', "Scan exact amount.")
        
        encoded_name = urllib.parse.quote(pay_name)
        upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={trx_id}"
        dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
        
        text = f"""<blockquote>💳 UPI GATEWAY SECURED</blockquote>

<b>Payable Amount:</b> ₹{amount:.2f}
<b>UPI ID:</b> <code>{upi_id}</code>

<i>{note}</i>"""
        
        kb = InlineKeyboardMarkup([
            [btn("✅ Upload Payment Proof", f"verify_pay:{payment_id}", style="success")],
            [btn("🔙 Back to Invoice", f"invoice:{pid}", style="back")]
        ])
        
        await query.message.delete()
        await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 8. Gateway: Crypto
    if data.startswith("gate_crypto:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        amount = float(plan['price'])
        payment_id = await get_next_sequence_value(BOT_ID, "payment_id")
        trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
        
        await db.payments.insert_one({
            "id": payment_id, "bot_id": BOT_ID, "user_id": user_id,
            "category_id": plan["category_id"], "plan_id": pid,
            "amount": amount, "method": "USDT", "status": 'awaiting_screenshot',
            "trx_id": trx_id, "created_at": now_iso()
        })

        usdt_address = await get_bot_setting(BOT_ID, "usdt_address", "YourUSDTAddressHere")
        usdt_amount = round(amount / 85.0, 2)
        note = await get_bot_setting(BOT_ID, 'payment_note', "Send exact USDT amount via TRC20.")
        
        text = f"""<blockquote>🪙 CRYPTO GATEWAY SECURED</blockquote>

<b>Payable Amount:</b> {usdt_amount} USDT
<b>Network:</b> TRC20
<b>Address:</b>
<code>{usdt_address}</code>

<i>{note}</i>"""
        
        kb = InlineKeyboardMarkup([
            [btn("✅ Upload Payment Proof", f"verify_pay:{payment_id}", style="success")],
            [btn("🔙 Back to Invoice", f"invoice:{pid}", style="back")]
        ])
        
        await query.message.delete()
        await context.bot.send_message(query.message.chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 9. Ask for Screenshot
    if data.startswith("verify_pay:"):
        payment_id = int(data.split(":")[1])
        USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id}
        
        kb = InlineKeyboardMarkup([[btn("❌ Cancel", "dash_main", style="danger")]])
        await query.message.reply_text("📸 <b>AWAITING RECEIPT</b>\n\nPlease upload the screenshot of your transaction here to finalize your purchase.", parse_mode=ParseMode.HTML, reply_markup=kb)
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
        await update.message.reply_text("❌ Invalid file. Please upload an image.")
        return

    payment_id = state["payment_id"]
    await db.payments.update_one({"id": payment_id, "bot_id": BOT_ID}, {"$set": {"screenshot_file_id": file_id, "status": "pending"}})
    USER_STATES.pop(user.id, None)
    
    await update.message.reply_text("<blockquote>✅ Receipt Logged Successfully</blockquote>\n\nYour invoice is now pending verification by our administrators. Your access link will be delivered here automatically.", parse_mode=ParseMode.HTML)

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

    logger.info(f"✅ {BOT_ID.upper()} Premium Portal UI Started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
