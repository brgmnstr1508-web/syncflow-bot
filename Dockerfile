# 1. Берем за основу легкую и современную версию Python
FROM python:3.11-slim

# 2. Создаем внутри контейнера папку для нашего бота и делаем её рабочей
WORKDIR /app

# 3. Копируем файл с библиотеками и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копируем весь остальной код нашего бота в папку /app
COPY . .

# 5. Говорим Docker'у, какую команду выполнить для запуска бота
CMD ["python3", "bot.py"]