# ============================================================
#   smsotps.com Telegram Bot  |  English Version
#   API: https://api.smsotps.com/api
# ============================================================

import telebot
from telebot import types
import requests
import json
import os
import sys
import threading
import time
from datetime import datetime

# Windows UTF-8 fix
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────── Config ───────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
USERS_FILE  = os.path.join(BASE_DIR, "users.json")

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

BOT_TOKEN = CONFIG["bot_token"]
ADMIN_ID  = int(CONFIG["admin_id"])

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ─────────────── API Constants ───────────────
API_BASE = "https://api.smsotps.com/api"
CDN_BASE = "https://smsotps.com"

PROVIDERS = {
    "A": "provider_a",
    "B": "provider_b",
    "D": "provider_d",
}

# ─────────────── User Data ───────────────
def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(data: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(uid: int) -> dict:
    return load_users().get(str(uid), {})

def set_user(uid: int, data: dict):
    users = load_users()
    users[str(uid)] = data
    save_users(users)

def update_user(uid: int, **kwargs):
    u = get_user(uid)
    u.update(kwargs)
    set_user(uid, u)

# ─────────────── Cache ───────────────
_cache = {}

# ─────────────── Cancel Flags (bulk order thread stop) ───────────────
_cancel_flags: set = set()  # group_ids that have been cancelled

def cached_get(url: str, ttl: int = 3600):
    now = time.time()
    if url in _cache and now - _cache[url]["ts"] < ttl:
        return _cache[url]["data"]
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if r.ok:
            _cache[url] = {"data": r.json(), "ts": now}
            return _cache[url]["data"]
    except Exception:
        pass
    return None

# ─────────────── smsotps API ───────────────
class SMSOtpsAPI:
    def __init__(self, api_key: str):
        self.key = api_key
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
        }

    def _get(self, path: str):
        try:
            r = requests.get(f"{API_BASE}{path}", headers=self.headers, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path: str, body: dict = None):
        try:
            r = requests.post(f"{API_BASE}{path}", headers=self.headers, json=body or {}, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def balance(self):
        return self._get("/balance")

    def order_number(self, provider, service, country, max_price=None):
        body = {"provider": provider, "service": service, "country": country}
        if max_price:
            body["max_price"] = max_price
        return self._post("/order-number", body)

    def number_status(self, order_id: int):
        return self._get(f"/number-status/{order_id}")

    def cancel_number(self, order_id: int):
        return self._post(f"/cancel-number/{order_id}")

    def resend_sms(self, order_id: int):
        return self._post(f"/resend-sms/{order_id}")

    def offers(self, provider_letter: str, service: str, country: int):
        return self._get(f"/p_{provider_letter.lower()}/offers/{service}/{country}")

    def validate_key(self) -> bool:
        return "balance" in self.balance()

# ─────────────── Data Loaders ───────────────
def get_countries(provider_letter: str) -> dict:
    return cached_get(f"{CDN_BASE}/provider_{provider_letter.lower()}_countries.json") or {}

def get_services(provider_letter: str) -> dict:
    return cached_get(f"{CDN_BASE}/provider_{provider_letter.lower()}_services.json") or {}

# ─────────────── Helpers ───────────────
def strip_country_code(number: str) -> str:
    """Remove international country code prefix, return local subscriber number."""
    num = number.lstrip('+')
    # Try longest codes first to avoid false matches
    codes_3 = [
        '370','371','372','373','374','375','376','377','378','379',
        '380','381','382','383','385','386','387','389',
        '420','421','423',
        '500','501','502','503','504','505','506','507','508','509',
        '590','591','592','593','594','595','596','597','598','599',
        '670','672','673','674','675','676','677','678','679',
        '680','681','682','683','685','686','687','688','689',
        '690','691','692',
        '850','852','853','855','856',
        '880','886',
        '960','961','962','963','964','965','966','967','968',
        '970','971','972','973','974','975','976','977',
        '992','993','994','995','996','998',
    ]
    codes_2 = [
        '20','27','30','31','32','33','34','36','39',
        '40','41','43','44','45','46','47','48','49',
        '51','52','53','54','55','56','57','58',
        '60','61','62','63','64','65','66',
        '81','82','84','86',
        '90','91','92','93','94','95','98',
    ]
    codes_1 = ['1', '7']
    for code in codes_3:
        if num.startswith(code):
            return num[3:]
    for code in codes_2:
        if num.startswith(code):
            return num[2:]
    for code in codes_1:
        if num.startswith(code):
            return num[1:]
    return num

def flag(country_name: str) -> str:
    flags = {
        "USA": "🇺🇸", "United Kingdom": "🇬🇧", "Russia": "🇷🇺",
        "Ukraine": "🇺🇦", "Germany": "🇩🇪", "France": "🇫🇷",
        "India": "🇮🇳", "China": "🇨🇳", "Bangladesh": "🇧🇩",
        "Pakistan": "🇵🇰", "Indonesia": "🇮🇩", "Philippines": "🇵🇭",
        "Turkey": "🇹🇷", "Brazil": "🇧🇷", "Canada": "🇨🇦",
        "Australia": "🇦🇺", "Japan": "🇯🇵", "South Korea": "🇰🇷",
        "Vietnam": "🇻🇳", "Thailand": "🇹🇭", "Malaysia": "🇲🇾",
        "Singapore": "🇸🇬", "Mexico": "🇲🇽", "Spain": "🇪🇸",
        "Italy": "🇮🇹", "Poland": "🇵🇱", "Netherlands": "🇳🇱",
        "Belgium": "🇧🇪", "Sweden": "🇸🇪", "Norway": "🇳🇴",
        "Saudi Arabia": "🇸🇦", "UAE": "🇦🇪", "Egypt": "🇪🇬",
        "Nigeria": "🇳🇬", "South Africa": "🇿🇦", "Kenya": "🇰🇪",
        "Argentina": "🇦🇷", "Colombia": "🇨🇴", "Chile": "🇨🇱",
        "Romania": "🇷🇴", "Kazakhstan": "🇰🇿", "Uzbekistan": "🇺🇿",
        "Myanmar": "🇲🇲", "Cambodia": "🇰🇭", "Iran": "🇮🇷",
        "Iraq": "🇮🇶", "Israel": "🇮🇱", "Portugal": "🇵🇹",
        "Greece": "🇬🇷", "Czech": "🇨🇿", "Hungary": "🇭🇺",
        "Hong Kong": "🇭🇰", "Taiwan": "🇹🇼", "Morocco": "🇲🇦",
    }
    return flags.get(country_name, "🌐")

def service_emoji(name: str) -> str:
    emojis = {
        "Telegram": "✈️", "Whatsapp": "💬", "facebook": "📘",
        "Instagram": "📸", "Google": "🔍", "Twitter": "🐦",
        "TikTok": "🎵", "Discord": "🎮", "Snapchat": "👻",
        "Amazon": "📦", "Uber": "🚗", "Apple": "🍎",
        "Microsoft": "🪟", "Netflix": "🎬", "Steam": "🎮",
        "OpenAI": "🤖", "Tinder": "❤️", "LinkedIn": "💼",
    }
    for k, v in emojis.items():
        if k.lower() in name.lower():
            return v
    return "📱"

def is_logged_in(uid: int) -> bool:
    return bool(get_user(uid).get("api_key"))

def get_api(uid: int):
    u = get_user(uid)
    return SMSOtpsAPI(u["api_key"]) if u.get("api_key") else None

# ─────────────── Keyboards ───────────────
def main_menu_keyboard(uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Balance",       callback_data="balance"),
        types.InlineKeyboardButton("📱 Buy Number",    callback_data="buy_menu"),
    )
    kb.add(
        types.InlineKeyboardButton("📋 My Orders",     callback_data="my_orders"),
        types.InlineKeyboardButton("📜 History",       callback_data="history"),
    )
    kb.add(
        types.InlineKeyboardButton("🔑 Change API Key", callback_data="change_key"),
        types.InlineKeyboardButton("❌ Logout",         callback_data="logout"),
    )
    if uid == ADMIN_ID:
        kb.add(types.InlineKeyboardButton("👑 Admin Panel", callback_data="admin"))
    return kb

def back_keyboard(dest: str = "main") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data=f"back_{dest}"))
    return kb

def provider_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("🅰️ Provider A", callback_data="prov_A"),
        types.InlineKeyboardButton("🅱️ Provider B", callback_data="prov_B"),
        types.InlineKeyboardButton("🅳 Provider D", callback_data="prov_D"),
    )
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return kb



def reply_keyboard(uid: int = 0) -> types.ReplyKeyboardMarkup:
    """Persistent bottom keyboard — mirrors the Main Menu inline buttons."""
    kb = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    kb.add(
        types.KeyboardButton("💰 Balance"),
        types.KeyboardButton("📱 Buy Number"),
    )
    kb.add(
        types.KeyboardButton("📋 My Orders"),
        types.KeyboardButton("📜 History"),
    )
    kb.add(
        types.KeyboardButton("🔑 Change API Key"),
        types.KeyboardButton("❌ Logout"),
    )
    return kb

# ─────────────── Register Bot Commands (Left Menu) ───────────────
def register_commands():
    commands = [
        types.BotCommand("start",   "▶️ Start / Main Menu"),
        types.BotCommand("menu",    "🏠 Show Menu"),
        types.BotCommand("balance", "💰 Check Balance"),
        types.BotCommand("buy",     "📱 Buy a Number"),
        types.BotCommand("orders",  "📋 My Active Orders"),
        types.BotCommand("history", "📜 Order History"),
        types.BotCommand("logout",  "❌ Logout"),
    ]
    try:
        bot.set_my_commands(commands)
        print("[*] Bot commands registered successfully.")
    except Exception as e:
        print(f"[!] Failed to register commands: {e}")

# ─────────────── /start ───────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    if is_logged_in(uid):
        bot.send_message(
            uid,
            f"👋 <b>Welcome back!</b>\n\nUse the menu below to get started 👇",
            reply_markup=reply_keyboard(),
        )
    else:
        update_user(uid, state="awaiting_key")
        bot.send_message(
            uid,
            "👋 <b>Welcome to smsotps Bot!</b>\n\n"
            "📌 Please send your <b>smsotps API Key</b> to login.\n\n"
            "🔗 Get your API Key at: <a href='https://smsotps.com/profile'>smsotps.com/profile</a>",
        )

@bot.message_handler(commands=["menu"])
def cmd_menu(msg: types.Message):
    uid = msg.from_user.id
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return
    bot.send_message(uid, "🏠 <b>Main Menu</b>", reply_markup=main_menu_keyboard(uid),
                     )

@bot.message_handler(commands=["balance"])
def cmd_balance(msg: types.Message):
    uid = msg.from_user.id
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return
    api = get_api(uid)
    result = api.balance()
    if "balance" in result:
        bot.send_message(uid, f"💰 <b>Balance:</b> ${result['balance']} {result.get('currency','USD')}")
    else:
        bot.send_message(uid, "❌ Failed to fetch balance.")

@bot.message_handler(commands=["buy"])
def cmd_buy(msg: types.Message):
    uid = msg.from_user.id
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return
    bot.send_message(uid, "📱 <b>Buy Number</b>\n\nSelect a Provider:", reply_markup=provider_keyboard())

@bot.message_handler(commands=["orders"])
def cmd_orders(msg: types.Message):
    uid = msg.from_user.id
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return
    _show_my_orders_msg(uid)

@bot.message_handler(commands=["history"])
def cmd_history(msg: types.Message):
    uid = msg.from_user.id
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return
    _show_history_msg(uid)

@bot.message_handler(commands=["logout"])
def cmd_logout(msg: types.Message):
    uid = msg.from_user.id
    set_user(uid, {})
    bot.send_message(uid, "👋 You have been logged out. Use /start to login again.")

# ─────────────── Message Handler ───────────────
@bot.message_handler(func=lambda m: True)
def handle_text(msg: types.Message):
    uid  = msg.from_user.id
    text = msg.text.strip()
    u    = get_user(uid)
    state = u.get("state", "")

    # API Key
    if state == "awaiting_key":
        api = SMSOtpsAPI(text)
        bot.send_message(uid, "⏳ Validating API Key...")
        if api.validate_key():
            update_user(uid, api_key=text, state="", orders={})
            bal = api.balance()
            bot.send_message(
                uid,
                f"✅ <b>Login Successful!</b>\n\n"
                f"💰 Balance: <b>${bal.get('balance','?')} {bal.get('currency','USD')}</b>\n\n"
                f"Use the menu below 👇",
                reply_markup=reply_keyboard(uid),
            )
            bot.send_message(
                uid,
                "🏠 <b>Main Menu</b>",
                reply_markup=main_menu_keyboard(uid),
            )
        else:
            bot.send_message(
                uid,
                "❌ <b>Invalid API Key!</b>\n\n"
                "Please try again or get your key from "
                "<a href='https://smsotps.com/profile'>smsotps.com/profile</a>",
            )
        return

    # Country search
    if state == "awaiting_country_search":
        s     = u.get("buy_session", {})
        prov  = s.get("prov_letter", "A")
        query = text.strip().lower()
        update_user(uid, state="")
        _search_countries(uid, msg, prov, query)
        return

    # Quantity
    if state == "awaiting_quantity":
        s = u.get("buy_session", {})
        try:
            qty = int(text)
            if qty < 1 or qty > 50:
                raise ValueError
        except ValueError:
            bot.send_message(uid, "❌ Please enter a number between 1 and 50.")
            return
        s["quantity"] = qty
        update_user(uid, buy_session=s, last_buy_session=s, state="")
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Buy Now",   callback_data="confirm_order"),
            types.InlineKeyboardButton("💲 Max Price", callback_data="set_max_price"),
        )
        kb.add(types.InlineKeyboardButton("❌ Cancel", callback_data="back_main"))
        countries = get_countries(s.get("prov_letter", "A"))
        services  = get_services(s.get("prov_letter", "A"))
        cname = countries.get(str(s.get("country", "")), {}).get("name", "?")
        sname = services.get(s.get("service", ""), s.get("service", "?"))
        max_p_str = f" | Max: ${s['max_price']}" if s.get("max_price") else ""
        bot.send_message(
            uid,
            f"📦 <b>Confirm Order</b>\n\n"
            f"📱 Service: <b>{sname}</b>\n"
            f"🌍 Country: <b>{flag(cname)} {cname}</b>\n"
            f"🔢 Quantity: <b>{qty}</b>{max_p_str}\n\n"
            f"⚠️ Balance will be deducted upon purchase.",
            reply_markup=kb,
        )
        return

    # Max Price
    if state == "awaiting_max_price":
        s = u.get("buy_session", {})
        try:
            max_p = float(text)
        except ValueError:
            bot.send_message(uid, "❌ Enter a valid number (e.g. 0.15)")
            return
        s["max_price"] = max_p
        update_user(uid, buy_session=s, state="awaiting_quantity")
        bot.send_message(uid, f"✅ Max Price set to ${max_p}\n\nHow many numbers do you want? (1–50)")
        return

    # ─── Reply Keyboard Button Handlers (mirrors Main Menu) ───
    if not is_logged_in(uid):
        bot.send_message(uid, "⚠️ Please login first. Send /start")
        return

    if text == "💰 Balance":
        api2   = get_api(uid)
        result = api2.balance()
        if "balance" in result:
            bot.send_message(
                uid,
                f"💰 <b>Your Balance</b>\n\n"
                f"💵 Amount: <b>${result['balance']}</b>\n"
                f"💱 Currency: {result.get('currency','USD')}\n\n"
                f"🕒 Updated: {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            bot.send_message(uid, "❌ Failed to fetch balance.")
        return

    if text == "📱 Buy Number":
        bot.send_message(uid, "📱 <b>Buy Number</b>\n\nSelect a Provider:", reply_markup=provider_keyboard())
        return

    if text == "📋 My Orders":
        _show_my_orders_msg(uid)
        return

    if text == "📜 History":
        _show_history_msg(uid)
        return

    if text == "🔑 Change API Key":
        update_user(uid, state="awaiting_key")
        bot.send_message(uid, "🔑 Please send your new API Key:")
        return

    if text == "❌ Logout":
        set_user(uid, {})
        bot.send_message(
            uid,
            "👋 You have been logged out.\nUse /start to login again.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    bot.send_message(uid, "ℹ️ Use /menu or the buttons below.")

# ─────────────── Callback Handler ───────────────
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call: types.CallbackQuery):
    uid  = call.from_user.id
    data = call.data
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if not is_logged_in(uid) and data not in ("back_main",):
        bot.send_message(uid, "⚠️ Please login first with /start")
        return

    if data == "balance":
        _show_balance(uid, call.message)

    elif data == "buy_menu":
        bot.edit_message_text(
            "📱 <b>Buy Number</b>\n\nSelect a Provider:",
            uid, call.message.message_id,
            reply_markup=provider_keyboard(),
        )

    elif data.startswith("prov_"):
        prov = data.split("_")[1]
        update_user(uid, buy_session={"provider": PROVIDERS[prov], "prov_letter": prov})
        _show_services(uid, call.message, prov)

    elif data.startswith("svc_"):
        parts = data.split("_", 2)
        prov, svc_code = parts[1], parts[2]
        s = get_user(uid).get("buy_session", {})
        s["service"] = svc_code
        update_user(uid, buy_session=s)
        _show_countries(uid, call.message, prov, page=0)

    elif data.startswith("cpage_"):
        parts = data.split("_")
        prov, page = parts[1], int(parts[2])
        _show_countries(uid, call.message, prov, page)

    elif data.startswith("csearch_"):
        prov = data.split("_")[1]
        update_user(uid, state="awaiting_country_search")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("❌ Cancel", callback_data=f"cpage_{prov}_0"))
        bot.send_message(
            uid,
            f"🔍 <b>Search Country</b> (Provider {prov})\n\n"
            f"Type a country name or part of it:\n"
            f"<i>Example: Bangladesh, USA, India...</i>",
            reply_markup=kb,
        )

    elif data.startswith("ctry_"):
        parts = data.split("_", 2)
        prov, cid = parts[1], parts[2]
        s = get_user(uid).get("buy_session", {})
        s["country"] = int(cid)
        update_user(uid, buy_session=s)
        _show_offers(uid, call.message, s)

    elif data.startswith("qty_"):
        val = data.split("_")[1]
        s   = get_user(uid).get("buy_session", {})
        if val == "custom":
            update_user(uid, state="awaiting_quantity", buy_session=s)
            bot.send_message(uid, "✏️ How many numbers do you want? (1–50)")
        else:
            qty = int(val)
            s["quantity"] = qty
            # ✅ Save session so user can quickly buy again with same settings
            update_user(uid, buy_session=s, last_buy_session=s)
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("✅ Buy Now",   callback_data="confirm_order"),
                types.InlineKeyboardButton("💲 Max Price", callback_data="set_max_price"),
            )
            kb.add(types.InlineKeyboardButton("❌ Cancel", callback_data="back_main"))
            countries_d = get_countries(s.get("prov_letter", "A"))
            services_d  = get_services(s.get("prov_letter", "A"))
            cname_d = countries_d.get(str(s.get("country", "")), {}).get("name", "?")
            sname_d = services_d.get(s.get("service", ""), s.get("service", "?"))
            bot.send_message(
                uid,
                f"📦 <b>Confirm Order</b>\n\n"
                f"📱 Service: <b>{sname_d}</b>\n"
                f"🌍 Country: <b>{flag(cname_d)} {cname_d}</b>\n"
                f"🔢 Quantity: <b>{qty}</b>\n\n"
                f"⚠️ Balance will be deducted upon purchase.",
                reply_markup=kb,
            )

    elif data == "confirm_order":
        s   = get_user(uid).get("buy_session", {})
        qty = s.get("quantity", 1)
        if qty > 1:
            threading.Thread(target=_do_bulk_order, args=(uid, s), daemon=True).start()
        else:
            _do_order(uid, s)

    elif data.startswith("bulk_cancel_"):
        group_id = data.split("_", 2)[2]
        _bulk_cancel(uid, call.message, group_id)

    elif data.startswith("bulk_again_"):
        group_id = data.split("_", 2)[2]
        threading.Thread(target=_bulk_cancel_and_again, args=(uid, call.message, group_id), daemon=True).start()

    elif data == "set_max_price":
        update_user(uid, state="awaiting_max_price")
        bot.send_message(uid, "💬 Enter max price per number (e.g. <code>0.15</code>):")

    elif data == "my_orders":
        _show_my_orders(uid, call.message)

    elif data.startswith("order_"):
        oid = data.split("_")[1]
        _show_order_detail(uid, call.message, oid)

    elif data.startswith("check_"):
        oid = data.split("_")[1]
        _check_otp(uid, call.message, oid)

    elif data.startswith("cancel_"):
        oid = data.split("_")[1]
        _cancel_order(uid, call.message, oid)

    elif data.startswith("resend_"):
        oid = data.split("_")[1]
        _resend_otp(uid, call.message, oid)

    elif data == "history":
        _show_history(uid, call.message)

    elif data == "change_key":
        update_user(uid, state="awaiting_key")
        bot.send_message(uid, "🔑 Please send your new API Key:")

    elif data == "logout":
        set_user(uid, {})
        bot.edit_message_text(
            "👋 You have been logged out.\nUse /start to login again.",
            uid, call.message.message_id,
        )

    elif data == "admin" and uid == ADMIN_ID:
        _show_admin(uid, call.message)

    elif data == "back_main":
        bot.edit_message_text(
            "🏠 <b>Main Menu</b>",
            uid, call.message.message_id,
            reply_markup=main_menu_keyboard(uid),
        )
    elif data == "back_buy":
        bot.edit_message_text(
            "📱 <b>Buy Number</b>\n\nSelect a Provider:",
            uid, call.message.message_id,
            reply_markup=provider_keyboard(),
        )

    elif data == "buy_again_last":
        # ✅ Restore last buy session and go to offers screen
        u2 = get_user(uid)
        s  = u2.get("last_buy_session") or u2.get("last_bulk_session", {})
        if not s or not s.get("provider"):
            bot.send_message(uid, "⚠️ No previous session found. Please select from Buy Number.")
            bot.send_message(uid, "📱 <b>Buy Number</b>\n\nSelect a Provider:", reply_markup=provider_keyboard())
            return
        # Restore session (keep quantity from last time)
        update_user(uid, buy_session=s)
        countries_r = get_countries(s.get("prov_letter", "A"))
        services_r  = get_services(s.get("prov_letter", "A"))
        cname_r = countries_r.get(str(s.get("country", "")), {}).get("name", "?")
        sname_r = services_r.get(s.get("service", ""), s.get("service", "?"))
        prov_r  = s.get("prov_letter", "?")
        qty_r   = s.get("quantity", 1)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Buy Now",   callback_data="confirm_order"),
            types.InlineKeyboardButton("💲 Max Price", callback_data="set_max_price"),
        )
        kb.add(
            types.InlineKeyboardButton("🔢 Change Qty", callback_data="qty_custom"),
            types.InlineKeyboardButton("❌ Cancel",    callback_data="back_main"),
        )
        bot.send_message(
            uid,
            f"🔄 <b>Buy Again (Saved Settings)</b>\n\n"
            f"🏢 Provider: <b>Provider {prov_r}</b>\n"
            f"📱 Service: <b>{sname_r}</b>\n"
            f"🌍 Country: <b>{flag(cname_r)} {cname_r}</b>\n"
            f"🔢 Quantity: <b>{qty_r}</b>\n\n"
            f"⚠️ Balance will be deducted upon purchase.",
            reply_markup=kb,
        )

# ─────────────── Balance ───────────────
def _show_balance(uid: int, msg: types.Message):
    api    = get_api(uid)
    result = api.balance()
    if "balance" in result:
        text = (
            f"💰 <b>Your Balance</b>\n\n"
            f"💵 Amount: <b>${result['balance']}</b>\n"
            f"💱 Currency: {result.get('currency','USD')}\n\n"
            f"🕒 Updated: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        text = f"❌ Failed to load balance.\n<code>{result}</code>"
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔄 Refresh", callback_data="balance"),
        types.InlineKeyboardButton("⬅️ Back",    callback_data="back_main"),
    )
    bot.edit_message_text(text, uid, msg.message_id, reply_markup=kb)

# ─────────────── Services ───────────────
POPULAR_SERVICES = ["tg", "wa", "fb", "ig", "go", "tw", "ds", "dr", "mm", "am", "lf", "ub"]

def _show_services(uid: int, msg: types.Message, prov: str):
    services = get_services(prov)
    if not services:
        bot.send_message(uid, "❌ Failed to load services.")
        return
    kb = types.InlineKeyboardMarkup(row_width=2)
    popular = []
    for code in POPULAR_SERVICES:
        if code in services:
            name = services[code]
            popular.append(types.InlineKeyboardButton(
                f"{service_emoji(name)} {name[:18]}", callback_data=f"svc_{prov}_{code}"
            ))
    kb.add(*popular)
    others, count = [], 0
    for code, name in services.items():
        if code not in POPULAR_SERVICES and count < 20:
            others.append(types.InlineKeyboardButton(
                f"{service_emoji(name)} {name[:18]}", callback_data=f"svc_{prov}_{code}"
            ))
            count += 1
    if others:
        kb.add(*others)
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_buy"))
    bot.edit_message_text(
        f"📱 <b>Select Service</b> (Provider {prov})\n\n"
        "⭐ Popular services shown first:",
        uid, msg.message_id, reply_markup=kb,
    )

# ─────────────── Countries ───────────────
COUNTRIES_PER_PAGE  = 20
POPULAR_COUNTRIES   = [187, 16, 22, 60, 66, 10, 6, 52, 7, 4, 43, 78, 86, 56, 73]

def _show_countries(uid: int, msg: types.Message, prov: str, page: int):
    countries = get_countries(prov)
    if not countries:
        bot.send_message(uid, "❌ Failed to load countries.")
        return

    if page == 0:
        popular_items = [(str(k), v) for k, v in countries.items() if int(k) in POPULAR_COUNTRIES]
        rest          = [(k, v) for k, v in countries.items() if int(k) not in POPULAR_COUNTRIES]
        items         = popular_items + rest
    else:
        items = [(k, v) for k, v in countries.items() if int(k) not in POPULAR_COUNTRIES]

    total      = len(items)
    start      = page * COUNTRIES_PER_PAGE
    end        = start + COUNTRIES_PER_PAGE
    page_items = items[start:end]

    kb   = types.InlineKeyboardMarkup(row_width=2)
    btns = []
    for cid, cdata in page_items:
        cname = cdata["name"]
        btns.append(types.InlineKeyboardButton(
            f"{flag(cname)} {cname}", callback_data=f"ctry_{prov}_{cid}"
        ))
    kb.add(*btns)

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ Prev", callback_data=f"cpage_{prov}_{page-1}"))
    if end < total:
        nav.append(types.InlineKeyboardButton("Next ▶️", callback_data=f"cpage_{prov}_{page+1}"))
    if nav:
        kb.add(*nav)
    kb.add(
        types.InlineKeyboardButton("🔍 Search Country", callback_data=f"csearch_{prov}"),
        types.InlineKeyboardButton("⬅️ Back",           callback_data=f"prov_{prov}"),
    )

    bot.edit_message_text(
        f"🌍 <b>Select Country</b> (Provider {prov})\n"
        f"Page {page+1} / {(total // COUNTRIES_PER_PAGE) + 1} — {total} countries total\n"
        f"⚡ <i>Use 🔍 Search to find a specific country</i>",
        uid, msg.message_id, reply_markup=kb,
    )

# ─────────────── Country Search ───────────────
def _search_countries(uid: int, msg: types.Message, prov: str, query: str):
    countries = get_countries(prov)
    if not countries:
        bot.send_message(uid, "❌ Failed to load countries.")
        return

    matched = [(cid, cdata) for cid, cdata in countries.items() if query in cdata["name"].lower()]

    if not matched:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("🔍 Search Again", callback_data=f"csearch_{prov}"),
            types.InlineKeyboardButton("🌍 All Countries", callback_data=f"cpage_{prov}_0"),
        )
        bot.send_message(
            uid,
            f"❌ <b>No country found for '{query}'.</b>\n\nTry again or browse all countries.",
            reply_markup=kb,
        )
        return

    kb   = types.InlineKeyboardMarkup(row_width=2)
    btns = []
    for cid, cdata in matched[:30]:
        cname = cdata["name"]
        btns.append(types.InlineKeyboardButton(
            f"{flag(cname)} {cname}", callback_data=f"ctry_{prov}_{cid}"
        ))
    kb.add(*btns)
    kb.add(
        types.InlineKeyboardButton("🔍 Search Again",  callback_data=f"csearch_{prov}"),
        types.InlineKeyboardButton("🌍 All Countries", callback_data=f"cpage_{prov}_0"),
    )
    bot.send_message(
        uid,
        f"🔍 <b>Search results for '{query}'</b> ({len(matched)} found)\n\nSelect a country:",
        reply_markup=kb,
    )

# ─────────────── Offers ───────────────
def _show_offers(uid: int, msg: types.Message, s: dict):
    prov_letter = s.get("prov_letter", "A")
    api         = get_api(uid)
    offers_data = api.offers(prov_letter, s["service"], s["country"])
    countries   = get_countries(prov_letter)
    services    = get_services(prov_letter)
    cname = countries.get(str(s["country"]), {}).get("name", str(s["country"]))
    sname = services.get(s["service"], s["service"])

    text = (
        f"📋 <b>Order Details</b>\n\n"
        f"🏢 Provider: <b>Provider {prov_letter}</b>\n"
        f"📱 Service: <b>{sname}</b>\n"
        f"🌍 Country: <b>{flag(cname)} {cname}</b>\n\n"
    )

    if offers_data and "offers" in offers_data:
        offers = offers_data["offers"]
        if offers:
            best = min(offers, key=lambda x: float(x.get("price", 999)))
            text += (
                f"💰 Best Price: <b>${best.get('price','?')}</b>\n"
                f"📦 Available: <b>{best.get('available','?')} pcs</b>\n"
                f"📡 Operator: {best.get('operator','any')}\n\n"
            )
        else:
            text += "⚠️ No numbers available right now.\n\n"
    elif isinstance(offers_data, list) and offers_data:
        for item in offers_data:
            for offer in item.get("offers", []):
                text += f"💰 Price: <b>${offer.get('price','?')}</b> | 📦 {offer.get('count','?')} pcs\n"
        text += "\n"
    else:
        text += "⚠️ Could not load offers.\n\n"

    text += "👇 <b>How many numbers do you want?</b>"

    kb = types.InlineKeyboardMarkup(row_width=4)
    kb.add(
        types.InlineKeyboardButton("1️⃣ 1",  callback_data="qty_1"),
        types.InlineKeyboardButton("3️⃣ 3",  callback_data="qty_3"),
        types.InlineKeyboardButton("5️⃣ 5",  callback_data="qty_5"),
        types.InlineKeyboardButton("🔟 10", callback_data="qty_10"),
    )
    kb.add(
        types.InlineKeyboardButton("✏️ Custom",    callback_data="qty_custom"),
        types.InlineKeyboardButton("💲 Max Price", callback_data="set_max_price"),
    )
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data=f"cpage_{prov_letter}_0"))
    bot.edit_message_text(text, uid, msg.message_id, reply_markup=kb)

# ─────────────── Single Order ───────────────
MAX_PRICE_RETRY_INTERVAL = 10   # seconds between retries
MAX_PRICE_RETRY_LIMIT    = 180  # max retries (~30 minutes)

def _do_order(uid: int, s: dict):
    api       = get_api(uid)
    max_price = s.get("max_price")
    services  = get_services(s.get("prov_letter", "A"))
    countries = get_countries(s.get("prov_letter", "A"))
    sname     = services.get(s.get("service", ""), s.get("service", "?"))
    cname     = countries.get(str(s.get("country", "")), {}).get("name", "?")

    if max_price:
        status_msg = bot.send_message(
            uid,
            f"🔍 <b>Searching for number...</b>\n\n"
            f"📱 Service: <b>{sname}</b>\n"
            f"🌍 Country: <b>{flag(cname)} {cname}</b>\n"
            f"💲 Max Price: <b>${max_price}</b>\n\n"
            f"<i>⏳ Waiting for a number at or below max price. Will keep trying automatically...</i>\n"
            f"<code>Attempt 1 — searching...</code>",
        )
        kb_cancel = types.InlineKeyboardMarkup()
        kb_cancel.add(types.InlineKeyboardButton("❌ Stop Searching", callback_data="back_main"))
        try:
            bot.edit_message_reply_markup(uid, status_msg.message_id, reply_markup=kb_cancel)
        except Exception:
            pass
    else:
        status_msg = bot.send_message(uid, "⏳ Ordering number...")

    attempt = 0
    while True:
        attempt += 1
        try:
            # ❗ max_price API-তে পাঠাই না — API সঠিকভাবে filter করে না
            # বরং order করে price check করি, বেশি হলে cancel করি
            result = api.order_number(
                provider=s["provider"], service=s["service"],
                country=s["country"],
            )
        except Exception as e:
            result = {"error": str(e)}

        number   = result.get("number") or result.get("phone") or result.get("num") or result.get("telephone")
        order_id = str(result.get("id") or result.get("order_id") or result.get("activation_id") or "")

        if number and order_id:
            price_raw = result.get("price", 0)
            try:
                price_val = float(price_raw)
            except Exception:
                price_val = 0.0

            # 💲 Max price check — cancel if too expensive
            if max_price and price_val > float(max_price):
                # Cancel this overpriced number silently
                try:
                    api.cancel_number(int(order_id))
                except Exception:
                    pass
                err_hint = f"Price ${price_val:.4f} > max ${max_price} — cancelled, retrying..."
                if attempt >= MAX_PRICE_RETRY_LIMIT:
                    try:
                        bot.edit_message_text(
                            f"⏰ <b>Search Timed Out</b>\n\n"
                            f"Could not find a number at or below <b>${max_price}</b> after {attempt} attempts.",
                            uid, status_msg.message_id,
                            reply_markup=back_keyboard("main"),
                        )
                    except Exception:
                        pass
                    return
                try:
                    bot.edit_message_text(
                        f"🔍 <b>Searching for number...</b>\n\n"
                        f"📱 Service: <b>{sname}</b>\n"
                        f"🌍 Country: <b>{flag(cname)} {cname}</b>\n"
                        f"💲 Max Price: <b>${max_price}</b>\n\n"
                        f"<i>⏳ Retrying every {MAX_PRICE_RETRY_INTERVAL}s...</i>\n"
                        f"<code>Attempt {attempt} — {err_hint}</code>",
                        uid, status_msg.message_id,
                        reply_markup=kb_cancel,
                    )
                except Exception:
                    pass
                time.sleep(MAX_PRICE_RETRY_INTERVAL)
                continue

            # ✅ Price OK — save and notify
            price = price_raw
            u     = get_user(uid)
            orders = u.get("orders", {})
            orders[order_id] = {
                "id": order_id, "number": number,
                "service": s["service"], "provider": s["provider"],
                "country": s["country"], "price": price,
                "status": "active", "created_at": datetime.now().isoformat(), "otp": None,
            }
            update_user(uid, orders=orders, buy_session={})

            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("🔍 Check OTP", callback_data=f"check_{order_id}"),
                types.InlineKeyboardButton("🔄 Resend",    callback_data=f"resend_{order_id}"),
            )
            kb.add(
                types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{order_id}"),
                types.InlineKeyboardButton("🏠 Menu",   callback_data="back_main"),
            )
            try:
                bot.edit_message_text(
                    f"✅ <b>Number Received!</b>\n\n"
                    f"📞 Number: <code>{number}</code>\n"
                    f"🆔 Order ID: <code>{order_id}</code>\n"
                    f"💰 Price: ${price}" +
                    (f" ✔️ (Max: ${max_price})" if max_price else "") +
                    f"\n\n📋 Use this number and press Check OTP when the code arrives.\n"
                    f"⏰ Time limit: ~15 minutes",
                    uid, status_msg.message_id, reply_markup=kb,
                )
            except Exception:
                pass
            threading.Thread(target=_auto_poll_otp, args=(uid, order_id), daemon=True).start()
            return

        # ❌ No number returned (API error)
        if not max_price:
            try:
                bot.edit_message_text(
                    f"❌ <b>Order failed!</b>\n\n<code>{json.dumps(result, indent=2)}</code>",
                    uid, status_msg.message_id,
                )
            except Exception:
                pass
            return

        if attempt >= MAX_PRICE_RETRY_LIMIT:
            try:
                bot.edit_message_text(
                    f"⏰ <b>Search Timed Out</b>\n\n"
                    f"No number found at or below <b>${max_price}</b> after {attempt} attempts.",
                    uid, status_msg.message_id,
                    reply_markup=back_keyboard("main"),
                )
            except Exception:
                pass
            return

        err_hint = (
            result.get("message") or result.get("error") or
            result.get("detail") or str(result)
        )
        try:
            bot.edit_message_text(
                f"🔍 <b>Searching for number...</b>\n\n"
                f"📱 Service: <b>{sname}</b>\n"
                f"🌍 Country: <b>{flag(cname)} {cname}</b>\n"
                f"💲 Max Price: <b>${max_price}</b>\n\n"
                f"<i>⏳ No number found yet. Retrying every {MAX_PRICE_RETRY_INTERVAL}s...</i>\n"
                f"<code>Attempt {attempt} — {str(err_hint)[:80]}</code>",
                uid, status_msg.message_id,
                reply_markup=kb_cancel,
            )
        except Exception:
            pass

        time.sleep(MAX_PRICE_RETRY_INTERVAL)

# ─────────────── Bulk Order ───────────────
def _do_bulk_order(uid: int, s: dict):
    """Buy numbers one by one with 3s gap between each."""
    qty      = s.get("quantity", 1)
    api      = get_api(uid)
    group_id = str(int(time.time()))

    bought, failed = [], []

    services  = get_services(s.get("prov_letter", "A"))
    countries = get_countries(s.get("prov_letter", "A"))
    sname = services.get(s["service"], s["service"])
    cname = countries.get(str(s["country"]), {}).get("name", str(s["country"]))

    # প্রথম progress message
    progress_msg = bot.send_message(
        uid,
        f"⏳ <b>Starting bulk order...</b>\n"
        f"📱 {sname} | 🌍 {flag(cname)} {cname}\n"
        f"🔢 Total: {qty} numbers\n\n"
        f"<code>0 / {qty} done</code>"
    )

    for i in range(qty):
        # ─── Cancel check ───
        if group_id in _cancel_flags:
            _cancel_flags.discard(group_id)
            try:
                bot.edit_message_text(
                    f"🚫 <b>Bulk order cancelled by user.</b>\n"
                    f"✅ {len(bought)} bought before cancel.",
                    uid, progress_msg.message_id,
                    reply_markup=back_keyboard("main"),
                )
            except Exception:
                pass
            return
        step = i + 1

        # progress update
        bar = "✅ " * len(bought) + "⏳ " + "⬜ " * (qty - len(bought) - 1)
        try:
            bot.edit_message_text(
                f"⏳ <b>Buying number {step} of {qty}...</b>\n"
                f"📱 {sname} | 🌍 {flag(cname)} {cname}\n\n"
                f"{bar}\n"
                f"<code>{len(bought)} success | {len(failed)} failed</code>",
                uid, progress_msg.message_id,
            )
        except Exception:
            pass

        # ─── একটি নম্বর কেনো ───
        max_price = s.get("max_price")
        sub_attempt = 0
        result = None
        while True:
            # ─── Cancel check inside retry loop ───
            if group_id in _cancel_flags:
                break
            sub_attempt += 1
            try:
                # ❗ max_price API-তে পাঠাই না — order করে price check করি
                result = api.order_number(
                    s["provider"], s["service"],
                    s["country"]
                )
            except Exception as e:
                result = {"error": str(e)}

            _num_check = (
                result.get("number") or result.get("phone") or
                result.get("num") or result.get("telephone")
            )
            _id_check = str(
                result.get("id") or result.get("order_id") or
                result.get("activation_id") or ""
            )

            if _num_check and _id_check:
                # 💲 price check
                if max_price:
                    try:
                        got_price = float(result.get("price", 0))
                    except Exception:
                        got_price = 0.0
                    if got_price > float(max_price):
                        # Cancel this overpriced number
                        try:
                            api.cancel_number(int(_id_check))
                        except Exception:
                            pass
                        err_hint = f"${got_price:.4f} > max ${max_price} — cancelled"
                        if sub_attempt >= MAX_PRICE_RETRY_LIMIT:
                            result = {"error": f"Timed out (max ${max_price})"}
                            _num_check = None
                            _id_check  = ""
                            break
                        bar = "✅ " * len(bought) + "🔍 " + "⬜ " * (qty - len(bought) - 1)
                        try:
                            bot.edit_message_text(
                                f"🔍 <b>Buying number {step} of {qty}...</b>\n"
                                f"📱 {sname} | 🌍 {flag(cname)} {cname}\n"
                                f"💲 Max Price: ${max_price} — retrying...\n\n"
                                f"{bar}\n"
                                f"<code>{len(bought)} success | {len(failed)} failed | attempt {sub_attempt}</code>\n"
                                f"<i>{err_hint}</i>",
                                uid, progress_msg.message_id,
                            )
                        except Exception:
                            pass
                        time.sleep(MAX_PRICE_RETRY_INTERVAL)
                        continue
                # price OK — break out
                break

            if not max_price:
                # no max_price — don't retry
                break

            if sub_attempt >= MAX_PRICE_RETRY_LIMIT:
                result = {"error": f"Timed out after {sub_attempt} attempts (max ${max_price})"}
                break

            # update progress with retry info
            err_hint = (
                result.get("message") or result.get("error") or
                result.get("detail") or str(result)
            )
            bar = "✅ " * len(bought) + "🔍 " + "⬜ " * (qty - len(bought) - 1)
            try:
                bot.edit_message_text(
                    f"🔍 <b>Buying number {step} of {qty}...</b>\n"
                    f"📱 {sname} | 🌍 {flag(cname)} {cname}\n"
                    f"💲 Max Price: ${max_price} — retrying...\n\n"
                    f"{bar}\n"
                    f"<code>{len(bought)} success | {len(failed)} failed | attempt {sub_attempt}</code>\n"
                    f"<i>{str(err_hint)[:60]}</i>",
                    uid, progress_msg.message_id,
                )
            except Exception:
                pass
            time.sleep(MAX_PRICE_RETRY_INTERVAL)
            continue

        if not (_num_check and _id_check):
            err_msg = (
                result.get("message") or result.get("error") or
                result.get("detail") or result.get("msg") or str(result)
            )
            failed.append(str(err_msg)[:100])
            if i < qty - 1:
                time.sleep(3)
            continue

        # success — _num_check and _id_check are set from the retry loop
        number   = _num_check
        order_id = _id_check

        price = result.get("price", "?")
        u = get_user(uid)
        orders = u.get("orders", {})
        orders[order_id] = {
            "id": order_id, "number": number,
            "service": s["service"], "provider": s["provider"],
            "country": s["country"], "price": price,
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "otp": None, "group_id": group_id,
        }
        update_user(uid, orders=orders)
        bought.append({"id": order_id, "number": number, "price": price})
        # auto OTP poll
        threading.Thread(
            target=_auto_poll_otp, args=(uid, order_id), daemon=True
        ).start()

        # 3 সেকেন্ড বিরতি (শেষেরটার পরে না)
        if i < qty - 1:
            time.sleep(3)


    services  = get_services(s.get("prov_letter", "A"))
    countries = get_countries(s.get("prov_letter", "A"))
    sname = services.get(s["service"], s["service"])
    cname = countries.get(str(s["country"]), {}).get("name", str(s["country"]))

    lines = [
        f"✅ <b>Bulk Order Complete!</b>\n",
        f"📱 Service: <b>{sname}</b>",
        f"🌍 Country: <b>{flag(cname)} {cname}</b>",
        f"📦 Total: <b>{qty}</b> | Success: <b>{len(bought)}</b> | Failed: <b>{len(failed)}</b>\n",
        "─" * 30,
    ]
    total_cost = 0.0
    for idx, o in enumerate(bought, 1):
        try:
            total_cost += float(o["price"])
        except Exception:
            pass
        num_display = o['number'] if o['number'].startswith('+') else f"+{o['number']}"
        lines.append(f"<b>{idx}.</b> 📞 <code>{num_display}</code>  💰 ${o['price']}")

    if failed:
        lines.append(f"\n❌ <b>{len(failed)} order(s) failed:</b>")
        # বাস্তব error দেখাও (unique মেসেজ)
        seen = []
        for err in failed:
            err_str = str(err)[:120]
            if err_str not in seen:
                seen.append(err_str)
                lines.append(f"• <code>{err_str}</code>")
    lines.append(f"\n💸 Total Cost: <b>~${total_cost:.4f}</b>")
    lines.append("\n⏳ You will be notified automatically when OTPs arrive.")

    kb = types.InlineKeyboardMarkup(row_width=2)
    if bought:
        for o in bought:
            num     = o['number'] if o['number'].startswith('+') else f"+{o['number']}"
            local   = strip_country_code(num)   # e.g. 76029568
            kb.add(
                types.InlineKeyboardButton(f"🔍 {local}", callback_data=f"check_{o['id']}"),
                types.InlineKeyboardButton(f"❌ {local}",  callback_data=f"cancel_{o['id']}"),
            )
        kb.add(
            types.InlineKeyboardButton("❌ Cancel All",  callback_data=f"bulk_cancel_{group_id}"),
            types.InlineKeyboardButton("🔄 Again",       callback_data=f"bulk_again_{group_id}"),
        )
    kb.add(types.InlineKeyboardButton("🏠 Menu", callback_data="back_main"))

    try:
        bot.edit_message_text("\n".join(lines), uid, progress_msg.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(uid, "\n".join(lines), reply_markup=kb)

    # Save session so 'Again' can reuse it
    update_user(uid, buy_session={}, last_bulk_session=s)

# ─────────────── Bulk Cancel ───────────────
def _bulk_cancel(uid: int, msg: types.Message, group_id: str):
    # ─── Signal running thread to stop ───
    _cancel_flags.add(group_id)

    api    = get_api(uid)
    u      = get_user(uid)
    orders = u.get("orders", {})
    count  = 0
    for oid, o in orders.items():
        if o.get("group_id") == group_id and o.get("status") == "active":
            try:
                api.cancel_number(int(oid))
            except Exception:
                pass
            orders[oid]["status"] = "cancelled"
            count += 1
    update_user(uid, orders=orders)

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 Buy Again (Same)", callback_data="buy_again_last"),
        types.InlineKeyboardButton("🏠 Menu",           callback_data="back_main"),
    )
    bot.edit_message_text(
        f"✅ <b>{count} number(s) cancelled.</b>\n\n"
        f"🔄 Press <b>Buy Again</b> to reuse same Service + Country + Provider.",
        uid, msg.message_id, reply_markup=kb,
    )

# ─────────────── Bulk Cancel & Re-order ───────────────
def _bulk_cancel_and_again(uid: int, msg: types.Message, group_id: str):
    """Cancel all numbers in group, then re-buy with same session."""
    api    = get_api(uid)
    u      = get_user(uid)
    orders = u.get("orders", {})
    count  = 0

    # Cancel all active numbers in this group
    for oid, o in orders.items():
        if o.get("group_id") == group_id and o.get("status") == "active":
            try:
                api.cancel_number(int(oid))
            except Exception:
                pass
            orders[oid]["status"] = "cancelled"
            count += 1
    update_user(uid, orders=orders)

    # Get last bulk session
    u2 = get_user(uid)
    s  = u2.get("last_bulk_session", {})

    if not s or not s.get("provider"):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🏠 Menu", callback_data="back_main"))
        try:
            bot.edit_message_text(
                f"✅ {count} number(s) cancelled.\n\n❌ Could not re-order: session expired.",
                uid, msg.message_id, reply_markup=kb,
            )
        except Exception:
            pass
        return

    try:
        bot.edit_message_text(
            f"🔄 <b>Cancelled {count} number(s).</b>\n\n"
            f"⏳ Re-ordering {s.get('quantity', 1)} number(s)...",
            uid, msg.message_id,
        )
    except Exception:
        pass

    # Re-buy with same session
    _do_bulk_order(uid, s)

# ─────────────── Auto OTP Poll ───────────────
def _auto_poll_otp(uid: int, order_id: str, max_attempts: int = 45, interval: int = 20):
    api = get_api(uid)
    if not api:
        return
    for _ in range(max_attempts):
        time.sleep(interval)
        u      = get_user(uid)
        orders = u.get("orders", {})
        if order_id not in orders:
            break
        if orders[order_id].get("status") in ("completed", "cancelled"):
            break

        result   = api.number_status(int(order_id))
        otp_code = None

        if "sms_code" in result:
            otp_code = result["sms_code"]
        elif "STATUS_OK:" in str(result.get("status", "")):
            otp_code = str(result["status"]).split("STATUS_OK:")[1]

        if otp_code:
            orders[order_id]["otp"]    = otp_code
            orders[order_id]["status"] = "completed"
            update_user(uid, orders=orders)
            full_text = result.get("full_text", "")
            number    = orders[order_id].get("number", "?")
            bot.send_message(
                uid,
                f"🎉 <b>OTP Received!</b>\n\n"
                f"📞 Number: <code>{number}</code>\n"
                f"🔑 OTP: <code>{otp_code}</code>"
                + (f"\n📩 SMS: {full_text}" if full_text else ""),
            )
            return

    u      = get_user(uid)
    orders = u.get("orders", {})
    if order_id in orders and orders[order_id].get("status") == "active":
        bot.send_message(
            uid,
            f"⏰ <b>Order #{order_id} timed out!</b>\n\n"
            f"No OTP received within 15 minutes.",
        )

# ─────────────── Manual OTP Check ───────────────
def _check_otp(uid: int, msg: types.Message, order_id: str):
    api    = get_api(uid)
    u      = get_user(uid)
    orders = u.get("orders", {})
    if order_id not in orders:
        return

    result   = api.number_status(int(order_id))
    otp_code = None

    if "sms_code" in result:
        otp_code = result["sms_code"]
    elif "STATUS_OK:" in str(result.get("status", "")):
        otp_code = str(result["status"]).split("STATUS_OK:")[1]

    number = orders[order_id].get("number", "?")

    if otp_code:
        orders[order_id]["otp"]    = otp_code
        orders[order_id]["status"] = "completed"
        update_user(uid, orders=orders)
        full_text = result.get("full_text", "")
        text = (
            f"🎉 <b>OTP Received!</b>\n\n"
            f"📞 Number: <code>{number}</code>\n"
            f"🔑 <b>OTP: <code>{otp_code}</code></b>\n"
            + (f"📩 Message: {full_text}" if full_text else "")
        )
    else:
        text = (
            f"⏳ <b>OTP not received yet</b>\n\n"
            f"📞 Number: <code>{number}</code>\n"
            f"📊 Status: {result.get('status','pending')}\n\n"
            f"Please check again in a moment."
        )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Check Again", callback_data=f"check_{order_id}"),
        types.InlineKeyboardButton("🔄 Resend OTP",  callback_data=f"resend_{order_id}"),
    )
    kb.add(
        types.InlineKeyboardButton("❌ Cancel",  callback_data=f"cancel_{order_id}"),
        types.InlineKeyboardButton("⬅️ Back",    callback_data="my_orders"),
    )
    bot.edit_message_text(text, uid, msg.message_id, reply_markup=kb)

# ─────────────── Cancel ───────────────
def _cancel_order(uid: int, msg: types.Message, order_id: str):
    api    = get_api(uid)
    result = api.cancel_number(int(order_id))

    # ── Check if cancel succeeded ──
    # Success: API returns status "cancelled", "ok", "success" or no error key
    err_msg = (
        result.get("message") or result.get("error") or
        result.get("detail") or result.get("msg") or ""
    )
    status_val = str(result.get("status", "")).lower()
    is_success = (
        status_val in ("cancelled", "ok", "success", "1", "true")
        or result.get("success") is True
        or (not err_msg and "error" not in result and "message" not in result)
    )

    u      = get_user(uid)
    orders = u.get("orders", {})

    if is_success:
        # ✅ Cancelled — update status and show confirmation
        if order_id in orders:
            orders[order_id]["status"] = "cancelled"
            update_user(uid, orders=orders)
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("📋 My Orders", callback_data="my_orders"),
            types.InlineKeyboardButton("🏠 Menu",      callback_data="back_main"),
        )
        bot.edit_message_text(
            f"✅ <b>Order #{order_id} cancelled.</b>",
            uid, msg.message_id, reply_markup=kb,
        )
    else:
        # ❌ Cancel failed — keep number active, show error as new message below
        number = orders.get(order_id, {}).get("number", order_id)
        num_display = f"+{number}" if not str(number).startswith("+") else number
        bot.send_message(
            uid,
            f"⚠️ <b>Cancel failed for {num_display}</b>\n\n"
            f"<code>{err_msg or str(result)}</code>",
        )

# ─────────────── Resend ───────────────
def _resend_otp(uid: int, msg: types.Message, order_id: str):
    api = get_api(uid)
    api.resend_sms(int(order_id))
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Check OTP", callback_data=f"check_{order_id}"),
        types.InlineKeyboardButton("❌ Cancel",     callback_data=f"cancel_{order_id}"),
    )
    bot.edit_message_text(
        f"🔄 <b>OTP resend requested.</b>\n\nOrder: #{order_id}\nPlease check in a moment.",
        uid, msg.message_id, reply_markup=kb,
    )

# ─────────────── My Orders ───────────────
def _show_my_orders(uid: int, msg: types.Message):
    u      = get_user(uid)
    orders = u.get("orders", {})
    active = {oid: o for oid, o in orders.items() if o.get("status") == "active"}

    if not active:
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("📱 Buy Number", callback_data="buy_menu"),
            types.InlineKeyboardButton("🏠 Menu",       callback_data="back_main"),
        )
        bot.edit_message_text("📋 <b>No active orders.</b>\nBuy a number to get started.", uid, msg.message_id, reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for oid, o in list(active.items())[-10:]:
        kb.add(types.InlineKeyboardButton(
            f"📞 {o.get('number','?')} | {o.get('service','?')}",
            callback_data=f"order_{oid}"
        ))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    bot.edit_message_text(f"📋 <b>Active Orders</b> ({len(active)}):", uid, msg.message_id, reply_markup=kb)

def _show_my_orders_msg(uid: int):
    u      = get_user(uid)
    orders = u.get("orders", {})
    active = {oid: o for oid, o in orders.items() if o.get("status") == "active"}
    if not active:
        bot.send_message(uid, "📋 No active orders.")
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for oid, o in list(active.items())[-10:]:
        kb.add(types.InlineKeyboardButton(
            f"📞 {o.get('number','?')} | {o.get('service','?')}",
            callback_data=f"order_{oid}"
        ))
    bot.send_message(uid, f"📋 <b>Active Orders</b> ({len(active)}):", reply_markup=kb)

# ─────────────── Order Detail ───────────────
def _show_order_detail(uid: int, msg: types.Message, order_id: str):
    u      = get_user(uid)
    orders = u.get("orders", {})
    o      = orders.get(order_id)
    if not o:
        bot.edit_message_text("❌ Order not found.", uid, msg.message_id)
        return

    text = (
        f"📋 <b>Order Details</b>\n\n"
        f"🆔 ID: <code>{order_id}</code>\n"
        f"📞 Number: <code>{o.get('number','?')}</code>\n"
        f"📱 Service: {o.get('service','?')}\n"
        f"💰 Price: ${o.get('price','?')}\n"
        f"📊 Status: {o.get('status','?')}\n"
        f"🕒 Time: {o.get('created_at','?')[:16]}\n"
    )
    if o.get("otp"):
        text += f"\n🔑 <b>OTP: <code>{o['otp']}</code></b>"

    kb = types.InlineKeyboardMarkup(row_width=2)
    if o.get("status") == "active":
        kb.add(
            types.InlineKeyboardButton("🔍 Check OTP", callback_data=f"check_{order_id}"),
            types.InlineKeyboardButton("🔄 Resend",    callback_data=f"resend_{order_id}"),
        )
        kb.add(types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{order_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="my_orders"))
    bot.edit_message_text(text, uid, msg.message_id, reply_markup=kb)

# ─────────────── History ───────────────
def _show_history(uid: int, msg: types.Message):
    u          = get_user(uid)
    orders     = u.get("orders", {})
    all_orders = list(orders.items())[-15:]

    if not all_orders:
        bot.edit_message_text("📜 No history yet.", uid, msg.message_id, reply_markup=back_keyboard("main"))
        return

    lines = ["📜 <b>Recent Order History</b>\n"]
    for oid, o in reversed(all_orders):
        icon    = {"active": "🟡", "completed": "✅", "cancelled": "❌"}.get(o.get("status"), "❓")
        otp_str = f" | OTP: <code>{o['otp']}</code>" if o.get("otp") else ""
        lines.append(f"{icon} <code>{o.get('number','?')}</code> ({o.get('service','?')}){otp_str}")

    bot.edit_message_text("\n".join(lines), uid, msg.message_id, reply_markup=back_keyboard("main"))

def _show_history_msg(uid: int):
    u      = get_user(uid)
    orders = u.get("orders", {})
    if not orders:
        bot.send_message(uid, "📜 No history yet.")
        return
    lines = ["📜 <b>Recent Order History</b>\n"]
    for oid, o in reversed(list(orders.items())[-15:]):
        icon    = {"active": "🟡", "completed": "✅", "cancelled": "❌"}.get(o.get("status"), "❓")
        otp_str = f" | OTP: <code>{o['otp']}</code>" if o.get("otp") else ""
        lines.append(f"{icon} <code>{o.get('number','?')}</code> ({o.get('service','?')}){otp_str}")
    bot.send_message(uid, "\n".join(lines))

# ─────────────── Admin Panel ───────────────
def _show_admin(uid: int, msg: types.Message):
    users        = load_users()
    total        = len(users)
    active_users = sum(1 for u in users.values() if u.get("api_key"))
    total_orders = sum(len(u.get("orders", {})) for u in users.values())

    text = (
        f"👑 <b>Admin Panel</b>\n\n"
        f"👥 Total Users: <b>{total}</b>\n"
        f"🔑 Logged In: <b>{active_users}</b>\n"
        f"📋 Total Orders: <b>{total_orders}</b>\n"
        f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    bot.edit_message_text(text, uid, msg.message_id, reply_markup=back_keyboard("main"))

# ─────────────── Start Bot ───────────────
register_commands()
print("[*] smsotps Bot starting...")
print(f"[*] Token: {BOT_TOKEN[:15]}...")
print(f"[*] Admin ID: {ADMIN_ID}")
print("[*] Ready! Waiting for messages...")

while True:
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=25, skip_pending=True)
    except Exception as e:
        print(f"[!] Connection error: {e}")
        print("[*] Reconnecting in 5 seconds...")
        time.sleep(5)
