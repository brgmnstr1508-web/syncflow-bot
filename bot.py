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
import asyncio
import re

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# ИНИЦИАЛИЗАЦИЯ GIGACHAT
# ============================================

giga = GigaChat(
    credentials=GIGACHAT_AUTH_KEY,
    scope=GIGACHAT_SCOPE,
    verify_ssl_certs=False,
    model="GigaChat-3-Ultra"
)

# ============================================
# РАБОТА С КОНФИГУРАЦИЕЙ (НАСТРОЙКИ ЧАТОВ)
# ============================================

CONFIG_FILE = "config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except:
        return {}


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def get_config_for_chat(chat_id):
    config = load_config()
    return config.get(str(chat_id), {})


def set_config_for_chat(chat_id, key, value):
    config = load_config()
    if str(chat_id) not in config:
        config[str(chat_id)] = {}
    config[str(chat_id)][key] = value
    save_config(config)


# ============================================
# БАЗА ДАННЫХ (РАЗДЕЛЬНО ПО ЧАТАМ)
# ============================================

def get_messages_file(chat_id):
    return f"messages_{chat_id}.json"


def save_message(chat_id, user_name, text):
    filename = get_messages_file(chat_id)

    messages = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    messages = json.loads(content)
        except:
            messages = []

    messages.append({
        'user': user_name,
        'text': text,
        'time': datetime.now().isoformat()
    })

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)


def get_recent_messages(chat_id, hours=24):
    filename = get_messages_file(chat_id)

    if not os.path.exists(filename):
        return []

    try:
        with open(filename, 'r', encoding='utf-8') as f:
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
# СИСТЕМА ЗАДАЧ
# ============================================

TASKS_FILE = "tasks.json"


def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except:
        return []


def save_tasks(tasks):
    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=4)


def get_next_task_id(tasks):
    if not tasks:
        return 1
    return max(t['id'] for t in tasks) + 1


def add_task(text, assignee, deadline, chat_id):
    tasks = load_tasks()
    task = {
        'id': get_next_task_id(tasks),
        'text': text,
        'assignee': assignee,
        'deadline': deadline,
        'status': 'active',
        'created_at': datetime.now().isoformat(),
        'chat_id': chat_id
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def get_tasks_by_chat(chat_id, status=None):
    tasks = load_tasks()
    filtered = [t for t in tasks if t.get('chat_id') == chat_id]
    if status:
        filtered = [t for t in filtered if t.get('status') == status]
    return filtered


def get_active_tasks(chat_id):
    tasks = get_tasks_by_chat(chat_id, 'active')
    today = datetime.now().date()
    active = []
    overdue = []
    for t in tasks:
        try:
            deadline = datetime.strptime(t['deadline'], '%Y-%m-%d').date()
            if deadline < today:
                overdue.append(t)
            else:
                active.append(t)
        except:
            active.append(t)
    return active, overdue


def complete_task(task_id):
    tasks = load_tasks()
    for t in tasks:
        if t['id'] == task_id:
            t['status'] = 'done'
            save_tasks(tasks)
            return True
    return False


def delete_task(task_id):
    tasks = load_tasks()
    tasks = [t for t in tasks if t['id'] != task_id]
    save_tasks(tasks)
    return True


def format_tasks_list(tasks, title="📋 **Задачи:**"):
    if not tasks:
        return "❌ Задач нет."

    lines = [title]
    for t in tasks:
        assignee = f" — {t['assignee']}" if t.get('assignee') else ""
        deadline = f" (до {t['deadline']})" if t.get('deadline') else ""
        lines.append(f"{t['id']}. {t['text']}{assignee}{deadline}")
    return '\n'.join(lines)


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


def format_digest(active_tasks, overdue_tasks):
    lines = []

    if active_tasks:
        lines.append("📋 **Активные задачи:**")
        for t in active_tasks:
            assignee = f" — {t['assignee']}" if t.get('assignee') else ""
            deadline = f" (до {t['deadline']})" if t.get('deadline') else ""
            lines.append(f"{t['id']}. {t['text']}{assignee}{deadline}")
    else:
        lines.append("✅ Активных задач нет.")

    if overdue_tasks:
        lines.append("\n❌ **Просроченные задачи:**")
        for t in overdue_tasks:
            assignee = f" — {t['assignee']}" if t.get('assignee') else ""
            deadline = f" (до {t['deadline']})" if t.get('deadline') else ""
            lines.append(f"{t['id']}. {t['text']}{assignee}{deadline}")

    return '\n'.join(lines)


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
    if not users:
        logger.warning("❌ Нет подписчиков!")
        return

    for chat_id in users:
        config = get_config_for_chat(chat_id)
        digest_chat = config.get('digest_chat', chat_id)

        active_tasks, overdue_tasks = get_active_tasks(chat_id)

        if not active_tasks and not overdue_tasks:
            try:
                await app.bot.send_message(
                    chat_id=digest_chat,
                    text="🌅 **Доброе утро!**\n\nАктивных задач нет. Отличная работа! 🎉"
                )
                logger.info(f"✅ Отправлено сообщение об отсутствии задач в чат {digest_chat}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки в чат {digest_chat}: {e}")
            continue

        digest_text = format_digest(active_tasks, overdue_tasks)
        try:
            await app.bot.send_message(
                chat_id=digest_chat,
                text=f"🌅 **Дайджест:**\n\n{digest_text}"
            )
            logger.info(f"✅ Дайджест отправлен в чат {digest_chat}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат {digest_chat}: {e}")


# ============================================
# КОМАНДЫ
# ============================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("✅ /start")
    await update.message.reply_text(
        "👋 Привет! Я умный Хаос-менеджер.\n\n"
        "📌 **Как правильно ставить задачи:**\n"
        "Чтобы бот точно понял срок, пишите **дату** в формате:\n"
        "`сделать отчёт 20.08`\n"
        "`встреча 18.08 в 14:00`\n\n"
        "❌ Избегайте слов 'завтра', 'послезавтра' — бот может их неправильно понять.\n"
        "✅ Лучше написать конкретную дату — и задача будет точной!\n\n"
        "📌 **Команды:**\n"
        "/subscribe — подписаться на дайджест\n"
        "/unsubscribe — отписаться\n"
        "/status — проверить подписку\n"
        "/digest — получить дайджест сейчас\n"
        "/test — тестовый дайджест\n"
        "/set_tasks_chat — установить этот чат как чат для задач\n"
        "/set_digest_chat — установить этот чат как чат для дайджестов\n\n"
        "📋 **Управление задачами:**\n"
        "/tasks — показать активные задачи\n"
        "/tasks overdue — показать просроченные задачи\n"
        "/tasks all — показать все задачи\n"
        "/done <id> — отметить задачу выполненной\n"
        "/delete <id> — удалить задачу"
    )


async def cmd_set_tasks_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"✅ /set_tasks_chat от {chat_id}")
    set_config_for_chat(chat_id, 'tasks_chat', chat_id)
    await update.message.reply_text(
        "✅ Этот чат установлен как **чат для задач**. Теперь бот будет читать сообщения только отсюда.")


async def cmd_set_digest_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    logger.info(f"✅ /set_digest_chat от {chat_id}")
    set_config_for_chat(chat_id, 'digest_chat', chat_id)
    await update.message.reply_text(
        "✅ Этот чат установлен как **чат для дайджестов**. Теперь дайджесты будут приходить сюда.")


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

    chat_id = update.message.chat_id
    config = get_config_for_chat(chat_id)
    tasks_chat = config.get('tasks_chat', chat_id)
    digest_chat = config.get('digest_chat', chat_id)

    if chat_id != digest_chat:
        await update.message.reply_text("ℹ️ Команда /digest доступна только в чате дайджестов.")
        return

    await update.message.reply_text("📋 Собираю задачи...")

    active_tasks, overdue_tasks = get_active_tasks(tasks_chat)

    if not active_tasks and not overdue_tasks:
        await update.message.reply_text("✅ Активных задач нет. Отличная работа! 🎉")
        return

    digest_text = format_digest(active_tasks, overdue_tasks)
    await update.message.reply_text(f"📋 **Дайджест:**\n\n{digest_text}")


# ============================================
# КОМАНДЫ УПРАВЛЕНИЯ ЗАДАЧАМИ
# ============================================

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    config = get_config_for_chat(chat_id)
    tasks_chat = config.get('tasks_chat', chat_id)

    args = context.args
    if args and args[0].lower() == 'overdue':
        tasks = get_tasks_by_chat(tasks_chat, 'active')
        today = datetime.now().date()
        overdue = []
        for t in tasks:
            try:
                deadline = datetime.strptime(t['deadline'], '%Y-%m-%d').date()
                if deadline < today:
                    overdue.append(t)
            except:
                continue
        if overdue:
            await update.message.reply_text(format_tasks_list(overdue, "❌ **Просроченные задачи:**"))
        else:
            await update.message.reply_text("✅ Просроченных задач нет.")
        return

    if args and args[0].lower() == 'all':
        tasks = get_tasks_by_chat(tasks_chat)
        if tasks:
            await update.message.reply_text(format_tasks_list(tasks, "📋 **Все задачи:**"))
        else:
            await update.message.reply_text("❌ Задач нет.")
        return

    # По умолчанию — активные задачи
    active_tasks, overdue_tasks = get_active_tasks(tasks_chat)
    if active_tasks or overdue_tasks:
        await update.message.reply_text(format_digest(active_tasks, overdue_tasks))
    else:
        await update.message.reply_text("✅ Активных задач нет.")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    config = get_config_for_chat(chat_id)
    tasks_chat = config.get('tasks_chat', chat_id)

    if not context.args:
        await update.message.reply_text("⚠️ Укажите ID задачи: `/done 3`")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return

    tasks = load_tasks()
    task = next((t for t in tasks if t['id'] == task_id and t.get('chat_id') == tasks_chat), None)

    if not task:
        await update.message.reply_text(f"❌ Задача с ID {task_id} не найдена.")
        return

    complete_task(task_id)
    await update.message.reply_text(f"✅ Задача {task_id} отмечена как выполненная!")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    config = get_config_for_chat(chat_id)
    tasks_chat = config.get('tasks_chat', chat_id)

    if not context.args:
        await update.message.reply_text("⚠️ Укажите ID задачи: `/delete 3`")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID должен быть числом.")
        return

    tasks = load_tasks()
    task = next((t for t in tasks if t['id'] == task_id and t.get('chat_id') == tasks_chat), None)

    if not task:
        await update.message.reply_text(f"❌ Задача с ID {task_id} не найдена.")
        return

    delete_task(task_id)
    await update.message.reply_text(f"🗑️ Задача {task_id} удалена.")


# ============================================
# ОБРАБОТЧИК ТЕКСТА (АВТОДОБАВЛЕНИЕ ЗАДАЧ)
# ============================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text
        user_name = update.message.from_user.first_name
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id
        chat_type = update.message.chat.type

        logger.info(
            f"🔍 ВИЖУ СООБЩЕНИЕ: от {user_name} (ID: {user_id}) в чате {chat_id} (тип: {chat_type}): {text[:50]}...")

        if not text.startswith('/'):
            save_message(chat_id, user_name, text)
            logger.info(f"📩 Сохранено в БД: {user_name}: {text[:50]}...")

            # Проверяем, есть ли задача в сообщении (через GigaChat)
            config = get_config_for_chat(chat_id)
            tasks_chat = config.get('tasks_chat')
            if not tasks_chat:
                tasks_chat = chat_id

            if chat_id == tasks_chat:
                try:
                    logger.info("🤖 Проверяю сообщение на наличие задачи...")
                    system_prompt = (
                        "Ты — ИИ-помощник. Прочитай сообщение и определи, есть ли в нём задача. "
                        "Если есть — верни JSON в формате: "
                        "{'task': true, 'text': 'текст задачи', 'assignee': 'имя исполнителя', 'deadline': 'YYYY-MM-DD'}. "
                        "Если задачи нет — верни {'task': false}."
                    )
                    user_prompt = f"Сообщение: {text}"

                    request = Chat(
                        messages=[
                            Messages(role=MessagesRole.SYSTEM, content=system_prompt),
                            Messages(role=MessagesRole.USER, content=user_prompt)
                        ],
                        temperature=0.5,
                        max_tokens=200
                    )
                    response = giga.chat(request)
                    result_text = response.choices[0].message.content

                    # Пробуем извлечь JSON из ответа
                    import ast
                    try:
                        result = ast.literal_eval(result_text)
                        if result.get('task'):
                            assignee = result.get('assignee', '')
                            deadline = result.get('deadline', '')
                            task_text = result.get('text', text)

                            add_task(task_text, assignee, deadline, chat_id)
                            logger.info(f"✅ Задача добавлена: {task_text}")
                    except:
                        logger.info("ℹ️ Не удалось распарсить ответ GigaChat как JSON")
                except Exception as e:
                    logger.error(f"❌ Ошибка при проверке задачи: {e}")


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
    app.add_handler(CommandHandler("set_tasks_chat", cmd_set_tasks_chat))
    app.add_handler(CommandHandler("set_digest_chat", cmd_set_digest_chat))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("delete", cmd_delete))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    scheduler = BackgroundScheduler()

    loop = asyncio.get_event_loop()

    def run_async_job(app):
        asyncio.run_coroutine_threadsafe(send_daily_digest(app), loop)

    scheduler.add_job(
        run_async_job,
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
    print("   /set_tasks_chat - установить текущий чат как чат для задач")
    print("   /set_digest_chat - установить текущий чат как чат для дайджестов")
    print("   /tasks - показать активные задачи")
    print("   /tasks overdue - показать просроченные задачи")
    print("   /tasks all - показать все задачи")
    print("   /done <id> - отметить задачу выполненной")
    print("   /delete <id> - удалить задачу")

    app.run_polling()


if __name__ == '__main__':
    main()