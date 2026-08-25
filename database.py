import json
import os
from datetime import datetime, timedelta

# ============================================
# ЗАДАЧИ
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

def add_task(text, assignee, assignee_id, deadline, chat_id):
    tasks = load_tasks()
    task = {
        'id': get_next_task_id(tasks),
        'text': text,
        'assignee': assignee,
        'assignee_id': assignee_id,
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

def format_tasks_list(tasks, title=" **Задачи:**"):
    if not tasks:
        return "❌ Задач нет."

    lines = [title]
    for t in tasks:
        assignee = f" — {t['assignee']}" if t.get('assignee') else ""
        deadline = f" (до {t['deadline']})" if t.get('deadline') else ""
        lines.append(f"{t['id']}. {t['text']}{assignee}{deadline}")
    return '\n'.join(lines)

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
# ПОДПИСКИ И ПОЛЬЗОВАТЕЛИ
# ============================================

USERS_FILE = "users.json"

def load_users():
    if not os.path.exists(USERS_FILE):
        save_users({})
        return {}

    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        save_users({})
        return {}
    except Exception as e:
        save_users({})
        return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def check_subscription(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        return False
    user_data = users[str(chat_id)]
    if not user_data.get('is_active', False):
        return False
    trial_until = user_data.get('trial_until')
    if trial_until:
        try:
            expiry = datetime.strptime(trial_until, '%Y-%m-%d')
            if expiry < datetime.now():
                return False
        except:
            return False
    return True

def activate_subscription(chat_id, plan='trial'):
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}
    users[str(chat_id)]['is_active'] = True
    users[str(chat_id)]['plan'] = plan
    users[str(chat_id)]['subscribed_at'] = datetime.now().strftime('%Y-%m-%d')
    if plan == 'trial':
        trial_until = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        users[str(chat_id)]['trial_until'] = trial_until
    else:
        paid_until = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        users[str(chat_id)]['trial_until'] = paid_until
    save_users(users)

def add_digest_subscriber(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}
    users[str(chat_id)]['digest_subscribed'] = True
    save_users(users)
    return True

def remove_digest_subscriber(chat_id):
    users = load_users()
    if str(chat_id) in users:
        users[str(chat_id)]['digest_subscribed'] = False
        save_users(users)
        return True
    return False

def get_digest_subscribers():
    users = load_users()
    return [int(chat_id) for chat_id, data in users.items() if data.get('digest_subscribed', False)]