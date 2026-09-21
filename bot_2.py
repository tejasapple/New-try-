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
BOT_ID = "bot_2" 

# Screenshot State Manager
USER_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# UI BUILDERS (Specific to Bot 2 Funnel)
# ==========================================
def btn(text: str, data: str = None, url: str = None) -> InlineKeyboardButton:
    if url: return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)

async def build_vip_menu() -> InlineKeyboardMarkup:
    """Bot 2 Specific: Single Entry Button"""
    return InlineKeyboardMarkup([
        [btn("🔓 Unlock VIP Access Now", "vip_access")]
    ])

async def plans_keyboard() -> InlineKeyboardMarkup:
    """Shows all active plans across categories for direct selection."""
    plans = await db.plans.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    rows = []
    for p in plans:
        # Format: Plan Name - Price
        rows.append([btn(f"{p['button_name']} - ₹{p['price']}", f"plan_select:{p['id']}")])
    
    rows.append([btn("🔙 Back", "start_back")])
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

    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome to the Ultimate VIP Club!")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")

    kb = await build_vip_menu()

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

    # 1. Back to Start Menu
    if data == "start_back":
        welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome to the Ultimate VIP Club!")
        start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")
        kb = await build_vip_menu()
        
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 2. Unlock VIP Access (Show Plans)
    if data == "vip_access":
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "💎 <b>CHOOSE YOUR VIP PLAN</b>\n\nSelect a package below to continue:")
        kb = await plans_keyboard()
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await query.edit_message_text(text=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 3. Select Payment Method (UPI / USDT)
    if data.startswith("plan_select:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        text = f"<blockquote>💎 {plan['button_name']}</blockquote>\n\n<b>Price:</b> ₹{plan['price']}\n\nSelect your preferred payment method below:"
        
        kb = InlineKeyboardMarkup([
            [btn("💳 Pay by UPI (PhonePe, GPay)", f"pay_method:{pid}:UPI")],
            [btn("🪙 USDT (Crypto)", f"pay_method:{pid}:USDT")],
            [btn("🔙 Back to Plans", "vip_access")]
        ])
        
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass
        return

    # 4. Show QR Code or USDT Address
    if data.startswith("pay_method:"):
        _, pid, method = data.split(":")
        pid = int(pid)
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        amount = float(plan['price'])
        payment_id = await get_next_sequence_value(BOT_ID, "payment_id")
        trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
        
        await db.payments.insert_one({
            "id": payment_id, "bot_id": BOT_ID, "user_id": user_id,
            "category_id": plan["category_id"], "plan_id": pid,
            "amount": amount, "method": method, "status": 'awaiting_screenshot',
            "trx_id": trx_id, "created_at": now_iso()
        })

        proofs_link = await get_bot_setting(BOT_ID, "proofs_link", "https://t.me/your_proofs")
        note = await get_bot_setting(BOT_ID, 'payment_note', "Scan & pay the exact amount. Then click Check Payment.")
        
        kb = InlineKeyboardMarkup([
            [btn("✅ Check Payment", f"check_pay:{payment_id}")],
            [btn("📸 Payment Proofs", url=proofs_link)],
            [btn("❌ Cancel", "vip_access")]
        ])

        await query.message.delete()

        if method == "UPI":
            upi_id = await get_bot_setting(BOT_ID, "upi_id", "default@upi")
            pay_name = await get_bot_setting(BOT_ID, "payment_name", "VIP Access")
            
            encoded_name = urllib.parse.quote(pay_name)
            upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={trx_id}"
            dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
            
            text = f"""<b>Plan:</b> {plan['button_name']}
<b>Amount to Pay:</b> ₹{amount:.2f}
<b>UPI ID:</b> <code>{upi_id}</code>

<blockquote>{note}</blockquote>"""
            await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            
        else: # USDT Crypto
            usdt_address = await get_bot_setting(BOT_ID, "usdt_address", "TYourUSDTWalletAddressHere")
            usdt_amount = round(amount / 85.0, 2) # Basic INR to USDT conversion estimation
            
            text = f"""<b>Plan:</b> {plan['button_name']}
<b>Amount to Pay:</b> {usdt_amount} USDT (TRC20)
<b>Wallet Address:</b>
<code>{usdt_address}</code>

<blockquote>{note}</blockquote>"""
            # Send text without photo for Crypto
            await context.bot.send_message(query.message.chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # 5. Check Payment (Ask for Screenshot)
    if data.startswith("check_pay:"):
        payment_id = int(data.split(":")[1])
        USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id}
        
        kb = InlineKeyboardMarkup([[btn("❌ Cancel Payment", "vip_access")]])
        await query.message.reply_text("📸 <b>SCREENSHOT REQUIRED</b>\n\nPlease upload the screenshot of your successful transaction here to automatically verify your payment.", parse_mode=ParseMode.HTML, reply_markup=kb)
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
    
    await update.message.reply_text("<blockquote>✅ Payment Verification Started</blockquote>\n\nYour screenshot has been submitted. Our system is verifying the transaction. You will receive the VIP access link here shortly.", parse_mode=ParseMode.HTML)

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

    logger.info(f"✅ {BOT_ID.upper()} Funnel UI Started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
