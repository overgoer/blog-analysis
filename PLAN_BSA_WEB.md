# BSA Web — План реализации

## Что строим

Flask-вебчат на сервере (порт 3000). BSA внутри — тот же DeepSeek с function calling. У BSA есть инструменты: читать/писать Obsidian, запускать агентов, смотреть репозитории. Заходишь с мобилы по паролю.

## Архитектура

```
Мобила ──https──→ Сервер:3000
                          │
                     Flask (bsa_web.py)
                       │        │
                  DeepSeek ← → инструменты
                    API         │
                          read/write файлы
                          subprocess → агенты
                          email
```

## Файлы

| Файл | Назначение |
|------|-----------|
| `agents/bsa/bsa_web.py` | Flask + DeepSeek function calling |
| `agents/bsa/templates/index.html` | Чат-интерфейс (мобильный) |
| `agents/bsa/bsa_prompt.txt` | Системный промпт BSA |
| `agents/bsa/sessions/` | История диалогов (JSON) |

## Инструменты BSA

| Инструмент | Что делает | Безопасность |
|-----------|-----------|-------------|
| `read_file(path)` | Читает файлы Obsidian, конфиги, стратегии | Read-only, белый список директорий |
| `write_file(path, content)` | Пишет в Obsidian (стратегии, беты) | Только `obsidian-vault/`, не перезаписывает код |
| `list_dir(path)` | Смотрит что есть в директориях | Read-only, белый список |
| `run_agent(agent_name)` | Запускает BSA, PM Agent, ресерчер | Фиксированный список команд |
| `run_researcher(topic)` | Запускает ресерчер | Только researcher.py |
| `send_email(subj, body)` | Отправляет email | Через mailer, без shell |

## Безопасность

- Пароль в `bsa_web_config.json` (bcrypt/simple hash)
- Никакого shell-доступа — только конкретные subprocess
- Запись только в Obsidian vault, не в код
- DeepSeek API ключ — из Bitwarden на сервере

## Git workflow

1. Ветка `bsa-web` на маке
2. Разработка в `/tmp/blog-analysis/`
3. Пуш → GitHub
4. Pull на сервере
5. Тест
6. Мерж в main

## Размер

- Flask: ~1 файл, 200 строк
- HTML шаблон: 1 файл, ~100 строк
- RAM: ~20MB
- CPU: 0 в простое
