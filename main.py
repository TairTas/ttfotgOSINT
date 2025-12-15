import asyncio
import logging
import json
from aiohttp import web  # <--- ДОБАВЛЕНО ДЛЯ RENDER
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from supabase import create_client, Client

# --- ВАШИ ДАННЫЕ ---
SUPABASE_URL = "https://tdhupjntuqgzmohyobdr.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRkaHVwam50dXFnem1vaHlvYmRyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjU4MTY1NjEsImV4cCI6MjA4MTM5MjU2MX0.j9RV2dZuPiOQdQV2UFnJMeO1F37neJ-Qy09ea4anQpw"
BOT_TOKEN = "8490895113:AAE24bqoOc7YL4P8Ls5EjsCdOcsytxy49QA"
CHANNEL_ID = "-1003591773124"  # <-- !!! ОБЯЗАТЕЛЬНО ВПИШИТЕ СЮДА ID КАНАЛА !!!
ADMIN_USERNAME = "ttfotg"  # Ваш ник (без @), для доступа к кнопке обновления

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (ДОБАВЛЕНО) ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render требует слушать 0.0.0.0 и порт 8080
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

# --- СОСТОЯНИЯ ---
class Registration(StatesGroup):
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_phone = State()

class Search(StatesGroup):
    waiting_for_query = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def log_to_db(user: types.User, text: str):
    """Логирование действий пользователя"""
    try:
        supabase.table("chat_logs").insert({
            "user_tg_id": user.id,
            "username": user.username or "no_username",
            "message_text": text
        }).execute()
    except Exception as e:
        print(f"Ошибка лога: {e}")

def format_user_text(user_data):
    """Формирует текст анкеты для канала"""
    # Если данные пустые, ставим прочерк или дефолтный текст
    phone = user_data.get('phone') or "нет"
    email = user_data.get('email') or "нет"
    username = user_data.get('username') or "нет"
    first_name = user_data.get('first_name') or "Без имени"
    tg_id = user_data.get('tg_id')
    search_count = user_data.get('search_count', 0)

    return (
        f"🆕 <b>ПОЛЬЗОВАТЕЛЬ</b>\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"👤 Имя: {first_name}\n"
        f"🔗 Ник: @{username}\n"
        f"🆔 ID: <code>{tg_id}</code>\n"
        f"📧 Email: {email}\n"
        f"📱 Тел: {phone}\n"
        f"📊 Поисков: {search_count}"
    )

async def send_or_update_channel_message(user_data: dict):
    """
    Отправляет или обновляет сообщение в канале.
    """
    msg_text = format_user_text(user_data)
    tg_id = user_data['tg_id']
    msg_id = user_data.get('channel_message_id')

    try:
        if msg_id:
            # Если ID есть, пробуем редактировать
            try:
                await bot.edit_message_text(chat_id=CHANNEL_ID, message_id=msg_id, text=msg_text, parse_mode="HTML")
            except Exception as ex:
                if "message is not modified" in str(ex):
                    pass # Текст не изменился, всё ок
                else:
                    print(f"Ошибка редактирования (ID {tg_id}): {ex}")
        else:
            # Если ID нет, отправляем новое
            new_msg = await bot.send_message(CHANNEL_ID, msg_text, parse_mode="HTML")
            # Сохраняем ID сообщения в базу
            supabase.table("users").update({
                "channel_message_id": new_msg.message_id,
                "is_sent_to_channel": True
            }).eq("tg_id", tg_id).execute()
            
    except Exception as e:
        print(f"Ошибка канала для {tg_id}: {e}")

# --- КЛАВИАТУРЫ ---
def get_main_keyboard(user_username: str, is_registered: bool):
    kb = []
    # Меню пользователя
    if is_registered:
        kb.append([KeyboardButton(text="🔍 Поиск людей"), KeyboardButton(text="👤 Мой профиль")])
    else:
        kb.append([KeyboardButton(text="📝 Регистрация")])

    # Меню админа
    if user_username == ADMIN_USERNAME:
        kb.append([KeyboardButton(text="📂 Экспорт JSON"), KeyboardButton(text="🔄 Обновить канал")])

    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
phone_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Отправить мой номер телефона", request_contact=True)], [KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# --- АДМИНСКИЕ ФУНКЦИИ ---

@dp.message(F.text == "📂 Экспорт JSON")
async def admin_export_json(message: types.Message):
    if message.from_user.username != ADMIN_USERNAME: return
    
    await message.answer("⏳ Выгружаю базу...")
    try:
        users = supabase.table("users").select("*").execute().data
        json_str = json.dumps(users, indent=4, ensure_ascii=False)
        file = BufferedInputFile(json_str.encode('utf-8'), filename="users_export.json")
        await message.answer_document(document=file, caption=f"Пользователей: {len(users)}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text == "🔄 Обновить канал")
async def admin_sync_channel(message: types.Message):
    if message.from_user.username != ADMIN_USERNAME: return

    await message.answer("⏳ Начинаю синхронизацию... Это может занять время.")
    
    try:
        # ИСПРАВЛЕНИЕ ОШИБКИ: Сначала берем всех, фильтруем в Python
        all_users = supabase.table("users").select("*").execute().data
        
        # Оставляем только тех, у кого есть channel_message_id (кто уже в канале)
        users_in_channel = [u for u in all_users if u.get('channel_message_id')]
        
        count = 0
        for u in users_in_channel:
            await send_or_update_channel_message(u)
            count += 1
            await asyncio.sleep(0.3) # Анти-спам задержка
            
        await message.answer(f"✅ Готово! Обновлено записей: {count}")
        
    except Exception as e:
        await message.answer(f"Ошибка синхронизации: {e}")


# --- ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЯ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    await log_to_db(user, "/start")
    
    data = {"tg_id": user.id, "username": user.username, "first_name": user.first_name}
    try:
        res = supabase.table("users").upsert(data, on_conflict="tg_id").execute()
        is_registered = bool(res.data[0].get('email'))
        
        await message.answer(
            f"Привет, {user.first_name}!", 
            reply_markup=get_main_keyboard(user.username, is_registered)
        )
    except Exception as e:
        await message.answer(f"Ошибка соединения: {e}")

# --- РЕГИСТРАЦИЯ ---
@dp.message(F.text == "📝 Регистрация")
async def start_reg(message: types.Message, state: FSMContext):
    await message.answer("Шаг 1. Введите Email:", reply_markup=cancel_kb)
    await state.set_state(Registration.waiting_for_email)

@dp.message(Registration.waiting_for_email)
async def reg_email(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": await state.clear(); return
    await state.update_data(email=message.text)
    await message.answer("Шаг 2. Введите пароль:")
    await state.set_state(Registration.waiting_for_password)

@dp.message(Registration.waiting_for_password)
async def reg_pass(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": await state.clear(); return
    await state.update_data(password=message.text)
    await message.answer("Шаг 3. Отправьте телефон кнопкой:", reply_markup=phone_kb)
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def reg_phone(message: types.Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
        data = await state.get_data()
        tg_id = message.from_user.id
        
        try:
            supabase.table("users").update({
                "email": data['email'], "password": data['password'], "phone": phone
            }).eq("tg_id", tg_id).execute()
            
            full_user = supabase.table("users").select("*").eq("tg_id", tg_id).execute().data[0]
            
            await message.answer("✅ Регистрация завершена!", 
                                 reply_markup=get_main_keyboard(message.from_user.username, True))
            await state.clear()
            await send_or_update_channel_message(full_user)
        except Exception as e:
            await message.answer(f"Ошибка записи: {e}")
            
    elif message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отмена.", reply_markup=get_main_keyboard(message.from_user.username, False))

# --- ПОИСК (ИСПРАВЛЕНО) ---
@dp.message(F.text == "🔍 Поиск людей")
async def start_search(message: types.Message, state: FSMContext):
    await message.answer("Введите запрос (Имя, ID, Телефон):", reply_markup=cancel_kb)
    await state.set_state(Search.waiting_for_query)

@dp.message(Search.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": 
        await state.clear()
        await message.answer("Поиск отменен", reply_markup=get_main_keyboard(message.from_user.username, True))
        return
    
    query = message.text
    await log_to_db(message.from_user, f"ПОИСК: {query}")
    
    try:
        # Увеличиваем счетчик поиска
        curr = supabase.table("users").select("search_count").eq("tg_id", message.from_user.id).execute()
        new_c = (curr.data[0].get('search_count') or 0) + 1
        supabase.table("users").update({"search_count": new_c}).eq("tg_id", message.from_user.id).execute()

        # Формируем запрос поиска
        filter_str = (
            f"username.ilike.%{query}%,"
            f"first_name.ilike.%{query}%,"
            f"phone.ilike.%{query}%,"
            f"email.ilike.%{query}%"
        )
        if query.isdigit():
            filter_str += f",tg_id.eq.{query}"
        
        # Выполняем поиск
        response = supabase.table("users").select("*").or_(filter_str).execute()
        found_users = response.data
        
        if not found_users:
            await message.answer("Ничего не найдено 😔")
        else:
            await message.answer(f"Найдено результатов: {len(found_users)}")
            
            # Вывод результатов (КРАСИВЫЙ ФОРМАТ)
            for u in found_users[:5]: # Максимум 5 карточек
                card_text = (
                    f"👤 {u.get('first_name', 'Без имени')} | @{u.get('username', '---')}\n"
                    f"🆔 <b>ID:</b> <code>{u.get('tg_id')}</code>\n"
                    f"📱 {u.get('phone', '---')}\n"
                    f"📧 {u.get('email', '---')}"
                )
                await message.answer(card_text, parse_mode="HTML")
                
        await state.clear()
        # Возвращаем клавиатуру
        await message.answer("Что делаем дальше?", reply_markup=get_main_keyboard(message.from_user.username, True))

    except Exception as e:
        await message.answer(f"Ошибка поиска: {e}")
        await state.clear()

# --- ПРОФИЛЬ ---
@dp.message(F.text == "👤 Мой профиль")
async def cmd_profile(message: types.Message):
    try:
        u = supabase.table("users").select("*").eq("tg_id", message.from_user.id).execute().data[0]
        text = (
            f"👤 <b>ВАШ ПРОФИЛЬ</b>\n"
            f"ID: <code>{u['tg_id']}</code>\n"
            f"Email: {u.get('email')}\n"
            f"Тел: {u.get('phone')}\n"
            f"Поисков: {u.get('search_count')}"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard(message.from_user.username, True))
    except: pass

# --- ЗАПУСК ---
async def main():
    print("Бот запускается + Веб-сервер...")
    
    # Проверка "неотправленных" при старте (ТВОЯ ЛОГИКА)
    try:
        all_users = supabase.table("users").select("*").execute().data
        # Находим тех, кто зареган (есть email), но нет channel_message_id (не отправлен)
        unsent = [u for u in all_users if u.get('email') and not u.get('channel_message_id')]
        
        if unsent:
            print(f"Досылаю {len(unsent)} анкет в канал...")
            for u in unsent:
                await send_or_update_channel_message(u)
                await asyncio.sleep(1)
    except Exception as e:
        print(f"Ошибка при старте: {e}")

    # ЗАПУСКАЕМ ПАРАЛЛЕЛЬНО БОТА И ВЕБ-СЕРВЕР (ДЛЯ RENDER)
    await asyncio.gather(
        dp.start_polling(bot),
        start_web_server()
    )

if __name__ == "__main__":
    asyncio.run(main())