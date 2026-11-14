"""Example bot used to demonstrate the quality gate (python-telegram-bot)."""
from html import escape
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

ITEMS = {i: (f"Template {i}", 10 + i) for i in range(1, 8)}
PAGE_SIZE = 3
MAX_DOWNLOAD = 20_000_000
HTML = ParseMode.HTML


def keyboard(*rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def home():
    return "<b>Template store</b>\nBuy document templates and manage alerts.", keyboard([("Browse catalog", "cat:0")], [("Settings", "settings")])


def catalog(page):
    ids = sorted(ITEMS)
    pages = (len(ids) - 1) // PAGE_SIZE
    page = max(0, min(page, pages))
    rows = [[(ITEMS[i][0], f"item:{i}:{page}")] for i in ids[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]]
    nav = ([("Previous", f"cat:{page - 1}")] if page else []) + ([("Next page", f"cat:{page + 1}")] if page < pages else [])
    return f"<b>Catalog</b>\nPage {page + 1} of {pages + 1}", keyboard(*rows, *([nav] if nav else []), [("Back", "home")])


def settings_view(alerts):
    state = "On" if alerts else "Off"
    return f"<b>Settings</b>\nAlerts: {state}", keyboard([(f"Turn alerts {'off' if alerts else 'on'}", "alerts")], [("Reset settings", "reset:ask")], [("Back", "home")])


async def show(query, view):
    try:
        await query.edit_message_text(view[0], reply_markup=view[1], parse_mode=HTML)
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = home()
    await update.message.reply_text(text, reply_markup=markup, parse_mode=HTML)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    alerts = context.user_data.get("alerts", True)
    if data == "home":
        await query.answer()
        await show(query, home())
    elif data.startswith("cat:"):
        await query.answer()
        await show(query, catalog(int(data.split(":")[1])))
    elif data.startswith("item:"):
        _, item_id, page = data.split(":")
        item = ITEMS.get(int(item_id))
        if item is None:
            await query.answer("This item is no longer available.")
            await show(query, home())
            return
        await query.answer()
        await show(query, (f"<b>{escape(item[0])}</b>\nPrice: {item[1]} Stars", keyboard([(f"Buy for {item[1]} Stars", f"buy:{item_id}")], [("Back", f"cat:{page}")])))
    elif data.startswith("buy:"):
        item_id = int(data.split(":")[1])
        await query.answer()
        await query.message.reply_invoice(title=ITEMS[item_id][0], description="Editable document template", payload=f"order-{item_id}",
                                          provider_token="", currency="XTR", prices=[LabeledPrice("Template", ITEMS[item_id][1])])
    elif data == "settings":
        await query.answer()
        await show(query, settings_view(alerts))
    elif data == "alerts":
        context.user_data["alerts"] = not alerts
        await query.answer("Saved")
        await show(query, settings_view(not alerts))
    elif data == "reset:ask":
        await query.answer()
        await show(query, ("<b>Reset settings?</b>\nAlerts return to On.", keyboard([("Keep settings", "settings")], [("Reset settings now", "reset:confirm")])))
    elif data == "reset:confirm":
        context.user_data.pop("alerts", None)
        await query.answer("Settings reset")
        await show(query, settings_view(True))
    else:
        await query.answer("This menu expired.")
        await show(query, home())


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    item = ITEMS.get(int(query.invoice_payload.split("-")[1]))
    if item is None or query.total_amount != item[1]:
        await query.answer(ok=False, error_message="This price changed. Open the catalog and try again.")
    else:
        await query.answer(ok=True)


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    await update.message.reply_text(f"<b>Receipt</b>\nPaid: {payment.total_amount} Stars\nRef: <code>{escape(payment.telegram_payment_charge_id)}</code>\nHelp: /paysupport", parse_mode=HTML)


async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    name = escape(document.file_name or "file")
    if (document.file_size or 0) > MAX_DOWNLOAD:
        await update.message.reply_text(f"{name} is too large. I can download files up to 20 MB.")
        return
    status = await update.message.reply_text(f"Converting {name}…")
    file = await document.get_file()
    data = await file.download_as_bytearray()
    await update.message.reply_document(BytesIO(bytes(data).upper()), filename="converted.txt", caption=f"Converted {name}")
    await status.delete()


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I need a file or a command. Send /start to open the menu.")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.add_handler(MessageHandler(filters.Document.ALL, convert))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
