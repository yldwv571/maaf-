# -*- coding: utf-8 -*-
"""
NIGHT MAFIA BOT  —  bitta fayl (bot + Telegram Web App "Shaxsiy kabinet")

ISHGA TUSHIRISH:
  pip install -U aiogram aiohttp
  export BOT_TOKEN="123:ABC..."            (yoki token.txt fayliga yozing)
  export ADMIN_ID="8495751297"             (vergul bilan bir nechta)
  export WEB_URL="https://sizning-domen"   (HTTPS majburiy. Berilmasa va PATH da cloudflared yoki ngrok bo'lsa — bot o'zi HTTPS tunnel
                                            ochadi. Yoki adminga botda: /weburl https://domen  — saqlanadi, web_url.txt ga)
  export PORT=8000
  python bot.py

PREMIUM EMOJI:  adminga botning shaxsiy chatida istalgan premium emoji(lar) yuboring — bot ID larni o'zi o'qib premium_emoji.json ga
  yozadi va darhol ishlata boshlaydi. Matndagi premium emoji faqat Fragment'dan qo'shimcha username sotib olgan botlarda,
  tugma ikonkalari esa bot egasida Telegram Premium bo'lsa ishlaydi. Ishlamasa bot oddiy emoji bilan yuboradi (xato bermaydi).
"""
import aiohttp, asyncio, base64, hashlib, hmac, html, json, logging, os, random, re, shutil, sqlite3, time, urllib.parse, uuid
from datetime import datetime, timezone, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, BotCommand, FSInputFile,
                           BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, ReplyKeyboardRemove,
                           WebAppInfo, MenuButtonCommands, InlineKeyboardButton, InlineKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ⚠️ TOKEN KODGA YOZILMAYDI. Terminalda:  export BOT_TOKEN="123:ABC..."   yoki  token.txt fayliga yozing.
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN and os.path.exists("token.txt"):
    TOKEN = open("token.txt", encoding="utf-8").read().strip()
if not TOKEN:
    raise SystemExit("❌ BOT_TOKEN topilmadi: export BOT_TOKEN=\"123:ABC...\"  yoki token.txt fayliga yozing.")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "8495751297").split(",") if x.strip().isdigit()}
WEB_PORT = int(os.getenv("PORT", "8000"))


def norm_url(u):
    """WEB_URL ni to'g'rilaydi: sxema yo'q bo'lsa https:// qo'shadi; lokal bo'lmagan http:// ni https:// ga almashtiradi."""
    u = (u or "").strip().strip("\"'").rstrip("/")
    if not u: return ""
    if "://" not in u: u = ("http://" if re.match(r"^(127\.|localhost|0\.0\.0\.0|192\.168\.|10\.)", u) else "https://") + u
    if u.startswith("http://") and not re.match(r"^http://(127\.|localhost|0\.0\.0\.0|192\.168\.|10\.)", u): u = "https://" + u[7:]
    return u


def _read(path):
    try: return open(path, encoding="utf-8").read()
    except Exception: return ""


WEB_URL = norm_url(os.getenv("WEB_URL") or _read("web_url.txt")) or f"http://127.0.0.1:{WEB_PORT}"
WEB_HTTPS = WEB_URL.startswith("https://")             # Telegram Web App faqat HTTPS bilan ishlaydi
NEWS = "https://t.me/NightMafiaNews"
NEWS_USER = "NightMafiaNews"
CARD_USER = "https://t.me/yldwv_fx"
SUF = "nightmafiauzbot"            # /gamenightmafiauzbot kabi qo'shimcha buyruqlar uchun
REG_SEC, NIGHT_SEC, DAY_SEC, VOTE_SEC, CONF_SEC, MINP, MINVS = 1800, 45, 40, 30, 20, 4, 2
IDLE_STOP = 7200                   # o'yin yaratilib 2 soat o'ynalmasa to'xtatiladi
EXT_MAX = 20                       # /extend max daqiqa
CH_MAX = 75                        # /change max ishtirokchi
AMAX = 10                          # max faol rollar soni
TZ = timezone(timedelta(hours=5))
UP = "uploads"                     # operator chatidagi rasmlar
os.makedirs(UP, exist_ok=True)

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
r = Router()
dp.include_router(r)
esc = html.escape
BOTNAME = ""
BG_TASKS = []

# ───────────────────────── Premium emoji ─────────────────────────
# premium_emoji.json:  {"💎": "<custom_emoji_id>", ...}.  ID larni olish: adminga botga premium emoji yuborish kifoya (/emojiid).
PE, PE_RE, PE_KEYS = {}, None, []
_HAS_ICON = "icon_custom_emoji_id" in getattr(InlineKeyboardButton, "model_fields", {})     # tugma ikonkasi (aiogram 3.25+)


def set_pe(d):
    global PE, PE_RE, PE_KEYS
    PE = {k: str(v) for k, v in d.items() if v and k}
    PE_KEYS = sorted(PE, key=len, reverse=True)
    PE_RE = re.compile("|".join(re.escape(k) for k in PE_KEYS)) if PE else None


def load_pe():
    try:
        if os.path.exists("premium_emoji.json"): set_pe(json.load(open("premium_emoji.json", encoding="utf-8")))
    except Exception:
        logging.exception("premium_emoji.json o'qilmadi"); set_pe({})


def save_pe():
    with open("premium_emoji.json", "w", encoding="utf-8") as f: json.dump(PE, f, ensure_ascii=False, indent=1)


load_pe()


def prem(text):
    """Oddiy emoji -> premium emoji (faqat HTML matnlarda). ID kiritilmagan bo'lsa matn o'zgarmaydi."""
    if not PE_RE or not isinstance(text, str): return text
    return PE_RE.sub(lambda m_: f'<tg-emoji emoji-id="{PE[m_.group(0)]}">{m_.group(0)}</tg-emoji>', text)


def prem_markup(mk):
    """Inline tugma matnidagi boshlang'ich emoji ni premium ikonkaga almashtiradi (aiogram 3.25+ bo'lsa)."""
    changed = False; rows = []
    for row in mk.inline_keyboard:
        nr = []
        for b in row:
            nb = b
            if not getattr(b, "icon_custom_emoji_id", None):
                for k in PE_KEYS:
                    if b.text.startswith(k):
                        nb = b.model_copy(update={"text": b.text[len(k):].lstrip() or k, "icon_custom_emoji_id": PE[k]}); changed = True; break
            nr.append(nb)
        rows.append(nr)
    return mk.model_copy(update={"inline_keyboard": rows}) if changed else mk


class PremMW(BaseRequestMiddleware):
    """Botdan ketadigan HTML xabarlar va tugmalarga premium emoji qo'llaydi; Telegram rad etsa oddiy ko'rinishda qayta yuboradi."""
    async def __call__(self, make_request, bot_, method):
        if PE_RE:
            upd = {}
            pmode = getattr(method, "parse_mode", "x")
            if pmode != "x" and not (isinstance(pmode, str) and pmode.upper() != "HTML"):
                for f in ("text", "caption"):
                    v = getattr(method, f, None)
                    if isinstance(v, str) and v: upd[f] = prem(v)
            mk = getattr(method, "reply_markup", None)
            if _HAS_ICON and isinstance(mk, InlineKeyboardMarkup):
                nm = prem_markup(mk)
                if nm is not mk: upd["reply_markup"] = nm
            if upd:
                try: return await make_request(bot_, method.model_copy(update=upd))
                except TelegramBadRequest: pass
        return await make_request(bot_, method)


bot.session.middleware(PremMW())


def dfmt(ts): return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def n_(x): return f"{int(x):,}"     # 999,997,650 — Telegram telefon raqam deb ko'k qilib yubormasligi uchun


# ───────────────────────── DB ─────────────────────────
db = sqlite3.connect("mafia", check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, lang TEXT DEFAULT 'uz',
 web TEXT, money INT DEFAULT 0, diamonds INT DEFAULT 0, ncoin INT DEFAULT 0, himoya INT DEFAULT 0,
 hujjat INT DEFAULT 0, osish INT DEFAULT 0, geroyd INT DEFAULT 0, wins INT DEFAULT 0, games INT DEFAULT 0,
 arole TEXT DEFAULT '', vip INT DEFAULT 0, vip_until INT DEFAULT 0, t_h INT DEFAULT 1, t_d INT DEFAULT 1,
 t_o INT DEFAULT 1, t_g INT DEFAULT 1, blocked INT DEFAULT 0, pair INT DEFAULT 0, has_hero INT DEFAULT 0,
 hname TEXT DEFAULT '', points INT DEFAULT 0, hprot INT DEFAULT 0, charge INT DEFAULT 0, boosts INT DEFAULT 0)""")
db.execute("""CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY, bal INT DEFAULT 0, sub_until INT DEFAULT 0,
 notified INT DEFAULT 1, mode TEXT DEFAULT 'night', off TEXT DEFAULT '')""")
db.execute("CREATE TABLE IF NOT EXISTS pts_log(uid INT, ball INT, ts INT)")
db.execute("CREATE INDEX IF NOT EXISTS i_pts ON pts_log(ts)")
db.execute("CREATE TABLE IF NOT EXISTS pairs(a INT, b INT, PRIMARY KEY(a,b))")
db.execute("""CREATE TABLE IF NOT EXISTS heroes(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, name TEXT DEFAULT '',
 points INT DEFAULT 0, hprot INT DEFAULT 0, charge INT DEFAULT 10)""")
db.execute("CREATE TABLE IF NOT EXISTS tx(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INT, src INT, dst INT, kind TEXT, amount INT)")
db.execute("CREATE TABLE IF NOT EXISTS bans(id INTEGER PRIMARY KEY, snap TEXT)")
db.execute("""CREATE TABLE IF NOT EXISTS market(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, name TEXT DEFAULT '',
 points INT DEFAULT 0, hprot INT DEFAULT 0, charge INT DEFAULT 10, price INT DEFAULT 0, ts INT DEFAULT 0)""")
db.execute("CREATE TABLE IF NOT EXISTS support(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, role TEXT, text TEXT DEFAULT '', img TEXT DEFAULT '', ts INT)")
db.execute("CREATE INDEX IF NOT EXISTS i_sup ON support(uid,id)")
db.execute("CREATE TABLE IF NOT EXISTS support_map(chat INT, mid INT, uid INT, PRIMARY KEY(chat,mid))")
db.execute("CREATE TABLE IF NOT EXISTS gchat(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, text TEXT, ts INT)")


def addcol(tbl, col, ddl):
    if col not in [x["name"] for x in db.execute(f"PRAGMA table_info({tbl})")]:
        db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")


addcol("users", "boosts", "INT DEFAULT 0")
addcol("users", "username", "TEXT DEFAULT ''")
addcol("users", "theme", "TEXT DEFAULT 'cyber'")
addcol("users", "wlang", "TEXT DEFAULT 'uz'")
addcol("groups", "sub_until", "INT DEFAULT 0")
addcol("groups", "notified", "INT DEFAULT 1")
addcol("groups", "mode", "TEXT DEFAULT 'night'")
addcol("groups", "off", "TEXT DEFAULT ''")
addcol("groups", "glang", "TEXT DEFAULT 'uz'")
addcol("groups", "listed", "INT DEFAULT 0")
addcol("groups", "title", "TEXT DEFAULT ''")
addcol("groups", "invite", "TEXT DEFAULT ''")
addcol("pts_log", "chat", "INT DEFAULT 0")
for _x in db.execute("SELECT id,pair FROM users WHERE pair>0").fetchall():      # eski para ma'lumotlarini ko'chirish
    _a, _b = sorted((_x["id"], _x["pair"]))
    db.execute("INSERT OR IGNORE INTO pairs(a,b) VALUES(?,?)", (_a, _b))
    db.execute("UPDATE users SET pair=0 WHERE id=?", (_x["id"],))
db.commit()
COLS = ["money", "diamonds", "ncoin", "himoya", "hujjat", "osish", "geroyd", "wins", "games", "arole", "vip",
        "vip_until", "has_hero", "hname", "points", "hprot", "charge", "boosts"]


def U(uid, name=None):
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        db.execute("INSERT INTO users(id,name,web) VALUES(?,?,?)", (uid, name or str(uid), uuid.uuid4().hex))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    elif name and row["name"] != name:
        db.execute("UPDATE users SET name=? WHERE id=?", (name, uid)); db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return row


def S(uid, **kw):
    U(uid)
    db.execute(f"UPDATE users SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), uid)); db.commit()


def A(uid, f, n):
    U(uid)
    db.execute(f"UPDATE users SET {f}={f}+? WHERE id=?", (n, uid)); db.commit()


def is_admin(uid): return uid in ADMIN_IDS


def vlevel(u): return u["vip"] if u["vip_until"] > time.time() else 0


def txlog(src, dst, kind, amount):
    db.execute("INSERT INTO tx(ts,src,dst,kind,amount) VALUES(?,?,?,?,?)", (int(time.time()), src, dst, kind, amount)); db.commit()


# ---- guruh sozlamalari / obuna ----
def Gr(chat):
    db.execute("INSERT OR IGNORE INTO groups(id) VALUES(?)", (chat,)); db.commit()
    return db.execute("SELECT * FROM groups WHERE id=?", (chat,)).fetchone()


def gset(chat, **kw):
    Gr(chat)
    db.execute(f"UPDATE groups SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), chat)); db.commit()


def goff(chat): return {x for x in Gr(chat)["off"].split(",") if x}


def sub_active(chat): return Gr(chat)["sub_until"] > time.time()


def sub_add(chat, days):
    g = Gr(chat); new = int(max(g["sub_until"], time.time()) + days * 86400)
    db.execute("UPDATE groups SET sub_until=?, notified=0 WHERE id=?", (new, chat)); db.commit()
    return new


def sub_link(chat): return f"https://t.me/{BOTNAME}?start=sub{abs(chat)}"


SUB_M, SUB_Y = 5, 60               # guruh obunasi: 1 oy = 5 💎, 1 yil = 60 💎


# ---- para / geroy ----
PLIM = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}
HLIM = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}


def pairs_of(uid):
    return [x["b"] if x["a"] == uid else x["a"] for x in db.execute("SELECT a,b FROM pairs WHERE a=? OR b=?", (uid, uid))]


def padd(a, b):
    a, b = sorted((a, b)); db.execute("INSERT OR IGNORE INTO pairs(a,b) VALUES(?,?)", (a, b)); db.commit()


def pdel(a, b):
    a, b = sorted((a, b)); db.execute("DELETE FROM pairs WHERE a=? AND b=?", (a, b)); db.commit()


def plim(uid): return PLIM[vlevel(U(uid))]


def hlim(uid): return HLIM[vlevel(U(uid))]


def hcount(uid):
    return (1 if U(uid)["has_hero"] else 0) + db.execute("SELECT COUNT(*) c FROM heroes WHERE uid=?", (uid,)).fetchone()["c"]


def add_hero(uid, name="", points=None, hprot=0, charge=10):
    if not U(uid)["has_hero"]:
        kw = dict(has_hero=1, hname=name, hprot=hprot, charge=charge)
        if points is not None: kw["points"] = points
        S(uid, **kw)
    else:
        db.execute("INSERT INTO heroes(uid,name,points,hprot,charge) VALUES(?,?,?,?,?)", (uid, name, points or 0, hprot, charge)); db.commit()


def hero_remove_active(uid):
    row = db.execute("SELECT * FROM heroes WHERE uid=? ORDER BY id LIMIT 1", (uid,)).fetchone()
    if row:
        S(uid, has_hero=1, hname=row["name"], points=row["points"], hprot=row["hprot"], charge=row["charge"])
        db.execute("DELETE FROM heroes WHERE id=?", (row["id"],)); db.commit()
    else:
        S(uid, has_hero=0, hname="", points=0, hprot=0, charge=0)


def hero_swap(uid, hid):
    u = U(uid); row = db.execute("SELECT * FROM heroes WHERE id=? AND uid=?", (hid, uid)).fetchone()
    if not row: return
    cur = (u["hname"], u["points"], u["hprot"], u["charge"])
    S(uid, hname=row["name"], points=row["points"], hprot=row["hprot"], charge=row["charge"], has_hero=1)
    db.execute("UPDATE heroes SET name=?,points=?,hprot=?,charge=? WHERE id=?", (*cur, hid)); db.commit()


def aroles(u): return [x for x in (u["arole"] or "").split(",") if x]


VIPS = {1: ("➕ VIP Plus", 30), 2: ("🌟 VIP Pro", 60), 3: ("👨‍🍳 VIP Ultra", 90), 4: ("👑 VIP Ultra Promax", 150)}


def vemoji(uid):
    lv = vlevel(U(uid)); return VIPS[lv][0].split()[0] + " " if lv else ""


def grant_vip(uid, k):
    """VIP berish (30 kun) + har safar 1 ta /boost."""
    u = U(uid); base = max(u["vip_until"], time.time()) if vlevel(u) == k else time.time()
    S(uid, vip=k, vip_until=int(base + 30 * 86400)); A(uid, "boosts", 1)


# ───────────────────────── Tillar (uz / ru / en) ─────────────────────────
LANGS = ("uz", "ru", "en"); IDX = {"uz": 0, "ru": 1, "en": 2}
LT = {
    "start": ("Salom\nMen mafiya botiman. Doʻstlar bilan mafiya oʻynash uchun meni guruhingizga qoʻshing va 30 kishilik oʻyindan zavqlaning, batafsil maʼlumot uchun\n\n👨‍💻 @yldwv_fx\n\nMeni admin qilib qoʻyganingizdan soʻng, oʻyinni boshlashingiz mumkin..",
              "Привет\nЯ бот для игры в мафию. Добавьте меня в свою группу, чтобы играть с друзьями — до 30 игроков! Подробности:\n\n👨‍💻 @yldwv_fx\n\nКогда вы сделаете меня администратором, можно начинать игру..",
              "Hello\nI'm a mafia bot. Add me to your group to play mafia with friends — up to 30 players! More info:\n\n👨‍💻 @yldwv_fx\n\nOnce you make me an admin, you can start the game.."),
    "btn_gap": ("Guruhga qo‘shish", "Добавить в группу", "Add to group"),
    "btn_news": ("Yangiliklar", "Новости", "News"),
    "btn_lang": ("Til / Язык", "Til / Язык", "Til / Язык"),
    "btn_ask": ("Savollar uchun", "Вопросы", "Questions"),
    "btn_cab": ("Shaxsiy kabinet", "Личный кабинет", "Personal cabinet"),
    "btn_prem": ("Premium guruhlar", "Премиум группы", "Premium groups"),
    "prem_none": ("Hozircha premium guruhlar mavjud emas!", "Премиум групп пока нет!", "No premium groups yet!"),
    "prem_add": ("O'z guruhini qo'shish", "Добавить свою группу", "Add your group"),
    "web_off": ("⚠️ Shaxsiy kabinet hozircha ishlamayapti (WEB_URL https:// bo'lishi kerak).", "⚠️ Личный кабинет пока недоступен (WEB_URL должен быть https://).", "⚠️ The cabinet is unavailable (WEB_URL must be https://)."),
    "langtitle": ("🌐 Shaxsiy chat tili", "🌐 Язык личного чата", "🌐 Personal chat language"),
    "roles_hdr": ("Rollar ro'yxati:", "Список ролей:", "Roles list:"),
    "back": ("⬅️ Orqaga", "⬅️ Назад", "⬅️ Back"),
    "none": ("Yo'q", "Нет", "None"),
    "prof": ("👤 {name}{vip}\n\n💶 Dollar: {money}\n💎 Olmos: {dia}\n💠 NightCoin: {nc}\n\n🛡 Himoya: {h}\n📁 Hujjat: {d}\n⚖️ Osishdan himoya: {o}\n🔰 Geroydan himoya: {g}\n\n🎯 G'alaba: {w}\n🎲 Barcha o'yinlar: {gm}\n\n🃏 Faol rollar:{ar}",
             "👤 {name}{vip}\n\n💶 Доллары: {money}\n💎 Алмазы: {dia}\n💠 NightCoin: {nc}\n\n🛡 Защита: {h}\n📁 Документ: {d}\n⚖️ Защита от повешения: {o}\n🔰 Защита от героя: {g}\n\n🎯 Победы: {w}\n🎲 Всего игр: {gm}\n\n🃏 Активные роли:{ar}",
             "👤 {name}{vip}\n\n💶 Dollars: {money}\n💎 Diamonds: {dia}\n💠 NightCoin: {nc}\n\n🛡 Shield: {h}\n📁 Document: {d}\n⚖️ Hanging protection: {o}\n🔰 Hero protection: {g}\n\n🎯 Wins: {w}\n🎲 Total games: {gm}\n\n🃏 Active roles:{ar}"),
    "p_shop": ("Do'kon", "Магазин", "Shop"),
    "p_buyd": ("Xarid qilish 💎", "Купить 💎", "Buy 💎"),
    "p_buym": ("Xarid qilish 💵", "Купить 💵", "Buy 💵"),
    "p_hero": ("🥷 Mening geroyim", "🥷 Мой герой", "🥷 My hero"),
    "p_tr": ("🔄 Profil almashish", "🔄 Перенос профиля", "🔄 Switch profile"),
    "shop_title": ("🛒 <b>Do'kon</b>", "🛒 <b>Магазин</b>", "🛒 <b>Shop</b>"),
    "price": ("Narxi", "Цена", "Price"),
    "sh_hero": ("🥷 Geroy — 90 💎", "🥷 Герой — 90 💎", "🥷 Hero — 90 💎"),
    "sh_hero_s": ("🥷 Geroy — 300 ⭐️", "🥷 Герой — 300 ⭐️", "🥷 Hero — 300 ⭐️"),
    "sh_vip": ("⭐️ VIP", "⭐️ VIP", "⭐️ VIP"),
    "sh_ar": ("🎭 Faol rol", "🎭 Активная роль", "🎭 Active role"),
    "it_himoya": ("🛡 Himoya", "🛡 Защита", "🛡 Shield"),
    "itd_himoya": ("Bir marta hayotingizni saqlab qoladi.", "Один раз спасёт вам жизнь.", "Saves your life once."),
    "it_hujjat": ("📁 Hujjat", "📁 Документ", "📁 Document"),
    "itd_hujjat": ("Kimdir rolingizni tekshirsa, soxta hujjat yordam beradi.", "Если проверят вашу роль, поддельный документ поможет.", "A fake document helps if someone checks your role."),
    "it_osish": ("⚖️ Ovozdan himoya", "⚖️ Защита от повешения", "⚖️ Vote protection"),
    "itd_osish": ("Osishga hukm qilishsa, bir marta qutqaradi.", "Спасёт один раз, если приговорят к повешению.", "Saves you once if you're sentenced to hang."),
    "it_geroyd": ("🔰 Geroydan himoya", "🔰 Защита от героя", "🔰 Hero protection"),
    "itd_geroyd": ("Geroydan bo'lgan hujumdan omon qolish.", "Позволяет пережить атаку героя.", "Survive a hero attack."),
    "it_ncoin": ("💠 NightCoin", "💠 NightCoin", "💠 NightCoin"),
    "itd_ncoin": ("Tez orada ishga tushadigan marketdagi valyuta.", "Валюта будущего маркета.", "Currency of the upcoming market."),
    "no_dia": ("Olmos yetarli emas!", "Недостаточно алмазов!", "Not enough diamonds!"),
    "no_money": ("Pul yetarli emas!", "Недостаточно денег!", "Not enough money!"),
    "no_bal": ("Balans yetarli emas!", "Недостаточный баланс!", "Insufficient balance!"),
    "bought": ("✅ {n} sotib olindi!", "✅ {n} куплено!", "✅ {n} purchased!"),
    "hero_full": ("Geroy sloti to'lgan! (limit: {n}). VIP orqali limitni oshiring.", "Слоты героев заполнены! (лимит: {n}). Повысьте лимит через VIP.", "Hero slots are full! (limit: {n}). Raise it with VIP."),
    "hero_bought": ("🥷 Geroy sotib olindi! «Mening geroyim» bo'limiga o'ting.", "🥷 Герой куплен! Откройте раздел «Мой герой».", "🥷 Hero purchased! Open the “My hero” section."),
    "hero_none": ("Sizda geroy yo'q. Do'kondan sotib oling.", "У вас нет героя. Купите его в магазине.", "You have no hero. Buy one in the shop."),
    "hb_buy_d": ("🥷 Geroy sotib olish — 90 💎", "🥷 Купить героя — 90 💎", "🥷 Buy hero — 90 💎"),
    "hb_buy_s": ("🥷 Geroy — 300 ⭐️", "🥷 Герой — 300 ⭐️", "🥷 Hero — 300 ⭐️"),
    "hero_fmt": ("🥷 Geroy: {name}\n\n⭐️ Daraja: {L}\n👊 Kuch: {pow}\n🖤 Himoya: {hp}\n♥️ Max himoya: {mh}\n🩸 Zaryad miqdori: {ch}\n☑️ Jami ballari: {pts} ball\n🔰 Geroydan himoya: {gd}{nxt}",
                 "🥷 Герой: {name}\n\n⭐️ Уровень: {L}\n👊 Сила: {pow}\n🖤 Защита: {hp}\n♥️ Макс. защита: {mh}\n🩸 Заряд: {ch}\n☑️ Всего очков: {pts}\n🔰 Защита от героя: {gd}{nxt}",
                 "🥷 Hero: {name}\n\n⭐️ Level: {L}\n👊 Power: {pow}\n🖤 Protection: {hp}\n♥️ Max protection: {mh}\n🩸 Charge: {ch}\n☑️ Total points: {pts}\n🔰 Hero protection: {gd}{nxt}"),
    "hero_shop": ("🛒 Xaridlar uchun:\n➕ 1000 Ball qo'shish = 💎 50\n🛡 Himoyani yangilash = 💶 300\n🩸 Qurolni zaryadlash = 💶 200\n🖋 Geroy nomini o'zgartirish 💶 800",
                  "🛒 Покупки:\n➕ 1000 очков = 💎 50\n🛡 Обновить защиту = 💶 300\n🩸 Зарядить оружие = 💶 200\n🖋 Сменить имя героя = 💶 800",
                  "🛒 Purchases:\n➕ 1000 points = 💎 50\n🛡 Renew protection = 💶 300\n🩸 Recharge weapon = 💶 200\n🖋 Rename hero = 💶 800"),
    "hero_next": ("\n\n⏫ Keyingi daraja = {n} => {p} ball", "\n\n⏫ Следующий уровень = {n} => {p} очков", "\n\n⏫ Next level = {n} => {p} points"),
    "pow_range": ("{a}-{b} oralig'ida", "в пределах {a}-{b}", "between {a}-{b}"),
    "pow_max": ("maksimal uradi", "максимальный урон", "maximum damage"),
    "noname": ("nomsiz", "без имени", "unnamed"),
    "hb_ball": ("➕ 1000 Ball", "➕ 1000 очков", "➕ 1000 Points"),
    "hb_prot": ("🛡 Himoyani yangilash", "🛡 Обновить защиту", "🛡 Renew protection"),
    "hb_charge": ("🩸 Qurolni o'qlash", "🩸 Зарядить оружие", "🩸 Recharge weapon"),
    "hb_name": ("🖋 Geroy nomini o'zgartirish", "🖋 Сменить имя героя", "🖋 Rename hero"),
    "hb_lvls": ("⭐️ Darajalar haqida", "⭐️ Об уровнях", "⭐️ About levels"),
    "hb_status": ("🎭 Status", "🎭 Статус", "🎭 Status"),
    "hb_list": ("🔁 Geroylarim ({n}/{lim})", "🔁 Мои герои ({n}/{lim})", "🔁 My heroes ({n}/{lim})"),
    "h_ball_ok": ("1000 bal qo'shildi!", "Добавлено 1000 очков!", "1000 points added!"),
    "h_prot_ok": ("Himoya yangilandi!", "Защита обновлена!", "Protection renewed!"),
    "h_charge_ok": ("Qurol o'qlandi! (max 10 marta)", "Оружие заряжено! (макс. 10)", "Weapon recharged! (max 10)"),
    "h_name_ask": ("🖋 Geroyingiz uchun yangi nom yuboring:", "🖋 Отправьте новое имя для героя:", "🖋 Send a new name for your hero:"),
    "h_status_ask": ("🎭 Status uchun premium emoji/matn yuboring:", "🎭 Отправьте премиум-эмодзи/текст для статуса:", "🎭 Send a premium emoji/text for your status:"),
    "h_no800": ("Pul yetarli emas (800 💶)", "Недостаточно денег (800 💶)", "Not enough money (800 💶)"),
    "h_name_ok": ("✅ Geroy nomi o'zgardi.", "✅ Имя героя изменено.", "✅ Hero name changed."),
    "h_status_ok": ("✅ Status o'rnatildi.", "✅ Статус установлен.", "✅ Status set."),
    "h_list": ("🥷 Geroylaringiz ({n}/{lim}). Faol qilish uchun tanlang:", "🥷 Ваши герои ({n}/{lim}). Выберите активного:", "🥷 Your heroes ({n}/{lim}). Pick the active one:"),
    "lvl_fmt": ("⭐️ {i}-daraja:\n☑️ O'tish balli: {pts} ball\n👊 Kuch: {pow}\n♥️ Max Himoya: {mh}.0",
                "⭐️ Уровень {i}:\n☑️ Нужно очков: {pts}\n👊 Сила: {pow}\n♥️ Макс. защита: {mh}.0",
                "⭐️ Level {i}:\n☑️ Points needed: {pts}\n👊 Power: {pow}\n♥️ Max protection: {mh}.0"),
    "lvl_yours": ("Sizning darajangiz: {n}-daraja", "Ваш уровень: {n}", "Your level: {n}"),
    "vip_txt": ("⭐️ <b>VIP Obunalar</b>\n\n➕ VIP Plus — 30 💎 / 30 kun\n• Komissiyasiz o'tkazmalar\n• VIP status emoji\n• Kechqurun yoza olish\n• 1 para, 1 geroy\n• /boost — guruhga 1 oylik obuna\n\n🌟 VIP Pro — 60 💎 / 30 kun\n• Plus imkoniyatlari\n• 2 para, 2 geroy\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 kun\n• Pro imkoniyatlari\n• 4 para, 4 geroy\n\n👑 VIP Ultra Promax — 150 💎 / 30 kun\n• Ultra imkoniyatlari\n• 6 para, 6 geroy\n• /boost — guruhga 2 oylik obuna",
                "⭐️ <b>VIP-подписки</b>\n\n➕ VIP Plus — 30 💎 / 30 дней\n• Переводы без комиссии\n• VIP-эмодзи\n• Писать ночью\n• 1 пара, 1 герой\n• /boost — 1 месяц подписки для группы\n\n🌟 VIP Pro — 60 💎 / 30 дней\n• Всё из Plus\n• 2 пары, 2 героя\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 дней\n• Всё из Pro\n• 4 пары, 4 героя\n\n👑 VIP Ultra Promax — 150 💎 / 30 дней\n• Всё из Ultra\n• 6 пар, 6 героев\n• /boost — 2 месяца подписки для группы",
                "⭐️ <b>VIP Subscriptions</b>\n\n➕ VIP Plus — 30 💎 / 30 days\n• Commission-free transfers\n• VIP status emoji\n• Write at night\n• 1 pair, 1 hero\n• /boost — 1 month of subscription for a group\n\n🌟 VIP Pro — 60 💎 / 30 days\n• Plus perks\n• 2 pairs, 2 heroes\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 days\n• Pro perks\n• 4 pairs, 4 heroes\n\n👑 VIP Ultra Promax — 150 💎 / 30 days\n• Ultra perks\n• 6 pairs, 6 heroes\n• /boost — 2 months of subscription for a group"),
    "vip_bought": ("✅ {n} sotib olindi (30 kun)!", "✅ {n} куплен (30 дней)!", "✅ {n} purchased (30 days)!"),
    "buyd_title": ("💎 Olmos xarid qilish usulini tanlang:", "💎 Выберите способ покупки алмазов:", "💎 Choose how to buy diamonds:"),
    "buyd_stars": ("⭐️ Stars orqali", "⭐️ Через Stars", "⭐️ With Stars"),
    "buyd_card": ("💳 Karta orqali", "💳 Картой", "💳 By card"),
    "stars_title": ("💎 Qancha olmos olmoqchisiz?\n\n⭐️ Star orqali olmos xarid qiling!", "💎 Сколько алмазов хотите?\n\n⭐️ Покупайте алмазы за Stars!", "💎 How many diamonds do you want?\n\n⭐️ Buy diamonds with Stars!"),
    "buym_title": ("💵 Dollar xarid qilish (olmosga):", "💵 Покупка долларов (за алмазы):", "💵 Buy dollars (with diamonds):"),
    "paid": ("✅ To'lov qabul qilindi! +{d} 💎", "✅ Оплата принята! +{d} 💎", "✅ Payment received! +{d} 💎"),
    "ar_title": ("Sizga aktiv rol kerakmi?\n\nKerak bo'lsa, ro'yxatdan tanlab xarid qiling (maksimal {n} ta).\nO'yin boshlanganda birinchi sotib olingan rol 100% tushadi va faol roldan o'chadi — xohlasangiz qayta sotib olasiz.",
                 "Нужна активная роль?\n\nВыберите из списка и купите (максимум {n}).\nПри старте игры первая купленная роль выпадает на 100% и снимается — можно купить снова.",
                 "Need an active role?\n\nPick one from the list and buy it (max {n}).\nAt game start your first purchased role is assigned 100% and then removed — you can buy it again."),
    "ar_del": ("❌ Faol rollarni o'chirish — 100 💶", "❌ Удалить активные роли — 100 💶", "❌ Remove active roles — 100 💶"),
    "ar_none": ("Sizda faol rol yo'q.", "У вас нет активных ролей.", "You have no active roles."),
    "ar_max": ("Faol rollar limiti to'lgan (max {n}).", "Лимит активных ролей достигнут (макс. {n}).", "Active role limit reached (max {n})."),
    "ar_ok": ("✅ Faol rol sotib olindi: {role}. Keyingi o'yinda shu rol 100% tushadi.", "✅ Активная роль куплена: {role}. В следующей игре она выпадет на 100%.", "✅ Active role purchased: {role}. You'll get it 100% next game."),
    "ar_deleted": ("✅ Faol rollar o'chirildi.", "✅ Активные роли удалены.", "✅ Active roles removed."),
    "sub_txt": ("💎 <b>Guruh obunasi</b>\n\nGuruh: <b><i>{title}</i></b>\n📅 Obuna tugashi: {until}\n💎 Sizning balansingiz: {bal}\n\nTarifni tanlang. To'lov shaxsiy olmos balansingizdan olinadi.\nFaol obuna muddati ustiga yangi muddat qo'shiladi.",
                "💎 <b>Подписка группы</b>\n\nГруппа: <b><i>{title}</i></b>\n📅 Подписка до: {until}\n💎 Ваш баланс: {bal}\n\nВыберите тариф. Оплата списывается с вашего личного баланса алмазов.\nНовый срок добавляется к действующей подписке.",
                "💎 <b>Group subscription</b>\n\nGroup: <b><i>{title}</i></b>\n📅 Expires: {until}\n💎 Your balance: {bal}\n\nChoose a plan. Payment is taken from your personal diamond balance.\nThe new period is added on top of an active subscription."),
    "sub_m": ("1 oy (30 kun)", "1 месяц (30 дней)", "1 month (30 days)"),
    "sub_y": ("1 yil (365 kun)", "1 год (365 дней)", "1 year (365 days)"),
    "sub_none": ("Faol emas", "Не активна", "Inactive"),
    "sub_nodia": ("Olmos yetarli emas. Shaxsiy balansingizni to‘ldiring.", "Недостаточно алмазов. Пополните личный баланс.", "Not enough diamonds. Top up your personal balance."),
    "sub_ok_m": ("✅ Sotib olindi! Bot aktiv holatda (1-oy)", "✅ Куплено! Бот активен (1 месяц)", "✅ Purchased! Bot is active (1 month)"),
    "sub_ok_y": ("✅ Sotib olindi! Bot aktiv holatda: 1 yil (365 kun)", "✅ Куплено! Бот активен: 1 год (365 дней)", "✅ Purchased! Bot is active: 1 year (365 days)"),
    "back_group": ("Guruhga qaytish", "Вернуться в группу", "Back to group"),
    "tr_ask": ("🔄 Profil almashish\n\nO'tkazmoqchi bo'layotgan odamingizni telegram id raqamini yuboring.\nProfilni almashish narxi: 5 💎",
               "🔄 Перенос профиля\n\nОтправьте Telegram ID человека, которому хотите передать профиль.\nСтоимость переноса: 5 💎",
               "🔄 Switch profile\n\nSend the Telegram ID of the person you want to transfer to.\nTransfer cost: 5 💎"),
    "tr_conf": ("❓ Hamma narsa (geroy, pul, olmos va h.k.) shu akkauntga o'tkazilsinmi?\n\n🆔 ID: <code>{id}</code>\n👤 Ism: {name}\n💎 Narxi: 5",
                "❓ Передать всё (героя, деньги, алмазы и т.д.) на этот аккаунт?\n\n🆔 ID: <code>{id}</code>\n👤 Имя: {name}\n💎 Стоимость: 5",
                "❓ Transfer everything (hero, money, diamonds, etc.) to this account?\n\n🆔 ID: <code>{id}</code>\n👤 Name: {name}\n💎 Cost: 5"),
    "tr_yes": ("✅ Ha", "✅ Да", "✅ Yes"), "tr_no": ("❌ Yo'q", "❌ Нет", "❌ No"),
    "tr_done": ("✅ Profil o'tkazildi.", "✅ Профиль передан.", "✅ Profile transferred."),
    "tr_got": ("🔄 Sizga profil o'tkazildi!", "🔄 Вам передан профиль!", "🔄 A profile was transferred to you!"),
    "tr_nostart": ("⚠️ Qabul qiluvchi hali botdan /start bosmagan. U botga /start bosishi kerak, shundan keyin qayta urinib ko'ring.",
                   "⚠️ Получатель ещё не нажал /start в боте. Пусть сделает это и попробуйте снова.",
                   "⚠️ The receiver hasn't pressed /start in the bot yet. Ask them to, then try again."),
    "tr_new": ("Qabul qiluvchi akkaunti yangi (0 o'yin) bo'lishi kerak.", "Аккаунт получателя должен быть новым (0 игр).", "The receiver's account must be new (0 games)."),
    "tr_5": ("5 💎 kerak.", "Нужно 5 💎.", "You need 5 💎."),
    "tr_digits": ("Faqat raqam yuboring.", "Отправьте только цифры.", "Send digits only."),
    "tr_self": ("O'zingizga o'tkaza olmaysiz.", "Нельзя передать самому себе.", "You can't transfer to yourself."),
    "night_pick": ("🌃 Tunda kimni tanlaysiz?", "🌃 Кого выберете этой ночью?", "🌃 Whom do you pick tonight?"),
    "hm_prompt": ("Harakat turini tanlang.", "Выберите действие.", "Choose an action."),
    "hm_attack": ("🥷 Hujum qilish", "🥷 Атаковать", "🥷 Attack"),
    "hm_shield": ("⚜️ Himoyalanish", "⚜️ Защититься", "⚜️ Defend"),
    "hm_skip": ("🚷 O'tkazib yuborish", "🚷 Пропустить", "🚷 Skip"),
    "you_are": ("Siz - {role}!", "Вы — {role}!", "You are {role}!"),
    "mates": ("Sheriklaringizni eslab qoling!", "Запомните своих сообщников!", "Remember your partners!"),
    "set_title": ("⚙️ <b>Sozlamalar</b>\nGuruh: <b>{title}</b>\nRejim: <b>{mode}</b>", "⚙️ <b>Настройки</b>\nГруппа: <b>{title}</b>\nРежим: <b>{mode}</b>", "⚙️ <b>Settings</b>\nGroup: <b>{title}</b>\nMode: <b>{mode}</b>"),
    "set_mode": ("🎮 O'yin rejimi", "🎮 Режим игры", "🎮 Game mode"),
    "set_roles": ("🎭 Rollarni boshqarish", "🎭 Управление ролями", "🎭 Manage roles"),
    "set_sub": ("📅 Guruh obunasi", "📅 Подписка группы", "📅 Group subscription"),
    "set_lang": ("🌐 Guruh tili", "🌐 Язык группы", "🌐 Group language"),
    "set_modes_title": ("🎮 O'yin rejimini tanlang:", "🎮 Выберите режим игры:", "🎮 Choose the game mode:"),
    "set_roles_title": ("🎭 Rollarni yoqish/o'chirish (barcha rejimlarda ishlaydi).\n✅ — yoqilgan, ❌ — o'chirilgan.", "🎭 Включение/выключение ролей (во всех режимах).\n✅ — включена, ❌ — выключена.", "🎭 Enable/disable roles (works in every mode).\n✅ — on, ❌ — off."),
    "set_lang_title": ("🌐 Guruh tilini tanlang (Premium guruhlar ro'yxati uchun):", "🌐 Выберите язык группы (для списка премиум групп):", "🌐 Choose the group language (for the premium groups list):"),
    "set_on_all": ("✅ Hammasini yoqish", "✅ Включить все", "✅ Enable all"),
    "set_off_all": ("🚫 Hammasini o'chirish", "🚫 Выключить все", "🚫 Disable all"),
    "seller_offer": ("🎁 Sotuvchi sizga bugun yarim narxdagi mahsulotlarni taklif qilmoqda:", "🎁 Продавец предлагает вам сегодня товары за полцены:", "🎁 The Seller offers you half-price items today:"),
}


def tt(uid, key, **kw):
    lg = U(uid)["lang"] if uid else "uz"
    s = LT[key][IDX.get(lg, 0)]
    return s.format(**kw) if kw else s


# ───────────────────────── Rollar ─────────────────────────
RL = [
    ("tinch", "🧑🏼", "Tinch axoli", "Sizning vazifangiz mafiani topish va ovoz berish jarayonida ularni osish"),
    ("don", "🤵🏻", "Don", "Bu tunda kim o'lishini siz hal qilasiz. Siz mafialar sardorisiz."),
    ("mafia", "🤵🏼", "Mafia", "Siz Mafiasiz, Donga boysunasiz va sizga qarshilik qilganlarni o'ldirasiz. Don o'lsa yangi Don bo'lishingiz mumkin."),
    ("manyak", "🔪", "Manyak", "Shahardagi hamma o'lishi kerak, sizdan tashqari albatta :)"),
    ("komissar", "🕵🏻‍♂️", "Komissar", "Shaharning asosiy himoyachisi va mafia qushandasi. Tunda tekshirasiz yoki otasiz."),
    ("doktor", "👨🏼‍⚕️", "Doktor", "Tunda kimnidir qutqarib qolishingiz mumkin..."),
    ("serjant", "👮🏻‍♂️", "Serjant", "Komissar katanining yordamchisi. Komissar o'lsa uning o'rnini egallaysiz."),
    ("daydi", "🧙‍♂️", "Daydi", "Xohlagan odamning uyiga ichkilik butilka olish uchun borib, qotilikning guvohi bo'lib qolishingiz mumkin."),
    ("mashuqa", "💃🏻", "Mashuqa", "Mehmonga borgan odamingizga uyqu dori berasiz va u bir kun uxlaydi (harakat qila olmaydi)."),
    ("advokat", "👨🏼‍💼", "Advokat", "Tunda kimni himoya qilishni tanlaysiz. Mafiani tanlasangiz, Komissar uni tinch aholi deb ko'radi. Siz mafia tarafdorisiz."),
    ("suidsid", "🤦🏼", "Suidsid", "Seni osib o'ldirishsa sen yutasan :)"),
    ("ubiytsa", "🥷", "Убийца", "Mafialar tarafda o'ynaysiz! Har tun kimnidir yashirincha ovlaydi, ammo komissarni nishonga olsa, komissar sizni o'ldiradi."),
    ("kamikaze", "💣", "Kamikaze", "Kechasi o'ldirilsangiz, o'ldirgan ham o'ladi. Kunlik ovozda o'ldirilsangiz, bir o'yinchini o'zingiz bilan olib ketasiz."),
    ("aferist", "🤹🏻", "Aferist", "Erkin rol. Kechasi birovga tashrif buyurib, uning ismini aldab qo'yadi. Maqsad — tirik qolish!"),
    ("minior", "☠️", "Minior", "Siz erkinsiz. Tunda tanlagan odamingiz eshigi oldiga mina qo'yasiz."),
    ("donxotin", "👩🏻‍💼", "Donning xotini", "Siz mafialar tarafdasiz. Tunda bir o'yinchining rolini bilib, mafialarga oshkor qilasiz."),
    ("zombi", "🧟‍♂️", "Zombi", "Vazifangiz hammani zombiga aylantirish."),
    ("kimyogar", "👨🏼‍🔬", "Kimyogar", "Siz mafialar tarafdasiz! Mafia a'zosini tanlasangiz himoya qilasiz, boshqalarni o'ldirasiz."),
    ("tentak", "👨🏻‍🦲", "Tentak", "Tunda bir o'yinchini tanlaysiz. Tinch taraf bo'lsa, uni o'sha kuni hech kim osa olmaydi, bo'lmasa o'ldirasiz."),
    ("buqalamun", "🦎", "Buqalamun", "Tun payti bir marta kimnidir tanlab, uning tarafida o'yinni davom ettirasiz."),
    ("sotuvchi", "🎁", "Sotuvchi", "Tunda kimnidir tanlab, ertasi kuni bot mahsulotlarini yarim narxda taklif qilasiz, sotib olsa 10% ishlaysiz."),
    ("muxlis", "🔮", "Muxlis", "Har kuni kimgadir muxlislik qilasiz. Uni o'ldirishsa, qotilga (manyakka) aylanib qasos olasiz."),
    ("omadli", "🤞🏼", "Omadli", "Omadi kulsa, suiqasddan omon qolishi mumkin bo'lgan tinch aholi."),
    ("rais", "💰", "Rais", "Tunda kimnidir tanlab, unga 50-250 dollar sovg'a berasiz."),
    ("sehrgar", "🧙‍♀️", "Sehrgar", "Sizni o'ldirishga urinsa, uni kechirish yoki kechirmaslik tanlovi beriladi."),
    ("mergan", "🎯", "Mergan", "Yakkalar ichida eng kuchlisi. Yakkalar uni o'ldira olmaydi."),
    ("janob", "🎖", "Janob", "Kunduzgi ovozda ovozingiz ikkitaga teng, shaxsingiz oshkor bo'lmaydi."),
    ("qoy", "🐑", "Qo'y", "Ovoz berishda suidsidni osishda qatnashsangiz, rolingiz qo'yga aylanadi."),
    ("jurnalist", "📰", "Jurnalist", "Tunda bir o'yinchini tekshirib, u qaysi tomonda ekanini (tinch / mafia / yakka) bilib olasiz."),
    ("qoriqchi", "💂🏻‍♂️", "Qo'riqchi", "Tunda bir o'yinchini qo'riqlaysiz: unga hujum bo'lsa, uning o'rniga siz o'lasiz."),
    ("hamshira", "👩🏻‍⚕️", "Hamshira", "Doktor o'lsa, uning o'rnini egallab Doktorga aylanasiz."),
    ("ovchi", "🏹", "Ovchi", "Sizni o'ldirishsa yoki osishsa, tasodifiy bitta mafia yoki yakka o'yinchini o'zingiz bilan olib ketasiz."),
]
RD = {k: (e, n, d) for k, e, n, d in RL}
RD["jangchi"] = ("⚔️", "Jangchi", "VS mode: har tun raqib jamoadan bitta o'yinchini nishonga olasiz. Jamoangiz nishonga eng ko'p olingan dushmanni yo'q qiladi.")
RT = {  # (ru nom, en nom, ru tavsif, en tavsif)
    "tinch": ("Мирный житель", "Civilian", "Найдите мафию и казните её на голосовании.", "Find the mafia and hang them in the vote."),
    "don": ("Дон", "Don", "Вы решаете, кто умрёт этой ночью. Вы глава мафии.", "You decide who dies tonight. You are the mafia boss."),
    "mafia": ("Мафия", "Mafia", "Вы подчиняетесь Дону и убиваете неугодных. Если Дон погибнет, можете стать новым Доном.", "You obey the Don and kill anyone in the way. If the Don dies you may become the new Don."),
    "manyak": ("Маньяк", "Maniac", "Все в городе должны умереть, кроме вас :)", "Everyone in town must die, except you :)"),
    "komissar": ("Комиссар", "Commissioner", "Главный защитник города. Ночью проверяете или стреляете.", "The city's main defender. At night you check or shoot."),
    "doktor": ("Доктор", "Doctor", "Ночью вы можете кого-то спасти...", "At night you can save someone..."),
    "serjant": ("Сержант", "Sergeant", "Помощник Комиссара. Если он погибнет — вы займёте его место.", "Commissioner's deputy. If he dies you take his place."),
    "daydi": ("Бродяга", "Tramp", "Ночью идёте к кому-то за бутылкой и можете стать свидетелем убийства.", "At night you visit someone for a bottle and may witness a murder."),
    "mashuqa": ("Любовница", "Mistress", "Усыпляете гостя — он не может действовать этой ночью.", "You put your guest to sleep — they can't act tonight."),
    "advokat": ("Адвокат", "Lawyer", "Выбираете, кого защитить. Комиссар увидит мафиози мирным. Вы на стороне мафии.", "You pick who to defend. The Commissioner sees a mafioso as civilian. You side with the mafia."),
    "suidsid": ("Суицидник", "Suicide", "Если вас повесят — вы побеждаете :)", "If they hang you, you win :)"),
    "ubiytsa": ("Убийца", "Assassin", "Играете за мафию! Каждую ночь тайно охотитесь, но если выберете комиссара — он убьёт вас.", "You play for the mafia! You hunt secretly each night, but if you target the Commissioner he kills you."),
    "kamikaze": ("Камикадзе", "Kamikaze", "Если вас убьют ночью, убийца умрёт тоже. Если повесят — заберёте одного с собой.", "If killed at night, your killer dies too. If hanged, you take one player with you."),
    "aferist": ("Аферист", "Swindler", "Свободная роль. Ночью обманывает проверки. Цель — выжить!", "Free role. At night you fool investigations. Goal — survive!"),
    "minior": ("Минёр", "Miner", "Свободная роль. Ночью ставите мину у двери выбранного игрока.", "Free role. At night you plant a mine at a chosen player's door."),
    "donxotin": ("Жена Дона", "Don's Wife", "На стороне мафии. Ночью узнаёте роль игрока и сообщаете мафии.", "Mafia side. At night you learn a player's role and tell the mafia."),
    "zombi": ("Зомби", "Zombie", "Ваша цель — превратить всех в зомби.", "Your goal is to turn everyone into zombies."),
    "kimyogar": ("Химик", "Chemist", "На стороне мафии! Члена мафии защищаете, остальных убиваете.", "Mafia side! You protect a mafia member and kill everyone else."),
    "tentak": ("Дурак", "Fool", "Ночью выбираете игрока. Если он мирный — днём его не повесят, иначе вы его убьёте.", "At night you pick a player. If peaceful, nobody can hang them that day; otherwise you kill them."),
    "buqalamun": ("Хамелеон", "Chameleon", "Один раз выбираете игрока и переходите на его сторону.", "Once you pick a player and join their side."),
    "sotuvchi": ("Продавец", "Seller", "Выбираете игрока: на следующий день он получит товары бота за полцены, вы заработаете 10%.", "Pick a player: next day they get bot items at half price and you earn 10%."),
    "muxlis": ("Фанат", "Fan", "Выбираете кумира. Если его убьют — вы становитесь маньяком и мстите.", "You pick an idol. If they're killed you become a maniac and take revenge."),
    "omadli": ("Везунчик", "Lucky", "Мирный житель, которому может повезти пережить покушение.", "A civilian who may luckily survive an assassination attempt."),
    "rais": ("Босс", "Boss", "Ночью дарите выбранному игроку 50–250 долларов.", "At night you gift a chosen player $50–250."),
    "sehrgar": ("Волшебник", "Wizard", "Если вас пытаются убить, вам дают выбор — простить или нет.", "If someone tries to kill you, you choose to forgive or not."),
    "mergan": ("Снайпер", "Sniper", "Сильнейший среди одиночек. Одиночки не могут его убить.", "The strongest among solos. Solo killers can't kill you."),
    "janob": ("Господин", "Gentleman", "Ваш голос днём равен двум, личность скрыта.", "Your daytime vote counts double and your identity stays hidden."),
    "qoy": ("Овца", "Sheep", "Если участвуете в повешении суицидника, ваша роль станет овцой.", "If you take part in hanging the suicide, you turn into a sheep."),
    "jurnalist": ("Журналист", "Journalist", "Ночью проверяете игрока и узнаёте, на чьей он стороне.", "At night you check a player and learn which side they're on."),
    "qoriqchi": ("Телохранитель", "Bodyguard", "Ночью охраняете игрока: если на него нападут, вы умрёте вместо него.", "At night you guard a player: if attacked, you die in their place."),
    "hamshira": ("Медсестра", "Nurse", "Если Доктор погибнет, вы займёте его место.", "If the Doctor dies, you take his place."),
    "ovchi": ("Охотник", "Hunter", "Если вас убьют или повесят, вы заберёте с собой случайного мафиози или одиночку.", "If you're killed or hanged, you take a random mafioso or solo player with you."),
    "jangchi": ("Боец", "Fighter", "VS режим: каждую ночь целитесь в игрока команды соперников.", "VS mode: each night you target a player of the enemy team."),
}


def rname(k, uid=None):
    e, n, d = RD[k]
    if uid and k in RT:
        lg = U(uid)["lang"]
        if lg in ("ru", "en"): n = RT[k][0 if lg == "ru" else 1]
    return f"{e} {n}"


def rdesc(k, uid=None):
    d = RD[k][2]
    if uid and k in RT:
        lg = U(uid)["lang"]
        if lg in ("ru", "en"): d = RT[k][2 if lg == "ru" else 3]
    return d


MAF = {"don", "mafia", "advokat", "ubiytsa", "donxotin", "kimyogar"}
SOLO = {"manyak", "suidsid", "aferist", "minior", "zombi"}
# Faol rol narxlari: ("d" = 💎, "m" = 💶)
ARP = {"ubiytsa": ("d", 5), "mergan": ("d", 2), "minior": ("d", 1), "suidsid": ("d", 5), "komissar": ("d", 3),
       "don": ("d", 2), "manyak": ("d", 2), "kimyogar": ("d", 3), "tentak": ("d", 1), "mafia": ("d", 1),
       "serjant": ("d", 1), "aferist": ("d", 2), "buqalamun": ("d", 1), "muxlis": ("d", 1), "sehrgar": ("d", 1), "ovchi": ("d", 2),
       "doktor": ("m", 600), "rais": ("m", 500), "mashuqa": ("m", 500), "advokat": ("m", 300),
       "kamikaze": ("m", 700), "daydi": ("m", 500), "donxotin": ("m", 500), "tinch": ("m", 200),
       "sotuvchi": ("m", 400), "omadli": ("m", 300), "janob": ("m", 600), "jurnalist": ("m", 500),
       "qoriqchi": ("m", 500), "hamshira": ("m", 400)}
ACT = {"don": [("k", "🔪")], "mafia": [("k", "🔪")], "ubiytsa": [("k", "🥷")], "manyak": [("k", "🔪")],
       "komissar": [("c", "🔍"), ("s", "🔫")], "doktor": [("h", "💉")], "mashuqa": [("b", "💃")], "advokat": [("a", "⚖️")],
       "daydi": [("d", "🍾")], "aferist": [("x", "🤹")], "minior": [("m", "💣")], "donxotin": [("w", "👁")],
       "kimyogar": [("e", "⚗️")], "tentak": [("t", "🎲")], "buqalamun": [("y", "🦎")], "sotuvchi": [("v", "🎁")],
       "muxlis": [("f", "⭐️")], "rais": [("g", "💰")], "zombi": [("z", "🧟")], "jurnalist": [("j", "📰")],
       "qoriqchi": [("q", "🛡")]}
ACT_VS = {"jangchi": [("k", "🎯")], "doktor": [("h", "💉")]}
FLAV = {"mergan": "🎯 Mergan tepkini bosdi", "buqalamun": "🦎 Buqalamun o'z tomonini tanladi",
        "manyak": "🔪 Manyak butalar orasiga yashirinib pichoqni qinidan chiqardi", "aferist": "🤹🏻 Aferist o'ljasini tanladi",
        "muxlis": "🔮 Muxlis dasht olishga ketdi", "komissar": "🕵🏻‍♂️ Komissar yozuvlarni tekshirishga ketdi",
        "mashuqa": "💃🏻 Mashuqa kimnikigadir mehmonga ketdi", "daydi": "🧙‍♂️ Daydi kimnikigadir shisha olish uchun ketdi",
        "zombi": "🧟‍♂️ Zombi ovga chiqdi"}
HOW = {"mafia": "mafialar", "manyak": "manyak", "ubiytsa": "qotil", "komissar": "komissar", "hero": "geroy",
       "kamikaze": "kamikaze portlashi", "vs": "dushman jamoa", "mine": "minior minasi", "kimyogar": "kimyogar",
       "tentak": "tentak", "sehrgar": "sehrgar", "ovchi": "ovchi o'qi"}
TEAM = {"r": "🔴 Qizil", "b": "🔵 Ko'k"}


def roles_kb_u(uid):
    b = InlineKeyboardBuilder()
    for k, e, n, d in RL: b.button(text=rname(k, uid), callback_data=f"ri:{k}")
    b.adjust(2); return b.as_markup()


def C(*names):
    """/game va /gamenightmafiauzbot (qo'shimcha nom) ikkalasini ham qabul qiladi."""
    return Command(*names, *[n + SUF for n in names])


GROUP = F.chat.type.in_({"group", "supergroup"})


@r.message(C("roles"))
async def cmd_roles(m: Message):
    await m.answer(tt(m.from_user.id, "roles_hdr"), reply_markup=roles_kb_u(m.from_user.id))


@r.callback_query(F.data.startswith("ri:"))
async def cb_role(c: CallbackQuery):
    k = c.data[3:]; uid = c.from_user.id
    if k not in RD: return await c.answer()
    await c.answer(f"{tt(uid, 'you_are', role=rname(k, uid))}\n\n{rdesc(k, uid)}"[:200], show_alert=True)


# ───────────────────────── Middleware: blok, username, eski klaviatura, tungi chat ─────────────────────────
KBCLR = set()
ADMC = {}


async def rm_kb(chat_id):
    """Eski reply-klaviatura (Start Game / Profile / Top / Rules / Settings) ni olib tashlaydi."""
    if chat_id in KBCLR: return
    KBCLR.add(chat_id)
    try:
        x = await bot.send_message(chat_id, ".", reply_markup=ReplyKeyboardRemove(remove_keyboard=True))
        await x.delete()
    except Exception: pass


async def chat_admin(chat, uid):
    if is_admin(uid): return True
    k = (chat, uid); c_ = ADMC.get(k)
    if c_ and time.time() - c_[0] < 60: return c_[1]
    try: ok_ = (await bot.get_chat_member(chat, uid)).status in ("administrator", "creator")
    except Exception: ok_ = False
    ADMC[k] = (time.time(), ok_); return ok_


class Track(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and not u.is_bot:
            row = U(u.id, u.full_name)
            if row["blocked"] and not is_admin(u.id): return
            if (u.username or "") != (row["username"] or ""): S(u.id, username=u.username or "")
        return await handler(event, data)


class MsgMW(BaseMiddleware):
    """1) buyruq yozilganda eski klaviaturani olib tashlaydi; 2) tunda faqat VIP yoza oladi (adminlar '!' bilan)."""
    async def __call__(self, handler, event: Message, data):
        txt = event.text or ""
        if txt.startswith("/") and event.chat.id not in KBCLR: asyncio.create_task(rm_kb(event.chat.id))
        if event.chat.type in ("group", "supergroup"):
            g = games.get(event.chat.id)
            if (g and g.state in ("night", "resolving") and event.from_user and not event.from_user.is_bot
                    and not event.sender_chat and not txt.startswith("/")
                    and event.content_type in ("text", "photo", "sticker", "voice", "video", "animation", "video_note", "document", "audio")):
                uid = event.from_user.id
                ok_ = is_admin(uid) or vlevel(U(uid)) > 0 or (txt.startswith("!") and await chat_admin(event.chat.id, uid))
                if not ok_:
                    try: await event.delete()
                    except Exception: pass
                    return
        return await handler(event, data)


dp.update.outer_middleware(Track())
dp.message.outer_middleware(MsgMW())


# ───────────────────────── /start, premium guruhlar, til ─────────────────────────
PL = [("uz", "🇺🇿 O'zbekcha"), ("ru", "🇷🇺 Русский"), ("en", "🇺🇸 English"), ("ar", "🇸🇦 العربية"), ("id", "🇮🇩 Indonesia"),
      ("kk", "🇰🇿 Қазақша"), ("tr", "🇹🇷 Türkçe"), ("ko", "🇰🇷 한국어"), ("es", "🇪🇸 Español"), ("pt", "🇧🇷 Português"),
      ("fr", "🇫🇷 Français"), ("hi", "🇮🇳 हिन्दी"), ("ur", "🇵🇰 اردو")]
PLD = dict(PL)
_HAS_STYLE = "style" in getattr(InlineKeyboardButton, "model_fields", {})


def sty(x):
    """Tugma rangi (Bot API 9.4+): aiogram yangi bo'lsa qo'llanadi, bo'lmasa e'tiborsiz qoldiriladi."""
    return {"style": x} if _HAS_STYLE else {}



def cab_button(b, uid):
    if WEB_HTTPS: b.button(text="🌐 " + tt(uid, "btn_cab"), web_app=WebAppInfo(url=WEB_URL + "/app"))
    else: b.button(text="🌐 " + tt(uid, "btn_cab"), callback_data="m:profile")


def start_kb(uid):
    b = InlineKeyboardBuilder()
    cab_button(b, uid)
    b.button(text="✅ " + tt(uid, "btn_gap"), url=f"https://t.me/{BOTNAME}?startgroup=true", **sty("success"))
    b.button(text="✍️ " + tt(uid, "btn_ask"), url=CARD_USER, **sty("success"))
    b.button(text="⭐️ " + tt(uid, "btn_prem"), callback_data="pg:menu", **sty("primary"))
    b.button(text="🎄 " + tt(uid, "btn_news"), url=NEWS)
    b.button(text="🌐 " + tt(uid, "btn_lang"), callback_data="m:lang")
    b.adjust(1, 1, 2, 2); return b.as_markup()


def lang_kb(uid):
    cur = U(uid)["lang"]; b = InlineKeyboardBuilder()
    for code, label in (("uz", "🇺🇿 O'zbekcha"), ("ru", "🇷🇺 Русский"), ("en", "🇬🇧 English")):
        b.button(text=label + (" ◾" if code == cur else ""), callback_data=f"l:{code}")
    b.adjust(1); return b.as_markup()


@r.message(CommandStart(deep_link=True), F.chat.type == "private")
async def start_dl(m: Message, command: CommandObject):
    U(m.from_user.id, m.from_user.full_name)
    a = command.args or ""
    try:
        if a.startswith("sub"): return await sub_page(m, -int(a[3:]))
        if a.startswith("vs"):
            ch, tm = a[2:].rsplit("_", 1); return await vs_join_pm(m, int(ch), tm)
        if a.startswith("j"): return await join_game(m, int(a[1:]))
    except ValueError: pass
    await start_pm(m)


@r.message(CommandStart(), F.chat.type == "private")
async def start_pm(m: Message):
    U(m.from_user.id, m.from_user.full_name)
    await m.answer(tt(m.from_user.id, "start"), reply_markup=start_kb(m.from_user.id))


@r.message(Command("language"), F.chat.type == "private")
async def cmd_language(m: Message):
    uid = m.from_user.id; await m.answer(tt(uid, "langtitle"), reply_markup=lang_kb(uid))


@r.callback_query(F.data == "m:lang")
async def m_lang(c: CallbackQuery):
    uid = c.from_user.id; await c.message.answer(tt(uid, "langtitle"), reply_markup=lang_kb(uid)); await c.answer()


@r.callback_query(F.data == "m:start")
async def m_start(c: CallbackQuery):
    uid = c.from_user.id
    try: await c.message.edit_text(tt(uid, "start"), reply_markup=start_kb(uid))
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("l:"))
async def set_lang(c: CallbackQuery):
    uid = c.from_user.id; S(uid, lang=c.data[2:])
    try: await c.message.edit_text(tt(uid, "langtitle"), reply_markup=lang_kb(uid))
    except Exception: pass
    await c.answer()


# ---- Premium guruhlar ----
def pg_menu_kb(uid):
    b = InlineKeyboardBuilder()
    for code, label in PL: b.button(text=label, callback_data=f"pg:l:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=tt(uid, "back"), callback_data="m:start", **sty("danger")),
          InlineKeyboardButton(text="➕ " + tt(uid, "prem_add"),
                               url=f"https://t.me/{BOTNAME}?startgroup=premium&admin=delete_messages+pin_messages+invite_users"))
    return b.as_markup()


@r.callback_query(F.data.startswith("pg:"))
async def cb_pg(c: CallbackQuery):
    uid = c.from_user.id; a = c.data.split(":")
    if a[1] == "menu":
        try: await c.message.edit_text(tt(uid, "btn_prem"), reply_markup=pg_menu_kb(uid))
        except Exception: pass
        return await c.answer()
    code = a[2] if len(a) > 2 else "uz"
    rows = db.execute("SELECT * FROM groups WHERE listed=1 AND glang=? AND sub_until>? AND invite LIKE 'https://%' ORDER BY sub_until DESC LIMIT 40",
                      (code, int(time.time()))).fetchall()
    b = InlineKeyboardBuilder()
    for x in rows: b.button(text=f"👥 {x['title'] or x['id']}"[:60], url=x["invite"])
    b.adjust(1); b.row(InlineKeyboardButton(text=tt(uid, "back"), callback_data="pg:menu", **sty("danger")))
    txt = f"{tt(uid, 'btn_prem')} — {PLD.get(code, code)}" if rows else tt(uid, "prem_none")
    try: await c.message.edit_text(txt, reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.message(CommandStart(deep_link=True), GROUP)
async def grp_premium(m: Message, command: CommandObject):
    if (command.args or "") != "premium": return
    if not await chat_admin(m.chat.id, m.from_user.id): return await m.reply("⛔️ Faqat guruh adminlari.")
    url = await group_url(m.chat.id)
    gset(m.chat.id, listed=1, title=m.chat.title or "", invite=url or "")
    b = InlineKeyboardBuilder()
    for code, label in PL: b.button(text=label, callback_data=f"gl:{m.chat.id}:{code}")
    b.adjust(2)
    await m.answer("✅ Guruh «Premium guruhlar» ro'yxatiga qo'shildi (faol obunasi bo'lsa ko'rinadi).\n🌐 Guruh tilini tanlang:", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("gl:"))
async def cb_glang(c: CallbackQuery):
    _, ch, code = c.data.split(":"); chat = int(ch)
    if not await chat_admin(chat, c.from_user.id): return await c.answer("Faqat adminlar", show_alert=True)
    gset(chat, glang=code if code in PLD else "uz")
    try: await c.message.edit_text(f"✅ Guruh tili: {PLD.get(code, code)}")
    except Exception: pass
    await c.answer()


# ───────────────────────── Profil ─────────────────────────
def onoff(v): return "🟢 ON" if v else "🔴 OFF"


def prof(uid):
    u = U(uid); lv = vlevel(u); ar = aroles(u)
    arl = "".join(f"\n{rname(x, uid)}" for x in ar if x in RD) if ar else f" <i>{tt(uid, 'none')}</i>"
    vip = f"\n{VIPS[lv][0]}" if lv else ""
    txt = tt(uid, "prof", name=esc(u["name"] or str(uid)), vip=vip, money=n_(u["money"]), dia=n_(u["diamonds"]), nc=n_(u["ncoin"]),
             h=n_(u["himoya"]), d=n_(u["hujjat"]), o=n_(u["osish"]), g=n_(u["geroyd"]), w=n_(u["wins"]), gm=n_(u["games"]), ar=arl)
    b = InlineKeyboardBuilder()
    b.button(text=f"🛡 - {onoff(u['t_h'])}", callback_data="tg:t_h")
    b.button(text=f"📁 - {onoff(u['t_d'])}", callback_data="tg:t_d")
    b.button(text=f"⚖️ - {onoff(u['t_o'])}", callback_data="tg:t_o")
    b.button(text=f"🔰 - {onoff(u['t_g'])}", callback_data="tg:t_g")
    b.button(text=tt(uid, "p_shop"), callback_data="m:shop")
    b.button(text=tt(uid, "p_buyd"), callback_data="m:buyd")
    b.button(text=tt(uid, "p_buym"), callback_data="m:buym")
    b.button(text=tt(uid, "p_hero"), callback_data="m:hero")
    b.button(text=tt(uid, "p_tr"), callback_data="m:transfer")
    if WEB_HTTPS: b.button(text="🌐 " + tt(uid, "btn_cab"), web_app=WebAppInfo(url=WEB_URL + "/app"))
    b.adjust(2, 2, 1, 2, 1, 1, 1)
    return txt, b.as_markup()


@r.message(Command("profile"))
async def cmd_profile(m: Message):
    if m.chat.type != "private": return await m.reply("Profilni shaxsiy chatda ko'ring.")
    U(m.from_user.id, m.from_user.full_name); t_, k = prof(m.from_user.id); await m.answer(t_, reply_markup=k)


@r.callback_query(F.data == "m:profile")
async def m_prof(c: CallbackQuery):
    U(c.from_user.id, c.from_user.full_name); t_, k = prof(c.from_user.id)
    try: await c.message.edit_text(t_, reply_markup=k)
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("tg:"))
async def toggle(c: CallbackQuery):
    f = c.data[3:]
    if f not in ("t_h", "t_d", "t_o", "t_g"): return await c.answer()
    u = U(c.from_user.id); S(c.from_user.id, **{f: 0 if u[f] else 1})
    t_, k = prof(c.from_user.id)
    try: await c.message.edit_text(t_, reply_markup=k)
    except Exception: pass
    await c.answer()


# ───────────────────────── Do'kon ─────────────────────────
ITEMS = {"himoya": ("money", 300), "hujjat": ("money", 200), "osish": ("diamonds", 1), "geroyd": ("diamonds", 3), "ncoin": ("diamonds", 100)}
CUR = {"money": "💶", "diamonds": "💎"}


def back(uid, to="m:profile"):
    b = InlineKeyboardBuilder(); b.button(text=tt(uid, "back"), callback_data=to); return b


@r.callback_query(F.data == "m:shop")
async def m_shop(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (cur, p) in ITEMS.items(): b.button(text=f"{tt(uid, 'it_' + k)} — {p} {CUR[cur]}", callback_data=f"b:{k}")
    b.button(text=tt(uid, "sh_hero"), callback_data="b:hero")
    b.button(text=tt(uid, "sh_hero_s"), callback_data="sh")
    b.button(text=tt(uid, "sh_vip"), callback_data="m:vip")
    b.button(text=tt(uid, "sh_ar"), callback_data="m:arole")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    txt = tt(uid, "shop_title") + "\n\n" + "\n\n".join(
        f"{tt(uid, 'it_' + k)}\n{tt(uid, 'itd_' + k)}\n{tt(uid, 'price')}: {p} {CUR[cur]}" for k, (cur, p) in ITEMS.items())
    try: await c.message.edit_text(txt, reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("b:"))
async def buy(c: CallbackQuery):
    k = c.data[2:]; uid = c.from_user.id; u = U(uid)
    if k == "hero":
        lim = hlim(uid)
        if hcount(uid) >= lim: return await c.answer(tt(uid, "hero_full", n=lim), show_alert=True)
        if u["diamonds"] < 90: return await c.answer(tt(uid, "no_dia"), show_alert=True)
        A(uid, "diamonds", -90); add_hero(uid)
        return await c.answer(tt(uid, "hero_bought"), show_alert=True)
    if k not in ITEMS: return await c.answer()
    cur, p = ITEMS[k]
    if u[cur] < p: return await c.answer(tt(uid, "no_dia" if cur == "diamonds" else "no_money"), show_alert=True)
    A(uid, cur, -p); A(uid, k, 1)
    await c.answer(tt(uid, "bought", n=tt(uid, "it_" + k)), show_alert=True)


@r.callback_query(F.data == "sh")
async def stars_hero(c: CallbackQuery):
    uid = c.from_user.id; lim = hlim(uid)
    if hcount(uid) >= lim: return await c.answer(tt(uid, "hero_full", n=lim), show_alert=True)
    await bot.send_invoice(uid, "🥷 Geroy", "1-daraja geroy", "hero", "XTR", [LabeledPrice(label="Geroy", amount=300)])
    await c.answer()


@r.callback_query(F.data == "m:vip")
async def m_vip(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (n, p) in VIPS.items(): b.button(text=f"{n} — {p} 💎", callback_data=f"v:{k}")
    b.button(text=tt(uid, "back"), callback_data="m:shop"); b.adjust(1)
    try: await c.message.edit_text(tt(uid, "vip_txt"), reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("v:"))
async def buy_vip(c: CallbackQuery):
    k = int(c.data[2:]); uid = c.from_user.id; u = U(uid)
    if k not in VIPS: return await c.answer()
    n, p = VIPS[k]
    if u["diamonds"] < p: return await c.answer(tt(uid, "no_dia"), show_alert=True)
    A(uid, "diamonds", -p); grant_vip(uid, k)             # har sotib olishda 1 ta /boost beriladi
    await c.answer(tt(uid, "vip_bought", n=n), show_alert=True)


@r.callback_query(F.data == "m:arole")
async def m_arole(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (cur, p) in ARP.items():
        b.button(text=f"{rname(k, uid)} — {p} {'💎' if cur == 'd' else '💶'}", callback_data=f"ar:{k}")
    b.button(text=tt(uid, "ar_del"), callback_data="ar:del")
    b.button(text=tt(uid, "back"), callback_data="m:shop"); b.adjust(2)
    try: await c.message.edit_text(tt(uid, "ar_title", n=AMAX), reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("ar:"))
async def buy_arole(c: CallbackQuery):
    k = c.data[3:]; uid = c.from_user.id; u = U(uid); lst = aroles(u)
    if k == "del":
        if not lst: return await c.answer(tt(uid, "ar_none"), show_alert=True)
        if u["money"] < 100: return await c.answer(tt(uid, "no_money"), show_alert=True)
        A(uid, "money", -100); S(uid, arole=""); return await c.answer(tt(uid, "ar_deleted"), show_alert=True)
    if k not in ARP: return await c.answer()
    if len(lst) >= AMAX: return await c.answer(tt(uid, "ar_max", n=AMAX), show_alert=True)
    cur, p = ARP[k]; f = "diamonds" if cur == "d" else "money"
    if u[f] < p: return await c.answer(tt(uid, "no_bal"), show_alert=True)
    A(uid, f, -p); S(uid, arole=",".join(lst + [k]))
    await c.answer(tt(uid, "ar_ok", role=rname(k, uid)), show_alert=True)


# ───────────────────────── Olmos / dollar xaridi ─────────────────────────
STARS = {1: 5, 10: 50, 40: 200, 100: 500, 200: 1000, 1000: 5000}
DOLLAR = {1: 150, 5: 750, 10: 1500}


@r.callback_query(F.data == "m:buyd")
async def m_buyd(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    b.button(text=tt(uid, "buyd_stars"), callback_data="sd"); b.button(text=tt(uid, "buyd_card"), url=CARD_USER)
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    try: await c.message.edit_text(tt(uid, "buyd_title"), reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data == "sd")
async def stars_menu(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for d, s in STARS.items(): b.button(text=f"{d} 💎 = {s} ⭐️", callback_data=f"st:{d}")
    b.button(text=tt(uid, "back"), callback_data="m:buyd"); b.adjust(2)
    try: await c.message.edit_text(tt(uid, "stars_title"), reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("st:"))
async def stars_invoice(c: CallbackQuery):
    d = int(c.data[3:])
    if d not in STARS: return await c.answer()
    await bot.send_invoice(c.from_user.id, f"{d} 💎 olmos", "Olmos xaridi", f"dia:{d}", "XTR", [LabeledPrice(label=f"{d} olmos", amount=STARS[d])])
    await c.answer()


@r.pre_checkout_query()
async def pre(q: PreCheckoutQuery): await q.answer(True)


@r.message(F.successful_payment)
async def paid(m: Message):
    uid = m.from_user.id; pl = m.successful_payment.invoice_payload
    if pl == "hero":
        if hcount(uid) < hlim(uid): add_hero(uid); return await m.answer(tt(uid, "hero_bought"))
        A(uid, "diamonds", 90); return await m.answer("🥷 Geroy sloti to'lgan — 90 💎 hisobingizga qaytarildi.")
    if pl.startswith("vip:"):
        k = int(pl.split(":")[1])
        if k in VIPS: grant_vip(uid, k); return await m.answer(tt(uid, "vip_bought", n=VIPS[k][0]))
    d = int(pl.split(":")[1]); A(uid, "diamonds", d)
    await m.answer(tt(uid, "paid", d=d))


@r.callback_query(F.data == "m:buym")
async def m_buym(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for d, p in DOLLAR.items(): b.button(text=f"{d} 💎 → {p} 💶", callback_data=f"dm:{d}")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    try: await c.message.edit_text(tt(uid, "buym_title"), reply_markup=b.as_markup())
    except Exception: pass
    await c.answer()


@r.callback_query(F.data.startswith("dm:"))
async def buy_dollar(c: CallbackQuery):
    d = int(c.data[3:]); uid = c.from_user.id
    if d not in DOLLAR: return await c.answer()
    if U(uid)["diamonds"] < d: return await c.answer(tt(uid, "no_dia"), show_alert=True)
    A(uid, "diamonds", -d); A(uid, "money", DOLLAR[d]); await c.answer(f"✅ +{DOLLAR[d]} 💶", show_alert=True)


# ───────────────────────── Geroy ─────────────────────────
MAXH = [0, 0, 10, 20, 30, 40, 50, 50, 60, 70, 80, 90, 100, 100, 110, 120, 130, 140, 150, 150, 160, 170, 180, 190,
        200, 200, 210, 220, 230, 240, 250, 250, 260, 270, 280, 290, 300, 300]
WAIT = {}
PEND = {}


def lvl(p): return min(38, p // 1100 + 1)


def lvl_list(uid):
    out = []
    for i in range(38):
        pw = tt(uid, "pow_range", a=40 + 7 * i, b=47 + 7 * i) if i < 37 else tt(uid, "pow_max")
        out.append(tt(uid, "lvl_fmt", i=i + 1, pts=i * 1100, pow=pw, mh=MAXH[i]))
    return out


def hero_dmg(uid):
    L_ = lvl(U(uid)["points"])
    return min(100, random.randint(40 + 7 * (L_ - 1), 47 + 7 * (L_ - 1)))


def hero_txt(u, uid, short=False):
    L_ = lvl(u["points"])
    pw = tt(uid, "pow_range", a=40 + 7 * (L_ - 1), b=47 + 7 * (L_ - 1)) if L_ < 38 else tt(uid, "pow_max")
    nxt = tt(uid, "hero_next", n=L_ + 1, p=L_ * 1100) if L_ < 38 else ""
    s = tt(uid, "hero_fmt", name=esc(u["hname"]) or tt(uid, "noname"), L=L_, pow=pw, hp=u["hprot"], mh=MAXH[L_ - 1],
           ch=u["charge"], pts=u["points"], gd=u["geroyd"], nxt=nxt)
    return s if short else s + "\n\n" + tt(uid, "hero_shop")


@r.callback_query(F.data == "m:hero")
async def m_hero(c: CallbackQuery):
    uid = c.from_user.id; u = U(uid); lim = hlim(uid); cnt = hcount(uid); b = InlineKeyboardBuilder()
    if not u["has_hero"]:
        b.button(text=tt(uid, "hb_buy_d"), callback_data="b:hero"); b.button(text=tt(uid, "hb_buy_s"), callback_data="sh")
        b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
        try: await c.message.edit_text(tt(uid, "hero_none"), reply_markup=b.as_markup())
        except Exception: pass
        return await c.answer()
    for t_, d in [(tt(uid, "hb_ball"), "h:ball"), (tt(uid, "hb_prot"), "h:prot"), (tt(uid, "hb_charge"), "h:charge"),
                  (tt(uid, "hb_name"), "h:name"), (tt(uid, "hb_lvls"), "h:lvls"), (tt(uid, "hb_status"), "h:status")]:
        b.button(text=t_, callback_data=d)
    if cnt > 1: b.button(text=tt(uid, "hb_list", n=cnt, lim=lim), callback_data="h:list")
    if cnt < lim: b.button(text=tt(uid, "hb_buy_d"), callback_data="b:hero"); b.button(text=tt(uid, "hb_buy_s"), callback_data="sh")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    try: await c.message.edit_text(hero_txt(u, uid), reply_markup=b.as_markup())
    except Exception: pass
    try: await c.answer()
    except Exception: pass


@r.callback_query(F.data.startswith("hs:"))
async def hero_select(c: CallbackQuery):
    uid = c.from_user.id; hid = int(c.data[3:])
    if hid: hero_swap(uid, hid)
    await m_hero(c)


@r.callback_query(F.data.startswith("h:"))
async def hero_act(c: CallbackQuery):
    a = c.data[2:]; uid = c.from_user.id; u = U(uid)
    if not u["has_hero"]: return await c.answer("Geroy yo'q", show_alert=True)
    if a == "lvls":
        ls = lvl_list(uid)
        await c.message.answer("\n\n".join(ls[:19]))
        await c.message.answer("\n\n".join(ls[19:]) + "\n\n" + tt(uid, "lvl_yours", n=lvl(u["points"])))
        return await c.answer()
    if a == "list":
        b = InlineKeyboardBuilder()
        b.button(text=f"✅ {u['hname'] or tt(uid, 'noname')} — {lvl(u['points'])}", callback_data="hs:0")
        for x in db.execute("SELECT * FROM heroes WHERE uid=? ORDER BY id", (uid,)):
            b.button(text=f"🥷 {x['name'] or tt(uid, 'noname')} — {lvl(x['points'])}", callback_data=f"hs:{x['id']}")
        b.button(text=tt(uid, "back"), callback_data="m:hero"); b.adjust(1)
        try: await c.message.edit_text(tt(uid, "h_list", n=hcount(uid), lim=hlim(uid)), reply_markup=b.as_markup())
        except Exception: pass
        return await c.answer()
    if a == "status":
        WAIT[uid] = "status"; await c.message.answer(tt(uid, "h_status_ask")); return await c.answer()
    if a == "name":
        if u["money"] < 800: return await c.answer(tt(uid, "h_no800"), show_alert=True)
        WAIT[uid] = "hname"; await c.message.answer(tt(uid, "h_name_ask")); return await c.answer()
    if a not in ("ball", "prot", "charge"): return await c.answer()
    cost = {"ball": ("diamonds", 50), "prot": ("money", 300), "charge": ("money", 200)}[a]
    if u[cost[0]] < cost[1]: return await c.answer(tt(uid, "no_bal"), show_alert=True)
    A(uid, cost[0], -cost[1])
    if a == "ball": A(uid, "points", 1000); await c.answer(tt(uid, "h_ball_ok"), show_alert=True)
    if a == "prot": S(uid, hprot=MAXH[lvl(u["points"]) - 1]); await c.answer(tt(uid, "h_prot_ok"), show_alert=True)
    if a == "charge": S(uid, charge=10); await c.answer(tt(uid, "h_charge_ok"), show_alert=True)
    await m_hero(c)


@r.message(Command("geroyinfo"))
async def geroyinfo(m: Message):
    tg = m.reply_to_message.from_user if m.reply_to_message else m.from_user; u = U(tg.id, tg.full_name)
    await m.reply(hero_txt(u, m.from_user.id, True) if u["has_hero"] else "Bu foydalanuvchida geroy yo'q.")


@r.message(C("gtop"))
async def gtop(m: Message):
    rows = db.execute("SELECT * FROM users WHERE has_hero=1 ORDER BY points DESC LIMIT 10").fetchall()
    await m.answer("🏆 <b>Geroylar reytingi</b>\n\n" + ("\n".join(
        f"{i}. {esc(x['hname'] or 'nomsiz')} ({esc(x['name'])}) — {lvl(x['points'])}-daraja, {x['points']} ball"
        for i, x in enumerate(rows, 1)) or "Hozircha yo'q"))


@r.message(Command("tgeroy"))
async def tgeroy(m: Message):
    if not m.reply_to_message: return await m.reply("Geroyni sotish uchun xaridorga reply qiling.")
    s, tg = m.from_user, m.reply_to_message.from_user; u = U(s.id); ub = U(tg.id, tg.full_name)
    if not u["has_hero"] or hcount(tg.id) >= HLIM[vlevel(ub)]: return await m.reply("Sizda geroy yo'q yoki xaridorda geroy sloti to'lgan.")
    price = lvl(u["points"]) * 10
    b = InlineKeyboardBuilder(); b.button(text=f"✅ Sotib olish ({price} 💎)", callback_data=f"tb:{s.id}:{tg.id}:{price}")
    b.button(text="❌ Rad etish", callback_data=f"tb:{s.id}:{tg.id}:0")
    await m.answer(f"{esc(tg.full_name)}, {esc(s.full_name)} geroyini ({lvl(u['points'])}-daraja) {price} 💎 ga sotmoqda.", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("tb:"))
async def tgeroy_buy(c: CallbackQuery):
    _, s, tg, p = c.data.split(":"); s, tg, p = int(s), int(tg), int(p)
    if c.from_user.id != tg: return await c.answer("Bu siz uchun emas", show_alert=True)
    if p == 0: return await c.message.edit_text("❌ Rad etildi.")
    us, ut = U(s), U(tg)
    if not us["has_hero"] or hcount(tg) >= HLIM[vlevel(ut)] or ut["diamonds"] < p:
        return await c.answer("Shartlar bajarilmadi (olmos/geroy).", show_alert=True)
    A(tg, "diamonds", -p); A(s, "diamonds", p)
    add_hero(tg, us["hname"], us["points"], us["hprot"], us["charge"]); hero_remove_active(s)
    await c.message.edit_text("✅ Geroy sotildi!")


# ───────────────────────── Profil almashish ─────────────────────────
@r.callback_query(F.data == "m:transfer")
async def m_transfer(c: CallbackQuery):
    uid = c.from_user.id; WAIT[uid] = "transfer"
    await c.message.answer(tt(uid, "tr_ask")); await c.answer()


@r.callback_query(F.data.in_({"pt:y", "pt:n"}))
async def cb_pt(c: CallbackQuery):
    uid = c.from_user.id; tid = PEND.pop(uid, None)
    if c.data == "pt:n" or not tid:
        t_, k = prof(uid)
        try: await c.message.edit_text(t_, reply_markup=k)
        except Exception: pass
        return await c.answer()
    tu = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
    if not tu or tu["games"] > 0: return await c.answer(tt(uid, "tr_new"), show_alert=True)
    if U(uid)["diamonds"] < 5: return await c.answer(tt(uid, "tr_5"), show_alert=True)
    A(uid, "diamonds", -5); u = U(uid)                   # -5 💎 komissiya bilan o'tadi
    S(tid, **{c_: u[c_] for c_ in COLS})
    S(uid, **{c_: ("" if isinstance(u[c_], str) else 0) for c_ in COLS})
    db.execute("UPDATE heroes SET uid=? WHERE uid=?", (tid, uid)); db.commit()
    txlog(uid, tid, "account", 0)
    await c.message.edit_text(tt(uid, "tr_done")); await pm(tid, tt(tid, "tr_got")); await c.answer()


# ───────────────────────── Para ─────────────────────────
@r.message(C("para"))
async def para(m: Message):
    if not m.reply_to_message: return await m.reply("Para qo'shish uchun odamga reply qiling.")
    a, tg = m.from_user, m.reply_to_message.from_user
    if a.id == tg.id or tg.is_bot: return
    U(a.id, a.full_name); U(tg.id, tg.full_name)
    if tg.id in pairs_of(a.id): return await m.reply("Siz allaqachon para bo'lgansiz.")
    if len(pairs_of(a.id)) >= plim(a.id) or len(pairs_of(tg.id)) >= plim(tg.id):
        return await m.reply("Sizda yoki unda para limiti to'lgan (VIP bilan oshadi).")
    b = InlineKeyboardBuilder(); b.button(text="💕 Qabul", callback_data=f"pa:{a.id}:{tg.id}:1"); b.button(text="💔 Rad", callback_data=f"pa:{a.id}:{tg.id}:0")
    await m.answer(f"💌 {esc(tg.full_name)}, {esc(a.full_name)} sizga para bo'lishni taklif qilmoqda!", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("pa:"))
async def para_ans(c: CallbackQuery):
    _, a, tg, y = c.data.split(":"); a, tg = int(a), int(tg)
    if c.from_user.id != tg: return await c.answer("Bu siz uchun emas", show_alert=True)
    if y == "1":
        if len(pairs_of(a)) >= plim(a) or len(pairs_of(tg)) >= plim(tg): return await c.message.edit_text("Para limiti to'lgan.")
        padd(a, tg); await c.message.edit_text("💞 Yangi para tuzildi!")
    else: await c.message.edit_text("💔 Rad etildi.")


@r.message(C("mypara"))
async def mypara(m: Message):
    uid = m.from_user.id; U(uid, m.from_user.full_name); ps = pairs_of(uid); lim = plim(uid)
    if not ps: return await m.answer("👫 <b>Paralarim</b>\n\nSizda para yo'q. /para orqali para qo'shing.")
    txt = f"👫 Sizning asosiy parangiz : <b>{esc(U(ps[0])['name'])}</b> {lim}/{len(ps)}"
    if len(ps) > 1: txt += "\n\nBoshqa paralar: " + ", ".join(esc(U(x)["name"]) for x in ps[1:])
    await m.answer(txt)


@r.message(C("dpara"))
async def dpara(m: Message):
    uid = m.from_user.id; ps = pairs_of(uid)
    if not ps: return await m.reply("Sizda para yo'q.")
    if m.reply_to_message and m.reply_to_message.from_user.id in ps:
        pdel(uid, m.reply_to_message.from_user.id); return await m.reply("💔 Para uzildi.")
    if len(ps) == 1: pdel(uid, ps[0]); return await m.reply("💔 Para uzildi.")
    b = InlineKeyboardBuilder()
    for x in ps: b.button(text=f"💔 {U(x)['name']}", callback_data=f"dp:{uid}:{x}")
    b.adjust(1); await m.reply("Qaysi parani uzmoqchisiz?", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("dp:"))
async def dpara_cb(c: CallbackQuery):
    _, a, x = c.data.split(":")
    if c.from_user.id != int(a): return await c.answer("Bu siz uchun emas", show_alert=True)
    pdel(int(a), int(x)); await c.message.edit_text("💔 Para uzildi."); await c.answer()


# ───────────────────────── O'tkazmalar / giveaway ─────────────────────────
def num(m: Message):
    p = (m.text or "").split()
    return int(p[-1]) if len(p) > 1 and p[-1].isascii() and p[-1].isdigit() else 0


async def transfer(m: Message, f, name):
    if not m.reply_to_message: return await m.reply("Odamga reply qiling.")
    n = num(m); s, tg = m.from_user, m.reply_to_message.from_user
    if n < 1 or s.id == tg.id or tg.is_bot: return await m.reply(f"Foydalanish: reply + /{'give' if f == 'diamonds' else 'money'} miqdor")
    u = U(s.id, s.full_name); U(tg.id, tg.full_name); vip = vlevel(u) > 0
    if f == "money":
        fee = 0 if vip else 100                       # VIP — komissiyasiz; VIP bo'lmasa har o'tkazmaga 100 💶
        if u["money"] < n + fee: return await m.reply(f"{name} yetarli emas (o'tkazma + komissiya {fee})." if fee else f"{name} yetarli emas.")
        A(s.id, f, -(n + fee)); A(tg.id, f, n); got = n
        txt = f"✅ {n} {name} o'tkazildi." + ("" if vip else f" Komissiya: {fee} 💶 (VIP'larda komissiya yo'q)")
    else:
        if u[f] < n: return await m.reply(f"{name} yetarli emas.")
        got = n if vip else int(n * 0.9)
        A(s.id, f, -n); A(tg.id, f, got)
        txt = f"✅ {n} {name} o'tkazildi. Qabul qildi: {got}" + ("" if vip else " (10% komissiya, VIP komissiyasiz)")
    txlog(s.id, tg.id, f, got); await m.reply(txt)


@r.message(C("give"))
async def cmd_give(m: Message): await transfer(m, "diamonds", "💎")


@r.message(C("money"))
async def cmd_money(m: Message): await transfer(m, "money", "💶")


GV = {}


async def make_gv(m: Message, kind, restricted=False):
    n = num(m) if kind != "himoya" else 1; uid = m.from_user.id; u = U(uid, m.from_user.full_name)
    f = "himoya" if kind == "himoya" else "diamonds"
    if m.chat.type == "private": return await m.reply("Faqat guruhda.")
    if n < 1 or u[f] < n: return await m.reply("Balans yetarli emas yoki miqdor noto'g'ri.")
    A(uid, f, -n)
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="gv")
    msg = await m.answer(f"🎁 {esc(m.from_user.full_name)} {n} {'🛡 himoya' if kind == 'himoya' else '💎 olmos'} giveaway qildi!"
                         + (" (faqat o'yin qatnashchilari)" if restricted else ""), reply_markup=b.as_markup())
    GV[(m.chat.id, msg.message_id)] = dict(kind=kind, n=n, f=f, owner=uid, r=restricted)


@r.message(C("send"), GROUP)
async def cmd_send(m: Message): await make_gv(m, "send")


@r.message(C("gsend"))
async def cmd_gsend(m: Message): await make_gv(m, "send", True)


@r.message(C("giveaway"))
async def cmd_gw(m: Message): await make_gv(m, "himoya")


@r.callback_query(F.data == "gv")
async def gv_claim(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = GV.get(k); uid = c.from_user.id
    if not d: return await c.answer("Tugagan", show_alert=True)
    U(uid, c.from_user.full_name)
    if d["r"]:
        g = games.get(c.message.chat.id)
        if not g or uid not in g.p: return await c.answer("Faqat o'yin qatnashchilari uchun!", show_alert=True)
    GV.pop(k); A(uid, d["f"], d["n"])
    await c.message.edit_text(f"🎉 {esc(c.from_user.full_name)} {d['n']} {'🛡' if d['f'] == 'himoya' else '💎'} oldi!"); await c.answer()


# ---- /change: ishtirokchilar ro'yxati (max 75), egasi To'xtatadi ----
CH = {}


def ch_names(d):
    lines = [f"{i}. <a href='tg://user?id={u}'>{esc(nm[:25])}</a>" for i, (u, nm) in enumerate(d["join"].items(), 1)]
    return "\n".join(lines)


def ch_text(d, winner=None):
    if winner:
        head = (f"🎉 {d['n']} ta 💎 sovg'a yakunlandi!\nG'olib: <a href='tg://user?id={winner}'>{esc(d['join'][winner][:25])}</a>.\n"
                f"👥 Ishtirokchilar: {len(d['join'])}")
    elif winner is False:
        head = f"🎉 {d['n']} ta 💎 sovg'a yakunlandi!\nHech kim qo'shilmadi, olmos egasiga qaytarildi.\n👥 Ishtirokchilar: 0"
    else:
        head = (f"<a href='tg://user?id={d['owner']}'>{esc(d['oname'][:25])}</a> kimgadir {d['n']} ta 💎 sovg'a qilmoqchi!\n"
                f"👥 Ishtirokchilar: {len(d['join'])}")
    names = ch_names(d)
    return head + (("\n\n" + names) if names else "")


def ch_kb():
    b = InlineKeyboardBuilder(); b.button(text="Qo'shilish", callback_data="chj"); b.button(text="To'xtatish", callback_data="chs")
    return b.as_markup()


@r.message(C("change"), GROUP)
async def cmd_change(m: Message):
    n = num(m); uid = m.from_user.id; u = U(uid, m.from_user.full_name)
    if n < 1 or u["diamonds"] < n: return await m.reply("Foydalanish: /change miqdor (olmosingiz yetarli bo'lishi kerak).")
    A(uid, "diamonds", -n)
    d = dict(n=n, owner=uid, oname=m.from_user.full_name, join={}, chat=m.chat.id)
    msg = await m.answer(ch_text(d), reply_markup=ch_kb()); d["mid"] = msg.message_id
    CH[(m.chat.id, msg.message_id)] = d
    try: await bot.pin_chat_message(m.chat.id, msg.message_id, disable_notification=False)
    except Exception: pass
    asyncio.create_task(ch_timer(m.chat.id, msg.message_id))


async def ch_timer(chat, mid):
    await asyncio.sleep(900)
    await ch_finish(chat, mid)


async def ch_finish(chat, mid):
    d = CH.pop((chat, mid), None)
    if not d: return
    if d["join"]:
        w = random.choice(list(d["join"])); A(w, "diamonds", d["n"]); txt = ch_text(d, w)
    else:
        A(d["owner"], "diamonds", d["n"]); txt = ch_text(d, False)
    try: await bot.edit_message_text(txt, chat_id=chat, message_id=mid, reply_markup=None)
    except Exception: pass
    try: await bot.unpin_chat_message(chat, mid)
    except Exception: pass


@r.callback_query(F.data == "chj")
async def ch_join(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = CH.get(k); uid = c.from_user.id
    if not d: return await c.answer("Tugagan", show_alert=True)
    if uid == d["owner"]: return await c.answer("Siz egasiz, qatnasha olmaysiz!", show_alert=True)
    if uid in d["join"]: return await c.answer("Siz allaqachon qo'shilgansiz!", show_alert=True)
    if len(d["join"]) >= CH_MAX: return await c.answer(f"Ishtirokchilar to'lgan (max {CH_MAX})!", show_alert=True)
    U(uid, c.from_user.full_name); d["join"][uid] = c.from_user.full_name
    await c.answer("✅ Siz qo'shildingiz!")
    try: await c.message.edit_text(ch_text(d), reply_markup=ch_kb())
    except Exception: pass


@r.callback_query(F.data == "chs")
async def ch_stop(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = CH.get(k)
    if not d: return await c.answer("Tugagan", show_alert=True)
    if c.from_user.id != d["owner"] and not is_admin(c.from_user.id): return await c.answer("Faqat egasi to'xtata oladi!", show_alert=True)
    await c.answer(); await ch_finish(*k)


# ---- Guruh obunasi ----
async def sub_view(uid, chat):
    try: title = (await bot.get_chat(chat)).title or str(chat)
    except Exception: title = str(chat)
    g = Gr(chat)
    until = dfmt(g["sub_until"]) if g["sub_until"] > time.time() else tt(uid, "sub_none")
    txt = tt(uid, "sub_txt", title=esc(title), until=until, bal=U(uid)["diamonds"])
    b = InlineKeyboardBuilder()
    b.button(text=f"📅 {tt(uid, 'sub_m')} — {SUB_M} 💎", callback_data=f"sb:{chat}:m")
    b.button(text=f"🗓 {tt(uid, 'sub_y')} — {SUB_Y} 💎", callback_data=f"sb:{chat}:y")
    url = await group_url(chat)
    if url: b.button(text="⬅️ " + tt(uid, "back_group"), url=url)          # "Orqaga" o'rniga: guruhga qaytish
    else: b.button(text=tt(uid, "back"), callback_data="m:start")
    b.adjust(1)
    return txt, b.as_markup()


async def sub_page(m: Message, chat):
    txt, kb = await sub_view(m.from_user.id, chat); await m.answer(txt, reply_markup=kb)


@r.callback_query(F.data.startswith("sb:"))
async def sub_buy(c: CallbackQuery):
    _, ch, k = c.data.split(":"); chat = int(ch); uid = c.from_user.id; u = U(uid)
    price, days = (SUB_M, 30) if k == "m" else (SUB_Y, 365)
    if u["diamonds"] < price: return await c.answer(tt(uid, "sub_nodia"), show_alert=True)
    A(uid, "diamonds", -price); new = sub_add(chat, days)
    await c.answer(tt(uid, "sub_ok_m" if k == "m" else "sub_ok_y"), show_alert=True)
    txt, kb = await sub_view(uid, chat)
    try: await c.message.edit_text(txt, reply_markup=kb)
    except Exception: pass
    await say(chat, f"✅ {esc(c.from_user.full_name)} guruh obunasini faollashtirdi ({'1 oy' if k == 'm' else '1 yil'}).\n📅 Obuna tugashi: {dfmt(new)}")


async def need_sub(m: Message):
    if sub_active(m.chat.id): return False
    b = InlineKeyboardBuilder(); b.button(text="📅 Guruh obunasi", url=sub_link(m.chat.id))
    await m.reply(f"⛔️ Bu guruhda obuna faol emas. Botdan foydalanish uchun guruh obunasini faollashtiring (1 oy — {SUB_M} 💎, 1 yil — {SUB_Y} 💎).",
                  reply_markup=b.as_markup())
    return True


@r.message(C("psend"))
async def psend(m: Message):
    uid = m.from_user.id; U(uid, m.from_user.full_name)
    if m.chat.type == "private": return await m.reply("Bu buyruq guruhda ishlaydi: /psend")
    n = num(m)
    if n == 0:
        b = InlineKeyboardBuilder(); b.button(text="📅 Guruh obunasi", url=sub_link(m.chat.id))
        return await m.reply("Obunani shaxsiy chatda boshqaring.", reply_markup=b.as_markup())
    if n not in (SUB_M, SUB_Y): return await m.reply(f"Noto'g'ri miqdor. 1 oy — /psend {SUB_M}, 1 yil — /psend {SUB_Y}")
    if U(uid)["diamonds"] < n: return await m.reply("Olmos yetarli emas. Shaxsiy balansingizni to‘ldiring.")
    A(uid, "diamonds", -n); days = 30 if n == SUB_M else 365; new = sub_add(m.chat.id, days)
    await m.reply(f"✅ Sotib olindi! Bot aktiv holatda ({'1-oy' if days == 30 else '1 yil (365 kun)'}).\n📅 Obuna tugashi: {dfmt(new)}\n💎 Sizning balansingiz: {U(uid)['diamonds']}")


@r.message(C("ginfo"))
async def ginfo(m: Message):
    g = Gr(m.chat.id)
    await m.reply(f"🏦 Guruh obunasi: {('✅ faol, tugashi ' + dfmt(g['sub_until'])) if g['sub_until'] > time.time() else '❌ faol emas'}")


@r.message(C("boost"), GROUP)
async def cmd_boost(m: Message):
    u = U(m.from_user.id, m.from_user.full_name); lv = vlevel(u)
    if lv < 1: return await m.reply("🚀 /boost faqat VIP foydalanuvchilar uchun.")
    if u["boosts"] < 1: return await m.reply("Boost qolmagan. VIP ni qayta sotib oling — har sotib olishda yangi boost beriladi.")
    A(m.from_user.id, "boosts", -1); days = 60 if lv == 4 else 30; new = sub_add(m.chat.id, days)
    await m.reply(f"🚀 Guruhga {'2 oylik' if lv == 4 else '1 oylik'} bepul obuna berildi!\n📅 Obuna tugashi: {dfmt(new)}")


async def say(chat, text, **kw):
    try: return await bot.send_message(chat, text, **kw)
    except Exception: return None


async def sub_watch():
    while True:
        try:
            for x in db.execute("SELECT id FROM groups WHERE sub_until>0 AND sub_until<=? AND notified=0", (int(time.time()),)).fetchall():
                db.execute("UPDATE groups SET notified=1 WHERE id=?", (x["id"],)); db.commit()
                b = InlineKeyboardBuilder(); b.button(text="🔄 Qayta sotib olish", url=sub_link(x["id"]))
                await say(x["id"], "⌛️ Sizning 1 oylik yoki 1 yillik obunangiz tugadi.\nQayta sotib olish uchun pastdagi tugmani bosing.", reply_markup=b.as_markup())
        except Exception:
            logging.exception("sub_watch")
        await asyncio.sleep(60)


# ───────────────────────── NEWS KANAL: /send (olmos) va /sendmoney (pul) ─────────────────────────
def is_news(m: Message):
    return (m.chat.username or "").lower() == NEWS_USER.lower()


NG = {}


def ng_text(d, final=False):
    sym = "💎" if d["f"] == "diamonds" else "💶"
    head = f"🎁 <b>Obunachilarimizga {n_(d['n'])} {sym} sovg'a ajratildi!</b>"
    if not d["got"]: return head + "\n\nOlish uchun pastdagi tugmani bosing!"
    lines = "\n".join(f"{i}) {esc(nm)} {d['per']}{sym}" for i, nm in enumerate(d["got"][-60:], max(1, len(d["got"]) - 59)))
    return head + f"\n\n<b>Olganlar:</b>\n{lines}" + ("" if final else f"\n\nQolgan: {n_(d['left'])} {sym}")


async def news_gift(m: Message, f):
    p = (m.text or "").split()
    n = int(p[1]) if len(p) > 1 and p[1].isascii() and p[1].isdigit() else 0
    per = 1 if f == "diamonds" else 100
    if len(p) > 2 and p[2].isascii() and p[2].isdigit() and int(p[2]) > 0: per = int(p[2])
    if n < 1 or per > n: return
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="ng")
    d = dict(n=n, left=n, per=per, f=f, got=[], users=set())
    msg = await m.answer(ng_text(d), reply_markup=b.as_markup())
    NG[(msg.chat.id, msg.message_id)] = d
    try: await m.delete()
    except Exception: pass


@r.channel_post(Command("send"), is_news)
async def news_send(m: Message): await news_gift(m, "diamonds")


@r.channel_post(Command("sendmoney", "moneysend"), is_news)
async def news_sendmoney(m: Message): await news_gift(m, "money")          # /sendmoney 1000 [har biriga, default 100]


@r.callback_query(F.data == "ng")
async def news_claim(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = NG.get(k); uid = c.from_user.id
    if not d: return await c.answer("Giveaway tugagan!", show_alert=True)
    if uid in d["users"]: return await c.answer("Siz allaqachon olgansiz!", show_alert=True)
    U(uid, c.from_user.full_name)
    d["users"].add(uid); d["left"] -= d["per"]; d["got"].append(c.from_user.full_name); A(uid, d["f"], d["per"])
    await c.answer(f"🎉 Sizga {d['per']} {'💎' if d['f'] == 'diamonds' else '💶'} berildi!")
    fin = d["left"] < d["per"]
    if fin: NG.pop(k, None)
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="ng")
    try: await c.message.edit_text(ng_text(d, fin), reply_markup=None if fin else b.as_markup())
    except Exception: pass


# ---- Top: guruhda /top1 /top7 /top30 (shu guruh o'yinchilari), news kanalda /top (umr bo'yi) va /top1 /top7 /top30 ----
TOPS = {1: "📆 Kunlik eng yaxshi o'yinchilar", 7: "📆 Haftalik eng yaxshi o'yinchilar",
        30: "📆 Oylik eng yaxshi o'yinchilar", 0: "🏆 Barcha vaqtdagi eng yaxshi o'yinchilar"}


def cmd_key(cmd):
    cmd = cmd.lower()
    return cmd[:-len(SUF)] if cmd.endswith(SUF) else cmd


async def send_top(m: Message, days, chat=0):
    since = int(time.time() - days * 86400) if days else 0
    q = "SELECT u.name nm, SUM(l.ball) s FROM pts_log l JOIN users u ON u.id=l.uid WHERE l.ts>=?"
    prm = [since]
    if chat: q += " AND l.chat=?"; prm.append(chat)
    q += " GROUP BY l.uid HAVING s>0 ORDER BY s DESC LIMIT 30"
    rows = db.execute(q, prm).fetchall()
    body = "\n".join(f"{i}. {esc(x['nm'])} – {x['s']} ball" for i, x in enumerate(rows, 1)) or "Hozircha ma'lumot yo'q."
    await m.answer(f"<b>{TOPS[days]}</b>\n\n{body}")


@r.message(C("top", "top1", "top7", "top30"), GROUP)
async def grp_top(m: Message, command: CommandObject):
    days = {"top1": 1, "top7": 7, "top30": 30, "top": 30}.get(cmd_key(command.command), 30)
    await send_top(m, days, m.chat.id)


@r.channel_post(C("top", "top1", "top7", "top30", "topall"), is_news)
async def news_top(m: Message, command: CommandObject):
    days = {"top1": 1, "top7": 7, "top30": 30, "top": 0, "topall": 0}.get(cmd_key(command.command), 0)
    await send_top(m, days, 0)


# ───────────────────────── O'YIN ─────────────────────────
games = {}
MODES = {"classic": ("Classik", 20), "night": ("Night", 30), "zombie": ("Zombie", 30), "mega": ("Mega Night", 30), "vs": ("VS mode", 30)}
MC = {}
# rejimlarda chiqmaydigan rollar
EXCL = {"classic": {"suidsid", "aferist", "zombi", "ubiytsa", "muxlis"},
        "night": {"janob", "zombi", "ubiytsa", "aferist", "kimyogar", "muxlis", "mergan"},
        "mega": {"zombi"}}
CORE = {"tinch", "don", "mafia", "komissar", "doktor", "manyak", "qoy", "zombi", "jangchi"}
SAFE = ["omadli", "janob", "daydi", "serjant", "mashuqa"]
ZPOOL = ["serjant", "omadli", "janob", "mergan", "daydi", "jurnalist", "qoriqchi", "hamshira", "ovchi", "kamikaze"]
SELL = {"himoya": ("🛡", 150), "hujjat": ("📁", 100), "osish": ("⚖️", 700), "geroyd": ("🔰", 1500)}


def newp(name, team=None):
    return dict(n=name, r=None, a=True, idle=0, act=False, r0=None, hp=100, shield=False, t=team, osh=False)


class G:
    def __init__(s, chat, owner, vs=False):
        s.chat, s.owner, s.p, s.state, s.round = chat, owner, {}, "reg", 0
        s.night, s.hero, s.votes, s.start_ev, s.task, s.regmsg = {}, {}, {}, asyncio.Event(), None, None
        s.vs = vs
        s.mode = "vs" if vs else Gr(chat)["mode"]
        s.url, s.t0, s.suid = None, time.time(), None
        s.t_create = time.time(); s.reg_end = time.time() + REG_SEC
        s.need, s.night_ev, s.idx = set(), asyncio.Event(), {}
        s.yn, s.cand = {}, None
        s.immune, s.seller, s.offers, s.fans, s.wit = set(), {}, {}, {}, []

    def alive(s): return [u for u, d in s.p.items() if d["a"]]

    def plist(s):
        tag = {"r": "🔴 ", "b": "🔵 "}
        return "\n".join(f"{i}. {tag.get(s.p[u]['t'], '') if s.vs else ''}{vemoji(u)}<a href='tg://user?id={u}'>{esc(s.p[u]['n'])}</a>"
                         for i, u in enumerate(s.alive(), 1))


async def pm(uid, text, **kw):
    try: return await bot.send_message(uid, text, **kw)
    except Exception: return None


async def gm(g, text, **kw):
    try: return await bot.send_message(g.chat, text, **kw)
    except Exception: return None


async def pm_g(g, uid, text):
    kb = None
    if g.url:
        b = InlineKeyboardBuilder(); b.button(text="Guruhga o'tish", url=g.url); kb = b.as_markup()
    return await pm(uid, text, reply_markup=kb)


def link_kb(label="Botga o'tish"):
    b = InlineKeyboardBuilder(); b.button(text=label, url=f"https://t.me/{BOTNAME}"); return b.as_markup()


async def group_url(chat_id):
    try:
        c = await bot.get_chat(chat_id)
        if c.username: return f"https://t.me/{c.username}"
        if c.invite_link: return c.invite_link
        try: return await bot.export_chat_invite_link(chat_id)
        except Exception: pass
    except Exception: pass
    return f"https://t.me/c/{str(chat_id)[4:]}" if str(chat_id).startswith("-100") else None


async def gmedia(g, key, caption, kb=None):
    """media/night.mp4|gif|jpg|png va media/day.* fayllari yoki NIGHT_MEDIA / DAY_MEDIA (URL). Topilmasa — matn."""
    try:
        if key in MC: kind, src = MC[key]
        else:
            src, kind = None, None
            for ext, kd in (("mp4", "a"), ("gif", "a"), ("jpg", "p"), ("jpeg", "p"), ("png", "p")):
                pth = f"media/{key}.{ext}"
                if os.path.exists(pth): src, kind = FSInputFile(pth), kd; break
            if not src:
                url = os.getenv(f"{key.upper()}_MEDIA", "")
                if url: src, kind = url, ("a" if url.lower().endswith(("mp4", "gif")) else "p")
            if not src: return await gm(g, caption, reply_markup=kb)
        if kind == "a": msg = await bot.send_animation(g.chat, src, caption=caption, reply_markup=kb)
        else: msg = await bot.send_photo(g.chat, src, caption=caption, reply_markup=kb)
        MC[key] = (kind, msg.animation.file_id if kind == "a" and msg.animation else (msg.photo[-1].file_id if msg.photo else src))
        return msg
    except Exception:
        logging.exception("media xato")
        return await gm(g, caption, reply_markup=kb)


async def is_gadmin(m: Message): return await chat_admin(m.chat.id, m.from_user.id)


async def post_reg(g):
    """Ro'yxatdan o'tish xabarini yuboradi va pin qiladi (/game qayta bosilganda eng pastga tushadi)."""
    old = g.regmsg
    g.regmsg = await gm(g, reg_text(g)); await upd_reg(g)
    if g.regmsg:
        try: await bot.pin_chat_message(g.chat, g.regmsg.message_id, disable_notification=False)
        except Exception: pass
    if old:
        try: await bot.unpin_chat_message(g.chat, old.message_id)
        except Exception: pass
        try: await old.delete()
        except Exception: pass


@r.message(C("game"), GROUP)
async def cmd_game(m: Message):
    g = games.get(m.chat.id)
    if g:
        if g.state == "reg" and not g.vs: return await post_reg(g)          # qayta bossa — eng pastga tushadi
        return await m.reply("O'yin allaqachon boshlangan.")
    if await need_sub(m): return
    g = G(m.chat.id, m.from_user.id); games[m.chat.id] = g
    g.task = asyncio.create_task(run_game(g))


@r.message(C("vsgame"), GROUP)
async def cmd_vsgame(m: Message):
    g = games.get(m.chat.id)
    if g:
        if g.state == "reg" and g.vs: return await post_reg(g)
        return await m.reply("O'yin allaqachon boshlangan.")
    if await need_sub(m): return
    g = G(m.chat.id, m.from_user.id, vs=True); games[m.chat.id] = g
    g.task = asyncio.create_task(run_game(g))


def enough(g):
    if g.vs:
        rc = sum(1 for d in g.p.values() if d["t"] == "r"); bc = len(g.p) - rc
        return rc >= MINVS and bc >= MINVS
    return len(g.p) >= MINP


@r.message(C("start"), GROUP)
async def cmd_gstart(m: Message):
    g = games.get(m.chat.id)
    if not g or g.state != "reg": return await m.reply("Avval /game orqali o'yin yarating.")
    if not enough(g):
        return await m.reply(f"Har bir jamoada kamida {MINVS} ta o'yinchi kerak." if g.vs else f"Kamida {MINP} ta o'yinchi kerak.")
    g.start_ev.set()


@r.message(Command("extend"), GROUP)
async def cmd_extend(m: Message, command: CommandObject):
    g = games.get(m.chat.id)
    if not g or g.state != "reg": return await m.reply("Hozir ro'yxatdan o'tish davom etmayapti.")
    uid = m.from_user.id
    if not (uid in g.p or uid == g.owner or await is_gadmin(m)): return
    arg = (command.args or "").split()
    if not arg or not (arg[0].isascii() and arg[0].isdigit()): return await m.reply("Foydalanish: /extend 5  (daqiqa)")
    n = int(arg[0])
    if n < 1: return await m.reply("Foydalanish: /extend 5  (daqiqa)")
    if n > EXT_MAX: return await m.reply(f"⚠️ Ro'yxatdan o'tish vaqtini ko'pi bilan {EXT_MAX} daqiqaga uzaytirish mumkin.")
    g.reg_end = max(g.reg_end, time.time()) + n * 60
    await m.reply(f"⏳ Ro'yxatdan o'tish vaqti {n} daqiqaga uzaytirildi!")


@r.message(C("stop"), GROUP)
async def cmd_stop(m: Message):
    g = games.get(m.chat.id)
    if not g or not await is_gadmin(m): return
    if g.task: g.task.cancel()
    await m.answer("🛑 O'yin to'xtatildi. Qaytadan boshlash uchun /game")


@r.message(C("leave"), GROUP)
async def cmd_leave(m: Message):
    g = games.get(m.chat.id)
    if g and g.state == "reg" and m.from_user.id in g.p: g.p.pop(m.from_user.id); await upd_reg(g); await m.reply("Siz o'yindan chiqdingiz.")


# ---- Sozlamalar: shaxsiy chatga yuboriladi ----
async def set_view(uid, chat, page):
    try: title = (await bot.get_chat(chat)).title or str(chat)
    except Exception: title = str(chat)
    g = Gr(chat); off = goff(chat); b = InlineKeyboardBuilder()
    if page == "m":
        for k, (n, mx) in MODES.items():
            if k != "vs": b.button(text=("✅ " if g["mode"] == k else "") + f"{n} ({mx})", callback_data=f"cm:{chat}:{k}")
        b.button(text=tt(uid, "back"), callback_data=f"cs:{chat}:b"); b.adjust(2, 2, 1)
        return tt(uid, "set_modes_title"), b.as_markup()
    if page == "g":
        for code, label in PL: b.button(text=("✅ " if g["glang"] == code else "") + label, callback_data=f"cg:{chat}:{code}")
        b.adjust(2); b.row(InlineKeyboardButton(text=tt(uid, "back"), callback_data=f"cs:{chat}:b"))
        return tt(uid, "set_lang_title"), b.as_markup()
    if page == "r":
        ks = [k for k, _, _, _ in RL if k != "qoy"]
        for k in ks: b.button(text=("❌ " if k in off else "✅ ") + rname(k, uid), callback_data=f"cr:{chat}:{k}")
        b.button(text=tt(uid, "set_on_all"), callback_data=f"ca:{chat}:1")
        b.button(text=tt(uid, "set_off_all"), callback_data=f"ca:{chat}:0")
        b.button(text=tt(uid, "back"), callback_data=f"cs:{chat}:b")
        b.adjust(*([2] * (len(ks) // 2) + ([1] if len(ks) % 2 else []) + [1]))
        return tt(uid, "set_roles_title"), b.as_markup()
    b.button(text=f"{tt(uid, 'set_mode')}: {MODES[g['mode']][0]}", callback_data=f"cs:{chat}:m")
    b.button(text=tt(uid, "set_roles"), callback_data=f"cs:{chat}:r")
    b.button(text=tt(uid, "set_sub"), url=sub_link(chat))
    b.button(text=f"{tt(uid, 'set_lang')}: {PLD.get(g['glang'], g['glang'])}", callback_data=f"cs:{chat}:g")
    b.button(text=f"⭐️ {tt(uid, 'btn_prem')}: {onoff(g['listed'])}", callback_data=f"cp:{chat}:x")
    url = await group_url(chat)
    if url: b.button(text="⬅️ " + tt(uid, "back_group"), url=url)            # sozlab bo'lgach guruhga qaytish
    b.adjust(1)
    return tt(uid, "set_title", title=esc(title), mode=MODES[g["mode"]][0]), b.as_markup()


@r.message(C("sozlamalar"), GROUP)
async def cmd_settings(m: Message):
    if not await is_gadmin(m): return
    uid = m.from_user.id; txt, kb = await set_view(uid, m.chat.id, "b")
    b = InlineKeyboardBuilder(); b.button(text="Botga o'tish", url=f"https://t.me/{BOTNAME}")
    if await pm(uid, txt, reply_markup=kb): await m.reply("⚙️ Sozlamalar shaxsiy chatga yuborildi.", reply_markup=b.as_markup())
    else: await m.reply("⚠️ Sozlamalarni yuborib bo'lmadi. Avval botga o'tib /start bosing.", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith(("cs:", "cm:", "cr:", "ca:", "cg:", "cp:")))
async def cb_cfg(c: CallbackQuery):
    p, ch, a = c.data.split(":"); chat = int(ch); uid = c.from_user.id
    if not await chat_admin(chat, uid): return await c.answer("Faqat adminlar", show_alert=True)
    page = "b"
    if p == "cs": page = a
    elif p == "cm": gset(chat, mode=a); page = "m"
    elif p == "cr":
        off = goff(chat); off.symmetric_difference_update({a}); gset(chat, off=",".join(sorted(off))); page = "r"
    elif p == "ca":
        gset(chat, off="" if a == "1" else ",".join(k for k, _, _, _ in RL if k != "qoy")); page = "r"
    elif p == "cg": gset(chat, glang=a if a in PLD else "uz"); page = "g"
    elif p == "cp":
        g = Gr(chat); nl = 0 if g["listed"] else 1
        if nl:
            try: tl = (await bot.get_chat(chat)).title or ""
            except Exception: tl = ""
            gset(chat, listed=1, title=tl, invite=(await group_url(chat)) or "")
        else: gset(chat, listed=0)
        page = "b"
    txt, kb = await set_view(uid, chat, page)
    try: await c.message.edit_text(txt, reply_markup=kb)
    except Exception: pass
    await c.answer()


@r.message(C("tep"), GROUP)
async def cmd_tep(m: Message):
    g = games.get(m.chat.id)
    if not g or g.state == "reg" or not await is_gadmin(m): return
    n = num(m); al = g.alive()
    if 1 <= n <= len(al):
        u = al[n - 1]; g.p[u]["a"] = False
        await m.answer(f"{esc(g.p[u]['n'])} o'yin admin tomonidan chiqarildi. U edi {rname(g.p[u]['r'])}")


def reg_text(g):
    if g.vs:
        def tm(t_):
            ns = [esc(d["n"]) for d in g.p.values() if d["t"] == t_]
            return ", ".join(ns) or "—", len(ns)
        (rn, rc), (bn, bc) = tm("r"), tm("b")
        return (f"<b>⚔️ VS mode — ro'yxatdan o'tish davom etmoqda!</b>\n\n🔴 Qizil jamoa ({rc}): {rn}\n\n"
                f"🔵 Ko'k jamoa ({bc}): {bn}\n\nJami: {len(g.p)} ta\nJamoani tanlash uchun pastdagi tugmalarni bosing.")
    names = ", ".join(esc(d["n"]) for d in g.p.values()) or "—"
    return f"<b>Ro'yxatdan o'tish davom etmoqda!</b>\nRejim: {MODES[g.mode][0]}\nRo'yxatdan o'tganlar: {names}\n\nJami: {len(g.p)} ta"


async def upd_reg(g):
    if not g.regmsg: return
    b = InlineKeyboardBuilder()
    if g.vs:
        rc = sum(1 for d in g.p.values() if d["t"] == "r"); bc = len(g.p) - rc
        b.button(text=f"🔴 Qizil ({rc})", url=f"https://t.me/{BOTNAME}?start=vs{g.chat}_r")      # botga o'tadi
        b.button(text=f"🔵 Ko'k ({bc})", url=f"https://t.me/{BOTNAME}?start=vs{g.chat}_b")
    else:
        b.button(text="💡 Qo'shilish", url=f"https://t.me/{BOTNAME}?start=j{g.chat}")
    try: await g.regmsg.edit_text(reg_text(g), reply_markup=b.as_markup())
    except Exception: pass


def to_group_kb(g):
    if not g.url: return None
    b = InlineKeyboardBuilder(); b.button(text="Guruhga qaytish", url=g.url); return b.as_markup()


async def vs_join_pm(m: Message, chat, tm):
    g = games.get(chat); uid = m.from_user.id
    if not g or not g.vs or g.state != "reg" or tm not in ("r", "b"):
        return await m.answer("Kechirasiz, bu o'yinga qo'shilib bo'lmaydi!")
    kb = to_group_kb(g)
    if uid in g.p:
        if g.p[uid]["t"] == tm: return await m.answer("Siz o'yinga qo'shilib bo'ldingiz.", reply_markup=kb)
        g.p[uid]["t"] = tm
        await m.answer(f"🔄 Jamoa almashtirdingiz! ({TEAM[tm]})", reply_markup=kb); return await upd_reg(g)
    if len(g.p) >= MODES["vs"][1]: return await m.answer("O'yin to'lgan!")
    g.p[uid] = newp(m.from_user.full_name, tm)
    await m.answer(f"✅ Siz o'yinga qo'shildingiz! ({TEAM[tm]} jamoa)", reply_markup=kb)
    await upd_reg(g)


async def join_game(m: Message, chat):
    g = games.get(chat); uid = m.from_user.id
    if not g or g.state != "reg" or g.vs or len(g.p) >= MODES[g.mode][1]:
        return await m.answer("Kechirasiz, bu o'yinga qo'shilib bo'lmaydi!")
    if uid in g.p: return await m.answer("Siz o'yinga qo'shilib bo'ldingiz.", reply_markup=to_group_kb(g))
    g.p[uid] = newp(m.from_user.full_name)
    await m.answer("✅ Siz o'yinga qo'shildingiz!", reply_markup=to_group_kb(g))
    await upd_reg(g)


def assign(g):
    ids = list(g.p); random.shuffle(ids); n = len(ids); mode = g.mode; off = goff(g.chat)
    ok = lambda k: k not in off
    safe = [k for k in SAFE if ok(k)]

    def filler(): return "tinch" if ok("tinch") else (random.choice(safe) if safe else "tinch")

    roles = []
    if mode == "zombie":
        roles = ["zombi"]
        if n >= 5 and ok("komissar"): roles.append("komissar")
        if n >= 6 and ok("doktor"): roles.append("doktor")
        pool = [k for k in ZPOOL if ok(k)]; random.shuffle(pool)
        while len(roles) < n: roles.append(pool.pop() if pool and random.random() < .5 else filler())
    else:
        nm = max(1, n // 4)
        roles += [k for k in (["don"] + ["mafia"] * (nm - 1)) if ok(k)]
        if n >= 5 and ok("komissar"): roles.append("komissar")
        if n >= 6 and ok("doktor"): roles.append("doktor")
        if n >= 7 and ok("manyak"): roles.append("manyak")
        ex = EXCL.get(mode, set())
        pool = [k for k, _, _, _ in RL if k not in CORE and k not in ex and ok(k)]; random.shuffle(pool)
        while len(roles) < n:
            if pool and (mode == "mega" or random.random() < .5): roles.append(pool.pop())
            elif mode == "mega": roles.append(random.choice(safe) if safe else "tinch")
            else: roles.append(filler())
    roles = roles[:n]; random.shuffle(roles)
    for u, rl in zip(ids, roles): g.p[u]["r"] = rl
    if mode != "zombie":                       # faol rollar 100% tushadi va ro'yxatdan o'chadi
        for u in ids:
            lst = aroles(U(u)); pick = next((x for x in lst if x in RD and x not in off and x != "zombi"), None)
            if pick: g.p[u]["r"] = pick; lst.remove(pick); S(u, arole=",".join(lst))
    for d in g.p.values(): d["r0"] = d["r"]


def assign_vs(g):
    for tm in "rb":
        ids = [u for u, d in g.p.items() if d["t"] == tm]; random.shuffle(ids)
        for i, u in enumerate(ids): g.p[u]["r"] = "doktor" if i == 0 and len(ids) >= 3 else "jangchi"
    for d in g.p.values(): d["r0"] = d["r"]


async def send_roles(g):
    bad = []
    for u, d in g.p.items():
        rl = d["r"]; txt = f"{tt(u, 'you_are', role=rname(rl, u))}\n\n{rdesc(rl, u)}"
        mates = []
        if g.vs:
            txt = f"{TEAM[d['t']]}\n\n" + txt
            mates = [(x, y) for x, y in g.p.items() if y["t"] == d["t"] and x != u]
        elif rl in MAF:
            mates = [(x, y) for x, y in g.p.items() if y["r"] in MAF and x != u]
        elif rl in ("komissar", "serjant"):
            mates = [(x, y) for x, y in g.p.items() if y["r"] in ("komissar", "serjant") and x != u]
        if mates:
            txt += f"\n\n<b>{tt(u, 'mates')}</b>\n" + "\n".join(f"{esc(y['n'])} - {rname(y['r'], u)}" for x, y in mates)
        if not await pm(u, txt): bad.append(esc(d["n"]))
    if bad: await gm(g, "⚠️ Quyidagi o'yinchilarga xabar yuborib bo'lmadi (botga /start bosing): " + ", ".join(bad))


async def wait_reg(g):
    """Ro'yxatdan o'tishni kutadi. /start yoki vaqt tugaganda (yetarli o'yinchi bo'lsa) -> 'start'; 2 soat o'ynalmasa -> 'idle'."""
    while True:
        try: await asyncio.wait_for(g.start_ev.wait(), 20)
        except asyncio.TimeoutError: pass
        if g.start_ev.is_set(): return "start"
        if time.time() >= g.reg_end and enough(g): return "start"
        if time.time() - g.t_create >= IDLE_STOP: return "idle"


async def run_game(g):
    try:
        g.url = await group_url(g.chat)
        await post_reg(g)
        if await wait_reg(g) == "idle":
            await gm(g, "⌛️ O'yin 2 soat davomida o'ynalmadi va to'xtatildi.")
            return
        if not enough(g):
            await gm(g, "O'yin bekor qilindi: o'yinchilar yetarli emas.")
            return
        g.state = "start"
        if g.regmsg:
            try: await g.regmsg.edit_reply_markup(reply_markup=None)
            except Exception: pass
        assign_vs(g) if g.vs else assign(g)
        if not g.vs and not any(d["r"] in MAF or d["r"] in ("manyak", "zombi") for d in g.p.values()):
            await gm(g, "⚠️ Mafia / yakka rollari sozlamalarda o'chirilgan — o'yin bekor qilindi. /sozlamalar orqali rollarni yoqing.")
            return
        g.t0 = time.time()
        await gm(g, f"🎮 <b>O'yin boshlandi!</b>\nMode: <b>{MODES[g.mode][0]}</b>")
        await send_roles(g)
        await asyncio.sleep(3)
        w = None
        while True:
            g.round += 1
            await night(g)
            rep = await (resolve_vs(g) if g.vs else resolve(g))
            await day_intro(g)
            await gm(g, rep)
            if (w := win(g)): break
            if g.vs: await idle_check(g)
            else:
                await seller_offers(g)
                await day(g)
                if (w := win(g)): break
                await idle_check(g)
                if (w := win(g)): break
            if g.vs and (w := win(g)): break
        await finish(g, w)
    except asyncio.CancelledError:
        pass
    except Exception:
        logging.exception("O'yin xatosi")
        await gm(g, "⚠️ O'yinda xatolik yuz berdi, o'yin to'xtatildi.")
    finally:
        games.pop(g.chat, None)
        if g.regmsg:
            try: await bot.unpin_chat_message(g.chat, g.regmsg.message_id)
            except Exception: pass


# ───────────────────────── Tun ─────────────────────────
def kb_targets(g, kinds, tgts):
    b = InlineKeyboardBuilder()
    for k, em in kinds:
        for t_ in tgts: b.button(text=f"{em} {g.idx[t_]}. {g.p[t_]['n']}", callback_data=f"na:{g.chat}:{t_}:{k}")
    b.adjust(1); return b.as_markup()


def targets(g, u, rl):
    al = g.alive(); d = g.p[u]
    if g.vs:
        return [x for x in al if g.p[x]["t"] == d["t"]] if rl == "doktor" else [x for x in al if g.p[x]["t"] != d["t"]]
    if rl == "doktor": return al
    if rl in ("don", "mafia"): return [x for x in al if g.p[x]["r"] not in ("don", "mafia")]
    if rl == "zombi": return [x for x in al if g.p[x]["r"] != "zombi"]
    return [x for x in al if x != u]


def hero_targets(g, u):
    al = g.alive()
    if g.vs: return [x for x in al if g.p[x]["t"] != g.p[u]["t"]]
    return [x for x in al if x != u]


def hero_menu(g, u):
    b = InlineKeyboardBuilder()
    if U(u)["charge"] > 0: b.button(text=tt(u, "hm_attack"), callback_data=f"hm:{g.chat}:a")
    b.button(text=tt(u, "hm_shield"), callback_data=f"hm:{g.chat}:s")
    b.button(text=tt(u, "hm_skip"), callback_data=f"hm:{g.chat}:n")
    b.adjust(1); return b.as_markup()


def done(g, uid, key):
    g.need.discard((uid, key))
    if not g.need: g.night_ev.set()


async def night(g):
    g.state = "night"; g.night = {}; g.hero = {}; g.need = set(); g.night_ev = asyncio.Event(); g.offers = {}; g.seller = {}
    for d in g.p.values(): d["act"] = False; d["shield"] = False
    al = g.alive(); g.idx = {u: i for i, u in enumerate(al, 1)}
    await gmedia(g, "night", "🌃 <b>Tun</b>\nKo'chaga faqat jasur va qo'rqmas odamlar chiqishdi. Ertalab tirik qolganlarni sanaymiz...", link_kb())
    if not g.vs:
        fl = "\n".join(FLAV[g.p[u]["r"]] for u in al if g.p[u]["r"] in FLAV)
        if fl: await gm(g, fl)
    await gm(g, f"<b>Tirik o'yinchilar:</b>\n{g.plist()}\n\nTonggacha ⏳ {NIGHT_SEC} sekund qoldi", reply_markup=link_kb())
    for u in al:
        rl = g.p[u]["r"]; acts = (ACT_VS if g.vs else ACT).get(rl)
        if acts:
            tg = targets(g, u, rl)
            if tg and await pm(u, tt(u, "night_pick"), reply_markup=kb_targets(g, acts, tg)): g.need.add((u, "r"))
        if U(u)["has_hero"]:
            if await pm(u, tt(u, "hm_prompt"), reply_markup=hero_menu(g, u)): g.need.add((u, "h"))
    if not g.need: g.night_ev.set()
    try: await asyncio.wait_for(g.night_ev.wait(), NIGHT_SEC)
    except asyncio.TimeoutError: pass
    g.state = "resolving"


@r.callback_query(F.data.startswith("na:"))
async def cb_night(c: CallbackQuery):
    _, ch, tg, k = c.data.split(":"); g = games.get(int(ch)); uid, tg = c.from_user.id, int(tg)
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"] or tg not in g.p: return await c.answer("Kech qoldingiz!", show_alert=True)
    g.night[uid] = (k, tg); g.p[uid]["act"] = True
    await c.message.edit_text(f"✅ {esc(g.p[tg]['n'])}"); await c.answer()
    done(g, uid, "r")


@r.callback_query(F.data.startswith("hm:"))
async def cb_hero_menu(c: CallbackQuery):
    _, ch, a = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"]: return await c.answer("Kech qoldingiz!", show_alert=True)
    if a == "back":
        await c.message.edit_text(tt(uid, "hm_prompt"), reply_markup=hero_menu(g, uid)); return await c.answer()
    if a == "a":
        if U(uid)["charge"] <= 0: return await c.answer("Qurolda zaryad yo'q!", show_alert=True)
        b = InlineKeyboardBuilder()
        for x in hero_targets(g, uid): b.button(text=f"{g.idx[x]}. {g.p[x]['n']}", callback_data=f"hg:{g.chat}:{x}")
        b.button(text=tt(uid, "back"), callback_data=f"hm:{g.chat}:back"); b.adjust(1)
        await c.message.edit_text("🥷 →", reply_markup=b.as_markup()); return await c.answer()
    if a == "s":
        g.p[uid]["shield"] = True; g.p[uid]["act"] = True
        text = f"⚜️ Geroy himoyasi: {U(uid)['hprot']}"
    else: text = "🚷"
    await c.message.edit_text(text); await c.answer(); done(g, uid, "h")


@r.callback_query(F.data.startswith("hg:"))
async def cb_hero_hit(c: CallbackQuery):
    _, ch, tg = c.data.split(":"); g = games.get(int(ch)); uid, tg = c.from_user.id, int(tg)
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"] or tg not in g.p: return await c.answer("Kech qoldingiz!", show_alert=True)
    g.hero[uid] = tg; g.p[uid]["act"] = True
    await c.message.edit_text(f"🥷 → {esc(g.p[tg]['n'])}"); await c.answer(); done(g, uid, "h")


async def hero_phase(g, blocked, dead):
    P = g.p; lines = []
    for u, tg in g.hero.items():
        if u in blocked or not P[u]["a"] or not P[tg]["a"] or any(d == tg for d, _, _ in dead): continue
        ud = U(u)
        if ud["charge"] <= 0: continue
        S(u, charge=ud["charge"] - 1)
        atk = rname(P[u]["r"]); tn = esc(P[tg]["n"]); tu = U(tg)
        if tu["geroyd"] > 0 and tu["t_g"]:
            A(tg, "geroyd", -1)
            lines.append(f"🔰 {tn}, siz geroydan saqlandingiz! {atk} geroyining hujumi qaytarildi.")
            await pm_g(g, tg, "🔰 Sizga geroy bilan hujum bo'ldi, ammo geroydan himoya sizni qutqardi!")
            continue
        dmg = hero_dmg(u)
        if P[tg]["shield"] and tu["hprot"] > 0:
            ab = min(dmg, tu["hprot"]); S(tg, hprot=tu["hprot"] - ab); dmg -= ab
            if dmg <= 0:
                lines.append(f"⚜️ {tn} geroy himoyasi bilan {atk} geroyining hujumini qaytardi!"); continue
        P[tg]["hp"] = max(0, P[tg]["hp"] - dmg)
        if P[tg]["hp"] <= 0:
            dead.append((tg, "hero", u))
        else:
            lines.append(f"{tn}ga {atk} geroyi bilan hujum qildi va {dmg}% jonini oldi. Hozirda uni {P[tg]['hp']}% joni bor.")
            await pm_g(g, tg, f"🥷 Sizga geroy bilan hujum qilindi! Joningiz: {P[tg]['hp']}%")
    return lines


def death_text(g, dead):
    P = g.p; txt = ""
    for tg, how, _ in dead:
        P[tg]["a"] = False
        txt += (f"\n💀 <b>{esc(P[tg]['n'])}</b> — {rname(P[tg]['r'])} vahshiylarcha o'ldirildi. "
                f"Aytishlaricha, uni {HOW.get(how, how)} tomonidan o'ldirishgan.")
    return txt


async def last_words(g, dead):
    for tg, _, _ in dead:
        await pm(tg, "Sizni shavqatsizlarcha o'ldirishdi! So'nggi so'zingizni aytish uchun sizda 45 soniya vaqt bor.")


async def resolve(g):
    P = g.p; N = g.night
    blocked = {x for u, (k, x) in N.items() if k == "b" and P[u]["a"]}
    heal = {x for u, (k, x) in N.items() if k == "h" and u not in blocked}
    hide = {x for u, (k, x) in N.items() if k == "a" and u not in blocked}
    guard = {x: u for u, (k, x) in N.items() if k == "q" and u not in blocked}
    mines = {x: u for u, (k, x) in N.items() if k == "m" and u not in blocked}
    fooled = {x for u, (k, x) in N.items() if k == "x" and u not in blocked}
    g.immune = set(); g.wit = []
    kills, bites = [], []
    mv = [(u, x) for u, (k, x) in N.items() if k == "k" and P[u]["r"] in ("don", "mafia") and u not in blocked]
    if mv:
        pick = next((y for y in mv if P[y[0]]["r"] == "don"), random.choice(mv)); kills.append((pick[0], pick[1], "mafia"))
    for u, (k, x) in N.items():
        if u in blocked or not P[u]["a"] or x not in P: continue
        rl = P[u]["r"]
        if k == "k" and rl in ("manyak", "ubiytsa"): kills.append((u, x, rl))
        elif k == "s" and rl == "komissar": kills.append((u, x, "komissar"))
        elif k == "e":
            if P[x]["r"] in MAF: heal.add(x)
            else: kills.append((u, x, "kimyogar"))
        elif k == "t":
            if P[x]["r"] in MAF or P[x]["r"] in SOLO: kills.append((u, x, "tentak"))
            else: g.immune.add(x)
        elif k == "c":
            tr = P[x]["r"]; ud = U(x)
            if x in hide and tr in MAF: tr = "tinch"
            elif ud["hujjat"] > 0 and ud["t_d"] and tr != "tinch": A(x, "hujjat", -1); tr = "tinch"
            if x in fooled: tr = P[random.choice(g.alive())]["r"]
            await pm(u, f"🔍 {esc(P[x]['n'])} — {rname(tr, u)}")
        elif k == "j":
            tr = P[x]["r"]; side = "🤵 Mafia" if tr in MAF else ("🎭 Yakka" if tr in SOLO else "🧑🏼 Tinch")
            await pm(u, f"📰 {esc(P[x]['n'])} — {side}")
        elif k == "w":
            tr = P[x]["r"]; msg = f"👁 Donning xotini aniqladi: {esc(P[x]['n'])} — {rname(tr)}"
            for z, d in P.items():
                if d["a"] and (d["r"] in MAF): await pm(z, msg)
        elif k == "d": g.wit.append((u, x))
        elif k == "g":
            amt = random.randint(50, 250); A(x, "money", amt)
            await pm(x, f"💰 Rais sizga {amt} 💶 sovg'a qildi!"); await pm(u, f"💰 Siz {esc(P[x]['n'])} ga {amt} 💶 sovg'a qildingiz.")
        elif k == "v": g.seller[x] = u
        elif k == "f": g.fans[u] = x
        elif k == "y":
            tr = P[x]["r"]; P[u]["r"] = tr if tr in MAF else "tinch"
            await pm(u, f"🦎 Siz endi {rname(P[u]['r'], u)}!")
        elif k == "z": bites.append((u, x))
    for u, x in g.wit:
        ks = [esc(P[kl]["n"]) for kl, kt, _ in kills if kt == x]
        await pm(u, f"🍾 Siz {esc(P[x]['n'])} uyiga bordingiz va {'qotilni ko`rdingiz: ' + ', '.join(ks) if ks else 'hech narsa ko`rmadingiz'}")
    dead = []
    dead_ids = lambda: {d for d, _, _ in dead}
    for killer, tg, how in kills:
        if not P[tg]["a"] or tg in dead_ids(): continue
        tr = P[tg]["r"]; ud = U(tg)
        if tg in mines and killer not in dead_ids():
            dead.append((killer, "mine", mines[tg])); await pm_g(g, tg, "💣 Eshigingiz oldidagi minada hujumchi portladi!"); continue
        gd = guard.get(tg)
        if gd and P[gd]["a"] and gd not in dead_ids() and gd != killer:
            dead.append((gd, how, killer)); await pm_g(g, tg, "💂 Sizga hujum bo'ldi, ammo Qo'riqchi o'zini qurbon qildi!"); continue
        if tg in heal: await pm_g(g, tg, "💉 Sizga hujum bo'ldi, ammo siz qutqarildingiz!"); continue
        if tr == "omadli" and random.random() < .35: await pm_g(g, tg, "🍀 Sizga hujum bo'ldi, ammo omadingiz kuldi!"); continue
        if ud["himoya"] > 0 and ud["t_h"]: A(tg, "himoya", -1); await pm_g(g, tg, "🛡 Sizga hujum bo'ldi, ammo himoya qutqardi!"); continue
        if tr == "mergan" and how == "manyak": await pm_g(g, tg, "🎯 Manyak sizni o'ldira olmadi!"); continue
        if tr == "sehrgar":
            if random.random() < .5: await pm_g(g, tg, "🧙‍♀️ Siz hujumchini kechirdingiz va omon qoldingiz."); continue
            if P[killer]["a"] and killer not in dead_ids(): dead.append((killer, "sehrgar", tg))
        dead.append((tg, how, killer))
        if tr == "kamikaze" and P[killer]["a"] and killer not in dead_ids(): dead.append((killer, "kamikaze", tg))
        if tr == "ovchi":
            cand = [y for y in g.alive() if (P[y]["r"] in MAF or P[y]["r"] in SOLO) and y not in dead_ids() and y != tg]
            if cand: dead.append((random.choice(cand), "ovchi", tg))
    conv = []
    for u, x in bites:                                        # zombi tishlashi
        if not P[x]["a"] or P[x]["r"] == "zombi" or x in dead_ids() or x in conv: continue
        if x in heal: await pm_g(g, x, "💉 Zombi sizga hujum qildi, ammo siz qutqarildingiz!"); continue
        if U(x)["himoya"] > 0 and U(x)["t_h"]: A(x, "himoya", -1); await pm_g(g, x, "🛡 Zombi sizni tishlamoqchi bo'ldi, himoya qutqardi!"); continue
        conv.append(x)
    for x in conv:
        P[x]["r"] = "zombi"; await pm_g(g, x, "🧟 Sizni zombi tishladi va siz zombiga aylandingiz!")
    hl = await hero_phase(g, blocked, dead)
    txt = ""
    if hl: txt += "\n".join(hl) + "\n"
    if conv: txt += f"\n🧟 Zombilar ko'payib bormoqda! Bu tun {len(conv)} kishi zombiga aylandi."
    if not dead and not conv: txt += "\nBu tun hech kim o'lmadi."
    txt += death_text(g, dead)
    await last_words(g, dead)
    for u, x in list(g.fans.items()):                         # muxlis: kumiri o'lsa — manyak
        if P[u]["a"] and P[u]["r"] == "muxlis" and not P[x]["a"]:
            P[u]["r"] = "manyak"; await pm(u, "🔪 Kumiringiz o'ldirildi! Siz endi Manyaksiz va qasos olasiz."); g.fans.pop(u, None)
    if not any(d["a"] and d["r"] == "komissar" for d in P.values()):
        for u, d in P.items():
            if d["a"] and d["r"] == "serjant": d["r"] = "komissar"; await pm(u, "🕵🏻‍♂️ Siz endi Komissarsiz!"); break
    if not any(d["a"] and d["r"] == "doktor" for d in P.values()):
        for u, d in P.items():
            if d["a"] and d["r"] == "hamshira": d["r"] = "doktor"; await pm(u, "👨🏼‍⚕️ Siz endi Doktorsiz!"); break
    g.state = "talk"
    return txt.strip()


async def resolve_vs(g):
    P = g.p; N = g.night
    heal = {"r": set(), "b": set()}
    for u, (k, x) in N.items():
        if k == "h" and P[u]["a"]: heal[P[u]["t"]].add(x)
    shots = {"r": {}, "b": {}}
    for u, (k, x) in N.items():
        if k == "k" and P[u]["a"]: shots[P[u]["t"]][x] = shots[P[u]["t"]].get(x, 0) + 1
    dead = []
    for tm, sh in shots.items():
        if not sh: continue
        mx = max(sh.values()); x = random.choice([y for y, v in sh.items() if v == mx])
        if not P[x]["a"]: continue
        ud = U(x)
        if x in heal[P[x]["t"]]: await pm_g(g, x, "💉 Sizga hujum bo'ldi, ammo Doktor sizni qutqardi!"); continue
        if ud["himoya"] > 0 and ud["t_h"]: A(x, "himoya", -1); await pm_g(g, x, "🛡 Sizga hujum bo'ldi, ammo himoya qutqardi!"); continue
        dead.append((x, "vs", 0))
    hl = await hero_phase(g, set(), dead)
    txt = ""
    if hl: txt += "\n".join(hl) + "\n"
    if not dead: txt += "\nBu tun hech kim o'lmadi."
    txt += death_text(g, dead)
    await last_words(g, dead)
    g.state = "talk"
    return txt.strip()


async def day_intro(g):
    await gmedia(g, "day", f"🏙 <b>{g.round}-kun</b>\nQuyosh chiqdi, ammo tun orqasida nima bo'lganini faqat bir necha kishi biladi...", link_kb())


# ---- Sotuvchi: yarim narxdagi mahsulotlar, 10% sotuvchiga ----
async def seller_offers(g):
    for x, s_ in g.seller.items():
        if not g.p[x]["a"]: continue
        b = InlineKeyboardBuilder()
        for k, (em, p) in SELL.items(): b.button(text=f"{tt(x, 'it_' + k)} — {p} 💶", callback_data=f"sv:{g.chat}:{k}")
        b.adjust(1); g.offers[x] = s_
        await pm_g(g, x, tt(x, "seller_offer"))
        await pm(x, "👇", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("sv:"))
async def cb_seller(c: CallbackQuery):
    _, ch, k = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or uid not in g.offers or g.state in ("night", "resolving") or k not in SELL: return await c.answer("⌛️ Taklif tugagan.", show_alert=True)
    em, p = SELL[k]
    if U(uid)["money"] < p: return await c.answer(tt(uid, "no_money"), show_alert=True)
    s_ = g.offers[uid]; A(uid, "money", -p); A(uid, k, 1); A(s_, "money", p // 10)
    await pm(s_, f"🎁 {esc(c.from_user.full_name)} {tt(s_, 'it_' + k)} sotib oldi — siz {p // 10} 💶 ishladingiz!")
    await c.answer(tt(uid, "bought", n=tt(uid, "it_" + k)), show_alert=True)


# ───────────────────────── Kun / ovoz berish ─────────────────────────
def yn_kb(chat, y=0, n=0):
    b = InlineKeyboardBuilder(); b.button(text=f"👍 {y}", callback_data=f"yn:{chat}:1"); b.button(text=f"👎 {n}", callback_data=f"yn:{chat}:0")
    return b.as_markup()


async def day(g):
    al = g.alive()
    await gm(g, f"<b>Tirik o'yinchilar:</b>\n{g.plist()}\n\n💬 Muhokama vaqti ⏳ {DAY_SEC} sekund", reply_markup=link_kb())
    await asyncio.sleep(DAY_SEC)
    g.state = "vote"; g.votes = {}
    await gm(g, f"⚖️ Aybdorlarni aniqlash vaqti keldi.\nOvoz berish uchun {VOTE_SEC} sekund vaqt.", reply_markup=link_kb("🗳 Ovoz berish"))
    for u in al:
        b = InlineKeyboardBuilder()
        for x in al:
            if x != u: b.button(text=g.p[x]["n"], callback_data=f"vt:{g.chat}:{x}")
        b.button(text="⏭ O'tkazib yuborish", callback_data=f"vt:{g.chat}:0"); b.adjust(2)
        await pm(u, "Kimni osamiz?", reply_markup=b.as_markup())
    await asyncio.sleep(VOTE_SEC)
    tally = {}
    for u, x in g.votes.items():
        if x: tally[x] = tally.get(x, 0) + (2 if g.p[u]["r"] == "janob" else 1)
    if not tally:
        g.state = "post"; return await gm(g, "Hech kim ovoz bermadi. Hech kim osilmadi, arqon osilib qoldi.")
    mx = max(tally.values()); top = [x for x, v in tally.items() if v == mx]
    if len(top) > 1:
        g.state = "post"; return await gm(g, "Bahslar tugadi, arqon osilib qoldi. Hech kim osilmadi.")
    tg = top[0]; g.cand = tg; g.yn = {}; g.state = "confirm"
    await gm(g, f"⚖️ <b>{esc(g.p[tg]['n'])}</b>ni osishga rozimisiz?\nOvoz berish uchun {CONF_SEC} sekund.", reply_markup=yn_kb(g.chat))
    await asyncio.sleep(CONF_SEC)
    g.state = "post"
    y = sum(1 for v in g.yn.values() if v == 1); n = sum(1 for v in g.yn.values() if v == 0)
    head = f"<b>Ovoz berish natijalari:</b>\n{y}👍 | {n}👎\n\n"
    ud = U(tg)
    if y <= n:
        return await gm(g, head + f"Aholi fikri bo'linib, <b>{esc(g.p[tg]['n'])}</b> osilmadi.")
    if tg in g.immune:
        return await gm(g, head + f"🎲 {esc(g.p[tg]['n'])} bugun osilmaydi (Tentak himoyasi).")
    if ud["osish"] > 0 and ud["t_o"] and not g.p[tg]["osh"]:     # osishdan himoya: bir o'yinda 1 marta
        A(tg, "osish", -1); g.p[tg]["osh"] = True
        return await gm(g, head + f"⚖️ {esc(g.p[tg]['n'])} osishdan himoya tufayli qutqarildi!")
    g.p[tg]["a"] = False
    await gm(g, head + f"🪢 <b>{esc(g.p[tg]['n'])}</b> kunduzgi yig'ilishda osildi!\nU edi {rname(g.p[tg]['r'])}.")
    await pm(tg, "Sizni osib o'ldirishdi! So'nggi so'zingizni aytish uchun sizda 45 soniya vaqt bor.")
    if g.p[tg]["r"] == "suidsid": g.suid = tg
    if g.p[tg]["r"] == "kamikaze":
        vs_ = [u for u, v in g.votes.items() if v == tg and g.p[u]["a"]]
        if vs_:
            k = random.choice(vs_); g.p[k]["a"] = False
            await gm(g, f"💣 Kamikaze {esc(g.p[k]['n'])} ({rname(g.p[k]['r'])}) ni o'zi bilan olib ketdi!")
    if g.p[tg]["r"] == "ovchi":
        cand = [y for y in g.alive() if g.p[y]["r"] in MAF or g.p[y]["r"] in SOLO]
        if cand:
            k = random.choice(cand); g.p[k]["a"] = False
            await gm(g, f"🏹 Ovchi {esc(g.p[k]['n'])} ({rname(g.p[k]['r'])}) ni o'zi bilan olib ketdi!")


async def idle_check(g):
    for u, d in g.p.items():
        if not d["a"]: continue
        d["idle"] = 0 if d["act"] else d["idle"] + 1
        if d["idle"] >= 2:
            d["a"] = False
            await gm(g, f"⌛️ {esc(d['n'])} 2 kun hech narsa qilmadi va o'yindan chetlatildi! U edi {rname(d['r'])}")
            await pm(u, "⌛️ Siz 2 kun hech narsa qilmadingiz va o'yindan chetlatildingiz!")


@r.callback_query(F.data.startswith("vt:"))
async def cb_vote(c: CallbackQuery):
    _, ch, tg = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "vote" or uid not in g.p or not g.p[uid]["a"] or (int(tg) and int(tg) not in g.p):
        return await c.answer("Kech qoldingiz!", show_alert=True)
    g.votes[uid] = int(tg); g.p[uid]["act"] = True
    await c.message.edit_text("Siz ovoz berdingiz: " + (esc(g.p[int(tg)]["n"]) if int(tg) else "o'tkazib yuborildi"))
    await gm(g, f"🗳 {esc(g.p[uid]['n'])} ovoz berdi" + (f": {esc(g.p[int(tg)]['n'])}" if int(tg) else "")); await c.answer()


@r.callback_query(F.data.startswith("yn:"))
async def cb_yn(c: CallbackQuery):
    _, ch, v = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "confirm" or uid not in g.p or not g.p[uid]["a"] or uid == g.cand:
        return await c.answer("Siz ovoz bera olmaysiz!", show_alert=True)
    g.yn[uid] = int(v); g.p[uid]["act"] = True
    y = sum(1 for x in g.yn.values() if x == 1); n = sum(1 for x in g.yn.values() if x == 0)
    try: await c.message.edit_reply_markup(reply_markup=yn_kb(g.chat, y, n))
    except Exception: pass
    await c.answer("Ovozingiz qabul qilindi")


# ───────────────────────── G'alaba / yakun ─────────────────────────
def win(g):
    P = g.p; al = [d for d in P.values() if d["a"]]
    if g.vs:
        rc = sum(1 for d in al if d["t"] == "r"); bc = sum(1 for d in al if d["t"] == "b")
        if rc == 0 and bc == 0: return "draw"
        if bc == 0: return "r"
        if rc == 0: return "b"
        if g.round >= 15: return "r" if rc > bc else ("b" if bc > rc else "draw")
        return None
    if g.mode == "zombie":
        z = sum(d["r"] == "zombi" for d in al)
        if z == 0: return "tinch"
        if z >= len(al) - z: return "zombi"
        return None
    if getattr(g, "suid", None): return "suidsid"
    mf = sum(d["r"] in MAF for d in al); mn = sum(d["r"] == "manyak" for d in al)
    if mf == 0 and mn == 0: return "tinch"
    if mf == 0 and mn and len(al) <= 2: return "manyak"
    if mf and mf >= len(al) - mf: return "mafia"
    return None


async def finish(g, w):
    mins = max(1, round((time.time() - g.t0) / 60))

    def won(d):
        rl = d["r"]
        if g.vs: return w == d["t"]
        if g.mode == "zombie": return (w == "zombi" and rl == "zombi") or (w == "tinch" and rl != "zombi")
        return (w == "mafia" and rl in MAF) or (w == "manyak" and rl == "manyak") or \
               (w == "tinch" and rl not in MAF and rl not in SOLO) or (w == "suidsid" and rl == "suidsid")

    tag = {"r": "🔴 ", "b": "🔵 "}

    def fmt(d):
        s = f"{tag.get(d['t'], '') if g.vs else ''}{esc(d['n'])} — {rname(d['r0'])}"
        return s + (f" ➜ {rname(d['r'])}" if d["r"] != d["r0"] else "")

    win_l = [fmt(d) for d in g.p.values() if won(d)]
    oth_l = [fmt(d) for d in g.p.values() if not won(d)]
    txt = "<b>O'yin tugadi!</b>\n\n"
    if g.vs and w == "draw": txt += "🤝 Durang!\n\n"
    if win_l: txt += "<b>G'olib bo'lgan o'yinchilar:</b>\n" + "\n".join(win_l) + "\n\n"
    if oth_l: txt += "<b>Qolgan o'yinchilar ro'yhati:</b>\n" + "\n".join(oth_l) + "\n\n"
    txt += f"O'yin vaqti: {mins} minut"
    await gm(g, txt)
    now = int(time.time())
    for u, d in g.p.items():
        wn = won(d)
        ball = random.randint(50, 150) if wn else -random.randint(10, 50)
        A(u, "games", 1); A(u, "money", 130 if wn else 40)
        if wn: A(u, "wins", 1)
        S(u, points=max(0, U(u)["points"] + ball))
        db.execute("INSERT INTO pts_log(uid,ball,ts,chat) VALUES(?,?,?,?)", (u, ball, now, g.chat)); db.commit()
        await pm(u, f"🏁 O'yin tugadi.\nSizga 💶 {130 if wn else 40}, {abs(ball)} ball {'🎯 berildi!' if wn else '🎯 ayirildi!'}")


# ───────────────────────── Admin panel (faqat ADMIN_ID) ─────────────────────────
BIG = 10 ** 9


def admin_kb():
    b = InlineKeyboardBuilder()
    for t_, d in [("💶 Cheksiz pul", "ad:money"), ("💎 Cheksiz olmos", "ad:dia"), ("💠 Cheksiz NightCoin", "ad:nc"),
                  ("🛡 Barcha buyumlar +99", "ad:items"), ("🥷 Geroy + 38-daraja", "ad:hero"), ("👑 VIP Promax (365 kun)", "ad:vip"),
                  ("📊 Statistika", "ad:stat")]: b.button(text=t_, callback_data=d)
    b.adjust(2); return b.as_markup()


@r.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id): return
    await m.answer("🛠 <b>Admin panelingiz</b>\n\nBuyruqlar:\n<code>/addmoney [id] miqdor</code>\n<code>/adddiamond [id] miqdor</code>\n"
                   "<code>/addncoin [id] miqdor</code>\n<code>/blok id</code> / <code>/unblok id</code>\n<code>/broadcast matn</code>\n"
                   "Operator: foydalanuvchi xabariga <b>reply</b> qilib javob bering.\n(id yozilmasa — o'zingizga)", reply_markup=admin_kb())


@r.callback_query(F.data.startswith("ad:"))
async def cb_admin(c: CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer("Ruxsat yo'q", show_alert=True)
    a, uid = c.data[3:], c.from_user.id
    if a == "money": S(uid, money=BIG)
    if a == "dia": S(uid, diamonds=BIG)
    if a == "nc": S(uid, ncoin=BIG)
    if a == "items": S(uid, himoya=99, hujjat=99, osish=99, geroyd=99)
    if a == "hero": S(uid, has_hero=1, points=40700, hprot=300, charge=10)
    if a == "vip": S(uid, vip=4, vip_until=int(time.time() + 365 * 86400)); A(uid, "boosts", 1)
    if a == "stat":
        n = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        return await c.answer(f"Foydalanuvchilar: {n}\nAktiv o'yinlar: {len(games)}", show_alert=True)
    await c.answer("✅ Bajarildi", show_alert=True)


async def admin_add(m: Message, f):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()[1:]
    if not p or not p[-1].lstrip("-").isdigit(): return await m.reply("Foydalanish: /buyruq [id] miqdor")
    tid = int(p[0]) if len(p) > 1 else m.from_user.id
    A(tid, f, int(p[-1])); await m.reply(f"✅ {tid}: {f} {int(p[-1]):+d}")


@r.message(Command("addmoney"))
async def a1(m: Message): await admin_add(m, "money")


@r.message(Command("adddiamond"))
async def a2(m: Message): await admin_add(m, "diamonds")


@r.message(Command("addncoin"))
async def a3(m: Message): await admin_add(m, "ncoin")


@r.message(Command("blok"))
async def blok(m: Message):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()
    tid = int(p[1]) if len(p) > 1 and p[1].isdigit() else (m.reply_to_message.from_user.id if m.reply_to_message else 0)
    if not tid or tid in ADMIN_IDS: return await m.reply("Foydalanish: /blok id")
    u = U(tid)
    if u["blocked"]: return await m.reply("Bu foydalanuvchi allaqachon bloklangan.")
    snap = {c_: u[c_] for c_ in COLS}
    snap["heroes"] = [dict(x) for x in db.execute("SELECT name,points,hprot,charge FROM heroes WHERE uid=?", (tid,))]
    db.execute("INSERT OR REPLACE INTO bans(id,snap) VALUES(?,?)", (tid, json.dumps(snap)))
    db.execute("DELETE FROM heroes WHERE uid=?", (tid,)); db.commit()
    S(tid, blocked=1, **{c_: ("" if isinstance(u[c_], str) else 0) for c_ in COLS})
    await m.reply(f"🚫 {esc(u['name'])} ({tid}) botdan ban qilindi. Akkaunti 0 qilindi (/unblok bilan tiklanadi).")


@r.message(Command("unblok"))
async def unblok(m: Message):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()
    tid = int(p[1]) if len(p) > 1 and p[1].isdigit() else (m.reply_to_message.from_user.id if m.reply_to_message else 0)
    if not tid: return await m.reply("Foydalanish: /unblok id")
    row = db.execute("SELECT snap FROM bans WHERE id=?", (tid,)).fetchone()
    S(tid, blocked=0)
    if row:
        snap = json.loads(row["snap"]); hs = snap.pop("heroes", [])
        S(tid, **{k: v for k, v in snap.items() if k in COLS})
        for h in hs: db.execute("INSERT INTO heroes(uid,name,points,hprot,charge) VALUES(?,?,?,?,?)", (tid, h["name"], h["points"], h["hprot"], h["charge"]))
        db.execute("DELETE FROM bans WHERE id=?", (tid,)); db.commit()
    await m.reply(f"✅ {esc(U(tid)['name'])} ({tid}) blokdan chiqarildi, akkaunt asl holatiga qaytarildi.")


@r.message(Command("broadcast"))
async def broadcast(m: Message):
    if not is_admin(m.from_user.id): return
    txt = (m.text or "").partition(" ")[2]; ok_ = 0
    for row in db.execute("SELECT id FROM users").fetchall():
        if await pm(row["id"], txt): ok_ += 1
        await asyncio.sleep(.05)
    await m.reply(f"Yuborildi: {ok_}")


# ───────────────────────── Premium emoji ID larni avtomatik olish + /weburl ─────────────────────────
def has_cemoji(m: Message):
    return bool(m.chat.type == "private" and m.from_user and is_admin(m.from_user.id)
                and any(e.type == "custom_emoji" for e in (m.entities or [])))


@r.message(has_cemoji, F.text)
async def cap_emoji(m: Message):
    found = {}
    for e in m.entities:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            ch = e.extract_from(m.text)
            if ch: found[ch] = e.custom_emoji_id
    if not found: return
    d = dict(PE); d.update(found); set_pe(d); save_pe()
    await m.reply("✅ Premium emoji saqlandi:\n" + "\n".join(f"{k} → <code>{v}</code>" for k, v in found.items())
                  + f"\n\nJami: {len(PE)} ta. Bot ularni shu zahoti ishlata boshladi.")


@r.message(Command("emojiid"))
async def cmd_emojiid(m: Message):
    if not is_admin(m.from_user.id): return
    await m.reply("Menga premium emoji(lar) yuboring (masalan 💎 🛡 🥷 ...) — ID larini o'zim topib saqlayman.\n"
                  f"Hozir saqlangan: {' '.join(PE) or 'yo`q'}\nTozalash: /emojiclear")


@r.message(Command("emojiclear"))
async def cmd_emojiclear(m: Message):
    if is_admin(m.from_user.id): set_pe({}); save_pe(); await m.reply("🧹 Tozalandi.")


@r.message(Command("weburl"))
async def cmd_weburl(m: Message, command: CommandObject):
    global WEB_URL, WEB_HTTPS
    if not is_admin(m.from_user.id): return
    if not command.args:
        return await m.reply(f"🌐 WEB_URL: <code>{esc(WEB_URL)}</code>\n{'✅ HTTPS' if WEB_HTTPS else '⚠️ HTTPS emas'}\nO'zgartirish: /weburl https://domen")
    u = norm_url(command.args.split()[0])
    if not u.startswith("https://"): return await m.reply("⚠️ HTTPS manzil kerak, masalan: /weburl https://mafia.example.com")
    WEB_URL, WEB_HTTPS = u, True
    open("web_url.txt", "w", encoding="utf-8").write(u)
    await m.reply(f"✅ Saqlandi: <code>{esc(u)}</code>\nKabinet: {esc(u)}/app")


# ───────────────────────── Operator: admin javobi (reply) ─────────────────────────
def is_sup_reply(m: Message):
    if not (m.chat.type == "private" and m.reply_to_message and is_admin(m.from_user.id)): return False
    return db.execute("SELECT 1 FROM support_map WHERE chat=? AND mid=?", (m.chat.id, m.reply_to_message.message_id)).fetchone() is not None


@r.message(is_sup_reply, F.text | F.photo)
async def admin_support_reply(m: Message):
    row = db.execute("SELECT uid FROM support_map WHERE chat=? AND mid=?", (m.chat.id, m.reply_to_message.message_id)).fetchone()
    if not row: return
    uid = row["uid"]; fname = ""; text = (m.text or m.caption or "").strip()[:1000]
    if m.photo:
        fname = uuid.uuid4().hex + ".jpg"
        try: await bot.download(m.photo[-1], destination=os.path.join(UP, fname))
        except Exception: fname = ""
    if not text and not fname: return
    db.execute("INSERT INTO support(uid,role,text,img,ts) VALUES(?,?,?,?,?)", (uid, "a", text, fname, int(time.time()))); db.commit()
    await pm(uid, "📩 <b>Operator javobi:</b>\n\n" + esc(text or "🖼"))
    await m.reply("✅ Foydalanuvchiga yuborildi.")


# ───────────────────────── Matnli javoblar (nom, status, profil almashish) ─────────────────────────
@r.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def private_text(m: Message):
    uid = m.from_user.id; w = WAIT.pop(uid, None); u = U(uid)
    if w == "hname":
        if u["money"] < 800: return await m.answer(tt(uid, "h_no800"))
        A(uid, "money", -800); S(uid, hname=m.text[:24]); await m.answer(tt(uid, "h_name_ok"))
    elif w == "status":
        S(uid, name=m.text[:40]); await m.answer(tt(uid, "h_status_ok"))
    elif w == "transfer":
        if not m.text.strip().isdigit(): return await m.answer(tt(uid, "tr_digits"))
        tid = int(m.text.strip())
        if tid == uid: return await m.answer(tt(uid, "tr_self"))
        tu = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
        if not tu: return await m.answer(tt(uid, "tr_nostart"))
        if tu["games"] > 0: return await m.answer(tt(uid, "tr_new"))
        if u["diamonds"] < 5: return await m.answer(tt(uid, "tr_5"))
        PEND[uid] = tid
        b = InlineKeyboardBuilder(); b.button(text=tt(uid, "tr_yes"), callback_data="pt:y"); b.button(text=tt(uid, "tr_no"), callback_data="pt:n")
        await m.answer(tt(uid, "tr_conf", id=tid, name=esc(tu["name"] or str(tid))), reply_markup=b.as_markup())


# ═════════════════════════ TELEGRAM WEB APP — "Shaxsiy kabinet" (backend) ═════════════════════════
class ApiErr(Exception): pass


API = {}
THEME_IDS = {"cyber", "green", "gold", "pink", "blue", "purple", "ruby", "teal", "platinum"}
NEWR = {"sehrgar", "mergan", "ovchi", "qoriqchi", "hamshira", "jurnalist", "jangchi"}
ACTN = {"k": "Qotillik", "c": "Tekshirish / otish", "s": "Otish", "h": "Davolash", "b": "Mehmonga borish", "a": "Himoya qilish",
        "d": "Butilka olish", "x": "Aldash", "m": "Mina qo'yish", "w": "Rolni aniqlash", "e": "Kimyo", "t": "Tanlash",
        "y": "Tarafni tanlash", "v": "Taklif qilish", "f": "Muxlislik", "g": "Sovg'a berish", "z": "Zombilash", "j": "Tekshirish", "q": "Qo'riqlash"}
RA = {  # (ikonka, sarlavha, matn) — faqat o'zbek tilida
    "don": [("🎯", "Buyruq", "Tunda mafia nishonini siz belgilaysiz: Don va Mafia tanlovi orasidan Donning tanlovi hal qiluvchi."),
            ("🤝", "Jamoa", "O'yin boshida mafia sheriklaringiz ro'yxati sizga yuboriladi.")],
    "mafia": [("🔪", "Hujum", "Tunda Don bilan birga nishon tanlaysiz; Don bo'lmasa tanlovlardan biri tasodifiy ishlaydi."),
              ("🤝", "Jamoa", "Mafia sheriklaringiz ro'yxati o'yin boshida yuboriladi.")],
    "manyak": [("🔪", "Yakka ov", "Har tun bitta o'yinchini o'ldirasiz. Mergan sizdan himoyalangan."),
               ("🏆", "Yutuq", "Siz va yana bir kishi qolsa, g'olib bo'lasiz.")],
    "komissar": [("🔍", "Tekshirish", "Tunda bir o'yinchining rolini aniqlaysiz (Advokat himoyasi va soxta hujjat natijani buzishi mumkin)."),
                 ("🔫", "Otish", "Yoki tunda bir o'yinchini otib o'ldirasiz.")],
    "doktor": [("💉", "Davolash", "Tunda tanlagan o'yinchingiz hujumdan omon qoladi (o'zingizni ham tanlashingiz mumkin).")],
    "serjant": [("🕵️", "Vorislik", "Komissar o'lsa, uning o'rniga Komissar bo'lasiz.")],
    "advokat": [("⚖️", "Himoya", "Tanlagan mafiangizni Komissar tinch aholi deb ko'radi.")],
    "ubiytsa": [("🥷", "Ov", "Mafia tarafida har tun bir o'yinchini yo'q qilasiz.")],
    "suidsid": [("🪢", "Yutuq", "Kunduzgi ovozda osilsangiz — siz g'olibsiz.")],
    "kamikaze": [("💣", "Portlash", "Tunda o'ldirilsangiz, qotilingiz ham o'ladi. Osilsangiz, ovoz bergan bir kishini olib ketasiz.")],
    "mashuqa": [("💃", "Uyqu", "Tanlagan odamingiz shu tunda harakat qila olmaydi.")],
    "daydi": [("🍾", "Guvoh", "Tanlangan odamning uyiga borib, o'sha tunda uni o'ldirmoqchi bo'lganlarni ko'rasiz.")],
    "mergan": [("🎯", "Daxlsizlik", "Manyak sizni o'ldira olmaydi.")],
    "tinch": [("🗳", "Ovoz", "Kunduzi ovoz berib, mafiyani osishga yordam bering.")],
    "jangchi": [("🎯", "Nishon", "VS rejimida har tun raqib jamoadan bitta o'yinchini nishonga olasiz.")],
}
SUP_LAST, GC_LAST = {}, {}


def api(name):
    def deco(fn): API[name] = fn; return fn
    return deco


def iv(x, lo=1, hi=10 ** 12):
    try: n = int(str(x).strip())
    except Exception: raise ApiErr("bad_amount")
    if n < lo or n > hi: raise ApiErr("bad_amount")
    return n


def check_init(init):
    """Telegram WebApp initData imzosini tekshiradi."""
    if not init: return None
    try:
        d = dict(urllib.parse.parse_qsl(init, keep_blank_values=True))
        h = d.pop("hash", "")
        s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
        key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(key, s.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, h): return None
        if time.time() - int(d.get("auth_date", "0")) > 172800: return None
        user = json.loads(d["user"])
        return user if isinstance(user, dict) and "id" in user else None
    except Exception:
        return None


async def api_handler(req):
    fn = API.get(req.match_info["name"])
    if not fn: return web.json_response({"error": "nf"}, status=404)
    tu = check_init(req.headers.get("X-Init", ""))
    if not tu: return web.json_response({"error": "auth"}, status=401)
    try: body = await req.json()
    except Exception: body = {}
    if not isinstance(body, dict): body = {}
    uid = int(tu["id"]); full = (tu.get("first_name", "") + " " + tu.get("last_name", "")).strip() or str(uid)
    u = U(uid, full)
    if u["blocked"] and not is_admin(uid): return web.json_response({"error": "blocked"}, status=403)
    if (tu.get("username") or "") != (u["username"] or ""):
        S(uid, username=tu.get("username") or ""); u = U(uid)
    try:
        res = fn(u, body, tu)
        if asyncio.iscoroutine(res): res = await res
        return web.json_response(res)
    except ApiErr as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception:
        logging.exception("api xato: %s", req.match_info["name"])
        return web.json_response({"error": "server"}, status=500)


def hero_dict(u):
    if not u["has_hero"]: return None
    L_ = lvl(u["points"])
    return dict(name=u["hname"], lvl=L_, pts=u["points"], prot=u["hprot"], maxp=MAXH[L_ - 1], charge=u["charge"], gd=u["geroyd"],
                nxt=(L_ * 1100 if L_ < 38 else None), pw=([40 + 7 * (L_ - 1), 47 + 7 * (L_ - 1)] if L_ < 38 else None))


def rtxt(k, lg):
    e, n, d = RD[k]
    if lg in ("ru", "en") and k in RT: n = RT[k][0 if lg == "ru" else 1]; d = RT[k][2 if lg == "ru" else 3]
    return e, n, d


@api("me")
def a_me(u, b, tu):
    uid = u["id"]; lv = vlevel(u); lg = u["wlang"]
    pairs = []
    for x in pairs_of(uid):
        row = db.execute("SELECT name FROM users WHERE id=?", (x,)).fetchone()
        pairs.append(dict(id=x, name=row["name"] if row else str(x)))
    return dict(id=uid, name=u["name"], username=tu.get("username") or u["username"] or "", photo=tu.get("photo_url", ""),
                money=u["money"], dia=u["diamonds"], nc=u["ncoin"], vip=lv, vip_name=VIPS[lv][0] if lv else "", vip_until=u["vip_until"],
                items=dict(himoya=u["himoya"], hujjat=u["hujjat"], osish=u["osish"], geroyd=u["geroyd"], ncoin=u["ncoin"]),
                tg=dict(himoya=u["t_h"], hujjat=u["t_d"], osish=u["t_o"], geroyd=u["t_g"]),
                aroles=[dict(k=x, e=rtxt(x, lg)[0], n=rtxt(x, lg)[1]) for x in aroles(u) if x in RD],
                games=u["games"], wins=u["wins"], lost=max(0, u["games"] - u["wins"]),
                wr=round(u["wins"] * 100 / u["games"]) if u["games"] else 0,
                theme=u["theme"] if u["theme"] in THEME_IDS else "cyber", lang=u["wlang"], pairs=pairs, plim=PLIM[lv],
                hero=hero_dict(u), hcount=hcount(uid), hlim=HLIM[lv], boosts=u["boosts"],
                fee=dict(money=0 if lv else 100, dia=0 if lv else 10, item=0 if lv else 100),
                vips=[dict(k=k, n=n, p=p, st=p * 5) for k, (n, p) in VIPS.items()],
                srv=dict(games=len(games), users=db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]))


@api("set")
def a_set(u, b, tu):
    th, lg = b.get("theme"), b.get("lang")
    if th is not None:
        if th not in THEME_IDS: raise ApiErr("bad")
        S(u["id"], theme=th)
    if lg is not None:
        if lg not in PLD: raise ApiErr("bad")
        S(u["id"], wlang=lg)
    return dict(ok=1)


@api("roles")
def a_roles(u, b, tu):
    lg = u["wlang"]; out = []
    for k, (e0, n0, d0) in RD.items():
        e, n, d = rtxt(k, lg)
        team = "maf" if k in MAF else ("solo" if k in SOLO else "city")
        ex = [dict(i=i, t=t, x=x) for i, t, x in RA.get(k, [])] if lg == "uz" else []
        acts = ACT.get(k) or ACT_VS.get(k) or []
        out.append(dict(k=k, e=e, n=n, d=d, team=team, new=k in NEWR, ex=ex,
                        act=[dict(i=em, t=ACTN.get(c_, c_)) for c_, em in acts]))
    return dict(roles=out)


@api("shop")
def a_shop(u, b, tu):
    lg = u["wlang"]
    return dict(items=[dict(k=k, cur=cur, p=p) for k, (cur, p) in ITEMS.items()],
                aroles=[dict(k=k, e=rtxt(k, lg)[0], n=rtxt(k, lg)[1], cur=cur, p=p) for k, (cur, p) in ARP.items() if k in RD],
                amax=AMAX)


@api("buy")
def a_buy(u, b, tu):
    k = b.get("k"); uid = u["id"]
    if k == "hero":
        if hcount(uid) >= hlim(uid): raise ApiErr("hero_full")
        if u["diamonds"] < 90: raise ApiErr("no_dia")
        A(uid, "diamonds", -90); add_hero(uid); return dict(ok=1)
    if k not in ITEMS: raise ApiErr("bad")
    cur, p = ITEMS[k]
    if u[cur] < p: raise ApiErr("no_dia" if cur == "diamonds" else "no_money")
    A(uid, cur, -p); A(uid, k, 1); return dict(ok=1)


@api("arole")
def a_arole(u, b, tu):
    k = b.get("k"); uid = u["id"]; lst = aroles(u)
    if k == "del":
        if not lst: raise ApiErr("no_ar")
        if u["money"] < 100: raise ApiErr("no_money")
        A(uid, "money", -100); S(uid, arole=""); return dict(ok=1)
    if k not in ARP: raise ApiErr("bad")
    if len(lst) >= AMAX: raise ApiErr("ar_max")
    cur, p = ARP[k]; f = "diamonds" if cur == "d" else "money"
    if u[f] < p: raise ApiErr("no_dia" if cur == "d" else "no_money")
    A(uid, f, -p); S(uid, arole=",".join(lst + [k])); return dict(ok=1)


@api("toggle")
def a_toggle(u, b, tu):
    col = {"himoya": "t_h", "hujjat": "t_d", "osish": "t_o", "geroyd": "t_g"}.get(b.get("k"))
    if not col: raise ApiErr("bad")
    S(u["id"], **{col: 0 if u[col] else 1}); return dict(ok=1)


@api("transfer")
async def a_transfer(u, b, tu):
    uid = u["id"]; kind = b.get("kind"); to = b.get("to_type"); val = str(b.get("to") or "").strip()
    amt = iv(b.get("amount"))
    if to == "pair":
        ps = pairs_of(uid)
        if not ps: raise ApiErr("no_pair")
        tid = ps[0]
    elif to == "id":
        if not val.isascii() or not val.isdigit(): raise ApiErr("no_user")
        tid = int(val)
    elif to == "user":
        un = val.lstrip("@").lower()
        if not un: raise ApiErr("no_user")
        row = db.execute("SELECT id FROM users WHERE lower(username)=? LIMIT 1", (un,)).fetchone()
        if not row: raise ApiErr("no_user")
        tid = row["id"]
    else: raise ApiErr("bad")
    tr = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
    if not tr or tr["blocked"]: raise ApiErr("no_user")
    if tid == uid: raise ApiErr("self")
    vip = vlevel(u) > 0
    if kind == "money":
        fee = 0 if vip else 100
        if u["money"] < amt + fee: raise ApiErr("no_money")
        A(uid, "money", -(amt + fee)); A(tid, "money", amt); got = amt; sym = f"{n_(amt)} 💶"
    elif kind == "diamonds":
        got = amt if vip else int(amt * 0.9)
        if got < 1: raise ApiErr("bad_amount")
        if u["diamonds"] < amt: raise ApiErr("no_dia")
        A(uid, "diamonds", -amt); A(tid, "diamonds", got); sym = f"{n_(got)} 💎"
    elif kind == "item":
        item = b.get("item")
        if item not in ("himoya", "hujjat", "osish", "geroyd"): raise ApiErr("bad")
        fee = 0 if vip else 100
        if u[item] < amt: raise ApiErr("no_item")
        if u["money"] < fee: raise ApiErr("no_money")
        A(uid, item, -amt); A(tid, item, amt)
        if fee: A(uid, "money", -fee)
        got = amt; sym = f"{amt} × {tt(tid, 'it_' + item)}"; kind = "item:" + item
    else: raise ApiErr("bad")
    txlog(uid, tid, kind, got)
    await pm(tid, f"📥 {esc(u['name'])} sizga {sym} o'tkazdi!")
    return dict(ok=1, to=tr["name"])


@api("history")
def a_history(u, b, tu):
    uid = u["id"]; mine = b.get("scope") != "all"
    q = ("SELECT t.ts,t.src,t.dst,t.kind,t.amount,us.name sn,ud.name dn FROM tx t LEFT JOIN users us ON us.id=t.src "
         "LEFT JOIN users ud ON ud.id=t.dst WHERE t.kind!='account'")
    prm = []
    if mine: q += " AND (t.src=? OR t.dst=?)"; prm += [uid, uid]
    q += " ORDER BY t.id DESC LIMIT 50"
    rows = db.execute(q, prm).fetchall()
    return dict(rows=[dict(ts=x["ts"], frm=x["sn"] or str(x["src"]), to=x["dn"] or str(x["dst"]), kind=x["kind"], amt=x["amount"],
                           out=x["src"] == uid, me=(x["src"] == uid or x["dst"] == uid)) for x in rows])


@api("top")
def a_top(u, b, tu):
    days = int(b.get("days") or 0)
    if days not in (0, 1, 7, 30): days = 0
    since = int(time.time() - days * 86400) if days else 0
    rows = db.execute("SELECT l.uid uid, u.name nm, SUM(l.ball) s FROM pts_log l JOIN users u ON u.id=l.uid WHERE l.ts>=? "
                      "GROUP BY l.uid HAVING s>0 ORDER BY s DESC LIMIT 50", (since,)).fetchall()
    return dict(rows=[dict(n=x["nm"], s=x["s"], me=x["uid"] == u["id"]) for x in rows])


@api("love")
def a_love(u, b, tu):
    rows = db.execute("SELECT a1.name an, b1.name bn FROM pairs p JOIN users a1 ON a1.id=p.a JOIN users b1 ON b1.id=p.b ORDER BY p.rowid DESC LIMIT 40").fetchall()
    return dict(sky=[dict(a=x["an"], b=x["bn"]) for x in rows])


@api("vip")
def a_vip(u, b, tu):
    k = int(b.get("k") or 0)
    if k not in VIPS: raise ApiErr("bad")
    if u["diamonds"] < VIPS[k][1]: raise ApiErr("no_dia")
    A(u["id"], "diamonds", -VIPS[k][1]); grant_vip(u["id"], k); return dict(ok=1)


@api("invoice")
async def a_invoice(u, b, tu):
    what = b.get("what")
    if what == "hero":
        if hcount(u["id"]) >= hlim(u["id"]): raise ApiErr("hero_full")
        link = await bot.create_invoice_link("🥷 Geroy", "1-daraja geroy", "hero", "XTR", [LabeledPrice(label="Geroy", amount=300)])
    elif what == "vip":
        k = int(b.get("k") or 0)
        if k not in VIPS: raise ApiErr("bad")
        link = await bot.create_invoice_link(VIPS[k][0], "30 kunlik VIP obuna", f"vip:{k}", "XTR", [LabeledPrice(label=VIPS[k][0], amount=VIPS[k][1] * 5)])
    else: raise ApiErr("bad")
    return dict(link=link)


# ---- Geroy ----
@api("hero")
async def a_hero(u, b, tu):
    a = b.get("a"); uid = u["id"]
    if a == "buy": return a_buy(u, {"k": "hero"}, tu)
    if not u["has_hero"]: raise ApiErr("no_hero")
    if a == "name":
        nm = str(b.get("name") or "").strip()[:24]
        if not nm: raise ApiErr("empty")
        if u["money"] < 800: raise ApiErr("no_money")
        A(uid, "money", -800); S(uid, hname=nm); return dict(ok=1)
    cost = {"ball": ("diamonds", 50), "prot": ("money", 300), "charge": ("money", 200)}.get(a)
    if not cost: raise ApiErr("bad")
    if u[cost[0]] < cost[1]: raise ApiErr("no_dia" if cost[0] == "diamonds" else "no_money")
    A(uid, cost[0], -cost[1])
    if a == "ball": A(uid, "points", 1000)
    if a == "prot": S(uid, hprot=MAXH[lvl(u["points"]) - 1])
    if a == "charge": S(uid, charge=10)
    return dict(ok=1)


def mk_row(x, uid):
    L_ = lvl(x["points"])
    return dict(id=x["id"], name=x["name"], lvl=L_, pts=x["points"], prot=x["hprot"], maxp=MAXH[L_ - 1], charge=x["charge"], price=x["price"],
                seller=(db.execute("SELECT name FROM users WHERE id=?", (x["uid"],)).fetchone() or {"name": "?"})["name"], mine=x["uid"] == uid)


@api("market")
def a_market(u, b, tu):
    rows = db.execute("SELECT * FROM market ORDER BY id DESC LIMIT 50").fetchall()
    return dict(rows=[mk_row(x, u["id"]) for x in rows])


@api("msell")
def a_msell(u, b, tu):
    uid = u["id"]
    if not u["has_hero"]: raise ApiErr("no_hero")
    if db.execute("SELECT 1 FROM market WHERE uid=?", (uid,)).fetchone(): raise ApiErr("have_ad")
    price = iv(b.get("price"), 1, 1_000_000)
    db.execute("INSERT INTO market(uid,name,points,hprot,charge,price,ts) VALUES(?,?,?,?,?,?,?)",
               (uid, u["hname"], u["points"], u["hprot"], u["charge"], price, int(time.time())))
    db.commit(); hero_remove_active(uid); return dict(ok=1)


@api("mcancel")
def a_mcancel(u, b, tu):
    uid = u["id"]; row = db.execute("SELECT * FROM market WHERE uid=?", (uid,)).fetchone()
    if not row: raise ApiErr("gone")
    if hcount(uid) >= hlim(uid): raise ApiErr("hero_full")
    add_hero(uid, row["name"], row["points"], row["hprot"], row["charge"])
    db.execute("DELETE FROM market WHERE id=?", (row["id"],)); db.commit(); return dict(ok=1)


@api("mbuy")
async def a_mbuy(u, b, tu):
    uid = u["id"]; row = db.execute("SELECT * FROM market WHERE id=?", (int(b.get("id") or 0),)).fetchone()
    if not row: raise ApiErr("gone")
    if row["uid"] == uid: raise ApiErr("self")
    if hcount(uid) >= hlim(uid): raise ApiErr("hero_full")
    if u["diamonds"] < row["price"]: raise ApiErr("no_dia")
    A(uid, "diamonds", -row["price"]); A(row["uid"], "diamonds", row["price"])
    add_hero(uid, row["name"], row["points"], row["hprot"], row["charge"])
    db.execute("DELETE FROM market WHERE id=?", (row["id"],)); db.commit()
    await pm(row["uid"], f"🏪 Geroyingiz bozorda sotildi! +{row['price']} 💎 ({esc(u['name'])})")
    return dict(ok=1)


# ---- Operator (yordam) va global chat ----
HELP_GREET = ("👋 Assalomu alaykum! Men avtomatik yordamchiman. Narxlar, geroy, VIP, rollar yoki profil almashish haqida savolingiz bo'lsa yozing — "
              "darhol javob beraman. Agar savolingiz boshqa (texnik muammo va h.k.) bo'lsa, adminimiz tez orada javob beradi.")


def helper_answer(text):
    t = text.lower()
    if re.search(r"\b(narx\w*|qancha|price\w*|цен\w*|стоит|сколько)\b", t):
        its = ", ".join(f"{tt(0, 'it_' + k)} {p}{CUR[c_]}" for k, (c_, p) in ITEMS.items() if k != "ncoin")
        vp = ", ".join(f"{n} {p}💎" for n, p in VIPS.values())
        return (f"💰 Narxlar:\n{its}\n🥷 Geroy: 90 💎 yoki 300 ⭐️\n⭐️ VIP (30 kun): {vp}\n"
                f"📅 Guruh obunasi: 1 oy — {SUB_M} 💎, 1 yil — {SUB_Y} 💎")
    if re.search(r"\b(geroy\w*|hero\w*|герой\w*)\b", t):
        return ("🥷 Geroy: Geroy bo'limidan sotib olasiz (90 💎 yoki 300 ⭐️). Tunda hujum yoki himoya qilasiz, o'yinlarda ball to'plab "
                "38 darajagacha ko'tarilasiz. Keraksiz geroyni «Savdo» bo'limida sotishingiz mumkin.")
    if re.search(r"\bvip\w*\b", t):
        return ("⭐️ VIP: komissiyasiz o'tkazma, tunda guruhda yozish, ko'proq para/geroy slotlari va /boost (guruhga 1 oylik obuna). "
                "Narxlar: Plus 30 💎, Pro 60 💎, Ultra 90 💎, Promax 150 💎 (30 kun). Menyu → VIP bo'limida.")
    if re.search(r"\b(rol\w*|role\w*|роль|роли)\b", t):
        return ("🎭 Rollar bo'limida barcha rollar va ularning qobiliyatlari bor. Faol rolni Do'kon → Faol rol orqali sotib olasiz — "
                "keyingi o'yinda u 100% tushadi.")
    if re.search(r"(profil\w*\s*almash|almash\w*\s*profil|перенос|switch profile)", t):
        return ("🔄 Profil almashish: botda /start → /profile → «Profil almashish». Narxi 5 💎. Qabul qiluvchi akkaunt yangi (0 o'yin) bo'lishi "
                "va botga /start bosgan bo'lishi kerak.")
    if len(t) < 40 and re.search(r"\b(salom\w*|assalom\w*|nmadr|nimadr|hello|hi|hey|привет\w*|здравствуй\w*|qalay|nima gap)\b", t):
        return HELP_GREET
    return None


def save_img(data_url):
    m_ = re.match(r"^data:image/(?:png|jpe?g|webp|gif);base64,(.+)$", str(data_url or ""), re.S)
    if not m_: raise ApiErr("bad_img")
    try: raw = base64.b64decode(m_.group(1))
    except Exception: raise ApiErr("bad_img")
    if len(raw) > 5 * 1024 * 1024: raise ApiErr("big_img")
    sig = raw[:12]
    if sig.startswith(b"\x89PNG"): ext = "png"
    elif sig.startswith(b"\xff\xd8"): ext = "jpg"
    elif sig[:4] == b"RIFF" and sig[8:12] == b"WEBP": ext = "webp"
    elif sig[:4] == b"GIF8": ext = "gif"
    else: raise ApiErr("bad_img")
    name = uuid.uuid4().hex + "." + ext
    with open(os.path.join(UP, name), "wb") as f: f.write(raw)
    return name


def sup_list(uid, after=0):
    rows = db.execute("SELECT id,role,text,img,ts FROM support WHERE uid=? AND id>? ORDER BY id LIMIT 100", (uid, after)).fetchall()
    return [dict(id=x["id"], role=x["role"], text=x["text"], img=("/uploads/" + x["img"]) if x["img"] else "", ts=x["ts"]) for x in rows]


@api("sup_get")
def a_sup_get(u, b, tu):
    return dict(msgs=sup_list(u["id"], int(b.get("after") or 0)))


async def fwd_admin(u, text, fname):
    head = f"🆘 <b>Operator</b>\n👤 {esc(u['name'])} (<code>{u['id']}</code>)" + (f" @{esc(u['username'])}" if u["username"] else "")
    for a in ADMIN_IDS:
        try:
            if fname:
                m_ = await bot.send_photo(a, FSInputFile(os.path.join(UP, fname)), caption=head + ("\n\n" + esc(text[:700]) if text else ""))
            else:
                m_ = await bot.send_message(a, head + "\n\n" + esc(text) + "\n\n↩️ Javob berish uchun shu xabarga reply qiling.")
            db.execute("INSERT OR REPLACE INTO support_map(chat,mid,uid) VALUES(?,?,?)", (a, m_.message_id, u["id"])); db.commit()
        except Exception: pass


@api("sup_send")
async def a_sup_send(u, b, tu):
    uid = u["id"]; text = str(b.get("text") or "").strip()[:1000]; img = b.get("img")
    if not text and not img: raise ApiErr("empty")
    now = time.time()
    if now - SUP_LAST.get(uid, 0) < 1.5: raise ApiErr("slow")
    SUP_LAST[uid] = now
    fname = save_img(img) if img else ""
    db.execute("INSERT INTO support(uid,role,text,img,ts) VALUES(?,?,?,?,?)", (uid, "u", text, fname, int(now))); db.commit()
    ans = None if fname else helper_answer(text)
    if ans:
        db.execute("INSERT INTO support(uid,role,text,img,ts) VALUES(?,?,?,?,?)", (uid, "b", ans, "", int(now))); db.commit()
    else:
        await fwd_admin(u, text, fname)
        if not fname or text:
            db.execute("INSERT INTO support(uid,role,text,img,ts) VALUES(?,?,?,?,?)",
                       (uid, "b", "✅ Xabaringiz operatorga yuborildi. Admin tez orada javob beradi.", "", int(now))); db.commit()
    return dict(msgs=sup_list(uid, int(b.get("after") or 0)))


@api("gc_get")
def a_gc_get(u, b, tu):
    after = int(b.get("after") or 0)
    rows = db.execute("SELECT g.id,g.uid,g.text,g.ts,u.name,u.vip,u.vip_until FROM gchat g LEFT JOIN users u ON u.id=g.uid "
                      "WHERE g.id>? ORDER BY g.id DESC LIMIT 60", (after,)).fetchall()
    rows = list(reversed(rows))
    return dict(msgs=[dict(id=x["id"], me=x["uid"] == u["id"], name=x["name"] or "?", text=x["text"], ts=x["ts"],
                           vip=(VIPS[x["vip"]][0].split()[0] if x["vip"] and (x["vip_until"] or 0) > time.time() else "")) for x in rows])


@api("gc_send")
def a_gc_send(u, b, tu):
    text = str(b.get("text") or "").strip()[:300]
    if not text: raise ApiErr("empty")
    now = time.time()
    if now - GC_LAST.get(u["id"], 0) < 2: raise ApiErr("slow")
    GC_LAST[u["id"]] = now
    db.execute("INSERT INTO gchat(uid,text,ts) VALUES(?,?,?)", (u["id"], text, int(now)))
    db.execute("DELETE FROM gchat WHERE id < (SELECT MAX(id) FROM gchat) - 2000"); db.commit()
    return a_gc_get(u, {"after": int(b.get("after") or 0)}, tu)


async def web_app_page(req):
    return web.Response(text=APP_HTML, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-store"})


async def web_upload(req):
    name = req.match_info["name"]
    if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|webp|gif)", name): return web.Response(status=404)
    p = os.path.join(UP, name)
    if not os.path.isfile(p): return web.Response(status=404)
    return web.FileResponse(p, headers={"Cache-Control": "private, max-age=86400"})


async def web_root(req): return web.Response(text="Night Mafia ✅")


async def start_web():
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.router.add_get("/", web_root)
    app.router.add_get("/app", web_app_page)
    app.router.add_post("/api/{name}", api_handler)
    app.router.add_get("/uploads/{name}", web_upload)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    logging.info("Web App: %s/app", WEB_URL)


APP_HTML = r'''<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Night Mafia</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{--a:#7c6cff;--a2:#38bdf8;--b1:#0b0a1c;--b2:#1d1552;--gl:rgba(124,108,255,.38);--tx:#f3f1ff;--mu:#a9a4cc;--cd:rgba(255,255,255,.065);--bd:rgba(255,255,255,.13);--ok:#34d399;--er:#fb7185}
[data-theme=green]{--a:#22c55e;--a2:#86efac;--b1:#05120b;--b2:#0e3a22;--gl:rgba(34,197,94,.34)}
[data-theme=gold]{--a:#fbbf24;--a2:#f59e0b;--b1:#100b03;--b2:#33240a;--gl:rgba(251,191,36,.33)}
[data-theme=pink]{--a:#ec4899;--a2:#f9a8d4;--b1:#16060f;--b2:#3d1030;--gl:rgba(236,72,153,.34)}
[data-theme=blue]{--a:#3b82f6;--a2:#93c5fd;--b1:#050b1d;--b2:#10265c;--gl:rgba(59,130,246,.36)}
[data-theme=purple]{--a:#a855f7;--a2:#d8b4fe;--b1:#0f061c;--b2:#2e1158;--gl:rgba(168,85,247,.36)}
[data-theme=ruby]{--a:#ef4444;--a2:#fca5a5;--b1:#160606;--b2:#471215;--gl:rgba(239,68,68,.34)}
[data-theme=teal]{--a:#14b8a6;--a2:#5eead4;--b1:#031211;--b2:#0b3b36;--gl:rgba(20,184,166,.34)}
[data-theme=platinum]{--a:#e2e8f0;--a2:#94a3b8;--b1:#0c0e11;--b2:#272c34;--gl:rgba(203,213,225,.28)}
html,body{margin:0;min-height:100%;color:var(--tx);font:15px/1.45 -apple-system,"Segoe UI",Roboto,"Noto Sans",Arial,sans-serif;background:var(--b1)}
body{background:radial-gradient(900px 560px at 12% -8%,var(--b2),transparent 72%),radial-gradient(700px 520px at 105% 38%,var(--gl),transparent 70%),var(--b1);background-attachment:fixed;transition:background .4s}
button,input{font:inherit;color:inherit}button{cursor:pointer;border:0;background:none}
.wrap{max-width:520px;margin:0 auto;padding:14px 14px 150px}
.card{background:var(--cd);border:1px solid var(--bd);border-radius:20px;padding:16px;margin-bottom:14px;backdrop-filter:blur(10px);transition:transform .2s,border-color .2s,box-shadow .2s}
.card:hover{border-color:var(--a);box-shadow:0 8px 30px var(--gl)}
h2{margin:0 0 4px;font-size:25px;letter-spacing:-.3px}h3{margin:0 0 12px;font-size:16px}h4{margin:18px 2px 8px;font-size:13px;color:var(--a2);letter-spacing:.4px}
.mu{color:var(--mu);margin:0 0 6px;font-size:13px}small{display:block;color:var(--mu);font-size:12px}
.pc{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:center}
.av{position:relative;width:68px;height:68px;border-radius:50%;padding:3px;background:linear-gradient(135deg,var(--a),var(--a2));display:grid;place-items:center}
.av>span,.av>img{width:100%;height:100%;border-radius:50%;object-fit:cover;background:#05050c;display:grid;place-items:center;font-size:26px;font-weight:700}
.av>img{position:absolute;inset:3px;width:calc(100% - 6px);height:calc(100% - 6px)}
.nm{font-size:19px;font-weight:700;word-break:break-word}.un{color:var(--mu);font-size:13px}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.bd{padding:3px 10px;border-radius:999px;border:1px solid var(--bd);background:rgba(255,255,255,.07);font-size:12px;font-weight:600}
.bd.vip{background:linear-gradient(135deg,var(--a2),var(--a));color:#10101a;border:0}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;grid-column:1/-1}
.chip{display:inline-flex;align-items:center;gap:6px;padding:8px 13px;border-radius:999px;background:rgba(255,255,255,.07);border:1px solid var(--bd);font-weight:700;transition:.18s}
button.chip:hover,.chip:hover{border-color:var(--a);background:var(--gl);transform:translateY(-2px)}
.chip.gold{border-color:var(--a);color:var(--a2)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{display:block;text-align:left;padding:16px;border-radius:20px;min-height:112px;border:1px solid var(--bd);background:linear-gradient(150deg,var(--gl),rgba(255,255,255,.04));transition:.2s}
.tile:hover{transform:translateY(-4px);border-color:var(--a);box-shadow:0 12px 30px var(--gl)}.tile i{font-style:normal;font-size:28px;display:block;margin-bottom:8px}.tile b{display:block;font-size:16px}
.st{display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px;padding:16px 8px}.st i{font-style:normal;width:42px;height:42px;display:grid;place-items:center;border-radius:50%;background:var(--gl);font-size:20px}.st b{font-size:24px}.st small{text-transform:none}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between;margin-top:10px}.row>div{min-width:0}
.btn{padding:11px 16px;border-radius:14px;font-weight:700;background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18;transition:.18s;border:0}
.btn:hover{transform:translateY(-2px);box-shadow:0 8px 22px var(--gl);filter:brightness(1.08)}.btn:active{transform:scale(.97)}
.btn.alt{background:rgba(255,255,255,.09);color:var(--tx);border:1px solid var(--bd)}.btn.alt:hover{border-color:var(--a)}
.btn.wide{width:100%;margin-top:10px}.btn.sm{padding:8px 12px;font-size:13px}.btn.dng{background:rgba(251,113,133,.18);color:var(--er);border:1px solid var(--er)}
.inp{width:100%;padding:13px 14px;border-radius:14px;border:1px solid var(--bd);background:rgba(0,0,0,.28);outline:none;transition:.18s}
.inp:focus{border-color:var(--a);box-shadow:0 0 0 3px var(--gl)}
.pill{padding:9px 14px;border-radius:999px;border:1px solid var(--bd);background:rgba(255,255,255,.06);font-weight:600;margin:0 6px 8px 0;transition:.18s}
.pill:hover{border-color:var(--a);transform:translateY(-1px)}.pill.on{background:var(--gl);border-color:var(--a);color:var(--a2);box-shadow:0 0 0 1px var(--a) inset}
.lbl{display:block;margin:14px 0 8px;font-weight:700;color:var(--mu);font-size:13px}
.it small{max-width:210px}
.role{position:relative;display:flex;align-items:center;gap:8px;text-align:left;padding:13px;border-radius:16px;border:1px solid var(--bd);background:var(--cd);transition:.18s;min-height:54px}
.role:hover{transform:translateY(-3px);border-color:var(--a);box-shadow:0 10px 24px var(--gl)}.role span{font-size:20px}.role b{font-size:14px}
.role em,.nw{position:absolute;top:-7px;right:8px;background:var(--ok);color:#052e1d;font-style:normal;font-size:10px;font-weight:800;padding:2px 8px;border-radius:999px}
.nw{position:static;margin-left:8px}
.rh{display:flex;align-items:center;margin-bottom:10px;font-size:20px}
.ab{display:flex;gap:12px;padding:13px;border-radius:16px;border:1px solid var(--bd);background:rgba(0,0,0,.22);margin-top:10px;transition:.18s}.ab:hover{border-color:var(--a);transform:translateX(3px)}
.ab i{font-style:normal;flex:none;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:var(--gl)}.ab b{color:var(--a2)}
.li{padding:12px 14px;border-radius:14px;border:1px solid var(--bd);background:var(--cd);margin-bottom:8px;transition:.18s}.li:hover{border-color:var(--a);transform:translateX(3px)}
.li.me{border-color:var(--a);background:var(--gl)}.li .r{float:right;font-weight:700}.up{color:var(--ok)}.dn{color:var(--er)}
.tabs2{display:flex;gap:8px}.tabs2 button{flex:1;padding:11px;border-radius:14px;border:1px solid var(--bd);background:var(--cd);font-weight:700;transition:.18s}
.tabs2 button:hover{border-color:var(--a)}.tabs2 button.on{background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18;border:0}
.sw{width:48px;height:28px;border-radius:999px;background:rgba(255,255,255,.15);position:relative;transition:.2s;flex:none}.sw:after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:.2s}
.sw.on{background:var(--a)}.sw.on:after{left:23px}
.hh{display:flex;gap:14px;align-items:center}.big{font-size:46px}.stats3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:14px 0}.stats3 div{padding:10px;border-radius:14px;background:rgba(0,0,0,.25);text-align:center;font-weight:700}
.bar{height:8px;border-radius:99px;background:rgba(255,255,255,.12);overflow:hidden;margin-top:6px}.bar>div{height:100%;background:linear-gradient(90deg,var(--a),var(--a2))}
.mk{display:flex;gap:12px;align-items:center}.mk .big{font-size:38px}
.plus{position:fixed;right:18px;bottom:162px;width:52px;height:52px;border-radius:50%;font-size:28px;background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18;box-shadow:0 8px 24px var(--gl);transition:.2s;z-index:6}.plus:hover{transform:scale(1.1) rotate(90deg)}
.nav{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(10px + env(safe-area-inset-bottom,0px));width:min(500px,calc(100% - 20px));display:flex;gap:4px;padding:8px;border-radius:26px;background:rgba(14,12,30,.82);border:1px solid var(--bd);backdrop-filter:blur(16px);z-index:5}
.nav button{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:7px 2px;border-radius:18px;transition:.18s;color:var(--mu)}
.nav button i{font-style:normal;font-size:20px}.nav button b{font-size:11px}.nav button:hover{background:var(--cd);color:var(--tx);transform:translateY(-2px)}
.nav button.on{background:var(--gl);color:var(--a2);box-shadow:0 0 0 1px var(--a) inset}.nav .mn.on,.nav .mn:hover{background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18}
.fab{position:fixed;right:16px;bottom:92px;width:54px;height:54px;border-radius:50%;font-size:24px;background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18;box-shadow:0 8px 26px var(--gl);z-index:5;transition:.2s}.fab:hover{transform:scale(1.1)}
#ov .back{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:20;animation:fd .2s}
.panel{position:fixed;z-index:21;background:var(--b1);border:1px solid var(--bd);animation:up .25s}
.sheet{left:0;right:0;bottom:0;max-width:520px;margin:0 auto;border-radius:26px 26px 0 0;padding:18px 16px calc(22px + env(safe-area-inset-bottom,0px));max-height:85vh;overflow:auto;background:linear-gradient(180deg,var(--b2),var(--b1))}
.drawer{left:0;top:0;bottom:0;width:min(330px,86vw);padding:18px 14px;border-radius:0 26px 26px 0;overflow:auto;animation:sl .25s;background:linear-gradient(180deg,var(--b2),var(--b1))}
.dm{display:flex;align-items:center;gap:14px;width:100%;padding:12px;border-radius:16px;text-align:left;font-weight:700;transition:.18s}.dm:hover{background:var(--gl);transform:translateX(4px)}.dm i{font-style:normal;width:40px;height:40px;display:grid;place-items:center;border-radius:12px;background:var(--cd);border:1px solid var(--bd)}
.sup{left:50%;top:max(12px,env(safe-area-inset-top,0px));bottom:12px;width:min(500px,calc(100% - 20px));transform:translateX(-50%);border-radius:24px;display:flex;flex-direction:column;animation:fd .2s}
.ph{display:flex;gap:10px;align-items:center;padding:12px}.x{width:38px;height:38px;border-radius:50%;background:var(--cd);border:1px solid var(--bd);transition:.18s}.x:hover{background:var(--er);color:#fff}
.msgs{flex:1;overflow:auto;padding:6px 12px;display:flex;flex-direction:column;gap:8px}
.bb{max-width:82%;padding:10px 12px;border-radius:16px;background:var(--cd);border:1px solid var(--bd);white-space:pre-wrap;word-break:break-word}.bb img{max-width:100%;border-radius:12px;display:block;margin-top:6px}
.bb.me{align-self:flex-end;background:linear-gradient(135deg,var(--a),var(--a2));color:#0c0c18;border:0}.bb small{margin-bottom:3px;font-weight:700;color:var(--a2)}.bb.me small{color:#1c1c30}
.pf{padding:10px 12px calc(12px + env(safe-area-inset-bottom,0px));border-top:1px solid var(--bd)}.pi{display:flex;gap:8px;align-items:center}.att{width:44px;height:44px;border-radius:14px;background:var(--cd);border:1px solid var(--bd);display:grid;place-items:center;cursor:pointer;flex:none;transition:.18s}.att:hover{border-color:var(--a)}
.pv{display:inline-flex;align-items:center;gap:8px;margin-bottom:8px;padding:6px 10px;border-radius:12px;background:var(--cd);border:1px solid var(--bd);font-size:13px}
.th{display:grid;grid-template-columns:repeat(4,1fr);gap:14px 8px;margin-top:14px}.th button{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:12px;font-weight:600;transition:.18s}.th button:hover{transform:translateY(-3px)}
.th span{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;font-size:24px;color:#fff;border:2px solid transparent;box-shadow:inset 0 -6px 12px rgba(0,0,0,.25)}.th .on span{border-color:#fff;box-shadow:0 0 0 3px var(--a)}
.lg{display:flex;align-items:center;gap:12px;width:100%;padding:12px;border-radius:14px;border:1px solid var(--bd);background:var(--cd);margin-bottom:8px;font-weight:600;transition:.18s}.lg:hover{border-color:var(--a);transform:translateX(3px)}.lg.on{background:var(--gl);border-color:var(--a)}
#toast{position:fixed;left:50%;top:18px;transform:translate(-50%,-90px);padding:12px 18px;border-radius:14px;background:#14121f;border:1px solid var(--bd);z-index:50;transition:.3s;max-width:90%;text-align:center;font-weight:600}
#toast.s{transform:translate(-50%,0)}#toast.ok{border-color:var(--ok)}#toast.er{border-color:var(--er)}
.sk{height:90px;background:linear-gradient(90deg,var(--cd),rgba(255,255,255,.12),var(--cd));background-size:200% 100%;animation:sh 1.2s infinite}
@keyframes sh{to{background-position:-200% 0}}@keyframes up{from{transform:translateY(40px);opacity:0}}@keyframes fd{from{opacity:0}}@keyframes sl{from{transform:translateX(-40px);opacity:0}}
.sup.panel{animation:fd .2s}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
[dir=rtl] .row,[dir=rtl] .pc{direction:rtl}
</style></head>
<body data-theme="cyber"><div id="app"></div><div id="ov"></div><div id="toast"></div>
<script>
"use strict";
const tg=window.Telegram&&window.Telegram.WebApp;
if(tg){try{tg.ready();tg.expand();if(tg.disableVerticalSwipes)tg.disableVerticalSwipes();}catch(e){}}
const INIT=tg?tg.initData:"";
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmt=n=>Number(n||0).toLocaleString("en-US");
const THEMES={cyber:["#7c6cff","#38bdf8"],green:["#22c55e","#86efac"],gold:["#fbbf24","#f59e0b"],pink:["#ec4899","#f9a8d4"],blue:["#3b82f6","#93c5fd"],purple:["#a855f7","#d8b4fe"],ruby:["#ef4444","#fca5a5"],teal:["#14b8a6","#5eead4"],platinum:["#e2e8f0","#94a3b8"]};
const LANGS=[["uz","🇺🇿","O'zbekcha"],["ru","🇷🇺","Русский"],["en","🇺🇸","English"],["ar","🇸🇦","العربية"],["id","🇮🇩","Indonesia"],["kk","🇰🇿","Қазақша"],["tr","🇹🇷","Türkçe"],["ko","🇰🇷","한국어"],["es","🇪🇸","Español"],["pt","🇧🇷","Português"],["fr","🇫🇷","Français"],["hi","🇮🇳","हिन्दी"],["ur","🇵🇰","اردو"]];
const ITM={himoya:"🛡",hujjat:"📁",osish:"⚖️",geroyd:"🔰",ncoin:"💠"};
const L={
uz:{home:"Asosiy",roles:"Rollar",shop:"Do'kon",transfer:"O'tkazma",menu:"Menyu",home_t:"Bosh sahifa",ov:"Profilingiz haqida umumiy ko'rinish",love:"Sevgi galaktikasi",love_s:"Barcha juftlar osmoni",shop_s:"Himoya · rol · geroy",hero_c:"Geroy",hero_s:"To'plam · savdo",roles_s:"Rollar va qobiliyatlar",
own:"Nimalarga egasiz",novip:"VIP yo'q",games:"Jami o'yinlar",wins:"G'alabalar",losses:"Mag'lubiyatlar",wr:"G'alaba foizi",srv:"Server holati",agames:"Faol o'yinlar",users:"Foydalanuvchilar",vipt:"VIP maqom",vipd:"Maxsus imkoniyatlar va emoji uchun VIP oling",via:"orqali",days:"kun",
roles_t:"O'yin rollari",roles_ss:"Barcha rollar va ularning qobiliyatlari",search:"Rol nomini qidirish...",g_maf:"MAFIYA GURUHI",g_city:"SHAHAR GURUHI",g_solo:"YAKKA O'YINCHILAR",team:"Jamoa",night:"Tun harakati",noact:"Yo'q (faqat kunduzi ovoz)",t_maf:"Mafiya",t_city:"Shahar",t_solo:"Yakka",you:"Siz",new:"YANGI",
shop_t:"Do'kon",buy:"Sotib olish",price:"Narxi",it_himoya:"Himoya",it_hujjat:"Hujjat",it_osish:"Osishdan himoya",it_geroyd:"Geroydan himoya",it_ncoin:"NightCoin",d_himoya:"Bir marta hayotingizni saqlab qoladi.",d_hujjat:"Rolingizni tekshirishsa, soxta hujjat yordam beradi.",d_osish:"Osishga hukm qilinsangiz, bir marta qutqaradi.",d_geroyd:"Geroy hujumidan omon qolasiz.",d_ncoin:"Tez orada ishga tushadigan market valyutasi.",
ar_t:"Faol rollar",ar_d:"Faol rol keyingi o'yinda 100% tushadi (maks. {n} ta).",ar_del:"Faol rollarni o'chirish — 100 $",hero_b:"Geroy sotib olish",
tr_t:"O'tkazma",to:"Kimga",uname:"Username",tgid:"Telegram ID",pair:"Param",what:"Nima",dollar:"Dollar",dia:"Olmos",inv:"Inventar",amount:"Miqdor",amount_ph:"Masalan: 100",fee:"Komissiya",do_tr:"O'tkazish",item:"Buyum",un_ph:"@username",id_ph:"Telegram ID",pair_h:"Param: miqdorni yozing — para bo'lgan odamingizga o'tadi.",ok_tr:"Yuborildi!",
his:"O'tkazmalar tarixi",mine:"Mening",all:"Hammasi",sent:"yubordi",got:"oldi",none:"Hozircha yo'q",rate:"Reyting",d1:"Kunlik",d7:"Haftalik",d30:"Oylik",dall:"Barchasi",ball:"ball",
inv_t:"Shaxsiy inventar",inv_s:"Sotib olingan faol rollar va anjomlaringiz",no_ar:"Faol rol yo'q",items:"Anjomlar",cnt:"ta",sh_t:"Himoyalar",sh_s:"O'yin ichida avtomatik ishlaydigan himoyalarni boshqaring",on:"Yoqilgan",off:"O'chirilgan",
her_t:"Geroy",her_s:"Shaxsiy Geroyingizni sotib oling va boshqaring",my_h:"Geroyim",mkt:"Savdo",no_h:"Sizda hali Geroy yo'q",no_h_s:"Shaxsiy Geroy sotib olib, jangda ishlatishingiz mumkin",lvl:"Daraja",pwr:"Kuch",prot:"Himoya",chg:"Zaryad",pts:"Ball",nxt:"Keyingi daraja",a_ball:"+1000 ball",a_prot:"Himoyani yangilash",a_chg:"Qurolni o'qlash",a_name:"Nomini o'zgartirish",name_ph:"Yangi nom",bozor:"Bozor",my_ad:"Mening e'lonim",seller:"Sotuvchi",cancel:"Sotuvdan olish",sell:"Sotuvga qo'yish",price_ph:"Narx (olmos)",no_h_sell:"Sizda hali Geroy yo'q — sotuvga qo'yish uchun avval Geroy bo'limidan sotib oling",empty_m:"Hozircha e'lonlar yo'q",no_ad:"Sizda e'lon yo'q",save:"Saqlash",
sup:"Yordam",gchat:"Global chat",sup_in:"🆘 Savolingiz bormi? Shu yerga yozing — operator sizga o'z tilingizda javob beradi.",msg_ph:"Xabar yozing...",send:"Yuborish",op:"Operator",bot_h:"Yordamchi",gc_in:"Hamma bilan umumiy suhbat. Odob bilan yozing.",
theme:"Mavzu",lang:"Til",back:"Orqaga",loading:"Yuklanmoqda...",sky:"Barcha juftlar osmoni",my_pairs:"Mening juftlarim",no_pairs:"Hozircha juftlar yo'q — guruhda /para yozing",r0:"Fuqaro",r1:"Tajribali",r2:"Usta",r3:"Ekspert",r4:"Afsona",
th_cyber:"Cyber",th_green:"Yashil",th_gold:"Oltin",th_pink:"Pushti",th_blue:"Zangori",th_purple:"Binafsha",th_ruby:"Yoqut",th_teal:"Turkuaz",th_platinum:"Platina",ok:"Bajarildi!",
e_no_money:"Pul yetarli emas",e_no_dia:"Olmos yetarli emas",e_no_user:"Foydalanuvchi topilmadi (u botga /start bosgan bo'lishi kerak)",e_no_pair:"Sizda para yo'q",e_bad_amount:"Miqdor noto'g'ri",e_self:"O'zingizga o'tkaza olmaysiz",e_net:"Tarmoq xatosi",e_auth:"Shaxsiy kabinetni Telegram ichida oching",e_hero_full:"Geroy sloti to'lgan",e_no_item:"Buyum yetarli emas",e_no_hero:"Sizda geroy yo'q",e_have_ad:"Sizda faol e'lon bor",e_slow:"Sekinroq yozing",e_bad_img:"Rasm noto'g'ri",e_big_img:"Rasm juda katta (5 MB gacha)",e_empty:"Bo'sh",e_blocked:"Akkaunt bloklangan",e_server:"Server xatosi",e_gone:"Topilmadi",e_no_ar:"Faol rol yo'q",e_ar_max:"Faol rollar limiti to'lgan",e_bad:"Xato so'rov",e_nf:"Topilmadi"},
ru:{home:"Главная",roles:"Роли",shop:"Магазин",transfer:"Перевод",menu:"Меню",home_t:"Главная страница",ov:"Общий обзор вашего профиля",love:"Галактика любви",love_s:"Небо всех пар",shop_s:"Защита · роли · герой",hero_c:"Герой",hero_s:"Коллекция · торговля",roles_s:"Роли и способности",
own:"Что у вас есть",novip:"Нет VIP",games:"Всего игр",wins:"Победы",losses:"Поражения",wr:"Процент побед",srv:"Состояние сервера",agames:"Активные игры",users:"Пользователи",vipt:"VIP статус",vipd:"Получите VIP для особых возможностей и эмодзи",via:"за",days:"дн.",
roles_t:"Роли игры",roles_ss:"Все роли и их способности",search:"Поиск роли...",g_maf:"ГРУППА МАФИИ",g_city:"ГОРОД",g_solo:"ОДИНОЧКИ",team:"Команда",night:"Ночное действие",noact:"Нет (только дневное голосование)",t_maf:"Мафия",t_city:"Город",t_solo:"Одиночка",you:"Вы",new:"НОВОЕ",
shop_t:"Магазин",buy:"Купить",price:"Цена",it_himoya:"Защита",it_hujjat:"Документ",it_osish:"Защита от повешения",it_geroyd:"Защита от героя",it_ncoin:"NightCoin",d_himoya:"Один раз спасёт вам жизнь.",d_hujjat:"Поддельный документ поможет при проверке роли.",d_osish:"Спасёт один раз при приговоре к повешению.",d_geroyd:"Позволяет пережить атаку героя.",d_ncoin:"Валюта будущего маркета.",
ar_t:"Активные роли",ar_d:"Активная роль выпадет на 100% в следующей игре (макс. {n}).",ar_del:"Удалить активные роли — 100 $",hero_b:"Купить героя",
tr_t:"Перевод",to:"Кому",uname:"Username",tgid:"Telegram ID",pair:"Пара",what:"Что",dollar:"Доллар",dia:"Алмазы",inv:"Инвентарь",amount:"Количество",amount_ph:"Например: 100",fee:"Комиссия",do_tr:"Перевести",item:"Предмет",un_ph:"@username",id_ph:"Telegram ID",pair_h:"Пара: введите количество — оно уйдёт вашей паре.",ok_tr:"Отправлено!",
his:"История переводов",mine:"Мои",all:"Все",sent:"отправил",got:"получил",none:"Пока пусто",rate:"Рейтинг",d1:"День",d7:"Неделя",d30:"Месяц",dall:"Всё время",ball:"очков",
inv_t:"Личный инвентарь",inv_s:"Купленные активные роли и предметы",no_ar:"Нет активных ролей",items:"Предметы",cnt:"шт.",sh_t:"Защиты",sh_s:"Управляйте защитами, работающими автоматически в игре",on:"Включено",off:"Выключено",
her_t:"Герой",her_s:"Купите и развивайте личного Героя",my_h:"Мой герой",mkt:"Торговля",no_h:"У вас ещё нет Героя",no_h_s:"Купите личного Героя и используйте его в бою",lvl:"Уровень",pwr:"Сила",prot:"Защита",chg:"Заряд",pts:"Очки",nxt:"Следующий уровень",a_ball:"+1000 очков",a_prot:"Обновить защиту",a_chg:"Зарядить оружие",a_name:"Сменить имя",name_ph:"Новое имя",bozor:"Рынок",my_ad:"Моё объявление",seller:"Продавец",cancel:"Снять с продажи",sell:"Выставить на продажу",price_ph:"Цена (алмазы)",no_h_sell:"У вас ещё нет Героя — сначала купите его в разделе Герой",empty_m:"Объявлений пока нет",no_ad:"У вас нет объявления",save:"Сохранить",
sup:"Помощь",gchat:"Общий чат",sup_in:"🆘 Есть вопрос? Пишите сюда — оператор ответит на вашем языке.",msg_ph:"Напишите сообщение...",send:"Отправить",op:"Оператор",bot_h:"Помощник",gc_in:"Общий чат со всеми. Пишите вежливо.",
theme:"Тема",lang:"Язык",back:"Назад",loading:"Загрузка...",sky:"Небо всех пар",my_pairs:"Мои пары",no_pairs:"Пар пока нет — используйте /para в группе",r0:"Горожанин",r1:"Опытный",r2:"Мастер",r3:"Эксперт",r4:"Легенда",
th_cyber:"Cyber",th_green:"Зелёный",th_gold:"Золотой",th_pink:"Розовый",th_blue:"Синий",th_purple:"Фиолетовый",th_ruby:"Рубин",th_teal:"Бирюзовый",th_platinum:"Платина",ok:"Готово!",
e_no_money:"Недостаточно денег",e_no_dia:"Недостаточно алмазов",e_no_user:"Пользователь не найден (он должен нажать /start в боте)",e_no_pair:"У вас нет пары",e_bad_amount:"Неверное количество",e_self:"Нельзя перевести себе",e_net:"Ошибка сети",e_auth:"Откройте кабинет внутри Telegram",e_hero_full:"Слоты героев заполнены",e_no_item:"Недостаточно предметов",e_no_hero:"У вас нет героя",e_have_ad:"У вас уже есть объявление",e_slow:"Пишите помедленнее",e_bad_img:"Неверное изображение",e_big_img:"Изображение слишком большое (до 5 МБ)",e_empty:"Пусто",e_blocked:"Аккаунт заблокирован",e_server:"Ошибка сервера",e_gone:"Не найдено",e_no_ar:"Нет активных ролей",e_ar_max:"Лимит активных ролей достигнут",e_bad:"Неверный запрос",e_nf:"Не найдено"},
en:{home:"Home",roles:"Roles",shop:"Shop",transfer:"Transfer",menu:"Menu",home_t:"Home",ov:"A quick look at your profile",love:"Love galaxy",love_s:"Sky of all couples",shop_s:"Shields · roles · hero",hero_c:"Hero",hero_s:"Collection · trade",roles_s:"Roles and abilities",
own:"What you own",novip:"No VIP",games:"Total games",wins:"Wins",losses:"Losses",wr:"Win rate",srv:"Server status",agames:"Active games",users:"Users",vipt:"VIP status",vipd:"Get VIP for special perks and emoji",via:"via",days:"days",
roles_t:"Game roles",roles_ss:"All roles and their abilities",search:"Search a role...",g_maf:"MAFIA GROUP",g_city:"CITY",g_solo:"SOLO PLAYERS",team:"Team",night:"Night action",noact:"None (day vote only)",t_maf:"Mafia",t_city:"City",t_solo:"Solo",you:"You",new:"NEW",
shop_t:"Shop",buy:"Buy",price:"Price",it_himoya:"Shield",it_hujjat:"Document",it_osish:"Hanging protection",it_geroyd:"Hero protection",it_ncoin:"NightCoin",d_himoya:"Saves your life once.",d_hujjat:"A fake document helps if your role is checked.",d_osish:"Saves you once if you're sentenced to hang.",d_geroyd:"Survive a hero attack.",d_ncoin:"Currency of the upcoming market.",
ar_t:"Active roles",ar_d:"An active role is assigned 100% next game (max {n}).",ar_del:"Remove active roles — 100 $",hero_b:"Buy hero",
tr_t:"Transfer",to:"To",uname:"Username",tgid:"Telegram ID",pair:"Pair",what:"What",dollar:"Dollar",dia:"Diamonds",inv:"Inventory",amount:"Amount",amount_ph:"E.g. 100",fee:"Fee",do_tr:"Send",item:"Item",un_ph:"@username",id_ph:"Telegram ID",pair_h:"Pair: enter the amount — it goes to your pair.",ok_tr:"Sent!",
his:"Transfer history",mine:"Mine",all:"All",sent:"sent",got:"received",none:"Nothing yet",rate:"Rating",d1:"Daily",d7:"Weekly",d30:"Monthly",dall:"All time",ball:"pts",
inv_t:"Personal inventory",inv_s:"Your purchased active roles and items",no_ar:"No active roles",items:"Items",cnt:"pcs",sh_t:"Protections",sh_s:"Manage protections that work automatically in game",on:"On",off:"Off",
her_t:"Hero",her_s:"Buy and manage your personal Hero",my_h:"My hero",mkt:"Market",no_h:"You don't have a Hero yet",no_h_s:"Buy a personal Hero and use it in battle",lvl:"Level",pwr:"Power",prot:"Protection",chg:"Charge",pts:"Points",nxt:"Next level",a_ball:"+1000 points",a_prot:"Renew protection",a_chg:"Recharge weapon",a_name:"Rename",name_ph:"New name",bozor:"Bazaar",my_ad:"My listing",seller:"Seller",cancel:"Remove listing",sell:"List for sale",price_ph:"Price (diamonds)",no_h_sell:"You don't have a Hero yet — buy one in the Hero section first",empty_m:"No listings yet",no_ad:"You have no listing",save:"Save",
sup:"Help",gchat:"Global chat",sup_in:"🆘 Have a question? Write here — an operator will reply in your language.",msg_ph:"Write a message...",send:"Send",op:"Operator",bot_h:"Helper",gc_in:"A public chat with everyone. Be polite.",
theme:"Theme",lang:"Language",back:"Back",loading:"Loading...",sky:"Sky of all couples",my_pairs:"My pairs",no_pairs:"No pairs yet — use /para in a group",r0:"Citizen",r1:"Veteran",r2:"Master",r3:"Expert",r4:"Legend",
th_cyber:"Cyber",th_green:"Green",th_gold:"Gold",th_pink:"Pink",th_blue:"Blue",th_purple:"Purple",th_ruby:"Ruby",th_teal:"Teal",th_platinum:"Platinum",ok:"Done!",
e_no_money:"Not enough money",e_no_dia:"Not enough diamonds",e_no_user:"User not found (they must press /start in the bot)",e_no_pair:"You have no pair",e_bad_amount:"Invalid amount",e_self:"You can't send to yourself",e_net:"Network error",e_auth:"Open the cabinet inside Telegram",e_hero_full:"Hero slots are full",e_no_item:"Not enough items",e_no_hero:"You have no hero",e_have_ad:"You already have a listing",e_slow:"Slow down",e_bad_img:"Invalid image",e_big_img:"Image too large (max 5 MB)",e_empty:"Empty",e_blocked:"Account blocked",e_server:"Server error",e_gone:"Not found",e_no_ar:"No active roles",e_ar_max:"Active role limit reached",e_bad:"Bad request",e_nf:"Not found"},
ar:{home:"الرئيسية",roles:"الأدوار",shop:"المتجر",transfer:"تحويل",menu:"القائمة",theme:"السمة",lang:"اللغة",back:"رجوع",his:"سجل التحويلات",rate:"التصنيف",inv_t:"المخزون",her_t:"البطل",sup:"مساعدة",gchat:"الدردشة العامة",send:"إرسال",msg_ph:"اكتب رسالة...",buy:"شراء",loading:"جارٍ التحميل..."},
id:{home:"Beranda",roles:"Peran",shop:"Toko",transfer:"Transfer",menu:"Menu",theme:"Tema",lang:"Bahasa",back:"Kembali",his:"Riwayat transfer",rate:"Peringkat",inv_t:"Inventaris",her_t:"Pahlawan",sup:"Bantuan",gchat:"Obrolan global",send:"Kirim",msg_ph:"Tulis pesan...",buy:"Beli",loading:"Memuat..."},
kk:{home:"Басты",roles:"Рөлдер",shop:"Дүкен",transfer:"Аударым",menu:"Мәзір",theme:"Тақырып",lang:"Тіл",back:"Артқа",his:"Аударымдар тарихы",rate:"Рейтинг",inv_t:"Жеке инвентарь",her_t:"Қаһарман",sup:"Көмек",gchat:"Жалпы чат",send:"Жіберу",msg_ph:"Хабар жазыңыз...",buy:"Сатып алу",loading:"Жүктелуде..."},
tr:{home:"Ana sayfa",roles:"Roller",shop:"Mağaza",transfer:"Transfer",menu:"Menü",theme:"Tema",lang:"Dil",back:"Geri",his:"Transfer geçmişi",rate:"Sıralama",inv_t:"Envanter",her_t:"Kahraman",sup:"Yardım",gchat:"Genel sohbet",send:"Gönder",msg_ph:"Mesaj yazın...",buy:"Satın al",loading:"Yükleniyor..."},
ko:{home:"홈",roles:"역할",shop:"상점",transfer:"전송",menu:"메뉴",theme:"테마",lang:"언어",back:"뒤로",his:"전송 내역",rate:"랭킹",inv_t:"인벤토리",her_t:"영웅",sup:"도움말",gchat:"글로벌 채팅",send:"보내기",msg_ph:"메시지를 입력하세요...",buy:"구매",loading:"불러오는 중..."},
es:{home:"Inicio",roles:"Roles",shop:"Tienda",transfer:"Transferir",menu:"Menú",theme:"Tema",lang:"Idioma",back:"Atrás",his:"Historial de transferencias",rate:"Clasificación",inv_t:"Inventario",her_t:"Héroe",sup:"Ayuda",gchat:"Chat global",send:"Enviar",msg_ph:"Escribe un mensaje...",buy:"Comprar",loading:"Cargando..."},
pt:{home:"Início",roles:"Papéis",shop:"Loja",transfer:"Transferir",menu:"Menu",theme:"Tema",lang:"Idioma",back:"Voltar",his:"Histórico de transferências",rate:"Ranking",inv_t:"Inventário",her_t:"Herói",sup:"Ajuda",gchat:"Chat global",send:"Enviar",msg_ph:"Escreva uma mensagem...",buy:"Comprar",loading:"Carregando..."},
fr:{home:"Accueil",roles:"Rôles",shop:"Boutique",transfer:"Transfert",menu:"Menu",theme:"Thème",lang:"Langue",back:"Retour",his:"Historique des transferts",rate:"Classement",inv_t:"Inventaire",her_t:"Héros",sup:"Aide",gchat:"Chat global",send:"Envoyer",msg_ph:"Écrivez un message...",buy:"Acheter",loading:"Chargement..."},
hi:{home:"होम",roles:"भूमिकाएँ",shop:"दुकान",transfer:"ट्रांसफर",menu:"मेन्यू",theme:"थीम",lang:"भाषा",back:"वापस",his:"ट्रांसफर इतिहास",rate:"रैंकिंग",inv_t:"इन्वेंटरी",her_t:"हीरो",sup:"सहायता",gchat:"ग्लोबल चैट",send:"भेजें",msg_ph:"संदेश लिखें...",buy:"खरीदें",loading:"लोड हो रहा है..."},
ur:{home:"ہوم",roles:"کردار",shop:"دکان",transfer:"منتقلی",menu:"مینو",theme:"تھیم",lang:"زبان",back:"واپس",his:"منتقلی کی تاریخ",rate:"درجہ بندی",inv_t:"انوینٹری",her_t:"ہیرو",sup:"مدد",gchat:"گلوبل چیٹ",send:"بھیجیں",msg_ph:"پیغام لکھیں...",buy:"خریدیں",loading:"لوڈ ہو رہا ہے..."}
};
const S={me:null,page:"home",lang:"uz",d:{},pend:{},q:"",role:null,hs:"me",rd:0,hv:"my",ms:"mkt",tr:{to:"user",kind:"money",item:"himoya",val:"",amt:""},sup:null};
const t=(k,v)=>{let s=(L[S.lang]&&L[S.lang][k])||L.en[k]||L.uz[k]||k;if(v)for(const x in v)s=s.replace("{"+x+"}",v[x]);return s;};
let tt_=0;
function toast(msg,ok){const e=$("#toast");e.textContent=msg;e.className="s "+(ok?"ok":"er");clearTimeout(tt_);tt_=setTimeout(()=>{e.className=""},2600);}
async function api(p,b){let r;try{r=await fetch("/api/"+p,{method:"POST",headers:{"Content-Type":"application/json","X-Init":INIT},body:JSON.stringify(b||{})});}catch(e){throw new Error("net");}
 let j={};try{j=await r.json();}catch(e){throw new Error("server");}
 if(!r.ok||j.error)throw new Error(j.error||"server");return j;}
function err(e){const m=String(e&&e.message||e);const k="e_"+m;const s=t(k);toast(s===k?m:s,false);}
let busy=false;
async function run(fn){if(busy)return;busy=true;try{await fn();}catch(e){err(e);}finally{busy=false;}}
function D(key,path,body){if(S.d[key])return S.d[key];if(!S.pend[key]){S.pend[key]=1;api(path,body||{}).then(r=>{S.d[key]=r;}).catch(e=>{err(e);S.d[key]={err:1};}).finally(()=>{S.pend[key]=0;render(true);});}return null;}
const skel=()=>`<div class="card sk"></div><div class="card sk"></div>`;
const rankOf=w=>w>=150?4:w>=75?3:w>=30?2:w>=10?1:0;
function applyMe(){const m=S.me;document.body.dataset.theme=m.theme;S.lang=m.lang;document.documentElement.dir=(S.lang==="ar"||S.lang==="ur")?"rtl":"ltr";document.documentElement.lang=S.lang;}
async function refresh(){S.me=await api("me");applyMe();}
function go(p){S.page=p;S.drawer=false;closeOv();const keep={roles:S.d.roles,shop:S.d.shop};S.d=keep;S.pend={};render();window.scrollTo(0,0);}
function closeOv(){if(S.sup&&S.sup.timer)clearInterval(S.sup.timer);S.sup=null;$("#ov").innerHTML="";}
function pCard(){const m=S.me,rk=rankOf(m.wins);const ini=esc((m.name||"?").trim().charAt(0).toUpperCase()||"?");
 return `<div class="card pc"><div class="av"><span>${ini}</span>${m.photo?`<img src="${esc(m.photo)}" alt="" onerror="this.remove()">`:""}</div>
 <div><div class="nm">${esc(m.name)}</div><div class="un">${m.username?"@"+esc(m.username):"ID "+m.id}</div>
 <div class="badges"><span class="bd">★ ${t("r"+rk)}</span>${m.vip?`<span class="bd vip">👑 VIP</span>`:""}</div></div>
 <div class="chips"><span class="chip">💰 ${fmt(m.money)}</span><span class="chip">💎 ${fmt(m.dia)}</span><button class="chip" data-a="theme" aria-label="${t("theme")}">🎨</button><button class="chip" data-a="lang" aria-label="${t("lang")}">🌐</button></div></div>`;}
function nav(){const it=[["home","🏠"],["roles","🎭"],["shop","🛍"],["transfer","🔁"]];
 return `<nav class="nav">${it.map(([p,ic])=>`<button data-a="go" data-p="${p}" class="${S.page===p?"on":""}"><i>${ic}</i><b>${t(p)}</b></button>`).join("")}<button data-a="menu" class="mn"><i>☰</i><b>${t("menu")}</b></button></nav>`;}
function pHome(){const m=S.me;const chip=(k,ic)=>`<span class="chip">${ic} ${m.items[k]}</span>`;
 const tile=(p,ic,a,b)=>`<button class="tile" data-a="go" data-p="${p}"><i>${ic}</i><b>${t(a)}</b><small>${t(b)}</small></button>`;
 return `<div class="card"><h2>${t("home_t")}</h2><p class="mu">${t("ov")}</p></div>
 <div class="grid2" style="margin-bottom:14px">${tile("love","💞","love","love_s")}${tile("roles","🎭","roles","roles_s")}${tile("shop","🛍","shop_t","shop_s")}${tile("hero","🥷","hero_c","hero_s")}</div>
 <div class="card"><h3>💼 ${t("own")}</h3><div class="chips" style="margin:0">${chip("himoya","🛡")}${chip("hujjat","📁")}${chip("osish","⚖️")}${chip("geroyd","🔰")}<span class="chip">🃏 ${m.aroles.length}</span><span class="chip ${m.vip?"gold":""}">${m.vip?esc(m.vip_name):t("novip")}</span></div></div>
 <div class="grid2">${[["🎮",m.games,"games"],["🏆",m.wins,"wins"],["💀",m.lost,"losses"],["📈",m.wr+"%","wr"]].map(([i,v,k])=>`<div class="card st"><i>${i}</i><b>${fmt(v)}</b><small>${t(k)}</small></div>`).join("")}</div>
 <div class="card"><h3>🖥 ${t("srv")}</h3><div class="row"><span>🟡 ${t("agames")}</span><b>${fmt(m.srv.games)}</b></div><div class="row"><span>👥 ${t("users")}</span><b>${fmt(m.srv.users)}</b></div></div>
 ${pVip()}`;}
function pVip(){const m=S.me;return `<div class="card"><h3>⚡ ${t("vipt")}</h3>${m.vips.map(v=>`<div class="li"><b>${esc(v.n)} — 30 ${t("days")}</b><small>${t("vipd")}</small><div class="row"><button class="btn sm" data-a="vipd" data-k="${v.k}">💎 ${v.p} ${t("via")}</button><button class="btn sm alt" data-a="vips" data-k="${v.k}">⭐ ${v.st} ${t("via")}</button></div></div>`).join("")}</div>`;}
function pRoles(){const d=D("roles","roles");if(!d)return skel();if(d.err)return `<div class="card">${t("e_net")}</div>`;
 return `<div class="card"><h2>${t("roles_t")}</h2><p class="mu">${t("roles_ss")}</p><input id="rq" class="inp" placeholder="${esc(t("search"))}" value="${esc(S.q)}" autocomplete="off"></div><div id="rl">${rolesList()}</div>`;}
function rolesList(){const d=S.d.roles;if(!d||!d.roles)return "";const q=S.q.trim().toLowerCase();
 return [["maf","g_maf"],["city","g_city"],["solo","g_solo"]].map(([tm,k])=>{const rs=d.roles.filter(r=>r.team===tm&&(!q||r.n.toLowerCase().includes(q)));if(!rs.length)return "";
 return `<h4>${t(k)}</h4><div class="grid2">${rs.map(r=>`<button class="role" data-a="role" data-k="${r.k}"><span>${r.e}</span><b>${esc(r.n)}</b>${r.new?`<em>${t("new")}</em>`:""}</button>`).join("")}</div>`;}).join("");}
function pRole(){const d=S.d.roles;const r=d&&d.roles&&d.roles.find(x=>x.k===S.role);if(!r){S.page="roles";return pRoles();}
 const ab=r.ex.map(x=>[x.i,x.t,x.x]).concat([["👥",t("team"),t("t_"+r.team)],["🌙",t("night"),r.act.length?r.act.map(a=>a.i+" "+a.t).join(", "):t("noact")]]);
 return `<div class="card"><div class="rh"><b>${r.e} ${esc(r.n)}</b>${r.new?`<em class="nw">${t("new")}</em>`:""}</div><p>${t("you")} — ${r.e} ${esc(r.n)}! ${esc(r.d)}</p>${ab.map(x=>`<div class="ab"><i>${x[0]}</i><div><b>${esc(x[1])}</b><div>${esc(x[2])}</div></div></div>`).join("")}</div><button class="btn alt wide" data-a="go" data-p="roles">⬅️ ${t("back")}</button>`;}
function pShop(){const d=D("shop","shop");if(!d)return skel();if(d.err)return `<div class="card">${t("e_net")}</div>`;const cur=c=>(c==="diamonds"||c==="d")?"💎":"$";
 return `<div class="card"><h2>${t("shop_t")}</h2>${d.items.map(i=>`<div class="row it"><div><b>${ITM[i.k]} ${t("it_"+i.k)}</b><small>${t("d_"+i.k)}</small></div><button class="btn sm" data-a="buy" data-k="${i.k}">${fmt(i.p)} ${cur(i.cur)}</button></div>`).join("")}
 <div class="row it"><div><b>🥷 ${t("hero_b")}</b></div><button class="btn sm" data-a="buy" data-k="hero">90 💎</button></div></div>
 <div class="card"><h3>🃏 ${t("ar_t")}</h3><p class="mu">${t("ar_d",{n:d.amax})}</p><div class="grid2">${d.aroles.map(a=>`<button class="role" data-a="arole" data-k="${a.k}"><span>${a.e}</span><div><b>${esc(a.n)}</b><small>${a.p} ${cur(a.cur)}</small></div></button>`).join("")}</div><button class="btn dng wide" data-a="arole" data-k="del">${t("ar_del")}</button></div>`;}
function pTransfer(){const m=S.me,tr=S.tr;const pill=(g,v,l)=>`<button class="pill ${tr[g]===v?"on":""}" data-a="trs" data-g="${g}" data-v="${v}">${l}</button>`;
 const fee=tr.kind==="diamonds"?(m.fee.dia?m.fee.dia+"%":"0"):((tr.kind==="money"?m.fee.money:m.fee.item)+" $");
 return `<div class="card"><h2>${t("tr_t")}</h2><span class="lbl">${t("to")}:</span>${pill("to","user","@ "+t("uname"))}${pill("to","id","🆔 "+t("tgid"))}${pill("to","pair","💕 "+t("pair"))}
 ${tr.to==="pair"?`<p class="mu">${t("pair_h")}</p>`:`<input id="trv" class="inp" placeholder="${esc(tr.to==="user"?t("un_ph"):t("id_ph"))}" value="${esc(tr.val)}" autocomplete="off">`}
 <span class="lbl">${t("what")}:</span>${pill("kind","money","💵 "+t("dollar"))}${pill("kind","diamonds","💎 "+t("dia"))}${pill("kind","item","🎒 "+t("inv"))}
 ${tr.kind==="item"?`<span class="lbl">${t("item")}:</span>${["himoya","hujjat","osish","geroyd"].map(k=>pill("item",k,ITM[k]+" "+t("it_"+k))).join("")}`:""}
 <span class="lbl">${t("amount")}:</span><input id="tra" class="inp" inputmode="numeric" placeholder="${esc(t("amount_ph"))}" value="${esc(tr.amt)}" autocomplete="off">
 <p class="mu" style="margin-top:10px">${t("fee")}: ${fee}</p><button class="btn" data-a="dotr">${t("do_tr")}</button></div>`;}
function pHistory(){const d=D("his_"+S.hs,"history",{scope:S.hs});const tabs=`<div class="tabs2" style="margin-bottom:12px"><button class="${S.hs==="me"?"on":""}" data-a="hs" data-v="me">${t("mine")}</button><button class="${S.hs==="all"?"on":""}" data-a="hs" data-v="all">${t("all")}</button></div>`;
 if(!d)return `<div class="card"><h2>${t("his")}</h2></div>`+tabs+skel();const ic=k=>k==="money"?"💶":k==="diamonds"?"💎":k.startsWith("item:")?ITM[k.slice(5)]||"🎒":"🔄";
 return `<div class="card"><h2>${t("his")}</h2></div>`+tabs+(d.rows&&d.rows.length?d.rows.map(r=>`<div class="li ${r.me?"me":""}"><span class="r ${r.me?(r.out?"dn":"up"):""}">${r.me?(r.out?"−":"+"):""}${fmt(r.amt)} ${ic(r.kind)}</span><b>${esc(r.frm)}</b> → <b>${esc(r.to)}</b><small>${new Date(r.ts*1000).toLocaleString()}</small></div>`).join(""):`<div class="card mu">${t("none")}</div>`);}
function pRating(){const d=D("top"+S.rd,"top",{days:S.rd});const tabs=`<div class="tabs2" style="margin-bottom:12px">${[[1,"d1"],[7,"d7"],[30,"d30"],[0,"dall"]].map(([v,k])=>`<button class="${S.rd===v?"on":""}" data-a="rd" data-v="${v}">${t(k)}</button>`).join("")}</div>`;
 if(!d)return `<div class="card"><h2>🏆 ${t("rate")}</h2></div>`+tabs+skel();const md=["🥇","🥈","🥉"];
 return `<div class="card"><h2>🏆 ${t("rate")}</h2></div>`+tabs+(d.rows&&d.rows.length?d.rows.map((r,i)=>`<div class="li ${r.me?"me":""}"><span class="r">${fmt(r.s)} ${t("ball")}</span>${md[i]||(i+1)+"."} ${esc(r.n)}</div>`).join(""):`<div class="card mu">${t("none")}</div>`);}
function pInv(){const m=S.me;return `<div class="card"><h2>🎒 ${t("inv_t")}</h2><p class="mu">${t("inv_s")}</p></div>
 <div class="card"><h3>🃏 ${t("ar_t")}</h3>${m.aroles.length?`<div class="chips" style="margin:0">${m.aroles.map(a=>`<span class="chip">${a.e} ${esc(a.n)}</span>`).join("")}</div>`:`<p class="mu">${t("no_ar")}</p>`}</div>
 <div class="card"><h3>📦 ${t("items")}</h3>${["himoya","hujjat","osish","geroyd"].map(k=>`<div class="li">${ITM[k]} ${t("it_"+k)}<span class="r">${m.items[k]} ${t("cnt")}</span></div>`).join("")}</div>`;}
function pShields(){const m=S.me;return `<div class="card"><h2>🛡 ${t("sh_t")}</h2><p class="mu">${t("sh_s")}</p>${["himoya","hujjat","osish","geroyd"].map(k=>`<div class="row"><div><b>${ITM[k]} ${t("it_"+k)}</b><small>${m.items[k]} ${t("cnt")} · ${m.tg[k]?t("on"):t("off")}</small></div><button class="sw ${m.tg[k]?"on":""}" data-a="tgl" data-k="${k}" aria-label="${t("it_"+k)}"></button></div>`).join("")}</div>`;}
function pLove(){const d=D("love","love");const m=S.me;const mine=m.pairs.length?m.pairs.map(p=>`<div class="li">💞 ${esc(p.name)}</div>`).join(""):`<p class="mu">${t("no_pairs")}</p>`;
 return `<div class="card"><h2>💞 ${t("love")}</h2><p class="mu">${t("love_s")}</p></div><div class="card"><h3>${t("my_pairs")} (${m.pairs.length}/${m.plim})</h3>${mine}</div><div class="card"><h3>✨ ${t("sky")}</h3>${d?(d.sky&&d.sky.length?d.sky.map(x=>`<div class="li">${esc(x.a)} 💞 ${esc(x.b)}</div>`).join(""):`<p class="mu">${t("none")}</p>`):`<div class="sk" style="height:60px;border-radius:14px"></div>`}</div>`;}
const hemo=l=>l>=30?"👑":l>=20?"🤠":l>=10?"😎":l>=5?"🙂":"😴";
function heroMine(){const m=S.me,h=m.hero;
 if(!h)return `<div class="card"><b>${t("no_h")}</b><p class="mu">${t("no_h_s")}</p><div class="row"><button class="btn" data-a="buy" data-k="hero">💎 90 ${t("via")}</button><button class="btn alt" data-a="herostars">⭐ 300 ${t("via")}</button></div></div>`;
 const pw=h.pw?h.pw[0]+"–"+h.pw[1]:"MAX";const pc=h.nxt?Math.min(100,Math.round((h.pts%1100)/11)):100;
 return `<div class="card"><div class="hh"><span class="big">${hemo(h.lvl)}</span><div><b style="font-size:18px">${esc(h.name||"—")}</b><small>${t("lvl")} ${h.lvl}</small></div></div>
 <div class="stats3"><div>🩸 ${h.charge}/10</div><div>🛡 ${h.prot}/${h.maxp}</div><div>⭐ ${fmt(h.pts)}</div></div>
 <div class="row"><span>👊 ${t("pwr")}</span><b>${pw}</b></div><div class="row"><span>🔰 ${t("it_geroyd")}</span><b>${h.gd}</b></div>
 ${h.nxt?`<div class="row"><span>⏫ ${t("nxt")}</span><b>${fmt(h.nxt)} ${t("ball")}</b></div><div class="bar"><div style="width:${pc}%"></div></div>`:""}</div>
 <div class="card"><div class="row"><b>${t("a_ball")}</b><button class="btn sm" data-a="hact" data-v="ball">💎 50</button></div><div class="row"><b>${t("a_prot")}</b><button class="btn sm" data-a="hact" data-v="prot">$ 300</button></div><div class="row"><b>${t("a_chg")}</b><button class="btn sm" data-a="hact" data-v="charge">$ 200</button></div><div class="row"><b>${t("a_name")}</b><button class="btn sm alt" data-a="hname">$ 800</button></div></div>`;}
function heroMarket(){const d=D("mk","market");const m=S.me;const tabs=`<div class="tabs2" style="margin-bottom:12px"><button class="${S.ms==="mkt"?"on":""}" data-a="ms" data-v="mkt">${t("bozor")}</button><button class="${S.ms==="mine"?"on":""}" data-a="ms" data-v="mine">${t("my_ad")}</button></div>`;
 if(!d)return tabs+skel();const rows=(d.rows||[]).filter(x=>S.ms==="mkt"?true:x.mine);
 const card=x=>`<div class="card"><div class="mk"><span class="big">${hemo(x.lvl)}</span><div><b>${esc(x.name||"—")}</b><small>${t("lvl")} ${x.lvl}</small><small>🩸 ${x.charge}/10 · 🛡 ${x.prot}/${x.maxp} · ⭐ ${fmt(x.pts)}</small><small>${t("seller")}: ${esc(x.seller)}</small></div></div><div class="row"><b>💎 ${fmt(x.price)}</b>${x.mine?`<button class="btn sm dng" data-a="mcancel">${t("cancel")}</button>`:`<button class="btn sm" data-a="mbuy" data-id="${x.id}">${t("buy")}</button>`}</div></div>`;
 let body;if(rows.length)body=rows.map(card).join("");else if(S.ms==="mine")body=`<div class="card mu">${m.hero?t("no_ad"):t("no_h_sell")}</div>`;else body=`<div class="card mu">${t("empty_m")}</div>`;
 return tabs+body+`<button class="plus" data-a="msellopen" aria-label="${t("sell")}">＋</button>`;}
function pHero(){return `<div class="card"><h2>🥷 ${t("her_t")}</h2><p class="mu">${t("her_s")}</p><div class="tabs2"><button class="${S.hv==="my"?"on":""}" data-a="hv" data-v="my">🛡 ${t("my_h")}</button><button class="${S.hv==="mkt"?"on":""}" data-a="hv" data-v="mkt">🏪 ${t("mkt")}</button></div></div>`+(S.hv==="my"?heroMine():heroMarket());}
function render(keep){const m=S.me;if(!m){$("#app").innerHTML=`<div class="wrap"><div class="card sk"></div></div>`;return;}
 const P={home:pHome,roles:pRoles,role:pRole,shop:pShop,transfer:pTransfer,history:pHistory,rating:pRating,inventory:pInv,shields:pShields,hero:pHero,love:pLove,vip:()=>pVip()};
 const body=(P[S.page]||pHome)();const y=window.scrollY;
 $("#app").innerHTML=`<div class="wrap">${pCard()}${body}</div>${nav()}<button class="fab" data-a="sup" aria-label="${t("sup")}">🎧</button>`;
 if(keep)window.scrollTo(0,y);}
function ov(html){closeOv();$("#ov").innerHTML=html;}
function openTheme(){const m=S.me;ov(`<div class="back" data-a="ovclose"></div><div class="panel sheet"><h3>🎨 ${t("theme")}</h3><div class="th">${Object.keys(THEMES).map(k=>`<button data-a="setTheme" data-k="${k}" class="${m.theme===k?"on":""}"><span style="background:linear-gradient(135deg,${THEMES[k][0]},${THEMES[k][1]})">${m.theme===k?"✓":""}</span>${t("th_"+k)}</button>`).join("")}</div></div>`);}
function openLang(){ov(`<div class="back" data-a="ovclose"></div><div class="panel sheet"><h3>🌐 ${t("lang")}</h3>${LANGS.map(l=>`<button class="lg ${S.lang===l[0]?"on":""}" data-a="setLang" data-k="${l[0]}"><span>${l[1]}</span>${l[2]}</button>`).join("")}</div>`);}
function openDrawer(){const m=S.me;const it=[["home","🏠","home_t"],["rating","📊","rate"],["history","🕘","his"],["inventory","🧰","inv_t"],["shields","🛡","sh_t"],["hero","🥷","hero_c"],["love","💞","love"]];
 ov(`<div class="back" data-a="ovclose"></div><div class="panel drawer"><div class="pc" style="margin-bottom:14px"><div class="av" style="width:54px;height:54px"><span style="font-size:20px">${esc((m.name||"?").charAt(0).toUpperCase())}</span></div><div><div class="nm" style="font-size:16px">${esc(m.name)}</div><div class="un">${m.username?"@"+esc(m.username):""}</div></div></div>${it.map(x=>`<button class="dm" data-a="go" data-p="${x[0]}"><i>${x[1]}</i>${t(x[2])}</button>`).join("")}<button class="btn wide" data-a="go" data-p="vip">👑 VIP — 30 ${t("days")}</button></div>`);}
function openSell(){ov(`<div class="back" data-a="ovclose"></div><div class="panel sheet"><h3>🏪 ${t("sell")}</h3>${S.me.hero?`<input id="sp" class="inp" inputmode="numeric" placeholder="${esc(t("price_ph"))}"><button class="btn wide" data-a="msell">${t("sell")}</button>`:`<p class="mu">${t("no_h_sell")}</p>`}</div>`);}
function openName(){ov(`<div class="back" data-a="ovclose"></div><div class="panel sheet"><h3>${t("a_name")} — $ 800</h3><input id="hn" class="inp" maxlength="24" placeholder="${esc(t("name_ph"))}"><button class="btn wide" data-a="hnsave">${t("save")}</button></div>`);}
/* ---- operator va global chat ---- */
function openSup(tab){ov(`<div class="back" data-a="ovclose"></div><div class="panel sup"><div class="ph"><div class="tabs2" style="flex:1"><button id="tb_help" data-a="suptab" data-v="help">🆘 ${t("sup")}</button><button id="tb_gc" data-a="suptab" data-v="gc">🌍 ${t("gchat")}</button></div><button class="x" data-a="ovclose" aria-label="x">✕</button></div>
 <div id="sm" class="msgs"></div><div class="pf"><div id="simg"></div><div class="pi"><label class="att" id="satt">📎<input type="file" id="sfile" accept="image/*" hidden></label><input id="sin" class="inp" maxlength="1000" placeholder="${esc(t("msg_ph"))}" autocomplete="off"><button class="btn" data-a="supsend" aria-label="${t("send")}">➤</button></div></div></div>`);
 S.sup={tab:tab||"help",last:{help:0,gc:0},msgs:{help:[],gc:[]},img:"",timer:null};supTab(S.sup.tab);supPoll();S.sup.timer=setInterval(supPoll,4000);}
function supTab(v){const s=S.sup;if(!s)return;s.tab=v;$("#tb_help").className=v==="help"?"on":"";$("#tb_gc").className=v==="gc"?"on":"";$("#satt").style.display=v==="help"?"":"none";drawMsgs(true);supPoll();}
function drawMsgs(bottom){const s=S.sup;if(!s)return;const box=$("#sm");if(!box)return;
 const intro=s.tab==="help"?t("sup_in"):t("gc_in");let h=`<div class="bb"><small>${s.tab==="help"?t("bot_h"):t("gchat")}</small>${esc(intro)}</div>`;
 h+=s.msgs[s.tab].map(x=>{if(s.tab==="help"){const me=x.role==="u";return `<div class="bb ${me?"me":""}">${me?"":`<small>${x.role==="a"?t("op"):t("bot_h")}</small>`}${esc(x.text)}${x.img?`<img src="${esc(x.img)}" alt="">`:""}</div>`;}
  return `<div class="bb ${x.me?"me":""}"><small>${x.vip?esc(x.vip)+" ":""}${esc(x.name)}</small>${esc(x.text)}</div>`;}).join("");
 box.innerHTML=h;if(bottom)box.scrollTop=box.scrollHeight;}
function addMsgs(key,arr){const s=S.sup;if(!s||!arr||!arr.length)return;const have=new Set(s.msgs[key].map(x=>x.id));arr.forEach(x=>{if(!have.has(x.id))s.msgs[key].push(x);});
 s.last[key]=Math.max(s.last[key],...s.msgs[key].map(x=>x.id));if(s.tab===key)drawMsgs(true);}
async function supPoll(){const s=S.sup;if(!s)return;const k=s.tab;try{const r=await api(k==="help"?"sup_get":"gc_get",{after:s.last[k]});if(S.sup===s)addMsgs(k,r.msgs);}catch(e){}}
function drawImg(){const s=S.sup;if(!s)return;$("#simg").innerHTML=s.img?`<span class="pv">🖼 <button data-a="rmimg">✕</button></span>`:"";}
async function supSend(){const s=S.sup;if(!s)return;const inp=$("#sin");const text=inp.value.trim();const k=s.tab;
 if(k==="help"){if(!text&&!s.img)return;const r=await api("sup_send",{text,img:s.img,after:s.last.help});inp.value="";s.img="";drawImg();addMsgs("help",r.msgs);}
 else{if(!text)return;const r=await api("gc_send",{text,after:s.last.gc});inp.value="";addMsgs("gc",r.msgs);}}
function payInvoice(link){if(tg&&tg.openInvoice)tg.openInvoice(link,st=>{if(st==="paid"){toast(t("ok"),true);setTimeout(()=>run(async()=>{await refresh();render(true);}),1500);}});else toast(t("e_auth"));}
const ACTS={
 go:d=>go(d.p),menu:()=>openDrawer(),theme:()=>openTheme(),lang:()=>openLang(),ovclose:()=>closeOv(),sup:()=>openSup("help"),suptab:d=>supTab(d.v),
 setTheme:d=>run(async()=>{await api("set",{theme:d.k});await refresh();closeOv();render(true);}),
 setLang:d=>run(async()=>{await api("set",{lang:d.k});S.d={};S.pend={};await refresh();closeOv();render(true);}),
 role:d=>{S.role=d.k;S.page="role";render();window.scrollTo(0,0);},
 buy:d=>run(async()=>{await api("buy",{k:d.k});await refresh();toast(t("ok"),true);render(true);}),
 arole:d=>run(async()=>{await api("arole",{k:d.k});await refresh();toast(t("ok"),true);render(true);}),
 trs:d=>{S.tr[d.g]=d.v;render(true);},
 dotr:()=>run(async()=>{const tr=S.tr;const r=await api("transfer",{to_type:tr.to,to:tr.val,kind:tr.kind,item:tr.item,amount:tr.amt});S.tr.amt="";await refresh();toast(t("ok_tr")+" → "+r.to,true);render(true);}),
 hs:d=>{S.hs=d.v;render(true);},rd:d=>{S.rd=Number(d.v);render(true);},
 tgl:d=>run(async()=>{await api("toggle",{k:d.k});await refresh();render(true);}),
 hv:d=>{S.hv=d.v;delete S.d.mk;render(true);},ms:d=>{S.ms=d.v;render(true);},
 hact:d=>run(async()=>{await api("hero",{a:d.v});await refresh();toast(t("ok"),true);render(true);}),
 hname:()=>openName(),
 hnsave:()=>run(async()=>{const v=$("#hn").value;await api("hero",{a:"name",name:v});await refresh();closeOv();toast(t("ok"),true);render(true);}),
 herostars:()=>run(async()=>{const r=await api("invoice",{what:"hero"});payInvoice(r.link);}),
 vipd:d=>run(async()=>{await api("vip",{k:Number(d.k)});await refresh();toast(t("ok"),true);render(true);}),
 vips:d=>run(async()=>{const r=await api("invoice",{what:"vip",k:Number(d.k)});payInvoice(r.link);}),
 msellopen:()=>openSell(),
 msell:()=>run(async()=>{await api("msell",{price:$("#sp").value});delete S.d.mk;await refresh();closeOv();toast(t("ok"),true);S.ms="mine";render(true);}),
 mcancel:()=>run(async()=>{await api("mcancel");delete S.d.mk;await refresh();toast(t("ok"),true);render(true);}),
 mbuy:d=>run(async()=>{await api("mbuy",{id:Number(d.id)});delete S.d.mk;await refresh();toast(t("ok"),true);render(true);}),
 supsend:()=>run(supSend),rmimg:()=>{if(S.sup){S.sup.img="";drawImg();}}
};
document.addEventListener("click",e=>{const el=e.target.closest("[data-a]");if(!el)return;const f=ACTS[el.dataset.a];if(f){e.preventDefault();f(el.dataset);}});
document.addEventListener("input",e=>{const id=e.target.id;
 if(id==="rq"){S.q=e.target.value;const rl=$("#rl");if(rl)rl.innerHTML=rolesList();}
 else if(id==="trv")S.tr.val=e.target.value;else if(id==="tra")S.tr.amt=e.target.value;});
document.addEventListener("keydown",e=>{if(e.key==="Enter"&&e.target.id==="sin"){e.preventDefault();run(supSend);}});
document.addEventListener("change",e=>{if(e.target.id!=="sfile")return;const f=e.target.files&&e.target.files[0];if(!f||!S.sup)return;
 if(f.size>4*1024*1024){toast(t("e_big_img"));e.target.value="";return;}
 const fr=new FileReader();fr.onload=()=>{if(S.sup){S.sup.img=String(fr.result);drawImg();}};fr.readAsDataURL(f);e.target.value="";});
(async()=>{if(!INIT){$("#app").innerHTML=`<div class="wrap"><div class="card">${esc(t("e_auth"))}</div></div>`;return;}
 try{await refresh();}catch(e){$("#app").innerHTML=`<div class="wrap"><div class="card">${esc(t("e_"+String(e.message)))}</div></div>`;return;}
 render();})();
</script></body></html>'''


# ───────────────────────── Ishga tushirish ─────────────────────────

async def ensure_https():
    """WEB_URL HTTPS bo'lmasa: cloudflared yoki ngrok bor bo'lsa o'zi HTTPS tunnel ochadi (Telegram Web App uchun shart)."""
    global WEB_URL, WEB_HTTPS
    if WEB_HTTPS: return
    url = None
    cf = shutil.which("cloudflared")
    if cf:
        try:
            proc = await asyncio.create_subprocess_exec(cf, "tunnel", "--url", f"http://127.0.0.1:{WEB_PORT}", "--no-autoupdate",
                                                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            async def scan():
                while True:
                    line = await proc.stderr.readline()
                    if not line: return None
                    m_ = re.search(rb"https://[a-z0-9-]+\.trycloudflare\.com", line)
                    if m_: return m_.group(0).decode()
            url = await asyncio.wait_for(scan(), 45)
            async def drain():
                while await proc.stderr.readline(): pass
            BG_TASKS.append(asyncio.create_task(drain()))
        except Exception:
            logging.exception("cloudflared ishga tushmadi")
    ng = shutil.which("ngrok")
    if not url and ng:
        try:
            await asyncio.create_subprocess_exec(ng, "http", str(WEB_PORT), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            for _ in range(20):
                await asyncio.sleep(1)
                try:
                    async with aiohttp.ClientSession() as ses:
                        async with ses.get("http://127.0.0.1:4040/api/tunnels", timeout=aiohttp.ClientTimeout(total=3)) as rs:
                            for tn in (await rs.json()).get("tunnels", []):
                                if str(tn.get("public_url", "")).startswith("https://"): url = tn["public_url"]
                except Exception: pass
                if url: break
        except Exception:
            logging.exception("ngrok ishga tushmadi")
    if url:
        WEB_URL, WEB_HTTPS = url.rstrip("/"), True
        logging.info("HTTPS tunnel: %s/app", WEB_URL)
        for a in ADMIN_IDS: await pm(a, f"🌐 Shaxsiy kabinet manzili (avtomatik tunnel):\n<code>{esc(WEB_URL)}/app</code>")
    else:
        logging.warning("HTTPS topilmadi. Yechim: WEB_URL=https://domen o'rnating, yoki cloudflared/ngrok o'rnating, yoki adminga botda /weburl https://domen yozing.")

async def main():
    global BOTNAME
    logging.basicConfig(level=logging.INFO)
    os.makedirs("media", exist_ok=True)
    BOTNAME = (await bot.get_me()).username
    await start_web()
    BG_TASKS.append(asyncio.create_task(sub_watch()))
    await ensure_https()
    gap = [("start", "O'yinni boshlash"), ("game", "O'yin yaratish"), ("vsgame", "Jamoaviy o'yin (VS)"),
           ("roles", "O'yin rollarini ko'rish"), ("leave", "O'yindan chiqish"), ("sozlamalar", "Sozlamalarni ochish"),
           ("stop", "O'yinni to'xtatish"), ("gtop", "Geroy va geroychalar reytingi")]
    prv = [("start", "O'yinni boshlash"), ("profile", "Profilingizni ko'rish (Shaxsiy chatda)"),
           ("roles", "O'yin rollarini ko'rish"), ("gtop", "Geroy va geroychalar reytingi"), ("language", "Tilni tanlash")]
    await bot.set_my_commands([BotCommand(command=c_, description=d) for c_, d in gap], scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands([BotCommand(command=c_, description=d) for c_, d in prv], scope=BotCommandScopeAllPrivateChats())
    try: await bot.set_chat_menu_button(menu_button=MenuButtonCommands())       # eski "Menyu"/klaviatura o'rniga buyruqlar menyusi
    except Exception: pass
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())