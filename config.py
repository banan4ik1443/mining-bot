import os
import ast

# ==================== НАСТРОЙКИ БОТА ====================

# Токен бота (можно оставить пустым, если используешь local_config.py)
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# ID администраторов
admin_ids_str = os.environ.get('ADMIN_IDS', '[8044082858]')
try:
    ADMIN_IDS = ast.literal_eval(admin_ids_str)
except:
    ADMIN_IDS = [8044082858]

# Юзернейм бота
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'Bananazzabot')

# Настройки майнинга
MINING_COOLDOWN = 0  # 1 час в секундах
BASE_REWARD = 10  # Базовая награда за майнинг
HASHRATE_MULTIPLIER = 0.4  # Множитель хешрейта к награде
WEAR_PER_USE = 5  # Износ за один майнинг
MIN_WEAR_FOR_MINING = 20  # Минимальный износ для работы карты
REPAIR_COST = 100  # Стоимость ремонта

# Настройки опыта
EXP_FROM_MINING_BASE = 10  # Базовый опыт за майнинг
EXP_FROM_HASHRATE = 0.2  # Опыт от хешрейта

# Стартовая карта
STARTER_CARD_NAME = "Встроенная графика Intel HD"
STARTER_CARD_HASHRATE = 5  # 5 MH/s
START_BALANCE = 1000  # Стартовый баланс в тонах

# Настройки рефералов
REFERRAL_BONUS = 600  # Бонус пригласившему в тонах
REFERRAL_EXP_BONUS = 300  # Бонус пригласившему в опыте
REFERRAL_BONUS_FOR_NEW = 200  # Бонус новому пользователю в тонах
REFERRAL_EXP_FOR_NEW = 50  # Бонус новому пользователю в опыте

# Настройки ежедневного бонуса
DAILY_BONUS_AMOUNT = 100  # Ежедневный бонус в тонах
DAILY_BONUS_EXP = 50  # Ежедневный бонус в опыте
DAILY_STREAK_BONUS = True  # Включить бонус за стрик
STREAK_MULTIPLIER = {
    7: 2,    # x2 на 7 день
    30: 3,   # x3 на 30 день
    100: 5,  # x5 на 100 день
    365: 10  # x10 на 365 день
}

# Настройки уровней
MAX_LEVEL = 100
LEVEL_UP_BASE_TON = 1000  # Базовая стоимость повышения уровня в тонах
LEVEL_UP_BASE_EXP = 500  # Базовая стоимость повышения уровня в опыте
LEVEL_COST_MULTIPLIER = 1.5  # Множитель стоимости за уровень

# Кастомные стоимости уровней (если нужно переопределить)
CUSTOM_LEVEL_COSTS = {
    # 2: {"ton": 500, "exp": 200},  # Пример для 2 уровня
}

# Награды за уровни
LEVEL_REWARDS = {
    1: {"ton": 0, "exp": 0, "bonus": "Нет награды"},
    2: {"ton": 100, "exp": 50, "bonus": "+100 тон, +50 опыта"},
    3: {"ton": 200, "exp": 100, "bonus": "+200 тон, +100 опыта"},
    4: {"ton": 300, "exp": 150, "bonus": "+300 тон, +150 опыта"},
    5: {"ton": 500, "exp": 200, "bonus": "+500 тон, +200 опыта"},
    10: {"ton": 1000, "exp": 500, "bonus": "Скидка на ремонт 5%", "repair_discount": 5},
    15: {"ton": 1500, "exp": 750, "bonus": "Бонус к стартовому ASIC x1.5", "starter_bonus": 1.5},
    20: {"ton": 2000, "exp": 1000, "bonus": "+5 MH/s ко всем ASIC", "hash_bonus": 5},
    25: {"ton": 2500, "exp": 1250, "bonus": "Скидка на ремонт 10%", "repair_discount": 10},
    30: {"ton": 3000, "exp": 1500, "bonus": "Бонус к стартовому ASIC x2", "starter_bonus": 2.0},
    35: {"ton": 3500, "exp": 1750, "bonus": "+10 MH/s ко всем ASIC", "hash_bonus": 10},
    40: {"ton": 4000, "exp": 2000, "bonus": "Скидка на ремонт 15%", "repair_discount": 15},
    45: {"ton": 4500, "exp": 2250, "bonus": "+15 MH/s ко всем ASIC", "hash_bonus": 15},
    50: {"ton": 5000, "exp": 2500, "bonus": "Бонус к стартовому ASIC x3", "starter_bonus": 3.0},
}

# Настройки привилегий
PRIVILEGES = {
    "player": {
        "name": "Игрок",
        "icon": "👤",
        "price": 0,
        "duration": 0,
        "description": "Обычный игрок",
        "bonuses": {
            "ton_multiplier": 1.0,
            "exp_multiplier": 1.0,
            "repair_discount": 0,
            "hash_bonus": 0,
            "daily_bonus_multiplier": 1.0,
            "max_cards": 10,
            "event_chance_multiplier": 1.0
        }
    },
    "premium": {
        "name": "Премиум",
        "icon": "⭐",
        "price": 50,
        "duration": 30,
        "description": "Премиум статус на 30 дней",
        "bonuses": {
            "ton_multiplier": 1.5,
            "exp_multiplier": 1.5,
            "repair_discount": 10,
            "hash_bonus": 0,
            "daily_bonus_multiplier": 1.5,
            "max_cards": 15,
            "event_chance_multiplier": 1.5
        }
    },
    "vip": {
        "name": "VIP",
        "icon": "👑",
        "price": 150,
        "duration": 30,
        "description": "VIP статус на 30 дней",
        "bonuses": {
            "ton_multiplier": 2.0,
            "exp_multiplier": 2.0,
            "repair_discount": 20,
            "hash_bonus": 5,
            "daily_bonus_multiplier": 2.0,
            "max_cards": 20,
            "event_chance_multiplier": 2.0
        }
    },
    "legend": {
        "name": "Легенда",
        "icon": "🌟",
        "price": 500,
        "duration": 30,
        "description": "Легендарный статус на 30 дней",
        "bonuses": {
            "ton_multiplier": 3.0,
            "exp_multiplier": 3.0,
            "repair_discount": 30,
            "hash_bonus": 10,
            "daily_bonus_multiplier": 3.0,
            "max_cards": 25,
            "event_chance_multiplier": 2.5
        }
    }
}

# Настройки платежей (звезды)
STARS_PAYMENT_PROVIDER_TOKEN = ""  # Токен для оплаты звездами
STARS_CURRENCY = "XTR"  # Валюта для звезд

# Настройки случайных событий
RANDOM_EVENTS_ENABLED = True
EVENT_CHANCE = 10  # 10% шанс события

EVENTS = [
    {
        "name": "Везение",
        "icon": "🍀",
        "chance": 30,
        "description": "Тебе сегодня везёт!",
        "ton_multiplier": 2.0
    },
    {
        "name": "Неудача",
        "icon": "😔",
        "chance": 20,
        "description": "Сегодня не твой день...",
        "ton_multiplier": 0.5
    },
    {
        "name": "Находка",
        "icon": "💎",
        "chance": 15,
        "description": "Ты нашёл старый кошелёк!",
        "ton_bonus": 500
    },
    {
        "name": "Опыт",
        "icon": "✨",
        "chance": 15,
        "description": "Ты много узнал сегодня!",
        "exp_multiplier": 2.0
    },
    {
        "name": "Бережливость",
        "icon": "🔧",
        "chance": 10,
        "description": "Карты износились меньше!",
        "wear_reduction": 2
    },
    {
        "name": "Халява",
        "icon": "🎁",
        "chance": 5,
        "description": "Бесплатный ремонт!",
        "free_repair": True
    },
    {
        "name": "Джекпот",
        "icon": "💰",
        "chance": 5,
        "description": "ТЫ СОРВАЛ ДЖЕКПОТ!",
        "ton_multiplier": 5.0,
        "exp_multiplier": 3.0
    }
]

# Настройки автопополнения магазина
AUTO_RESTOCK_ENABLED = True
AUTO_RESTOCK_TIME = "12:00"  # Время пополнения (МСК)
AUTO_RESTOCK_MIN_ITEMS = 3  # Минимальное количество для пополнения
AUTO_RESTOCK_MAX_ITEMS = 7  # Максимальное количество для пополнения
RESTOCK_CHANCE_BY_PRICE = {
    "low": 70,        # 70% шанс для дешевых карт (<1000)
    "medium": 50,     # 50% шанс для средних карт (1000-3000)
    "high": 30,       # 30% шанс для дорогих карт (3000-6000)
    "very_high": 15   # 15% шанс для очень дорогих карт (>6000)
}

# Иконки для разных категорий
LEVEL_ICONS = {
    (1, 9): "🌱",
    (10, 19): "🌿",
    (20, 29): "🌳",
    (30, 39): "🏔",
    (40, 49): "👑",
    (50, 100): "⭐"
}

CARD_COUNT_ICONS = {
    5: "💻",
    10: "🖥",
    20: "🏢",
    50: "🏭"
}

REFERRAL_ICONS = {
    1: "🤝",
    5: "👥",
    10: "👨‍👩‍👧",
    20: "👨‍👩‍👧‍👦",
    50: "👪"
}

TOP_ICONS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

SEASONAL_ICONS = {
    1: "❄️",   # Январь
    2: "☃️",   # Февраль
    3: "🌸",   # Март
    4: "🌷",   # Апрель
    5: "🌺",   # Май
    6: "☀️",   # Июнь
    7: "🏖",   # Июль
    8: "🍉",   # Август
    9: "🍂",   # Сентябрь
    10: "🎃",  # Октябрь
    11: "🍁",  # Ноябрь
    12: "🎄"   # Декабрь
}