import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "data" / "analysis.db")
NOTABLE_POSTS_DIR = Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Notable")
OBSIDIAN_STRAT = Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Ежедневный")

DEFAULT_CHANNELS = [
    "@qachanell", "@qabigtech", "@rvtsakunov", "@rvtsakunov_manual",
    "@burning_tester", "@protestinginfo", "@qa_chillout", "@testerlib",
    "@serious_tester", "@qa_and_it", "@eddytester",
]

POSTS_PER_CHANNEL = 50

NOTABLE_PERCENTILE = 10

ENGAGEMENT_WEIGHTS = {"views": 1, "replies": 3, "forwards": 5}

# Пост цели: зачем написан этот пост
GOAL_KEYWORDS = {
    "прогрев": ["а вы", "как вы", "что вы", "делитесь", "у вас так было", "знакомо",
                "я недавно", "история", "мои мысли", "делюсь"],
    "экспертиза": ["как работает", "разбор", "под капотом", "архитектур", "реализаци",
                   "паттерн", "антипаттерн", "лучшие практик", "best practice",
                   "как мы", "почему так", "отличие", "сравнение", "deep dive",
                   "туториал", "гайд", "шпаргалк", "cheat sheet", "пошагов"],
    "продажа": ["попробуй", "попробуйте", "запишись", "курс", "промо", "скидк",
                "бесплатн", "доступ", "регистрируйс", "ссылка", "t.me/", "@", "бот"],
    "hot_take": ["не согласен", "спорно", "на самом деле", "все врут", "правда в том",
                 "холивар", "жарен", "провокаци", "бесит", "достало", "раздражает"],
    "news": ["вышл", "релиз", "обновлен", "анонс", "новость", "теперь", "запустил",
             "выпустил", "апдейт", "changelog", "release", "новый"],
    "meta": ["канал", "подписчик", "рубрик", "контент", "эфир", "\n\n---\n\n", "дайджест"],
}
CATEGORY_KEYWORDS = {
    "api/bugs": ["баг", "bug", "api", "ошибк", "багрепорт", "дефект", "тест-кейс", "test case",
                  "postman", "rest", "soap", "graphql", "crud", "endpoint", "http", "status code"],
    "tools": ["инструмент", "tool", "библиотек", "framework", "фреймворк", "charles", "fiddler",
              "selenium", "playwright", "cypress", "appium", "junit", "testng", "allure", "docker",
              "kubernetes", "k8s", "jenkins", "gitlab", "ci/cd", "devops"],
    "career": ["карьер", "career", "собеседован", "interview", "резюме", "cv", "зарплат", "salary",
               "job", "работа", "ваканси", "senior", "middle", "junior", "лид", "lead", "менеджер"],
    "opinion": ["мнение", "opinion", "думаю", "считаю", "имхо", "imo", "на мой взгляд",
                "проблема", "проблемы отрасли", "почему", "зачем", "бесит", "достало"],
    "learning": ["курс", "course", "обучени", "learn", "книг", "book", "ресурс", "resource",
                 "урок", "lesson", "гайд", "guide", "туториал", "tutorial", "шпаргалк", "cheat"],
    "engagement": ["опрос", "poll", "голосовани", "что вы", "а вы", "как вы", "сколько",
                   "тест", "quiz", "викторин"],
    "meme": ["мем", "meme", "смешн", "funny", "шутк", "joke", "прикол", "😂", "🤣", "💀"],
    "meta": ["канал", "channel", "подписчик", "subscriber", "блог", "blog", "telegram",
             "пост", "post", "контент", "content", "рубрик", "редакци"],
}
