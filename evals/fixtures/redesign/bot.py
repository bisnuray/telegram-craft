"""Support bot for an online course school. Business rules must not change."""
import asyncio, os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as K, Message

dp = Dispatcher()
COURSES = {"py": ("Python Basics", 49, 12), "ds": ("Data Science", 129, 24)}


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(
        f"🎉🎉🎉 WELCOME {m.from_user.first_name.upper()} TO THE AMAZING LEARNING BOT!!! 🎉🎉🎉\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🚀 I am your AI-powered learning assistant and I'm here to help you on your journey!\n"
        "✨ Feel free to explore all of our amazing features below!\n"
        "💎 Premium courses  🔥 Expert teachers  🎯 Great results\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "👇👇👇 PLEASE CHOOSE AN OPTION 👇👇👇",
        reply_markup=K(inline_keyboard=[
            [B(text="📚 Courses 📚", callback_data="courses")],
            [B(text="💬 Support 💬", callback_data="support")],
        ]),
    )


@dp.callback_query(F.data == "courses")
async def courses(c: CallbackQuery):
    await c.answer()
    text = "📚📚 HERE ARE ALL OUR COURSES!!! 📚📚\n\n"
    for key, (name, price, lessons) in COURSES.items():
        text += f"🔥 {name} 🔥\n💰 Price: ${price}\n📖 Lessons: {lessons}\n━━━━━━━━\n"
    await c.message.answer(text, reply_markup=K(inline_keyboard=[
        [B(text=name, callback_data=f"course:{key}")] for key, (name, _, _) in COURSES.items()
    ]))


@dp.callback_query(F.data.startswith("course:"))
async def course(c: CallbackQuery):
    await c.answer()
    name, price, lessons = COURSES[c.data.split(":")[1]]
    await c.message.answer(
        f"✅✅ Course selected successfully! ✅✅\n\nYou have selected the course {name}. This course costs ${price} "
        f"and it has {lessons} lessons. Refunds are available within 14 days of purchase. "
        "Please press the button below in order to enroll in this amazing course!",
        reply_markup=K(inline_keyboard=[[B(text="OK", callback_data=f"enroll:{c.data.split(':')[1]}")]]),
    )


@dp.callback_query(F.data.startswith("enroll:"))
async def enroll(c: CallbackQuery):
    await c.answer()
    await c.message.answer("🎉🎉 Success!!! Your request has been processed successfully! 🎉🎉 An operator will contact you within 24 hours.")


@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery):
    await c.answer()
    await c.message.answer("💬 Please wait... ⏳ Our support team is available Mon-Fri 9:00-18:00 at support@example.com")


@dp.message(F.text)
async def fallback(m: Message):
    await m.answer("❌ ERROR!!! Something went wrong! Invalid input! Please try again later! ❌")


async def main():
    await dp.start_polling(Bot(os.environ["BOT_TOKEN"]))

if __name__ == "__main__":
    asyncio.run(main())
