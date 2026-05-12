#!/usr/bin/env python3
"""Nightly Digest v2 — generates 3-4 full post drafts with channel context.
All in Russian. Uses channel profile for style and topic matching.
"""

import os, sys, json, random
from datetime import datetime
from pathlib import Path

AGENTS_DIR = Path("/root/blog-analysis/agents")
DATA_DIR = Path("/root/blog-analysis/data")


def load_channel_profile():
    """Load channel context profile."""
    pfile = DATA_DIR / "channel_profile.json"
    if not pfile.exists():
        return {}
    return json.loads(pfile.read_text())


def load_competitor_names():
    """Load readable channel names."""
    comp_file = AGENTS_DIR / "scout" / "competitors.json"
    if not comp_file.exists():
        return {}
    try:
        data = json.loads(comp_file.read_text())
        names = {}
        for group in ["primary", "extended"]:
            for ch in data.get(group, []):
                names[ch["id"]] = ch["name"]
        return names
    except Exception:
        return {}


def get_scout_recs():
    """Parse SCOUT report for recommendations."""
    report_file = AGENTS_DIR / "scout" / "reports" / "latest_report.md"
    if not report_file.exists():
        return []
    recs = []
    for line in report_file.read_text().split("\n"):
        if line.strip().startswith("- **"):
            try:
                cat = line.split("**")[1]
                rest = line.split("--")[-1].strip() if "--" in line else ""
                # Clean up
                for p in ["У конкурентов в этой теме:", "Y konkurentov:"]:
                    if p in rest:
                        rest = rest.replace(p, "").strip().strip(": ,")
                bad = {"только", "больше", "потому", "сегодня", "можно", "будет",
                       "когда", "очень", "просто", "тоже", "этот", "свои", "такие",
                       "значит", "самое", "inside", "often", "great", "first"}
                words = [w.strip() for w in rest.split(",") if w.strip() not in bad and len(w.strip()) > 3]
                recs.append({"cat": cat, "words": words[:4]})
            except Exception:
                pass
    return recs


def get_content_plan_items():
    """Extract post ideas from this week's content plan."""
    plans = sorted(DATA_DIR.glob("eddytester-content-plan-*.md"))
    if not plans:
        return []
    content = plans[-1].read_text()
    items = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("###") and "—" in line:
            items.append(line.replace("###", "").strip())
    return items


def get_educator_tip():
    """Get latest educator tip."""
    tip_dir = AGENTS_DIR / "educator" / "tips"
    if not tip_dir.exists():
        return None, None
    tips = sorted(tip_dir.glob("tip_*.md"))
    if not tips:
        return None, None
    return tips[-1].read_text().strip(), tips[-1].name


def get_all_topics():
    """Get ALL available educator topics."""
    try:
        from collections import OrderedDict
        # Import topics from module
        mod_path = str(AGENTS_DIR / "educator")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        # Read topics from file directly
        content = (AGENTS_DIR / "educator" / "educator.py").read_text()
        idx = content.find("TOPICS = [")
        if idx == -1:
            return []
        # Extract JSON-like topics list
        # Find matching closing bracket
        depth = 0
        start = content.find("[", idx)
        end = start
        for i in range(start, len(content)):
            if content[i] == "[":
                depth += 1
            elif content[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        topic_str = content[start:end]
        # Use exec to safely parse
        ns = {}
        exec(f"import json\nimport random\n_topics = {topic_str}", ns)
        return ns.get("_topics", [])
    except Exception as e:
        print(f"[digest] ERROR loading topics: {e}")
        return []


# ── Russian Post Templates ──────────────────────────────────────

TOPIC_LINKS = {
    "postman": [
        "https://learning.postman.com/docs/introduction/overview/",
        "https://www.postman.com/",
        "https://github.com/postmanlabs/newman"
    ],
    "sql": [
        "https://www.postgresql.org/docs/current/index.html",
        "https://sqlzoo.net/",
        "https://www.db-fiddle.com/"
    ],
    "http": [
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status",
        "https://httpbin.org/",
        "https://datatracker.ietf.org/doc/html/rfc7231"
    ],
    "api": [
        "https://jsonplaceholder.typicode.com/",
        "https://httpbin.org/",
        "https://swagger.io/resources/open-api/"
    ],
    "auth": [
        "https://jwt.io/",
        "https://auth0.com/docs/get-started/identity-fundamentals",
        "https://datatracker.ietf.org/doc/html/rfc7519"
    ],
    "websocket": [
        "https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API",
        "https://wscat.vercel.app/"
    ],
    "webhook": [
        "https://webhook.site/",
        "https://ngrok.com/"
    ],
    "queue": [
        "https://www.rabbitmq.com/getstarted.html",
        "https://kafka.apache.org/documentation/"
    ],
    "cors": [
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS",
        "https://cors-anywhere.herokuapp.com/"
    ],
    "cache": [
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/ETag",
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching"
    ],
    "grpc": [
        "https://grpc.io/docs/",
        "https://github.com/fullstorydev/grpcurl"
    ],
    "ci": [
        "https://www.jenkins.io/doc/",
        "https://docs.github.com/en/actions"
    ],
}


def get_links(topic_name):
    """Get relevant links for a topic."""
    t = topic_name.lower()
    for key, links in TOPIC_LINKS.items():
        if key in t:
            return links
    return []


def get_ru_description(topic_name):
    """Full RU description for a topic (5-10 sentences)."""
    t = topic_name.lower()
    if "postman" in t:
        return (
            "Postman — это не просто HTTP-клиент. Это среда для работы с API, "
            "которая включает коллекции, окружения, pre-request скрипты, тесты и авто-документацию. "
            "Большинство тестировщиков используют 10% его возможностей. "
            "Главная фишка Postman — переменные окружения: ты заводишь {{base_url}}, "
            "{{token}}, {{account_id}} и переключаешься между dev/staging/prod одной кнопкой. "
            "А pre-request скрипты позволяют генерировать данные прямо перед запросом — "
            "например, свежий JWT токен или timestamp."
        )
    if "newman" in t:
        return (
            "Newman — это CLI-версия Postman для запуска коллекций без GUI. "
            "Твой главный инструмент для регресса API в CI/CD. "
            "Сценарий: собрал коллекцию тестов → запустил newman → получил JUnit-отчёт → "
            "упало — чини, зелёное — катим. "
            "Флаги --iteration-count, --timeout-request, --env-file делают его гибким. "
            "А reporters=cli,junit дают и красивый вывод, и машиночитаемый отчёт."
        )
    if "sql" in t or "database" in t or "join" in t:
        if "join" in t:
            return (
                "JOIN — база работы с реляционными БД. INNER JOIN возвращает строки, "
                "которые есть в обеих таблицах. LEFT JOIN — все строки из левой таблицы + "
                "совпадения из правой (NULL где нет совпадения). "
                "Типичный баг: использовали LEFT JOIN где нужен INNER — получили NULL-поля "
                "и упавшие тесты. Или наоборот: INNER JOIN вместо LEFT — потеряли данные. "
                "Для тестировщика понимание JOIN — это способ проверять связанные данные "
                "через SQL напрямую, не дожидаясь API."
            )
        if "index" in t or "explain" in t or "query plan" in t:
            return (
                "EXPLAIN ANALYZE — твой рентген для SQL-запросов. "
                "Показывает как база данных выполняет запрос: какие индексы использует, "
                "сколько строк сканирует, где узкое место. "
                "Seq Scan на большой таблице = беда. Index Scan = хорошо. "
                "Если API под нагрузкой тормозит — первый шаг: EXPLAIN ANALYZE проблемного запроса. "
                "Часто причина — отсутствующий индекс на колонке WHERE/JOIN."
            )
        return (
            "Базы данных — не чёрный ящик. Хороший тестировщик смотрит в БД напрямую, "
            "потому что API может врать, а SQL — нет. "
            "Транзакции (BEGIN/COMMIT/ROLLBACK) гарантируют атомарность операций. "
            "Миграции меняют схему — тестируй откат ДО деплоя. "
            "Connection pooling: когда пул исчерпан, запросы падают с таймаутом."
        )
    if "http" in t or "status" in t or "cors" in t or "content" in t:
        return (
            "HTTP — язык общения клиента и сервера. Статус-коды это диагноз: "
            "2xx успех, 3xx редирект/кэш, 4xx проблема клиента, 5xx проблема сервера. "
            "Важный нюанс: 200 OK не означает правильные данные. "
            "Всегда проверяй тело ответа отдельно от статуса. "
            "CORS-заголовки приходят от сервера — баг фронта? Нет, баг бэкенда. "
            "Content-Type определяет формат ответа — если запросил JSON а получил XML, это баг."
        )
    if "api" in t:
        if "idempotent" in t or "idempotency" in t:
            return (
                "Идемпотентность — гарантия, что повторный запрос не создаст дубликат. "
                "Критично для платежей, заказов, регистрации. "
                "Механизм: клиент отправляет уникальный Idempotency-Key, сервер запоминает ответ. "
                "Если приходит повторный запрос с тем же ключом — возвращает сохранённый ответ. "
                "Как тестировать: отправить запрос → оборвать соединение → отправить снова с тем же ключом. "
                "Должен получить тот же ответ без сайд-эффектов."
            )
        if "pagination" in t:
            return (
                "Пагинация — стандартный механизм постраничной выдачи. "
                "Бывает page/offset и cursor-based. Типичные баги: "
                "пустая последняя страница не = 404, отрицательный номер страницы не валидируется, "
                "page=9999 отдаёт 200 вместо 404, между страницами дублируются или теряются записи."
            )
        if "rate" in t or "429" in t:
            return (
                "Rate limiting — защита от перегрузки и DDoS. "
                "Когда лимит исчерпан, сервер возвращает 429 Too Many Requests с заголовком Retry-After. "
                "Что тестировать: точное количество запросов до лимита, "
                "формат Retry-After (секунды или дата), сброс лимита через время, "
                "разные лимиты для разных эндпоинтов и пользователей."
            )
        if "etag" in t or "cache" in t or "conditional" in t:
            return (
                "ETag (Entity Tag) — хеш содержимого ресурса. "
                "Сервер отдаёт ETag в заголовке ответа. Клиент сохраняет и при следующем "
                "запросе отправляет If-None-Match: <etag>. "
                "Если ресурс не изменился → 304 Not Modified (без тела). "
                "Основные проверки: 304 возвращается без тела, "
                "ETag меняется при обновлении ресурса, два одинаковых ресурса дают тот же ETag."
            )
        if "grpc" in t:
            return (
                "gRPC — современный протокол для микросервисов от Google. "
                "Использует Protocol Buffers (protobuf) вместо JSON/XML. "
                "Сообщения — бинарные, не человекочитаемые. "
                "Транспорт — HTTP/2, один канал может мультиплексировать много запросов. "
                "Для тестирования: grpcurl, Postman gRPC, BloomRPC. "
                "Проверяй service reflection — если отключена, найти методы сложно."
            )
        if "version" in t:
            return (
                "Версионирование API — про обратную совместимость. "
                "Клиенты на старых версиях не должны ломаться при обновлении. "
                "Способы: версия в URL (/v1/, /v2/), в заголовке (Accept: version=2), "
                "или в query-параметре. "
                "Что тестировать: старый эндпоинт работает после выхода нового, "
                "заголовки Sunset и Deprecation появляются вовремя."
            )
        return (
            "API-тестирование — база. Но 90% тестировщиков проверяют только позитивные сценарии: "
            "отправил валидный запрос → получил 200 → ОК. "
            "А негативные тесты (невалидные данные, отсутствующие поля, превышение лимитов, "
            "истекшие токены, кривые заголовки) пропускают. "
            "Именно в негативных сценариях живут самые дорогие баги."
        )
    if "auth" in t or "jwt" in t or "token" in t:
        return (
            "Аутентификация — это не просто логин/пароль. "
            "JWT (JSON Web Token) — самый популярный формат токенов. "
            "Состоит из трёх частей: header.payload.signature (base64). "
            "Опасные моменты: не проверен exp (токен живет вечно), "
            "alg=none (атака подмены алгоритма), слабая подпись."
        )
    if "websocket" in t:
        return (
            "WebSocket — протокол реального времени. Чаты, уведомления, "
            "онлайн-статусы, live-графики — всё через WebSocket. "
            "Соединение начинается как HTTP Upgrade (101 Switching Protocols), "
            "потом переходит в постоянный канал. "
            "Фреймы, не запросы. Тестировать: wscat или Postman WebSocket. "
            "Критично проверить reconnect — при обрыве клиент должен переподключаться."
        )
    if "webhook" in t:
        return (
            "Webhook — обратный вызов от внешнего сервиса. "
            "Платежка подтвердила оплату → POST на твой URL. "
            "Тестировать сложно: нет синхронного запроса-ответа. "
            "Используй webhook.site для приёма. "
            "Проверяй: повторные попытки при ошибке (retry), "
            "HMAC-подпись для верификации, идемпотентность."
        )
    if "queue" in t or "rabbitmq" in t or "kafka" in t:
        return (
            "Очереди сообщений (RabbitMQ, Kafka) — backbone асинхронной архитектуры. "
            "Отправил запрос → получил 202 Accepted → задача ушла в очередь. "
            "Проверять надо не только ответ, но и что consumer обработал сообщение. "
            "Важно: dead letter queue (упавшие сообщения), "
            "гарантии доставки (at-most-once/at-least-once), "
            "порядок сообщений."
        )
    if "circuit" in t:
        return (
            "Circuit Breaker — паттерн для изолирования сбоев. "
            "Когда внешний сервис падает, breaker переключается в OPEN и запросы "
            "не доходят до упавшего сервиса — возвращается fallback. "
            "Потом HALF-OPEN проверяет ожил ли сервис. "
            "Тестировать: отключи downstream → проверь fallback, "
            "включи обратно → проверь восстановление."
        )
    if "connection pool" in t:
        return (
            "Connection pool — пул соединений к БД. "
            "Открыть новое соединение дорого, поэтому приложения держат пул "
            "и переиспользуют. Симптомы истощения пула: "
            "периодические таймауты под нагрузкой, 'too many connections' в логах. "
            "Что тестировать: открыть много одновременных запросов → "
            "проверить что соединения возвращаются в пул."
        )
    if "log" in t or "correlation" in t:
        return (
            "Correlation ID (X-Request-ID) — сквозной идентификатор запроса. "
            "Позволяет отследить путь запроса: nginx → app → DB → external API. "
            "Журнал ""DEBUG: correlation_id=abc-123"". "
            "Если своего correlation ID нет в логах — баг. "
            "Тестировать: отправь запрос со своим X-Request-ID → "
            "найди его во всех сервисах."
        )
    return (
        "Разбираем тему глубже: мало знать что это работает — надо понимать "
        "как это работает под капотом, какие есть граничные случаи, "
        "и как это правильно тестировать."
    )


def get_ru_tip_long(topic_name):
    """Longer practical tip in Russian (3-5 paragraphs)."""
    t = topic_name.lower()
    if "postman" in t:
        if "collection" in t:
            return (
                "Создай коллекцию логически: по эндпоинтам или по фичам. "
                "Окружения (environments) — для dev/staging/prod. "
                "Переменные: {{base_url}}, {{auth_token}}, {{user_id}}. "
                "Pre-request script: автоматически получать токен перед каждым запросом. "
                "Tests tab: pm.test('Status is 200', () => pm.response.to.have.status(200)). "
                "Экспортируй коллекцию в JSON — залей в Git. "
                "Команда будет использовать одни и те же тесты."
            )
        if "pre-request" in t or "pre request" in t:
            return (
                "Pre-request скрипты выполняются ДО отправки запроса. "
                "Сценарий: получил JWT токен → положил в переменную → "
                "следующий запрос использует. "
                "Всё автоматически, без ручной вставки. "
                "Ещё: генерация timestamp, случайных UUID, подпись payload. "
                "Пример: pm.variables.set('timestamp', Date.now()). "
                "Удобно для тестирования идемпотентности — каждый раз новый key."
            )
        if "test" in t:
            return (
                "Tests tab — это Postman-assertions. Пишутся на JavaScript. "
                "Базовые проверки: статус (200), время ответа (< 200ms), "
                "JSON-схема, заголовки. "
                "Продвинутые: проверка массива (каждый элемент), "
                "сравнение с предыдущим ответом, цепочка запросов. "
                "Используй pm.response.json() для доступа к телу."
            )
    if "sql" in t or "database" in t:
        if "join" in t:
            return (
                "INNER JOIN — только пересечение двух таблиц. "
                "LEFT JOIN — все строки из A + совпадения из B или NULL. "
                "RIGHT JOIN — наоборот. FULL JOIN — всё вместе. "
                "Кросс-проверка: отправь POST → проверь что появилась запись в БД "
                "через JOIN со связанной таблицей. "
                "Если INNER JOIN не вернул строк — значит что-то пошло не так."
            )
        if "explain" in t or "plan" in t:
            return (
                "EXPLAIN ANALYZE — запусти запрос с этим префиксом. "
                "Получишь план выполнения: Seq Scan (плохо, читает всю таблицу), "
                "Index Scan (хорошо, использует индекс). "
                "Bitmap Heap Scan — приемлемо для больших выборок. "
                "cost — относительная стоимость, rows — оценка строк. "
                "actual time — реальное время. "
                "Если rows сильно отличается от actual — статистика БД устарела."
            )
    if "http" in t or "status" in t:
        return (
            "2xx: 200 OK, 201 Created, 204 No Content, 206 Partial Content. "
            "3xx: 301 Moved (навсегда), 302 Found (временно), 304 Not Modified (кэш), "
            "307/308 — как 301/302 но с сохранением метода. "
            "4xx: 400 Bad Request, 401 Unauthorized, 403 Forbidden, "
            "404 Not Found, 405 Method Not Allowed, 409 Conflict, "
            "413 Payload Too Large, 415 Unsupported Media Type, "
            "422 Unprocessable, 429 Too Many Requests. "
            "5xx: 500 Internal, 502 Bad Gateway, 503 Unavailable, 504 Gateway Timeout. "
            "Нюанс: 200 ≠ правильные данные. Всегда проверяй тело."
        )
    if "cors" in t:
        return (
            "CORS — механизм безопасности браузера. "
            "Сервер должен явно разрешить кросс-доменные запросы. "
            "Ключевые заголовки: Access-Control-Allow-Origin (кто может), "
            "Access-Control-Allow-Methods (какие методы), "
            "Access-Control-Allow-Headers (какие заголовки). "
            "Preflight (OPTIONS) — для non-simple запросов (PUT, DELETE, кастомные заголовки). "
            "Тест: curl -H 'Origin: https://evil.com' -X OPTIONS. "
            "Если вернул Access-Control-Allow-Origin: * — без разницы, "
            "но если вообще не вернул — CORS error."
        )
    if "api" in t:
        if "pagination" in t:
            return (
                "Page-based: /api/items?page=1&limit=20. "
                "Cursor-based: /api/items?cursor=abc123. "
                "Page-based проще, но при вставке новых записей данные "
                "съезжают между страницами. "
                "Cursor-based стабильнее, но сложнее. "
                "Тесты: page 1 = первые N, page 2 = следующие, "
                "page=9999 = пустой массив (не 404!), "
                "limit=0, limit=-1, limit=100000 (границы), "
                "page=string, cursor=not-a-valid-cursor."
            )
        if "idempotent" in t:
            return (
                "Idempotency-Key — уникальный UUID клиента. "
                "Сервер кеширует ответ для каждого ключа. "
                "Повторный запрос с тем же ключом → тот же ответ. "
                "Сценарий: клиент отправил запрос → не дождался ответа (таймаут) → "
                "отправил снова с тем же ключом → сервер вернул кешированный ответ. "
                "Тесты: два запроса с одинаковым ключом → одинаковые ответы. "
                "Без ключа → каждый запрос обрабатывается заново."
            )
    if "auth" in t or "jwt" in t:
        return (
            "JWT = три base64url-закодированные части, разделённые точкой. "
            "Header: тип токена и алгоритм подписи. "
            "Payload: данные (sub, name, exp, iat). "
            "Signature: подпись для проверки целостности. "
            "Опасность: алгоритм 'none' — если сервер не проверяет подпись, "
            "можно отправить токен без подписи и он пройдёт валидацию. "
            "Также: exp — срок действия, если не проверяется — токен живёт вечно. "
            "Тесты: jwt.io — декодировать, проверить payload, exp, подпись."
        )
    return (
        "Копай глубже: опишу не только 'как правильно', но и 'что сломается, если сделать неправильно'. "
        "Граничные случаи — твой хлеб как тестировщика."
    )


# ── Draft generators ────────────────────────────────────────────

def format_draft_deep(topic, idx=1):
    """Format 1: Deep technical dive (like eddytester's long posts)."""
    name = topic["topic"]
    ru_desc = get_ru_description(name)
    ru_tip = get_ru_tip_long(name)
    links = get_links(name)

    draft = f"🎯 Вариант {idx}: Разбор\n\n"
    draft += f"🔥 {name}\n\n"
    draft += f"{ru_desc}\n\n"
    draft += f"⚙️ Что важно знать:\n{ru_tip}\n"
    draft += f"\n💬 А ты проверяешь это в своих тестах? Напиши в комментах 👇"

    if links:
        draft += f"\n\n🔗 Полезные ссылки:\n"
        for link in links[:3]:
            draft += f"• {link}\n"
    return draft


def format_draft_checklist(topic, idx=2):
    """Format 2: Quick cheatsheet / checklist."""
    name = topic["topic"]
    t = name.lower()
    ru_desc = get_ru_description(name)
    ru_tip = get_ru_tip_long(name).split("\n")
    cheatsheet = [l.strip() for l in ru_tip if l.strip() and len(l.strip()) > 15][:5]

    draft = f"📋 Вариант {idx}: Шпаргалка\n\n"
    draft += f"🔥 {name}\n\n"
    draft += f"{ru_desc}\n\n"
    draft += f"📌 Коротко по делу:\n"

    for i, item in enumerate(cheatsheet, 1):
        draft += f"{i}. {item}\n"

    draft += f"\n💬 Сохрани, чтобы не потерять 👇"

    links = get_links(name)
    if links:
        draft += f"\n\n🔗 {links[0]}"

    return draft


def format_draft_interactive(topic, idx=3):
    """Format 3: Interactive quiz/question."""
    name = topic["topic"]
    t = name.lower()

    draft = f"🤔 Вариант {idx}: А ты знал?\n\n"
    draft += f"🔥 {name}\n\n"

    # Generate a quiz question based on topic
    if "postman" in t and "environment" in t:
        draft += "Вопрос: Как переключиться между dev/staging/prod в Postman "
        draft += "не редактируя каждый URL руками?\n\n"
        draft += "A) Создать отдельную коллекцию для каждой среды\n"
        draft += "B) Использовать переменные окружения ({{base_url}})\n"
        draft += "C) Правой кнопкой → Switch Environment\n\n"
        draft += "Ответ в следующем посте! А пока подумай 👇\n"
    elif "sql" in t or "database" in t:
        draft += "Вопрос: SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id\n"
        draft += "Что вернётся для пользователя, у которого нет ни одного заказа?\n\n"
        draft += "A) Только данные пользователя, без колонок заказа\n"
        draft += "B) Данные пользователя с NULL в колонках заказа\n"
        draft += "C) Ничего — строка не вернётся\n\n"
        draft += "Пиши ответ в комментах! Разберём в следующем посте.\n"
    elif "http" in t or "status" in t:
        draft += "Вопрос: Почему 200 OK ≠ правильные данные?\n\n"
        if "status" in t:
            draft += "Подсказка: сервер может вернуть 200 с fallback-данными, "
            draft += "пустым массивом или мусором в теле. "
            draft += "Статус говорит только о том, что запрос обработан. "
            draft += "Правильность данных — отдельная проверка.\n"
        draft += "\nКак проверяешь? Расскажи в комментах!\n"
    elif "api" in t and "idempotent" in t:
        draft += "Ситуация: клиент отправил POST /api/orders — запрос ушёл, "
        draft += "но ответ не пришёл (таймаут). Что делать?\n\n"
        draft += "A) Отправить снова — если ушёл, будет дубликат заказа\n"
        draft += "B) Не отправлять — заказ может потеряться\n"
        draft += "C) Отправить с Idempotency-Key — сервер не создаст дубликат\n\n"
        draft += "Подсказка: для этого и нужна идемпотентность 👇\n"
    elif "auth" in t or "jwt" in t:
        draft += "Вопрос: Что будет, если отправить JWT с alg: 'none'?\n\n"
        draft += "A) Сервер вернёт ошибку — подпись не совпадает\n"
        draft += "B) Сервер примет токен — если не проверяет подпись\n"
        draft += "C) Токен невалидный с самого начала\n\n"
        draft += "Ответ: зависит от сервера. Многие библиотеки давно запретили 'none', "
        draft += "но legacy-код может пропустить.\n"
    else:
        draft += f"Вопрос: Что самое неочевидное в теме {name}?\n\n"
        draft += f"Напиши в комментах — обсудим!\n"

    links = get_links(name)
    if links:
        draft += f"\n🔗 Почитать: {links[0]}"

    return draft


def format_draft_case(topic, idx=4):
    """Format 4: Case study with a bug scenario."""
    name = topic["topic"]
    t = name.lower()

    draft = f"🔍 Вариант {idx}: Реальный кейс\n\n"
    draft += f"🔥 {name}\n\n"

    # Generate a case study based on topic
    if "postman" in t:
        draft += "Было: тестировщик вручную менял URL для каждой среды "
        "(dev → staging → prod). Ошибся — запустил деструктивный тест на продакшене. "
        "Стало: создали окружения ({{base_url}}) в Postman, "
        "переключаемся выпадающим списком. "
        "Новый тест пишем один раз — работает везде.\n"
    elif "sql" in t or "database" in t:
        draft += "Баг: на staging приложение падало при просмотре заказов пользователя. "
        "Разработчик: 'у меня локально работает'. "
        "Запрос в логе: SELECT * FROM users LEFT JOIN orders ON ... WHERE user_id = 123. "
        "Оказалось: у пользователя 50К заказов, запрос выполнялся 30 секунд — "
        "APP-сервер сбрасывал соединение по таймауту. "
        "Решение: пагинация + индекс на orders.user_id.\n"
    elif "http" in t or "status" in t:
        draft += "Кейс: API возвращает 200 OK на запрос с невалидными данными. "
        "Разработчик: 'статус 200 — всё ок'. "
        "Проверка тела: ответ содержит {'error': 'validation failed', 'code': 422}. "
        "Статус 200, но данные не сохранены. "
        "Вывод: 200 ≠ правильные данные. Всегда проверяй тело.\n"
    elif "api" in t:
        if "idempotent" in t:
            draft += "Кейс: пользователь нажал 'Оплатить' дважды из-за задержки. "
            "Списалась сумма дважды. Поддержка: 'отмените дубликат вручную'. "
            "Решение: Idempotency-Key на payment endpoint. "
            "Первый запрос: 200 OK, деньги списаны. "
            "Повторный с тем же ключом: 200 OK, деньги НЕ списаны. "
            "Тест: отправить 5 раз с одним ключом — 1 списание.\n"
        elif "pagination" in t:
            draft += "Баг: админ-панель показывает 20 заказов, но в БД их 1000. "
            "Фронтенд запрашивает /api/orders?page=1&limit=20 — всё ок. "
            "Листает — page=2, page=3... данные есть. "
            "Но page=100 отправляет запрос и ... 200 OK с пустым массивом. "
            "Не 404, не ошибка — просто пусто. "
            "Фронтенд показывает 'Нет данных', хотя админ не понимает — "
            "это конец или баг? "
            "Лучше: включать total_pages в ответ, "
            "а на запрос page > total_pages возвращать 400 Bad Request.\n"
        elif "rate" in t or "429" in t:
            draft += "Ситуация: нагрузочное тестирование API. "
            "На 1000-м запросе API начал возвращать 429 Too Many Requests. "
            "Сервис лёг на 5 минут. "
            "Анализ: rate limit был 1000 req/min на IP. "
            "Нагружали с одной машины. "
            "Решение: тестировать с разных IP, "
            "проверять Retry-After заголовок и делать паузу. "
            "Прод: rate limit должен быть выше ожидаемого трафика.\n"
        else:
            draft += "Кейс: POST /api/users с полем email. "
            "Отправляю email = ''. Ответ 201 Created, пользователь создан без email. "
            "Документация: 'email — required'. "
            "Бэкенд: 'там стоит @NotBlank, это фронтенд косяк'. "
            "Проверили: аннотация стоит, но на уровне сервера, "
            "а DTO не проходит валидацию. "
            "Оказывается: валидация включена только для определённых профилей. "
            "Баг: профиль 'staging' не включает валидацию email.\n"
    elif "auth" in t or "jwt" in t:
        draft += "Кейс: пентест. Отправляю JWT с alg: 'none' и пустой подписью. "
        "Сервер: 200 OK, доступ к данным. "
        "Почему: библиотека проверки JWT старая, alg='none' разрешён для legacy. "
        "Рекомендация: обновить библиотеку, "
        "включить валидацию алгоритма (только RS256/HS256). "
        "Тест: всегда проверяй alg и exp.\n"
    else:
        draft += (
            "Реальный баг из прода: тестировщик не проверил граничный случай, "
            "потому что 'такое не может произойти'. "
            "Произошло. Упал прод. "
            "Вывод: если что-то может сломаться — оно сломается. "
            "Тестируй негативные сценарии."
        )

    draft += (
        f"\n💬 Сталкивался с похожим? Делись историей в комментах!\n"
    )

    links = get_links(name)
    if links:
        draft += f"\n🔗 Подробнее: {links[0]}"
        if len(links) > 1:
            draft += f"\n   {links[1]}"

    return draft


# ── Main digest builder ─────────────────────────────────────────

def generate_digest():
    """Generate full digest with 3-4 post drafts."""
    date_str = datetime.now().strftime("%d.%m.%Y")
    profile = load_channel_profile()
    recs = get_scout_recs()
    plan_items = get_content_plan_items()
    ch_names = load_competitor_names()

    # Get educators best matched topic + 2-3 more
    # Run educator to get assigned topics
    tip_text, tip_file = get_educator_tip()
    topics = get_all_topics()

    # Select 3-4 topics: best match + 2-3 random from available
    # Read educator history to know what's available
    history = {}
    hist_file = AGENTS_DIR / "educator" / "history.json"
    if hist_file.exists():
        history = json.loads(hist_file.read_text())
    sent = set(history.get("sent_topics", []))
    available = [t for t in topics if t["topic"] not in sent]
    if not available:
        available = topics

    # Pick best (the topic of today's tip) + others
    selected = []
    tip_topic_name = ""
    if tip_text:
        for line in tip_text.split("\n"):
            if line.startswith("# Backend Tip:"):
                tip_topic_name = line.replace("# Backend Tip:", "").strip()
                break
        # Find the matching topic dict
        for t in available:
            if t["topic"] == tip_topic_name:
                selected.append(t)
                break
        else:
            # Not in available (already sent), pick from available
            pass

    # Fill up to 4 topics
    remaining = [t for t in available if t not in selected]
    random.shuffle(remaining)
    while len(selected) < 4 and remaining:
        t = remaining.pop()
        if t not in selected:
            selected.append(t)

    formats = ["deep", "cheatsheet", "interactive", "case"]
    fns = {"deep": format_draft_deep, "cheatsheet": format_draft_checklist,
            "interactive": format_draft_interactive, "case": format_draft_case}
    drafts = []
    for i, topic in enumerate(selected[:4]):
        draft = fns[formats[i]](topic, i + 1)
        drafts.append(draft)

    # Build digest
    lines = []
    lines.append(f"⚡ Ежедневный дайджест | {date_str}")
    lines.append("=" * 50)
    lines.append("")

    # POST DRAFTS
    lines.append("📝 ЧЕРНОВИКИ ПОСТОВ НА СЕГОДНЯ")
    lines.append("")
    for i, draft in enumerate(drafts):
        lines.append(draft)
        lines.append("")
        if i < len(drafts) - 1:
            lines.append("─" * 40)
            lines.append("")

    # COMPETITOR INSIGHTS
    lines.append("📊 ЧТО У КОНКУРЕНТОВ")
    lines.append("")
    for r in recs:
        if r["words"]:
            lines.append(f"• {r['cat']}: пишут про {', '.join(r['words'][:3])}")
    if not recs:
        lines.append("• Данных пока нет")

    # Content plan
    if plan_items:
        lines.append("")
        lines.append("📋 НА ЭТОЙ НЕДЕЛЕ ПО ПЛАНУ")
        lines.append("")
        for p in plan_items:
            lines.append(f"• {p}")

    # Channel stats
    if profile:
        lines.append("")
        lines.append("📈 КАНАЛ В ЦИФРАХ")
        lines.append(f"• {profile.get('total_posts', 0)} постов всего")
        lines.append(f"• Средняя длина: ~{profile.get('avg_post_length_chars', 0)} символов")
        topics_list = list(profile.get("topics", {}).keys())[:5]
        if topics_list:
            lines.append(f"• В фокусе: {', '.join(topics_list)}")

    lines.append("")
    lines.append("=" * 50)
    lines.append(f"Сгенерировано {datetime.now().strftime('%H:%M %d.%m.%Y')}")
    lines.append("Выбери вариант, адаптируй под себя и публикуй 👍")

    return "\n".join(lines), tip_topic_name, [t["topic"] for t in selected]


def main():
    send = "--send" in sys.argv
    digest, tip_topic, selected_topics = generate_digest()

    print(digest)

    if send:
        sys.path.insert(0, str(AGENTS_DIR.parent / "lib"))
        try:
            from mailer import send_report
            date_str = datetime.now().strftime("%Y-%m-%d")
            scout_report = AGENTS_DIR / "scout" / "reports" / f"report_{date_str}.md"

            attachments = []
            if scout_report.exists():
                attachments.append(str(scout_report))

            # Include all 3-4 topic tip files
            # (they may not all exist as individual files, but include what we can)
            for f in AGENTS_DIR.glob("educator/tips/tip_*.md"):
                if f.name not in [Path(a).name for a in attachments]:
                    attachments.append(str(f))

            send_report(
                f"⚡ Дайджест | {date_str} | {len(selected_topics)} черновика",
                digest,
                attachments=attachments
            )
            print(f"\n[digest] Письмо отправлено ({len(selected_topics)} черновиков)")
        except Exception as e:
            print(f"\n[digest] Ошибка: {e}")
    else:
        print(f"\n[digest] Запусти с --send чтобы отправить письмо")


if __name__ == "__main__":
    main()
