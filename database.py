import os
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument, ASCENDING
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# CONFIGURATION & LOGGING
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
IST = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if not MONGO_URI:
    raise ValueError("MONGO_URI is missing in .env file. System cannot start.")

# Initialize MongoDB Async Client with timeout
try:
    db_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = db_client["enterprise_multi_bot"]
except Exception as e:
    logger.error(f"Database connection failed: {e}")
    raise SystemExit(1)

# ==========================================
# HELPER TIME FUNCTIONS
# ==========================================
def now_utc() -> datetime:
    """Returns current UTC time."""
    return datetime.now(timezone.utc)

def now_iso() -> str:
    """Returns current UTC time in ISO format."""
    return now_utc().isoformat()

# ==========================================
# DATABASE SETUP & INDEXING (Multi-Bot Optimized)
# ==========================================
async def setup_indexes() -> None:
    """Creates database indexes to ensure fast multi-bot queries."""
    try:
        await db.users.create_index([("bot_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
        await db.payments.create_index([("bot_id", ASCENDING), ("id", ASCENDING)])
        await db.purchases.create_index([("bot_id", ASCENDING), ("user_id", ASCENDING)])
        await db.bot_configs.create_index([("bot_id", ASCENDING)], unique=True)
        logger.info("Database Indexes Verified for Multi-Bot Architecture.")
    except Exception as e:
        logger.error(f"Error setting up database indexes: {e}")

async def get_next_sequence_value(bot_id: str, sequence_name: str) -> int:
    """Retrieves next unique ID isolated per bot."""
    try:
        doc = await db.counters.find_one_and_update(
            {"_id": f"{bot_id}_{sequence_name}"},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return doc["sequence_value"]
    except Exception as e:
        logger.error(f"Failed to get sequence value for {sequence_name}: {e}")
        return int(now_utc().timestamp()) # Fallback ID

# ==========================================
# BOT CONFIGURATION MANAGERS
# ==========================================
async def get_bot_setting(bot_id: str, key: str, default: str = "") -> str:
    """Fetches a specific setting for a specific bot (e.g., token, payment UI)."""
    try:
        config = await db.bot_configs.find_one({"bot_id": bot_id})
        if not config or key not in config:
            return default
        
        val = config.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            return default
        return val
    except Exception as e:
        logger.error(f"Error fetching bot setting ({bot_id} - {key}): {e}")
        return default

async def set_bot_setting(bot_id: str, key: str, value: str) -> None:
    """Updates a setting for a specific bot from the Master Panel."""
    try:
        await db.bot_configs.update_one(
            {"bot_id": bot_id}, 
            {"$set": {key: value}}, 
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error setting bot setting ({bot_id} - {key}): {e}")

async def init_default_bot_config(bot_id: str) -> None:
    """Initializes a new bot with default settings if it doesn't exist."""
    try:
        existing = await db.bot_configs.find_one({"bot_id": bot_id})
        if not existing:
            await db.bot_configs.insert_one({
                "bot_id": bot_id,
                "bot_name": f"Enterprise Bot {bot_id[-1] if bot_id[-1].isdigit() else ''}",
                "bot_token": "", 
                "status": "stopped", 
                "payment_name": "Your Enterprise",
                "payment_note": "Scan exact amount to get instant access.",
                "demo_link": "https://t.me/your_demo",
                "support_link": "https://t.me/your_support",
                "show_btn_buy": "1",
                "show_btn_profile": "1",
                "show_btn_support": "1",
                "show_btn_proofs": "0",
                "created_at": now_iso()
            })
    except Exception as e:
        logger.error(f"Error initializing default config for {bot_id}: {e}")

# ==========================================
# GLOBAL ADMIN INITIALIZATION
# ==========================================
async def is_global_admin(user_id: int) -> bool:
    """Checks if a user is a Master Admin (can access Master Panel)."""
    if user_id == OWNER_ID:
        return True
    try:
        row = await db.global_admins.find_one({"_id": user_id})
        return row is not None
    except Exception as e:
        logger.error(f"Error checking admin status for {user_id}: {e}")
        return False

async def init_system() -> None:
    """Called when Master Panel starts to prep the database structure."""
    await setup_indexes()
    try:
        await db.global_admins.update_one(
            {"_id": OWNER_ID}, 
            {"$setOnInsert": {"added_at": now_iso(), "role": "owner"}}, 
            upsert=True
        )
        
        # Pre-initialize configs for 5 slave slots
        for i in range(1, 6):
            await init_default_bot_config(f"bot_{i}")
            
        logger.info("System Core Initialized Successfully.")
    except Exception as e:
        logger.error(f"System initialization failed: {e}")
