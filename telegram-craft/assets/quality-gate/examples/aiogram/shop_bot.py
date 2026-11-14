"""Example bot used to demonstrate the quality gate (aiogram 3)."""
from html import escape
from io import BytesIO

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

ITEMS = {i: (f"Template {i}", 10 + i) for i in range(1, 8)}
PAGE_SIZE = 3
MAX_DOWNLOAD = 20_000_000


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


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


async def show(callback, view):
    try:
        await callback.message.edit_text(view[0], reply_markup=view[1])
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


def build_dispatcher():
    router = Router()
    alerts = {}

    @router.message(CommandStart())
    async def start(message: Message):
        text, markup = home()
        await message.answer(text, reply_markup=markup)

    @router.callback_query(F.data == "home")
    async def go_home(callback: CallbackQuery):
        await callback.answer()
        await show(callback, home())

    @router.callback_query(F.data.startswith("cat:"))
    async def open_catalog(callback: CallbackQuery):
        await callback.answer()
        await show(callback, catalog(int(callback.data.split(":")[1])))

    @router.callback_query(F.data.startswith("item:"))
    async def open_item(callback: CallbackQuery):
        _, item_id, page = callback.data.split(":")
        item = ITEMS.get(int(item_id))
        if item is None:
            await callback.answer("This item is no longer available.")
            await show(callback, home())
            return
        await callback.answer()
        await show(callback, (f"<b>{escape(item[0])}</b>\nPrice: {item[1]} Stars", keyboard([(f"Buy for {item[1]} Stars", f"buy:{item_id}")], [("Back", f"cat:{page}")])))

    @router.callback_query(F.data.startswith("buy:"))
    async def buy(callback: CallbackQuery):
        item_id = int(callback.data.split(":")[1])
        await callback.answer()
        await callback.message.answer_invoice(title=ITEMS[item_id][0], description="Editable document template", payload=f"order-{item_id}",
                                              provider_token="", currency="XTR", prices=[LabeledPrice(label="Template", amount=ITEMS[item_id][1])])

    @router.callback_query(F.data == "settings")
    async def open_settings(callback: CallbackQuery):
        await callback.answer()
        await show(callback, settings_view(alerts.get(callback.from_user.id, True)))

    @router.callback_query(F.data == "alerts")
    async def toggle(callback: CallbackQuery):
        alerts[callback.from_user.id] = not alerts.get(callback.from_user.id, True)
        await callback.answer("Saved")
        await show(callback, settings_view(alerts[callback.from_user.id]))

    @router.callback_query(F.data == "reset:ask")
    async def reset_ask(callback: CallbackQuery):
        await callback.answer()
        await show(callback, ("<b>Reset settings?</b>\nAlerts return to On.", keyboard([("Keep settings", "settings")], [("Reset settings now", "reset:confirm")])))

    @router.callback_query(F.data == "reset:confirm")
    async def reset_do(callback: CallbackQuery):
        alerts.pop(callback.from_user.id, None)
        await callback.answer("Settings reset")
        await show(callback, settings_view(True))

    @router.callback_query()
    async def unknown(callback: CallbackQuery):
        await callback.answer("This menu expired.")
        await show(callback, home())

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery):
        item = ITEMS.get(int(query.invoice_payload.split("-")[1]))
        if item is None or query.total_amount != item[1]:
            await query.answer(ok=False, error_message="This price changed. Open the catalog and try again.")
        else:
            await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def paid(message: Message):
        payment = message.successful_payment
        await message.answer(f"<b>Receipt</b>\nPaid: {payment.total_amount} Stars\nRef: <code>{escape(payment.telegram_payment_charge_id)}</code>\nHelp: /paysupport")

    @router.message(F.document)
    async def convert(message: Message):
        document = message.document
        name = escape(document.file_name or "file")
        if (document.file_size or 0) > MAX_DOWNLOAD:
            await message.answer(f"{name} is too large. I can download files up to 20 MB.")
            return
        status = await message.answer(f"Converting {name}…")
        buffer = BytesIO()
        await message.bot.download(document, destination=buffer)
        await message.answer_document(BufferedInputFile(buffer.getvalue().upper(), "converted.txt"), caption=f"Converted {name}")
        await status.delete()

    @router.message(F.text)
    async def fallback(message: Message):
        await message.answer("I need a file or a command. Send /start to open the menu.")

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
