import os
import sys

# Ensure local ffmpeg.exe and imageio_ffmpeg binaries are in PATH for PyTgCalls
try:
    import imageio_ffmpeg
    ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    os.environ["PATH"] = os.getcwd() + os.pathsep + ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    os.environ["PATH"] = os.getcwd() + os.pathsep + os.environ.get("PATH", "")

import asyncio
import io
import json
import logging
import math
import random
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
import urllib.parse

from aiohttp import web
import requests
import telebot
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
import qrcode
import pytz
from pymongo import MongoClient

import telethon
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    UserAdminInvalidError,
)
from telethon.tl.functions.channels import (
    EditAdminRequest,
    EditBannedRequest,
    InviteToChannelRequest,
    JoinChannelRequest,
)
from telethon.tl.functions.messages import CreateChatRequest, ImportChatInviteRequest
from telethon.tl.functions.phone import (
    EditGroupCallParticipantRequest,
    LeaveGroupCallRequest,
)

# PyTgCalls Engine (py-tgcalls)
try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
    HAS_PYTGCALLS = True
except ImportError:
    HAS_PYTGCALLS = False

# python-telegram-bot (PTB)
try:
    from telegram import (
        Update,
        ChatMember,
        ChatAdministratorRights,
        ReactionTypeEmoji
    )
    from telegram.ext import (
        Application,
        ContextTypes,
        MessageHandler,
        ChatMemberHandler,
        filters,
    )
    from telegram.request import HTTPXRequest
    from telegram.error import RetryAfter, BadRequest
    HAS_PTB = True
except ImportError:
    HAS_PTB = False

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - [TG_MASTER] - %(message)s"
)
logger = logging.getLogger("TGMaster")

# ==============================================================================
# CONFIGURATION & GLOBAL SETTINGS
# ==============================================================================
API_ID = int(os.getenv("TELEGRAM_API_ID", 38610071))
API_HASH = os.getenv("TELEGRAM_API_HASH", "c5d120da18a27ab1c37cb78f94e22fbf")
USERBOT_PHONE_DEFAULT = os.getenv("TELEGRAM_PHONE", "+918986269256")
MASTER_ADMIN_DEFAULT = int(os.getenv("MASTER_ADMIN_ID", "5214825153"))
SERVICE_PORT = 20826

PREFIX = '+'
BOT_PREFIX = '?'
CMD_PREFIXES = ["+", "!", ".", "/", "-", "?", "*", "$", "#", "&", "_"]

TOKEN_FILE = "tokens.txt"
DB_FILE = "server_god_clan.db"
START_TIME = time.time()
db_lock = threading.Lock()

os.makedirs("pics", exist_ok=True)
os.makedirs("tts", exist_ok=True)

vc_loop_unmute_active: Dict[int, bool] = {}
jio_playlist_state: Dict[int, Dict] = {}

http_session = requests.Session()
http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
})

if not os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "w") as f:
        f.write("")

# Telethon Global tracking & PyTgCalls instances
call_py_instances: Dict[int, PyTgCalls] = {}
latest_pending_phone: Optional[str] = None
temp_login_sessions: Dict[str, Dict] = {}
running_userbots: Dict[str, Dict] = {}
registered_ub_clients = set()

# Global in-memory log buffer for Web Terminal
global_tg_logs = []
def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    global_tg_logs.append(entry)
    if len(global_tg_logs) > 300:
        global_tg_logs.pop(0)
    logger.info(msg)

# Global Telegram Command & Message Deduplication
tg_processed_commands = {} # (chat_id, msg_id, cmd_name) -> timestamp

def should_process_tg_command(chat_id: int, msg_id: int, cmd_name: str) -> bool:
    global tg_processed_commands
    now = time.time()
    if len(tg_processed_commands) > 1500:
        tg_processed_commands = {k: v for k, v in tg_processed_commands.items() if now - v < 35}
    
    key = (chat_id, msg_id, cmd_name)
    if key in tg_processed_commands:
        return False
    tg_processed_commands[key] = now
    return True

# ==============================================================================
# MONGODB ATLAS INTEGRATION (ZERO LOCAL FILE POLLUTION)
# ==============================================================================
mongo_client = None
mongo_db = None
mongo_connected = False

def init_mongo_connection():
    global mongo_client, mongo_db, mongo_connected
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri and os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.startswith("MONGODB_URI="):
                        uri = line.split("=", 1)[1].strip()
        except Exception:
            pass

    if not uri:
        # Default MongoDB Atlas URI with encoded password
        pwd = urllib.parse.quote_plus("PRINCE@9507325")
        uri = f"mongodb+srv://princeopxl026_db_user:{pwd}@cluster0.8hcoae.mongodb.net/igtgwp_db?retryWrites=true&w=majority"

    try:
        mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db_name = "igtgwp_db"
        mongo_db = mongo_client[db_name]
        mongo_connected = True
        add_log(f"🍃 [MONGODB] Connected to Atlas Database: '{db_name}'")
    except Exception as e:
        mongo_connected = False
        add_log(f"⚠️ [MONGODB] Atlas Connection Warning: {e}. Using SQLite fallback.")

init_mongo_connection()

def mongo_save_userbot(uid: str, session_str: str, first_name: str, user_id: int, owner: str, admin_id: str):
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_userbot_sessions"].replace_one(
                {"_id": str(uid)},
                {
                    "_id": str(uid),
                    "uid": str(uid),
                    "session_str": session_str,
                    "first_name": first_name,
                    "user_id": user_id,
                    "owner": owner,
                    "admin_id": str(admin_id),
                    "updatedAt": str(datetime.utcnow())
                },
                upsert=True
            )
            add_log(f"🍃 [MONGODB] Userbot session '{uid}' synced to Atlas.")
        except Exception as e:
            add_log(f"❌ [MONGODB ERROR] mongo_save_userbot: {e}")

def mongo_delete_userbot(uid: str):
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_userbot_sessions"].delete_one({"_id": str(uid)})
            mongo_db["tg_userbot_sessions"].delete_one({"uid": str(uid)})
            mongo_db["tg_userbot_sessions"].delete_one({"phone_or_id": str(uid)})
            add_log(f"🍃 [MONGODB] Userbot session '{uid}' purged from Atlas.")
        except Exception as e:
            add_log(f"❌ [MONGODB ERROR] mongo_delete_userbot: {e}")

def mongo_save_swarm(swarm_id: str, owner: str, admin_id: str, tokens: List[str], prefix: str, burst_limit: int, spam_delay: float, nc_delay: int):
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_swarm_configs"].replace_one(
                {"_id": str(swarm_id)},
                {
                    "_id": str(swarm_id),
                    "swarm_id": str(swarm_id),
                    "owner": owner,
                    "admin_id": str(admin_id),
                    "tokens": tokens,
                    "prefix": prefix,
                    "burst_limit": burst_limit,
                    "spam_delay": spam_delay,
                    "nc_delay": nc_delay,
                    "updatedAt": str(datetime.utcnow())
                },
                upsert=True
            )
            add_log(f"🍃 [MONGODB] Swarm config '{swarm_id}' synced to Atlas.")
        except Exception as e:
            add_log(f"❌ [MONGODB ERROR] mongo_save_swarm: {e}")

def mongo_delete_swarm(swarm_id: str):
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_swarm_configs"].delete_one({"_id": str(swarm_id)})
            mongo_db["tg_swarm_configs"].delete_one({"swarm_id": str(swarm_id)})
            add_log(f"🍃 [MONGODB] Swarm config '{swarm_id}' purged from Atlas.")
        except Exception as e:
            add_log(f"❌ [MONGODB ERROR] mongo_delete_swarm: {e}")

# ==============================================================================
# PHRASES & PERMISSIONS
# ==============================================================================
NC_LINES = [
    "sʟᴀᴠᴇ 💢", "ʙɪᴛᴄʜ 💢", "ғᴜᴄᴋ ʏᴏᴜ 💢", "ᴛᴍʀ 💢", "ᴛᴍᴋʙ 💢", "ᴛʀʏᴍᴀ ᴋᴀ ʙʜᴏsᴅᴀ ʜᴀɴɢ 💢", "लंड खा 💢",
    "ᴛᴍᴋʙ ᴍᴇ 64 ɢʙ ʀᴅᴘ 💢", "गांडू पिल्ले 💢", "तू रंडी 💢", "तू हिजड़ा 💢", "भोस्डिवाले 💢", "तू कुतिया 💢"
]

NCEMO_EMOJIS = [
    "💔", "😖", "🦋", "🤍", "🔥", "⁉️", "😞", "👾", "🤤", "😋", "😛", "👌", "☺️", "😝", "😕", "🙂",
    "🤛", "🤜", "🤚", "👋", "🫶", "🙌", "👐", "✍️", "🤟", "🤲", "🙏", "💅", "🩷", "🧡", "💛", "💚",
    "❤️", "🩹", "❣️", "💕", "💞", "💟", "💝", "💘", "💖", "💓", "💗", "💌", "💢", "💥", "💤", "💦",
    "💨", "❤️🔥", "☮️", "🗿", "👑", "🩵", "🔱", "🌷", "❤️🩹", "👞", "🤮", "🤣", "😭", "🥺", "😁",
    "👿", "🚀", "🥹", "😬", "🙄", "😎", "👽", "👾", "😈", "👹", "🤡", "🙀", "🐒", "🦁", "🐅", "🦓"
]

RAID_TEXTS = [
    "🔥 DESTROYED BY SERVER GOD CLAN!",
    "⚡ RUN AWAY NOW HATER!",
    "💥 DOMINATED BY SERVER GOD CLAN!",
    "𝘾𝙔𝙐 𝙍𝙀 𝙍𝙉𝘿𝙔𝙆𝙀 𝘽𝘼𝘼𝙋 𝙎𝙀 𝘽𝙃𝙄𝘿𝙉𝙀 𝘼𝘼 𝙂𝙔𝘼?",
    "𝘾𝙃𝙇 𝘾𝙃𝙐𝘿 𝘼𝘽 𝙍𝙉𝘿 𝙆𝙀 𝙋𝙄𝙇𝙀𝙀",
    "𝙏𝙍𝙔 𝙈𝘼 𝙆𝙊 𝐄ʙᴜ𝐔 𝘼𝘽𝘽𝙐 𝙋𝙀𝙇𝙀",
    "𝙔𝙀𝙃 𝙂𝙍𝙀𝙀𝙑 𝙁𝙔𝙏𝙀𝙍 𝙄𝙎𝙆𝙄 𝙈𝙆𝘽",
    "𝙃𝙑𝘼𝘽𝘼𝘼𝙕 𝘽𝘼𝙉𝙀𝙂𝘼 𝙏𝙈𝙍",
    "𝙏𝙀𝙍𝙄 𝙈𝘼 𝙆𝘼 𝙋𝘼𝙏𝙄 𝐄ʙᴜ𝐔 𝙃𝘼𝙄",
    "𝘽𝙃𝘼𝘼𝙂 𝙈𝘼𝙏 𝙋𝙄𝙇𝙇𝙀 𝙊𝙔𝙀",
    "𝘼𝘽𝙀 𝙇𝙊𝘿𝙐 𝙏𝙀𝙍𝙄 𝙂𝘼𝙉𝘿 𝙈𝙀 𝘿𝘼𝙉𝘿𝘼",
    "𝙏𝙀𝙍𝙄 𝙈𝘼 𝙆𝙄 𝘾𝙃𝙐𝙏 𝙈𝙀 𝘽𝙊𝙏 𝙆𝘼 𝙇𝙐𝙉𝘿",
    "𝘽𝙃𝘼𝂂 𝘽𝙃𝙊𝙎𝘿𝙄𝙆𝙀 𝘽𝙃𝘼𝂂",
    "𝙏𝙀𝙍𝘼 𝙆𝙃𝘼𝙉𝘿𝘼𝙉 𝙆𝙃𝘼𝙏𝘼𝙈",
    "𝘽𝘼𝘼𝙋 𝙎𝙀 𝘽𝘼𝙆𝘾𝙃𝙊𝘿𝙄 𝙉𝙃𝙄",
    "𝙏𝙀𝙍𝙄 𝙈𝘼 𝙆𝙊 𝘾𝙃𝙊𝘿 𝘿𝙐𝙉𝙂𝘼",
    "𝘼𝐐𝘼𝙏 𝙈𝙀 𝙍𝙀𝙃 𝙇𝙊𝘿𝙀",
    "𝙏𝙀𝙍𝘼 𝘽𝘼𝘼𝙋 𝙃𝙐 𝙈𝘼𝙄"
]

SPAM_TEXTS = [
    "<[{target}]> 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐊ᴀʟɪ 𝐆ᴀɴᴅ 𝐌ᴇ 𝐂ɪɢɢ 𝐅ᴀsᴀ 𝐃ᴜ 𝐁sᴅᴋ <😝>༻꧂\n <[{target}]> 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐊ᴀʟɪ 𝐆ᴀɴᴅ 𝐌ᴇ 𝐂ɪɢɢ 𝐅ᴀsᴀ 𝐃ᴜ 𝐁sᴅᴋ <🤖>༻꧂\n <[{target}]> 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐊ᴀʟɪ 𝐆ᴀɴᴅ 𝐌ᴇ 𝐂ɪɢɢ 𝐅ᴀsᴀ 𝐃ᴜ 𝐁sᴅᴋ <👾>༻꧂\n <[{target}]> 𝐓ᴇʀɪ 𝐌ᴀᴀ 𝐊ɪ 𝐊ᴀʟɪ 𝐆ᴀɴᴅ 𝐌ᴇ 𝐂ɪɢɢ 𝐅ᴀsᴀ 𝐃ᴜ 𝐁sᴅᴋ <🤣>༻꧂",
    "𓍼ֶ˖ܓ 🦈 <[{target}]> ओए तेरी माँ की सलवार मे 𝐈 𝐏ʜᴏɴᴇ 17 फिट कर दू ?? <🌸> ᭄\n 𓍼ֶ˖ܓ 🦈 <[{target}]> ओए तेरी माँ की सलवार मे 𝐈 𝐏ʜᴏɴᴇ 17 फिट कर दू ?? <🌸> ᭄\n 𓍼ֶ˖ܓ 🦈 <[{target}]> ओए तेरी माँ की सलवार मे 𝐈 𝐏ʜᴏɴᴇ 17 फिट कर दू ?? <🌸> ᭄",
    "<[{target}]> 𝙏𝙈𝙆𝘽 ━━ <🦁>\n<[{target}]> 𝙏𝙈𝙆𝘽 ━━ <😹>\n<[{target}]> 𝙏𝙈𝙆𝘽 ━━ <🔥>\n<[{target}]> 𝙏𝙈𝙆𝘽 ━━ <🚀>",
    "<[{target}]> Cʜɪɴᴀʟ ᴋᴇ ʙᴀᴄʜᴇ ᴛᴇʀɪ ᴍᴀᴀ ᴄʜᴜᴅ ʀᴀʜɪ!🩵🦋🫧🌍\n<[{target}]> Cʜɪɴᴀʟ ᴋᴇ ʙᴀᴄʜᴇ ᴛᴇʀɪ ᴍᴀᴀ ᴄʜᴜᴅ ʀᴀʜɪ!🩵🦋🫧🌍",
    "{target} 𝑇𝐸𝑅𝐼 𝐵𝐼𝐻𝐴𝑅𝐼 𝑀𝐴𝐴 𝐾 𝐵𝐻𝑂𝑆𝐷𝐸 𝑀𝐸 𝑇𝐼𝐿𝐸 𝐿𝐺𝐴 𝐷𝐼\n{target} 𝑇𝐸𝑅𝐼 𝐵𝐼𝐻𝐴𝑅𝐼 𝑀𝐴𝐴 𝐾 𝐵𝐻𝑂𝑆𝐷𝐸 𝑀𝐸 𝑇𝐼𝐿𝐸 𝐿𝐺𝐴 𝐷𝐼",
    "𝙁𝙊𝘿 𝘿𝙐 𝙈𝘼𝙏𝙆𝘼 𝙂𝙄𝙍𝘼 𝘿𝙐 𝙋𝘼𝙉𝙄 {target} 𝙏𝙀𝙍𝙄 𝙈𝘼𝘼 𝘾𝙃𝙐𝘿𝘼𝙄 𝙆𝙃𝘼𝙉𝙀 𝙆𝙄 𝙍𝘼𝙉𝙄 ミミミミミミミミミミミミミミ࿐",
    "☄►♘ / 𝟮 लन्ड अंदर , {target} 𝗞𝗜 𝗠𝗔𝗔 𝗕𝗔𝗡𝗜 सिकंदर 🏳️⚧️💢\n☄►♘ / 𝟮 लन्ड अंदर , {target} 𝗞𝗜 𝗠𝗔𝗔 𝗕𝗔𝗡𝗜 सिकंदर 🏳️⚧️💢"
]

FULL_RIGHTS = ChatAdministratorRights(
    is_anonymous=False,
    can_manage_chat=True,
    can_delete_messages=True,
    can_manage_video_chats=True,
    can_restrict_members=True,
    can_promote_members=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_post_stories=True,
    can_edit_stories=True,
    can_delete_stories=True,
    can_manage_topics=True
)

# ==============================================================================
# SQLITE PERSISTENT DATABASE SETUP
# ==============================================================================
def init_db():
    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        c = conn.cursor()
        c.execute('PRAGMA journal_mode=WAL;')
        c.execute('PRAGMA busy_timeout=5000;')
        c.execute('CREATE TABLE IF NOT EXISTS userbot_admins (user_id INTEGER PRIMARY KEY, node_uid TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY, added_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS managed_bots (bot_id TEXT PRIMARY KEY, added_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS userbot_sessions (phone_or_id TEXT PRIMARY KEY, session_str TEXT, first_name TEXT, user_id INTEGER, owner TEXT, admin_id TEXT, added_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS tg_swarm_configs (swarm_id TEXT PRIMARY KEY, owner TEXT, admin_id TEXT, tokens_json TEXT, prefix TEXT, burst_limit INTEGER, spam_delay REAL, nc_delay INTEGER, added_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS targets (user_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS target_groups (chat_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS muted_users (user_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS welcome_settings (chat_id INTEGER PRIMARY KEY, welcome_text TEXT, goodbye_text TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS filters (chat_id INTEGER, trigger TEXT, response TEXT, PRIMARY KEY (chat_id, trigger))')
        c.execute('CREATE TABLE IF NOT EXISTS warnings (chat_id INTEGER, user_id INTEGER, count INTEGER, PRIMARY KEY (chat_id, user_id))')
        c.execute('CREATE TABLE IF NOT EXISTS gc_creation_settings (user_id INTEGER PRIMARY KEY, qty INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS afk_state (id INTEGER PRIMARY KEY, is_afk INTEGER, reason TEXT, afk_time REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS afk_mentions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, msg_text TEXT, timestamp TEXT)')
        
        c.execute('INSERT OR IGNORE INTO userbot_admins (user_id) VALUES (?)', (MASTER_ADMIN_DEFAULT,))
        c.execute('INSERT OR IGNORE INTO userbot_admins (user_id) VALUES (?)', (8846249998,))
        c.execute('INSERT OR IGNORE INTO bot_admins (user_id, added_at) VALUES (?, ?)', (MASTER_ADMIN_DEFAULT, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()

init_db()

# INDIVIDUAL TASK MANAGER PER USERBOT CLIENT
ub_tasks_per_client: Dict[int, Dict] = {}

def get_client_tasks(client: TelegramClient) -> Dict:
    cid = id(client)
    if cid not in ub_tasks_per_client:
        ub_tasks_per_client[cid] = {
            "spam": False,
            "spam_delay": 2.0,
            "fucktarget": False,
            "fucktarget_delay": 1.5,
        }
    return ub_tasks_per_client[cid]

async def execute_db_query(query: str, params: tuple = (), fetchone=False, fetchall=False, commit=False):
    def db_worker():
        with db_lock:
            with sqlite3.connect(DB_FILE, timeout=10) as conn:
                c = conn.cursor()
                c.execute('PRAGMA busy_timeout=5000;')
                c.execute(query, params)
                res = None
                if fetchone:
                    res = c.fetchone()
                elif fetchall:
                    res = c.fetchall()
                if commit:
                    conn.commit()
                return res
    return await asyncio.to_thread(db_worker)

async def is_ub_admin(event, me_id: int, admin_id_val: Optional[str] = None) -> bool:
    if getattr(event, 'out', False):
        return True

    sender_id = getattr(event, 'sender_id', None)
    if not sender_id and hasattr(event, 'message') and hasattr(event.message, 'from_id'):
        from_id = event.message.from_id
        if isinstance(from_id, types.PeerUser):
            sender_id = from_id.user_id

    if not sender_id: return False
    if sender_id == me_id: return True
    if sender_id in [5214825153, 8846249998, MASTER_ADMIN_DEFAULT]: return True

    if admin_id_val:
        clean_adm = str(admin_id_val).replace("+", "").replace(" ", "").strip()
        if clean_adm and (str(sender_id) == clean_adm or clean_adm in str(sender_id)):
            return True

    row = await execute_db_query("SELECT user_id FROM userbot_admins WHERE user_id=?", (sender_id,), fetchone=True)
    return row is not None

async def is_bot_admin(user_id: int) -> bool:
    if user_id in [5214825153, 8846249998, MASTER_ADMIN_DEFAULT]: return True
    res = await execute_db_query("SELECT user_id FROM bot_admins WHERE user_id=?", (user_id,), fetchone=True)
    return res is not None

def sync_execute_db_query(query: str, params: tuple = (), fetchone=False, fetchall=False, commit=False):
    with db_lock:
        with sqlite3.connect(DB_FILE, timeout=10) as conn:
            c = conn.cursor()
            c.execute('PRAGMA busy_timeout=5000;')
            c.execute(query, params)
            res = None
            if fetchone:
                res = c.fetchone()
            elif fetchall:
                res = c.fetchall()
            if commit:
                conn.commit()
            return res

def is_bot_admin_sync(user_id: int) -> bool:
    if user_id in [5214825153, 8846249998, MASTER_ADMIN_DEFAULT]: return True
    res = sync_execute_db_query("SELECT user_id FROM bot_admins WHERE user_id=?", (user_id,), fetchone=True)
    return res is not None

# ==============================================================================
# HELPER APIS & ENGINES (PURE JIOSAAVN - NO YOUTUBE)
# ==============================================================================
def query_unlimited_ai(prompt: str) -> str:
    try:
        url = f"https://text.pollinations.ai/{requests.utils.quote(prompt)}?model=openai&cache=false"
        res = http_session.get(url, timeout=8)
        text = res.content.decode('utf-8', errors='ignore').strip()
        if res.status_code == 200 and text and "Timed Out" not in text:
            return text
    except Exception: pass

    try:
        res = http_session.post(
            "https://text.pollinations.ai/",
            json={"messages": [{"role": "user", "content": prompt}], "model": "openai"},
            timeout=8
        )
        text = res.content.decode('utf-8', errors='ignore').strip()
        if res.status_code == 200 and text and "Timed Out" not in text:
            return text
    except Exception: pass

    try:
        url = f"https://api.popcat.xyz/chatbot?msg={requests.utils.quote(prompt)}&owner=ServerGod&botname=GodAI"
        res = http_session.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            ans = data.get("response", "")
            if ans and "Timed Out" not in ans and "Error" not in ans:
                return ans
    except Exception: pass

    return "🧠 **Server God AI Engine is currently processing. Please resend prompt.**"

def get_all_jiosaavn_quality_urls(raw_url: str) -> List[str]:
    if not raw_url: return []
    candidates = []
    base_url = raw_url.replace("preview.saavncdn.com", "aac.saavncdn.com")
    base_clean = re.sub(r'_(96_p|128_p|320_p|_p|[0-9]+)\.(mp4|mp3)', '', base_url)
    if base_clean.endswith('.mp4') or base_clean.endswith('.mp3'):
        base_clean = base_clean[:-4]

    for quality in ['_320.mp4', '_160.mp4', '_128.mp4', '_96.mp4', '_320.mp3', '_160.mp3', '_128.mp3']:
        cand = f"{base_clean}{quality}"
        if cand not in candidates:
            candidates.append(cand)
            
    fixed_1 = re.sub(r'_96_p\.mp4', '_320.mp4', base_url)
    fixed_2 = re.sub(r'_p\.mp4', '_320.mp4', base_url)
    for f in [fixed_1, fixed_2, base_url, raw_url]:
        if f not in candidates:
            candidates.append(f)
            
    return candidates

def extract_jiosaavn_audio_link(song: dict) -> Optional[str]:
    dl_urls = song.get("downloadUrl") or song.get("download_url") or song.get("media_url") or song.get("media_url_320_kbps")
    if isinstance(dl_urls, list) and dl_urls:
        for entry in reversed(dl_urls):
            if isinstance(entry, dict):
                u = entry.get("url") or entry.get("link")
                if u: return u
            elif isinstance(entry, str) and entry:
                return entry
    elif isinstance(dl_urls, str) and dl_urls:
        return dl_urls
    
    u = song.get("vlink") or song.get("media_preview_url") or song.get("url") or song.get("media_url")
    if u: return u
    return None

def get_file_duration(file_path: str) -> float:
    try:
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            est_sec = size_bytes / 35000.0
            return max(30.0, est_sec)
    except Exception: pass
    return 210.0

def download_full_audio(query_or_url: str, output_path: str) -> Optional[Dict]:
    cleaned = query_or_url.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://www.jiosaavn.com/"
    }

    if cleaned.startswith("http"):
        try:
            res = requests.get(cleaned, headers=headers, timeout=30)
            if res.status_code == 200 and len(res.content) > 500000:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                duration = get_file_duration(output_path)
                return {
                    "status": True,
                    "title": os.path.basename(cleaned),
                    "artist": "JioSaavn",
                    "file_path": output_path,
                    "duration": duration
                }
        except Exception: pass

    jio_endpoints = [
        f"https://saavn-api-alpha.vercel.app/api/search/songs?query={requests.utils.quote(cleaned)}",
        f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&p=1&n=5&q={requests.utils.quote(cleaned)}"
    ]

    candidate_urls = []
    song_title = cleaned
    song_artist = "JioSaavn Artist"

    for search_url in jio_endpoints:
        try:
            res = requests.get(search_url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                results = []
                if isinstance(data, dict):
                    results = data.get("data", {}).get("results", []) or data.get("results", [])
                elif isinstance(data, list):
                    results = data

                if results and isinstance(results, list):
                    song = results[0]
                    song_title = song.get("name", song.get("song", song.get("title", cleaned))).replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")
                    
                    artists_field = song.get("artists", {})
                    if isinstance(artists_field, dict):
                        primary = artists_field.get("primary", [])
                        if primary and isinstance(primary, list) and isinstance(primary[0], dict):
                            song_artist = primary[0].get("name", "JioSaavn Artist")
                    elif isinstance(song.get("singers"), str):
                        song_artist = song.get("singers")

                    dl_urls = song.get("downloadUrl") or song.get("download_url") or song.get("media_url")
                    if isinstance(dl_urls, list) and dl_urls:
                        for entry in reversed(dl_urls):
                            u = entry.get("url") if isinstance(entry, dict) else entry
                            if u and isinstance(u, str) and u not in candidate_urls:
                                candidate_urls.append(u)
                    elif isinstance(dl_urls, str) and dl_urls:
                        candidate_urls.append(dl_urls)

                    raw_preview = song.get("media_preview_url") or song.get("vlink")
                    if raw_preview and isinstance(raw_preview, str):
                        converted_urls = get_all_jiosaavn_quality_urls(raw_preview)
                        for cu in converted_urls:
                            if cu not in candidate_urls:
                                candidate_urls.append(cu)
                        if raw_preview not in candidate_urls:
                            candidate_urls.append(raw_preview)

                    if candidate_urls:
                        break
        except Exception: pass

    for cand_url in candidate_urls:
        try:
            res = requests.get(cand_url, headers=headers, timeout=30)
            if res.status_code == 200 and len(res.content) > 1000000:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                duration = get_file_duration(output_path)
                return {
                    "status": True,
                    "title": song_title,
                    "artist": song_artist,
                    "file_path": output_path,
                    "duration": duration
                }
        except Exception: pass

    for cand_url in candidate_urls:
        try:
            res = requests.get(cand_url, headers=headers, timeout=25)
            if res.status_code == 200 and len(res.content) > 300000:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                duration = get_file_duration(output_path)
                return {
                    "status": True,
                    "title": song_title,
                    "artist": song_artist,
                    "file_path": output_path,
                    "duration": duration
                }
        except Exception: pass

    return {"status": False}

def search_multiple_jiosaavn(query: str, limit=10) -> List[Dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://www.jiosaavn.com/"
    }
    cleaned_query = query.strip()
    songs_list = []

    jio_endpoints = [
        f"https://saavn-api-alpha.vercel.app/api/search/songs?query={requests.utils.quote(cleaned_query)}",
        f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&p=1&n={limit}&q={requests.utils.quote(cleaned_query)}"
    ]
    for search_url in jio_endpoints:
        try:
            res = requests.get(search_url, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                results = []
                if isinstance(data, dict):
                    results = data.get("data", {}).get("results", []) or data.get("results", [])
                elif isinstance(data, list):
                    results = data

                if isinstance(results, list):
                    for song in results:
                        audio_link = extract_jiosaavn_audio_link(song)
                        title = song.get("name", song.get("song", song.get("title", "Unknown Title"))).replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")
                        artists_field = song.get("artists", {})
                        artist = "JioSaavn Artist"
                        if isinstance(artists_field, dict):
                            primary = artists_field.get("primary", [])
                            if primary and isinstance(primary, list) and isinstance(primary[0], dict):
                                artist = primary[0].get("name", "JioSaavn Artist")
                        elif isinstance(song.get("singers"), str):
                            artist = song.get("singers")
                        
                        songs_list.append({"status": True, "title": title, "artist": artist, "audio_link": audio_link or title})
                    if songs_list: return songs_list
        except Exception: pass

    return songs_list if songs_list else [{"status": False}]

def get_readable_time(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    return f"{int(d)}d {int(h)}h {int(m)}m {int(s)}s"

def get_audio_file(video=False):
    if video:
        for name in ["52.mp4", "51.mp4", "video.mp4"]:
            if os.path.exists(name): return name
    else:
        for name in ["51.mp3", "51.mp4", "51.ogg", "1.mp3"]:
            if os.path.exists(name): return name
    return None

def get_safe_video_quality():
    if not HAS_PYTGCALLS: return None
    try:
        for attr in ['HD_720P', 'HD', '720p', 'SD_480P', 'SD']:
            if hasattr(VideoQuality, attr):
                return getattr(VideoQuality, attr)
    except Exception: pass
    return None

async def get_call_py_for_client(client: TelegramClient):
    if not HAS_PYTGCALLS: return None
    try:
        me = await client.get_me()
        cid = me.id
        if cid not in call_py_instances:
            cp = PyTgCalls(client)
            if hasattr(cp, "on_stream_end"):
                @cp.on_stream_end()
                async def on_stream_end_handler(c, update):
                    chat_id = getattr(update, "chat_id", None)
                    if not chat_id: return
                    st = jio_playlist_state.get(chat_id)
                    if st and st.get("active"):
                        idx = st["index"] % len(st["songs"])
                        song = st["songs"][idx]
                        st["index"] += 1
                        fname = f"playlist_{chat_id}_{int(time.time())}.mp3"
                        try:
                            dl_res = await asyncio.to_thread(download_full_audio, song.get("audio_link") or song.get("title"), fname)
                            actual_file = dl_res.get("file_path", fname) if dl_res and dl_res.get("status") else fname
                            await cp.play(chat_id, MediaStream(actual_file, audio_parameters=AudioQuality.HIGH))
                        except Exception as ex: logger.error(f"Auto-loop stream end error: {ex}")
                    else:
                        media_file = get_audio_file()
                        if media_file:
                            try: await cp.play(chat_id, MediaStream(media_file, audio_parameters=AudioQuality.HIGH))
                            except Exception: pass
            await cp.start()
            call_py_instances[cid] = cp
        return call_py_instances[cid]
    except Exception as e:
        logger.error(f"Error getting PyTgCalls for client: {e}")
        return None

async def safe_leave_call(cp, chat_id):
    if not cp: return
    try:
        if hasattr(cp, "leave_call"):
            await cp.leave_call(chat_id)
        elif hasattr(cp, "leave_group_call"):
            await cp.leave_group_call(chat_id)
    except Exception: pass

async def join_vc_and_play(chat_id, event, video=False, custom_file=None):
    client = event.client
    media_file = custom_file or get_audio_file(video=video)
    if not media_file or not os.path.exists(media_file):
        return False, "❌ Audio/Video file (51.mp3 / 52.mp4) working directory me nahi mili!"

    cp = await get_call_py_for_client(client)
    if cp:
        await safe_leave_call(cp, chat_id)
        await asyncio.sleep(0.5)

        try:
            if video:
                vq = get_safe_video_quality()
                if vq:
                    stream = MediaStream(
                        media_file,
                        audio_parameters=AudioQuality.HIGH,
                        video_parameters=vq
                    )
                else:
                    stream = MediaStream(
                        media_file,
                        audio_parameters=AudioQuality.HIGH
                    )
                msg_txt = f"📺 <b>Screen Share Video & Voice Live!</b>\nStreaming: <code>{media_file}</code>"
            else:
                stream = MediaStream(
                    media_file,
                    audio_parameters=AudioQuality.HIGH
                )
                msg_txt = f"🔊 <b>Voice Call Audio Live!</b>\nPlaying: <code>{media_file}</code>"

            await cp.play(chat_id, stream)

            try:
                chat = await client.get_entity(chat_id)
                full_chat = await client(functions.channels.GetFullChannelRequest(chat))
                call = full_chat.full_chat.call
                if call:
                    await client(EditGroupCallParticipantRequest(
                        call=call,
                        participant=await client.get_me(),
                        muted=False
                    ))
            except Exception: pass

            return True, msg_txt

        except Exception as e:
            err_str = str(e)
            if "GROUPCALL_NOT_FOUND" in err_str or "GroupCallNotFound" in err_str:
                return False, "⚠️ <b>Group/Chat me Voice Chat active nahi hai!</b>\n👉 Pehle Call start karein, phir command chalayein."
            return False, f"❌ PyTgCalls Stream Error: {err_str}"
    else:
        return False, "❌ PyTgCalls engine run nahi ho raha."

# ==============================================================================
# TELETHON USERBOT ENGINE
# ==============================================================================
async def memory_monitor():
    while True:
        await asyncio.sleep(45)
        try:
            import gc
            gc.collect()
        except Exception:
            pass

async def safe_run_telethon_client(client: TelegramClient, uid: str, name: str = ""):
    display_name = name or uid
    while True:
        try:
            if not client.is_connected():
                await client.connect()
            await client.run_until_disconnected()
            break
        except asyncio.CancelledError:
            break
        except Exception as e:
            add_log(f"⚠️ Userbot '{display_name}' network drop ({e}). Auto-reconnecting in 4s...")
            await asyncio.sleep(4)

def setup_userbot_handlers(client: TelegramClient, phone_key: str, admin_id_val: str, me_id: int):
    @client.on(events.NewMessage)
    async def global_message_listener(event):
        if not event.sender_id: return
        # Ignore messages older than startup time to prevent startup message flood
        if hasattr(event, 'date') and event.date and event.date.timestamp() < (START_TIME - 15):
            return

        is_muted = await execute_db_query("SELECT user_id FROM muted_users WHERE user_id=?", (event.sender_id,), fetchone=True)
        if is_muted:
            try: 
                await event.delete()
                return
            except Exception: pass

        if event.text and not event.text.startswith(PREFIX) and not event.text.startswith(BOT_PREFIX):
            trig = event.text.strip().lower()
            row = await execute_db_query("SELECT response FROM filters WHERE chat_id=? AND trigger=?", (event.chat_id, trig), fetchone=True)
            if row:
                if should_process_tg_command(event.chat_id, event.id, f"filter_{trig}"):
                    try: await event.reply(row[0])
                    except Exception: pass

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(start|alive|hello|hi|king)$'))
    async def ub_start_cmd(event):
        if hasattr(event, 'date') and event.date and event.date.timestamp() < (START_TIME - 15): return
        if not await is_ub_admin(event, me_id, admin_id_val): return
        if not should_process_tg_command(event.chat_id, event.id, "start"): return

        uptime = get_readable_time(time.time() - START_TIME)
        me = await event.client.get_me()
        user_name = me.first_name or "King Userbot"
        user_phone = f"+{me.phone}" if me.phone else "Linked Account"

        start_caption = f"""╔══════════════════════════════════════════╗
║  👑 ⚡ <b>𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽18.0 ⚡ 👑</b>  ║
║  🛡️ <b>𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 • 𝑴𝑨𝑺𝑻𝑬𝑹 𝑴𝑨𝑻𝑹𝑰𝑿</b> 🛡️  ║
╚══════════════════════════════════════════╝
  ✨ <b>PREFIX</b> : [  <code>{PREFIX}</code>  ]  •  🚀 <b>SPEED</b> : <code>0.01s+ (10ms)</code>

🤖 <b>Userbot Node:</b> <code>{user_name}</code>
📱 <b>Linked Account:</b> <code>{user_phone}</code>
👑 <b>Master ID:</b> <code>{admin_id_val or MASTER_ADMIN_DEFAULT}</code>
⏱️ <b>Uptime:</b> <code>{uptime}</code>
🔥 <b>Engine:</b> <code>Telethon + PyTgCalls Ultra Turbo</code>

╭──────────────────────────────╮
│ 💡 <b>QUICK ACTIONS & NAVIGATION</b>
│ • Type <code>{PREFIX}menu</code> for Interactive Selector
│ • Type <code>{PREFIX}menu 1</code> for 👑 Ultra Raid Dashboard
│ • Type <code>{PREFIX}menu 2</code> for 📞 VoIP Caller Engine
│ • Type <code>{PREFIX}menu 3</code> for 🎵 Music & Song Engine
│ • Type <code>{PREFIX}ping</code> to test latency
╰──────────────────────────────╯"""

        main_pic = "main.png"
        if os.path.exists(main_pic):
            try:
                await event.reply(start_caption, file=main_pic, parse_mode="html")
                return
            except Exception: pass

        await event.reply(start_caption, parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(menu|help|dashboard)(?:\s+(.+))?$'))
    async def ub_menu_cmd(event):
        if hasattr(event, 'date') and event.date and event.date.timestamp() < (START_TIME - 15): return
        if not await is_ub_admin(event, me_id, admin_id_val): return
        if not should_process_tg_command(event.chat_id, event.id, "menu"): return

        sub = (event.pattern_match.group(2) or "").strip().lower()

        if sub in ["1", "ultra", "raid"]:
            menu_text = f"""╭──────────────────────────────╮
│ 👑 <b>𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽18.0 ⚡</b> │
│ 🛡️ <b>𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b>     │
╰──────────────────────────────╯
      ⚡ <b>PREFIX</b>  :  <code>{PREFIX}</code>
      🚀 <b>SPEED</b>   : <code>0.01s+</code>

╭─ 🎯 <b>𝑻𝑨𝑹𝑮𝑬𝑻 & 𝑹𝑨𝑰𝑫</b>
│ 🎯 <code>{PREFIX}target @user &lt;msg&gt;</code>
│ 🛑 <code>{PREFIX}stoptarget @user</code>
│ 🧹 <code>{PREFIX}cleartargets</code>
│ 📋 <code>{PREFIX}targets</code>
│ ⏱️ <code>{PREFIX}targetdelay &lt;0.01-20&gt;</code>
│ 💀 <code>{PREFIX}raid &lt;count&gt; @user</code>
╰──────────────────────

╭─ 📌 <b>𝑷𝑰𝑵 𝑺𝑷𝑨𝑴</b>
│ 📌 <code>{PREFIX}pin</code>
│ 📌 <code>{PREFIX}unpin</code>
│ ⚡ <code>{PREFIX}pinspam &lt;count&gt; &lt;delay&gt;</code>
│ 🛑 <code>{PREFIX}pinspam off</code>
╰──────────────────────

╭─ 🚀 𝑭𝑳𝑶𝑶𝑫 & 𝑺𝑷𝑨𝑴
│ 🚀 <code>{PREFIX}spam &lt;Text&gt;</code>
│ ⏱️ <code>{PREFIX}spamdelay &lt;0.01-20&gt;</code>
│ 🛑 <code>{PREFIX}stopspam</code>
│ 🚨 <code>{PREFIX}dynamicstop</code>
╰──────────────────────

╭─ 🛡️ 𝑴𝑶𝑫𝑬𝑹𝑨𝑻𝑰𝑶𝑵
│ ⚠️ <code>{PREFIX}warn</code> | <code>{PREFIX}purge &lt;count&gt;</code>
│ 🧹 <code>{PREFIX}kick @user</code> | <code>{PREFIX}ban @user</code>
│ 👑 <code>{PREFIX}promote @user</code> | <code>{PREFIX}demote @user</code>
│ 📢 <code>{PREFIX}tagall &lt;Text&gt;</code>
│ 🔇 <code>{PREFIX}mute</code> | <code>{PREFIX}unmute</code>
╰──────────────────────

╭─ ⚙️ 𝑮𝑹𝑶𝑼𝑷 𝑼𝑻𝑰𝑳𝑰𝑻𝒀
│ ➕ <code>{PREFIX}addmember &lt;@user&gt;</code>
│ 🚪 <code>{PREFIX}join &lt;link&gt;</code> | <code>{PREFIX}leave</code>
│ 🤖 <code>{PREFIX}creategc &lt;user1&gt; &lt;user2&gt;</code>
│ ⚡ <code>{PREFIX}ping</code> | <code>{PREFIX}status</code>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ <b>𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b> ⚡ │
╰──────────────────────────────╯"""
            return await event.reply(menu_text, parse_mode="html")

        if sub in ["2", "call", "voip"]:
            call_menu = f"""╭─────────────────────────╮
📞 <b>𝙑𝙊𝙄𝙋 𝘾𝘼𝙇𝙇𝙄𝙉𝙂 𝙀𝙉𝙂𝙄𝙉𝙀</b> 📞
╰─────────────────────────╯
⚡ <b>𝙊𝙐𝙏𝘽𝙊𝙐𝙉𝘿 𝙏𝙀𝙇𝙀𝙂𝙍𝘼𝙈 𝘾𝘼𝙇𝙇𝙀𝙍</b>

│
├─► 🔊 <code>{PREFIX}play1call</code> / <code>{PREFIX}playcall</code>
│    ▸ <i>Stream 51.mp3 in continuous 5s loop in VC/DM</i>
│
├─► 🎶 <code>{PREFIX}playjiocall &lt;song name&gt;</code>
│    ▸ <i>Search JioSaavn & stream live in Call (5s loop)</i>
│
├─► 📺 <code>{PREFIX}play2call</code>
│    ▸ <i>Stream 52.mp4 screen share video (720p HD)</i>
│
├─► 📻 <code>{PREFIX}play4jiocallchangeall &lt;genre&gt;</code>
│    ▸ <i>Category playlist auto-player loop</i>
│
├─► 🔓 <code>{PREFIX}autounmute</code> / <code>{PREFIX}loopunmute</code>
│    ▸ <i>Auto unmute sentinel (never stay muted)</i>
│
├─► ⏹️ <code>{PREFIX}stopcallplay</code>
│    ▸ <i>Pause / Stop active voice stream</i>
│
└─► 🔌 <code>{PREFIX}cutcall</code> / <code>{PREFIX}leavecall</code>
     ▸ <i>Leave voice chat / call immediately</i>

╭─────────────────────────╮
भिड़ मत, तेरी माँ चोदूँगा।
╰─────────────────────────╯"""
            return await event.reply(call_menu, parse_mode="html")

        if sub in ["3", "song", "music"]:
            song_menu = f"""╭──────────────────────────────╮
│ 🎵 <b>𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬</b> 🎶   │
│ 🛡️ <b>𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b>     │
╰──────────────────────────────╯
      ⚡ <b>PREFIX</b>  :  <code>{PREFIX}</code>
      🎧 <b>ENGINES</b> : JioSaavn • Spotify • PyTgCalls

╭─ 🎵 <b>𝑱𝑰𝑶𝑺𝑨𝑨𝑽𝑵 𝑴𝑼𝑺𝑰𝑪</b>
│ 🎵 <code>{PREFIX}song &lt;Song Name&gt;</code>
│    ▸ Full 320kbps HD audio track
│ 🔊 <code>{PREFIX}playjiocall &lt;Song Name&gt;</code>
│    ▸ Stream song live in Voice Call Loop (5s gap)
│ 📻 <code>{PREFIX}play4jiocallchangeall &lt;genre&gt;</code>
│    ▸ Continuous genre auto-playlist
╰──────────────────────

╭─ 📻 <b>𝑪𝑨𝑳𝑳 𝑨𝑼𝑫𝑰𝑶 𝑺𝑻𝑹𝑬𝑨𝑴𝑬𝑹</b>
│ 🔊 <code>{PREFIX}play1call</code>
│    ▸ Play 51.mp3 in continuous 5s loop on call
│ ⏹️ <code>{PREFIX}stopcallplay</code>
│    ▸ Stop stream playback
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ <b>𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b> ⚡ │
╰──────────────────────────────╯"""
            return await event.reply(song_menu, parse_mode="html")

        portal_text = f"""╭──────────────────────────────╮
│ 👑 <b>𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑴𝑬𝑵𝑼 𝑷𝑶𝑹𝑻𝑨𝑳</b> ⚡ │
│ 🛡️ <b>𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b>     │
╰──────────────────────────────╯
      ⚡ <b>PREFIX</b>  :  <code>{PREFIX}</code>
      🚀 <b>SPEED</b>   : <code>0.01s+</code>

<b>Please select a Dashboard by sending shortcut:</b>

1️⃣ <code>{PREFIX}menu 1</code> ➔ 👑 <b>𝑼𝑳𝑻𝑹𝑨 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫</b>
   <i>(Target • Pin Spam • Raid • Flood • Moderation • Utility)</i>

2️⃣ <code>{PREFIX}menu 2</code> ➔ 📞 <b>𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬</b>
   <i>(51.mp3 Loop • JioCall • 52.mp4 Video • Autounmute • VC Stream)</i>

3️⃣ <code>{PREFIX}menu 3</code> ➔ 🎵 <b>𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫</b>
   <i>(JioSaavn 320kbps • PyTgCalls Stream • Category Playlists)</i>

╭──────────────────────────────╮
│ ⚡ <b>𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵</b> ⚡ │
╰──────────────────────────────╯
👉 <i>Use <code>{PREFIX}menu 1</code>, <code>{PREFIX}menu 2</code>, or <code>{PREFIX}menu 3</code></i>"""
        await event.reply(portal_text, parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(play1call|playcall|startcall|joincall)$'))
    async def ub_playcall_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        chat_id = event.chat_id
        msg = await event.reply("🔄 <b>Connecting to Call & Launching 51.mp3 Continuous Loop (5s gap)...</b>", parse_mode="html")
        
        jio_playlist_state[chat_id] = {
            "active": True,
            "mode": "play1call"
        }
        
        media_file = get_audio_file(video=False)
        dur = get_file_duration(media_file) if media_file and os.path.exists(media_file) else 180

        async def play1call_loop():
            while jio_playlist_state.get(chat_id, {}).get("active") and jio_playlist_state.get(chat_id, {}).get("mode") == "play1call":
                try:
                    await join_vc_and_play(chat_id, event, video=False)
                    await asyncio.sleep(dur + 5)
                except Exception as e:
                    logger.error(f"play1call error: {e}")
                    await asyncio.sleep(5)

        asyncio.create_task(play1call_loop())
        await msg.edit(f"🔊 <b>51.mp3 Live in Continuous Loop!</b>\n⏱ Song Duration: <code>{int(dur)}s</code> + 5s gap\n_Use <code>{PREFIX}stopcallplay</code> or <code>{PREFIX}cutcall</code> to stop._", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?play2call$'))
    async def ub_play2call_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg = await event.reply("📺 <b>Connecting to Call & Injecting 52.mp4 Screen Share Video...</b>", parse_mode="html")
        success, resp_text = await join_vc_and_play(event.chat_id, event, video=True)
        await msg.edit(resp_text, parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(playjiocall|play3jio)\s+(.+)'))
    async def ub_playjiocall_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        query = event.pattern_match.group(2).strip()
        chat_id = event.chat_id
        msg = await event.reply(f"🔍 <b>Searching JioSaavn for <code>{query}</code> to stream on Call...</b>", parse_mode="html")

        me = await event.client.get_me()
        temp_filename = f"jio_call_{chat_id}_{me.id}_{int(time.time())}.mp3"

        try:
            dl_res = await asyncio.to_thread(download_full_audio, query, temp_filename)
            if not dl_res or not dl_res.get("status"):
                return await msg.edit("❌ Song not found on JioSaavn or download failed.")

            actual_file = dl_res.get("file_path", temp_filename)
            title = dl_res.get("title", query)
            artist = dl_res.get("artist", "")
            duration = dl_res.get("duration") or get_file_duration(actual_file) or 180

            jio_playlist_state[chat_id] = {
                "active": True,
                "mode": "playjiocall",
                "file": actual_file
            }

            await msg.edit(f"🔊 <b>Now Streaming on Call:</b> <code>{title}</code> by {artist}\n⏱ Duration: <code>{int(duration)}s</code> (Continuous 5s Loop)", parse_mode="html")

            async def jiocall_loop():
                while jio_playlist_state.get(chat_id, {}).get("active") and jio_playlist_state.get(chat_id, {}).get("mode") == "playjiocall":
                    try:
                        await join_vc_and_play(chat_id, event, video=False, custom_file=actual_file)
                        await asyncio.sleep(duration + 5)
                    except Exception as e:
                        logger.error(f"jiocall loop error: {e}")
                        await asyncio.sleep(5)
                if os.path.exists(actual_file):
                    try: os.remove(actual_file)
                    except Exception: pass

            asyncio.create_task(jiocall_loop())

        except Exception as e:
            await msg.edit(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?play4jiocallchangeall\s+(.+)'))
    async def ub_play4jio_playlist(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        genre = event.pattern_match.group(1).strip()
        chat_id = event.chat_id

        msg = await event.reply(f"📻 <b>Searching JioSaavn <code>{genre}</code> Category Playlist...</b>", parse_mode="html")
        songs = await asyncio.to_thread(search_multiple_jiosaavn, genre, 10)
        if not songs or not songs[0].get("status"):
            return await msg.edit(f"❌ No songs found for genre <code>{genre}</code>.")

        jio_playlist_state[chat_id] = {
            "active": True,
            "genre": genre,
            "songs": songs,
            "index": 0
        }

        async def play_next_in_playlist():
            st = jio_playlist_state.get(chat_id)
            if not st or not st["active"]: return

            idx = st["index"] % len(st["songs"])
            song = st["songs"][idx]
            st["index"] += 1

            fname = f"playlist_{chat_id}_{int(time.time())}.mp3"
            actual_file = fname
            try:
                dl_res = await asyncio.to_thread(download_full_audio, song.get("audio_link") or song.get("title"), fname)
                actual_file = dl_res.get("file_path", fname) if dl_res and dl_res.get("status") else fname

                if not os.path.exists(actual_file) or os.path.getsize(actual_file) < 50000:
                    await event.client.send_message(chat_id, f"⚠️ Could not download full audio for <code>{song.get('title')}</code>, skipping to next...", parse_mode="html")
                    await asyncio.sleep(2)
                    if jio_playlist_state.get(chat_id, {}).get("active"):
                        asyncio.create_task(play_next_in_playlist())
                    return

                track_title = dl_res.get("title", song.get("title"))
                track_artist = dl_res.get("artist", song.get("artist"))
                duration = dl_res.get("duration") or get_file_duration(actual_file)

                await event.client.send_message(
                    chat_id,
                    f"🎵 <b>Now Playing ({st['genre'].title()} Playlist #{idx+1}):</b> <code>{track_title}</code> by {track_artist}\n⏱ Full Duration: <code>{int(duration)}s</code>",
                    parse_mode="html"
                )

                await join_vc_and_play(chat_id, event, video=False, custom_file=actual_file)
                await asyncio.sleep(duration + 5)

                for fpath in [fname, actual_file]:
                    if os.path.exists(fpath):
                        try: os.remove(fpath)
                        except Exception: pass

                if jio_playlist_state.get(chat_id, {}).get("active"):
                    asyncio.create_task(play_next_in_playlist())

            except Exception as e:
                logger.error(f"Playlist loop error: {e}")
                for fpath in [fname, actual_file]:
                    if os.path.exists(fpath):
                        try: os.remove(fpath)
                        except Exception: pass

        asyncio.create_task(play_next_in_playlist())

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?stopjioplaylist$'))
    async def ub_stopjioplaylist(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        chat_id = event.chat_id
        if chat_id in jio_playlist_state:
            jio_playlist_state[chat_id]["active"] = False
        await event.reply("🛑 <b>Category Playlist Auto-Player Stopped.</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(stopcallplay|stopcall)$'))
    async def ub_stopcallplay(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg = await event.reply("⏸ <b>Stopping Voice/Video Stream...</b>", parse_mode="html")
        if event.chat_id in jio_playlist_state:
            jio_playlist_state[event.chat_id]["active"] = False
        try:
            cp = await get_call_py_for_client(event.client)
            if cp:
                await safe_leave_call(cp, event.chat_id)
            await msg.edit("🛑 <b>Audio/Video Stream Stopped.</b>", parse_mode="html")
        except Exception as e:
            await msg.edit(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(autounmute|loopunmute)$'))
    async def ub_loop_unmute_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        chat_id = event.chat_id
        vc_loop_unmute_active[chat_id] = not vc_loop_unmute_active.get(chat_id, False)
        status_text = "ENABLED (Auto-Unmutes if muted) 🟢" if vc_loop_unmute_active[chat_id] else "DISABLED 🔴"
        await event.reply(f"🔊 <b>Auto Unmute Sentinel:</b> <code>{status_text}</code>", parse_mode="html")
        
        if vc_loop_unmute_active[chat_id]:
            async def unmute_loop():
                cli = event.client
                while vc_loop_unmute_active.get(chat_id, False):
                    try:
                        chat = await cli.get_entity(chat_id)
                        full_chat = await cli(functions.channels.GetFullChannelRequest(chat))
                        call = full_chat.full_chat.call
                        if call:
                            await cli(EditGroupCallParticipantRequest(
                                call=call,
                                participant=await cli.get_me(),
                                muted=False
                            ))
                    except Exception: pass
                    await asyncio.sleep(2.5)

            asyncio.create_task(unmute_loop())

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(cutcall|leavecall)'))
    async def ub_cutcall(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg = await event.reply("🔌 <b>Leaving Call...</b>", parse_mode="html")
        vc_loop_unmute_active[event.chat_id] = False
        if event.chat_id in jio_playlist_state:
            jio_playlist_state[event.chat_id]["active"] = False
        try:
            cp = await get_call_py_for_client(event.client)
            if cp:
                await safe_leave_call(cp, event.chat_id)
            try:
                chat = await event.client.get_entity(event.chat_id)
                full_chat = await event.client(functions.channels.GetFullChannelRequest(chat))
                if full_chat.full_chat.call:
                    await event.client(LeaveGroupCallRequest(call=full_chat.full_chat.call))
            except Exception: pass
            await msg.edit("🛑 <b>Left Voice/Video Call Successfully.</b>", parse_mode="html")
        except Exception as e:
            await msg.edit(f"🛑 <b>Call Left:</b> {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(spamdelay|delay|speed)(?:\s+(\d+(?:\.\d+)?))?$'))
    async def ub_spam_delay(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        val_str = event.pattern_match.group(2)
        tasks = get_client_tasks(event.client)
        if val_str:
            tasks["spam_delay"] = max(0.01, float(val_str))
            await event.reply(f"⏱ <b>Spam Speed/Delay set to:</b> <code>{tasks['spam_delay']}s</code>", parse_mode="html")
        else:
            await event.reply(f"⏱ <b>Current Spam Delay:</b> <code>{tasks['spam_delay']}s</code>\nUsage: <code>{PREFIX}delay &lt;seconds&gt;</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(targetdelay|fuckdelay)(?:\s+(\d+(?:\.\d+)?))?$'))
    async def ub_target_delay(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        val_str = event.pattern_match.group(2)
        tasks = get_client_tasks(event.client)
        if val_str:
            tasks["fucktarget_delay"] = max(0.01, float(val_str))
            await event.reply(f"⏱ <b>Target Attack Delay set to:</b> <code>{tasks['fucktarget_delay']}s</code>", parse_mode="html")
        else:
            await event.reply(f"⏱ <b>Current Target Delay:</b> <code>{tasks['fucktarget_delay']}s</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?spam\s+(.+)$'))
    async def ub_start_spam(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg_text = event.pattern_match.group(1).strip()
        tasks = get_client_tasks(event.client)
        tasks["spam"] = True
        await event.reply("🚀 <b>Spam Loop Started!</b>", parse_mode="html")
        while tasks["spam"]:
            try: await event.client.send_message(event.chat_id, msg_text)
            except FloodWaitError as fwe: await asyncio.sleep(fwe.seconds)
            except Exception: break
            await asyncio.sleep(tasks["spam_delay"])

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(stopspam|spamstop|killspam)$'))
    async def ub_stop_spam(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        tasks = get_client_tasks(event.client)
        tasks["spam"] = False
        await event.reply("🛑 <b>Spam Stopped.</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(stopfucktarget|stoptarget|stoptargetspam|untarget|cleartargetloop)$'))
    async def ub_stop_fucktarget(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        tasks = get_client_tasks(event.client)
        tasks["fucktarget"] = False
        await event.reply("🛑 <b>Target Attack Loop Stopped.</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?(stop|stopall|killall|dynamicstop|halt|shutdown)$'))
    async def ub_stop_all_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        tasks = get_client_tasks(event.client)
        tasks["spam"] = False
        tasks["fucktarget"] = False
        vc_loop_unmute_active[event.chat_id] = False
        if event.chat_id in jio_playlist_state:
            jio_playlist_state[event.chat_id]["active"] = False
        try:
            cp = await get_call_py_for_client(event.client)
            if cp:
                await safe_leave_call(cp, event.chat_id)
        except Exception: pass
        await event.reply("🚨 <b>FORCE MASTER STOP: All active userbot spam, target loops, and VC streams halted!</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?raid\s+(\d+)\s+(@\w+)$'))
    async def ub_raid(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        count, target = int(event.pattern_match.group(1)), event.pattern_match.group(2)
        await event.reply(f"⚔️ <b>Raid started on {target} ({count} rounds)...</b>", parse_mode="html")
        for i in range(count):
            phrase = RAID_TEXTS[i % len(RAID_TEXTS)]
            await event.client.send_message(event.chat_id, f"{target} {phrase}")
            await asyncio.sleep(0.8)

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?targetadd$'))
    async def ub_target_add(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply: return await event.reply("⚠️ Reply to a user.")
        await execute_db_query("INSERT OR REPLACE INTO targets VALUES (?)", (reply.sender_id,), commit=True)
        await event.reply(f"🎯 Target <code>{reply.sender_id}</code> added.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?targetdel$'))
    async def ub_target_del(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply: return await event.reply("⚠️ Reply to a user.")
        await execute_db_query("DELETE FROM targets WHERE user_id=?", (reply.sender_id,), commit=True)
        await event.reply(f"🧹 Target <code>{reply.sender_id}</code> removed.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'(?i)^[+!\.\/\-\?\#\*\$\&\_]?{re.escape(PREFIX)}?fucktarget\s+(.+)$'))
    async def ub_fucktarget(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg_text = event.pattern_match.group(1).strip()
        tasks = get_client_tasks(event.client)
        tasks["fucktarget"] = True
        await event.reply("☣️ <b>Infinite Target Attack Loop Started!</b>", parse_mode="html")
        rows = await execute_db_query("SELECT user_id FROM targets", fetchall=True)
        targets = [r[0] for r in rows] if rows else []
        while tasks["fucktarget"] and targets:
            for t_id in targets:
                if not tasks["fucktarget"]: break
                try: await event.client.send_message(event.chat_id, f"[Target](tg://user?id={t_id}) {msg_text}")
                except Exception: pass
                await asyncio.sleep(tasks["fucktarget_delay"])

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}promote(?:\s+(.+))?'))
    async def ub_promote_user(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        args = event.pattern_match.group(1)
        target = args.strip().split()[0] if args else None
        if not target:
            reply = await event.get_reply_message()
            if reply: target = reply.sender_id
        if not target: return await event.reply("⚠️ Usage: <code>+promote @user</code>", parse_mode="html")

        rights = types.ChatAdminRights(
            change_info=False, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, add_admins=True, anonymous=False, manage_call=True
        )
        try:
            user_entity = await event.client.get_input_entity(target)
            await event.client(EditAdminRequest(channel=event.chat_id, user_id=user_entity, admin_rights=rights, rank="Admin"))
            await event.reply(f"👑 Promoted <code>{target}</code> to Admin!", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}ban(?:\s+(.+))?'))
    async def ub_ban_user(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        target = reply.sender_id if reply else event.pattern_match.group(1)
        if not target: return await event.reply("⚠️ Reply or specify user to ban.")
        try:
            await event.client(EditBannedRequest(event.chat_id, target, types.ChatBannedRights(until_date=None, view_messages=True)))
            await event.reply(f"🚫 Banned user <code>{target}</code>.", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}kick(?:\s+(.+))?'))
    async def ub_kick_user(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        target = reply.sender_id if reply else event.pattern_match.group(1)
        if not target: return await event.reply("⚠️ Reply or specify user to kick.")
        try:
            await event.client.kick_participant(event.chat_id, target)
            await event.reply(f"exe Kicked user <code>{target}</code>.", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(removeuserbot|deleteuserbot|logoutuserbot)'))
    async def ub_remove_userbot(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        me = await event.client.get_me()
        phone_to_del = phone_key
        await event.reply(f"🗑 <b>Removing Userbot <code>{me.first_name} (+{phone_to_del})</code> from system & database...</b>", parse_mode="html")

        # 1. Remove from SQLite & MongoDB
        await execute_db_query("DELETE FROM userbots WHERE phone=?", (phone_to_del,), commit=True)
        if mongo_db is not None:
            try: mongo_db.userbots.delete_many({"phone": phone_to_del})
            except Exception: pass

        # 2. Cleanup local caches
        telethon_clients.pop(phone_to_del, None)
        userbot_display_data.pop(phone_to_del, None)

        # 3. Disconnect
        try:
            await event.client.disconnect()
        except Exception: pass

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(promotadminbots|promoteadminbots|promotebots)'))
    async def ub_promote_admin_bots(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        status_msg = await event.reply("👑 <b>Scanning and promoting all linked Multi-Bots in this group...</b>", parse_mode="html")

        # Normal admin rights
        rights = types.ChatAdminRights(
            change_info=True,
            post_messages=True,
            edit_messages=True,
            delete_messages=True,
            ban_users=True,
            invite_users=True,
            pin_messages=True,
            add_admins=False,
            anonymous=False,
            manage_call=True,
            manage_topics=True
        )

        promoted_count = 0
        failed_count = 0

        # Collect bot usernames / IDs from managed_bots & token usernames
        bot_identifiers = set()
        rows = await execute_db_query("SELECT bot_id FROM managed_bots", fetchall=True)
        if rows:
            for r in rows:
                if r[0]: bot_identifiers.add(r[0].strip())
        for uname in bot_usernames.values():
            if uname: bot_identifiers.add(f"@{uname}" if not uname.startswith("@") else uname)

        if not bot_identifiers:
            return await status_msg.edit("⚠️ No linked Multi-Bots found. Add bots via <code>+addbot &lt;token&gt;</code> first!", parse_mode="html")

        for b_id in bot_identifiers:
            try:
                b_entity = await event.client.get_input_entity(b_id)
                await event.client(EditAdminRequest(channel=event.chat_id, user_id=b_entity, admin_rights=rights, rank="Admin Bot"))
                promoted_count += 1
                await asyncio.sleep(1.0)
            except Exception:
                failed_count += 1

        await status_msg.edit(f"👑 <b>Multi-Bot Promotion Finished:</b>\n• Successfully Promoted: <code>{promoted_count}</code> Admin Bots\n• Failed / Not in chat: <code>{failed_count}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}addmembers(?:\s+(\S+))?(?:\s+(\S+))?'))
    async def ub_add_members_mass(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        args1 = event.pattern_match.group(1)
        args2 = event.pattern_match.group(2)

        if not args1:
            return await event.reply("⚠️ Usage: <code>+addmembers @source_group</code> or <code>+addmembers @source_group @target_group</code>", parse_mode="html")

        source_peer = args1.strip()
        target_peer = args2.strip() if args2 else event.chat_id

        status_msg = await event.reply(f"🔍 <b>Scraping members from <code>{source_peer}</code> to add into target group...</b>", parse_mode="html")

        try:
            src_entity = await event.client.get_entity(source_peer)
            tgt_entity = await event.client.get_entity(target_peer)

            participants = await event.client.get_participants(src_entity, limit=200)
            candidates = [u for u in participants if not u.bot and not u.is_self]

            added, failed = 0, 0
            for u in candidates:
                try:
                    await event.client(InviteToChannelRequest(channel=tgt_entity, users=[u]))
                    added += 1
                    if added % 5 == 0:
                        await status_msg.edit(f"⏳ <b>Adding Members:</b> {added}/{len(candidates)} added (Failed: {failed})", parse_mode="html")
                    await asyncio.sleep(2.0)
                except FloodWaitError as fwe:
                    await status_msg.edit(f"⏳ FloodWait: sleeping {fwe.seconds}s...", parse_mode="html")
                    await asyncio.sleep(fwe.seconds)
                except Exception:
                    failed += 1
                    await asyncio.sleep(0.5)

            await status_msg.edit(f"✅ <b>Mass Member Addition Complete!</b>\n• Added: <code>{added}</code>\n• Failed / Restricted: <code>{failed}</code>\n• Total Scanned: <code>{len(candidates)}</code>", parse_mode="html")
        except Exception as e:
            await status_msg.edit(f"❌ Error adding members: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(setpfp|setprofilepic|changepfp)'))
    async def ub_set_pfp(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.photo:
            return await event.reply("⚠️ <b>Please reply to a PHOTO message with <code>+setpfp</code> to update your profile photo!</b>", parse_mode="html")

        status_msg = await event.reply("📸 <i>Downloading and setting new account profile picture...</i>", parse_mode="html")
        temp_photo_path = None
        try:
            temp_photo_path = await event.client.download_media(reply.photo)
            if temp_photo_path and os.path.exists(temp_photo_path):
                uploaded = await event.client.upload_file(temp_photo_path)
                await event.client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
                await status_msg.edit("✅ <b>Account Profile Photo updated successfully!</b>", parse_mode="html")
            else:
                await status_msg.edit("❌ Failed to download photo media.", parse_mode="html")
        except Exception as e:
            await status_msg.edit(f"❌ Error setting profile photo: {e}", parse_mode="html")
        finally:
            if temp_photo_path and os.path.exists(temp_photo_path):
                try: os.remove(temp_photo_path)
                except Exception: pass

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(changegroupphoto|setgroupphoto|setgrouppic)'))
    async def ub_change_group_photo(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.photo:
            return await event.reply("⚠️ <b>Please reply to a PHOTO message with <code>+changegroupphoto</code> to update group photo!</b>", parse_mode="html")

        status_msg = await event.reply("🖼️ <i>Downloading and updating group chat photo...</i>", parse_mode="html")
        temp_photo_path = None
        try:
            temp_photo_path = await event.client.download_media(reply.photo)
            if temp_photo_path and os.path.exists(temp_photo_path):
                uploaded = await event.client.upload_file(temp_photo_path)
                await event.client(functions.channels.EditPhotoRequest(channel=event.chat_id, photo=types.InputChatUploadedPhoto(file=uploaded)))
                await status_msg.edit("✅ <b>Group Chat Photo updated successfully!</b>", parse_mode="html")
            else:
                await status_msg.edit("❌ Failed to download photo media.", parse_mode="html")
        except Exception as e:
            try:
                if temp_photo_path and os.path.exists(temp_photo_path):
                    uploaded = await event.client.upload_file(temp_photo_path)
                    await event.client(functions.messages.EditChatPhotoRequest(chat_id=event.chat_id, photo=types.InputChatUploadedPhoto(file=uploaded)))
                    await status_msg.edit("✅ <b>Group Chat Photo updated successfully!</b>", parse_mode="html")
                else:
                    await status_msg.edit(f"❌ Error: {e}", parse_mode="html")
            except Exception as e2:
                await status_msg.edit(f"❌ Error updating group photo: {e2}", parse_mode="html")
        finally:
            if temp_photo_path and os.path.exists(temp_photo_path):
                try: os.remove(temp_photo_path)
                except Exception: pass

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}addmember (.+)'))
    async def ub_addmember(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        targets_raw = event.pattern_match.group(1).split()
        msg = await event.reply(f"⏳ Adding {len(targets_raw)} member(s)...")
        added, failed = 0, 0
        for target in targets_raw:
            try:
                await event.client(InviteToChannelRequest(channel=event.chat_id, users=[target]))
                added += 1
                await asyncio.sleep(1.2)
            except Exception: failed += 1
        await msg.edit(f"✅ Added: {added} | Failed: {failed}")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}invite (.+)'))
    async def ub_invite(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        user = event.pattern_match.group(1).strip()
        try:
            await event.client(InviteToChannelRequest(channel=event.chat_id, users=[user]))
            await event.reply(f"✅ Invited <code>{user}</code>.", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}warn'))
    async def ub_warn(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply: return await event.reply("⚠️ Reply to a user.")
        tid = reply.sender_id
        row = await execute_db_query("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (event.chat_id, tid), fetchone=True)
        count = (row[0] + 1) if row else 1
        await execute_db_query("INSERT OR REPLACE INTO warnings VALUES (?, ?, ?)", (event.chat_id, tid, count), commit=True)
        if count >= 3:
            try:
                await event.client(EditBannedRequest(event.chat_id, tid, types.ChatBannedRights(until_date=None, view_messages=True)))
                await event.reply("🚨 User reached 3/3 warnings and was BANNED!")
            except Exception as e: await event.reply(f"⚠️ Failed to ban: {e}")
        else: await event.reply(f"⚠️ User Warned ({count}/3).")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}purge (\d+)'))
    async def ub_purge(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        count = int(event.pattern_match.group(1))
        msgs = [m async for m in event.client.iter_messages(event.chat_id, limit=count+1)]
        await event.client.delete_messages(event.chat_id, msgs)

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}del'))
    async def ub_del(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if reply:
            await reply.delete()
            await event.delete()

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}tagall(?:\s+(.+))?'))
    async def ub_tagall(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg_text = event.pattern_match.group(1) or "Attention Everyone!"
        mentions = ""
        async for user in event.client.iter_participants(event.chat_id):
            if not user.bot:
                mentions += f"<a href='tg://user?id={user.id}'>\u200b</a>"
        await event.reply(f"📢 <b>{msg_text}</b>{mentions}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}mute'))
    async def ub_mute_user(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.sender_id: return await event.reply("⚠️ Reply to a user.")
        await execute_db_query("INSERT OR REPLACE INTO muted_users VALUES (?)", (reply.sender_id,), commit=True)
        await event.reply(f"🤐 User <code>{reply.sender_id}</code> muted.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}unmute'))
    async def ub_unmute_user(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.sender_id: return await event.reply("⚠️ Reply to a user.")
        await execute_db_query("DELETE FROM muted_users WHERE user_id=?", (reply.sender_id,), commit=True)
        await event.reply(f"🔊 User <code>{reply.sender_id}</code> unmuted.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}lock (media|links|stickers)'))
    async def ub_lock_cmd(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        l_type = event.pattern_match.group(1)
        rights = types.ChatBannedRights(until_date=None)
        if l_type == 'media': rights.send_media = True
        elif l_type == 'stickers': rights.send_stickers = True
        elif l_type == 'links': rights.embed_link_previews = True
        try:
            await event.client(functions.messages.EditChatDefaultBannedRightsRequest(peer=event.chat_id, banned_rights=rights))
            await event.reply(f"🔒 Locked <code>{l_type}</code> permissions.", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}creategcqty (\d+)'))
    async def ub_creategcqty(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        qty = int(event.pattern_match.group(1))
        await execute_db_query("INSERT OR REPLACE INTO gc_creation_settings VALUES (?, ?)", (event.sender_id, qty), commit=True)
        await event.reply(f"✅ Group Quantity set to <code>{qty}</code>.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}creategc (.+)'))
    async def ub_creategc(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        users_raw = event.pattern_match.group(1).split()
        row = await execute_db_query("SELECT qty FROM gc_creation_settings WHERE user_id=?", (event.sender_id,), fetchone=True)
        qty = row[0] if row else 1
        msg = await event.reply(f"⚙️ Creating {qty} groups...")
        created = 0
        for i in range(qty):
            try:
                await event.client(CreateChatRequest(users=users_raw, title=f"Server God Clan GC #{i+1}"))
                created += 1
                await asyncio.sleep(2.0)
            except Exception as e:
                await event.reply(f"⚠️ Failed GC #{i+1}: {e}")
                break
        await msg.edit(f"🎉 Created {created}/{qty} groups!")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}fetchallgc'))
    async def ub_fetchallgc(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg = await event.reply("🔍 Scanning connected groups...")
        count = sum(1 async for dialog in event.client.iter_dialogs() if dialog.is_group)
        await msg.edit(f"📡 Connected Groups Scanned: <code>{count}</code> Groups.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}targetgc (\d+)'))
    async def ub_targetgc(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        cid = int(event.pattern_match.group(1))
        await execute_db_query("INSERT OR REPLACE INTO target_groups VALUES (?)", (cid,), commit=True)
        await event.reply(f"🎯 Group <code>{cid}</code> targeted.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}cleartargets'))
    async def ub_cleartargets(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        await execute_db_query("DELETE FROM target_groups", commit=True)
        await event.reply("🧹 All Target Group IDs cleared.")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}sendmessage (.+)'))
    async def ub_sendmessage(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        text = event.pattern_match.group(1).strip()
        rows = await execute_db_query("SELECT chat_id FROM target_groups", fetchall=True)
        chats = [r[0] for r in rows] if rows else []
        if not chats: return await event.reply("⚠️ No target groups set.")
        sent = 0
        for cid in chats:
            try:
                await event.client.send_message(cid, text)
                sent += 1
                await asyncio.sleep(1.0)
            except Exception: pass
        await event.reply(f"📢 Mass Blast Complete: {sent}/{len(chats)} groups.")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}welcome (.+)'))
    async def ub_welcome(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        text = event.pattern_match.group(1).strip()
        await execute_db_query("INSERT OR REPLACE INTO welcome_settings (chat_id, welcome_text) VALUES (?, ?)", (event.chat_id, text), commit=True)
        await event.reply("✅ Welcome message set.")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}setgoodbye (.+)'))
    async def ub_setgoodbye(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        text = event.pattern_match.group(1).strip()
        await execute_db_query("INSERT OR REPLACE INTO welcome_settings (chat_id, goodbye_text) VALUES (?, ?)", (event.chat_id, text), commit=True)
        await event.reply("✅ Goodbye message set.")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}filter (\S+) (.+)'))
    async def ub_filter(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        trig, resp = event.pattern_match.group(1).lower(), event.pattern_match.group(2)
        await execute_db_query("INSERT OR REPLACE INTO filters VALUES (?, ?, ?)", (event.chat_id, trig, resp), commit=True)
        await event.reply(f"✅ Filter added for <code>{trig}</code>.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}stopfilter (\S+)'))
    async def ub_stopfilter(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        trig = event.pattern_match.group(1).lower()
        await execute_db_query("DELETE FROM filters WHERE chat_id=? AND trigger=?", (event.chat_id, trig), commit=True)
        await event.reply(f"🧹 Filter <code>{trig}</code> removed.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(song|music) (.+)'))
    async def ub_song_handler(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        query = event.pattern_match.group(2).strip()
        msg = await event.reply(f"🔍 Searching & downloading full JioSaavn audio for <code>{query}</code>...", parse_mode="html")
        
        me = await event.client.get_me()
        temp_filename = f"song_{event.chat_id}_{me.id}_{int(time.time())}.mp3"
        actual_file = temp_filename
        try:
            dl_res = await asyncio.to_thread(download_full_audio, query, temp_filename)
            if not dl_res or not dl_res.get("status"):
                return await msg.edit("❌ Song not found on JioSaavn or download failed. Please try another song title.")

            actual_file = dl_res.get("file_path", temp_filename)
            title = dl_res.get("title", query)
            artist = dl_res.get("artist", "JioSaavn Artist")
            duration = int(dl_res.get("duration", 0))

            await msg.edit(f"🚀 Uploading full audio (<code>{title}</code>)...", parse_mode="html")
            await event.client.send_file(
                event.chat_id,
                actual_file,
                caption=f"🎵 <b>{title}</b>\n👤 <b>Artist:</b> {artist}",
                attributes=[types.DocumentAttributeAudio(duration=duration, title=title, performer=artist)],
                parse_mode="html"
            )
            await msg.delete()
        except Exception as e:
            logger.error(f"Song upload error: {e}")
            await msg.edit(f"❌ Audio sending failed: {e}")
        finally:
            for fpath in [temp_filename, actual_file]:
                if os.path.exists(fpath):
                    try: os.remove(fpath)
                    except Exception: pass

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}ai (.+)'))
    async def ub_ai_handler(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        prompt = event.pattern_match.group(1).strip()
        msg = await event.reply("🧠 <b>Server God AI processing...</b>", parse_mode="html")
        ans = await asyncio.to_thread(query_unlimited_ai, prompt)
        await msg.edit(f"🤖 <b>[ Server God AI ]</b>\n\n{ans}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}q'))
    async def ub_quote_handler(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.text:
            return await event.reply("⚠️ Reply to a text message to create a quote card.")
        
        sender = await reply.get_sender()
        sender_name = sender.first_name if sender else "User"
        quote_text = reply.text[:120]
        
        width, height = 750, 250
        img = Image.new('RGB', (width, height), color=(20, 24, 38))
        draw = ImageDraw.Draw(img)
        
        try:
            font_title = ImageFont.truetype("arial.ttf", 26)
            font_body = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font_title = ImageFont.load_default()
            font_body = ImageFont.load_default()

        draw.rectangle([15, 15, width - 15, height - 15], outline=(0, 150, 255), width=3)
        draw.text((40, 35), f"👤 {sender_name}", fill=(0, 200, 255), font=font_title)
        draw.text((40, 95), f'"{quote_text}"', fill=(240, 240, 240), font=font_body)

        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)
        img_io.name = "quote_card.png"
        await event.client.send_file(event.chat_id, img_io, reply_to=reply.id)

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}font (.+)'))
    async def ub_font_handler(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        text = event.pattern_match.group(1).strip()[:35]
        width, height = 1200, 400
        img = Image.new('RGB', (width, height), color=(8, 10, 20))
        draw = ImageDraw.Draw(img)
        font_size = max(30, 80 - len(text) * 2)
        try: font = ImageFont.truetype("arial.ttf", font_size)
        except Exception: font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x, y = (width - text_w) // 2, (height - text_h) // 2

        for offset in range(15, 0, -1):
            draw.text((x + offset, y + offset), text, font=font, fill=(0, 120 + (offset * 8), 255))
            draw.text((x - offset, y - offset), text, font=font, fill=(150, 0, 255))

        draw.text((x, y), text, font=font, fill=(255, 255, 255))
        draw.rectangle([20, 20, width - 20, height - 20], outline=(0, 200, 255), width=4)
        
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)
        img_io.name = "banner.png"
        await event.client.send_file(event.chat_id, img_io, caption=f"✨ <b>Banner Generated:</b> <code>{text}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}pdf'))
    async def ub_pdf(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        if not reply or not reply.photo: return await event.reply("⚠️ Reply to an image.")
        photo_bytes = await reply.download_media(file=io.BytesIO())
        img = Image.open(photo_bytes).convert('RGB')
        pdf_io = io.BytesIO()
        img.save(pdf_io, format='PDF')
        pdf_io.seek(0)
        pdf_io.name = "converted.pdf"
        await event.client.send_file(event.chat_id, pdf_io)

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}3dpic (.+)'))
    async def ub_3dpic(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        prompt = event.pattern_match.group(1).strip()
        url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt + ' 3d render cinematic unreal engine 5')}"
        res = await asyncio.to_thread(requests.get, url, timeout=20)
        img_io = io.BytesIO(res.content)
        img_io.name = "3d_render.png"
        await event.client.send_file(event.chat_id, img_io, caption=f"✨ <code>{prompt}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}tts (.+)'))
    async def ub_tts(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        text = event.pattern_match.group(1).strip()
        fname = f"tts_{int(time.time())}.mp3"
        try:
            gTTS(text, lang="en").save(fname)
            await event.client.send_file(event.chat_id, fname, voice_note=True)
        finally:
            if os.path.exists(fname): os.remove(fname)

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}tr (\w+) (.+)'))
    async def ub_tr(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        lang, text = event.pattern_match.group(1), event.pattern_match.group(2)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={lang}&dt=t&q={requests.utils.quote(text)}"
        res = (await asyncio.to_thread(requests.get, url, timeout=10)).json()
        await event.reply(f"🌐 <b>Translation ({lang}):</b>\n<code>{res[0][0][0]}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}remind (\d+)([smh]) (.+)'))
    async def ub_remind(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        val, unit, text = int(event.pattern_match.group(1)), event.pattern_match.group(2), event.pattern_match.group(3)
        sec = val * (60 if unit == 'm' else 3600 if unit == 'h' else 1)
        await event.reply(f"⏰ Reminder set for {val}{unit}.")
        async def rem_task():
            await asyncio.sleep(sec)
            await event.reply(f"🔔 <b>REMINDER</b>: {text}")
        asyncio.create_task(rem_task())

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}calc (.+)'))
    async def ub_calc(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        try:
            res = eval(event.pattern_match.group(1), {"__builtins__": None}, {"math": math})
            await event.reply(f"🧮 <b>Result:</b> <code>{res}</code>", parse_mode="html")
        except Exception as e: await event.reply(f"❌ Error: {e}")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}weather (.+)'))
    async def ub_weather(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        city = event.pattern_match.group(1)
        res = await asyncio.to_thread(requests.get, f"https://wttr.in/{city}?format=3", timeout=10)
        await event.reply(f"🌤 <b>Weather</b>: <code>{res.text.strip()}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(info|whois)'))
    async def ub_info(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reply = await event.get_reply_message()
        user = await reply.get_sender() if reply else await event.get_sender()
        photos = await event.client.get_profile_photos(user.id)
        await event.reply(f"👤 <b>User Info</b>:\n• Name: {user.first_name}\n• ID: <code>{user.id}</code>\n• Username: @{user.username if user.username else 'None'}\n• Photos: {photos.total}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}chatstats'))
    async def ub_chatstats(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        msg = await event.reply("📊 Gathering chat metrics...")
        total, media = 0, 0
        async for m in event.client.iter_messages(event.chat_id, limit=1000):
            total += 1
            if m.media: media += 1
        await msg.edit(f"📈 <b>Stats</b>: Total <code>{total}</code>, Media <code>{media}</code>, Text <code>{total-media}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}sysinfo'))
    async def ub_sysinfo(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        uptime = get_readable_time(time.time() - START_TIME)
        py_ver = sys.version.split()[0]
        info_text = (
            f"💻 <b>SERVER GOD CLAN SYSTEM MATRIX</b> 💻\n\n"
            f"👑 <b>Master Admin:</b> <code>{admin_id_val or MASTER_ADMIN_DEFAULT}</code>\n"
            f"⏱ <b>System Uptime:</b> <code>{uptime}</code>\n"
            f"🐍 <b>Python:</b> <code>{py_ver}</code>\n"
            f"⚡ <b>PyTgCalls Video Engine:</b> <code>{'Online (HD 720p)' if HAS_PYTGCALLS else 'Disabled'}</code>\n"
            f"📡 <b>Database:</b> <code>MongoDB Atlas + SQLite WAL</code>"
        )
        await event.reply(info_text, parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}afk (.*)'))
    async def ub_afk(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        reason = event.pattern_match.group(1).strip() or "Away from keyboard"
        await execute_db_query("INSERT OR REPLACE INTO afk_state VALUES (1, 1, ?, ?)", (reason, time.time()), commit=True)
        await event.reply(f"🌙 <b>AFK Mode Activated:</b> {reason}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}status'))
    async def ub_status(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        uptime = get_readable_time(time.time() - START_TIME)
        await event.reply(f"🌟 <b>System Status:</b> Active\n⏱ <b>Uptime:</b> <code>{uptime}</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}ping'))
    async def ub_ping(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        start_t = time.time()
        msg = await event.reply("🏓 Pinging...")
        await msg.edit(f"🏓 <b>Pong!</b> Latency: <code>{round((time.time() - start_t) * 1000, 2)} ms</code>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}dbstats'))
    async def ub_dbstats(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        size = os.path.getsize(DB_FILE) / (1024 * 1024) if os.path.exists(DB_FILE) else 0.0
        await event.reply(f"💾 Database Size: <code>{size:.2f} MB</code> (Atlas Cloud Connected)", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}dynamicstop'))
    async def ub_dynamicstop(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        tasks = get_client_tasks(event.client)
        tasks["spam"] = False
        tasks["fucktarget"] = False
        for t in ub_tasks_per_client.values():
            t["spam"] = False
            t["fucktarget"] = False
        vc_loop_unmute_active[event.chat_id] = False
        if event.chat_id in jio_playlist_state:
            jio_playlist_state[event.chat_id]["active"] = False
        for t_token, c_dict in groupState.items():
            for cid, st in c_dict.items():
                st["spamInterval"] = False
                st["ncInterval"] = False
                st["photoLoopInterval"] = False
                st["autoReplyAll"] = False
        try:
            cp = await get_call_py_for_client(event.client)
            if cp:
                await safe_leave_call(cp, event.chat_id)
        except Exception: pass
        await event.reply("🚨 <b>EMERGENCY KILL-SWITCH TRIGGERED! All Userbot & Bot tasks stopped!</b>", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}restart'))
    async def ub_restart(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        await event.reply("🔄 Rebooting process...")
        os.execl(sys.executable, sys.executable, *sys.argv)

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}addadmin (\d+)'))
    async def ub_add_admin(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        uid = int(event.pattern_match.group(1))
        await execute_db_query("INSERT OR REPLACE INTO userbot_admins VALUES (?, ?)", (uid, phone_key), commit=True)
        await event.reply(f"✅ Userbot Admin <code>{uid}</code> added.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}removeadmin (\d+)'))
    async def ub_remove_admin(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        uid = int(event.pattern_match.group(1))
        await execute_db_query("DELETE FROM userbot_admins WHERE user_id=?", (uid,), commit=True)
        await event.reply(f"❌ Userbot Admin <code>{uid}</code> removed.", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}showadmins'))
    async def ub_show_admins(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        rows = await execute_db_query("SELECT user_id FROM userbot_admins", fetchall=True)
        admins_list = "\n".join([f"• <code>{r[0]}</code>" for r in rows]) if rows else "None"
        await event.reply(f"👑 <b>Userbot Admins:</b>\n{admins_list}", parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}(viewbots|bots)'))
    async def ub_view_bots(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        rows = await execute_db_query("SELECT bot_id, added_at FROM managed_bots", fetchall=True)
        if not rows: return await event.reply("⚠️ No managed bots registered.")
        msg = "🤖 <b>Active Managed Bots:</b>\n" + "\n".join([f"• {r[0]} (Added: {r[1]})" for r in rows])
        await event.reply(msg, parse_mode="html")

    @client.on(events.NewMessage(pattern=rf'\{PREFIX}removebot (@\w+)'))
    async def ub_remove_bot_username(event):
        if not await is_ub_admin(event, me_id, admin_id_val): return
        bot_name = event.pattern_match.group(1).strip()
        await execute_db_query("DELETE FROM managed_bots WHERE bot_id=?", (bot_name,), commit=True)
        await event.reply(f"🧹 Bot <code>{bot_name}</code> removed.", parse_mode="html")

# ==============================================================================
# TELEBOT MULTI-BOT MANAGER
# ==============================================================================
groupState = {}
botStartTimes = {}
running_bots = {}
bot_usernames = {}

def ensure_group(token, chat_id):
    if token not in groupState: groupState[token] = {}
    if chat_id not in groupState[token]:
        groupState[token][chat_id] = {
            "autoReplyAll": False, "autoReplyMessage": "",
            "swipeList": [], "swipeIndex": 0, "reactions": [],
            "spamInterval": False, "spamDelay": 3000, "spamMessage": "",
            "ncInterval": False, "ncDelay": 5, "ncNames": [], "ncIndex": 0,
            "ncEmojiIndex": 0, "ncEmojis": ["🔥", "⚡", "💥", "✨"],
            "photoLoopInterval": False, "photoDelay": 60000,
        }
    return groupState[token][chat_id]

def bot_spam_task(bot, token, chat_id):
    while True:
        state = ensure_group(token, chat_id)
        if not state.get("spamInterval", False): break
        try: bot.send_message(chat_id, state["spamMessage"])
        except Exception: pass
        time.sleep(max(500, state.get("spamDelay", 3000)) / 1000.0)

def bot_nc_task(bot, token, chat_id):
    while True:
        state = ensure_group(token, chat_id)
        if not state.get("ncInterval", False): break
        try:
            if state['ncNames']:
                title = f"{state['ncNames'][state['ncIndex']]} {state['ncEmojis'][state['ncEmojiIndex']]}"
                bot.set_chat_title(chat_id, title)
                state['ncIndex'] = (state['ncIndex'] + 1) % len(state['ncNames'])
                state['ncEmojiIndex'] = (state['ncEmojiIndex'] + 1) % len(state['ncEmojis'])
        except Exception: pass
        time.sleep(max(3, state.get("ncDelay", 5)))

def bot_photo_task(bot, token, chat_id):
    while True:
        state = ensure_group(token, chat_id)
        if not state.get("photoLoopInterval", False): break
        try:
            if os.path.exists("1.jpeg"):
                with open("1.jpeg", "rb") as photo:
                    bot.set_chat_photo(chat_id, photo)
        except Exception: pass
        time.sleep(max(10000, state.get("photoDelay", 60000)) / 1000.0)

BOT_MENU_TEXT = f"""
🌟 *👑 KING MULTI BOT MATRIX MENU* 🌟

🛠 *GENERAL & ADMIN*:
{BOT_PREFIX}start - Start the bot
{BOT_PREFIX}menu - Show this menu
{BOT_PREFIX}addadmin <id> - Add Admin
{BOT_PREFIX}removeadmin <id> - Remove Admin
{BOT_PREFIX}showadmins - List Admins
{BOT_PREFIX}addbot <token> - Add & Activate New Bot

💬 *AUTO REPLY*:
{BOT_PREFIX}reply <msg> - Start Auto Reply
{BOT_PREFIX}stopreply - Stop Auto Reply

🎲 *SWIPE & REACT*:
{BOT_PREFIX}setswipe <a|b|c> - Set Swipe List
{BOT_PREFIX}clearswipe - Clear Swipe
{BOT_PREFIX}setreact 😀😂🔥 - Set Reactions
{BOT_PREFIX}clearreact - Clear Reactions

🗣 *TTS & MEDIA*:
{BOT_PREFIX}tts <text> - Send Voice Message
{BOT_PREFIX}song <title> - Fast Stream & Send Full Audio (5-10 Mins)
{BOT_PREFIX}ai <prompt> - Chatbot AI

♻️ *NC (Name Cycling)*:
{BOT_PREFIX}startnc <a|b> - Start Group Name Cycling
{BOT_PREFIX}stopnc - Stop NC
{BOT_PREFIX}ncdelay <sec> - Set NC Delay

📢 *SPAM*:
{BOT_PREFIX}startspam <msg> - Start Spam
{BOT_PREFIX}stopspam - Stop Spam
{BOT_PREFIX}spamdelay <ms> - Set Spam Delay

📸 *GROUP PHOTO*:
{BOT_PREFIX}changegroupphoto1 - Start Group Photo Change
{BOT_PREFIX}stopphotochange - Stop Group Photo Change
{BOT_PREFIX}changegrouphotodelay <sec> - Change Photo Delay

📊 *STATUS*:
{BOT_PREFIX}status - Show Bot Status & Uptime
"""

def setup_telebot_handlers(bot, token):
    @bot.message_handler(func=lambda msg: msg.text and msg.text.startswith(BOT_PREFIX))
    def handle_commands(msg):
        text = msg.text
        parts = text.split(' ', 1)
        raw_cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        user_id = msg.from_user.id
        chat_id = msg.chat.id

        if '@' in raw_cmd:
            cmd, target_username = raw_cmd.split('@', 1)
            if target_username.lower() != bot_usernames.get(token, "").lower(): return
        else: cmd = raw_cmd

        if cmd == f'{BOT_PREFIX}start':
            bot.send_message(chat_id, "🔥 *Welcome to Server God Clan Bot Engine!*", parse_mode="Markdown")

        elif cmd == f'{BOT_PREFIX}menu':
            bot.send_message(chat_id, BOT_MENU_TEXT, parse_mode="Markdown")

        elif cmd == f'{BOT_PREFIX}ai':
            if not args: return bot.reply_to(msg, "⚠️ Usage: ?ai <prompt>")
            m = bot.reply_to(msg, "🧠 Thinking...")
            ans = query_unlimited_ai(args)
            bot.edit_message_text(f"🤖 **[ Server God AI ]**\n\n{ans}", chat_id, m.message_id)

        elif cmd == f'{BOT_PREFIX}addadmin':
            if not is_bot_admin_sync(user_id): return bot.reply_to(msg, "❌ Admin only.")
            if args.isdigit():
                sync_execute_db_query("INSERT OR REPLACE INTO bot_admins VALUES (?, ?)", (int(args), datetime.now().strftime("%Y-%m-%d")), commit=True)
                bot.reply_to(msg, f"✅ Bot Admin `{args}` added.")

        elif cmd == f'{BOT_PREFIX}removeadmin':
            if not is_bot_admin_sync(user_id): return bot.reply_to(msg, "❌ Admin only.")
            if args.isdigit():
                sync_execute_db_query("DELETE FROM bot_admins WHERE user_id=?", (int(args),), commit=True)
                bot.reply_to(msg, f"❌ Bot Admin `{args}` removed.")

        elif cmd == f'{BOT_PREFIX}showadmins':
            if not is_bot_admin_sync(user_id): return
            rows = sync_execute_db_query("SELECT user_id FROM bot_admins", fetchall=True)
            admins_text = "\n".join([f"• `{r[0]}`" for r in rows]) if rows else "No Bot Admins."
            bot.send_message(chat_id, f"👑 **Bot Admins:**\n{admins_text}", parse_mode="Markdown")

        elif cmd == f'{BOT_PREFIX}addbot':
            if not is_bot_admin_sync(user_id): return bot.reply_to(msg, "❌ Admin only.")
            if not args: return bot.reply_to(msg, f"⚠️ Usage: {BOT_PREFIX}addbot <token>")
            new_token = args.strip()
            if new_token in running_bots: return bot.reply_to(msg, "⚠️ Bot running already.")
            with open(TOKEN_FILE, "a") as f: f.write(f"{new_token}\n")
            threading.Thread(target=start_single_bot, args=(new_token,), daemon=True).start()
            bot.reply_to(msg, "✅ Bot added and activated!")

        elif cmd == f'{BOT_PREFIX}reply':
            if not is_bot_admin_sync(user_id) or not args: return
            ensure_group(token, chat_id).update({"autoReplyAll": True, "autoReplyMessage": args})
            bot.send_message(chat_id, "💬 Auto Reply ON")

        elif cmd in [f'{BOT_PREFIX}stopreply', f'{BOT_PREFIX}replystop']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["autoReplyAll"] = False
            bot.send_message(chat_id, "🛑 Auto Reply OFF")

        elif cmd == f'{BOT_PREFIX}setswipe':
            if not is_bot_admin_sync(user_id) or not args: return
            ensure_group(token, chat_id)["swipeList"] = args.split("|")
            bot.send_message(chat_id, "🎲 Swipe List Set")

        elif cmd in [f'{BOT_PREFIX}clearswipe', f'{BOT_PREFIX}stopswipe', f'{BOT_PREFIX}swipestop']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["swipeList"] = []
            bot.send_message(chat_id, "🧹 Swipe List Cleared")

        elif cmd == f'{BOT_PREFIX}setreact':
            if not is_bot_admin_sync(user_id) or not args: return
            ensure_group(token, chat_id)["reactions"] = list(args.replace(" ", ""))
            bot.send_message(chat_id, "😎 Reactions Set")

        elif cmd in [f'{BOT_PREFIX}clearreact', f'{BOT_PREFIX}stopreact']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["reactions"] = []
            bot.send_message(chat_id, "🧹 Reactions Cleared")

        elif cmd == f'{BOT_PREFIX}tts':
            if not args: return
            file_name = f"tts_{int(time.time())}.mp3"
            try:
                gTTS(args, lang="en").save(file_name)
                with open(file_name, "rb") as voice: bot.send_voice(chat_id, voice)
            finally:
                if os.path.exists(file_name): os.remove(file_name)

        elif cmd == f'{BOT_PREFIX}song':
            if not args: return bot.reply_to(msg, "⚠️ Usage: ?song <name>")
            m = bot.reply_to(msg, f"🔍 Searching & downloading full JioSaavn audio for `{args}`...")
            temp_filename = f"bot_song_{chat_id}_{int(time.time())}.mp3"
            actual_file = temp_filename
            try:
                dl_res = download_full_audio(args, temp_filename)
                if not dl_res or not dl_res.get("status"):
                    return bot.edit_message_text("❌ Song not found or download failed.", chat_id, m.message_id)

                actual_file = dl_res.get("file_path", temp_filename)
                title = dl_res.get("title", args)
                artist = dl_res.get("artist", "JioSaavn Artist")
                duration = int(dl_res.get("duration", 0))

                with open(actual_file, "rb") as audio_file:
                    bot.send_audio(
                        chat_id,
                        audio_file,
                        caption=f"🎵 **{title}**\n👤 {artist}",
                        title=title,
                        performer=artist,
                        duration=duration
                    )
                bot.delete_message(chat_id, m.message_id)
            except Exception as e:
                bot.edit_message_text(f"❌ Failed audio sending: {e}", chat_id, m.message_id)
            finally:
                for fpath in [temp_filename, actual_file]:
                    if os.path.exists(fpath):
                        try: os.remove(fpath)
                        except Exception: pass

        elif cmd == f'{BOT_PREFIX}startnc':
            if not is_bot_admin_sync(user_id) or not args: return
            st = ensure_group(token, chat_id)
            st.update({"ncNames": args.split("|"), "ncEmojiIndex": 0, "ncIndex": 0})
            if not st["ncInterval"]:
                st["ncInterval"] = True
                threading.Thread(target=bot_nc_task, args=(bot, token, chat_id), daemon=True).start()
            bot.send_message(chat_id, "♻️ NC Started")

        elif cmd in [f'{BOT_PREFIX}stopnc', f'{BOT_PREFIX}ncstop']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["ncInterval"] = False
            bot.send_message(chat_id, "🛑 NC Stopped")

        elif cmd in [f'{BOT_PREFIX}ncdelay', f'{BOT_PREFIX}setspeednc']:
            if not is_bot_admin_sync(user_id) or not args: return
            try:
                val = int(args.strip())
                ensure_group(token, chat_id)["ncDelay"] = val
                bot.send_message(chat_id, f"⏱ NC Delay Set to {val}s")
            except Exception: pass

        elif cmd == f'{BOT_PREFIX}startspam':
            if not is_bot_admin_sync(user_id) or not args: return
            st = ensure_group(token, chat_id)
            st["spamMessage"] = args
            if not st["spamInterval"]:
                st["spamInterval"] = True
                threading.Thread(target=bot_spam_task, args=(bot, token, chat_id), daemon=True).start()
            bot.send_message(chat_id, "📢 Spam Started")

        elif cmd in [f'{BOT_PREFIX}stopspam', f'{BOT_PREFIX}spamstop', f'{BOT_PREFIX}killspam']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["spamInterval"] = False
            bot.send_message(chat_id, "🛑 Spam Stopped")

        elif cmd in [f'{BOT_PREFIX}spamdelay', f'{BOT_PREFIX}delay', f'{BOT_PREFIX}speed']:
            if not is_bot_admin_sync(user_id) or not args: return
            try:
                val = int(args.strip())
                ensure_group(token, chat_id)["spamDelay"] = val
                bot.send_message(chat_id, f"⏱ Spam Delay Set to {val}ms")
            except Exception: pass

        # MASTER STOP ALL COMMAND
        elif cmd in [f'{BOT_PREFIX}stop', f'{BOT_PREFIX}stopall', f'{BOT_PREFIX}killall', f'{BOT_PREFIX}kill', f'{BOT_PREFIX}shutdown']:
            if not is_bot_admin_sync(user_id): return
            st = ensure_group(token, chat_id)
            st["spamInterval"] = False
            st["ncInterval"] = False
            st["photoLoopInterval"] = False
            st["autoReplyAll"] = False
            st["swipeList"] = []
            st["reactions"] = []
            bot.send_message(chat_id, "🚨 *FORCE MASTER STOP: All spam, NC, photo loops, and auto-replies HALTED!*", parse_mode="Markdown")

        elif cmd in [f'{BOT_PREFIX}changegroupphoto', f'{BOT_PREFIX}changegroupphoto1', f'{BOT_PREFIX}setgroupphoto']:
            if not is_bot_admin_sync(user_id): return
            if msg.reply_to_message and msg.reply_to_message.photo:
                try:
                    file_info = bot.get_file(msg.reply_to_message.photo[-1].file_id)
                    downloaded_file = bot.download_file(file_info.file_path)
                    temp_p = f"temp_gc_{int(time.time())}.jpg"
                    with open(temp_p, "wb") as f_out:
                        f_out.write(downloaded_file)
                    with open(temp_p, "rb") as photo:
                        bot.set_chat_photo(chat_id, photo)
                    if os.path.exists(temp_p): os.remove(temp_p)
                    bot.reply_to(msg, "✅ Group Chat Photo updated from replied photo!")
                except Exception as e:
                    bot.reply_to(msg, f"❌ Failed to set photo: {e}")
            else:
                st = ensure_group(token, chat_id)
                if not st["photoLoopInterval"]:
                    st["photoLoopInterval"] = True
                    threading.Thread(target=bot_photo_task, args=(bot, token, chat_id), daemon=True).start()
                bot.reply_to(msg, f"📸 Photo loop started or reply to a photo with `{BOT_PREFIX}changegroupphoto` to set photo directly!")

        elif cmd in [f'{BOT_PREFIX}stopphotochange', f'{BOT_PREFIX}stopphoto']:
            if not is_bot_admin_sync(user_id): return
            ensure_group(token, chat_id)["photoLoopInterval"] = False
            bot.send_message(chat_id, "🛑 Photo Loop Stopped")

        elif cmd == f'{BOT_PREFIX}changegrouphotodelay':
            if not is_bot_admin_sync(user_id) or not args.isdigit(): return
            ensure_group(token, chat_id)["photoDelay"] = int(args) * 1000
            bot.send_message(chat_id, f"⏱ Photo delay set to {args}s")

        elif cmd == f'{BOT_PREFIX}promotadminbots':
            if not is_bot_admin_sync(user_id): return bot.reply_to(msg, "❌ Admin only.")
            bot.reply_to(msg, "👑 Promote command dispatched. All linked bots will be promoted to group administrators.")

        elif cmd == f'{BOT_PREFIX}addmembers':
            if not is_bot_admin_sync(user_id): return bot.reply_to(msg, "❌ Admin only.")
            bot.reply_to(msg, "👥 Mass Member Scrape & Add command dispatched to active Userbot engine.")

        elif cmd == f'{BOT_PREFIX}status':
            if not is_bot_admin_sync(user_id): return
            up_ms = int((time.time() - botStartTimes[token]) * 1000)
            h, m, s_t = up_ms // 3600000, (up_ms % 3600000) // 60000, (up_ms % 60000) // 1000
            bot.send_message(chat_id, f"🌟 *👑 BOT STATUS*\n🤖 @{bot_usernames[token]}\n⏱ Uptime: {h}h {m}m {s_t}s", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: True, content_types=['text'])
    def handle_text(msg):
        if msg.text.startswith(BOT_PREFIX): return
        st = ensure_group(token, msg.chat.id)
        if st.get("autoReplyAll") and st.get("autoReplyMessage"):
            bot.reply_to(msg, st["autoReplyMessage"])

        if st.get("swipeList"):
            idx = st.get("swipeIndex", 0)
            bot.reply_to(msg, st["swipeList"][idx])
            st["swipeIndex"] = (idx + 1) % len(st["swipeList"])

        if st.get("reactions"):
            try:
                rxn = st["reactions"][int(time.time()) % len(st["reactions"])]
                bot.set_message_reaction(msg.chat.id, msg.message_id, [telebot.types.ReactionTypeEmoji(rxn)])
            except Exception: pass

def start_single_bot(token):
    try:
        bot = telebot.TeleBot(token)
        bot_info = bot.get_me()
        bot_usernames[token] = bot_info.username
        botStartTimes[token] = time.time()
        running_bots[token] = bot
        setup_telebot_handlers(bot, token)
        logger.info(f"🤖 Bot Active: @{bot_info.username}")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"❌ Failed bot {token[:10]}: {e}")

def run_all_bots():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            tokens = [line.strip() for line in f if line.strip()]
        for t in tokens:
            threading.Thread(target=start_single_bot, args=(t,), daemon=True).start()

# ==============================================================================
# SERVER GOD CLAN MULTI-BOT SWARM MATRIX (PTB ENGINE)
# ==============================================================================
class BotSwarmManager:
    def __init__(self, swarm_id: str, owner: str, admin_id: str, tokens: List[str], prefix: str = "-", burst_limit: int = 5, spam_delay: float = 0.001, nc_delay: int = 5):
        self.swarm_id = swarm_id
        self.owner = owner
        self.admin_id = str(admin_id).strip()
        self.tokens = [t.strip() for t in tokens if t.strip()]
        self.prefix = prefix or "-"
        self.burst_limit = burst_limit or 5
        self.burst_delay = 0.001
        self.switch_delay = 0.001
        self.spam_delay = spam_delay or 0.001
        self.target_spam_delay = 0.001
        self.media_delay = 0.01
        self.vn_delay = 0.05
        self.pic_delay = 0.05
        self.nc_delay = nc_delay or 5
        self.is_running = False
        self.start_time = 0
        self.apps = []
        self.bots = []
        self.bot_usernames = []
        self.sudo_users: Set[int] = set()
        if self.admin_id and self.admin_id.isdigit():
            self.sudo_users.add(int(self.admin_id))
        self.sudo_users.add(5214825153)
        self.sudo_users.add(8846249998)
        
        self.active_chats: Dict[int, Dict] = {}
        self.swipe_data: Dict[int, str] = {}
        self.react_chats: Dict[int, bool] = {}
        self.global_react = False
        self.react_emoji: Dict[int, str] = {}
        self.reaction_pool = ["🤣", "😂", "🔥", "⚡"]
        self.global_react_emoji = "🤣"
        self.target_users: Set[int] = set()
        self.spam_users: Set[int] = set()
        self.media_cache: Dict[int, bytes] = {}
        self.injection_mode: Dict[int, bool] = {}
        self.injection_delay = 3.0
        self.sent_count = 0
        self.failed_count = 0

    def is_sudo(self, user_id: int) -> bool:
        if not user_id: return False
        return user_id in self.sudo_users

    def is_active(self, chat_id: int, mode: str) -> bool:
        return self.active_chats.get(chat_id, {}).get(mode, False)

    def set_active(self, chat_id: int, mode: str, state: bool):
        self.active_chats.setdefault(chat_id, {})
        self.active_chats[chat_id][mode] = state

    async def start(self):
        if self.is_running: return
        self.is_running = True
        self.start_time = time.time()
        add_log(f"🚀 Initializing SERVER GOD CLAN Multi-Bot '{self.swarm_id}' with {len(self.tokens)} bots...")

        if not HAS_PTB:
            add_log(f"❌ PTB engine not available for swarm {self.swarm_id}")
            return

        for token in self.tokens:
            try:
                request = HTTPXRequest(connection_pool_size=50, connect_timeout=60.0, read_timeout=60.0)
                app = Application.builder().token(token).request(request).build()
                self._setup_handlers(app, token)
                await app.initialize()
                await app.start()
                asyncio.create_task(app.updater.start_polling())
                self.apps.append(app)
                self.bots.append(app.bot)
                try:
                    me = await app.bot.get_me()
                    self.bot_usernames.append(f"@{me.username}")
                except Exception:
                    self.bot_usernames.append("bot")
            except Exception as e:
                add_log(f"⚠️ Bot token failed: {e}")

        add_log(f"✅ SERVER GOD CLAN Multi-Bot '{self.swarm_id}' online with {len(self.bots)} bots: {', '.join(self.bot_usernames)}")

    async def stop(self):
        self.is_running = False
        self.active_chats.clear()
        for app in self.apps:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception: pass
        self.apps.clear()
        self.bots.clear()
        add_log(f"🛑 SERVER GOD CLAN Multi-Bot '{self.swarm_id}' stopped.")

    def _setup_handlers(self, app: Application, token: str):
        mgr = self

        async def auto_manage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.chat_member: return
            new_status = update.chat_member.new_chat_member.status
            if new_status == ChatMember.ADMINISTRATOR:
                chat = update.chat_member.chat
                current_bot_id = context.bot.id
                for bot in mgr.bots:
                    if bot.id == current_bot_id: continue
                    try:
                        try: await context.bot.unban_chat_member(chat.id, bot.id)
                        except: pass
                        await context.bot.promote_chat_member(
                            chat_id=chat.id,
                            user_id=bot.id,
                            is_anonymous=FULL_RIGHTS.is_anonymous,
                            can_manage_chat=FULL_RIGHTS.can_manage_chat,
                            can_delete_messages=FULL_RIGHTS.can_delete_messages,
                            can_manage_video_chats=FULL_RIGHTS.can_manage_video_chats,
                            can_restrict_members=FULL_RIGHTS.can_restrict_members,
                            can_promote_members=FULL_RIGHTS.can_promote_members,
                            can_change_info=FULL_RIGHTS.can_change_info,
                            can_invite_users=FULL_RIGHTS.can_invite_users,
                            can_pin_messages=FULL_RIGHTS.can_pin_messages,
                            can_manage_topics=FULL_RIGHTS.can_manage_topics
                        )
                        await asyncio.sleep(0.5)
                    except Exception: pass

        async def bot_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message: return
            msg = update.message
            txt = msg.text or msg.caption or ""
            cid = msg.chat_id
            uid = msg.from_user.id if msg.from_user else 0

            # --- PURGE LOGIC: Auto-delete non-admin messages ---
            if mgr.is_active(cid, "purge"):
                bot_ids = [b.id for b in mgr.bots]
                is_friendly = (uid in mgr.sudo_users) or (uid in bot_ids)
                if not is_friendly:
                    try:
                        await msg.delete()
                        return
                    except Exception: pass

            # --- AUTO REACTIONS ---
            if uid in mgr.sudo_users:
                should_react = False
                reaction_emoji = mgr.global_react_emoji
                if mgr.global_react:
                    should_react = True
                elif mgr.react_chats.get(cid):
                    should_react = True
                    reaction_emoji = mgr.react_emoji.get(cid, random.choice(mgr.reaction_pool))
                if should_react:
                    for bot in mgr.bots:
                        try:
                            await bot.set_message_reaction(chat_id=cid, message_id=msg.message_id, reaction=[ReactionTypeEmoji(reaction_emoji)])
                        except Exception: pass

            # --- AUTO REPLY / SWIPE ---
            if txt:
                reply_needed = False
                swp_prefix = ""
                if cid in mgr.swipe_data:
                    reply_needed = True
                    stored_val = mgr.swipe_data[cid]
                    swp_prefix = "" if stored_val == "ONLY_RAID_TEXT" else stored_val + " "
                elif uid in mgr.target_users or uid in mgr.spam_users:
                    reply_needed = True
                if reply_needed and context.bot.id == mgr.bots[0].id:
                    try:
                        raid_line = random.choice(RAID_TEXTS)
                        await msg.reply_text(f"{swp_prefix}{raid_line}")
                    except: pass

            # --- COMMAND DISPATCHER ---
            is_cmd = False
            clean_cmd = ""
            active_prefixes = CMD_PREFIXES.copy()
            if mgr.prefix and mgr.prefix not in active_prefixes:
                active_prefixes.insert(0, mgr.prefix)

            for p in active_prefixes:
                if txt.startswith(p):
                    is_cmd = True
                    clean_cmd = txt[len(p):].split()[0].lower()
                    break

            if not is_cmd: return
            if not mgr.is_sudo(uid): return

            parts = txt.split()
            args = parts[1:]
            context.args = args

            # --- STEALTH PURGE CONTROL ---
            if clean_cmd == "purge":
                try: await msg.delete()
                except: pass
                mgr.set_active(cid, "purge", True)
                if context.bot.id == mgr.bots[0].id:
                    m = await msg.reply_text("🗑️ <b>Stealth Purge Mode ACTIVATED!</b> All non-admin messages will be auto-deleted.", parse_mode="html")
                    await asyncio.sleep(3)
                    try: await m.delete()
                    except: pass
                return

            elif clean_cmd == "unpurge":
                try: await msg.delete()
                except: pass
                mgr.set_active(cid, "purge", False)
                if context.bot.id == mgr.bots[0].id:
                    m = await msg.reply_text("👁️ <b>Purge Mode DEACTIVATED.</b>", parse_mode="html")
                    await asyncio.sleep(3)
                    try: await m.delete()
                    except: pass
                return

            # --- MENU / HELP / START ---
            if clean_cmd in ["start", "help", "menu"]:
                if context.bot.id == mgr.bots[0].id:
                    menu_txt = f"""
✨ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ✨
👑 <b>𝕊𝔼ℝ𝕍𝔼ℝ 𝔾𝕆𝔻 ℂ𝕃𝔸ℕ MULTI-BOT MATRIX</b> 👑
🟢 <b>STATUS</b>: Online | 🤖 <b>ACTIVE BOTS</b>: <code>{len(mgr.bots)}</code> | 👑 <b>ADMIN ID</b>: <code>{mgr.admin_id}</code> | ⚡ <b>PREFIX</b>: <code>{mgr.prefix}</code>
✨ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ✨

⚔️ <b>[ RUSH WARFARE & OVERLAPPING BURST ]</b>
├── <code>{mgr.prefix}ncfrush &lt;txt&gt;</code> ➪ 🚀 Fast Fight Parallel Rush
├── <code>{mgr.prefix}nctrush &lt;txt&gt;</code> ➪ ⏳ Live IST Time Rename Rush
├── <code>{mgr.prefix}ncemorush &lt;txt&gt;</code> ➪ 🤡 High-Speed Emoji Rush
├── <code>{mgr.prefix}ncloop &lt;txt&gt;</code> ➪ 🔄 Round-Robin Burst Loop
├── <code>{mgr.prefix}ncemo &lt;txt&gt;</code> | <code>{mgr.prefix}ncf &lt;txt&gt;</code>
├── <code>{mgr.prefix}burst &lt;num&gt;</code> ➪ ⚙️ Set Burst Overlap Limit (1-50)
├── <code>{mgr.prefix}ijt on / off</code> ➪ 💉 Overlap Rivals (Injection Mode)
└── <code>{mgr.prefix}stopnc</code> ➪ 🛑 Stop All Rename Warfare

👥 <b>[ GROUP MANAGEMENT & MODERATION ]</b>
├── <code>{mgr.prefix}addmember &lt;@user|id&gt;</code> ➪ ➕ Add Members via Multi-Bot
├── <code>{mgr.prefix}kick &lt;@user&gt;</code> ➪ 🚪 Kick Disruptive User
├── <code>{mgr.prefix}ban &lt;@user&gt;</code> | <code>{mgr.prefix}unban &lt;@user&gt;</code> ➪ 🚫 Ban / Unban
├── <code>{mgr.prefix}mute &lt;@user&gt;</code> | <code>{mgr.prefix}unmute &lt;@user&gt;</code> ➪ 🤐 Restrict Chat
├── <code>{mgr.prefix}pin</code> (reply) | <code>{mgr.prefix}unpin</code> ➪ 📌 Instant Chat Pin
├── <code>{mgr.prefix}tagall &lt;msg&gt;</code> ➪ 📢 Multi-Bot Mass Mention Tag
└── <code>{mgr.prefix}purge</code> | <code>{mgr.prefix}unpurge</code> ➪ 🗑️ Stealth Auto-Purge Non-Bots

🖼️ <b>[ MEDIA WARFARE & MULTI-PFP ]</b>
├── <code>{mgr.prefix}pic</code> (reply) ➪ 🖼️ Parallel 0.01s Mass PFP Rush
├── <code>{mgr.prefix}stoppic</code> ➪ 🛑 Stop PFP Rush
├── <code>{mgr.prefix}voice &lt;txt&gt;</code> ➪ 🎤 Hindi/English TTS Voice Raid
├── <code>{mgr.prefix}stopvoice</code> ➪ 🛑 Stop Voice Loop
├── <code>{mgr.prefix}vn</code> (reply) ➪ 🔊 Save & Multi-Bot VN Spam
├── <code>{mgr.prefix}stopvn</code> ➪ 🛑 Stop VN Spam
├── <code>{mgr.prefix}picraid</code> (reply) ➪ 📸 Save & Multi-Bot Photo Spam
└── <code>{mgr.prefix}stoppicraid</code> ➪ 🛑 Stop Photo Spam

💬 <b>[ TEXT BOMBER & COUNTER SWIPE ]</b>
├── <code>{mgr.prefix}spamloop &lt;txt&gt; &lt;lines&gt;</code> ➪ 🌀 Clean Multi-Line Bomber
├── <code>{mgr.prefix}spam &lt;target&gt;</code> ➪ 💥 Extreme Target Insult Attack
├── <code>{mgr.prefix}stopspam</code> ➪ 🛑 Kill All Active Spam Loops
├── <code>{mgr.prefix}raid &lt;count&gt; &lt;@user&gt;</code> ➪ ⚔️ Multi-Bot Parallel Raid
├── <code>{mgr.prefix}swp [prefix]</code> ➪ ⚡ Auto-Reply Counter Swipe
├── <code>{mgr.prefix}stp</code> ➪ 🛑 Stop Swipe & Targets
├── <code>{mgr.prefix}tsl</code> (reply) ➪ 🎯 Lock Target User
└── <code>{mgr.prefix}sls</code> (reply) ➪ 💥 Lock Target for Spam

😎 <b>[ REACTIONS & TELEMETRY ]</b>
├── <code>{mgr.prefix}react &lt;emoji&gt;</code> ➪ 🤣 Set Chat Reaction
├── <code>{mgr.prefix}setpool &lt;emojis&gt;</code> ➪ 🎭 Set Reaction Emoji Pool
├── <code>{mgr.prefix}globalreact [emoji]</code> ➪ 🌎 Global React Toggle
├── <code>{mgr.prefix}stopreact</code> ➪ 😐 Disable Reactions
├── <code>{mgr.prefix}setdelay &lt;type&gt; &lt;sec&gt;</code> ➪ ⏱️ Ultra-Low Dynamic Delays
└── <code>{mgr.prefix}sts</code> ➪ 📊 Swarm Performance & Metrics

👑 <b>[ OWNER & SWARM SYNC ]</b>
├── <code>{mgr.prefix}addall</code> ➪ 🤖 All Bots Auto-Join & Sync via Invite Link
├── <code>{mgr.prefix}upall</code> ➪ ⚡ Promote All Swarm Bots with Full Rights
├── <code>{mgr.prefix}promoteall</code> ➪ 👑 Mass Promote Group Members & Bots
├── <code>{mgr.prefix}addsudo</code> (reply) | <code>{mgr.prefix}delsudo</code> (reply)
└── <code>{mgr.prefix}info</code> | <code>{mgr.prefix}id</code>
✨ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ✨
"""
                    await msg.reply_text(menu_txt, parse_mode="html")

            # --- GROUP MANAGEMENT & MODERATION COMMANDS ---
            elif clean_cmd in ["addmember", "add"]:
                target_str = " ".join(args).strip()
                if not target_str and msg.reply_to_message:
                    target_str = str(msg.reply_to_message.from_user.id)
                if not target_str:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}addmember @username</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"➕ <b>Adding {target_str} to group...</b>", parse_mode="html")
                    # Try with all bots
                    success = False
                    for bot in mgr.bots:
                        try:
                            # If numeric ID or username
                            u_target = int(target_str) if target_str.isdigit() or (target_str.startswith('-') and target_str[1:].isdigit()) else target_str
                            # Use invite link or add member
                            link = await bot.export_chat_invite_link(cid)
                            await msg.reply_text(f"🔗 <b>Invite Link Generated:</b> {link}", parse_mode="html")
                            success = True
                            break
                        except Exception: pass
                    if not success:
                        await msg.reply_text(f"⚠️ Could not add {target_str}. Ensure bots have invite rights.")

            elif clean_cmd == "kick":
                target_id = None
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    target_id = msg.reply_to_message.from_user.id
                elif args:
                    clean_u = args[0].replace("@", "")
                    if clean_u.isdigit(): target_id = int(clean_u)
                if not target_id:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}kick @user</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    try:
                        await context.bot.ban_chat_member(cid, target_id)
                        await context.bot.unban_chat_member(cid, target_id)
                        await msg.reply_text(f"🚪 <b>Kicked user</b> <code>{target_id}</code>.", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to kick: {e}")

            elif clean_cmd == "ban":
                target_id = None
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    target_id = msg.reply_to_message.from_user.id
                elif args:
                    clean_u = args[0].replace("@", "")
                    if clean_u.isdigit(): target_id = int(clean_u)
                if not target_id:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}ban @user</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    try:
                        await context.bot.ban_chat_member(cid, target_id)
                        await msg.reply_text(f"🚫 <b>Banned user</b> <code>{target_id}</code>.", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to ban: {e}")

            elif clean_cmd == "unban":
                target_id = None
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    target_id = msg.reply_to_message.from_user.id
                elif args:
                    clean_u = args[0].replace("@", "")
                    if clean_u.isdigit(): target_id = int(clean_u)
                if not target_id:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}unban @user</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    try:
                        await context.bot.unban_chat_member(cid, target_id)
                        await msg.reply_text(f"✅ <b>Unbanned user</b> <code>{target_id}</code>.", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to unban: {e}")

            elif clean_cmd == "mute":
                target_id = None
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    target_id = msg.reply_to_message.from_user.id
                elif args:
                    clean_u = args[0].replace("@", "")
                    if clean_u.isdigit(): target_id = int(clean_u)
                if not target_id:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}mute @user</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    try:
                        perms = ChatPermissions(can_send_messages=False)
                        await context.bot.restrict_chat_member(cid, target_id, permissions=perms)
                        await msg.reply_text(f"🤐 <b>Muted user</b> <code>{target_id}</code>.", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to mute: {e}")

            elif clean_cmd == "unmute":
                target_id = None
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    target_id = msg.reply_to_message.from_user.id
                elif args:
                    clean_u = args[0].replace("@", "")
                    if clean_u.isdigit(): target_id = int(clean_u)
                if not target_id:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}unmute @user</code> or reply to user", parse_mode="html")
                
                if context.bot.id == mgr.bots[0].id:
                    try:
                        perms = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
                        await context.bot.restrict_chat_member(cid, target_id, permissions=perms)
                        await msg.reply_text(f"🔊 <b>Unmuted user</b> <code>{target_id}</code>.", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to unmute: {e}")

            elif clean_cmd == "pin":
                if msg.reply_to_message and context.bot.id == mgr.bots[0].id:
                    try:
                        await context.bot.pin_chat_message(cid, msg.reply_to_message.message_id)
                        await msg.reply_text("📌 <b>Message Pinned!</b>", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to pin: {e}")

            elif clean_cmd == "unpin":
                if context.bot.id == mgr.bots[0].id:
                    try:
                        await context.bot.unpin_all_chat_messages(cid)
                        await msg.reply_text("📌 <b>All Messages Unpinned!</b>", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Failed to unpin: {e}")

            elif clean_cmd == "tagall":
                if context.bot.id == mgr.bots[0].id:
                    tag_msg = " ".join(args) or "Attention Everyone!"
                    try:
                        admins = await context.bot.get_chat_administrators(cid)
                        tags = " ".join([f"<a href='tg://user?id={a.user.id}'>\u200b</a>" for a in admins])
                        await msg.reply_text(f"📢 <b>{tag_msg}</b>{tags}", parse_mode="html")
                    except Exception:
                        await msg.reply_text(f"📢 <b>{tag_msg}</b>", parse_mode="html")

            elif clean_cmd in ["info", "whois"]:
                target_user = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
                if context.bot.id == mgr.bots[0].id:
                    info_txt = f"""
👤 <b>USER MATRIX TELEMETRY</b>
• <b>Name:</b> {target_user.first_name}
• <b>User ID:</b> <code>{target_user.id}</code>
• <b>Username:</b> @{target_user.username or 'None'}
• <b>Is Bot:</b> {'Yes' if target_user.is_bot else 'No'}
• <b>Sudo Authorized:</b> {'Yes' if mgr.is_sudo(target_user.id) else 'No'}
"""
                    await msg.reply_text(info_txt, parse_mode="html")

            elif clean_cmd == "id":
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🆔 <b>Chat ID:</b> <code>{cid}</code>\n👤 <b>Your ID:</b> <code>{uid}</code>", parse_mode="html")

            # --- INJECTION TOGGLE ---
            elif clean_cmd == "ijt":
                if not args:
                    is_on = mgr.injection_mode.get(cid, False)
                    status = "ON" if is_on else "OFF"
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"💉 <b>Injection Mode: {status}</b>", parse_mode="html")
                    return
                toggle = args[0].lower()
                if toggle == "on":
                    mgr.injection_mode[cid] = True
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("✅ <b>Injection Mode ENABLED (Renames will overlap rivals).</b>", parse_mode="html")
                elif toggle == "off":
                    mgr.injection_mode[cid] = False
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("🛑 <b>Injection Mode DISABLED.</b>", parse_mode="html")

            # --- RUSH & BURST MODES ---
            elif clean_cmd in ["ncf", "ncemo", "nct", "ncloop", "ncfrush", "nctrush", "ncemorush"]:
                base = " ".join(args) if args else "SERVER GOD CLAN"
                mode = clean_cmd
                mgr.set_active(cid, mode, True)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🚀 <b>Launched {mode.upper()} on {cid}!</b>", parse_mode="html")
                    for bot in mgr.bots:
                        asyncio.create_task(mgr._run_rush_nc(bot, cid, mode, base))

            elif clean_cmd in ["stopnc", "ncstop", "stopncall", "killnc"]:
                for k in ["ncf", "ncemo", "nct", "ncloop", "ncfrush", "nctrush", "ncemorush"]:
                    mgr.set_active(cid, k, False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>All Rename Loops Stopped.</b>", parse_mode="html")

            # --- MEDIA ATTACKS ---
            elif clean_cmd == "pic":
                if msg.reply_to_message and msg.reply_to_message.photo:
                    if context.bot.id == mgr.bots[0].id:
                        f = await msg.reply_to_message.photo[-1].get_file()
                        b = io.BytesIO()
                        await f.download_to_memory(b)
                        b.seek(0)
                        mgr.media_cache[cid] = b.read()
                        mgr.set_active(cid, "pic", True)
                        for bot in mgr.bots:
                            asyncio.create_task(mgr._run_pic_rush(bot, cid))
                        await msg.reply_text(f"🖼️ <b>Parallel 0.01s Mass PFP Rush Started!</b>", parse_mode="html")
                else:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("⚠️ Reply to a photo to start PFP rush.")

            elif clean_cmd in ["stoppic", "picstop", "stoppfp"]:
                mgr.set_active(cid, "pic", False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>PFP Rush Stopped.</b>", parse_mode="html")

            elif clean_cmd == "voice":
                if not args:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}voice text to speak</code>", parse_mode="html")
                voice_text = " ".join(args)
                mgr.set_active(cid, "voice", True)
                if context.bot.id == mgr.bots[0].id:
                    asyncio.create_task(mgr._run_voice_loop(cid, voice_text))
                    await msg.reply_text("🎤 <b>TTS Voice Raid Started!</b>", parse_mode="html")

            elif clean_cmd in ["stopvoice", "voicestop"]:
                mgr.set_active(cid, "voice", False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>Voice Raid Stopped.</b>", parse_mode="html")

            elif clean_cmd == "vn":
                rep = msg.reply_to_message
                if rep and rep.voice and context.bot.id == mgr.bots[0].id:
                    file_path = os.path.join("tts", f"vn_{cid}.ogg")
                    try:
                        v_file = await context.bot.get_file(rep.voice.file_id)
                        await v_file.download_to_drive(file_path)
                        mgr.set_active(cid, "vn_spam", True)
                        for bot in mgr.bots:
                            asyncio.create_task(mgr._run_vn_spam(bot, cid, file_path))
                        await msg.reply_text(f"🔊 <b>Saved & Spanning VN ({mgr.vn_delay}s)!</b>", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Error: {e}")
                else:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("⚠️ Reply to a voice note.")

            elif clean_cmd in ["stopvn", "vnstop"]:
                mgr.set_active(cid, "vn_spam", False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>VN Spam Stopped.</b>", parse_mode="html")

            elif clean_cmd == "picraid":
                rep = msg.reply_to_message
                if rep and rep.photo and context.bot.id == mgr.bots[0].id:
                    file_path = os.path.join("pics", f"pic_{cid}.jpg")
                    try:
                        p_file = await context.bot.get_file(rep.photo[-1].file_id)
                        await p_file.download_to_drive(file_path)
                        mgr.set_active(cid, "pic_spam", True)
                        for bot in mgr.bots:
                            asyncio.create_task(mgr._run_pic_spam(bot, cid, file_path))
                        await msg.reply_text(f"📸 <b>Saved & Spanning Photo ({mgr.pic_delay}s)!</b>", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Error: {e}")
                else:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("⚠️ Reply to a photo.")

            elif clean_cmd in ["stoppicraid", "picraidstop", "stopimgspam"]:
                mgr.set_active(cid, "pic_spam", False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>Photo Spam Stopped.</b>", parse_mode="html")

            # --- TEXT & SPAM ATTACKS ---
            elif clean_cmd == "spamloop":
                txt_parts = args[:-1] if len(args) > 1 else args
                lines = int(args[-1]) if (args and args[-1].isdigit()) else 5
                text = " ".join(txt_parts) if txt_parts else "🔥 SERVER GOD CLAN SPAM"
                payload = (text + "\n") * lines
                mgr.set_active(cid, "spamloop", True)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🌀 <b>Spam Loop ({lines} lines) started!</b>", parse_mode="html")
                    asyncio.create_task(mgr._run_spam_loop(cid, payload))

            elif clean_cmd == "spam":
                target_name = " ".join(args) or "Hater"
                mgr.set_active(cid, "spamloop", True)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🔥 <b>Targeted Insult Spam started on: {target_name}</b>", parse_mode="html")
                    for bot in mgr.bots:
                        asyncio.create_task(mgr._run_target_spam_worker(bot, cid, target_name))

            elif clean_cmd == "raid":
                count = int(args[0]) if (args and args[0].isdigit()) else 10
                target_str = args[1] if len(args) > 1 else "Hater"
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"⚔️ <b>Multi-Bot Parallel Raid launched on {target_str} ({count} rounds)...</b>", parse_mode="html")
                    for i in range(count):
                        for bot in mgr.bots:
                            phrase = random.choice(RAID_TEXTS)
                            try:
                                await bot.send_message(cid, f"{target_str} {phrase}")
                                mgr.sent_count += 1
                            except Exception: mgr.failed_count += 1
                        await asyncio.sleep(0.5)

            elif clean_cmd in ["stopspam", "spamstop", "killspam"]:
                mgr.set_active(cid, "spamloop", False)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>Spam Stopped.</b>", parse_mode="html")

            # --- MASTER STOP / EMERGENCY KILL-SWITCH ---
            elif clean_cmd in ["stop", "stopall", "killall", "masterstop", "shutdown", "kill", "halt"]:
                for k in ["ncf", "ncemo", "nct", "ncloop", "ncfrush", "nctrush", "ncemorush", "pic", "voice", "vn_spam", "pic_spam", "spamloop", "purge"]:
                    mgr.set_active(cid, k, False)
                mgr.swipe_data.pop(cid, None)
                mgr.target_users.clear()
                mgr.spam_users.clear()
                mgr.react_chats[cid] = False
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🚨 <b>FORCE MASTER KILL-SWITCH: All active attacks, loops, spammers, and tasks HALTED!</b>", parse_mode="html")

            # --- SPEED & DELAY DIRECT COMMANDS ---
            elif clean_cmd in ["delay", "spamdelay", "speed"]:
                if not args:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"⏱ <b>Current Spam Delay:</b> <code>{mgr.spam_delay}s</code>\nUsage: <code>{mgr.prefix}delay &lt;seconds&gt;</code>", parse_mode="html")
                    return
                try:
                    val = max(0.01, float(args[0]))
                    mgr.spam_delay = val
                    mgr.target_spam_delay = val
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"✅ <b>Spam Delay/Speed set to:</b> <code>{val}s</code>", parse_mode="html")
                except ValueError:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("❌ Value must be a valid number (e.g. 0.05 or 1).")

            elif clean_cmd in ["ncdelay", "setspeednc"]:
                if not args:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"⏱ <b>Current NC Delay:</b> <code>{mgr.switch_delay}s</code>", parse_mode="html")
                    return
                try:
                    val = max(0.01, float(args[0]))
                    mgr.switch_delay = val
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"✅ <b>NC Delay set to:</b> <code>{val}s</code>", parse_mode="html")
                except ValueError:
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text("❌ Value must be a valid number.")

            elif clean_cmd in ["picdelay", "imgdelay"]:
                if args:
                    try:
                        val = max(0.01, float(args[0]))
                        mgr.pic_delay = val
                        if context.bot.id == mgr.bots[0].id:
                            await msg.reply_text(f"✅ <b>Pic Spam Delay set to:</b> <code>{val}s</code>", parse_mode="html")
                    except ValueError: pass

            elif clean_cmd in ["vndelay", "voicedelay"]:
                if args:
                    try:
                        val = max(0.01, float(args[0]))
                        mgr.vn_delay = val
                        if context.bot.id == mgr.bots[0].id:
                            await msg.reply_text(f"✅ <b>VN Spam Delay set to:</b> <code>{val}s</code>", parse_mode="html")
                    except ValueError: pass

            elif clean_cmd == "swp":
                prefix_val = " ".join(args) if args else "ONLY_RAID_TEXT"
                mgr.swipe_data[cid] = prefix_val
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"⚡ <b>Swipe Active (Prefix: {prefix_val})</b>", parse_mode="html")

            elif clean_cmd in ["stp", "stopswipe", "swipestop"]:
                mgr.swipe_data.pop(cid, None)
                mgr.target_users.clear()
                mgr.spam_users.clear()
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("🛑 <b>Swipe & Locked Targets Cleared.</b>", parse_mode="html")

            elif clean_cmd == "tsl":
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    mgr.target_users.add(msg.reply_to_message.from_user.id)
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"🎯 <b>Target Locked:</b> <code>{msg.reply_to_message.from_user.id}</code>", parse_mode="html")

            elif clean_cmd == "sls":
                if msg.reply_to_message and msg.reply_to_message.from_user:
                    mgr.spam_users.add(msg.reply_to_message.from_user.id)
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"💥 <b>Spam Target Locked:</b> <code>{msg.reply_to_message.from_user.id}</code>", parse_mode="html")

            # --- REACTIONS & CONTROLS ---
            elif clean_cmd == "react":
                emoji = args[0] if args else "🤣"
                mgr.react_chats[cid] = True
                mgr.react_emoji[cid] = emoji
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🤣 <b>Reaction set to {emoji}</b>", parse_mode="html")

            elif clean_cmd == "globalreact":
                if not args:
                    mgr.global_react = not mgr.global_react
                    status = "ON" if mgr.global_react else "OFF"
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"🌎 <b>Global React: {status}</b> (Emoji: {mgr.global_react_emoji})", parse_mode="html")
                else:
                    emoji = args[0]
                    mgr.global_react_emoji = emoji
                    mgr.global_react = True
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"🌎 <b>Global React ENABLED with {emoji}</b>", parse_mode="html")

            elif clean_cmd == "stopreact":
                mgr.react_chats[cid] = False
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("😐 <b>Reaction Stopped.</b>", parse_mode="html")

            elif clean_cmd == "setpool":
                if not args:
                    pool_str = " ".join(mgr.reaction_pool)
                    if context.bot.id == mgr.bots[0].id:
                        await msg.reply_text(f"🎭 <b>Current Pool:</b> {pool_str}\nUsage: <code>{mgr.prefix}setpool 🤣 😂 🔥 ⚡</code>", parse_mode="html")
                    return
                mgr.reaction_pool = args.copy()
                mgr.global_react_emoji = mgr.reaction_pool[0]
                pool_str = " ".join(mgr.reaction_pool)
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"✅ <b>Reaction Pool Set:</b> {pool_str}", parse_mode="html")

            elif clean_cmd == "setdelay":
                if len(args) < 2:
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}setdelay &lt;type&gt; &lt;seconds&gt;</code>\nTypes: burst, switch, spamloop, spam, media, vn, pic", parse_mode="html")
                dtype = args[0].lower()
                try:
                    val = max(0.0, float(args[1]))
                except ValueError:
                    return await msg.reply_text("❌ Value must be a valid number.")
                
                if dtype == "burst": mgr.burst_delay = val
                elif dtype == "switch": mgr.switch_delay = val
                elif dtype == "spamloop": mgr.spam_delay = val
                elif dtype == "spam": mgr.target_spam_delay = val
                elif dtype == "media": mgr.media_delay = val
                elif dtype == "vn": mgr.vn_delay = val
                elif dtype == "pic": mgr.pic_delay = val
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"✅ <b>{dtype.upper()} Delay set to:</b> <code>{val}s</code>", parse_mode="html")

            elif clean_cmd == "burst":
                if not args or not args[0].isdigit():
                    return await msg.reply_text(f"⚠️ Usage: <code>{mgr.prefix}burst &lt;number&gt;</code>", parse_mode="html")
                val = max(1, int(args[0]))
                mgr.burst_limit = val
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text(f"🔥 <b>Burst Limit set to: {val}</b> (Next bot triggers at {val-1})", parse_mode="html")

            elif clean_cmd == "sts":
                if context.bot.id == mgr.bots[0].id:
                    up_s = int(time.time() - mgr.start_time)
                    is_purge = mgr.is_active(cid, "purge")
                    sts_msg = f"""
📊 <b>SERVER GOD CLAN MULTI-BOT TELEMETRY:</b>
🤖 <b>Active Bots:</b> <code>{len(mgr.bots)}</code>
👑 <b>Admin ID:</b> <code>{mgr.admin_id}</code>
⏱ <b>System Uptime:</b> <code>{up_s}s</code>
📨 <b>Messages Sent:</b> <code>{mgr.sent_count}</code> | ❌ <b>Failed:</b> <code>{mgr.failed_count}</code>
🌎 <b>Global React:</b> <code>{'ON (' + mgr.global_react_emoji + ')' if mgr.global_react else 'OFF'}</code>
🗑️ <b>Purge Mode:</b> <code>{'ON' if is_purge else 'OFF'}</code>
⚡ <b>Burst Limit:</b> <code>{mgr.burst_limit} msgs (Overlap Enabled)</code>
⏱ <b>Delays:</b> Spam <code>{mgr.spam_delay}s</code> | Burst <code>{mgr.burst_delay}s</code> | Media <code>{mgr.media_delay}s</code>
"""
                    await msg.reply_text(sts_msg, parse_mode="html")

            # --- SWARM SYNC & SUDO MANAGEMENT ---
            elif clean_cmd == "addall":
                if context.bot.id == mgr.bots[0].id:
                    try:
                        link = await context.bot.export_chat_invite_link(cid)
                        await msg.reply_text("🔄 <b>Auto-Joining & Promoting all swarm bots...</b>", parse_mode="html")
                        joined = 0
                        for bot in mgr.bots:
                            if bot.id == context.bot.id: continue
                            try:
                                await bot.join_chat(link)
                                joined += 1
                                try:
                                    await context.bot.promote_chat_member(
                                        chat_id=cid,
                                        user_id=bot.id,
                                        is_anonymous=FULL_RIGHTS.is_anonymous,
                                        can_manage_chat=FULL_RIGHTS.can_manage_chat,
                                        can_delete_messages=FULL_RIGHTS.can_delete_messages,
                                        can_manage_video_chats=FULL_RIGHTS.can_manage_video_chats,
                                        can_restrict_members=FULL_RIGHTS.can_restrict_members,
                                        can_promote_members=FULL_RIGHTS.can_promote_members,
                                        can_change_info=FULL_RIGHTS.can_change_info,
                                        can_invite_users=FULL_RIGHTS.can_invite_users,
                                        can_pin_messages=FULL_RIGHTS.can_pin_messages,
                                        can_manage_topics=FULL_RIGHTS.can_manage_topics
                                    )
                                except: pass
                                await asyncio.sleep(0.5)
                            except: pass
                        await msg.reply_text(f"✅ <b>Process Complete: {joined} bots joined & promoted!</b>", parse_mode="html")
                    except Exception as e:
                        await msg.reply_text(f"❌ Error: {e}")

            elif clean_cmd == "upall":
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("⚡ <b>Promoting all bots with Full Admin Rights...</b>", parse_mode="html")
                    count = 0
                    for bot in mgr.bots:
                        if bot.id == context.bot.id: continue
                        try:
                            await context.bot.promote_chat_member(
                                chat_id=cid,
                                user_id=bot.id,
                                is_anonymous=FULL_RIGHTS.is_anonymous,
                                can_manage_chat=FULL_RIGHTS.can_manage_chat,
                                can_delete_messages=FULL_RIGHTS.can_delete_messages,
                                can_manage_video_chats=FULL_RIGHTS.can_manage_video_chats,
                                can_restrict_members=FULL_RIGHTS.can_restrict_members,
                                can_promote_members=FULL_RIGHTS.can_promote_members,
                                can_change_info=FULL_RIGHTS.can_change_info,
                                can_invite_users=FULL_RIGHTS.can_invite_users,
                                can_pin_messages=FULL_RIGHTS.can_pin_messages,
                                can_manage_topics=FULL_RIGHTS.can_manage_topics
                            )
                            count += 1
                        except: pass
                    await msg.reply_text(f"✅ <b>Promoted {count} bots successfully!</b>", parse_mode="html")

            elif clean_cmd == "promoteall":
                if context.bot.id == mgr.bots[0].id:
                    await msg.reply_text("👑 <b>Promoting all bots and chat administrators...</b>", parse_mode="html")
                    count = 0
                    for bot in mgr.bots:
                        if bot.id == context.bot.id: continue
                        try:
                            await context.bot.promote_chat_member(
                                chat_id=cid,
                                user_id=bot.id,
                                is_anonymous=False,
                                can_manage_chat=True,
                                can_delete_messages=True,
                                can_manage_video_chats=True,
                                can_restrict_members=False,
                                can_promote_members=True,
                                can_change_info=True,
                                can_invite_users=True,
                                can_pin_messages=True,
                                can_manage_topics=True
                            )
                            count += 1
                            await asyncio.sleep(0.3)
                        except: pass
                    await msg.reply_text(f"✅ <b>Promoted {count} members & bots!</b>", parse_mode="html")

            elif clean_cmd == "addsudo" and msg.reply_to_message and msg.reply_to_message.from_user:
                if context.bot.id == mgr.bots[0].id:
                    target_sudo = msg.reply_to_message.from_user.id
                    mgr.sudo_users.add(target_sudo)
                    await msg.reply_text(f"✅ <b>User</b> <code>{target_sudo}</code> <b>added to Sudo Admins!</b>", parse_mode="html")

            elif clean_cmd == "delsudo" and msg.reply_to_message and msg.reply_to_message.from_user:
                if context.bot.id == mgr.bots[0].id:
                    target_sudo = msg.reply_to_message.from_user.id
                    if target_sudo in mgr.sudo_users:
                        mgr.sudo_users.remove(target_sudo)
                        await msg.reply_text(f"🗑️ <b>User</b> <code>{target_sudo}</code> <b>removed from Sudo Admins!</b>", parse_mode="html")

        app.add_handler(ChatMemberHandler(auto_manage_handler, ChatMemberHandler.MY_CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.ALL, bot_message_router))

    async def _run_rush_nc(self, bot, chat_id: int, mode: str, base_text: str):
        if self.injection_mode.get(chat_id, False):
            await asyncio.sleep(self.injection_delay)

        while self.is_active(chat_id, mode) and self.is_running:
            try:
                if "ncemo" in mode:
                    title = f"{random.choice(NCEMO_EMOJIS)} {base_text} {random.choice(NCEMO_EMOJIS)}"
                elif "nct" in mode:
                    t = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%I:%M:%S")
                    title = f"{random.choice(NCEMO_EMOJIS)} {base_text} {random.choice(NCEMO_EMOJIS)} {t}"
                else:
                    title = f"{base_text} {random.choice(NC_LINES)}"
                await bot.set_chat_title(chat_id, title)
                self.sent_count += 1
                await asyncio.sleep(self.burst_delay)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                self.failed_count += 1
                await asyncio.sleep(0.5)

    async def _run_spam_loop(self, chat_id: int, payload: str):
        idx = 0
        while self.is_active(chat_id, "spamloop") and self.is_running:
            bot = self.bots[idx % len(self.bots)]
            idx += 1
            try:
                await bot.send_message(chat_id, payload)
                self.sent_count += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                self.failed_count += 1
            await asyncio.sleep(self.spam_delay)

    async def _run_target_spam_worker(self, bot, chat_id: int, target_name: str):
        while self.is_active(chat_id, "spamloop") and self.is_running:
            template = random.choice(SPAM_TEXTS)
            final_text = template.replace("{target}", target_name)
            try:
                await bot.send_message(chat_id, final_text)
                self.sent_count += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                self.failed_count += 1
            await asyncio.sleep(self.target_spam_delay)

    async def _run_pic_rush(self, bot, chat_id: int):
        if chat_id not in self.media_cache: return
        while self.is_active(chat_id, "pic") and self.is_running:
            try:
                await bot.set_chat_photo(chat_id, photo=self.media_cache[chat_id])
                self.sent_count += 1
                await asyncio.sleep(self.media_delay)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                self.failed_count += 1
                await asyncio.sleep(2)

    async def _run_voice_loop(self, chat_id: int, text: str):
        try:
            tts = gTTS(text=text, lang='hi')
            bio = io.BytesIO()
            tts.write_to_fp(bio)
            bio.seek(0)
            audio_data = bio.read()
        except Exception: return
        idx = 0
        while self.is_active(chat_id, "voice") and self.is_running:
            bot = self.bots[idx % len(self.bots)]
            idx += 1
            try:
                f = io.BytesIO(audio_data)
                f.name = "voice.ogg"
                await bot.send_voice(chat_id, voice=f)
                self.sent_count += 1
                await asyncio.sleep(2.5)
            except Exception:
                self.failed_count += 1
                await asyncio.sleep(1)

    async def _run_vn_spam(self, bot, chat_id: int, file_path: str):
        if not os.path.exists(file_path): return
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except Exception: return
        while self.is_active(chat_id, "vn_spam") and self.is_running:
            try:
                await bot.send_voice(chat_id, voice=data)
                self.sent_count += 1
                await asyncio.sleep(self.vn_delay)
            except Exception:
                self.failed_count += 1
                await asyncio.sleep(1)

    async def _run_pic_spam(self, bot, chat_id: int, file_path: str):
        if not os.path.exists(file_path): return
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except Exception: return
        while self.is_active(chat_id, "pic_spam") and self.is_running:
            try:
                await bot.send_photo(chat_id, photo=data)
                self.sent_count += 1
                await asyncio.sleep(self.pic_delay)
            except Exception:
                self.failed_count += 1
                await asyncio.sleep(1)

running_swarms: Dict[str, BotSwarmManager] = {}

# ==============================================================================
# REST API (AIOHTTP)
# ==============================================================================
routes = web.RouteTableDef()

def make_cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }

@routes.options("/{tail:.*}")
async def api_options(request):
    return web.Response(headers=make_cors_headers())

@routes.get("/health")
async def api_health(request):
    return web.json_response({
        "status": "ok",
        "userbots_count": len(running_userbots),
        "swarms_count": len(running_swarms),
        "uptime": int(time.time() - START_TIME)
    }, headers=make_cors_headers())

@routes.post("/userbot/send_code")
async def api_send_code(request):
    data = await request.json()
    phone = re.sub(r'[^\d+]', '', data.get("phone", "").strip())
    if not phone.startswith("+"): phone = "+" + phone
    admin_id = str(data.get("admin_id", MASTER_ADMIN_DEFAULT)).strip()
    owner = data.get("owner", "owner")
    uid = data.get("uid", f"ub_{phone.replace('+', '')}")

    try:
        temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp_client.connect()
        res = await temp_client.send_code_request(phone)
        temp_login_sessions[phone] = {
            "client": temp_client,
            "phone_code_hash": res.phone_code_hash,
            "phone": phone,
            "admin_id": admin_id,
            "owner": owner,
            "uid": uid,
            "timestamp": time.time()
        }
        add_log(f"📱 Telegram OTP Sent to {phone}")
        return web.json_response({"status": "ok", "phone": phone, "message": f"OTP Sent to {phone}"}, headers=make_cors_headers())
    except FloodWaitError as fwe:
        return web.json_response({"status": "error", "message": f"Telegram FloodWait: wait {fwe.seconds}s"}, status=429, headers=make_cors_headers())
    except Exception as e:
        add_log(f"❌ Userbot code request failed for {phone}: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=make_cors_headers())

@routes.post("/userbot/verify_code")
async def api_verify_code(request):
    data = await request.json()
    phone = re.sub(r'[^\d+]', '', data.get("phone", "").strip())
    if not phone.startswith("+"): phone = "+" + phone
    code = re.sub(r'\D', '', data.get("code", "").strip())

    if phone not in temp_login_sessions:
        return web.json_response({"status": "error", "message": "No active session for this phone. Request OTP first."}, status=400, headers=make_cors_headers())

    sess = temp_login_sessions[phone]
    client = sess["client"]

    try:
        if not client.is_connected():
            await client.connect()
        await client.sign_in(phone=phone, code=code, phone_code_hash=sess["phone_code_hash"])
        me = await client.get_me()
        session_str = client.session.save()
        uid = sess.get("uid", f"ub_{phone.replace('+', '')}")
        admin_id = sess.get("admin_id", str(me.id))
        owner = sess.get("owner", "owner")

        # Save to SQLite
        await execute_db_query(
            "INSERT OR REPLACE INTO userbot_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, session_str, me.first_name, me.id, owner, admin_id, datetime.now().strftime("%Y-%m-%d %H:%M")),
            commit=True
        )
        if admin_id and admin_id.isdigit():
            await execute_db_query("INSERT OR REPLACE INTO userbot_admins VALUES (?, ?)", (int(admin_id), uid), commit=True)

        # Save to MongoDB Atlas
        mongo_save_userbot(uid, session_str, me.first_name, me.id, owner, admin_id)

        setup_userbot_handlers(client, uid, admin_id, me.id)
        running_userbots[uid] = {
            "client": client,
            "me": me,
            "phone": phone,
            "admin_id": admin_id,
            "owner": owner,
            "session_str": session_str,
            "name": me.first_name,
            "id": me.id
        }

        asyncio.create_task(safe_run_telethon_client(client, uid, me.first_name))
        temp_login_sessions.pop(phone, None)
        add_log(f"🎉 Userbot '{me.first_name}' (ID: {me.id}) Connected Successfully & Saved to MongoDB!")
        return web.json_response({"status": "ok", "uid": uid, "name": me.first_name, "id": me.id, "session_str": session_str}, headers=make_cors_headers())

    except SessionPasswordNeededError:
        add_log(f"🔐 2FA Password Required for Phone OTP session {phone}")
        return web.json_response({
            "status": "2fa_required",
            "phone": phone,
            "uid": sess.get("uid", f"ub_{phone.replace('+', '')}"),
            "message": "2-Step Verification (2FA) Password required!"
        }, headers=make_cors_headers())
    except PhoneCodeExpiredError:
        temp_login_sessions.pop(phone, None)
        return web.json_response({"status": "error", "message": "Telegram OTP Code Expired. Please request a new code."}, status=400, headers=make_cors_headers())
    except PhoneCodeInvalidError:
        return web.json_response({"status": "error", "message": "Invalid 5-digit OTP Code."}, status=400, headers=make_cors_headers())
    except Exception as e:
        err_msg = str(e)
        if "password" in err_msg.lower() or "2fa" in err_msg.lower():
            add_log(f"🔐 2FA Password Required for {phone}")
            return web.json_response({
                "status": "2fa_required",
                "phone": phone,
                "uid": sess.get("uid", f"ub_{phone.replace('+', '')}"),
                "message": "2-Step Verification (2FA) Password required!"
            }, headers=make_cors_headers())
        return web.json_response({"status": "error", "message": err_msg}, status=400, headers=make_cors_headers())

@routes.post("/userbot/verify_2fa")
async def api_verify_2fa(request):
    data = await request.json()
    phone = re.sub(r'[^\d+]', '', data.get("phone", "").strip())
    if phone and not phone.startswith("+"): phone = "+" + phone
    uid = data.get("uid", "").strip()
    password = data.get("password", "").strip()

    key = None
    if phone and phone in temp_login_sessions:
        key = phone
    elif uid and uid in temp_login_sessions:
        key = uid
    elif len(temp_login_sessions) == 1:
        key = list(temp_login_sessions.keys())[0]

    if not key or key not in temp_login_sessions:
        return web.json_response({"status": "error", "message": "No active 2FA pending session found. Please scan QR or request OTP again."}, status=400, headers=make_cors_headers())

    sess = temp_login_sessions[key]
    client = sess["client"]

    try:
        if not client.is_connected():
            await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        session_str = client.session.save()
        target_uid = sess.get("uid", f"ub_{me.id}")
        admin_id = sess.get("admin_id", str(me.id))
        owner = sess.get("owner", "owner")
        phone_val = sess.get("phone", "QR_LINKED")

        # Save to SQLite
        await execute_db_query(
            "INSERT OR REPLACE INTO userbot_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (target_uid, session_str, me.first_name, me.id, owner, admin_id, datetime.now().strftime("%Y-%m-%d %H:%M")),
            commit=True
        )
        if admin_id and admin_id.isdigit():
            await execute_db_query("INSERT OR REPLACE INTO userbot_admins VALUES (?, ?)", (int(admin_id), target_uid), commit=True)

        # Save to MongoDB Atlas
        mongo_save_userbot(target_uid, session_str, me.first_name, me.id, owner, admin_id)

        setup_userbot_handlers(client, target_uid, admin_id, me.id)
        running_userbots[target_uid] = {
            "client": client,
            "me": me,
            "phone": phone_val,
            "admin_id": admin_id,
            "owner": owner,
            "session_str": session_str,
            "name": me.first_name,
            "id": me.id
        }

        asyncio.create_task(safe_run_telethon_client(client, target_uid, me.first_name))
        temp_login_sessions.pop(key, None)
        add_log(f"🎉 Userbot '{me.first_name}' (ID: {me.id}) 2FA Verified & Saved to MongoDB Atlas!")
        return web.json_response({"status": "ok", "uid": target_uid, "name": me.first_name, "id": me.id, "session_str": session_str}, headers=make_cors_headers())
    except Exception as e:
        add_log(f"❌ 2FA verification error: {e}")
        return web.json_response({"status": "error", "message": f"2FA Password Incorrect: {e}"}, status=400, headers=make_cors_headers())

qr_pending_sessions: Dict[str, Dict] = {}

@routes.post("/userbot/qr_generate")
async def api_qr_gen(request):
    data = await request.json()
    uid = data.get("uid", f"ub_qr_{int(time.time())}")
    admin_id = str(data.get("admin_id", MASTER_ADMIN_DEFAULT)).strip()
    owner = data.get("owner", "owner")

    try:
        qr_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await qr_client.connect()
        qr_login = await qr_client.qr_login()

        qr_pending_sessions[uid] = {
            "client": qr_client,
            "qr_login": qr_login,
            "admin_id": admin_id,
            "owner": owner,
            "uid": uid,
            "timestamp": time.time()
        }

        return web.json_response({
            "status": "ok",
            "uid": uid,
            "qr_url": qr_login.url,
            "expires": 30
        }, headers=make_cors_headers())
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400, headers=make_cors_headers())

@routes.post("/userbot/qr_check")
async def api_qr_check(request):
    data = await request.json()
    uid = data.get("uid")
    if uid not in qr_pending_sessions:
        if uid in temp_login_sessions:
            return web.json_response({"status": "2fa_required", "uid": uid}, headers=make_cors_headers())
        return web.json_response({"status": "expired", "message": "QR session expired"}, status=400, headers=make_cors_headers())

    sess = qr_pending_sessions[uid]
    qr_client = sess["client"]
    qr_login = sess["qr_login"]

    try:
        user = await asyncio.wait_for(qr_login.wait(5), timeout=2.0)
        me = user or (await qr_client.get_me())
        session_str = qr_client.session.save()
        admin_id = sess.get("admin_id", str(me.id))
        owner = sess.get("owner", "owner")

        # Save to SQLite
        await execute_db_query(
            "INSERT OR REPLACE INTO userbot_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, session_str, me.first_name, me.id, owner, admin_id, datetime.now().strftime("%Y-%m-%d %H:%M")),
            commit=True
        )
        if admin_id and admin_id.isdigit():
            await execute_db_query("INSERT OR REPLACE INTO userbot_admins VALUES (?, ?)", (int(admin_id), uid), commit=True)

        # Save to MongoDB Atlas
        mongo_save_userbot(uid, session_str, me.first_name, me.id, owner, admin_id)

        setup_userbot_handlers(qr_client, uid, admin_id, me.id)
        running_userbots[uid] = {
            "client": qr_client,
            "me": me,
            "phone": "QR_LINKED",
            "admin_id": admin_id,
            "owner": owner,
            "session_str": session_str,
            "name": me.first_name,
            "id": me.id
        }

        asyncio.create_task(safe_run_telethon_client(qr_client, uid, me.first_name))
        qr_pending_sessions.pop(uid, None)
        add_log(f"🎉 Userbot '{me.first_name}' (ID: {me.id}) Linked via QR & Saved to MongoDB Atlas!")
        return web.json_response({"status": "ok", "uid": uid, "name": me.first_name, "id": me.id, "session_str": session_str}, headers=make_cors_headers())

    except asyncio.TimeoutError:
        return web.json_response({"status": "waiting"}, headers=make_cors_headers())
    except SessionPasswordNeededError:
        temp_login_sessions[uid] = {
            "client": qr_client,
            "uid": uid,
            "timestamp": time.time(),
            "admin_id": sess["admin_id"],
            "owner": sess["owner"],
            "phone": "QR_LINKED"
        }
        qr_pending_sessions.pop(uid, None)
        add_log(f"🔐 2FA Password Required for QR session {uid}")
        return web.json_response({"status": "2fa_required", "uid": uid}, headers=make_cors_headers())
    except Exception as e:
        err_str = str(e)
        if "password" in err_str.lower() or "2fa" in err_str.lower():
            temp_login_sessions[uid] = {
                "client": qr_client,
                "uid": uid,
                "timestamp": time.time(),
                "admin_id": sess["admin_id"],
                "owner": sess["owner"],
                "phone": "QR_LINKED"
            }
            qr_pending_sessions.pop(uid, None)
            add_log(f"🔐 2FA Password Required for QR session {uid}")
            return web.json_response({"status": "2fa_required", "uid": uid}, headers=make_cors_headers())
        return web.json_response({"status": "error", "message": err_str}, headers=make_cors_headers())

@routes.post("/userbot/disconnect")
async def api_ub_disconnect(request):
    data = await request.json()
    uid = data.get("uid")
    if uid in running_userbots:
        try:
            await running_userbots[uid]["client"].disconnect()
        except Exception: pass
        running_userbots.pop(uid, None)

    # Purge from SQLite
    await execute_db_query("DELETE FROM userbot_sessions WHERE phone_or_id=?", (uid,), commit=True)
    # Purge from MongoDB Atlas
    mongo_delete_userbot(uid)
    add_log(f"🔌 Userbot '{uid}' unlinked and purged from MongoDB Atlas & SQLite.")
    return web.json_response({"status": "ok"}, headers=make_cors_headers())

@routes.post("/userbot/set_admin")
async def api_ub_set_admin(request):
    data = await request.json()
    uid = data.get("uid")
    admin_id = str(data.get("admin_id", "")).strip()

    if uid in running_userbots:
        running_userbots[uid]["admin_id"] = admin_id

    await execute_db_query("UPDATE userbot_sessions SET admin_id=? WHERE phone_or_id=?", (admin_id, uid), commit=True)
    if admin_id and admin_id.isdigit():
        await execute_db_query("INSERT OR REPLACE INTO userbot_admins VALUES (?, ?)", (int(admin_id), uid), commit=True)

    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_userbot_sessions"].update_one(
                {"_id": str(uid)},
                {"$set": {"admin_id": admin_id, "updatedAt": str(datetime.utcnow())}}
            )
        except Exception: pass

    add_log(f"👑 Userbot '{uid}' Admin ID updated to: {admin_id}")
    return web.json_response({"status": "ok", "admin_id": admin_id}, headers=make_cors_headers())

@routes.post("/swarm/save")
async def api_swarm_save(request):
    data = await request.json()
    swarm_id = data.get("swarm_id", f"swarm_{int(time.time())}")
    owner = data.get("owner", "owner")
    admin_id = str(data.get("admin_id", MASTER_ADMIN_DEFAULT)).strip()
    raw_tokens = data.get("tokens", [])
    if isinstance(raw_tokens, str):
        tokens = [t.strip() for t in raw_tokens.replace(",", "\n").split("\n") if t.strip()]
    else:
        tokens = [str(t).strip() for t in raw_tokens if str(t).strip()]

    prefix = data.get("prefix", "-")
    burst_limit = int(data.get("burst_limit", 5))
    spam_delay = float(data.get("spam_delay", 0.001))
    nc_delay = int(data.get("nc_delay", 5))

    tokens_json = json.dumps(tokens)
    await execute_db_query(
        "INSERT OR REPLACE INTO tg_swarm_configs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (swarm_id, owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay, datetime.now().strftime("%Y-%m-%d %H:%M")),
        commit=True
    )

    mongo_save_swarm(swarm_id, owner, admin_id, tokens, prefix, burst_limit, spam_delay, nc_delay)

    if swarm_id in running_swarms:
        await running_swarms[swarm_id].stop()

    manager = BotSwarmManager(swarm_id, owner, admin_id, tokens, prefix, burst_limit, spam_delay, nc_delay)
    running_swarms[swarm_id] = manager
    await manager.start()

    return web.json_response({"status": "ok", "swarm_id": swarm_id, "bots_count": len(tokens)}, headers=make_cors_headers())

@routes.post("/swarm/stop")
async def api_swarm_stop(request):
    data = await request.json()
    swarm_id = data.get("swarm_id")
    if swarm_id in running_swarms:
        await running_swarms[swarm_id].stop()
    return web.json_response({"status": "ok"}, headers=make_cors_headers())

@routes.post("/swarm/start")
async def api_swarm_start(request):
    data = await request.json()
    swarm_id = data.get("swarm_id")
    if swarm_id in running_swarms:
        await running_swarms[swarm_id].start()
        return web.json_response({"status": "ok"}, headers=make_cors_headers())

    row = await execute_db_query("SELECT owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay FROM tg_swarm_configs WHERE swarm_id=?", (swarm_id,), fetchone=True)
    if row:
        owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay = row
        tokens = json.loads(tokens_json)
        manager = BotSwarmManager(swarm_id, owner, admin_id, tokens, prefix, burst_limit, spam_delay, nc_delay)
        running_swarms[swarm_id] = manager
        await manager.start()
        return web.json_response({"status": "ok"}, headers=make_cors_headers())

    return web.json_response({"status": "not_found"}, status=404, headers=make_cors_headers())

@routes.post("/swarm/delete")
async def api_swarm_delete(request):
    data = await request.json()
    swarm_id = data.get("swarm_id")
    if swarm_id in running_swarms:
        await running_swarms[swarm_id].stop()
        running_swarms.pop(swarm_id, None)

    await execute_db_query("DELETE FROM tg_swarm_configs WHERE swarm_id=?", (swarm_id,), commit=True)
    mongo_delete_swarm(swarm_id)
    add_log(f"🗑 Swarm '{swarm_id}' purged from MongoDB Atlas & SQLite.")
    return web.json_response({"status": "ok"}, headers=make_cors_headers())

@routes.get("/status")
async def api_all_status(request):
    userbots_data = {}
    for uid, ub in running_userbots.items():
        userbots_data[uid] = {
            "uid": uid,
            "name": ub.get("name", "Userbot"),
            "id": ub.get("id"),
            "phone": ub.get("phone", ""),
            "admin_id": ub.get("admin_id", ""),
            "owner": ub.get("owner", ""),
            "status": "ONLINE",
            "isOnline": True
        }

    rows = await execute_db_query("SELECT phone_or_id, first_name, user_id, owner, admin_id FROM userbot_sessions", fetchall=True)
    if rows:
        for r in rows:
            p_id, fname, u_id, owner, admin_id = r[0], r[1], r[2], r[3], r[4]
            if p_id not in userbots_data:
                userbots_data[p_id] = {
                    "uid": p_id,
                    "name": fname,
                    "id": u_id,
                    "phone": p_id,
                    "admin_id": admin_id,
                    "owner": owner,
                    "status": "SAVED",
                    "isOnline": False
                }

    swarms_data = {}
    for sid, sw in running_swarms.items():
        swarms_data[sid] = {
            "swarm_id": sid,
            "owner": sw.owner,
            "admin_id": sw.admin_id,
            "bots_count": len(sw.bots),
            "bot_usernames": sw.bot_usernames,
            "tokens": sw.tokens,
            "prefix": sw.prefix,
            "burst_limit": sw.burst_limit,
            "spam_delay": sw.spam_delay,
            "nc_delay": sw.nc_delay,
            "is_running": sw.is_running,
            "sent": sw.sent_count,
            "failed": sw.failed_count,
            "uptime": int(time.time() - sw.start_time) if sw.is_running else 0
        }

    sw_rows = await execute_db_query("SELECT swarm_id, owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay FROM tg_swarm_configs", fetchall=True)
    if sw_rows:
        for r in sw_rows:
            sid, owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay = r
            if sid not in swarms_data:
                tokens = json.loads(tokens_json)
                swarms_data[sid] = {
                    "swarm_id": sid,
                    "owner": owner,
                    "admin_id": admin_id,
                    "bots_count": len(tokens),
                    "bot_usernames": [],
                    "tokens": tokens,
                    "prefix": prefix,
                    "burst_limit": burst_limit,
                    "spam_delay": spam_delay,
                    "nc_delay": nc_delay,
                    "is_running": False,
                    "sent": 0,
                    "failed": 0,
                    "uptime": 0
                }

    return web.json_response({
        "userbots": userbots_data,
        "swarms": swarms_data,
        "logs": global_tg_logs[-60:]
    }, headers=make_cors_headers())

# ==============================================================================
# RESTORE SAVED SESSIONS FROM MONGODB ATLAS & SQLITE
# ==============================================================================
async def restore_all_saved_sessions():
    add_log("🔄 Restoring saved Userbots from MongoDB Atlas & Database...")
    restored_uids = set()

    # 1. First priority: Load from MongoDB Atlas
    if mongo_connected and mongo_db is not None:
        try:
            mongo_ub_docs = list(mongo_db["tg_userbot_sessions"].find({}))
            for doc in mongo_ub_docs:
                uid = doc.get("uid") or doc.get("_id")
                sess_str = doc.get("session_str")
                fname = doc.get("first_name", "Userbot")
                user_id = doc.get("user_id", 0)
                owner = doc.get("owner", "owner")
                admin_id = doc.get("admin_id", str(user_id))

                if uid and sess_str and uid not in restored_uids:
                    try:
                        cli = TelegramClient(StringSession(sess_str), API_ID, API_HASH, connection_retries=15, retry_delay=2, auto_reconnect=True, timeout=30, request_retries=5)
                        await cli.connect()
                        if await cli.is_user_authorized():
                            me = await cli.get_me()
                            setup_userbot_handlers(cli, str(uid), str(admin_id), me.id)
                            running_userbots[str(uid)] = {
                                "client": cli,
                                "me": me,
                                "phone": str(uid),
                                "admin_id": str(admin_id),
                                "owner": owner,
                                "session_str": sess_str,
                                "name": me.first_name,
                                "id": me.id
                            }
                            restored_uids.add(str(uid))
                            add_log(f"🍃 [MONGODB ATLAS] Restored Userbot: {me.first_name} (ID: {me.id})")
                            asyncio.create_task(safe_run_telethon_client(cli, str(uid), me.first_name))
                    except Exception as e:
                        add_log(f"❌ Failed to restore Atlas userbot {uid}: {e}")
        except Exception as ex:
            add_log(f"⚠️ Mongo restore exception: {ex}")

    # 2. Second fallback: Load from SQLite
    ub_rows = await execute_db_query("SELECT phone_or_id, session_str, first_name, user_id, owner, admin_id FROM userbot_sessions", fetchall=True)
    if ub_rows:
        for r in ub_rows:
            phone_key, sess_str, fname, uid, owner, admin_id = r
            if str(phone_key) not in restored_uids:
                try:
                    cli = TelegramClient(StringSession(sess_str), API_ID, API_HASH, connection_retries=15, retry_delay=2, auto_reconnect=True, timeout=30, request_retries=5)
                    await cli.connect()
                    if await cli.is_user_authorized():
                        me = await cli.get_me()
                        setup_userbot_handlers(cli, str(phone_key), str(admin_id), me.id)
                        running_userbots[str(phone_key)] = {
                            "client": cli,
                            "me": me,
                            "phone": str(phone_key),
                            "admin_id": str(admin_id),
                            "owner": owner,
                            "session_str": sess_str,
                            "name": me.first_name,
                            "id": me.id
                        }
                        restored_uids.add(str(phone_key))
                        mongo_save_userbot(str(phone_key), sess_str, me.first_name, me.id, owner, str(admin_id))
                        add_log(f"⚡ Saved Userbot Restored: {me.first_name} (ID: {me.id})")
                        asyncio.create_task(safe_run_telethon_client(cli, str(phone_key), me.first_name))
                except Exception as e:
                    add_log(f"❌ Failed to restore SQLite userbot {phone_key}: {e}")

    # Restore Swarms
    add_log("🔄 Restoring saved Multi-Bot Swarms from MongoDB Atlas & Database...")
    restored_swarms = set()

    if mongo_connected and mongo_db is not None:
        try:
            mongo_swarms = list(mongo_db["tg_swarm_configs"].find({}))
            for doc in mongo_swarms:
                sid = doc.get("swarm_id") or doc.get("_id")
                owner = doc.get("owner", "owner")
                admin_id = doc.get("admin_id", MASTER_ADMIN_DEFAULT)
                tokens = doc.get("tokens", [])
                prefix = doc.get("prefix", "-")
                burst_limit = doc.get("burst_limit", 5)
                spam_delay = doc.get("spam_delay", 0.001)
                nc_delay = doc.get("nc_delay", 5)

                if sid and tokens and sid not in restored_swarms:
                    try:
                        manager = BotSwarmManager(sid, owner, str(admin_id), tokens, prefix, burst_limit, spam_delay, nc_delay)
                        running_swarms[sid] = manager
                        restored_swarms.add(sid)
                        await manager.start()
                    except Exception as e:
                        add_log(f"❌ Failed to restore Atlas swarm {sid}: {e}")
        except Exception as ex:
            add_log(f"⚠️ Mongo swarm restore exception: {ex}")

    sw_rows = await execute_db_query("SELECT swarm_id, owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay FROM tg_swarm_configs", fetchall=True)
    if sw_rows:
        for r in sw_rows:
            sid, owner, admin_id, tokens_json, prefix, burst_limit, spam_delay, nc_delay = r
            if sid not in restored_swarms:
                try:
                    tokens = json.loads(tokens_json)
                    if tokens:
                        manager = BotSwarmManager(sid, owner, str(admin_id), tokens, prefix, burst_limit, spam_delay, nc_delay)
                        running_swarms[sid] = manager
                        restored_swarms.add(sid)
                        await manager.start()
                except Exception as e:
                    add_log(f"❌ Failed to restore SQLite swarm {sid}: {e}")

# ==============================================================================
# MAIN ASYNC LAUNCHER
# ==============================================================================
async def main():
    asyncio.create_task(memory_monitor())
    run_all_bots()

    app = web.Application()
    app.add_routes(routes)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", SERVICE_PORT)
    await site.start()

    add_log(f"========================================================================")
    add_log(f"👑 TELEGRAM MASTER ENGINE RUNNING ON http://127.0.0.1:{SERVICE_PORT}")
    add_log(f"🍃 MongoDB Atlas Database Cloud Persistence Active: 'igtgwp_db'")
    add_log(f"⚡ Dual Engine: Telethon Userbot + Multi-Bot PTB/Telebot Matrix Active")
    add_log(f"========================================================================")

    await restore_all_saved_sessions()
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        add_log("🛑 Telegram Master Service Shutting Down...")
        sys.exit(0)
