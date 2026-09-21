import sys
import asyncio
import logging
import traceback
from typing import Optional, List

from telegram import (
    Update, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters
)

# Import shared database engine
from database import db, get_bot_setting

# ==========================================
# SYSTEM INITIALIZATION & VALIDATION
# ==========================================
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Check if bot_id is provided in terminal command
if len(sys.argv) < 2:
    logger.error("Missing bot_id argument. Usage: python slave_bot.py bot_1")
    sys.exit(1)

BOT_ID = sys.argv[1].strip()

# ==========================================
# DYNAMIC UI ENGINE (Anonymity Feature)
# ==========================================
async def build_dynamic_keyboard() -> ReplyKeyboardMarkup:
    """Builds a custom UI bottom menu based on this specific bot's database config."""
    # Fetch settings specific to THIS bot only
    show_buy = await get_bot_setting(BOT_ID, "show_btn_buy", "1")
    show_profile = await get_bot_setting(BOT_ID, "show_btn_profile", "1")
    show_support = await get_bot_setting(BOT_ID, "show_btn_support", "1")
    show_proofs = await get_bot_setting(BOT_ID, "show_btn_proofs", "0")
    
    btns = []
    if show_buy == "1":
        btns.append(KeyboardButton(await get_bot_setting(BOT_ID, "btn_buy_text", "🛍️ Buy Packages")))
    if show_profile == "1":
        btns.append(KeyboardButton(await get_bot_setting(BOT_ID, "btn_profile_text", "👤 My Profile")))
    if show_proofs == "1":
        btns.append(KeyboardButton(await get_bot_setting(BOT_ID, "btn_proofs_text", "📸 Proofs")))
    if show_support == "1":
        btns.append(KeyboardButton(await get_bot_setting(BOT_ID, "btn_support_text", "📞 Help / Support")))

    # Format into a grid (2 buttons per row)
    keyboard: List[List[KeyboardButton]] = [btns[i:i+2] for i in range(0, len(btns), 2)]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# ==========================================
# USER MANAGEMENT & TRACKING
# ==========================================
async def register_user(update: Update) -> None:
    """Registers the user specifically under this bot_id to maintain isolation."""
    user = update.effective_user
    if not user:
        return

    try:
        await db.users.update_one(
            {"bot_id": BOT_ID, "user_id": user.id},
            {"$set": {
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "last_seen": asyncio.get_event_loop().time()
            }, "$setOnInsert": {
                "is_buyer": 0,
                "is_18_plus": False
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"[{BOT_ID}] User registration failed: {e}")

# ==========================================
# CORE COMMAND HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command with dynamic welcoming."""
    asyncio.create_task(register_user(update))
    
    # Check bot status from Master Panel
    status = await get_bot_setting(BOT_ID, "status", "stopped")
    if status != "active":
        await update.message.reply_text("⏳ This bot is currently under maintenance.")
        return

    # Fetch custom welcome elements for this specific bot
    welcome_text = await get_bot_setting(BOT_ID, "welcome_text", "Welcome to our Premium Bot!")
    start_media = await get_bot_setting(BOT_ID, "start_gif", "")

    dynamic_kb = await build_dynamic_keyboard()

    try:
        if start_media.startswith("http"):
            await context.bot.send_animation(
                chat_id=update.message.chat_id,
                animation=start_media,
                caption=welcome_text,
                parse_mode=ParseMode.HTML,
                reply_markup=dynamic_kb
            )
        else:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=welcome_text,
                parse_mode=ParseMode.HTML,
                reply_markup=dynamic_kb
            )
    except Exception as e:
        logger.error(f"[{BOT_ID}] Error sending start screen: {e}")
        # Fallback if image fails
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=welcome_text,
            parse_mode=ParseMode.HTML,
            reply_markup=dynamic_kb
        )

# ==========================================
# MESSAGE ROUTER (MENU NAVIGATION)
# ==========================================
async def handle_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes button clicks to the appropriate functions."""
    text = (update.message.text or "").strip()
    
    buy_txt = await get_bot_setting(BOT_ID, "btn_buy_text", "🛍️ Buy Packages")
    prof_txt = await get_bot_setting(BOT_ID, "btn_profile_text", "👤 My Profile")
    supp_txt = await get_bot_setting(BOT_ID, "btn_support_text", "📞 Help / Support")

    if text == buy_txt:
        # We will build the category fetching logic in the next file (callbacks)
        await update.message.reply_text("🛒 Loading packages... (Categories UI will trigger here)")
    elif text == prof_txt:
        await update.message.reply_text(f"👤 User ID: <code>{update.effective_user.id}</code>\nStatus: Free User", parse_mode=ParseMode.HTML)
    elif text == supp_txt:
        await update.message.reply_text("📞 Support feature initiated. Please type your message.")
    else:
        await update.message.reply_text("Please use the menu buttons below.", reply_markup=await build_dynamic_keyboard())

# ==========================================
# APP LAUNCHER
# ==========================================
async def get_bot_token_from_db() -> str:
    """Fetches the token synchronously for application building."""
    return await get_bot_setting(BOT_ID, "bot_token", "")

def main() -> None:
    # 1. Fetch token from DB
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    token = loop.run_until_complete(get_bot_token_from_db())

    if not token:
        logger.error(f"🚨 Token for {BOT_ID} not found! Please set it via the Master Panel first.")
        sys.exit(1)

    # 2. Initialize Application
    app = Application.builder().token(token).build()

    # 3. Add Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text))

    # 4. Start Polling
    logger.info(f"✅ {BOT_ID.upper()} Engine Started Successfully.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
