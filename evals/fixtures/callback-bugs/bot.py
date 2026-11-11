"""Small shop bot. Users report: some buttons spin forever, 'Купить' does nothing
for some products, the catalog button sometimes errors in the logs, and one
product name crashes the screen."""
import asyncio, os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as K, Message

dp = Dispatcher()
router = Router()
general = Router()
PRODUCTS = {
    1: {"name": "Чехол для телефона", "price": 500, "stock": 3},
    2: {"name": "Кабель <USB-C> & адаптер", "price": 300, "stock": 0},
    3: {"name": "Зарядное устройство повышенной мощности", "price": 900, "stock": 5},
}


def catalog_kb():
    return K(inline_keyboard=[[B(text=p["name"], callback_data=f"product:{i}")] for i, p in PRODUCTS.items()]
             + [[B(text="Обновить", callback_data="catalog")]])


@general.callback_query()
async def anything(c: CallbackQuery):
    await c.answer("Неизвестная команда")


@router.message(CommandStart())
async def start(m: Message):
    await m.answer("Каталог", reply_markup=catalog_kb())


@router.callback_query(F.data == "catalog")
async def catalog(c: CallbackQuery):
    await c.message.edit_text("Каталог", reply_markup=catalog_kb())
    await c.answer()


@router.callback_query(F.data.startswith("product:"))
async def product(c: CallbackQuery):
    p = PRODUCTS[int(c.data.split(":")[1])]
    if p["stock"] == 0:
        return
    await c.message.edit_text(
        f"<b>{p['name']}</b>\nЦена: {p['price']} ₽", parse_mode="HTML",
        reply_markup=K(inline_keyboard=[
            [B(text="Купить", callback_data=f"buy:{p['name']}:{p['price']}")],
            [B(text="Назад", callback_data="catalog")],
        ]),
    )
    await c.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    _, name, price = c.data.split(":")
    await c.answer(f"Заказ: {name} за {price} ₽", show_alert=True)


async def main():
    dp.include_router(general)
    dp.include_router(router)
    await dp.start_polling(Bot(os.environ["BOT_TOKEN"]))

if __name__ == "__main__":
    asyncio.run(main())
