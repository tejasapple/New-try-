import random
import urllib.parse
import logging
import traceback
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# Import shared database engine
from database import db, get_bot_setting, get_next_sequence_value, now_iso

logger = logging.getLogger(__name__)

# State management for screenshot uploads (Isolated by bot)
USER_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# KEYBOARD BUILDERS
# ==========================================
def btn(text: str, data: str = None, url: str = None) -> InlineKeyboardButton:
    """Helper method to create inline buttons."""
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)

async def categories_keyboard(bot_id: str) -> InlineKeyboardMarkup:
    """Builds the category list dynamically."""
    cats = await db.categories.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    
    rows = []
    for c in cats:
        rows.append([btn(c["name"], f"cat:{c['id']}")])
        
    rows.append([btn("🔙 Main Menu", "start_back")])
    return InlineKeyboardMarkup(rows)

async def plans_keyboard(bot_id: str, category_id: int) -> InlineKeyboardMarkup:
    """Builds the plans list for a specific category."""
    plans = await db.plans.find({"category_id": category_id, "is_active": 1}).sort("id", 1).to_list(length=None)
    
    rows = []
    for p in plans:
        rows.append([btn(f"{p['button_name']} - ₹{p['price']}", f"plan_prompt:{p['id']}")])
        
    rows.append([btn("🔙 Back to Categories", "buy_menu")])
    return InlineKeyboardMarkup(rows)

# ==========================================
# CALLBACK ROUTER (Inline Button Clicks)
# ==========================================
async def slave_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str) -> None:
    """Handles all inline button clicks for the slave bots."""
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    
    try:
        await query.answer()
    except Exception:
        pass

    try:
        # 1. Back to Main Menu
        if data == "start_back":
            welcome_text = await get_bot_setting(bot_id, "welcome_text", "Welcome back!")
            await query.edit_message_text(welcome_text, parse_mode=ParseMode.HTML)
            return

        # 2. Open Buy Menu (Categories)
        if data == "buy_menu":
            buy_text = await get_bot_setting(bot_id, "buy_text", "🛒 <b>CHOOSE YOUR PREMIUM PACKAGE</b>\n\nSelect a category below:")
            await query.edit_message_text(
                text=buy_text,
                parse_mode=ParseMode.HTML,
                reply_markup=await categories_keyboard(bot_id)
            )
            return

        # 3. View Plans in a Category
        if data.startswith("cat:"):
            cid = int(data.split(":")[1])
            c = await db.categories.find_one({"id": cid})
            if not c:
                await query.edit_message_text("Category not found.")
                return
                
            text = f"<blockquote>{c['name']}</blockquote>\n\nSelect your duration plan below."
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=await plans_keyboard(bot_id, cid))
            return
            
        # 4. Prompt Payment Method
        if data.startswith("plan_prompt:"):
            pid = int(data.split(":")[1])
            plan = await db.plans.find_one({"id": pid})
            cid = plan["category_id"] if plan else 0
            
            kb = InlineKeyboardMarkup([
                [btn("💳 UPI (Auto Verification)", f"pay:{pid}:UPI")],
                [btn("🔙 Back to Plans", f"cat:{cid}")]
            ])
            await query.edit_message_text("<blockquote>💳 Select Payment Method</blockquote>\n\nAll payments are 100% secured.", parse_mode=ParseMode.HTML, reply_markup=kb)
            return

        # 5. Generate Dynamic QR & Payment Details
        if data.startswith("pay:"):
            _, pid, method = data.split(":")
            pid = int(pid)
            
            plan = await db.plans.find_one({"id": pid})
            if not plan:
                await query.edit_message_text("Plan not found.")
                return
                
            amount = float(plan['price'])
            payment_id = await get_next_sequence_value(bot_id, "payment_id")
            trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
            
            # Save pending payment uniquely for THIS bot
            await db.payments.insert_one({
                "id": payment_id,
                "bot_id": bot_id,
                "user_id": user_id,
                "category_id": plan["category_id"],
                "plan_id": pid,
                "amount": amount,
                "method": method,
                "status": 'awaiting_screenshot',
                "trx_id": trx_id,
                "created_at": now_iso()
            })

            # Fetch custom UPI details for THIS specific bot (Anonymity feature)
            upi_id = await get_bot_setting(bot_id, "upi_id", "default@upi")
            pay_name = await get_bot_setting(bot_id, "payment_name", "Enterprise")
            payment_note = await get_bot_setting(bot_id, 'payment_note', "Scan exact amount to get instant access.")
            
            encoded_name = urllib.parse.quote(pay_name)
            encoded_note = urllib.parse.quote(trx_id)
            upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={encoded_note}"
            dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
            
            text = f"""<b>Plan:</b> {plan['button_name']}
<b>Amount:</b> ₹{amount:.2f}
<b>UPI ID:</b> <code>{upi_id}</code>

<blockquote>{payment_note}</blockquote>"""
            
            kb = InlineKeyboardMarkup([
                [btn("✅ I HAVE PAID", f"paid:{payment_id}")],
                [btn("🔙 Cancel", f"cat:{plan['category_id']}")]
            ])
            
            await query.message.delete()
            await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
            
        # 6. Request Screenshot
        if data.startswith("paid:"):
            payment_id = int(data.split(":")[1])
            USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id, "bot_id": bot_id}
            
            kb = InlineKeyboardMarkup([[btn("🔙 Cancel Payment", f"cancel_pay:{payment_id}")]])
            await query.message.reply_text("📸 <b>FINAL STEP: UPLOAD SCREENSHOT</b>\n\nPlease send your clear payment screenshot where the UPI ID and Transaction ID (UTR) are clearly visible.", parse_mode=ParseMode.HTML, reply_markup=kb)
            return
            
        # 7. Cancel Payment
        if data.startswith("cancel_pay:"):
            payment_id = int(data.split(":")[1])
            USER_STATES.pop(user_id, None)
            await db.payments.update_one({"id": payment_id, "bot_id": bot_id}, {"$set": {"status": "cancelled"}})
            await query.message.delete()
            await query.message.reply_text("❌ Payment process cancelled.")
            return

    except Exception as e:
        logger.error(f"[{bot_id}] Callback error: {e}")
        traceback.print_exc()

# ==========================================
# SCREENSHOT HANDLER
# ==========================================
async def handle_user_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str) -> bool:
    """Handles screenshot uploads for payments. Returns True if processed, False otherwise."""
    user = update.effective_user
    state = USER_STATES.get(user.id)
    
    if not state or state.get("state") != "awaiting_payment_screenshot" or state.get("bot_id") != bot_id:
        return False # Let the normal text handler process this if it's not a screenshot state
        
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
        file_id = update.message.document.file_id
        
    if not file_id:
        await update.message.reply_text("❌ Please send a valid screenshot image.")
        return True

    payment_id = state["payment_id"]
    
    # Update DB to pending so Master Admin can see it
    await db.payments.update_one({"id": payment_id, "bot_id": bot_id}, {"$set": {"screenshot_file_id": file_id, "status": "pending"}})
    USER_STATES.pop(user.id, None)
    
    success_text = """
<blockquote>✅ Securely Transmitted to AI Servers</blockquote>

Your transaction receipt has been sent to our automated verification system.
Once confirmed, your premium access will be instantly approved.
"""
    await update.message.reply_text(success_text.strip(), parse_mode=ParseMode.HTML)
    return True
