# obsidian-utils


# Мой телеграм канал
https://t.me/+4zHj_20Zmo43ZmVi

# Зависимости
```
pip install watchdog
pip install aiohttp
```

# Полное сканирование + мониторинг
```
python main.py
```


# Только сканирование
```
python main.py scan

docker run --name test -it registry.gitlab.com/my6145916/obsidian-utils:1.0.12
```

# Переменные 

VAULT_PATH=/srv/obsidian/notes
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"


  GNU nano 7.2                                                                                                                                                                                                                                            /home/aborisov/projects/my/ts/readme.md                                                                                                                                                                                                                                                      
obsidian-tracker-sync/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── config/
│   ├── config.yaml
│   └── .env.example
├── src/
│   ├── main.py
│   ├── obsidian/
│   │   ├── parser.py
│   │   └── vault_watcher.py
│   ├── trackers/
│   │   ├── yandex_tracker.py
│   │   ├── jira_client.py
│   │   └── base_tracker.py
│   ├── sync/
│   │   ├── sync_manager.py
│   │   ├── reconciliation.py
│   │   └── balance_checker.py
│   ├── telegram/
│   │   ├── bot.py
│   │   └── notifications.py
│   └── utils/
│       ├── logger.py
│       └── helpers.py
├── data/
│   ├── vaults/
│   └── cache/
└── scripts/
    └── entrypoint.sh

1. Настройка конфигурации
bash
# Клонирование проекта
git clone <repository-url>
cd obsidian-tracker-sync

# Копирование примера конфигурации
cp config/.env.example config/.env
cp config/config.yaml.example config/config.yaml

# Редактирование конфигурации
nano config/.env
2. Настройка переменных окружения в .env:
env
# Yandex Tracker
YANDEX_ORG_ID=your_org_id
YANDEX_OAUTH_TOKEN=your_oauth_token

# Jira
JIRA_URL=https://your-company.atlassian.net
JIRA_USERNAME=your_email@company.com
JIRA_API_TOKEN=your_api_token

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ADMIN_ID=your_user_id

# Настройки
RUN_TELEGRAM_BOT=true
3. Сборка и запуск
bash
# Сборка Docker образов
docker-compose build

# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
4. Использование Telegram бота
text
/start - Начало работы
/reconcile 2025-12 - Сверка за декабрь 2025
/balance - Проверка баланса проектов
/status - Статус службы
