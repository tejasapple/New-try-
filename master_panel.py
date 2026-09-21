import os
import asyncio
import logging
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    set_bot_setting
)

load_dotenv()

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================
MASTER_BOT_TOKEN = os.getenv("MASTER_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State management for admin inputs (e.g., waiting for token text)
ADMIN_STATES: Dict[int, Dict[str, Any]] = {}

# ==========================================
# UI BUILDERS
# ==========================================
async def build_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Builds the main dashboard showing all 5 bot slots."""
    rows = []
    for i in range(1, 6):
        bot_id = f"bot_{i}"
        status = await get_bot_setting(bot_id, "status", "stopped")
        name = await get_bot_setting(bot_id, "bot_name", f"Bot {i}")
        
        status_icon = "🟢" if status == "active" else "🔴"
        rows.append([InlineKeyboardButton(f"{status_icon} Manage {name}", callback_data=f"manage_{bot_id}")])
    
    rows.append([InlineKeyboardButton("🔄 Refresh Status", callback_data="refresh_dash")])
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

    # Clear any pending states
    ADMIN_STATES.pop(user_id, None)

    welcome_text = """
<blockquote>👑 <b>ENTERPRISE MASTER PANEL</b></blockquote>

Welcome to the central control system. From here, you can manage all your slave bots, assign tokens, and customize their UIs dynamically without touching the code.

Select a Bot Slot to configure:
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
    """Routes all inline button clicks in the Master Panel."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not await is_global_admin(user_id):
        await query.answer("Unauthorized.", show_alert=True)
        return

    try:
        await query.answer()
    except Exception:
        pass

    # Clear state on navigation
    if not data.startswith("set_"):
        ADMIN_STATES.pop(user_id, None)

    if data == "refresh_dash" or data == "back_dash":
        text = "<blockquote>👑 <b>ENTERPRISE MASTER PANEL</b></blockquote>\n\nSelect a Bot Slot to configure:"
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=await build_dashboard_keyboard()
        )
        return

    if data.startswith("manage_"):
        bot_id = data.split("_", 1)[1]
        name = await get_bot_setting(bot_id, "bot_name", bot_id)
        token = await get_bot_setting(bot_id, "bot_token", "")
        status = await get_bot_setting(bot_id, "status", "stopped")
        
        token_display = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else "Not Set"
        status_disp = "🟢 Active (Running)" if status == "active" else "🔴 Stopped / Inactive"

        text = f"""
<blockquote>🤖 <b>MANAGE: {name.upper()}</b></blockquote>

<b>Slot ID:</b> <code>{bot_id}</code>
<b>Token:</b> <code>{token_display}</code>
<b>Status:</b> {status_disp}

Use the buttons below to configure this bot independently.
        """
        await query.edit_message_text(
            text=text.strip(),
            parse_mode=ParseMode.HTML,
            reply_markup=await build_bot_menu(bot_id)
        )
        return

    if data.startswith("set_token_"):
        bot_id = data.replace("set_token_", "")
        ADMIN_STATES[user_id] = {"state": "waiting_for_token", "bot_id": bot_id}
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"manage_{bot_id}")]])
        await query.edit_message_text(
            text=f"🔑 <b>Send the new Telegram Bot Token for {bot_id}.</b>\n\n(Get this from @BotFather)",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        return
        
    if data.startswith("toggle_"):
        # Format: toggle_bot_1_start or toggle_bot_1_stop
        parts = data.split("_")
        action = parts[-1]
        bot_id = "_".join(parts[1:-1])
        
        new_status = "active" if action == "start" else "stopped"
        await set_bot_setting(bot_id, "status", new_status)
        
        name = await get_bot_setting(bot_id, "bot_name", bot_id)
        await query.edit_message_text(
            text=f"✅ Status for <b>{name}</b> updated to <code>{new_status}</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=await build_bot_menu(bot_id)
        )
        return
        
    # Placeholder for Payment & UI settings (Will be expanded in next steps)
    if data.startswith("set_pay_") or data.startswith("set_ui_"):
        bot_id = data.split("_", 2)[2]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{bot_id}")]])
        await query.edit_message_text(
            text="⚙️ This menu will control MongoDB settings for Payment and UI dynamically. (Coming in next module)",
            reply_markup=kb
        )
        return

# ==========================================
# MESSAGE HANDLERS (ADMIN INPUTS)
# ==========================================
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captures text inputs from the admin based on their current state."""
    user_id = update.effective_user.id
    
    if not await is_global_admin(user_id):
        return

    state_data = ADMIN_STATES.get(user_id)
    if not state_data:
        return # Ignore normal messages if not in a specific state

    text = update.message.text.strip()
    bot_id = state_data["bot_id"]
    state = state_data["state"]

    try:
        if state == "waiting_for_token":
            if ":" not in text or len(text) < 40:
                await update.message.reply_text("❌ Invalid token format. Please send a valid Bot Token from BotFather.")
                return
                
            await set_bot_setting(bot_id, "bot_token", text)
            ADMIN_STATES.pop(user_id, None)
            
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data=f"manage_{bot_id}")]])
            await update.message.reply_text(
                text=f"✅ <b>Token Updated Successfully for {bot_id}!</b>\n\nIf the bot script is running, it will automatically connect using this new token.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )
            
    except Exception as e:
        logger.error(f"Error handling admin text: {e}")
        await update.message.reply_text("❌ An error occurred while saving the data.")

# ==========================================
# MAIN INITIALIZATION
# ==========================================
async def post_init(application: Application) -> None:
    """Runs after the bot initializes but before polling starts."""
    await init_system()
    logger.info("Master Panel Booted Successfully.")

def main() -> None:
    if not MASTER_BOT_TOKEN:
        logger.error("MASTER_BOT_TOKEN is missing in .env file.")
        return

    app = Application.builder().token(MASTER_BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))

    # Run polling
    logger.info("Starting Enterprise Master Panel...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
