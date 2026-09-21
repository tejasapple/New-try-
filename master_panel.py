import os
import asyncio
import logging
import traceback
from typing import Dict, Any
from datetime import timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# Import database functions
from database import (
    db, 
    init_system, 
    is_global_admin, 
    get_bot_setting, 
    set_bot_setting,
    get_next_sequence_value,
    now_iso,
    now_utc
)

load_dotenv()

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")
IST = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ADMIN_STATES: Dict[int, Dict[str, Any]] = {}

def fmt_ist(iso_string: str) -> str:
    if not iso_string: return "Unknown"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso_string)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).strftime("%d-%m-%Y %I:%M %p")
    except:
        return "Unknown"

# ==========================================
# UI BUILDERS
# ==========================================
async def build_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Builds the main dashboard showing all 5 bot slots and centralized features."""
    rows = []
    for i in range(1, 6):
        bot_id = f"bot_{i}"
        status = await get_bot_setting(bot_id, "status", "stopped")
        name = await get_bot_setting(bot_id, "bot_name", f"Bot {i}")
        
        status_icon = "🟢" if status == "active" else "🔴"
        rows.append([InlineKeyboardButton(f"{status_icon} Manage {name}", callback_data=f"manage_{bot_id}")])
    
    # New Centralized Enterprise Features
    rows.append([
        InlineKeyboardButton("⏳ Pending Payments", callback_data="view_pending"),
        InlineKeyboardButton("🔗 Generate 1-Time Link", callback_data="menu_gen_link")
    ])
    rows.append([InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_dash")])
    return InlineKeyboardMarkup(rows)

async def build_bot_menu(bot_id: str) -> InlineKeyboardMarkup:
    """Builds the control menu for a specific slave bot."""
    status = await get_bot_setting(bot_id, "status", "stopped")
    toggle_text = "🔴 Stop Bot" if status == "active" else "🟢 Start Bot"
    toggle_action = "stop" if status == "active" else "start"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Set/Change Bot Token", callback_data=f"set_token_{bot_id}")],
        [InlineKeyboardButton("💳 Set UPI & Payment Settings", callback_data=f"set_pay_{bot_id}")],
        [InlineKeyboardButton("🎨 UI & Layout Settings", callback_data=f"set_ui_{bot_id}")],
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_{bot_id}_{toggle_action}")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_dash")]
    ])

# ==========================================
# COMMAND HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for the Master Panel."""
    user_id = update.effective_user.id
    
    if not await is_global_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized access. This is a private Master Panel.")
        return

    ADMIN_STATES.pop(user_id, None)

    welcome_text = """
<blockquote>👑 <b>ENTERPRISE MASTER PANEL</b></blockquote>

Welcome to the central control system. 
Manage all slave bots, approve global payments, and generate secure access links.
    """
    await update.message.reply_text(
        text=welcome_text.strip(),
        parse_mode=ParseMode.HTML,
        reply_markup=await build_dashboard_keyboard()
    )

# ==========================================
# CALLBACK HANDLERS (BUTTON CLICKS)
# ==========================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not await is_global_admin(user_id):
        await query.answer("Unauthorized.", show_alert=True)
        return

    try: await query.answer()
    except Exception: pass

    if not data.startswith("set_"):
        ADMIN_STATES.pop(user_id, None)

    # 1. Dashboard Navigation
    if data == "refresh_dash" or data == "back_dash":
        text = "<blockquote>👑 <b>ENTERPRISE MASTER PANEL</b></blockquote>\n\nManage all slave bots, approve global payments, and generate secure access links:"
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=await build_dashboard_keyboard())
        return

    # 2. Bot Management UI
    if data.startswith("manage_"):
        bot_id = data.split("_", 1)[1]
        name = await get_bot_setting(bot_id, "bot_name", bot_id)
        token = await get_bot_setting(bot_id, "bot_token", "")
        status = await get_bot_setting(bot_id, "status", "stopped")
        
        token_display = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else "Not Set"
        status_disp = "🟢 Active (Running)" if status == "active" else "🔴 Stopped / Inactive"

        text = f"<blockquote>🤖 <b>MANAGE: {name.upper()}</b></blockquote>\n\n<b>Slot ID:</b> <code>{bot_id}</code>\n<b>Token:</b> <code>{token_display}</code>\n<b>Status:</b> {status_disp}\n\nConfigure this bot independently below."
        await query.edit_message_text(text=text.strip(), parse_mode=ParseMode.HTML, reply_markup=await build_bot_menu(bot_id))
        return

    if data.startswith("set_token_"):
        bot_id = data.replace("set_token_", "")
        ADMIN_STATES[user_id] = {"state": "waiting_for_token", "bot_id": bot_id}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"manage_{bot_id}")]])
        await query.edit_message_text(text=f"🔑 <b>Send the new Telegram Bot Token for {bot_id}.</b>", parse_mode=ParseMode.HTML, reply_markup=kb)
        return
        
    if data.startswith("toggle_"):
        parts = data.split("_")
        action = parts[-1]
        bot_id = "_".join(parts[1:-1])
        new_status = "active" if action == "start" else "stopped"
        await set_bot_setting(bot_id, "status", new_status)
        await query.edit_message_text(text=f"✅ Status updated to <code>{new_status}</code>.", parse_mode=ParseMode.HTML, reply_markup=await build_bot_menu(bot_id))
        return

    # ==========================================
    # CENTRALIZED PAYMENT APPROVAL SYSTEM
    # ==========================================
    if data == "view_pending":
        p = await db.payments.find_one({"status": "pending"})
        if not p:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="back_dash")]])
            await query.edit_message_text("✅ No pending payments found across all bots.", reply_markup=kb)
            return

        bot_id = p["bot_id"]
        plan = await db.plans.find_one({"id": p["plan_id"]})
        cat = await db.categories.find_one({"id": p["category_id"]})
        
        p_name = plan["button_name"] if plan else "Unknown Plan"
        c_name = cat["name"] if cat else "Unknown Category"
        
        text = f"""
<blockquote>⏳ <b>PENDING REVIEW QUEUE</b></blockquote>

<b>Bot Slot:</b> <code>{bot_id}</code>
<b>Payment ID:</b> <code>{p['id']}</code>
<b>User ID:</b> <code>{p['user_id']}</code>
<b>Amount:</b> ₹{p.get('amount', 0)}
<b>Method:</b> {p.get('method', 'UPI')}
<b>Category:</b> {c_name}
<b>Plan:</b> {p_name}
<b>TRX Note:</b> <code>{p.get('trx_id', 'None')}</code>
<b>Time:</b> <code>{fmt_ist(p['created_at'])}</code>

<i>Note: Telegram prevents viewing media files uploaded to other bots directly. Verify the exact amount in your Bank/Crypto Wallet using the TRX Note.</i>
"""
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ VERIFY & SEND LINK", callback_data=f"verify_pay_{p['id']}_{bot_id}")],
            [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_pay_{p['id']}_{bot_id}")],
            [InlineKeyboardButton("⏭️ Skip for Now", callback_data="back_dash")]
        ])
        await query.edit_message_text(text=text.strip(), parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("verify_pay_"):
        _, _, p_id, bot_id = data.split("_")
        p_id = int(p_id)
        
        p = await db.payments.find_one({"id": p_id, "bot_id": bot_id})
        if not p or p["status"] == "verified":
            await query.answer("Payment not found or already verified.", show_alert=True)
            return
            
        plan = await db.plans.find_one({"id": p["plan_id"]})
        cat = await db.categories.find_one({"id": p["category_id"]})
        
        if not cat or "channel_id" not in cat:
            await query.answer("Channel ID not configured for this category!", show_alert=True)
            return

        channel_id = int(cat["channel_id"])
        duration = int(plan["duration_days"]) if plan else 30
        starts = now_utc()
        expires = starts + timedelta(days=duration)

        try:
            # Create 1-time link using Master Bot
            invite = await context.bot.create_chat_invite_link(chat_id=channel_id, member_limit=1, name=f"User {p['user_id']}")
            invite_link = invite.invite_link
            
            # Save Purchase
            purchase_id = await get_next_sequence_value(bot_id, "purchase_id")
            await db.purchases.insert_one({
                "id": purchase_id, "bot_id": bot_id, "user_id": p["user_id"],
                "category_id": p["category_id"], "plan_id": p["plan_id"],
                "channel_id": channel_id, "invite_link": invite_link,
                "starts_at": starts.isoformat(), "expires_at": expires.isoformat(),
                "status": "active", "payment_id": p_id, "created_at": now_iso()
            })

            # Update DB
            await db.payments.update_one({"id": p_id, "bot_id": bot_id}, {"$set": {"status": "verified", "verified_at": now_iso()}})
            await db.users.update_one({"bot_id": bot_id, "user_id": p["user_id"]}, {"$set": {"is_buyer": 1}})

            # Send Success Message via Specific Slave Bot Token
            slave_token = await get_bot_setting(bot_id, "bot_token", "")
            if slave_token:
                slave_bot = Bot(token=slave_token)
                msg = f"<blockquote>✅ PAYMENT VERIFIED</blockquote>\n\n<b>Category:</b> {cat['name']}\n<b>Valid Until:</b> <code>{fmt_ist(expires.isoformat())}</code>\n\n<b>Your Unique VIP Link (1-Time Use):</b>\n{invite_link}"
                await slave_bot.send_message(chat_id=p["user_id"], text=msg, parse_mode=ParseMode.HTML)

            await query.answer("✅ Payment Verified & Link Sent!", show_alert=True)
            
            # Load next pending
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Load Next Pending", callback_data="view_pending")], [InlineKeyboardButton("🔙 Dashboard", callback_data="back_dash")]])
            await query.edit_message_text(f"✅ Payment #{p_id} Approved Successfully.", reply_markup=kb)

        except Exception as e:
            logger.error(f"Verification Error: {e}")
            await query.answer(f"Failed: {e}. Is Master Bot admin in channel {channel_id}?", show_alert=True)
            traceback.print_exc()
        return

    if data.startswith("reject_pay_"):
        _, _, p_id, bot_id = data.split("_")
        p_id = int(p_id)
        p = await db.payments.find_one({"id": p_id, "bot_id": bot_id})
        
        if p:
            await db.payments.update_one({"id": p_id, "bot_id": bot_id}, {"$set": {"status": "rejected"}})
            slave_token = await get_bot_setting(bot_id, "bot_token", "")
            if slave_token:
                try:
                    slave_bot = Bot(token=slave_token)
                    await slave_bot.send_message(chat_id=p["user_id"], text="<blockquote>❌ Payment Rejected</blockquote>\n\nWe could not verify your exact payment amount. Please contact support.", parse_mode=ParseMode.HTML)
                except: pass

        await query.answer("Payment Rejected.")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Load Next Pending", callback_data="view_pending")], [InlineKeyboardButton("🔙 Dashboard", callback_data="back_dash")]])
        await query.edit_message_text(f"❌ Payment #{p_id} Rejected.", reply_markup=kb)
        return

    # ==========================================
    # MANUAL 1-TIME LINK GENERATOR
    # ==========================================
    if data == "menu_gen_link":
        rows = []
        for i in range(1, 6):
            bot_id = f"bot_{i}"
            name = await get_bot_setting(bot_id, "bot_name", f"Bot {i}")
            rows.append([InlineKeyboardButton(f"📁 Channels in {name}", callback_data=f"gen_link_bot_{bot_id}")])
        rows.append([InlineKeyboardButton("🔙 Dashboard", callback_data="back_dash")])
        await query.edit_message_text("<blockquote>🔗 <b>MANUAL LINK GENERATOR</b></blockquote>\n\nSelect a Bot Database to view its configured categories:", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("gen_link_bot_"):
        bot_id = data.replace("gen_link_bot_", "")
        cats = await db.categories.find({"is_active": 1}).to_list(length=None)
        
        if not cats:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_gen_link")]])
            await query.edit_message_text("No active categories found in database.", reply_markup=kb)
            return

        rows = []
        for c in cats:
            rows.append([InlineKeyboardButton(f"🔗 Generate: {c['name']}", callback_data=f"gen_link_cat_{c['id']}")])
        rows.append([InlineKeyboardButton("🔙 Back to Bot List", callback_data="menu_gen_link")])
        
        await query.edit_message_text("Select a Category to instantly generate a 1-Time Join Link:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("gen_link_cat_"):
        cat_id = int(data.replace("gen_link_cat_", ""))
        cat = await db.categories.find_one({"id": cat_id})
        
        if not cat or "channel_id" not in cat:
            await query.answer("Channel ID not configured!", show_alert=True)
            return

        channel_id = int(cat["channel_id"])
        try:
            invite = await context.bot.create_chat_invite_link(chat_id=channel_id, member_limit=1, name="Manual Master Link")
            text = f"""
<blockquote>✅ <b>1-TIME LINK GENERATED</b></blockquote>

<b>Category:</b> {cat['name']}
<b>Target Channel ID:</b> <code>{channel_id}</code>

<b>Unique Link:</b>
{invite.invite_link}

<i>Note: This link will automatically expire after 1 person joins.</i>
"""
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Generate Another", callback_data="menu_gen_link")], [InlineKeyboardButton("🏠 Dashboard", callback_data="back_dash")]])
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            logger.error(f"Link Gen Error: {e}")
            await query.answer(f"Error! Make sure Master Bot is Admin in {channel_id}", show_alert=True)
        return

# ==========================================
# MESSAGE HANDLERS (ADMIN INPUTS)
# ==========================================
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not await is_global_admin(user_id): return

    state_data = ADMIN_STATES.get(user_id)
    if not state_data: return

    text = update.message.text.strip()
    bot_id = state_data["bot_id"]
    state = state_data["state"]

    try:
        if state == "waiting_for_token":
            if ":" not in text or len(text) < 40:
                await update.message.reply_text("❌ Invalid token format.")
                return
                
            await set_bot_setting(bot_id, "bot_token", text)
            ADMIN_STATES.pop(user_id, None)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data=f"manage_{bot_id}")]])
            await update.message.reply_text(f"✅ <b>Token Updated Successfully for {bot_id}!</b>", parse_mode=ParseMode.HTML, reply_markup=kb)
            
    except Exception as e:
        logger.error(f"Error handling admin text: {e}")
        await update.message.reply_text("❌ An error occurred while saving the data.")

# ==========================================
# MAIN INITIALIZATION
# ==========================================
async def post_init(application: Application) -> None:
    await init_system()
    logger.info("Master Panel Booted Successfully.")

def main() -> None:
    if not MASTER_BOT_TOKEN:
        logger.error("MASTER_BOT_TOKEN is missing in .env file.")
        return

    app = Application.builder().token(MASTER_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))

    logger.info("Starting Enterprise Master Panel...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
