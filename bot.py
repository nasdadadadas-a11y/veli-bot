import asyncio, os, random, re
from datetime import datetime, timezone, timedelta
from html import escape as esc

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, InputMediaPhoto
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
    "У меня собрано более 50 простых рецептов для твоего ритма!\n\n"
    "Выбери свой часовой пояс, чтобы я понимал, "
    "какие рецепты предложить прямо сейчас."
)

HELP_TEXT = (
    "Я Veli, твой помощник в питании. Вот что я умею:\n\n"
    "• Подбирать завтрак, обед или ужин по твоему времени суток\n"
    "• Искать рецепты из продуктов, которые есть дома\n"
    "• Показывать время, цену и КБЖУ на одну порцию\n"
    "• Сохранять любимые рецепты в избранное\n\n"
    "Главное меню всегда под рукой: /menu"
)

TZ_TEXT = "Выбери свой часовой пояс, чтобы я подсказывал рецепты по твоему времени."
TZ_SAVED = "Готово, часовой пояс сохранён!"

SETTINGS_TEXTS = [
    "Ты в настройках. Здесь твоё избранное и часовой пояс.",
    "Настройки. Можно открыть избранное или поменять часовой пояс.",
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
    "Я лучше всего понимаю кнопки. Загляни в /menu, там всё самое вкусное.",
    "Хочешь рецепт? Открой /menu, и я всё подскажу.",
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

def find_recipes(have, limit=6):
    found = []
    for i, r in enumerate(ALL):
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

def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)

MENU_BTN = "В меню"

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

def settings_kb():
    return kb([
        [btn("Избранное", "favs")],
        [btn("Изменить часовой пояс", "tzmenu")],
        [btn(MENU_BTN, "menu")],
    ])

def all_kb():
    return kb([
        [btn("Завтрак", "cat:breakfast", GREEN), btn("Обед", "cat:lunch", GREEN)],
        [btn("Ужин", "cat:dinner", GREEN), btn("Перекус", "cat:snack", GREEN)],
        [btn("Случайный рецепт", "cat:random", GREEN)],
        [btn(MENU_BTN, "menu")],
    ])

# флаги раскрытых разделов рецепта
SHOW_PRODUCTS = 1
SHOW_STEPS = 2

def recipe_kb(user_id, idx, key, flags=0, seed=0):
    hist = HISTORY.get(user_id, [])
    rows = []
    if key == "fav":
        rows.append([btn("К избранному", "favs")])
    elif key == "fridge":
        rows.append([btn("К результатам", "fridge_back")])
    else:
        first_row = []
        if len(hist) >= 2:
            first_row.append(btn("Предыдущий", f"prev:{key}", RED))
        first_row.append(btn("Ещё вариант", f"cat:{key}", GREEN))
        rows.append(first_row)
    p_text = "Скрыть список продуктов" if flags & SHOW_PRODUCTS else "Список продуктов"
    s_text = "Скрыть пошаговый рецепт" if flags & SHOW_STEPS else "Пошаговый рецепт"
    rows.append([btn(p_text, f"t:{idx}:{key}:{flags ^ SHOW_PRODUCTS}:{seed}")])
    rows.append([btn(s_text, f"t:{idx}:{key}:{flags ^ SHOW_STEPS}:{seed}")])
    fav_text = ("Убрать из избранного" if db.is_fav(user_id, ALL[idx]["name"])
                else "В избранное")
    rows.append([btn(fav_text, f"fav:{idx}:{key}:{flags}:{seed}")])
    rows.append([btn(MENU_BTN, "menu")])
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
    rows.append([btn(MENU_BTN, "menu")])
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
        f"Цена на одну порцию: ~{r['price']} ₽",
        f"Калорийность на порцию: <b>{r['kcal']} ккал</b>",
        f"Белки {r['p']} г · Жиры {r['f']} г · Углеводы {r['c']} г",
    ]
    if flags & SHOW_PRODUCTS:
        lines += ["", "<blockquote><b>🛒 Список продуктов</b>\n"
                  + "\n".join(f"• {esc(cap(x))}" for x in r["need"])
                  + "</blockquote>"]
    if flags & SHOW_STEPS:
        lines += ["", "<blockquote><b>👩‍🍳 Пошаговый рецепт</b>\n"
                  + "\n".join(f"{i}. {esc(s)}" for i, s in enumerate(r["steps"], 1))
                  + "</blockquote>"]
    if not flags:
        lines += ["", "<i>Нажми на кнопки ниже, чтобы открыть список продуктов и пошаговый рецепт.</i>"]
    if r.get("tip"):
        lines += ["", f"💡 <i>Совет: {esc(r['tip'])}</i>"]
    lines += ["", outros[(seed // 7) % len(outros)]]
    return "\n".join(lines)

async def show_recipe(c, idx, key, push=True, flags=0, seed=None):
    """Показывает рецепт номер idx и запоминает его в истории."""
    uid = c.from_user.id
    if seed is None:
        seed = random.randint(0, 999)
    hist = HISTORY.setdefault(uid, [])
    if push and (not hist or hist[-1] != idx):
        hist.append(idx)
        del hist[:-30]
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
    else:
        reset_state(uid)
        text, markup, part = home_screen(tz)
        await send_banner(m, text, markup, part)

@dp.message(CommandStart())
async def start(m: Message):
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
    reset_state(c.from_user.id)
    text, markup, part = home_screen(tz)
    await to_photo(c, f"{TZ_SAVED}\n\n{text}", markup, part)
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
    options = [i for i in POOLS[key] if i != current]
    idx = random.choice(options or POOLS[key])
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

@dp.message(F.text)
async def any_text(m: Message):
    uid = m.from_user.id
    if uid not in FRIDGE_MODE:
        await m.answer(random.choice(FALLBACKS), reply_markup=kb([[btn(MENU_BTN, "menu")]]))
        return
    have, unknown = parse_products(m.text)
    unknown_line = ""
    if unknown:
        shown = ", ".join(esc(u) for u in unknown[:5])
        unknown_line = f"\n\nНе распознал: {shown}. Я знаю не все продукты, но учусь."
    results = find_recipes(have)
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

async def main():
    db.init()
    await start_web()
    await dp.start_polling(bot)

asyncio.run(main())
