"""Task manager bot. Storage is in-memory for this exercise."""
import asyncio, os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as K, Message

dp = Dispatcher()
TASKS = {uid: {"title": f"Task {uid}", "done": False} for uid in range(1, 38)}
OWNER = {uid: 1000 for uid in TASKS}


def menu():
    return K(inline_keyboard=[[
        B(text="Tasks", callback_data="list"), B(text="Add a brand new task to your list", callback_data="add"),
        B(text="Statistics overview", callback_data="stats"), B(text="Settings", callback_data="settings"),
    ]])


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Menu", reply_markup=menu())


@dp.callback_query(F.data == "list")
async def list_tasks(c: CallbackQuery):
    await c.answer()
    rows = [[B(text=t["title"], callback_data=f"open:{i}")] for i, t in TASKS.items()]
    await c.message.answer("All tasks", reply_markup=K(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("open:"))
async def open_task(c: CallbackQuery):
    await c.answer()
    i = int(c.data.split(":")[1])
    await c.message.answer(TASKS[i]["title"], reply_markup=K(inline_keyboard=[
        [B(text="Yes", callback_data=f"done:{i}"), B(text="No", callback_data=f"del:{i}")],
    ]))


@dp.callback_query(F.data.startswith("done:"))
async def done(c: CallbackQuery):
    await c.answer()
    TASKS[int(c.data.split(":")[1])]["done"] = True
    await c.message.answer("Done")


@dp.callback_query(F.data.startswith("del:"))
async def delete(c: CallbackQuery):
    await c.answer()
    del TASKS[int(c.data.split(":")[1])]
    await c.message.answer("Deleted")


async def main():
    await dp.start_polling(Bot(os.environ["BOT_TOKEN"]))

if __name__ == "__main__":
    asyncio.run(main())
