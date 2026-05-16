import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import Optional
import json
import urllib.request
import urllib.parse

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("BOT_TOKEN", "8981204786:AAESxFvvqNaR8Ryww4Ss1udy7MsFMC_K9WY")
ADMIN_IDS = {5815040020}
BOT_NAME = os.getenv("BOT_NAME", "ABHIJEET STORE")
QR_PATH = os.getenv("QR_PATH", "qr.png")
UPI_ID = os.getenv("UPI_ID", "arpam.bistan.ag@fam")
UPI_NAME = os.getenv("UPI_NAME", "BISTAN Charchil")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/A_bhijeeet")
PAYMENT_PROOF_LINK = os.getenv("PAYMENT_PROOF_LINK", "https://t.me/abhi_feedback")
FILES_LINK = os.getenv("FILES_LINK", "https://t.me/ABHI_FILES")
FAMPAY_API_KEY = os.getenv("FAMPAY_API_KEY", "FAM_e8eeefe8729a87fb92cc35f7a7730e94a25964c132df5d49")
FAMPAY_QR_API = os.getenv("FAMPAY_QR_API", "https://fampay.anujbots.xyz/qr.php")
FAMPAY_VERIFY_API = os.getenv("FAMPAY_VERIFY_API", "https://fampay.anujbots.xyz/verify.php")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", "store.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# =========================
# DB INIT
# =========================
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        is_reseller INTEGER DEFAULT 0
    )
    """
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS categories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        stock TEXT DEFAULT '',
        FOREIGN KEY(category_id) REFERENCES categories(id)
    )
    """
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS payment_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        utr TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    )
    """
)

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        category_name TEXT NOT NULL,
        price INTEGER NOT NULL,
        delivered_item TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
)

conn.commit()

# =========================
# HELPERS
# =========================
def get_setting(key: str, default: str = "") -> str:
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    cur.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def ensure_user(user_id: int) -> None:
    cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_reseller(user_id: int) -> bool:
    cur.execute("SELECT is_reseller FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return bool(row and row[0] == 1)


def get_balance(user_id: int) -> int:
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def add_balance(user_id: int, amount: int) -> None:
    ensure_user(user_id)
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()


def deduct_balance(user_id: int, amount: int) -> bool:
    bal = get_balance(user_id)
    if bal < amount:
        return False
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    return True


def pending_key(user_id: int) -> str:
    return f"pending_payment:{user_id}"


def get_category_id(name: str) -> Optional[int]:
    cur.execute("SELECT id FROM categories WHERE name=?", (name,))
    row = cur.fetchone()
    return int(row[0]) if row else None


def get_product(pid: int):
    cur.execute(
        """
        SELECT p.id, p.category_id, p.name, p.price, p.stock, c.name
        FROM products p
        JOIN categories c ON p.category_id = c.id
        WHERE p.id=?
        """,
        (pid,),
    )
    return cur.fetchone()


def consume_stock(stock_text: str):
    lines = [x.strip() for x in stock_text.splitlines() if x.strip()]
    if not lines:
        return None, None
    item = lines[0]
    rest = "\n".join(lines[1:])
    return item, rest


def seed_catalog() -> None:
    categories = ["Category 1", "Category 2", "Category 3"]
    for name in categories:
        cur.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
    conn.commit()


async def on_startup() -> None:
    seed_catalog()
    if not get_setting("bot_status"):
        set_setting("bot_status", "ON")


# =========================
# KEYBOARDS
# =========================
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Shop Now")],
            [KeyboardButton(text="📦 My Orders"), KeyboardButton(text="👤 Profile")],
            [KeyboardButton(text="🧾 Pay Proof"), KeyboardButton(text="🗂 Feedback")],
            [KeyboardButton(text="📘 How to Use"), KeyboardButton(text="💬 Support")],
        ],
        resize_keyboard=True,
    )


def admin_panel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📢 Broadcast"), KeyboardButton(text="🤖 Bot Status")],
            [KeyboardButton(text="💰 Add Balance"), KeyboardButton(text="🛠 Shop Setup")],
            [KeyboardButton(text="👥 Add Reseller"), KeyboardButton(text="🛑 Remove Reseller")],
            [KeyboardButton(text="📋 Reseller List"), KeyboardButton(text="➕ Add Category")],
            [KeyboardButton(text="🗑 Remove Category"), KeyboardButton(text="➕ Add Product")],
            [KeyboardButton(text="💲 Change Price"), KeyboardButton(text="🗑 Remove Product")],
            [KeyboardButton(text="📦 Stock")],
            [KeyboardButton(text="🔙 Main Menu")],
        ],
        resize_keyboard=True,
    )


def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Main Menu")]],
        resize_keyboard=True,
    )


def category_kb() -> ReplyKeyboardMarkup:
    cur.execute("SELECT id, name FROM categories ORDER BY id ASC")
    rows = cur.fetchall()
    kb = [[KeyboardButton(text=f"📁 {name}")] for _, name in rows]
    kb.append([KeyboardButton(text="🔙 Main Menu")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Support", url=SUPPORT_LINK)]]
    )


def info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Pay Proof", url=PAYMENT_PROOF_LINK)],
            [InlineKeyboardButton(text="📁 All Files", url=FILES_LINK)],
            [InlineKeyboardButton(text="💬 Support", url=SUPPORT_LINK)],
        ]
    )


def payment_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Check Payment", callback_data="paid_btn")],
            [InlineKeyboardButton(text="💬 Support", url=SUPPORT_LINK)],
        ]
    )


def product_inline_kb(category_id: int):
    cur.execute(
        "SELECT id, name, price, stock FROM products WHERE category_id=? ORDER BY id ASC",
        (category_id,),
    )
    rows = cur.fetchall()
    buttons = []
    for pid, name, price, stock in rows:
        stock_count = len([x for x in stock.splitlines() if x.strip()])
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{name} • ₹{price} • Stock:{stock_count}",
                    callback_data=f"buy:{pid}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


def product_text(category_id: int) -> str:
    cur.execute("SELECT name FROM categories WHERE id=?", (category_id,))
    cat = cur.fetchone()
    if not cat:
        return "Category not found."

    cur.execute(
        "SELECT id, name, price, stock FROM products WHERE category_id=? ORDER BY id ASC",
        (category_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return f"No products found in {cat[0]}."

    text = f"🛍 *{cat[0]} Products*\n\n"
    for pid, name, price, stock in rows:
        stock_count = len([x for x in stock.splitlines() if x.strip()])
        text += f"#{pid} — {name}\n₹{price} | Stock: {stock_count}\n\n"
    return text



def http_get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

async def create_fampay_qr(amount: int) -> Optional[dict]:
    if not FAMPAY_API_KEY or FAMPAY_API_KEY == "FAM_e8eeefe8729a87fb92cc35f7a7730e94a25964c132df5d49":
        return None
    params = urllib.parse.urlencode({"upi": UPI_ID, "amount": amount})
    url = f"{FAMPAY_QR_API}?{params}"
    try:
        data = await asyncio.to_thread(http_get_json, url)
        if data.get("status") == "success":
            return data.get("data", {})
    except Exception as exc:
        logger.exception("FamPay QR generation failed: %s", exc)
    return None

async def verify_fampay_payment(order_id: str) -> Optional[dict]:
    if not FAMPAY_API_KEY or FAMPAY_API_KEY == "FAM_e8eeefe8729a87fb92cc35f7a7730e94a25964c132df5d49":
        return None
    params = urllib.parse.urlencode({
        "order_id": order_id,
        "api_key": FAMPAY_API_KEY,
    })
    url = f"{FAMPAY_VERIFY_API}?{params}"
    try:
        data = await asyncio.to_thread(http_get_json, url)
        if data.get("status") == "success":
            return data.get("data", {})
    except Exception as exc:
        logger.exception("FamPay verify failed: %s", exc)
    return None

async def send_payment_qr(message: Message, amount: int) -> None:
    fam = await create_fampay_qr(amount)

    if not fam:
        await message.answer("❌ Automatic payment server unavailable.")
        return

    order_id = str(fam.get("order_id", ""))
    qr_url = fam.get("qr_url")
    expires_at = fam.get("expires_at_ist", "5 minutes")

    if not order_id or not qr_url:
        await message.answer("❌ QR generation failed.")
        return

    set_setting(
        pending_key(message.from_user.id),
        f"AUTO_VERIFY|{amount}|{order_id}"
    )

    caption = (
        f"💳 *Auto Deposit ₹{amount}*\\n\\n"
        f"⏳ Expires: {expires_at}\\n"
        f"📲 Scan QR and complete payment\\n\\n"
        f"✅ After payment click below button"
    )

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=qr_url,
        caption=caption,
        reply_markup=payment_action_kb(),
    )


# =========================
# START / BASIC COMMANDS
# =========================
@dp.message(CommandStart())
async def start(message: Message):
    ensure_user(message.from_user.id)
    shop_status = get_setting("bot_status", "ON")
    # fixed broken multiline string
    welcome = (
    f"👋 Welcome {message.from_user.first_name}\n\n"
    f"🤖 Bot Status: {'🟢 On' if shop_status == 'ON' else '🔴 Off'}"
)
    await message.answer(welcome, reply_markup=main_menu())


@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(f"👑 Admin Panel — {BOT_NAME}", reply_markup=admin_panel())


@dp.message(Command("orders"))
async def orders_cmd(message: Message):
    ensure_user(message.from_user.id)
    await send_order_history(message)


@dp.message(F.text == "🔙 Main Menu")
async def main_menu_handler(message: Message):
    await message.answer("Main menu:", reply_markup=main_menu())


@dp.message(F.text == "🛒 Shop Now")
async def shop(message: Message):
    await message.answer("Choose a category:", reply_markup=category_kb())


@dp.message(F.text == "🛒 Shop")
async def shop_legacy(message: Message):
    await message.answer("Choose a category:", reply_markup=category_kb())


@dp.message(F.text == "💳 Balance")
async def balance_legacy(message: Message):
    ensure_user(message.from_user.id)
    bal = get_balance(message.from_user.id)
    await message.answer(f"💰 Your balance: ₹{bal}", reply_markup=main_menu())


@dp.message(F.text == "👤 Profile")
async def profile(message: Message):
    ensure_user(message.from_user.id)
    bal = get_balance(message.from_user.id)
    role = "Admin" if is_admin(message.from_user.id) else ("Reseller" if is_reseller(message.from_user.id) else "User")
    text = (
        f"👤 Profile\n\n"
        f"ID: `{message.from_user.id}`\n"
        f"Name: {message.from_user.full_name}\n"
        f"Role: {role}\n"
        f"Balance: ₹{bal}"
    )
    await message.answer(text, reply_markup=main_menu())


@dp.message(F.text == "👤 My Profile")
async def profile_legacy(message: Message):
    ensure_user(message.from_user.id)
    bal = get_balance(message.from_user.id)
    role = "Admin" if is_admin(message.from_user.id) else ("Reseller" if is_reseller(message.from_user.id) else "User")
    text = (
        f"👤 Profile\n\n"
        f"ID: `{message.from_user.id}`\n"
        f"Name: {message.from_user.full_name}\n"
        f"Role: {role}\n"
        f"Balance: ₹{bal}"
    )
    await message.answer(text, reply_markup=main_menu())


@dp.message(F.text == "📦 My Orders")
async def my_orders(message: Message):
    ensure_user(message.from_user.id)
    await send_order_history(message)


@dp.message(F.text == "📜 Order History")
async def order_history_legacy(message: Message):
    ensure_user(message.from_user.id)
    await send_order_history(message)


@dp.message(F.text == "🧾 Pay Proof")
async def pay_proof_btn(message: Message):
    await message.answer(
        "Payment proof channel:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🧾 Pay Proof", url=PAYMENT_PROOF_LINK)]]
        ),
    )


@dp.message(F.text == "🗂 Feedback")
async def feedback_btn(message: Message):
    await message.answer(
        "All files channel:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📁 All Files", url=FILES_LINK)]]
        ),
    )


@dp.message(F.text == "📘 How to Use")
async def how_to_use_btn(message: Message):
    await message.answer(
        "Use Shop Now to browse categories. Use Add Money to top up via QR.\n"
        "Pay Proof opens your payment proof channel and All Files opens your files channel.",
        reply_markup=info_kb(),
    )


@dp.message(F.text == "ℹ️ Help")
async def help_legacy(message: Message):
    await message.answer(
        "Use Shop Now to browse categories. Use Add Money to top up via QR.\n"
        "Pay Proof opens your payment proof channel and All Files opens your files channel.",
        reply_markup=info_kb(),
    )


@dp.message(F.text == "💬 Support")
async def support_btn(message: Message):
    await message.answer("Support:", reply_markup=support_kb())





@dp.message(F.text == "➕ Add Money")
async def add_money_start(message: Message):
    ensure_user(message.from_user.id)
    set_setting(pending_key(message.from_user.id), "AMOUNT")
    await message.answer(
        "Send the amount you want to add, for example: `500`\n\n"
        f"UPI ID: `{UPI_ID}`\n"
        f"Name: `{UPI_NAME}`",
        reply_markup=payment_action_kb(),
    )


@dp.message(F.text == "🤖 Bot Status")
async def bot_status(message: Message):
    if not is_admin(message.from_user.id):
        return
    current = get_setting("bot_status", "ON")
    new_status = "OFF" if current == "ON" else "ON"
    set_setting("bot_status", new_status)
    await message.answer(f"Bot status changed to {new_status}.", reply_markup=admin_panel())


# =========================
# ADMIN ACTION STARTERS
# =========================
@dp.message(F.text == "📢 Broadcast")
async def broadcast_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_broadcast", "1")
    await message.answer(
        "Send the broadcast message now. You can send text, photo, video, or any media.",
        reply_markup=admin_panel(),
    )


@dp.message(F.text == "➕ Add Category")
async def add_category_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_category", "1")
    await message.answer("Send the category name.", reply_markup=admin_panel())


@dp.message(F.text == "🗑 Remove Category")
async def remove_category_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_remove_category", "1")
    await message.answer("Send the category name to remove.", reply_markup=admin_panel())


@dp.message(F.text == "➕ Add Product")
async def add_product_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_product_meta", "1")
    await message.answer(
        "Send product data in this format:\n"
        "Category Name | Product Name | Price",
        reply_markup=admin_panel(),
    )


@dp.message(F.text == "🗑 Remove Product")
async def remove_product_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_remove_product", "1")
    await message.answer(
        "Send the Product ID to remove.\nUse 📦 Stock to see product IDs.",
        reply_markup=admin_panel(),
    )


@dp.message(F.text == "💲 Change Price")
async def change_price_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_change_price", "1")
    await message.answer(
        "Send: product_id new_price\nExample: `12 499`",
        reply_markup=admin_panel(),
    )


@dp.message(F.text == "💰 Add Balance")
async def add_balance_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_add_balance", "1")
    await message.answer("Send: user_id amount", reply_markup=admin_panel())


@dp.message(F.text == "👥 Add Reseller")
async def add_reseller_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_add_reseller", "1")
    await message.answer("Send reseller Telegram user_id.", reply_markup=admin_panel())


@dp.message(F.text == "🛑 Remove Reseller")
async def remove_reseller_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    set_setting("await_remove_reseller", "1")
    await message.answer("Send reseller Telegram user_id to remove.", reply_markup=admin_panel())


@dp.message(F.text == "📋 Reseller List")
async def reseller_list(message: Message):
    if not is_admin(message.from_user.id):
        return
    cur.execute("SELECT user_id FROM users WHERE is_reseller=1 ORDER BY user_id ASC")
    rows = cur.fetchall()
    if not rows:
        await message.answer("No resellers yet.", reply_markup=admin_panel())
        return
    text = "📋 Resellers\n\n" + "\n".join(f"• `{r[0]}`" for r in rows)
    await message.answer(text, reply_markup=admin_panel())


@dp.message(F.text == "📦 Stock")
async def stock_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    cur.execute(
        """
        SELECT p.id, p.name, c.name, p.stock
        FROM products p
        JOIN categories c ON p.category_id = c.id
        ORDER BY p.id ASC
        """
    )
    rows = cur.fetchall()
    if not rows:
        await message.answer("No products available.", reply_markup=admin_panel())
        return

    text = "📦 Stock List\n\n"
    for pid, name, cat, stock in rows:
        count = len([x for x in stock.splitlines() if x.strip()])
        text += f"#{pid} — {name} [{cat}] | Stock: {count}\n"
    await message.answer(text, reply_markup=admin_panel())


@dp.message(F.text == "🛠 Shop Setup")
async def shop_setup(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "Shop setup is managed by the text commands in this bot.",
        reply_markup=admin_panel(),
    )


# =========================
# CATEGORY / PRODUCT VIEW
# =========================
@dp.message(F.text.startswith("📁 "))
async def open_category(message: Message):
    name = message.text.replace("📁 ", "", 1).strip()
    cid = get_category_id(name)
    if not cid:
        await message.answer("Category not found.")
        return

    text = product_text(cid)
    kb = product_inline_kb(cid)
    if kb:
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(text)


@dp.callback_query(F.data.startswith("buy:"))
async def buy_product(call: CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    row = get_product(pid)
    if not row:
        await call.answer("Product not found", show_alert=True)
        return

    _, _, name, price, stock, cat_name = row
    lines = [x.strip() for x in stock.splitlines() if x.strip()]
    if not lines:
        await call.answer("Out of stock", show_alert=True)
        return

    user_id = call.from_user.id
    ensure_user(user_id)

    bal = get_balance(user_id)
    if bal < price:
        amount_needed = price - bal
        await call.message.answer(
            f"❌ Insufficient balance\n\n"
            f"Product: {name}\n"
            f"Price: ₹{price}\n"
            f"Your balance: ₹{bal}\n"
            f"Need more: ₹{amount_needed}\n\n"
            f"Tap *Add Funds* to top up.",
            reply_markup=payment_action_kb(),
        )
        set_setting(pending_key(user_id), "AMOUNT")
        await send_payment_qr(call.message, amount_needed)
        await call.answer("Insufficient balance", show_alert=True)
        return

    item, rest = consume_stock(stock)
    if not item:
        await call.answer("Out of stock", show_alert=True)
        return

    if not deduct_balance(user_id, price):
        await call.answer("Payment failed", show_alert=True)
        return

    cur.execute("UPDATE products SET stock=? WHERE id=?", (rest, pid))
    conn.commit()

    cur.execute(
        """
        INSERT INTO orders(user_id, product_id, product_name, category_name, price, delivered_item, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            pid,
            name,
            cat_name,
            price,
            item,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    order_id = cur.lastrowid
    remaining_balance = get_balance(user_id)

    await call.message.answer(
        f"✅ Purchased: {name}\n"
        f"Category: {cat_name}\n"
        f"Price: ₹{price}\n"
        f"Order ID: `{order_id}`\n\n"
        f"Delivered item:\n`{item}`"
    )

    await notify_admins_purchase(
        user_id=user_id,
        full_name=call.from_user.full_name,
        username=call.from_user.username or "",
        order_id=order_id,
        product_id=pid,
        product_name=name,
        category_name=cat_name,
        price=price,
        delivered_item=item,
        balance_left=remaining_balance,
    )

    await call.answer("Purchased successfully")


# =========================
# PAYMENT FLOW
# =========================
@dp.callback_query(F.data == "add_funds")
async def add_funds_cb(call: CallbackQuery):
    ensure_user(call.from_user.id)
    set_setting(pending_key(call.from_user.id), "AMOUNT")
    await call.message.answer(
        "Send the amount you want to add, for example: `500`",
        reply_markup=back_kb(),
    )
    await call.answer("Send amount in chat")


@dp.callback_query(F.data == "paid_btn")
async def paid_btn_cb(call: CallbackQuery):

    pending = get_setting(
        pending_key(call.from_user.id),
        ""
    )

    if not pending.startswith("AUTO_VERIFY|"):
        await call.message.answer(
            "❌ No active payment found."
        )
        return

    try:
        _, amount_raw, order_id = pending.split("|", 2)
        amount = int(amount_raw)
    except:
        await call.message.answer(
            "❌ Invalid payment session."
        )
        return

    await call.answer("Checking payment...")

    payment = await verify_fampay_payment(order_id)

    if not payment:
        await call.message.answer(
            "❌ Payment not received yet. Try again after few seconds."
        )
        return

    txn_id = str(
        payment.get("transaction_id")
        or payment.get("utr")
        or order_id
    )

    already = get_setting(f"paid_txn:{txn_id}")

    if already:
        await call.message.answer(
            "⚠️ Payment already processed."
        )
        return

    add_balance(call.from_user.id, amount)

    set_setting(
        f"paid_txn:{txn_id}",
        "1"
    )

    set_setting(
        pending_key(call.from_user.id),
        ""
    )

    sender = payment.get("sender_name", "Unknown")
    utr = payment.get("utr", "N/A")

    balance = get_balance(call.from_user.id)

    await call.message.answer(
        f"✅ Payment Successful\\n\\n"
        f"💰 Amount: ₹{amount}\\n"
        f"👤 Name: {sender}\\n"
        f"🔢 UTR: `{utr}`\\n\\n"
        f"💳 New Balance: ₹{balance}"
    )

    admin_text = (
        f"💰 *New Auto Payment*\\n\\n"
        f"User: {call.from_user.full_name}\\n"
        f"ID: `{call.from_user.id}`\\n"
        f"Username: @{call.from_user.username or 'None'}\\n"
        f"Amount: ₹{amount}\\n"
        f"UTR: `{utr}`\\n"
        f"Status: AUTO VERIFIED"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except:
            pass


# =========================
# GENERAL TEXT ROUTER
# =========================
@dp.message(~F.text)
async def broadcast_media_router(message: Message):
    ensure_user(message.from_user.id)

    if not is_admin(message.from_user.id):
        return

    if get_setting("await_broadcast") != "1":
        return

    set_setting("await_broadcast", "0")
    cur.execute("SELECT user_id FROM users")
    users = [r[0] for r in cur.fetchall()]
    sent = 0
    for uid in users:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
        except Exception:
            pass

    await message.answer(f"Broadcast sent to {sent} users.", reply_markup=admin_panel())


@dp.message(F.text)
async def text_router(message: Message):
    ensure_user(message.from_user.id)
    pending = get_setting(pending_key(message.from_user.id), "")

    # =========================
    # USER PAYMENT FLOW
    # =========================
    if pending == "AMOUNT":
        raw = message.text.strip()
        if not raw.isdigit():
            await message.answer("Send only the amount as a number.", reply_markup=back_kb())
            return

        amount = int(raw)
        if amount <= 0:
            await message.answer("Amount must be greater than zero.", reply_markup=back_kb())
            return

        set_setting(pending_key(message.from_user.id), f"AUTO_PENDING|{amount}")
        await send_payment_qr(message, amount)
        return

        cur.execute(
            "INSERT INTO payment_requests(user_id, amount, utr, status, created_at) VALUES(?, ?, ?, 'pending', ?)",
            (message.from_user.id, amount, utr, datetime.utcnow().isoformat()),
        )
        conn.commit()
        req_id = cur.lastrowid
        set_setting(pending_key(message.from_user.id), "")

        await message.answer(
            f"✅ Payment request submitted.\n"
            f"Request ID: `{req_id}`\n"
            f"Amount: ₹{amount}\n\n"
            f"Wait for admin approval.",
            reply_markup=main_menu(),
        )

        admin_text = (
            f"💰 *New Payment Request*\n\n"
            f"Request ID: `{req_id}`\n"
            f"User ID: `{message.from_user.id}`\n"
            f"Name: {message.from_user.full_name}\n"
            f"Amount: ₹{amount}\n"
            f"UTR: `{utr}`"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Approve", callback_data=f"pay_approve:{req_id}"),
                    InlineKeyboardButton(text="❌ Reject", callback_data=f"pay_reject:{req_id}"),
                ]
            ]
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text, reply_markup=kb)
            except Exception:
                pass
        return

    # =========================
    # ADMIN BROADCAST FOR TEXT
    # =========================
    if is_admin(message.from_user.id) and get_setting("await_broadcast") == "1":
        set_setting("await_broadcast", "0")
        cur.execute("SELECT user_id FROM users")
        users = [r[0] for r in cur.fetchall()]
        sent = 0
        for uid in users:
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
                sent += 1
            except Exception:
                pass
        await message.answer(f"Broadcast sent to {sent} users.", reply_markup=admin_panel())
        return

    # =========================
    # ADMIN ROUTER
    # =========================
    if not is_admin(message.from_user.id):
        return

    if get_setting("await_category") == "1":
        set_setting("await_category", "0")
        name = message.text.strip()
        try:
            cur.execute("INSERT INTO categories(name) VALUES(?)", (name,))
            conn.commit()
            await message.answer(f"Category added: {name}", reply_markup=admin_panel())
        except sqlite3.IntegrityError:
            await message.answer("Category already exists.", reply_markup=admin_panel())
        return

    if get_setting("await_remove_category") == "1":
        set_setting("await_remove_category", "0")
        name = message.text.strip()

        cur.execute("SELECT id FROM categories WHERE name=?", (name,))
        row = cur.fetchone()
        if not row:
            await message.answer("Category not found.", reply_markup=admin_panel())
            return

        cid = row[0]
        cur.execute("DELETE FROM products WHERE category_id=?", (cid,))
        cur.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
        await message.answer(f"Category removed: {name}", reply_markup=admin_panel())
        return

    if get_setting("await_product_meta") == "1":
        parts = [x.strip() for x in message.text.split("|")]
        if len(parts) != 3:
            await message.answer(
                "Invalid format. Use: Category Name | Product Name | Price",
                reply_markup=admin_panel(),
            )
            return

        category_name, product_name, price_raw = parts
        if not price_raw.isdigit():
            await message.answer("Price must be a number.", reply_markup=admin_panel())
            return

        cid = get_category_id(category_name)
        if not cid:
            await message.answer("Category not found.", reply_markup=admin_panel())
            return

        set_setting("await_product_stock", f"{cid}|{product_name}|{price_raw}")
        set_setting("await_product_meta", "0")
        await message.answer("Now send stock lines, one per line.", reply_markup=admin_panel())
        return

    pending_product = get_setting("await_product_stock", "")
    if pending_product and "|" in pending_product:
        try:
            cid, product_name, price_raw = pending_product.split("|", 2)
            cid = int(cid)
            price = int(price_raw)
            stock = message.text.strip()

            cur.execute(
                "INSERT INTO products(category_id, name, price, stock) VALUES(?, ?, ?, ?)",
                (cid, product_name, price, stock),
            )
            conn.commit()
            set_setting("await_product_stock", "")
            await message.answer(f"Product added: {product_name}", reply_markup=admin_panel())
        except Exception as exc:
            set_setting("await_product_stock", "")
            await message.answer(f"Failed to add product: {exc}", reply_markup=admin_panel())
        return

    if get_setting("await_remove_product") == "1":
        set_setting("await_remove_product", "0")
        try:
            pid = int(message.text.strip())
            cur.execute("SELECT name FROM products WHERE id=?", (pid,))
            row = cur.fetchone()
            if not row:
                await message.answer("Product not found.", reply_markup=admin_panel())
                return

            cur.execute("DELETE FROM products WHERE id=?", (pid,))
            conn.commit()
            await message.answer(f"Product removed: #{pid} — {row[0]}", reply_markup=admin_panel())
        except Exception:
            await message.answer("Send a valid product ID.", reply_markup=admin_panel())
        return

    if get_setting("await_change_price") == "1":
        set_setting("await_change_price", "0")
        try:
            pid, new_price = map(int, message.text.split())
            cur.execute("SELECT name, price FROM products WHERE id=?", (pid,))
            row = cur.fetchone()
            if not row:
                await message.answer("Product not found.", reply_markup=admin_panel())
                return

            old_name, old_price = row
            cur.execute("UPDATE products SET price=? WHERE id=?", (new_price, pid))
            conn.commit()

            await message.answer(
                f"Price updated:\n#{pid} — {old_name}\n₹{old_price} → ₹{new_price}",
                reply_markup=admin_panel(),
            )
        except Exception:
            await message.answer("Format: product_id new_price", reply_markup=admin_panel())
        return

    if get_setting("await_add_balance") == "1":
        set_setting("await_add_balance", "0")
        try:
            uid, amt = map(int, message.text.split())
            add_balance(uid, amt)
            await message.answer(f"Added ₹{amt} to {uid}", reply_markup=admin_panel())
        except Exception:
            await message.answer("Format: user_id amount", reply_markup=admin_panel())
        return

    if get_setting("await_add_reseller") == "1":
        set_setting("await_add_reseller", "0")
        try:
            uid = int(message.text.strip())
            ensure_user(uid)
            cur.execute("UPDATE users SET is_reseller=1 WHERE user_id=?", (uid,))
            conn.commit()
            await message.answer(f"Reseller added: {uid}", reply_markup=admin_panel())
        except Exception:
            await message.answer("Invalid user ID.", reply_markup=admin_panel())
        return

    if get_setting("await_remove_reseller") == "1":
        set_setting("await_remove_reseller", "0")
        try:
            uid = int(message.text.strip())
            cur.execute("UPDATE users SET is_reseller=0 WHERE user_id=?", (uid,))
            conn.commit()
            await message.answer(f"Reseller removed: {uid}", reply_markup=admin_panel())
        except Exception:
            await message.answer("Invalid user ID.", reply_markup=admin_panel())
        return


# =========================
# MAIN
# =========================
async def main():
    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
