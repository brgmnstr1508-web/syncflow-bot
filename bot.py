import logging
import os
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from dotenv import load_dotenv
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Инициализация GigaChat ---
giga = GigaChat(
    credentials=GIGACHAT_AUTH_KEY,
    scope=GIGACHAT_SCOPE,
    verify_ssl_certs=False,
    model="GigaChat-3-Ultra"  # Оставляем базовую модель, так как GigaChat-3-Ultra может быть недоступна
)


# ============================================
# БАЗА ДАННЫХ
# ============================================

def save_message(chat_id, user_name, text):
    messages = []
    if os.path.exists('messages.json'):
        try:
            with open('messages.json', 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    messages = json.loads(content)
        except:
            messages = []

    messages.append({
        'chat_id': chat_id,
        'user': user_name,
        'text': text,
        'time': datetime.now().isoformat()
    })
    with open('messages.json', 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)


def get_recent_messages(hours=24):
    if not os.path.exists('messages.json'):
        return []
    try:
        with open('messages.json', 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            all_messages = json.loads(content)
    except:
        return []

    threshold = datetime.now() - timedelta(hours=hours)
    recent = []
    for msg in all_messages:
        try:
            msg_time = datetime.fromisoformat(msg['time'])
            if msg_time > threshold:
                recent.append(msg)
        except:
            continue
    return recent


# ============================================
# ПОДПИСЧИКИ
# ============================================

def load_users():
    if not os.path.exists('users.json'):
        save_users([])
        return []

    try:
        with open('users.json', 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                save_users([])
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("⚠️ users.json поврежден, создаю новый")
        save_users([])
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки users.json: {e}")
        save_users([])
        return []


def save_users(users):
    with open('users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)


def add_user(chat_id):
    users = load_users()
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)
        return True
    return False


def remove_user(chat_id):
    users = load_users()
    if chat_id in users:
        users.remove(chat_id)
        save_users(users)
        return True
    return False


APP_INSTANCE = None


def format_digest(text):
    lines = text.split('\n')
    formatted_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(('•', '-', '✅', '📌', '*', '1.', '2.', '3.', '4.', '5.', '—')):
            formatted_lines.append(line)
        else:
            formatted_lines.append(f'• {line}')
    return '\n'.join(formatted_lines)


# ============================================
# ОТПРАВКА ДАЙДЖЕСТА
# ============================================

async def send_daily_digest(app: Application = None):
    global APP_INSTANCE

    logger.info("📢 ЗАПУЩЕНА ФУНКЦИЯ send_daily_digest()")

    if app is None:
        app = APP_INSTANCE

    if app is None:
        logger.error("❌ APP_INSTANCE не инициализирован")
        return

    users = load_users()
    logger.info(f"📊 Загружено подписчиков: {len(users)}")

    if not users:
        logger.warning("❌ Нет подписчиков!")
        return

    recent_messages = get_recent_messages(24)
    logger.info(f"📝 Найдено сообщений за 24 часа: {len(recent_messages)}")

    if not recent_messages:
        for user_id in users:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text="🌅 **Доброе утро!**\n\nЗа последние 24 часа не было ни одного сообщения."
                )
                logger.info(f"✅ Отправлено пустое сообщение {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки: {e}")
        return

    messages_text = ""
    for msg in recent_messages[-30:]:
        messages_text += f"{msg['user']}: {msg['text']}\n"

    system_prompt = "Выдели задачи из диалога. Укажи исполнителя, действие и срок. Отвечай кратко, каждую задачу с новой строки."
    user_prompt = f"Переписка за сутки:\n\n{messages_text}\n\nВыдели задачи."

    try:
        logger.info("🔄 Отправляю запрос в GigaChat...")
        request = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system_prompt),
                Messages(role=MessagesRole.USER, content=user_prompt)
            ],
            temperature=0.7,
            max_tokens=500
        )
        response = giga.chat(request)
        ai_reply = response.choices[0].message.content
        formatted_reply = format_digest(ai_reply)

        for user_id in users:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=f"🌅 **Дайджест:**\n\n{formatted_reply}"
                )
                logger.info(f"✅ Дайджест отправлен {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки {user_id}: {e}")

    except Exception as e:
        logger.error(f"❌ Ошибка GigaChat: {e}")


# ============================================
# КОМАНДЫ
# ============================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("✅ /start")
    await update.message.reply_text(
        "👋 Привет! Я умный Хаос-менеджер.\n\n"
        "📌 **Команды:**\n"
        "/subscribe — подписаться на дайджест\n"
        "/unsubscribe — отписаться\n"
        "/status — проверить подписку\n"
        "/digest — получить дайджест сейчас\n"
        "/test — тестовый дайджест"
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"✅ /subscribe от {chat_id}")
    if add_user(chat_id):
        await update.message.reply_text("✅ Вы подписались на утренний дайджест!")
    else:
        await update.message.reply_text("⚠️ Вы уже подписаны!")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"✅ /unsubscribe от {chat_id}")
    if remove_user(chat_id):
        await update.message.reply_text("❌ Вы отписались от дайджеста!")
    else:
        await update.message.reply_text("⚠️ Вы не были подписаны!")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"✅ /status от {chat_id}")
    users = load_users()
    if chat_id in users:
        await update.message.reply_text("✅ Вы **подписаны** на утренний дайджест!")
    else:
        await update.message.reply_text("❌ Вы **не подписаны** на дайджест.\nНапишите /subscribe")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("✅ /test")
    await update.message.reply_text("🧪 Отправляю тестовый дайджест...")
    await send_daily_digest()


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("✅ /digest")
    await update.message.reply_text("🧠 Обрабатываю последние сообщения...")

    recent_messages = get_recent_messages(48)
    if not recent_messages:
        await update.message.reply_text("За последние 48 часов нет сообщений.")
        return

    messages_text = ""
    for msg in recent_messages[-30:]:
        messages_text += f"{msg['user']}: {msg['text']}\n"

    system_prompt = "Выдели задачи из переписки. Укажи исполнителя, действие и срок. Отвечай кратко, каждую задачу с новой строки."
    user_prompt = f"Переписка:\n\n{messages_text}\n\nВыдели задачи."

    try:
        request = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system_prompt),
                Messages(role=MessagesRole.USER, content=user_prompt)
            ],
            temperature=0.7,
            max_tokens=500
        )
        response = giga.chat(request)
        ai_reply = response.choices[0].message.content
        formatted_reply = format_digest(ai_reply)

        await update.message.reply_text(f"📋 **Дайджест:**\n\n{formatted_reply}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


# ============================================
# ОБРАБОТЧИК ТЕКСТА (ГЛАВНАЯ ФУНКЦИЯ!)
# ============================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет все текстовые сообщения (кроме команд) с логированием"""
    if update.message and update.message.text:
        text = update.message.text
        user_name = update.message.from_user.first_name
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id
        chat_type = update.message.chat.type

        # Логируем ВСЕ сообщения
        logger.info(f"🔍 ВИЖУ СООБЩЕНИЕ: от {user_name} (ID: {user_id}) в чате {chat_id} (тип: {chat_type}): {text[:50]}...")

        # Сохраняем только если это НЕ команда
        if not text.startswith('/'):
            save_message(chat_id, user_name, text)
            logger.info(f"📩 Сохранено в БД: {user_name}: {text[:50]}...")


# ============================================
# ЗАПУСК
# ============================================

def main():
    global APP_INSTANCE

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )

    app = Application.builder().token(TOKEN).request(request).build()
    APP_INSTANCE = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("digest", cmd_digest))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    scheduler = BackgroundScheduler()

    # Тестовый запуск через 30 секунд
    scheduler.add_job(
        send_daily_digest,
        'interval',
        seconds=30,
        args=[app],
        id='test_digest',
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=30)
    )
    print("🧪 Тестовый дайджест запланирован через 30 секунд")

    # Регулярный запуск в 9:00
    scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=9, minute=0),
        args=[app],
        id='daily_digest',
        replace_existing=True
    )
    print("⏰ Автоматический дайджест запланирован на 9:00 утра")

    scheduler.start()

    print("🚀 Бот SyncFlow с GigaChat запущен!")
    print("📌 Команды:")
    print("   /start - приветствие")
    print("   /subscribe - подписаться на дайджест")
    print("   /unsubscribe - отписаться")
    print("   /status - проверить подписку")
    print("   /test - тестовый дайджест")
    print("   /digest - получить дайджест сейчас")

    app.run_polling()


if __name__ == '__main__':
    main()