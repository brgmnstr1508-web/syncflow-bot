import json
import os
from datetime import datetime, timedelta

# Имя файла, где мы будем хранить все сообщения
DATA_FILE = 'messages.json'


# Функция для сохранения нового сообщения
def save_message(chat_id, user_name, text):
    # Загружаем старые сообщения (если они есть)
    messages = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            messages = json.load(f)

    # Создаем запись о новом сообщении
    new_msg = {
        'chat_id': chat_id,
        'user': user_name,
        'text': text,
        'time': datetime.now().isoformat()  # Запоминаем точное время
    }
    messages.append(new_msg)

    # Сохраняем обновленный список обратно в файл
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)


# Функция для получения сообщений за последние N часов
def get_recent_messages(hours=24):
    if not os.path.exists(DATA_FILE):
        return []

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        all_messages = json.load(f)

    # Вычисляем порог времени (сейчас минус 24 часа)
    threshold = datetime.now() - timedelta(hours=hours)
    recent = []

    for msg in all_messages:
        msg_time = datetime.fromisoformat(msg['time'])
        if msg_time > threshold:
            recent.append(msg)
    return recent