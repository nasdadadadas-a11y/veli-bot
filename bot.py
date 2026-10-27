import asyncio, os, random, re, zlib
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from html import escape as esc

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, InputMediaPhoto,
    BotCommandScopeChat, MenuButtonDefault, ReplyKeyboardMarkup, KeyboardButton
)
from dotenv import load_dotenv

import db
from recipes import RECIPES

load_dotenv()
bot = Bot(
    os.getenv("BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# Telegram id разработчика (через запятую, если несколько). Задаётся переменной ADMIN_ID.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "").replace(" ", "").split(",") if x.isdigit()}
BOT_USERNAME = None  # узнаём при запуске, нужно для ссылок «Поделиться»

# картинка для приветствия и главного меню (лежит рядом с bot.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# какая картинка к какому времени суток; "welcome" - приветствие, пока неизвестен часовой пояс
BANNER_FILES = {
    "morning": "banner_morning.jpg",
    "day": "banner_day.jpg",
    "evening": "banner_evening.jpg",
    "night": "banner_night.jpg",
    "welcome": "banner.png",
}
BANNER_IDS = {}  # после первой отправки запоминаем номер файла в Telegram, чтобы не загружать заново

# ---------- данные ----------

LABEL = {
    "breakfast": "завтрак",
    "lunch": "обед",
    "dinner": "ужин",
    "snack": "перекус",
}

# все рецепты одним списком; номер рецепта = его позиция в списке
ALL = [r for group in RECIPES.values() for r in group]
NAME_TO_IDX = {r["name"]: i for i, r in enumerate(ALL)}
POOLS = {k: [NAME_TO_IDX[r["name"]] for r in v] for k, v in RECIPES.items()}
POOLS["random"] = list(range(len(ALL)))

def slug(name):
    """Короткий постоянный код рецепта для ссылок: не меняется, даже если порядок рецептов изменится."""
    return format(zlib.crc32(name.encode("utf-8")) & 0xFFFFFFFF, "x")

SLUG_TO_IDX = {slug(r["name"]): i for i, r in enumerate(ALL)}

def pool_for(key, uid):
    """Номера рецептов категории. Если духовки нет, рецепты с духовкой не предлагаем."""
    pool = POOLS[key]
    if db.get_oven(uid) == 0:
        pool = [i for i in pool if not ALL[i]["oven"]] or pool
    return pool

# что запоминаем, пока бот запущен
HISTORY = {}      # пользователь -> номера просмотренных рецептов (для «Предыдущий»)
FRIDGE_MODE = set()  # кто сейчас вводит продукты для поиска
LAST_FRIDGE = {}  # последняя подборка «из холодильника»

ZONES = [
    ("Калининград", 2), ("Москва", 3),
    ("Самара", 4), ("Пермь, Екатеринбург", 5),
    ("Омск", 6), ("Красноярск", 7),
    ("Иркутск", 8), ("Якутск", 9),
    ("Владивосток", 10),
]

# ---------- тексты (можно свободно править и добавлять свои варианты) ----------

FIRST_TEXT = (
    "Привет, я Veli. Твой помощник в питании.\n"
    "У меня собрано 100 простых рецептов для твоего ритма!\n\n"
    "Выбери свой часовой пояс, чтобы я понимал, "
    "какие рецепты предложить прямо сейчас."
)

HELP_TEXT = (
    "Я Veli, твой помощник в питании. Вот что я умею:\n\n"
    "• Подбирать завтрак, обед или ужин по твоему времени суток\n"
    "• Искать рецепты из продуктов, которые есть дома\n"
    "• Учитывать, есть ли у тебя духовка\n"
    "• Показывать время, цену и КБЖУ на одну порцию\n"
    "• Сохранять любимые рецепты в избранное\n\n"
    "Главное меню всегда под рукой: кнопка «Меню» внизу или команда /menu"
)

TZ_TEXT = "Выбери свой часовой пояс, чтобы я подсказывал рецепты по твоему времени."
TZ_SAVED = "Готово, часовой пояс сохранён!"

OVEN_TEXT = (
    "Есть ли у тебя духовка?\n"
    "От этого зависит, какие рецепты я буду предлагать. "
    "Без духовки подберу блюда для плиты, сковороды и микроволновки."
)
OVEN_SAVED = {
    1: "Отлично, буду предлагать и блюда из духовки.",
    0: "Принято, готовим без духовки. Подберу блюда для плиты и сковороды.",
}

SETTINGS_TEXTS = [
    "Ты в настройках. Здесь избранное, часовой пояс и духовка.",
    "Настройки. Можно открыть избранное, поменять часовой пояс или ответ про духовку.",
]

GREETINGS = {
    "morning": [
        "Доброе утро! Самое время для завтрака.",
        "С добрым утром! Давай начнём день с чего-нибудь вкусного.",
        "Утро — отличное время, чтобы нормально позавтракать.",
    ],
    "day": [
        "Добрый день! Пора обедать.",
        "Время обеда! Сейчас подберём что-нибудь сытное.",
        "Привет! Обед пропускать не стоит, давай выберем что-нибудь вкусное.",
    ],
    "evening": [
        "Добрый вечер! Самое время для ужина.",
        "Вечер — время неспешного ужина. Что приготовим?",
        "Как прошёл день? Давай придумаем что-нибудь вкусное на ужин.",
    ],
    "night": [
        "Уже поздно, но если захотелось перекусить, у меня есть лёгкие идеи.",
        "Ночью лучше что-нибудь лёгкое. Смотри, что у меня есть.",
        "Не спится или просто захотелось перекусить? Есть пара лёгких вариантов.",
    ],
}

MENU_LINE = [
    "Ты в главном меню. Отсюда можно выбрать любое действие.",
    "Это главное меню. Выбирай, что хочешь сделать дальше.",
    "Ты в главном меню. Выбери, с чего начнём.",
]

WISHES = {
    "morning": [
        "Пусть утро будет спокойным. У тебя всё получится сегодня.",
        "Хорошего начала дня! Ты справишься со всем, что запланировано.",
        "Ты заслуживаешь хороший день. Пусть он сложится легко.",
    ],
    "day": [
        "Хорошего дня! Ты на правильном пути, заботясь о себе.",
        "Пусть остаток дня пройдёт легко. Ты отлично справляешься.",
        "Не забывай делать паузы. Ты делаешь достаточно.",
    ],
    "evening": [
        "Спокойного вечера. День был длинным, пора немного позаботиться о себе.",
        "Пусть вечер будет тёплым и уютным. За плечами целый день, и это уже немало.",
        "Отдыхай без чувства вины. Отдых тебе очень нужен.",
    ],
    "night": [
        "Спокойной ночи и мягкого сна. Завтра всё получится.",
        "Пусть эта ночь даст тебе отдых. Ты отлично справляешься.",
        "Не засиживайся допоздна. Отдых нужен всем, и тебе тоже.",
    ],
}

# совет дня на главном экране
FACTS = [
    "Чем больше разных цветов на тарелке, тем разнообразнее набор витаминов.",
    "Белок в завтраке помогает дольше не чувствовать голод.",
    "Замороженные овощи и ягоды сохраняют почти все витамины и стоят дешевле свежих вне сезона.",
    "Крупы, бобовые и сезонные овощи — самая выгодная по цене основа рациона.",
    "Иногда жажда маскируется под голод. Стакан воды перед перекусом не помешает.",
    "Приготовь сразу на два-три приёма пищи: это экономит и время, и деньги.",
    "Сытость приходит примерно через 15–20 минут после начала еды, так что не торопись.",
    "Если утром нет аппетита, начни с лёгкого: йогурта, фрукта или смузи.",
    "Цельнозерновой хлеб и овсянка дольше дают чувство сытости, чем белая выпечка.",
    "Составь список покупок на неделю, и лишних трат станет меньше.",
    "Остатки ужина — готовый обед на завтра.",
    "Разнообразие важнее идеальности: привычные блюда — это нормально, новые — приятный бонус.",
]

INTROS = {
    "breakfast": [
        "Смотри, что можно приготовить на завтрак:",
        "Вот вкусная идея для утра:",
        "Как насчёт такого завтрака?",
        "Завтрак на подходе, держи вариант:",
    ],
    "lunch": [
        "Вот что можно съесть на обед:",
        "Сытная идея для обеда:",
        "Как тебе такой обед?",
        "Обед не за горами, держи вариант:",
    ],
    "dinner": [
        "Смотри, что можно приготовить на ужин:",
        "Вот спокойная идея для вечера:",
        "Как насчёт такого ужина?",
        "Ужин на подходе, держи вариант:",
    ],
    "snack": [
        "Вот лёгкий перекус для тебя:",
        "Что-нибудь небольшое и вкусное:",
        "Как насчёт такого перекуса?",
        "Держи идею, чтобы продержаться до следующей еды:",
    ],
    "random": [
        "Доверимся случаю! Вот что выпало:",
        "Сюрприз для тебя:",
        "Случайный выбор, а получилось вкусно:",
        "Посмотрим, что подскажет случай:",
    ],
    "fav": [
        "Из твоего избранного:",
        "Один из твоих любимых рецептов:",
        "Вот он, твой любимчик:",
        "Рецепт из избранного, готовим?",
    ],
    "shared": [
        "Тебе поделились рецептом из Veli:",
        "Смотри, какой рецепт тебе прислали:",
        "Рецепт, которым с тобой поделились:",
    ],
    "fridge": [
        "Отличный выбор из того, что есть дома:",
        "Из твоих продуктов получится вот что:",
        "Холодильник не подвёл, смотри:",
    ],
}

OUTROS = {
    "breakfast": [
        "Хорошего утра и приятного аппетита!",
        "Пусть завтрак зарядит тебя на весь день.",
        "Приятного аппетита! Хорошего дня.",
    ],
    "lunch": [
        "Приятного аппетита! Пусть остаток дня пройдёт легко.",
        "Хорошего обеда и немного отдыха после него.",
        "Готовь с удовольствием, всё получится.",
    ],
    "dinner": [
        "Приятного аппетита и спокойного вечера!",
        "Пусть ужин будет уютным.",
        "Приятного аппетита. Пусть вечер будет тёплым.",
    ],
    "snack": [
        "Приятного аппетита!",
        "Небольшая радость между делами. Наслаждайся.",
        "Вкусного перекуса!",
    ],
    "random": [
        "Приятного аппетита!",
        "Получится вкусно, в этом нет сомнений.",
        "Если что-то пойдёт не так, ничего страшного. Получится в следующий раз.",
    ],
    "fav": [
        "Приятного аппетита!",
        "Хороший выбор. Готовь с удовольствием.",
        "Любимое всегда получается лучше всего.",
    ],
    "shared": [
        "Приятного аппетита! Хочешь больше рецептов под свой ритм? Нажми «Меню» внизу.",
        "Готовь с удовольствием. В главном меню я подберу ещё варианты под твоё время суток.",
    ],
    "fridge": [
        "Приятного аппетита! И никакой еды в мусор.",
        "Готовь с удовольствием, продукты уже ждут.",
        "Получится вкусно, а холодильник скажет спасибо.",
    ],
}

ALL_TEXTS = [
    "Что хочется? Выбери приём пищи или доверься случаю.",
    "Любой приём пищи на твой вкус. А если не хочется выбирать, жми на случайный рецепт.",
    "Выбирай, что готовим. Можно по времени дня, а можно и наугад.",
]

FAV_LIST_TEXTS = [
    "Твоё избранное. Выбери, что приготовим:",
    "Здесь твои любимые рецепты. С чего начнём?",
]

FAV_EMPTY = (
    "В избранном пока пусто. Открой любой рецепт и нажми «В избранное», "
    "чтобы он появился здесь."
)

FRIDGE_ASK = [
    "Заглянем в холодильник? Напиши продукты, которые у тебя есть, через запятую. "
    "Например: яйца, помидоры, сыр.",
    "Что есть дома? Перечисли продукты через запятую, а я подберу, что из них можно приготовить. "
    "Например: курица, рис, морковь.",
]

FRIDGE_FOUND = [
    "Вот что можно приготовить из твоих продуктов:",
    "Смотри, что получится из того, что есть дома:",
]

FRIDGE_NOTE = (
    "Масло, соль, воду и специи я считаю всегда имеющимися. "
    "Можешь написать ещё продукты, и подборка обновится."
)

FRIDGE_NONE = (
    "Пока ничего подходящего не нашлось. Попробуй добавить пару основных продуктов: "
    "яйца, крупу, овощи или творог. Я подожду."
)

FALLBACKS = [
    "Я лучше всего понимаю кнопки. Нажми «Меню» внизу, там всё самое вкусное.",
    "Хочешь рецепт? Нажми «Меню» внизу или отправь /menu.",
]

# ---------- поиск по продуктам ----------
# слово в сообщении пользователя -> продукт из рецептов (сравниваем начало слова)
STEMS = {
    "яйцо": ["яйц", "яиц"],
    "куриная грудка": ["кур", "грудк"],
    "куриный фарш": ["фарш"],
    "филе минтая": ["минта", "рыб"],
    "тунец консервированный": ["тунец", "тунц"],
    "гречка": ["греч"],
    "рис": ["рис"],
    "макароны": ["макарон", "спагет", "лапш", "пенне"],
    "овсяные хлопья": ["овсян", "хлопь", "геркулес"],
    "хлеб цельнозерновой": ["хлеб", "тост", "батон"],
    "хлебцы": ["хлебц"],
    "лаваш": ["лаваш"],
    "мука": ["мук"],
    "картофель": ["картоф", "картош"],
    "морковь": ["морков"],
    "лук": ["лук"],
    "чеснок": ["чесно"],
    "помидор": ["помидор", "томат"],
    "огурец": ["огур"],
    "болгарский перец": ["перец", "перц"],
    "кабачок": ["кабач", "цукини", "цуккини"],
    "капуста белокочанная": ["капуст"],
    "брокколи": ["брокол"],
    "шпинат замороженный": ["шпинат"],
    "свёкла": ["свекл"],
    "тыква": ["тыкв"],
    "шампиньоны": ["шампин", "гриб"],
    "зелёный горошек замороженный": ["горош"],
    "кукуруза консервированная": ["кукуруз"],
    "фасоль консервированная": ["фасол"],
    "нут консервированный": ["нут"],
    "красная чечевица": ["чечев"],
    "банан": ["банан"],
    "яблоко": ["яблок", "яблон"],
    "апельсин": ["апельсин"],
    "ягоды замороженные": ["ягод", "клубник", "малин", "черник", "смородин", "вишн"],
    "молоко 2,5%": ["молок"],
    "кефир 1%": ["кефир"],
    "йогурт натуральный": ["йогурт"],
    "творог 5%": ["творог"],
    "сметана 15%": ["сметан"],
    "сыр твёрдый": ["сыр"],
    "арахисовая паста": ["арахис"],
    "грецкие орехи": ["орех", "грецк"],
    "кукуруза для попкорна": ["попкорн"],
}
# слова, которые значат продукт только целиком
EXACT = {"паста": "макароны", "филе": "куриная грудка"}
# эти продукты не нужны для поиска (считаем, что они всегда есть дома)
PANTRY = ("масло", "соль", "вода", "специи", "перец черн")

def norm(s):
    return s.lower().replace("ё", "е")

def match_token(token):
    """Какие продукты из рецептов подходят под один пункт списка пользователя."""
    t = norm(token)
    if "фарш" in t:
        return {"куриный фарш"}
    if "арахис" in t:
        return {"арахисовая паста"}
    words = t.split()
    hits = set()
    for name, prefixes in STEMS.items():
        if any(w.startswith(p) for w in words for p in prefixes):
            hits.add(name)
    if t in EXACT:
        hits.add(EXACT[t])
    return hits

def parse_products(text):
    parts = re.split(r"[,;\n]+|\s+и\s+", text.lower())
    have, unknown = set(), []
    for p in parts:
        p = p.strip(" .!?")
        if not p:
            continue
        if any(norm(p).startswith(x) for x in PANTRY):
            continue
        hit = match_token(p)
        if hit:
            have |= hit
        else:
            unknown.append(p)
    return have, unknown

def find_recipes(have, oven_ok=True, limit=6):
    found = []
    for i, r in enumerate(ALL):
        if r["oven"] and not oven_ok:
            continue
        keys = r["keys"]
        got = [k for k in keys if k in have]
        missing = [k for k in keys if k not in have]
        if got and len(missing) <= 3:
            found.append((len(missing), -len(got), r["price"], i, missing))
    found.sort()
    return found[:limit]

# ---------- время суток ----------

def local_hour(tz):
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=tz)))
    return now.hour

def day_part(hour):
    """(время суток, какой приём пищи предлагать)"""
    if 5 <= hour < 11:
        return "morning", "breakfast"
    if 11 <= hour < 16:
        return "day", "lunch"
    if 16 <= hour < 22:
        return "evening", "dinner"
    return "night", "snack"

# ---------- клавиатуры ----------

GREEN = "success"   # зелёные кнопки: выбор приёма пищи и «Ещё вариант»
RED = "danger"      # красная кнопка «Предыдущий»


def cap(text):
    """Первая буква заглавная (остальное не трогаем)."""
    return text[:1].upper() + text[1:]

def btn(text, data, style=None):
    """Кнопка. style: 'success' (зелёная), 'danger' (красная), 'primary' (синяя)."""
    if style:
        try:
            return InlineKeyboardButton(text=text, callback_data=data, style=style)
        except Exception:
            pass  # если версия aiogram старая, делаем обычную кнопку
    return InlineKeyboardButton(text=text, callback_data=data)

MENU_TEXT = "Меню"
PIN_TEXT = "Кнопка «Меню» всегда под рукой: она закреплена внизу."
KB_SHOWN = set()  # кому уже показали закреплённую кнопку (пока бот запущен)

def pinned_kb():
    """Широкая кнопка «Меню» под полем ввода. Остаётся на любом экране бота."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )

async def send_pinned(chat_id, uid):
    try:
        await bot.send_message(chat_id, PIN_TEXT, reply_markup=pinned_kb())
        KB_SHOWN.add(uid)
        db.set_kb(uid)
    except Exception as e:
        print("Не удалось показать закреплённую кнопку:", e)

class PinnedKbMiddleware(BaseMiddleware):
    """Один раз показывает закреплённую кнопку каждому пользователю, в том числе тем, кто уже пользовался ботом."""
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        is_start = isinstance(event, Message) and (event.text or "").startswith("/start")
        if user and not is_start and user.id not in KB_SHOWN:
            if db.kb_shown(user.id):
                KB_SHOWN.add(user.id)
            else:
                msg = event if isinstance(event, Message) else getattr(event, "message", None)
                if msg is not None:
                    await send_pinned(msg.chat.id, user.id)
        return await handler(event, data)

dp.message.outer_middleware(PinnedKbMiddleware())
dp.callback_query.outer_middleware(PinnedKbMiddleware())

def kb(rows):
    if not rows:
        return None  # без кнопок: пустую клавиатуру Telegram не любит
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tz_kb(back=False):
    rows = []
    for i in range(0, len(ZONES), 2):
        rows.append([
            btn(f"{name} (UTC+{off})", f"tz:{off}")
            for name, off in ZONES[i:i + 2]
        ])
    if back:
        rows.append([btn("Назад", "settings")])
    return kb(rows)

def home_kb(meal):
    return kb([
        [btn(f"Подобрать {LABEL[meal]}", f"cat:{meal}", GREEN)],
        [btn("Что в холодильнике", "fridge")],
        [btn("Другой приём пищи", "all")],
        [btn("Настройки", "settings")],
    ])

def oven_kb(back=False):
    rows = [
        [btn("Да, есть", "oven:1", GREEN)],
        [btn("Нет, готовлю без духовки", "oven:0")],
    ]
    if back:
        rows.append([btn("Назад", "settings")])
    return kb(rows)

def settings_kb():
    return kb([
        [btn("Избранное", "favs")],
        [btn("Изменить часовой пояс", "tzmenu")],
        [btn("Изменить ответ про духовку", "ovenmenu")],
    ])

def all_kb():
    return kb([
        [btn("Завтрак", "cat:breakfast", GREEN), btn("Обед", "cat:lunch", GREEN)],
        [btn("Ужин", "cat:dinner", GREEN), btn("Перекус", "cat:snack", GREEN)],
        [btn("Случайный рецепт", "cat:random", GREEN)],
    ])

# флаги раскрытых разделов рецепта; число порций тоже хранится в флагах (биты 4 и 8)
SHOW_PRODUCTS = 1
SHOW_STEPS = 2
SERVINGS = {}  # сколько порций выбрал пользователь (запоминаем, пока бот запущен)

def servings(flags):
    return ((flags >> 2) & 3) + 1

def with_servings(flags, n):
    return (flags & 3) | ((n - 1) << 2)

def start_flags(uid):
    return with_servings(0, SERVINGS.get(uid, 1))

def need_lines(r, n):
    """Список продуктов на n порций. Количества целые: на одну порцию уже округлены вверх."""
    lines = []
    for name, qty, label in r["items"]:
        if qty is None:
            lines.append(f"{name} — по вкусу")
        else:
            lines.append(f"{name} — {qty * n} {label}")
    return lines

def share_url(r):
    if not BOT_USERNAME:
        return None
    link = f"https://t.me/{BOT_USERNAME}?start=r{slug(r['name'])}"
    text = (f"{cap(r['name'])}: {r['price']} ₽ на порцию, {r['time']} мин, "
            f"{r['kcal']} ккал. Рецепт из Veli.")
    return "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote(text, safe="")

def url_btn(text, url):
    return InlineKeyboardButton(text=text, url=url)

def recipe_kb(user_id, idx, key, flags=0, seed=0):
    hist = HISTORY.get(user_id, [])
    rows = []
    if key == "fav":
        rows.append([btn("К избранному", "favs")])
    elif key == "fridge":
        rows.append([btn("К результатам", "fridge_back")])
    elif key == "shared":
        pass
    else:
        first_row = []
        if len(hist) >= 2:
            first_row.append(btn("Предыдущий", f"prev:{key}", RED))
        first_row.append(btn("Ещё вариант", f"cat:{key}", GREEN))
        rows.append(first_row)
    n = servings(flags)
    next_n = n % 4 + 1
    p_text = "Скрыть продукты" if flags & SHOW_PRODUCTS else "Список продуктов"
    s_text = "Скрыть пошаговый рецепт" if flags & SHOW_STEPS else "Пошаговый рецепт"
    rows.append([
        btn(p_text, f"t:{idx}:{key}:{flags ^ SHOW_PRODUCTS}:{seed}"),
        btn(f"Порции: {n}", f"p:{idx}:{key}:{with_servings(flags, next_n)}:{seed}"),
    ])
    rows.append([btn(s_text, f"t:{idx}:{key}:{flags ^ SHOW_STEPS}:{seed}")])
    name = ALL[idx]["name"]
    rating = db.get_rating(user_id, name)
    rows.append([
        btn("❤️", f"rt:{idx}:{key}:{flags}:{seed}:1", GREEN if rating == 1 else None),
        btn("👎", f"rt:{idx}:{key}:{flags}:{seed}:-1", RED if rating == -1 else None),
    ])
    fav_text = "Убрать из избранного" if db.is_fav(user_id, name) else "В избранное"
    row = [btn(fav_text, f"fav:{idx}:{key}:{flags}:{seed}")]
    link = share_url(ALL[idx])
    if link:
        row.append(url_btn("Поделиться", link))
    rows.append(row)
    return kb(rows)

def recipe_button_label(i):
    r = ALL[i]
    return cap(r["name"])

def favs_kb(names):
    rows = [[btn(recipe_button_label(NAME_TO_IDX[n]), f"r:{NAME_TO_IDX[n]}:fav")]
            for n in names if n in NAME_TO_IDX]
    rows.append([btn("Назад", "settings")])
    return kb(rows)

def fridge_kb(indices=()):
    rows = [[btn(recipe_button_label(i), f"r:{i}:fridge")] for i in indices]
    return kb(rows)

# ---------- сборка сообщений ----------

def reset_state(uid):
    HISTORY.pop(uid, None)
    FRIDGE_MODE.discard(uid)

def home_screen(tz):
    part, meal = day_part(local_hour(tz))
    text = (
        f"{random.choice(GREETINGS[part])}\n\n"
        f"{random.choice(MENU_LINE)}\n\n"
        f"💡 <i>Совет дня: {random.choice(FACTS)}</i>\n\n"
        f"{random.choice(WISHES[part])}"
    )
    return text, home_kb(meal), part

def recipe_message(r, key, flags=0, seed=0):
    intros, outros = INTROS[key], OUTROS[key]
    lines = [
        intros[seed % len(intros)],
        "",
        f"{r['emoji']} <b>{esc(cap(r['name']))}</b>",
        f"<i>{esc(r['about'])}</i>",
        "",
        f"Время приготовления: {r['time']} мин",
        *([ "Нужна духовка" ] if r.get("oven") else []),
        *([f"Порций: {servings(flags)}"] if servings(flags) > 1 else []),
        f"Цена на одну порцию: ~{r['price']} ₽",
        *([f"Цена на все порции: ~{r['price'] * servings(flags)} ₽"] if servings(flags) > 1 else []),
        f"Калорийность на порцию: <b>{r['kcal']} ккал</b>",
        f"Белки {r['p']} г · Жиры {r['f']} г · Углеводы {r['c']} г",
    ]
    if flags & SHOW_PRODUCTS:
        n = servings(flags)
        title = "Список продуктов" if n == 1 else f"Список продуктов на {n} порции"
        lines += ["", f"<blockquote><b>🛒 {title}</b>\n"
                  + "\n".join(f"• {esc(cap(x))}" for x in need_lines(r, n))
                  + "</blockquote>"]
    if flags & SHOW_STEPS:
        lines += ["", "<blockquote><b>👩‍🍳 Пошаговый рецепт</b>\n"
                  + "\n".join(f"{i}. {esc(s)}" for i, s in enumerate(r["steps"], 1))
                  + ("\n<i>Количества в шагах указаны для одной порции, ориентируйся на список продуктов.</i>"
                     if servings(flags) > 1 else "")
                  + "</blockquote>"]
    if not (flags & 3):
        lines += ["", "<i>Нажми на кнопки ниже, чтобы открыть список продуктов и пошаговый рецепт.</i>"]
    if r.get("tip"):
        lines += ["", f"💡 <i>Совет: {esc(r['tip'])}</i>"]
    lines += ["", outros[(seed // 7) % len(outros)]]
    return "\n".join(lines)

async def show_recipe(c, idx, key, push=True, flags=None, seed=None):
    """Показывает рецепт номер idx и запоминает его в истории."""
    uid = c.from_user.id
    if flags is None:
        flags = start_flags(uid)
    if seed is None:
        seed = random.randint(0, 999)
    hist = HISTORY.setdefault(uid, [])
    if push and (not hist or hist[-1] != idx):
        hist.append(idx)
        del hist[:-30]
    if push:
        db.log(uid, "recipe", ALL[idx]["name"])
    await to_text(
        c,
        recipe_message(ALL[idx], key, flags, seed),
        recipe_kb(uid, idx, key, flags, seed),
    )

# ---------- показ экранов (с картинкой и без) ----------

def banner_source(key):
    """Что отправлять в Telegram: номер файла из кэша или сам файл. None, если картинки нет."""
    if key in BANNER_IDS:
        return BANNER_IDS[key]
    path = os.path.join(BASE_DIR, BANNER_FILES.get(key, ""))
    if os.path.exists(path):
        return FSInputFile(path)
    return None

def remember_banner(key, sent):
    if key not in BANNER_IDS and sent and sent.photo:
        BANNER_IDS[key] = sent.photo[-1].file_id

async def send_banner(message, caption, markup, key="welcome"):
    """Отправляет картинку с подписью и кнопками. Без файла картинки отправит просто текст."""
    photo = banner_source(key)
    if photo is None:
        return await message.answer(caption, reply_markup=markup)
    sent = await message.answer_photo(photo, caption=caption, reply_markup=markup)
    remember_banner(key, sent)
    return sent

async def safe_delete(message):
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

async def to_text(c, text, markup):
    """Показывает обычный текстовый экран. Если сейчас на экране картинка, заменяет её текстом."""
    if c.message.photo:
        await safe_delete(c.message)
        await c.message.answer(text, reply_markup=markup)
        return
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise

async def to_photo(c, caption, markup, key="welcome"):
    """Показывает экран с картинкой (приветствие, главное меню). Картинка зависит от времени суток."""
    photo = banner_source(key)
    if c.message.photo and photo is not None:
        try:
            sent = await c.message.edit_media(
                InputMediaPhoto(media=photo, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=markup,
            )
            remember_banner(key, sent)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise
        return
    await safe_delete(c.message)
    await send_banner(c.message, caption, markup, key)

# ---------- обработчики ----------

async def send_home(m: Message):
    uid = m.from_user.id
    tz = db.get_tz(uid)
    if tz is None:
        await send_banner(m, FIRST_TEXT, tz_kb())
    elif db.get_oven(uid) is None:
        await send_banner(m, OVEN_TEXT, oven_kb())
    else:
        reset_state(uid)
        text, markup, part = home_screen(tz)
        await send_banner(m, text, markup, part)

@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    uid = m.from_user.id
    db.log(uid, "start")
    await send_pinned(m.chat.id, uid)
    arg = command.args or ""
    if arg.startswith("r") and arg[1:] in SLUG_TO_IDX:
        # перешли по ссылке друга: сначала показываем присланный рецепт
        idx = SLUG_TO_IDX[arg[1:]]
        db.log(uid, "shared_open", ALL[idx]["name"])
        seed = random.randint(0, 999)
        flags = start_flags(uid)
        await m.answer(
            recipe_message(ALL[idx], "shared", flags, seed),
            reply_markup=recipe_kb(uid, idx, "shared", flags, seed),
        )
        return
    await send_home(m)

@dp.message(F.text == MENU_TEXT)
async def pinned_menu(m: Message):
    """Нажатие закреплённой кнопки «Меню» работает на любом экране, даже когда бот ждёт продукты."""
    await send_home(m)

@dp.message(Command("menu"))
async def menu_cmd(m: Message):
    await send_home(m)

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(HELP_TEXT)

@dp.message(Command("tz"))
async def tz_cmd(m: Message):
    await m.answer(TZ_TEXT, reply_markup=tz_kb())

@dp.callback_query(F.data.startswith("tz:"))
async def save_tz(c: CallbackQuery):
    tz = int(c.data.split(":")[1])
    db.set_tz(c.from_user.id, tz)
    db.log(c.from_user.id, "tz", tz)
    reset_state(c.from_user.id)
    if db.get_oven(c.from_user.id) is None:
        await to_photo(c, f"{TZ_SAVED}\n\n{OVEN_TEXT}", oven_kb())
    else:
        text, markup, part = home_screen(tz)
        await to_photo(c, f"{TZ_SAVED}\n\n{text}", markup, part)
    await c.answer()

@dp.callback_query(F.data == "ovenmenu")
async def oven_menu(c: CallbackQuery):
    await to_text(c, OVEN_TEXT, oven_kb(back=True))
    await c.answer()

@dp.callback_query(F.data.startswith("oven:"))
async def save_oven(c: CallbackQuery):
    uid = c.from_user.id
    value = int(c.data.split(":")[1])
    db.set_oven(uid, value)
    reset_state(uid)
    tz = db.get_tz(uid)
    if tz is None:
        await to_photo(c, FIRST_TEXT, tz_kb())
    else:
        text, markup, part = home_screen(tz)
        await to_photo(c, f"{OVEN_SAVED[value]}\n\n{text}", markup, part)
    await c.answer()

@dp.callback_query(F.data == "tzmenu")
async def tz_menu(c: CallbackQuery):
    await to_text(c, TZ_TEXT, tz_kb(back=True))
    await c.answer()

@dp.callback_query(F.data == "settings")
async def settings(c: CallbackQuery):
    await to_text(c, random.choice(SETTINGS_TEXTS), settings_kb())
    await c.answer()

@dp.callback_query(F.data == "menu")
async def back_to_menu(c: CallbackQuery):
    uid = c.from_user.id
    tz = db.get_tz(uid)
    if tz is None:
        await to_photo(c, FIRST_TEXT, tz_kb())
    elif db.get_oven(uid) is None:
        await to_photo(c, OVEN_TEXT, oven_kb())
    else:
        reset_state(uid)
        text, markup, part = home_screen(tz)
        await to_photo(c, text, markup, part)
    await c.answer()

@dp.callback_query(F.data == "all")
async def all_meals(c: CallbackQuery):
    await to_text(c, random.choice(ALL_TEXTS), all_kb())
    await c.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def pick_recipe(c: CallbackQuery):
    key = c.data.split(":")[1]
    hist = HISTORY.get(c.from_user.id, [])
    current = hist[-1] if hist else None
    uid = c.from_user.id
    pool = pool_for(key, uid)
    disliked = db.rated_names(uid, -1)
    liked = db.rated_names(uid, 1)
    options = [i for i in pool if i != current and ALL[i]["name"] not in disliked]
    options = options or [i for i in pool if i != current] or pool
    weights = [2 if ALL[i]["name"] in liked else 1 for i in options]
    idx = random.choices(options, weights)[0]
    db.log(uid, "cat", key)
    await show_recipe(c, idx, key)
    await c.answer()

@dp.callback_query(F.data.startswith("prev:"))
async def previous_recipe(c: CallbackQuery):
    key = c.data.split(":")[1]
    hist = HISTORY.get(c.from_user.id, [])
    if len(hist) < 2:
        await c.answer("Это самый первый рецепт в подборке")
        return
    hist.pop()
    await show_recipe(c, hist[-1], key, push=False)
    await c.answer()

@dp.callback_query(F.data.startswith("t:"))
async def toggle_section(c: CallbackQuery):
    """Раскрывает или скрывает список продуктов и пошаговый рецепт."""
    _, idx, key, flags, seed = c.data.split(":")
    await show_recipe(c, int(idx), key, push=False, flags=int(flags), seed=int(seed))
    await c.answer()

@dp.callback_query(F.data.startswith("p:"))
async def change_servings(c: CallbackQuery):
    """Переключает число порций: 1, 2, 3, 4 и снова 1."""
    _, idx, key, flags, seed = c.data.split(":")
    flags = int(flags)
    SERVINGS[c.from_user.id] = servings(flags)
    db.log(c.from_user.id, "portions", servings(flags))
    await show_recipe(c, int(idx), key, push=False, flags=flags, seed=int(seed))
    await c.answer(f"Порций: {servings(flags)}")

@dp.callback_query(F.data.startswith("rt:"))
async def rate_recipe(c: CallbackQuery):
    _, idx, key, flags, seed, value = c.data.split(":")
    idx, value = int(idx), int(value)
    uid = c.from_user.id
    name = ALL[idx]["name"]
    if db.get_rating(uid, name) == value:
        db.set_rating(uid, name, 0)
        toast = "Оценка убрана"
    else:
        db.set_rating(uid, name, value)
        db.log(uid, "rate", f"{value}|{name}")
        toast = ("Спасибо, буду чаще предлагать похожее!" if value == 1
                 else "Спасибо, такое предлагать реже.")
    await c.message.edit_reply_markup(
        reply_markup=recipe_kb(uid, idx, key, int(flags), int(seed))
    )
    await c.answer(toast)

@dp.callback_query(F.data.startswith("fav:"))
async def toggle_fav(c: CallbackQuery):
    _, idx, key, flags, seed = c.data.split(":")
    idx = int(idx)
    name = ALL[idx]["name"]
    if db.is_fav(c.from_user.id, name):
        db.remove_fav(c.from_user.id, name)
        toast = "Убрано из избранного"
    else:
        db.add_fav(c.from_user.id, name)
        db.log(c.from_user.id, "fav_add", name)
        toast = "Добавлено в избранное. Хороший выбор!"
    # меняем только кнопки, текст рецепта остаётся прежним
    await c.message.edit_reply_markup(
        reply_markup=recipe_kb(c.from_user.id, idx, key, int(flags), int(seed))
    )
    await c.answer(toast)

@dp.callback_query(F.data == "favs")
async def show_favs(c: CallbackQuery):
    names = [n for n in db.list_favs(c.from_user.id) if n in NAME_TO_IDX]
    if not names:
        await to_text(c, FAV_EMPTY, kb([[btn("Назад", "settings")]]))
    else:
        await to_text(c, random.choice(FAV_LIST_TEXTS), favs_kb(names))
    await c.answer()

@dp.callback_query(F.data.startswith("r:"))
async def open_recipe(c: CallbackQuery):
    _, idx, key = c.data.split(":")
    await show_recipe(c, int(idx), key)
    await c.answer()

# ----- «что в холодильнике» -----

@dp.callback_query(F.data == "fridge")
async def fridge_start(c: CallbackQuery):
    FRIDGE_MODE.add(c.from_user.id)
    await to_text(c, random.choice(FRIDGE_ASK), fridge_kb())
    await c.answer()

@dp.callback_query(F.data == "fridge_back")
async def fridge_back(c: CallbackQuery):
    saved = LAST_FRIDGE.get(c.from_user.id)
    FRIDGE_MODE.add(c.from_user.id)
    if saved:
        text, indices = saved
        await to_text(c, text, fridge_kb(indices))
    else:
        await to_text(c, random.choice(FRIDGE_ASK), fridge_kb())
    await c.answer()

@dp.message(Command("fridge"))
async def fridge_cmd(m: Message):
    uid = m.from_user.id
    reset_state(uid)
    FRIDGE_MODE.add(uid)
    await m.answer(random.choice(FRIDGE_ASK))

@dp.message(Command("favorites"))
async def favorites_cmd(m: Message):
    uid = m.from_user.id
    reset_state(uid)
    names = [n for n in db.list_favs(uid) if n in NAME_TO_IDX]
    if not names:
        await m.answer(FAV_EMPTY)
    else:
        await m.answer(random.choice(FAV_LIST_TEXTS), reply_markup=favs_kb(names))

@dp.message(Command("myid"))
async def my_id(m: Message):
    """Показывает твой Telegram id: он нужен, чтобы назвать себя разработчиком (ADMIN_ID)."""
    await m.answer(f"Твой Telegram ID: <code>{m.from_user.id}</code>")

def stats_text(st):
    def pct(a, b):
        return f"{round(100 * a / b)}%" if b else "0%"
    cats = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин", "snack": "перекус", "random": "случайный"}
    lines = [
        "<b>Статистика Veli</b>", "",
        f"Пользователей: {st['users']} (новых: {st['new_day']} за сутки, {st['new_week']} за неделю)",
        f"Активных: {st['active_day']} за сутки, {st['active_week']} за неделю",
        f"Рецептов показано: {st['views']} (за неделю: {st['views_week']})",
        f"Поиск по холодильнику: {st['fridge']}",
        f"Добавлено в избранное: {st['fav_adds']}",
        f"Открыто по ссылке «Поделиться»: {st['shared_open']}",
        f"Оценки: {st['likes']} понравилось, {st['dislikes']} не очень",
        f"Духовка: есть у {st['oven_yes']}, нет у {st['oven_no']} "
        f"({pct(st['oven_yes'], st['oven_yes'] + st['oven_no'])} с духовкой)",
    ]
    if st["cats"]:
        lines += ["", "<b>Что выбирают</b>"] + [f"• {cats.get(k, k)}: {v}" for k, v in st["cats"]]
    if st["top_recipes"]:
        lines += ["", "<b>Топ рецептов по просмотрам</b>"] + [f"• {esc(cap(n))}: {v}" for n, v in st["top_recipes"]]
    if st["top_liked"]:
        lines += ["", "<b>Чаще всего нравятся</b>"] + [f"• {esc(cap(n))}: {v}" for n, v in st["top_liked"]]
    if st["top_disliked"]:
        lines += ["", "<b>Чаще всего «не очень»</b>"] + [f"• {esc(cap(n))}: {v}" for n, v in st["top_disliked"]]
    if st["portions"]:
        lines += ["", "<b>Порции</b>: " + ", ".join(f"{k}: {v}" for k, v in st["portions"])]
    if st["tz"]:
        lines += ["", "<b>Часовые пояса</b>: " + ", ".join(f"UTC+{k}: {v}" for k, v in st["tz"])]
    if st["unknown"]:
        lines += ["", "<b>Продукты, которые бот не узнал</b>"] + [f"• {esc(n)}: {v}" for n, v in st["unknown"]]
    return "\n".join(lines)

@dp.message(Command("stats"))
async def stats_cmd(m: Message):
    """Статистика видна только разработчику (его id задан в ADMIN_ID). Остальным команда не отвечает."""
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer(stats_text(db.stats()))

@dp.message(F.text)
async def any_text(m: Message):
    uid = m.from_user.id
    if uid not in FRIDGE_MODE:
        await m.answer(random.choice(FALLBACKS))
        return
    have, unknown = parse_products(m.text)
    unknown_line = ""
    if unknown:
        shown = ", ".join(esc(u) for u in unknown[:5])
        unknown_line = f"\n\nНе распознал: {shown}. Я знаю не все продукты, но учусь."
    db.log(uid, "fridge", len(have))
    for u in unknown[:5]:
        db.log(uid, "unknown", u.lower()[:40])
    results = find_recipes(have, db.get_oven(uid) != 0)
    if not results:
        await m.answer(FRIDGE_NONE + unknown_line, reply_markup=fridge_kb())
        return
    lines = [random.choice(FRIDGE_FOUND), ""]
    indices = []
    for _, _, _, i, missing in results:
        indices.append(i)
        status = ("Все продукты есть" if not missing
                  else "Нужно докупить: " + ", ".join(missing))
        lines.append(f"{ALL[i]['emoji']} <b>{esc(cap(ALL[i]['name']))}</b>\n{esc(status)}\n")
    text = "\n".join(lines) + "\n" + FRIDGE_NOTE + unknown_line
    LAST_FRIDGE[uid] = (text, indices)
    await m.answer(text, reply_markup=fridge_kb(indices))

async def start_web():
    """Крошечный сайт для хостинга Render: он отвечает "ok", чтобы сервис считался живым.
    Локально на ноутбуке не включается (переменной PORT там нет)."""
    port = os.getenv("PORT")
    if not port:
        return
    from aiohttp import web

    async def ok(request):
        return web.Response(text="Veli is alive")

    app = web.Application()
    app.router.add_get("/", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()

async def setup_menu_button():
    """Убирает круглую кнопку со списком команд рядом с полем ввода.
    Остаётся только закреплённая кнопка «Меню» под полем ввода. Команды /menu, /fridge и другие по-прежнему работают."""
    try:
        await bot.delete_my_commands()
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        for admin in ADMIN_IDS:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin))
    except Exception as e:
        print("Не удалось убрать круглую кнопку:", e)

async def main():
    global BOT_USERNAME
    db.init()
    try:
        BOT_USERNAME = (await bot.get_me()).username
    except Exception:
        BOT_USERNAME = None
    await setup_menu_button()
    await start_web()
    await dp.start_polling(bot)

asyncio.run(main())
