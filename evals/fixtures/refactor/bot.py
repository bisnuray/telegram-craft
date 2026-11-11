import asyncio, os, sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

dp = Dispatcher()
db = sqlite3.connect(os.environ.get("DB_PATH", "notes.db"))
db.execute("create table if not exists notes(id integer primary key, user integer, text text)")
FREE_LIMIT = 5
ADMIN = 777


def kb(note_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Delete", callback_data=f"del:{note_id}")]])


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Send /add <text> to save a note, /list to see notes.")


@dp.message(Command("add"))
async def add(m: Message):
    text = (m.text or "").partition(" ")[2].strip()
    if not text:
        await m.answer("Usage: /add <text>")
        return
    count = db.execute("select count(*) from notes where user=?", (m.from_user.id,)).fetchone()[0]
    if count >= FREE_LIMIT and m.from_user.id != ADMIN:
        await m.answer(f"Limit reached: {FREE_LIMIT} notes.")
        return
    cur = db.execute("insert into notes(user, text) values(?, ?)", (m.from_user.id, text))
    db.commit()
    await m.answer(f"Saved #{cur.lastrowid}", reply_markup=kb(cur.lastrowid))


@dp.message(Command("list"))
async def list_notes(m: Message):
    rows = db.execute("select id, text from notes where user=? order by id", (m.from_user.id,)).fetchall()
    if not rows:
        await m.answer("No notes yet.")
        return
    for note_id, text in rows:
        await m.answer(f"#{note_id}: {text}", reply_markup=kb(note_id))


@dp.callback_query(F.data.startswith("del:"))
async def delete(c: CallbackQuery):
    note_id = int(c.data.split(":")[1])
    row = db.execute("select user from notes where id=?", (note_id,)).fetchone()
    if row is None:
        await c.answer("Already deleted.")
        return
    if row[0] != c.from_user.id and c.from_user.id != ADMIN:
        await c.answer("Not your note.", show_alert=True)
        return
    db.execute("delete from notes where id=?", (note_id,))
    db.commit()
    await c.answer("Deleted.")
    await c.message.edit_reply_markup(reply_markup=None)


async def main():
    await dp.start_polling(Bot(os.environ["BOT_TOKEN"]))

if __name__ == "__main__":
    asyncio.run(main())
