import sys
import asyncio
import random
import urllib.parse
import logging
import math
from typing import Dict, Any, Optional, List

from telegram import (
    Update, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
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
from database import db, get_bot_setting, get_next_sequence_value, now_iso, now_utc
from zoneinfo import ZoneInfo
import datetime as dt_module

logging.basicConfig(format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded for this specific Premium Flagship Bot
BOT_ID = "bot_5" 
IST = ZoneInfo("Asia/Kolkata")
ITEMS_PER_PAGE = 7

# Screenshot & Conversation State Manager
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

def fmt_ist(iso_string: str) -> str:
    if not iso_string: return "Unknown"
    try:
        dt = dt_module.datetime.fromisoformat(iso_string)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=dt_module.timezone.utc)
        return dt.astimezone(IST).strftime("%d-%m-%Y %I:%M %p")
    except:
        return "Unknown"

# ==========================================
# UI BUILDERS (Reply Keyboard & Pagination)
# ==========================================
async def build_reply_keyboard() -> ReplyKeyboardMarkup:
    """Builds the main persistent reply keyboard for users dynamically reading ON/OFF settings."""
    keys = ["btn_buy", "btn_offers", "btn_sub", "btn_proofs", "btn_leaderboard", "btn_reviews", "btn_faq", "btn_support", "btn_profile"]
    default_texts = ["🛍️ Buy Packages", "🎁 Special Sale", "💎 My Subscription", "📸 Proofs", "🏆 Leaderboard", "🌟 Reviews", "❓ FAQ & Refund", "📞 Support", "👤 My Profile"]

    btns = []
    for k, default in zip(keys, default_texts):
        # Fetch individual toggle settings via Master DB logic
        if await get_bot_setting(BOT_ID, f"show_{k}", "1") == "1":
            btns.append(KeyboardButton(await get_bot_setting(BOT_ID, k, default)))

    keyboard = [btns[i:i+2] for i in range(0, len(btns), 2)]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def categories_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    """Builds a paginated inline keyboard for main categories."""
    cats = await db.categories.find({"is_active": 1}).sort("id", 1).to_list(length=None)
    
    total_pages = max(1, math.ceil(len(cats) / ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_cats = cats[start_idx:end_idx]
    
    rows = [[btn(c["name"], f"cat:{c['id']}", style=c.get("button_color", "primary"))] for c in current_cats]
    
    nav_buttons = []
    if page > 0: nav_buttons.append(btn("⬅️ Prev", f"cat_page:{page-1}", style="default"))
    if page < total_pages - 1: nav_buttons.append(btn("Next ➡️", f"cat_page:{page+1}", style="default"))
    if nav_buttons: rows.append(nav_buttons)
        
    rows.append([btn("❌ Close Menu", "close_msg", style="danger")]) 
    return InlineKeyboardMarkup(rows)

async def plans_keyboard(category_id: int, page: int = 0) -> InlineKeyboardMarkup:
    """Builds a paginated inline keyboard for plans within a category."""
    plans = await db.plans.find({"category_id": category_id, "is_active": 1}).sort("id", 1).to_list(length=None)
    total_pages = max(1, math.ceil(len(plans) / ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_plans = plans[start_idx:end_idx]
    
    rows = []
    for p in current_plans:
        price_display = p.get('offer_price', p['price']) if p.get('is_offer_active') else p['price']
        rows.append([btn(f"{p['button_name']} - ₹{price_display}", f"plan_prompt:{p['id']}", style=p.get("button_style", "success"))])
        
    nav_buttons = []
    if page > 0: nav_buttons.append(btn("⬅️ Prev", f"plan_page:{category_id}:{page-1}", style="default"))
    if page < total_pages - 1: nav_buttons.append(btn("Next ➡️", f"plan_page:{category_id}:{page+1}", style="default"))
    if nav_buttons: rows.append(nav_buttons)
        
    rows.append([btn("🔙 Back to Categories", "buy_menu", style="default")])
    return InlineKeyboardMarkup(rows)

# ==========================================
# RICH FEATURES IMPLEMENTATION
# ==========================================
async def send_random_review(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    indian_names = ["Rahul", "Amit", "Suresh", "Vikram", "Rohan", "Karan", "Ajay", "Raj", "Sameer", "Aditya", "Rishabh"]
    foreign_names = ["John", "Michael", "David", "Chris", "James", "Robert", "Daniel", "William", "Alex"]
    
    ind_reviews = [
        "Bhai trust nahi tha pehle, par payment ke 2 minute baad link auto verify ho gaya. Genuine hai.",
        "Price thoda high hai market se, par yaha scam nhi hota. Instant access mila.",
        "Premium quality real hai. 100% working.",
        "Life time wala plan sabse best hai, 1 baar lo aur tension khatam."
    ]
    for_reviews = [
        "A bit pricey, but the verification is actually instant and flawless.",
        "Was hesitant at first because of scams, but it works perfectly.",
        "100% legit. Just pay the exact amount and the bot does the rest.",
        "Crypto payment worked instantly. Good job on the automated setup."
    ]
    
    plans = ["LIFETIME VIP", "30 DAYS PREMIUM", "VIP ACCESS"]
    text = "<blockquote>🌟 Recent Verified Customer Reviews</blockquote>\n\n"
    
    for _ in range(3):
        is_indian = random.random() < 0.6
        if is_indian:
            name = random.choice(indian_names) + " " + random.choice(["***", "**", "M."])
            review_text = random.choice(ind_reviews)
        else:
            name = random.choice(foreign_names) + " " + random.choice(["***", "**", "A."])
            review_text = random.choice(for_reviews)
            
        plan_name = random.choice(plans)
        stars = random.choice(["⭐⭐⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐½"])
        text += f"👤 <b>{name}</b> (Bought: <i>{plan_name}</i>)\n💬 <i>\"{review_text}\"</i>\nRating: {stars}\n───────────────\n"

    text += "✅ <i>100% Verified Premium Buyers via AI System</i>"
    kb = InlineKeyboardMarkup([[btn("🔄 Load More Reviews", "next_review", style="primary")], [btn("❌ Close", "close_msg", style="danger")]])
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_active_subscription(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    purchases = await db.purchases.find({"bot_id": BOT_ID, "user_id": user_id, "status": "active", "expires_at": {"$gt": now_iso()}}).to_list(length=None)
    if not purchases:
        await context.bot.send_message(chat_id, "<blockquote>No Active Subscription</blockquote>\n\nYou do not have active access right now. Check our premium plans.", parse_mode=ParseMode.HTML)
        return
        
    parts = ["<blockquote>💎 My Subscription</blockquote>"]
    rows = []
    for p in purchases:
        plan = await db.plans.find_one({"id": p["plan_id"]})
        cat = await db.categories.find_one({"id": p["category_id"]})
        p_name = plan["button_name"] if plan else "Plan"
        c_name = cat["name"] if cat else "Category"
        
        parts.append(f"<b>Category:</b> {c_name}\n<b>Plan:</b> {p_name}\n<b>Valid Until:</b> <code>{fmt_ist(p.get('expires_at'))}</code>\n<b>Status:</b> <code>{p.get('status')}</code>")
        if p.get("invite_link"):
            rows.append([btn(f"🔗 JOIN {c_name}", url=p.get("invite_link"), style="success")])
            
    rows.append([btn("🔄 REFRESH", "active_sub", style="primary"), btn("❌ Close", "close_msg", style="danger")])
    await context.bot.send_message(chat_id, "\n\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

# ==========================================
# CORE START & REGISTRATION
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start and age verification flow."""
    user = update.effective_user
    
    # 1. Registration
    await db.users.update_one(
        {"bot_id": BOT_ID, "user_id": user.id},
        {"$set": {"username": user.username, "first_name": user.first_name, "last_seen": now_iso()},
         "$setOnInsert": {"is_18_plus": False, "is_buyer": 0}},
        upsert=True
    )
    
    status = await get_bot_setting(BOT_ID, "status", "stopped")
    if status != "active":
        await update.message.reply_text("⏳ Premium System is currently under maintenance.")
        return

    # 2. Age Verification Check
    user_db = await db.users.find_one({"bot_id": BOT_ID, "user_id": user.id})
    if not user_db or not user_db.get("is_18_plus"):
        kb = InlineKeyboardMarkup([
            [btn("✅ Yes, I am 18+", "age_yes", style="success")],
            [btn("❌ No, I am not 18+", "age_no", style="danger")]
        ])
        await update.message.reply_text("🔞 <b>Age Verification Required</b>\n\nAre you 18 years of age or older?", reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    # 3. Send Start Media & Reply Keyboard
    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "<blockquote>🔥 WELCOME TO THE PREMIUM PORTAL</blockquote>\n\nUse the menu below to explore our premium plans.")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "https://picsum.photos/800/400")
    reply_kb = await build_reply_keyboard()

    try:
        if start_media.startswith("http"):
            await context.bot.send_photo(update.message.chat_id, photo=start_media, caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
    except Exception:
        await context.bot.send_message(update.message.chat_id, text=welcome_text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)

# ==========================================
# MESSAGE ROUTER (BOTTOM MENU CLICKS)
# ==========================================
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    chat_id = update.message.chat_id

    # Fetch active button texts dynamically
    btn_buy = await get_bot_setting(BOT_ID, "btn_buy", "🛍️ Buy Packages")
    btn_sub = await get_bot_setting(BOT_ID, "btn_sub", "💎 My Subscription")
    btn_offers = await get_bot_setting(BOT_ID, "btn_offers", "🎁 Special Sale")
    btn_proofs = await get_bot_setting(BOT_ID, "btn_proofs", "📸 Proofs")
    btn_support = await get_bot_setting(BOT_ID, "btn_support", "📞 Support")
    btn_profile = await get_bot_setting(BOT_ID, "btn_profile", "👤 My Profile")
    btn_lead = await get_bot_setting(BOT_ID, "btn_leaderboard", "🏆 Leaderboard")
    btn_reviews = await get_bot_setting(BOT_ID, "btn_reviews", "🌟 Reviews")
    btn_faq = await get_bot_setting(BOT_ID, "btn_faq", "❓ FAQ & Refund")

    # Clear pending states if menu is clicked
    if text in {btn_buy, btn_sub, btn_offers, btn_proofs, btn_support, btn_profile, btn_lead, btn_reviews, btn_faq}:
        USER_STATES.pop(user_id, None)

    state = USER_STATES.get(user_id)
    if state and state.get("state") == "awaiting_ticket_msg":
        # Handle Support Ticket Submission
        await db.tickets.insert_one({"bot_id": BOT_ID, "user_id": user_id, "username": update.effective_user.username, "message": text, "status": "open", "created_at": now_iso()})
        USER_STATES.pop(user_id, None)
        await update.message.reply_text("✅ Your ticket has been submitted to the admins. You will receive a reply here soon.")
        return

    if text == btn_buy:
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "<blockquote>🛒 CHOOSE YOUR PREMIUM PACKAGE</blockquote>")
        buy_photo = await get_bot_setting(BOT_ID, "buy_image", "https://picsum.photos/800/500")
        kb = await categories_keyboard(page=0)
        try:
            await context.bot.send_photo(chat_id, buy_photo, caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except:
            await context.bot.send_message(chat_id, buy_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            
    elif text == btn_sub:
        await show_active_subscription(chat_id, user_id, context)
        
    elif text == btn_offers:
        offer_img = await get_bot_setting(BOT_ID, "offers_image", "https://picsum.photos/800/400")
        offer_text_global = await get_bot_setting(BOT_ID, "offers_text", "Our Latest Exclusive Sale Packages Below!")
        active_offers = await db.plans.find({"is_offer_active": 1, "is_active": 1}).to_list(length=None)
        
        if not active_offers:
            await update.message.reply_text("<blockquote>🎁 Special Sale</blockquote>\n\nCurrently NO active offers. Check back later!", parse_mode=ParseMode.HTML)
            return
            
        rows = [[btn(f"🔥 SALE: {p['button_name']} @ ₹{p['offer_price']}", f"plan_prompt:{p['id']}", style="success")] for p in active_offers]
        rows.append([btn("❌ Close", "close_msg", style="danger")])
        
        caption = f"<blockquote>🎁 Exclusive Special Sale!</blockquote>\n\n{offer_text_global}"
        try:
            await update.message.reply_photo(offer_img, caption=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        except:
            await update.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

    elif text == btn_proofs:
        proofs_link = await get_bot_setting(BOT_ID, "proofs_link", "https://t.me/your_proofs")
        kb = InlineKeyboardMarkup([[btn("✅ Check Proofs", url=proofs_link, style="success")]])
        await update.message.reply_text("Click the button below to view thousands of successful verified payments:", reply_markup=kb)

    elif text == btn_profile:
        user = update.effective_user
        purchases = await db.purchases.find({"bot_id": BOT_ID, "user_id": user.id, "status": "active"}).to_list(length=None)
        status = "💎 Premium VIP" if purchases else "🆓 Free User"
        
        msg = f"<blockquote>👤 My Profile Dashboard</blockquote>\n\n<b>Name:</b> {user.first_name}\n<b>User ID:</b> <code>{user.id}</code>\n<b>Status:</b> {status}\n"
        if purchases:
            msg += "\n<b>📦 Active Plans:</b>\n"
            for p in purchases: msg += f"🔹 Category ID: {p['category_id']}\n"
            
        profile_img = await get_bot_setting(BOT_ID, "profile_image", "https://picsum.photos/800/800")
        try: await update.message.reply_photo(profile_img, caption=msg, parse_mode=ParseMode.HTML)
        except: await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    elif text == btn_lead:
        # Calculate Real Leaderboard
        pipeline = [{"$match": {"bot_id": BOT_ID, "status": "verified"}}, {"$group": {"_id": "$user_id", "amount": {"$sum": "$amount"}}}]
        cursor = db.payments.aggregate(pipeline)
        
        leaderboard = []
        async for doc in cursor:
            u = await db.users.find_one({"bot_id": BOT_ID, "user_id": doc["_id"]})
            name = u.get("first_name", "Unknown") if u else "Unknown"
            leaderboard.append({"name": name, "amount": doc["amount"]})
            
        sorted_lb = sorted(leaderboard, key=lambda x: x["amount"], reverse=True)[:10]
        if not sorted_lb:
            await update.message.reply_text("No buyers yet. Be the first to join the premium leaderboard!")
            return
            
        msg = "<blockquote>🏆 TOP PREMIUM VIP BUYERS</blockquote>\n\n"
        medals = ["👑", "👑", "👑", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹"]
        for i, entry in enumerate(sorted_lb):
            msg += f"{medals[i]} <b>{entry['name']}</b> - ₹{entry['amount']}\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    elif text == btn_support:
        USER_STATES[user_id] = {"state": "awaiting_ticket_msg"}
        kb = InlineKeyboardMarkup([[btn("🔙 Cancel Ticket", "close_msg", style="default")]])
        await update.message.reply_text("<blockquote>🎧 Professional Help Desk</blockquote>\n\nFacing issues? Please type and send your problem here.", parse_mode=ParseMode.HTML, reply_markup=kb)

    elif text == btn_reviews:
        await send_random_review(chat_id, context)

    elif text == btn_faq:
        faq_text = await get_bot_setting(BOT_ID, "faq_text", "FAQ section is currently empty.")
        await update.message.reply_text(faq_text, parse_mode=ParseMode.HTML)

# ==========================================
# CALLBACK ROUTER (INLINE BUTTONS)
# ==========================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    
    try: await query.answer()
    except Exception: pass

    # Age Verification
    if data == "age_yes":
        await db.users.update_one({"bot_id": BOT_ID, "user_id": user_id}, {"$set": {"is_18_plus": True}})
        await query.message.delete()
        await start_command(update, context) # Re-trigger start logic
        return
    if data == "age_no":
        await query.edit_message_text("🚫 You must be 18+ to use this bot.")
        return

    # Delete message
    if data == "close_msg":
        USER_STATES.pop(user_id, None)
        await query.message.delete()
        return

    # Pagination & Navigation
    if data.startswith("cat_page:"):
        page = int(data.split(":")[1])
        await query.edit_message_reply_markup(reply_markup=await categories_keyboard(page))
        return
    if data.startswith("plan_page:"):
        _, cid, page = data.split(":")
        await query.edit_message_reply_markup(reply_markup=await plans_keyboard(int(cid), int(page)))
        return
    if data == "buy_menu":
        buy_text = await get_bot_setting(BOT_ID, "buy_text", "<blockquote>🛒 CHOOSE YOUR PREMIUM PACKAGE</blockquote>")
        try:
            if query.message.photo: await query.edit_message_caption(caption=buy_text, parse_mode=ParseMode.HTML, reply_markup=await categories_keyboard(0))
            else: await query.edit_message_text(text=buy_text, parse_mode=ParseMode.HTML, reply_markup=await categories_keyboard(0))
        except Exception: pass
        return

    # Show Plans in Category
    if data.startswith("cat:"):
        cid = int(data.split(":")[1])
        c = await db.categories.find_one({"id": cid})
        if not c: return
        text = f"<blockquote>{c['name']}</blockquote>\n\nSelect your duration plan below."
        try:
            if query.message.photo: await query.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=await plans_keyboard(cid, 0))
            else: await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=await plans_keyboard(cid, 0))
        except Exception: pass
        return

    # Prompt Payment Methods (UPI / USDT)
    if data.startswith("plan_prompt:"):
        pid = int(data.split(":")[1])
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        kb = InlineKeyboardMarkup([
            [btn("💳 UPI (Auto Verification)", f"pay_gateway:{pid}:UPI", style="success")],
            [btn("🪙 USDT Crypto", f"pay_gateway:{pid}:USDT", style="primary")],
            [btn("🔙 Back to Plans", f"cat:{plan['category_id']}", style="default")]
        ])
        await query.message.delete()
        await context.bot.send_message(query.message.chat_id, "<blockquote>💳 Select Payment Method</blockquote>\n\nAll payments are 100% secured.", parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Generate QR or USDT Address
    if data.startswith("pay_gateway:"):
        _, pid, method = data.split(":")
        pid = int(pid)
        plan = await db.plans.find_one({"id": pid})
        if not plan: return
        
        amount = float(plan.get('offer_price', plan['price'])) if plan.get('is_offer_active') else float(plan['price'])
        payment_id = await get_next_sequence_value(BOT_ID, "payment_id")
        trx_id = f"TRX{payment_id}{random.randint(1000, 9999)}"
        
        await db.payments.insert_one({
            "id": payment_id, "bot_id": BOT_ID, "user_id": user_id,
            "category_id": plan["category_id"], "plan_id": pid,
            "amount": amount, "method": method, "status": 'awaiting_screenshot',
            "trx_id": trx_id, "created_at": now_iso()
        })

        note = await get_bot_setting(BOT_ID, 'payment_note', "Scan exact amount.")
        kb = InlineKeyboardMarkup([
            [btn("✅ I HAVE PAID", f"paid_ss:{payment_id}", style="success")],
            [btn("❌ Cancel", "close_msg", style="danger")]
        ])
        
        await query.message.delete()

        if method == "UPI":
            upi_id = await get_bot_setting(BOT_ID, "upi_id", "default@upi")
            pay_name = await get_bot_setting(BOT_ID, "payment_name", "Premium Access")
            
            encoded_name = urllib.parse.quote(pay_name)
            upi_uri = f"upi://pay?pa={upi_id}&pn={encoded_name}&am={amount:.2f}&cu=INR&tn={trx_id}"
            dynamic_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_uri)}"
            
            text = f"""<b>Plan:</b> {plan['button_name']}\n<b>Amount:</b> ₹{amount:.2f}\n<b>UPI ID:</b> <code>{upi_id}</code>\n\n<blockquote>{note}</blockquote>"""
            await context.bot.send_photo(query.message.chat_id, dynamic_qr, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            usdt_address = await get_bot_setting(BOT_ID, "usdt_address", "USDTAddressHere")
            usdt_amount = round(amount / 85.0, 2)
            text = f"""<b>Plan:</b> {plan['button_name']}\n<b>Amount:</b> {usdt_amount} USDT (TRC20)\n<b>Address:</b>\n<code>{usdt_address}</code>\n\n<blockquote>{note}</blockquote>"""
            await context.bot.send_message(query.message.chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Request Screenshot
    if data.startswith("paid_ss:"):
        payment_id = int(data.split(":")[1])
        USER_STATES[user_id] = {"state": "awaiting_payment_screenshot", "payment_id": payment_id}
        kb = InlineKeyboardMarkup([[btn("🔙 Cancel Process", "close_msg", style="danger")]])
        await query.message.reply_text("📸 <b>FINAL STEP: UPLOAD SCREENSHOT</b>\n\nPlease send your clear payment screenshot where Transaction ID (UTR) is visible.", parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Extra features
    if data == "next_review":
        await send_random_review(query.message.chat_id, context)
        return
    if data == "active_sub":
        await show_active_subscription(query.message.chat_id, user_id, context)
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
        await update.message.reply_text("❌ Please send a valid image screenshot.")
        return

    payment_id = state["payment_id"]
    await db.payments.update_one({"id": payment_id, "bot_id": BOT_ID}, {"$set": {"screenshot_file_id": file_id, "status": "pending"}})
    USER_STATES.pop(user.id, None)
    
    await update.message.reply_text("<blockquote>✅ Securely Transmitted to AI Servers</blockquote>\n\nYour transaction receipt has been sent for automated verification. Access will be approved shortly.", parse_mode=ParseMode.HTML)

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
    # Handle both text (for bottom menu) and photos (for screenshots)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_screenshot))

    logger.info(f"✅ {BOT_ID.upper()} Premium Flagship UI Started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
