import asyncio
import logging
import sqlite3
import os
import sys
import random
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, ContentType, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config
from cards_config import SHOP_CARDS
# В самом верху файла, после других импортов
from keep_alive import keep_alive

# Запускаем веб-сервер для UptimeRobot
keep_alive()
print("🌐 Веб-сервер для пинга запущен на порту 8080")

# Далее ваш существующий код...
# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Функция для экранирования специальных символов HTML
def escape_html(text):
    """Экранирует специальные символы для HTML"""
    if text is None:
        return ""
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('mining_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        # Таблица пользователей с custom_id и временем бана
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                custom_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                gems REAL DEFAULT 100,
                hash_rate REAL DEFAULT 0,
                cards_count INTEGER DEFAULT 1,
                referrals INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                banned INTEGER DEFAULT 0,
                ban_until TIMESTAMP DEFAULT NULL,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_mining TIMESTAMP DEFAULT NULL,
                total_mined REAL DEFAULT 0,
                last_repair TIMESTAMP DEFAULT NULL,
                boxes_count INTEGER DEFAULT 0
            )
        ''')
        
        # Проверяем и добавляем новые колонки, если их нет
        try:
            self.cursor.execute('ALTER TABLE users ADD COLUMN privilege TEXT DEFAULT "player"')
        except sqlite3.OperationalError:
            pass
        
        try:
            self.cursor.execute('ALTER TABLE users ADD COLUMN privilege_until TIMESTAMP DEFAULT NULL')
        except sqlite3.OperationalError:
            pass
        
        try:
            self.cursor.execute('ALTER TABLE users ADD COLUMN total_stars_spent INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        
        try:
            self.cursor.execute('ALTER TABLE users ADD COLUMN boxes_count INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        
        # Таблица видеокарт пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_name TEXT,
                hash_rate REAL,
                wear INTEGER DEFAULT 100,
                is_starter INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица магазина
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_name TEXT,
                hash_rate REAL,
                price INTEGER,
                stock INTEGER,
                photo TEXT
            )
        ''')
        
        # Таблица фотографий карт
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS card_photos (
                card_id INTEGER,
                photo_id TEXT,
                FOREIGN KEY (card_id) REFERENCES shop (id)
            )
        ''')
        
        # Таблица статистики
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_cards_sold INTEGER DEFAULT 0,
                total_gems_earned REAL DEFAULT 0,
                total_mining_actions INTEGER DEFAULT 0,
                total_boxes_opened INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица для отслеживания последнего автоматического пополнения
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_restock_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_restock TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица для ежедневных бонусов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_bonus (
                user_id INTEGER PRIMARY KEY,
                last_bonus DATE,
                streak INTEGER DEFAULT 0,
                total_bonus INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица для случайных событий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_name TEXT,
                event_time TIMESTAMP,
                reward TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица для логов действий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица для достижений
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_name TEXT,
                unlocked_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица для коробок
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                box_type TEXT DEFAULT 'common',
                opened INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                opened_at TIMESTAMP DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица для компонентов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                component_type TEXT,
                component_name TEXT,
                amount INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
        self.init_shop()

    def init_shop(self):
        self.cursor.execute("SELECT COUNT(*) FROM shop")
        if self.cursor.fetchone()[0] == 0:
            for photo, card_data in SHOP_CARDS.items():
                self.cursor.execute('''
                    INSERT INTO shop (card_name, hash_rate, price, stock, photo) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    card_data['name'],
                    card_data['hash_rate'],
                    card_data['price'],
                    card_data['stock'],
                    photo
                ))
            self.conn.commit()
        
        self.cursor.execute("SELECT COUNT(*) FROM stats")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO stats DEFAULT VALUES")
            self.conn.commit()

    def add_user(self, user_id, username, first_name, referrer_id=None):
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if self.cursor.fetchone():
                return
            
            self.cursor.execute("SELECT COUNT(*) FROM users")
            count = self.cursor.fetchone()[0]
            custom_id = count + 1
            
            # Генерируем ник по умолчанию
            if username:
                default_nick = username
            else:
                # Генерируем случайный ник с префиксом miner_
                random_num = random.randint(1000, 9999)
                default_nick = f"miner_{random_num}"
                # Проверяем, не занят ли такой ник
                while self.is_nickname_taken(default_nick):
                    random_num = random.randint(1000, 9999)
                    default_nick = f"miner_{random_num}"
            
            self.cursor.execute('''
                INSERT INTO users 
                (user_id, custom_id, username, first_name, gems, referrer_id, level, exp, privilege, boxes_count) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, custom_id, username, default_nick, config.START_BALANCE, referrer_id, 1, 0, "player", 0))
            
            self.cursor.execute('''
                INSERT INTO user_cards (user_id, card_name, hash_rate, wear, is_starter) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, config.STARTER_CARD_NAME, config.STARTER_CARD_HASHRATE, 100, 1))
            
            self.cursor.execute('''
                UPDATE users SET hash_rate = hash_rate + ? WHERE user_id = ?
            ''', (config.STARTER_CARD_HASHRATE, user_id))
            
            # Начисляем бонусы за реферала
            if referrer_id:
                self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (referrer_id,))
                referrer = self.cursor.fetchone()
                
                if referrer:
                    # Начисляем бонус пригласившему
                    self.cursor.execute('''
                        UPDATE users SET 
                            gems = gems + ?,
                            exp = exp + ?,
                            referrals = referrals + 1 
                        WHERE user_id = ?
                    ''', (config.REFERRAL_BONUS, config.REFERRAL_EXP_BONUS, referrer_id))
                    
                    # Начисляем бонус новому пользователю
                    self.cursor.execute('''
                        UPDATE users SET 
                            gems = gems + ?,
                            exp = exp + ? 
                        WHERE user_id = ?
                    ''', (config.REFERRAL_BONUS_FOR_NEW, config.REFERRAL_EXP_FOR_NEW, user_id))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding user: {e}")

    def is_nickname_taken(self, nickname, exclude_user_id=None):
        """Проверяет, занят ли никнейм"""
        if exclude_user_id:
            self.cursor.execute('SELECT user_id FROM users WHERE first_name = ? AND user_id != ?', (nickname, exclude_user_id))
        else:
            self.cursor.execute('SELECT user_id FROM users WHERE first_name = ?', (nickname,))
        return self.cursor.fetchone() is not None

    def change_nickname(self, user_id, new_nickname):
        """Изменяет никнейм пользователя"""
        if self.is_nickname_taken(new_nickname, user_id):
            return False, "🚫 Данный никнейм уже занят!"
        
        if len(new_nickname) > 32:
            return False, "❌ Ник не может быть длиннее 32 символов!"
        
        self.cursor.execute('UPDATE users SET first_name = ? WHERE user_id = ?', (new_nickname, user_id))
        self.conn.commit()
        return True, f"✅ Ник успешно изменен на {new_nickname}!"

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()

    def get_user_by_custom_id(self, custom_id):
        """Получает пользователя по MID"""
        self.cursor.execute('SELECT * FROM users WHERE custom_id = ?', (custom_id,))
        return self.cursor.fetchone()

    def get_user_cards(self, user_id):
        self.cursor.execute('SELECT * FROM user_cards WHERE user_id = ? ORDER BY is_starter DESC', (user_id,))
        return self.cursor.fetchall()

    def get_working_cards(self, user_id):
        """Получает работающие карты (стартовая всегда работает)"""
        user = self.get_user(user_id)
        level = user[11]
        
        # Получаем бонусы за уровень
        bonuses = self.get_level_bonuses(level)
        
        self.cursor.execute('''
            SELECT * FROM user_cards 
            WHERE user_id = ? AND (wear > ? OR is_starter = 1)
            ORDER BY is_starter DESC, wear DESC
        ''', (user_id, config.MIN_WEAR_FOR_MINING))
        
        cards = self.cursor.fetchall()
        
        # Применяем бонусы
        cards_list = list(cards)
        for i, card in enumerate(cards_list):
            card = list(card)
            
            if card[5] == 1:  # is_starter
                # Применяем бонус к стартовой карте
                card[3] = card[3] * bonuses["starter_bonus"]
            else:
                # Применяем бонус к хешрейту всех карт
                card[3] = card[3] + bonuses["hash_bonus"]
            
            cards_list[i] = tuple(card)
        
        return cards_list

    def get_level_bonuses(self, level):
        """Возвращает бонусы за указанный уровень"""
        bonuses = {
            "starter_bonus": 1.0,
            "repair_discount": 0,
            "hash_bonus": 0,
        }
        
        # Применяем бонусы из LEVEL_REWARDS
        for lvl, reward in config.LEVEL_REWARDS.items():
            if lvl <= level:
                if "starter_bonus" in reward:
                    bonuses["starter_bonus"] = reward["starter_bonus"]
                if "repair_discount" in reward:
                    bonuses["repair_discount"] = reward["repair_discount"]
                if "hash_bonus" in reward:
                    bonuses["hash_bonus"] = reward["hash_bonus"]
        
        return bonuses

    def get_level_up_cost(self, current_level):
        """Рассчитывает стоимость повышения уровня"""
        if current_level >= config.MAX_LEVEL:
            return None, None, "Достигнут максимальный уровень!"
        
        # Проверяем, есть ли кастомная стоимость для этого уровня
        if current_level + 1 in config.CUSTOM_LEVEL_COSTS:
            cost_data = config.CUSTOM_LEVEL_COSTS[current_level + 1]
            return cost_data["ton"], cost_data["exp"], None
        
        # Рассчитываем стоимость по формуле
        ton_cost = int(config.LEVEL_UP_BASE_TON * (config.LEVEL_COST_MULTIPLIER ** (current_level - 1)))
        exp_cost = int(config.LEVEL_UP_BASE_EXP * (config.LEVEL_COST_MULTIPLIER ** (current_level - 1)))
        
        return ton_cost, exp_cost, None

    def level_up(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return False, "Пользователь не найден"
        
        current_level = user[11]
        
        if current_level >= config.MAX_LEVEL:
            return False, "Достигнут максимальный уровень!"
        
        # Получаем стоимость повышения
        ton_cost, exp_cost, error = self.get_level_up_cost(current_level)
        if error:
            return False, error
        
        # Проверяем, хватает ли ресурсов
        if user[4] < ton_cost:
            return False, f"Недостаточно тон! Нужно {ton_cost} (у вас {int(user[4])})"
        
        if user[12] < exp_cost:
            return False, f"Недостаточно опыта! Нужно {exp_cost} (у вас {user[12]})"
        
        # Списываем ресурсы
        new_ton = user[4] - ton_cost
        new_exp = user[12] - exp_cost
        new_level = current_level + 1
        
        self.cursor.execute('''
            UPDATE users SET 
                gems = ?,
                exp = ?,
                level = ?
            WHERE user_id = ?
        ''', (new_ton, new_exp, new_level, user_id))
        
        self.conn.commit()
        
        # Получаем награду за уровень
        reward = config.LEVEL_REWARDS.get(new_level, {"ton": 0, "exp": 0, "bonus": "Нет награды"})
        
        # Если есть награда тоном или опытом, начисляем
        if reward["ton"] > 0 or reward["exp"] > 0:
            self.cursor.execute('''
                UPDATE users SET 
                    gems = gems + ?,
                    exp = exp + ?
                WHERE user_id = ?
            ''', (reward["ton"], reward["exp"], user_id))
            self.conn.commit()
        
        return True, {
            "old_level": current_level,
            "new_level": new_level,
            "ton_cost": ton_cost,
            "exp_cost": exp_cost,
            "reward": reward
        }

    def get_user_privilege(self, user_id):
        """Получает текущую привилегию пользователя"""
        self.cursor.execute('SELECT privilege, privilege_until FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if not result:
            return "player", None
        
        privilege = result[0]
        privilege_until = result[1]
        
        # Если privilege None, устанавливаем "player"
        if privilege is None:
            privilege = "player"
        
        # Проверяем, не истекла ли привилегия
        if privilege_until and privilege != "player":
            try:
                until = datetime.fromisoformat(privilege_until)
                if datetime.now() > until:
                    # Привилегия истекла
                    self.cursor.execute('UPDATE users SET privilege = "player", privilege_until = NULL WHERE user_id = ?', (user_id,))
                    self.conn.commit()
                    return "player", None
            except:
                pass
        
        return privilege, privilege_until

    def get_privilege_bonuses(self, privilege_name):
        """Получает бонусы для привилегии"""
        if privilege_name is None:
            privilege_name = "player"
        
        return config.PRIVILEGES.get(privilege_name, config.PRIVILEGES["player"])["bonuses"]

    def apply_privilege(self, user_id, privilege_name, days):
        """Применяет привилегию к пользователю"""
        if privilege_name not in config.PRIVILEGES:
            return False, "Привилегия не найдена"
        
        privilege_data = config.PRIVILEGES[privilege_name]
        price = privilege_data["price"]
        
        # Устанавливаем привилегию
        privilege_until = datetime.now() + timedelta(days=days)
        self.cursor.execute('''
            UPDATE users SET 
                privilege = ?,
                privilege_until = ?,
                total_stars_spent = total_stars_spent + ?
            WHERE user_id = ?
        ''', (privilege_name, privilege_until, price, user_id))
        self.conn.commit()
        
        return True, f"Привилегия {privilege_data['icon']} {privilege_data['name']} активирована до {privilege_until.strftime('%d.%m.%Y')}"

    def get_daily_bonus(self, user_id):
        """Получает ежедневный бонус"""
        today = datetime.now().date()
        
        # Получаем информацию о последнем бонусе
        self.cursor.execute('SELECT last_bonus, streak FROM daily_bonus WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if result:
            try:
                last_bonus = datetime.strptime(result[0], '%Y-%m-%d').date()
                streak = result[1]
                
                # Если уже получал сегодня
                if last_bonus == today:
                    return False, 0, 0, streak, "Сегодня бонус уже получен!"
                
                # Проверяем, был ли вчера
                if (today - last_bonus).days == 1:
                    streak += 1
                else:
                    streak = 1
            except:
                # Если ошибка парсинга даты, сбрасываем стрик
                streak = 1
        else:
            streak = 1
        
        # Получаем привилегию пользователя
        privilege, _ = self.get_user_privilege(user_id)
        priv_bonuses = self.get_privilege_bonuses(privilege)
        
        # Рассчитываем бонус
        base_ton = config.DAILY_BONUS_AMOUNT
        base_exp = config.DAILY_BONUS_EXP
        
        # Применяем множитель за стрик
        ton_bonus = base_ton
        exp_bonus = base_exp
        
        if config.DAILY_STREAK_BONUS:
            for days, multiplier in config.STREAK_MULTIPLIER.items():
                if streak >= days:
                    ton_bonus = base_ton * multiplier
                    exp_bonus = base_exp * multiplier
        
        # Применяем множитель от привилегии
        ton_bonus = int(ton_bonus * priv_bonuses["daily_bonus_multiplier"])
        exp_bonus = int(exp_bonus * priv_bonuses["daily_bonus_multiplier"])
        
        # Обновляем данные пользователя
        self.cursor.execute('UPDATE users SET gems = gems + ?, exp = exp + ? WHERE user_id = ?', 
                           (ton_bonus, exp_bonus, user_id))
        
        # Обновляем таблицу бонусов
        self.cursor.execute('''
            INSERT OR REPLACE INTO daily_bonus (user_id, last_bonus, streak, total_bonus) 
            VALUES (?, ?, ?, COALESCE((SELECT total_bonus FROM daily_bonus WHERE user_id = ?), 0) + ?)
        ''', (user_id, today, streak, user_id, ton_bonus))
        
        self.conn.commit()
        
        # Дополнительная награда за достижение стрика
        extra_reward = ""
        if streak in [7, 30, 100, 365]:
            extra_reward = f"\n🎉 Поздравляем с {streak} днями стрика!"
        
        return True, ton_bonus, exp_bonus, streak, extra_reward

    def trigger_random_event(self, user_id, base_ton, base_exp, wear_amount):
        """Активирует случайное событие при майнинге"""
        if not config.RANDOM_EVENTS_ENABLED:
            return base_ton, base_exp, wear_amount, None
        
        # Получаем привилегию пользователя
        privilege, _ = self.get_user_privilege(user_id)
        priv_bonuses = self.get_privilege_bonuses(privilege)
        
        # Проверяем шанс события с учетом привилегии
        event_chance = int(config.EVENT_CHANCE * priv_bonuses["event_chance_multiplier"])
        
        if random.randint(1, 100) > event_chance:
            return base_ton, base_exp, wear_amount, None
        
        # Выбираем случайное событие
        available_events = []
        for event in config.EVENTS:
            # Проверяем шанс конкретного события
            if random.randint(1, 100) <= event["chance"]:
                available_events.append(event)
        
        if not available_events:
            return base_ton, base_exp, wear_amount, None
        
        event = random.choice(available_events)
        event_icon = event.get("icon", "✨")
        
        # Применяем эффекты события
        new_ton = base_ton
        new_exp = base_exp
        new_wear = wear_amount
        event_description = f"{event_icon} {event['name']}!\n{event['description']}\n"
        
        if "ton_multiplier" in event:
            new_ton = int(base_ton * event["ton_multiplier"])
            event_description += f"💰 Тон: x{event['ton_multiplier']}\n"
        
        if "exp_multiplier" in event:
            new_exp = int(base_exp * event["exp_multiplier"])
            event_description += f"✨ Опыт: x{event['exp_multiplier']}\n"
        
        if "ton_bonus" in event:
            new_ton = base_ton + event["ton_bonus"]
            event_description += f"💰 +{event['ton_bonus']} тон\n"
        
        if "exp_bonus" in event:
            new_exp = base_exp + event["exp_bonus"]
            event_description += f"✨ +{event['exp_bonus']} опыта\n"
        
        if "wear_reduction" in event:
            new_wear = max(0, wear_amount - event["wear_reduction"])
            event_description += f"🔧 Износ уменьшен на {event['wear_reduction']}%\n"
        
        if event.get("free_repair", False):
            event_description += f"🔧 Следующий ремонт бесплатно!\n"
        
        # Логируем событие
        self.cursor.execute('''
            INSERT INTO events_log (user_id, event_name, event_time, reward) 
            VALUES (?, ?, ?, ?)
        ''', (user_id, event['name'], datetime.now(), event_description))
        self.conn.commit()
        
        return new_ton, new_exp, new_wear, event_description

    def buy_card(self, user_id, card_id):
        try:
            self.cursor.execute('SELECT * FROM shop WHERE id = ?', (card_id,))
            card = self.cursor.fetchone()
            
            if not card:
                return False, "Карта не найдена"
            
            # Проверяем наличие (может быть 0)
            out_of_stock = card[4] <= 0
            
            user = self.get_user(user_id)
            if not user:
                return False, "Пользователь не найден"
            
            # Получаем привилегию для проверки лимита карт
            privilege, _ = self.get_user_privilege(user_id)
            priv_bonuses = self.get_privilege_bonuses(privilege)
            max_cards = priv_bonuses["max_cards"]
            
            if user[6] >= max_cards:
                return False, f"Достигнут лимит карт ({max_cards})"
            
            if out_of_stock:
                return False, "⛔ Нет на складе"
            
            if user[4] < card[3]:
                return False, f"❌ Недостаточно средств! Нужно {card[3]} тон"
            
            self.cursor.execute('''
                UPDATE users SET 
                    gems = gems - ?,
                    cards_count = cards_count + 1,
                    hash_rate = hash_rate + ? 
                WHERE user_id = ?
            ''', (card[3], card[2], user_id))
            
            self.cursor.execute('''
                INSERT INTO user_cards (user_id, card_name, hash_rate, wear, is_starter) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, card[1], card[2], 100, 0))
            
            self.cursor.execute('UPDATE shop SET stock = stock - 1 WHERE id = ?', (card_id,))
            self.cursor.execute('UPDATE stats SET total_cards_sold = total_cards_sold + 1')
            
            self.conn.commit()
            return True, f"✅ Оплата прошла успешно! Куплено: {card[1]}", card_id
        except Exception as e:
            logger.error(f"Error buying card: {e}")
            return False, str(e), None

    def mine(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return False, "❌ Пользователь не найден"
        
        if user[9]:  # banned
            return False, "⛔ Вы забанены!"
        
        # Проверяем время последнего майнинга
        if user[14]:  # last_mining
            try:
                last_time = datetime.fromisoformat(user[14])
                time_diff = datetime.now() - last_time
                if time_diff.total_seconds() < config.MINING_COOLDOWN:
                    remaining = config.MINING_COOLDOWN - time_diff.total_seconds()
                    
                    # Форматируем оставшееся время
                    hours = int(remaining // 3600)
                    minutes = int((remaining % 3600) // 60)
                    seconds = int(remaining % 60)
                    
                    time_str = ""
                    if hours > 0:
                        time_str += f"{hours:02d}."
                    if minutes > 0 or hours > 0:
                        time_str += f"{minutes:02d}."
                    time_str += f"{seconds:02d}"
                    
                    return False, (
                        f"⏳ <b>Не прошло время до следующего майнинга!</b>\n\n"
                        f"Следующая попытка через: {time_str}\n\n"
                        f"<i>Наберись терпения, майнинг требует отдыха</i> 😴"
                    )
            except Exception as e:
                logger.error(f"Ошибка парсинга времени: {e}")
        
        # Получаем работающие карты
        cards = self.get_working_cards(user_id)
        
        # Рассчитываем базовую награду
        total_hash = sum(card[3] for card in cards)
        base_ton = int(total_hash * config.HASHRATE_MULTIPLIER) + config.BASE_REWARD
        exp_gain = config.EXP_FROM_MINING_BASE + int(total_hash * config.EXP_FROM_HASHRATE)
        
        # Случайное событие (если включено)
        event_description = None
        box_reward = None
        if config.RANDOM_EVENTS_ENABLED:
            base_ton, exp_gain, wear_amount, event_description = self.trigger_random_event(
                user_id, base_ton, exp_gain, config.WEAR_PER_USE
            )
        
        # Шанс получить коробку (10%)
        if random.random() < 0.1:
            box_id = self.add_box(user_id)
            self.cursor.execute('UPDATE users SET boxes_count = boxes_count + 1 WHERE user_id = ?', (user_id,))
            box_reward = "📦 Вы получили коробку с лутом!"
        
        # Обновляем данные
        self.cursor.execute('''
            UPDATE users SET 
                gems = gems + ?,
                total_mined = total_mined + ?,
                last_mining = ?,
                exp = exp + ?
            WHERE user_id = ?
        ''', (base_ton, base_ton, datetime.now(), exp_gain, user_id))
        
        # Применяем износ
        wear_to_apply = wear_amount if 'wear_amount' in locals() else config.WEAR_PER_USE
        self.cursor.execute('''
            UPDATE user_cards 
            SET wear = wear - ? 
            WHERE user_id = ? AND wear > ? AND is_starter = 0
        ''', (wear_to_apply, user_id, wear_to_apply))
        
        # Проверяем сломанные карты
        self.cursor.execute('''
            SELECT COUNT(*) FROM user_cards 
            WHERE user_id = ? AND wear <= ? AND is_starter = 0
        ''', (user_id, config.MIN_WEAR_FOR_MINING))
        broken = self.cursor.fetchone()[0]
        
        if broken > 0:
            self.cursor.execute('''
                UPDATE users SET hash_rate = (
                    SELECT COALESCE(SUM(hash_rate), 0) FROM user_cards 
                    WHERE user_id = ? AND (wear > ? OR is_starter = 1)
                ) WHERE user_id = ?
            ''', (user_id, config.MIN_WEAR_FOR_MINING, user_id))
        
        self.conn.commit()
        
        # Формируем ответ с HTML-цитатой
        result = f"<b>⛏ Успешный майнинг!</b>\n\n"
        result += f"<blockquote>"
        result += f"Твой HM/s ›› {total_hash:.0f}\n"
        result += f"Тон ›› {base_ton}\n"
        result += f"Опыт ›› {exp_gain}"
        result += f"</blockquote>\n\n"
        
        if event_description:
            # Экранируем event_description для HTML
            event_desc_escaped = escape_html(event_description)
            result += f"✨ <b>Событие:</b>\n{event_desc_escaped}\n"
        
        if box_reward:
            result += f"{box_reward}\n"
        
        result += f"⏳ <b>Следующая попытка</b> через 1.00.00\n"
        
        if broken > 0:
            result += f"\n⚠️ <b>{broken}</b> карт сломалось! Используй /repair для ремонта."
        
        return True, result

    def add_box(self, user_id, box_type='common'):
        """Добавляет коробку пользователю"""
        self.cursor.execute('''
            INSERT INTO boxes (user_id, box_type) VALUES (?, ?)
        ''', (user_id, box_type))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_user_boxes(self, user_id, unopened_only=True):
        """Получает коробки пользователя"""
        if unopened_only:
            self.cursor.execute('''
                SELECT id, box_type, created_at FROM boxes 
                WHERE user_id = ? AND opened = 0
                ORDER BY created_at DESC
            ''', (user_id,))
        else:
            self.cursor.execute('''
                SELECT id, box_type, created_at, opened_at FROM boxes 
                WHERE user_id = ?
                ORDER BY created_at DESC
            ''', (user_id,))
        return self.cursor.fetchall()

    def open_box(self, box_id):
        """Открывает коробку и возвращает лут"""
        self.cursor.execute('SELECT user_id, box_type FROM boxes WHERE id = ? AND opened = 0', (box_id,))
        box = self.cursor.fetchone()
        
        if not box:
            return None, "Коробка не найдена или уже открыта"
        
        user_id, box_type = box
        
        # Генерируем лут
        rewards = []
        reward_text = ""
        
        # Базовый лут (всегда)
        ton_reward = random.randint(50, 200)
        exp_reward = random.randint(20, 100)
        
        self.cursor.execute('UPDATE users SET gems = gems + ?, exp = exp + ? WHERE user_id = ?', 
                          (ton_reward, exp_reward, user_id))
        
        rewards.append(f"💰 {ton_reward} тон")
        rewards.append(f"✨ {exp_reward} опыта")
        
        # Шанс на компоненты (30%)
        if random.random() < 0.3:
            components = ["🧩 Чип", "⚙️ Вентилятор", "🔌 Кабель", "🛡️ Радиатор", "💾 Микросхема"]
            component = random.choice(components)
            amount = random.randint(1, 3)
            self.add_component(user_id, component, amount)
            rewards.append(f"📦 {component} x{amount}")
        
        # Маленький шанс на привилегию (2%)
        if random.random() < 0.02:
            priv = random.choice(["premium", "vip"])
            days = 7
            self.apply_privilege(user_id, priv, days)
            priv_name = config.PRIVILEGES[priv]['name']
            priv_icon = config.PRIVILEGES[priv]['icon']
            rewards.append(f"👑 {priv_icon} {priv_name} на {days} дней!")
        
        # Отмечаем коробку как открытую
        self.cursor.execute('''
            UPDATE boxes SET opened = 1, opened_at = ? WHERE id = ?
        ''', (datetime.now(), box_id))
        
        self.cursor.execute('UPDATE users SET boxes_count = boxes_count - 1 WHERE user_id = ?', (user_id,))
        self.cursor.execute('UPDATE stats SET total_boxes_opened = total_boxes_opened + 1')
        
        self.conn.commit()
        
        reward_text = "🎁 <b>В коробке:</b>\n"
        for reward in rewards:
            reward_text += f"• {reward}\n"
        
        return True, reward_text

    def add_component(self, user_id, component_name, amount):
        """Добавляет компонент пользователю"""
        self.cursor.execute('''
            INSERT INTO components (user_id, component_name, amount) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, component_name) DO UPDATE SET amount = amount + ?
        ''', (user_id, component_name, amount, amount))
        self.conn.commit()

    def get_user_components(self, user_id):
        """Получает компоненты пользователя"""
        self.cursor.execute('''
            SELECT component_name, amount FROM components WHERE user_id = ?
        ''', (user_id,))
        return self.cursor.fetchall()

    def set_card_photo(self, card_id, photo_id):
        """Устанавливает фотографию для карты"""
        self.cursor.execute('DELETE FROM card_photos WHERE card_id = ?', (card_id,))
        self.cursor.execute('INSERT INTO card_photos (card_id, photo_id) VALUES (?, ?)', (card_id, photo_id))
        self.conn.commit()

    def get_card_photo(self, card_id):
        """Получает фотографию карты"""
        self.cursor.execute('SELECT photo_id FROM card_photos WHERE card_id = ?', (card_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def repair_cards(self, user_id):
        user = self.get_user(user_id)
        level = user[11]
        
        # Получаем бонусы за уровень
        bonuses = self.get_level_bonuses(level)
        
        # Получаем привилегию пользователя
        privilege, _ = self.get_user_privilege(user_id)
        priv_bonuses = self.get_privilege_bonuses(privilege)
        
        # Общая скидка
        total_discount = bonuses["repair_discount"] + priv_bonuses["repair_discount"]
        
        # Базовая стоимость ремонта
        base_cost = config.REPAIR_COST
        
        # Применяем скидку
        if total_discount > 0:
            repair_cost = int(base_cost * (100 - total_discount) / 100)
        else:
            repair_cost = base_cost
        
        # Ремонтируем карты
        self.cursor.execute('UPDATE user_cards SET wear = 100 WHERE user_id = ? AND is_starter = 0', (user_id,))
        
        # Обновляем хешрейт
        self.cursor.execute('''
            UPDATE users SET hash_rate = (
                SELECT COALESCE(SUM(hash_rate), 0) FROM user_cards 
                WHERE user_id = ?
            ) WHERE user_id = ?
        ''', (user_id, user_id))
        
        self.conn.commit()
        return repair_cost, bonuses["repair_discount"], priv_bonuses["repair_discount"]

    def get_repair_needed(self, user_id):
        self.cursor.execute('''
            SELECT COUNT(*) FROM user_cards 
            WHERE user_id = ? AND wear < 100 AND is_starter = 0
        ''', (user_id,))
        return self.cursor.fetchone()[0] > 0

    def get_shop_items(self):
        self.cursor.execute('SELECT * FROM shop ORDER BY price')
        return self.cursor.fetchall()
    
    def get_all_shop_items(self):
        """Получает все товары в магазине (включая те, которых нет в наличии)"""
        self.cursor.execute('SELECT * FROM shop ORDER BY price')
        return self.cursor.fetchall()
    
    def update_stock(self, card_id, new_stock):
        """Обновляет количество товара на складе"""
        self.cursor.execute('UPDATE shop SET stock = ? WHERE id = ?', (new_stock, card_id))
        self.conn.commit()
        return True
    
    def get_card_by_id(self, card_id):
        """Получает карту по ID"""
        self.cursor.execute('SELECT * FROM shop WHERE id = ?', (card_id,))
        return self.cursor.fetchone()

    def get_stats(self):
        self.cursor.execute('SELECT * FROM stats')
        stats = self.cursor.fetchone()
        
        day_ago = datetime.now() - timedelta(days=1)
        hour_ago = datetime.now() - timedelta(hours=1)
        
        # Общий онлайн (кто хоть раз заходил)
        self.cursor.execute('SELECT COUNT(*) FROM users')
        total_users = self.cursor.fetchone()[0]
        
        # Онлайн за 24 часа
        self.cursor.execute('SELECT COUNT(*) FROM users WHERE last_mining > ?', (day_ago,))
        online_24h = self.cursor.fetchone()[0]
        
        # Текущий онлайн (за последний час)
        self.cursor.execute('SELECT COUNT(*) FROM users WHERE last_mining > ?', (hour_ago,))
        current_online = self.cursor.fetchone()[0]
        
        # Общее количество тон у всех игроков
        self.cursor.execute('SELECT SUM(gems) FROM users')
        total_ton = self.cursor.fetchone()[0] or 0
        
        # Среднее количество тон на игрока
        avg_ton = total_ton / total_users if total_users > 0 else 0
        
        # Общий хешрейт
        self.cursor.execute('SELECT SUM(hash_rate) FROM users')
        total_hash = self.cursor.fetchone()[0] or 0
        
        # Средний хешрейт на игрока
        avg_hash = total_hash / total_users if total_users > 0 else 0
        
        # Товара на складе
        self.cursor.execute('SELECT SUM(stock) FROM shop')
        total_stock = self.cursor.fetchone()[0] or 0
        
        return {
            'total_users': total_users,
            'online_24h': online_24h,
            'current_online': current_online,
            'total_ton': total_ton,
            'avg_ton': avg_ton,
            'total_hash': total_hash,
            'avg_hash': avg_hash,
            'total_stock': total_stock,
            'total_cards_sold': stats[1] if stats else 0,
            'total_gems_earned': stats[2] if stats else 0,
            'total_mining_actions': stats[3] if stats else 0,
            'total_boxes_opened': stats[4] if stats and len(stats) > 4 else 0
        }

    def get_top(self, category):
        """Получает топ пользователей"""
        if category == "hash":
            self.cursor.execute('''
                SELECT user_id, username, first_name, 
                       (hash_rate - ?) as real_hash 
                FROM users 
                WHERE hash_rate > ? 
                ORDER BY real_hash DESC LIMIT 10
            ''', (config.STARTER_CARD_HASHRATE, config.STARTER_CARD_HASHRATE))
        elif category == "gems":
            self.cursor.execute('''
                SELECT user_id, username, first_name, gems FROM users 
                ORDER BY gems DESC LIMIT 10
            ''')
        elif category == "referrals":
            self.cursor.execute('''
                SELECT user_id, username, first_name, referrals FROM users 
                WHERE referrals > 0
                ORDER BY referrals DESC LIMIT 10
            ''')
        else:  # level
            self.cursor.execute('''
                SELECT user_id, username, first_name, level, exp FROM users 
                ORDER BY level DESC, exp DESC LIMIT 10
            ''')
        return self.cursor.fetchall()

    def get_user_mining_count(self, user_id):
        """Получает количество майнингов пользователя"""
        self.cursor.execute('SELECT COUNT(*) FROM events_log WHERE user_id = ? AND event_name LIKE "%майнинг%"', (user_id,))
        return self.cursor.fetchone()[0]

    def get_user_referrals(self, user_id):
        """Получает список рефералов пользователя"""
        self.cursor.execute('''
            SELECT user_id, first_name, username, level, gems, created_at 
            FROM users 
            WHERE referrer_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
        return self.cursor.fetchall()

    def get_user_logs(self, user_id, limit=50):
        """Получает логи действий пользователя"""
        logs = []
        
        # Логи событий
        self.cursor.execute('''
            SELECT 'event' as type, event_time as time, event_name as action, reward as details 
            FROM events_log 
            WHERE user_id = ? 
            ORDER BY event_time DESC LIMIT ?
        ''', (user_id, limit))
        logs.extend(self.cursor.fetchall())
        
        # Логи майнинга (из total_mined можно отслеживать)
        self.cursor.execute('''
            SELECT 'level_up' as type, created_at as time, 'Повышение уровня' as action, 
                   'Уровень ' || level as details 
            FROM users 
            WHERE user_id = ? AND level > 1
            ORDER BY created_at DESC LIMIT ?
        ''', (user_id, limit))
        logs.extend(self.cursor.fetchall())
        
        # Сортируем по времени
        logs.sort(key=lambda x: x[1] if x[1] else datetime.min, reverse=True)
        return logs[:limit]

    # Админ методы
    def add_gems(self, user_id, amount, admin_id):
        self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (amount, user_id))
        self.log_admin_action(admin_id, 'add_gems', user_id, f'+{amount} тон')
        self.conn.commit()

    def remove_gems(self, user_id, amount, admin_id):
        self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (amount, user_id))
        self.log_admin_action(admin_id, 'remove_gems', user_id, f'-{amount} тон')
        self.conn.commit()

    def ban_user(self, user_id, reason=None, days=None, admin_id=None):
        """Банит пользователя. Если days указан - временный бан"""
        if days:
            ban_until = datetime.now() + timedelta(days=days)
            self.cursor.execute('''
                UPDATE users SET 
                    banned = 1,
                    ban_until = ? 
                WHERE user_id = ?
            ''', (ban_until, user_id))
            result = f"на {days} дн."
            details = f"Бан на {days} дн. Причина: {reason if reason else 'Не указана'}"
        else:
            self.cursor.execute('''
                UPDATE users SET 
                    banned = 1,
                    ban_until = NULL 
                WHERE user_id = ?
            ''', (user_id,))
            result = "навсегда"
            details = f"Бан навсегда. Причина: {reason if reason else 'Не указана'}"
        
        if admin_id:
            self.log_admin_action(admin_id, 'ban', user_id, details)
        
        self.conn.commit()
        return result

    def unban_user(self, user_id, admin_id=None):
        """Разбанивает пользователя"""
        self.cursor.execute('''
            UPDATE users SET 
                banned = 0,
                ban_until = NULL 
            WHERE user_id = ?
        ''', (user_id,))
        
        if admin_id:
            self.log_admin_action(admin_id, 'unban', user_id, 'Разбан')
        
        self.conn.commit()

    def log_admin_action(self, admin_id, action, target_id, details):
        """Логирует действия администратора"""
        self.cursor.execute('''
            INSERT INTO admin_logs (admin_id, action, target_id, details) 
            VALUES (?, ?, ?, ?)
        ''', (admin_id, action, target_id, details))
        self.conn.commit()

    def check_ban_status(self, user_id):
        """Проверяет статус бана и автоматически разбанивает если время истекло"""
        self.cursor.execute('SELECT banned, ban_until FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if not result:
            return False
        
        banned, ban_until = result
        
        if not banned:
            return False
        
        if ban_until:
            # Проверяем, не истек ли временный бан
            ban_time = datetime.fromisoformat(ban_until)
            if datetime.now() > ban_time:
                # Время вышло - автоматически разбаниваем
                self.unban_user(user_id)
                return False
        
        return True

    def force_reload_shop(self):
        """ПРИНУДИТЕЛЬНО перезагружает магазин из конфига"""
        try:
            self.cursor.execute('DELETE FROM shop')
            print("🗑 Старые карты удалены")
            
            for photo, card_data in SHOP_CARDS.items():
                self.cursor.execute('''
                    INSERT INTO shop (card_name, hash_rate, price, stock, photo) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    card_data['name'],
                    card_data['hash_rate'],
                    card_data['price'],
                    card_data['stock'],
                    photo
                ))
                print(f"✅ Добавлена: {card_data['name']}")
            
            self.conn.commit()
            
            self.cursor.execute('SELECT COUNT(*) FROM shop')
            count = self.cursor.fetchone()[0]
            print(f"📊 В магазине теперь {count} карт")
            
            return count
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return 0

    # ==================== МЕТОДЫ ДЛЯ АВТОМАТИЧЕСКОГО ПОПОЛНЕНИЯ ====================
    def get_price_category(self, price):
        """Определяет категорию карты по цене"""
        if price < 1000:
            return "low"
        elif price < 3000:
            return "medium"
        elif price < 6000:
            return "high"
        else:
            return "very_high"

    def auto_restock(self):
        """Автоматическое пополнение склада"""
        try:
            # Получаем все карты в магазине
            self.cursor.execute('SELECT id, card_name, price, stock FROM shop')
            cards = self.cursor.fetchall()
            
            if not cards:
                print("📦 В магазине нет карт для пополнения")
                return 0, []
            
            total_restocked = 0
            restock_log = []
            
            for card in cards:
                card_id = card[0]
                card_name = card[1]
                price = card[2]
                current_stock = card[3]
                
                # Определяем категорию цены и соответствующий шанс
                category = self.get_price_category(price)
                chance = config.RESTOCK_CHANCE_BY_PRICE.get(category, 50)
                
                # Рандомно решаем, будет ли пополнение
                if random.randint(1, 100) <= chance:
                    # Генерируем случайное количество для пополнения
                    restock_amount = random.randint(
                        config.AUTO_RESTOCK_MIN_ITEMS, 
                        config.AUTO_RESTOCK_MAX_ITEMS
                    )
                    
                    # Обновляем склад
                    new_stock = current_stock + restock_amount
                    self.cursor.execute('UPDATE shop SET stock = ? WHERE id = ?', (new_stock, card_id))
                    
                    total_restocked += restock_amount
                    restock_log.append(f"  • {card_name}: +{restock_amount} шт. (шанс {chance}%)")
            
            self.conn.commit()
            
            # Логируем результат
            print(f"📦 Автоматическое пополнение склада выполнено!")
            print(f"📊 Всего добавлено: {total_restocked} карт")
            for log in restock_log:
                print(log)
            
            return total_restocked, restock_log
            
        except Exception as e:
            print(f"❌ Ошибка при автоматическом пополнении: {e}")
            return 0, []

    def check_and_restock(self):
        """Проверяет, нужно ли выполнить автоматическое пополнение"""
        if not config.AUTO_RESTOCK_ENABLED:
            return False
        
        try:
            # Получаем время последнего пополнения
            self.cursor.execute('SELECT last_restock FROM auto_restock_log ORDER BY id DESC LIMIT 1')
            result = self.cursor.fetchone()
            
            now = datetime.now()
            
            # Если пополнений еще не было
            if not result:
                # Записываем текущее время и выполняем пополнение
                self.cursor.execute('INSERT INTO auto_restock_log (last_restock) VALUES (?)', (now,))
                self.conn.commit()
                return True
            
            last_restock = datetime.fromisoformat(result[0])
            
            # Проверяем, прошло ли больше суток
            if now.date() > last_restock.date():
                # Проверяем, наступило ли нужное время
                target_time = datetime.strptime(config.AUTO_RESTOCK_TIME, "%H:%M").time()
                target_datetime = datetime.combine(now.date(), target_time)
                
                # Если сейчас >= времени пополнения И последнее пополнение было до сегодня
                if now >= target_datetime and last_restock.date() < now.date():
                    # Обновляем время последнего пополнения
                    self.cursor.execute('INSERT INTO auto_restock_log (last_restock) VALUES (?)', (now,))
                    self.conn.commit()
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Ошибка при проверке времени пополнения: {e}")
            return False


# Создаем экземпляр БД
db = Database()

# ==================== ФУНКЦИИ ДЛЯ ИКОНОК ====================
def get_level_icon(level):
    """Возвращает иконку для уровня"""
    if level < 10:
        return "🌱"
    elif level < 20:
        return "🌿"
    elif level < 30:
        return "🌳"
    elif level < 40:
        return "🏔"
    elif level < 50:
        return "👑"
    else:
        return "⭐"

def get_card_count_icon(count):
    """Возвращает иконку для количества карт"""
    thresholds = sorted(config.CARD_COUNT_ICONS.keys(), reverse=True)
    for threshold in thresholds:
        if count >= threshold:
            return config.CARD_COUNT_ICONS[threshold]
    return "🖥"

def get_referral_icon(count):
    """Возвращает иконку для количества рефералов"""
    thresholds = sorted(config.REFERRAL_ICONS.keys(), reverse=True)
    for threshold in thresholds:
        if count >= threshold:
            return config.REFERRAL_ICONS[threshold]
    return "👤"

def get_seasonal_icon():
    """Возвращает сезонную иконку"""
    current_month = datetime.now().month
    return config.SEASONAL_ICONS.get(current_month, "✨")

def get_top_icon(position):
    """Возвращает иконку для позиции в топе"""
    if 1 <= position <= len(config.TOP_ICONS):
        return config.TOP_ICONS[position - 1]
    return "📊"

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    """Главная клавиатура с обновленным дизайном (без кнопки назад)"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # 1 строка - Ежедневный подарок
        [InlineKeyboardButton(text="🎁 Ежедневный подарок", callback_data="daily_bonus")],
        
        # 2 строка - Профиль, ДНС, Помощь
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🛒 ДНС", callback_data="shop_menu"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help_menu")
        ],
        
        # 3 строка - Топ, Уровень, Донат
        [
            InlineKeyboardButton(text="📯 Топ", callback_data="top_menu"),
            InlineKeyboardButton(text="🌟 Уровень", callback_data="level"),
            InlineKeyboardButton(text="🪙 Донат", callback_data="donate_menu")
        ],
        
        # 4 строка - Добавить в группу
        [InlineKeyboardButton(text="➕ Добавить бота в группу", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true")]
    ])
    return keyboard

def get_shop_menu_keyboard():
    """Клавиатура главного меню магазина"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖥 Видеокарты", callback_data="shop_cards"),
            InlineKeyboardButton(text="💨 Куллеры", callback_data="shop_coolers"),
        ],
        [
            InlineKeyboardButton(text="📟 Майнеры", callback_data="shop_miners"),
            InlineKeyboardButton(text="📦 Склад", callback_data="shop_stock"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

def get_shop_keyboard(page=0):
    """Клавиатура магазина с пагинацией"""
    items = db.get_shop_items()
    items_per_page = 9
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, item in enumerate(page_items, 1):
        # Добавляем эмодзи в зависимости от наличия
        if item[4] > 0:
            emoji = "✅"
        else:
            emoji = "⛔"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {item[1]}",
            callback_data=f"card_{item[0]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Добавляем кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="shop_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_card_detail_keyboard(card_id, in_stock=True):
    """Клавиатура для детальной информации о карте в магазине"""
    buttons = []
    
    if in_stock:
        buttons.append([InlineKeyboardButton(text="💳 Оплатить", callback_data=f"buy_{card_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔚 Назад", callback_data="shop_cards")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_profile_keyboard(target_user_id=None):
    """Клавиатура для профиля с кнопкой просмотра карт"""
    if target_user_id:
        # Если просматриваем чужой профиль
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖥 Видеокарты игрока", callback_data=f"view_cards_{target_user_id}")],
            [InlineKeyboardButton(text="📦 Коробки", callback_data=f"view_boxes_{target_user_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    else:
        # Свой профиль
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖥 Мои видеокарты", callback_data="my_cards")],
            [InlineKeyboardButton(text="📦 Мои коробки", callback_data="my_boxes")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    return keyboard

def get_boxes_keyboard(user_id, page=0, is_own=True):
    """Клавиатура для просмотра коробок"""
    boxes = db.get_user_boxes(user_id)
    items_per_page = 6
    total_pages = (len(boxes) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_boxes = boxes[start:end]
    
    buttons = []
    row = []
    
    for i, box in enumerate(page_boxes, 1):
        box_id, box_type, created_at = box[:3]
        box_date = datetime.fromisoformat(created_at).strftime('%d.%m')
        
        row.append(InlineKeyboardButton(
            text=f"📦 {box_date}",
            callback_data=f"open_box_{box_id}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Добавляем кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"boxes_page_{user_id}_{page-1}_{is_own}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"boxes_page_{user_id}_{page+1}_{is_own}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    
    if is_own:
        buttons.append([InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")])
    else:
        buttons.append([InlineKeyboardButton(text="◀️ Назад к профилю", callback_data=f"view_profile_{user_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_help_keyboard():
    """Клавиатура для раздела помощи (без кнопки назад)"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Майнинг", callback_data="help_mine"),
         InlineKeyboardButton(text="🛒 ДНС", callback_data="help_shop")],
        [InlineKeyboardButton(text="💼 Кошелек", callback_data="help_wallet"),
         InlineKeyboardButton(text="🖥 Видеокарты", callback_data="help_cards")],
        [InlineKeyboardButton(text="🔧 Ремонт", callback_data="help_repair"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="help_referrals")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="help_top"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="help_stats")],
        [InlineKeyboardButton(text="📦 Коробки", callback_data="help_boxes")]
    ])
    return keyboard

def get_mycards_keyboard(user_id, page=0):
    """Клавиатура для просмотра своих карт с пагинацией"""
    cards = db.get_user_cards(user_id)
    items_per_page = 6
    total_pages = (len(cards) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_cards = cards[start:end]
    
    buttons = []
    row = []
    
    for i, card in enumerate(page_cards, 1):
        # Определяем статус карты
        if card[5] == 1:
            status = "🔰"
        elif card[4] <= config.MIN_WEAR_FOR_MINING:
            status = "⚠️"
        else:
            status = "✅"
        
        row.append(InlineKeyboardButton(
            text=f"{status} {card[2]}",
            callback_data=f"mycard_detail_{card[0]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Добавляем кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"mycards_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"mycards_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_view_cards_keyboard(user_id, page=0):
    """Клавиатура для просмотра карт другого игрока"""
    cards = db.get_user_cards(user_id)
    items_per_page = 6
    total_pages = (len(cards) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_cards = cards[start:end]
    
    buttons = []
    row = []
    
    for i, card in enumerate(page_cards, 1):
        # Определяем статус карты
        if card[5] == 1:
            status = "🔰"
        elif card[4] <= config.MIN_WEAR_FOR_MINING:
            status = "⚠️"
        else:
            status = "✅"
        
        row.append(InlineKeyboardButton(
            text=f"{status} {card[2]}",
            callback_data=f"view_card_detail_{card[0]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Добавляем кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"view_cards_page_{user_id}_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"view_cards_page_{user_id}_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Назад к профилю", callback_data=f"view_profile_{user_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_mycard_detail_keyboard(card_id):
    """Клавиатура для детальной информации о своей карте"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="my_cards")]
    ])
    return keyboard

def get_view_card_detail_keyboard(card_id, user_id):
    """Клавиатура для просмотра карты другого игрока"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"view_cards_{user_id}")]
    ])
    return keyboard

def get_wallet_keyboard():
    """Клавиатура кошелька"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

def get_top_keyboard():
    """Клавиатура для топа с обновленными кнопками"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # 1 строка - Тоны, Уровень, Хешрейт
        [
            InlineKeyboardButton(text="💰 Тоны", callback_data="top_gems"),
            InlineKeyboardButton(text="📶 Уровень", callback_data="top_level"),
            InlineKeyboardButton(text="⚡ HM/s", callback_data="top_hash")
        ],
        # 2 строка - Рефералы
        [
            InlineKeyboardButton(text="👥 Рефералы", callback_data="top_referrals")
        ]
    ])
    return keyboard

def get_continue_shopping_keyboard():
    """Клавиатура для продолжения покупок"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Продолжить покупки", callback_data="shop_cards")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_menu")]
    ])
    return keyboard

def get_back_to_help_keyboard():
    """Клавиатура для возврата в помощь"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в помощь", callback_data="back_to_help")]
    ])
    return keyboard

def get_donate_keyboard():
    """Клавиатура для меню доната"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Премиум", callback_data="buy_premium"),
            InlineKeyboardButton(text="👑 VIP", callback_data="buy_vip"),
            InlineKeyboardButton(text="🌟 Легенда", callback_data="buy_legend")
        ],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")]
    ])
    return keyboard

def get_level_keyboard():
    """Клавиатура для меню уровня (только кнопка повышения)"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Повышение", callback_data="level_up")]
    ])
    return keyboard

def get_skl_keyboard():
    """Клавиатура для управления складом"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Состояние склада", callback_data="admin_show_stock"),
            InlineKeyboardButton(text="➕ Пополнить", callback_data="admin_add_stock")
        ],
        [
            InlineKeyboardButton(text="➖ Убрать со склада", callback_data="admin_remove_stock"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stock_stats")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

# ==================== СОСТОЯНИЯ FSM ====================
class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()
    waiting_for_card_id = State()
    waiting_for_new_stock = State()
    waiting_for_remove_stock = State()
    waiting_for_ban_days = State()
    waiting_for_ban_reason = State()
    waiting_for_target_id = State()
    waiting_for_photo = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def is_admin(user_id):
    return user_id in config.ADMIN_IDS

async def check_ban(user_id):
    """Проверяет, забанен ли пользователь"""
    return db.check_ban_status(user_id)

async def send_ban_message(message_or_callback):
    """Отправляет сообщение о бане"""
    user_id = message_or_callback.from_user.id
    db.cursor.execute('SELECT ban_until FROM users WHERE user_id = ?', (user_id,))
    result = db.cursor.fetchone()
    ban_until = result[0] if result else None
    
    if ban_until:
        ban_time = datetime.fromisoformat(ban_until)
        time_left = ban_time - datetime.now()
        days = time_left.days
        hours = time_left.seconds // 3600
        
        ban_text = (
            f"⛔ Ваш аккаунт временно заблокирован!\n\n"
            f"⏰ Осталось: {days} дн. {hours} ч.\n"
            f"📅 Разбан: {ban_time.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Если вы не согласны с решением администрации, "
            f"обратитесь @banankm"
        )
    else:
        ban_text = (
            "⛔ Ваш аккаунт заблокирован навсегда!\n\n"
            "Если вы не согласны с решением администрации, "
            "обратитесь @banankm"
        )
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(ban_text)
    else:
        await message_or_callback.message.edit_text(ban_text)

async def send_main_menu(chat_id, text="Главное меню:"):
    """Отправляет главное меню"""
    await bot.send_message(chat_id, text, reply_markup=get_main_keyboard())

# ==================== ФОНОВАЯ ЗАДАЧА ДЛЯ АВТОМАТИЧЕСКОГО ПОПОЛНЕНИЯ ====================
async def auto_restock_scheduler():
    """Фоновая задача для автоматического пополнения склада"""
    while True:
        try:
            # Проверяем, нужно ли выполнить пополнение
            if db.check_and_restock():
                print("🔄 Запуск автоматического пополнения склада...")
                total, logs = db.auto_restock()
                
                # Отправляем уведомление админам
                if total > 0:
                    for admin_id in config.ADMIN_IDS:
                        try:
                            text = f"📦 Автоматическое пополнение склада\n\n"
                            text += f"✅ Добавлено: {total} карт\n\n"
                            text += "Детали:\n"
                            text += "\n".join(logs[:10])
                            if len(logs) > 10:
                                text += f"\n... и ещё {len(logs) - 10} карт"
                            
                            await bot.send_message(admin_id, text)
                        except:
                            pass
            
            # Проверяем каждую минуту
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"❌ Ошибка в авто-пополнении: {e}")
            await asyncio.sleep(60)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    args = message.text.split()
    referrer_id = None
    
    # Проверяем, есть ли реферальный параметр
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        # Проверяем, что реферер существует и это не сам пользователь
        if referrer_id == message.from_user.id:
            referrer_id = None
    
    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referrer_id
    )
    
    # Если пользователь пришел по рефералке, показываем специальное сообщение
    if referrer_id:
        referrer = db.get_user(referrer_id)
        if referrer:
            referrer_name = referrer[3] or referrer[2] or f"Player_{referrer[1]}"
            welcome_text = (
                f"👋 Добро пожаловать в <b>Mining Game</b>!\n\n"
                f"Ты пришел по приглашению от <b>{escape_html(referrer_name)}</b>! 🎉\n"
                f"Ты получил бонус: <b>{config.REFERRAL_BONUS_FOR_NEW} тон</b> и <b>{config.REFERRAL_EXP_FOR_NEW} опыта</b> ✨\n\n"
                f"<blockquote>"
                f"Здесь ты можешь зарабатывать тон, майнить криптовалюту и покупать видеокарты в магазине"
                f"</blockquote>\n\n"
                f"👇 <b>Выбери действие:</b>"
            )
        else:
            welcome_text = (
                f"👋 Добро пожаловать в <b>Mining Game</b>!\n\n"
                f"<blockquote>"
                f"Здесь ты можешь зарабатывать тон, майнить криптовалюту и покупать видеокарты в магазине"
                f"</blockquote>\n\n"
                f"👇 <b>Выбери действие:</b>"
            )
    else:
        welcome_text = (
            f"👋 Добро пожаловать в <b>Mining Game</b>!\n\n"
            f"<blockquote>"
            f"Здесь ты можешь зарабатывать тон, майнить криптовалюту и покупать видеокарты в магазине"
            f"</blockquote>\n\n"
            f"👇 <b>Выбери действие:</b>"
        )
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    help_text = (
        "📚 Добро пожаловать в раздел помощи!\n\n"
        "Здесь вы можете узнать подробную информацию о каждом разделе бота.\n"
        "Выберите интересующий вас раздел ниже:"
    )
    
    await message.answer(help_text, reply_markup=get_help_keyboard())

@dp.message(Command("mine"))
async def cmd_mine(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    success, result = db.mine(message.from_user.id)
    
    # Отправляем ответ с HTML-форматированием
    await message.answer(result, parse_mode="HTML")

@dp.message(Command("nick"))
async def cmd_nick(message: Message):
    """Смена ника"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        user = db.get_user(message.from_user.id)
        current_nick = user[3]
        await message.answer(
            f"❌ Использование: /nick новый_ник\n\n"
            f"Твой текущий ник: <b>{escape_html(current_nick)}</b>\n\n"
            f"Пример: /nick Крипто_Майнер",
            parse_mode="HTML"
        )
        return
    
    new_nick = args[1].strip()
    
    success, result = db.change_nickname(message.from_user.id, new_nick)
    await message.answer(result, parse_mode="HTML")

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    # Проверяем, есть ли аргумент (MID)
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        # Просмотр профиля другого игрока по MID
        target_mid = int(args[1])
        target_user = db.get_user_by_custom_id(target_mid)
        if not target_user:
            await message.answer("❌ Игрок с таким MID не найден!")
            return
        await show_user_profile(message, target_user[0], is_own=False)
    else:
        # Свой профиль
        await show_user_profile(message, message.from_user.id, is_own=True)

async def show_user_profile(message_or_callback, user_id, is_own=True):
    """Показывает профиль пользователя"""
    try:
        user = db.get_user(user_id)
        if not user:
            await message_or_callback.answer("❌ Ошибка: профиль не найден")
            return
        
        # Получаем данные пользователя
        username = user[2]
        first_name = user[3]
        
        # Формируем ник
        if username:
            name_display = f"@{username}"
        else:
            name_display = escape_html(first_name)
        
        # Проверяем, админ ли
        admin_tag = " 👑 АДМИН" if is_admin(user_id) else ""
        
        # Получаем привилегию
        privilege, until = db.get_user_privilege(user_id)
        privilege_data = config.PRIVILEGES[privilege]
        privilege_name = f"{privilege_data['icon']} {privilege_data['name']}"
        
        # Вычисляем время в игре
        created_at = datetime.fromisoformat(user[13])
        hours_in_game = int((datetime.now() - created_at).total_seconds() / 3600)
        
        # Данные
        level = user[11] if user[11] is not None else 1
        exp = user[12] if user[12] is not None else 0
        ton = int(user[4]) if user[4] is not None else 0
        hash_rate = float(user[5]) if user[5] is not None else 0.0
        total_cards = user[6] if user[6] is not None else 0
        boxes_count = user[19] if len(user) > 19 and user[19] is not None else 0
        
        # Получаем карты пользователя
        cards = db.get_user_cards(user_id)
        working_cards = len([c for c in cards if c[4] > config.MIN_WEAR_FOR_MINING or c[5] == 1])
        broken_cards = len([c for c in cards if c[5] == 0 and c[4] <= config.MIN_WEAR_FOR_MINING])
        referrals = user[7] if user[7] is not None else 0
        
        # Получаем информацию о стрике
        db.cursor.execute('SELECT streak FROM daily_bonus WHERE user_id = ?', (user_id,))
        streak_result = db.cursor.fetchone()
        streak = streak_result[0] if streak_result else 0
        
        # MID
        mid = user[1]
        
        # Заголовок профиля
        if is_own:
            profile_title = f"<b>Твой профиль</b>"
        else:
            profile_title = f"<b>Профиль игрока {escape_html(first_name)}</b>"
        
        # Формируем текст профиля с HTML-цитатой
        profile_text = (
            f"{profile_title}\n\n"
            f"<blockquote>"
            f"👤 {name_display}{admin_tag}\n"
            f"├ 🆔 MID ›› {mid}\n"
            f"├ 🏷 Привилегия ›› {privilege_name}\n"
            f"├ 🌱 Уровень ›› {level}\n"
            f"│  └ 📊 Опыт ›› {exp}\n"
            f"└ ⏰ В игре ›› {hours_in_game} ч\n"
            f"\n"
            f"Баланс:\n"
            f"├💰 Тон ›› {ton}\n"
            f"└ ⚡ Хешрейт ›› {hash_rate:.1f} MH/s\n"
            f"\n"
            f"  🖥 Всего карт ›› {total_cards} шт.\n"
            f"    ├ ✅ Работает ›› {working_cards} шт.\n"
            f"    └ ⚠️ Сломано ›› {broken_cards} шт.\n"
            f"  📦 Коробок ›› {boxes_count} шт.\n"
            f" \n"
            f"├👤 Рефералов ›› {referrals}\n"
            f"└ 📅 Стрик ›› {streak} дней\n"
            f"</blockquote>\n\n"
        )
        
        if is_own:
            profile_text += f"💡 Для смены ника используй /nick"
        
        # Отправляем сообщение
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(
                profile_text, 
                reply_markup=get_profile_keyboard(user_id if not is_own else None),
                parse_mode="HTML"
            )
        else:
            await message_or_callback.message.edit_text(
                profile_text, 
                reply_markup=get_profile_keyboard(user_id if not is_own else None),
                parse_mode="HTML"
            )
        
    except Exception as e:
        error_text = f"❌ Ошибка: {str(e)}"
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(error_text)
        else:
            await message_or_callback.message.edit_text(error_text)
        print(f"❌ Ошибка в show_user_profile: {e}")
        import traceback
        traceback.print_exc()

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    await show_shop_menu(message)

async def show_shop_menu(message_or_callback):
    """Показывает главное меню магазина"""
    shop_text = (
        f"🛒 <b>Здравствуйте! ДНС — ваш эксперт в графических решениях.</b>\n"
        f"<i>Подберем лучшую GPU или отличное охлаждение для твоей майнинг фермы!</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Каталог:</b>"
    )
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(
            shop_text,
            reply_markup=get_shop_menu_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message_or_callback.message.edit_text(
            shop_text,
            reply_markup=get_shop_menu_keyboard(),
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "shop_menu")
async def shop_menu_callback(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await show_shop_menu(callback)

@dp.callback_query(F.data == "shop_cards")
async def shop_cards_callback(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    items = db.get_shop_items()
    
    shop_text = (
        f"🖥️ <b>Видеокарты на любой вкус и цвет:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    await callback.message.edit_text(
        shop_text,
        reply_markup=get_shop_keyboard(0),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("shop_page_"))
async def shop_page_handler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    page = int(callback.data.split("_")[2])
    
    items = db.get_shop_items()
    
    shop_text = (
        f"🖥️ <b>Видеокарты на любой вкус и цвет:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    await callback.message.edit_text(
        shop_text,
        reply_markup=get_shop_keyboard(page),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("card_"))
async def card_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    card_id = int(callback.data.split("_")[1])
    
    db.cursor.execute('SELECT * FROM shop WHERE id = ?', (card_id,))
    card = db.cursor.fetchone()
    
    if not card:
        await callback.message.edit_text("❌ <b>Карта не найдена!</b>", parse_mode="HTML")
        return
    
    photo_name = card[5]
    card_info = SHOP_CARDS.get(photo_name, {})
    
    # Получаем пользователя для проверки баланса
    user = db.get_user(callback.from_user.id)
    user_balance = int(user[4]) if user else 0
    can_afford = user_balance >= card[3]
    in_stock = card[4] > 0
    
    # Получаем фотографию карты
    photo_id = db.get_card_photo(card_id)
    
    # Формируем текст
    detail_text = (
        f"🖥 <b>{card[1]}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>Цена ››</b> {card[3]} тон\n"
        f"📦 <b>В наличии ››</b> {'⛔нет на складе' if not in_stock else f'{card[4]} шт.'}\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷⚡ Хешрейт ›› {card[2]} MH/s\n"
        f" ⤷⚡ Энергопотребление ›› {card_info.get('power', 'N/A')} Вт\n"
        f" ⤷💾 Память ›› {card_info.get('memory', 'N/A')} ГБ\n"
        f" ⤷📅 Год выпуска ›› {card_info.get('release_year', 'N/A')}\n\n"
        f"💰 <b>Твой баланс ››</b> {user_balance} тон"
    )
    
    # Отправляем с фотографией если есть
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=detail_text,
            reply_markup=get_card_detail_keyboard(card_id, in_stock),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            detail_text,
            reply_markup=get_card_detail_keyboard(card_id, in_stock),
            parse_mode="HTML"
        )

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    card_id = int(callback.data.split("_")[1])
    
    success, message, bought_card_id = db.buy_card(callback.from_user.id, card_id)
    
    if success:
        await callback.message.edit_caption(
            caption=f"✅ {message}",
            reply_markup=get_continue_shopping_keyboard(),
            parse_mode="HTML"
        )
    else:
        if "Недостаточно средств" in message:
            await callback.answer("❌ Недостаточно средств!", show_alert=True)
        elif "Нет на складе" in message:
            await callback.answer("⛔ Нет на складе!", show_alert=True)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)

@dp.message(Command("addphoto"))
async def cmd_add_photo(message: Message, state: FSMContext):
    """Команда для добавления фотографии к карте (только для админов)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        # Показываем список карт
        items = db.get_all_shop_items()
        text = "📸 <b>Добавление фотографии к карте</b>\n\n"
        text += "Использование: /addphoto [ID карты]\n\n"
        text += "<b>Доступные карты:</b>\n"
        for item in items[:10]:
            text += f"🆔 {item[0]} - {item[1]}\n"
        
        await message.answer(text, parse_mode="HTML")
        return
    
    try:
        card_id = int(args[1])
        card = db.get_card_by_id(card_id)
        
        if not card:
            await message.answer("❌ Карта не найдена!")
            return
        
        await state.update_data(card_id=card_id, card_name=card[1])
        await state.set_state(AdminStates.waiting_for_photo)
        
        await message.answer(
            f"📸 Отправьте фотографию для карты <b>{card[1]}</b>",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("❌ Неверный ID карты!")

@dp.message(AdminStates.waiting_for_photo, F.photo)
async def process_card_photo(message: Message, state: FSMContext):
    """Обработка фотографии для карты"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    
    data = await state.get_data()
    card_id = data.get('card_id')
    card_name = data.get('card_name')
    
    # Получаем ID самой большой фотографии
    photo = message.photo[-1]
    photo_id = photo.file_id
    
    # Сохраняем в базу
    db.set_card_photo(card_id, photo_id)
    
    await message.answer(
        f"✅ Фотография для карты <b>{card_name}</b> сохранена!",
        parse_mode="HTML"
    )
    
    await state.clear()

@dp.message(Command("wallet"))
async def cmd_wallet(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    
    wallet_text = (
        f"💼 Кошелек\n\n"
        f"Твой баланс: {user[4]:.0f} тон\n\n"
        f"Здесь ты можешь пополнить или вывести тон."
    )
    
    await message.answer(wallet_text, reply_markup=get_wallet_keyboard())

@dp.message(Command("repair"))
async def cmd_repair(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    
    if not db.get_repair_needed(message.from_user.id):
        await message.answer("✅ Все твои видеокарты в идеальном состоянии!")
        return
    
    repair_cost, level_discount, privilege_discount = db.repair_cards(message.from_user.id)
    
    if user[4] < repair_cost:
        await message.answer(f"❌ Недостаточно тон! Нужно {repair_cost} тон")
        return
    
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить ремонт", callback_data="confirm_repair")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    
    text = f"🔧 Ремонт видеокарт\n\n"
    text += f"Базовая стоимость: {config.REPAIR_COST} тон\n"
    
    discounts = []
    if level_discount > 0:
        discounts.append(f"Скидка за уровень: -{level_discount}%")
    if privilege_discount > 0:
        discounts.append(f"Скидка за привилегию: -{privilege_discount}%")
    
    if discounts:
        text += "(" + ", ".join(discounts) + ")\n"
    
    text += f"Итого: {repair_cost} тон\n\n"
    text += f"Твой баланс: {user[4]:.0f} тон\n\n"
    text += f"Подтверждаешь?"
    
    await message.answer(text, reply_markup=confirm_keyboard)

@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    
    # Получаем количество рефералов
    referrals_count = user[7] if user[7] is not None else 0
    
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    
    # Формируем текст с HTML-цитатой (без статистики)
    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"<blockquote>"
        f"Каждому приглашённому другу начисляется бонус в виде {config.REFERRAL_BONUS_FOR_NEW} тон и {config.REFERRAL_EXP_FOR_NEW} опыта\n\n"
        f"За каждого приглашённого друга тебе начисляется бонус в виде {config.REFERRAL_BONUS} тон и {config.REFERRAL_EXP_BONUS} опыта\n\n"
        f"Твои рефералы: {referrals_count}"
        f"</blockquote>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Клавиатура с кнопками
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=🔥 Присоединяйся к майнинг-боту! Получи бонус {config.REFERRAL_BONUS_FOR_NEW} тон и {config.REFERRAL_EXP_FOR_NEW} опыта при регистрации!"),
            InlineKeyboardButton(text="👥 Отслеживать", callback_data="track_referrals")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    stats = db.get_stats()
    
    # Формируем текст с HTML-цитатой
    text = (
        f"⚡️<b>Статистика бота:</b>\n\n"
        f"<blockquote>"
        f"⤷<b>Общий онлайн ››</b> {stats['total_users']}\n"
        f"  ⤷ Онлайн за 24 часа ›› {stats['online_24h']}\n"
        f"  ⤷ Текущий онлайн ›› {stats['current_online']}\n\n"
        f"⤷<b>Тон у игроков ››</b> {stats['total_ton']:.0f}\n"
        f"  ⤷ Тон на чел ›› {stats['avg_ton']:.0f}\n"
        f"⤷<b>Общий HM/s ››</b> {stats['total_hash']:.0f}\n"
        f"  ⤷ HM/s на чел ›› {stats['avg_hash']:.1f}\n\n"
        f"⤷<b>Товара на Складе ››</b> {stats['total_stock']} шт.\n"
        f"⤷<b>Куплено видеокарт ››</b> {stats['total_cards_sold']} шт.\n"
        f"⤷<b>Получено коробок ››</b> {stats['total_boxes_opened']} шт.\n"
        f"</blockquote>"
    )
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("top"))
async def cmd_top(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    await message.answer(
        "🏆 <b>Выбери топ, который хочешь увидеть</b>",
        reply_markup=get_top_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("level"))
async def cmd_level(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Ошибка: профиль не найден")
        return
    
    nick = user[3] or user[2] or f"Player_{user[1]}"
    current_level = user[11]
    current_exp = user[12]
    current_ton = int(user[4])
    
    # Получаем информацию о следующем уровне
    next_level = current_level + 1
    ton_cost, exp_cost, error = db.get_level_up_cost(current_level)
    
    # Получаем награду за следующий уровень
    next_reward = config.LEVEL_REWARDS.get(next_level, {"ton": 0, "exp": 0, "bonus": "Нет награды"})
    
    level_icon = get_level_icon(current_level)
    
    if current_level < config.MAX_LEVEL and ton_cost and exp_cost:
        text = (
            f"{level_icon} <b>Повышение уровня: {current_level} ›› {next_level}</b>\n\n"
            f"<blockquote>"
            f"[👤 {escape_html(nick)}\n\n"
            f"💰 Тон ›› {current_ton} | {ton_cost}\n"
            f"✨ Опыт ›› {current_exp} | {exp_cost}\n\n"
            f"🎖️ Награда ›› {next_reward['bonus']}"
            f"]"
            f"</blockquote>\n\n"
            f"При повышении с вас вычтут необходимый опыт и тон!"
        )
        
        # Только кнопка повышения
        await message.answer(text, reply_markup=get_level_keyboard(), parse_mode="HTML")
    else:
        if current_level >= config.MAX_LEVEL:
            await message.answer(f"{level_icon} <b>Достигнут максимальный уровень!</b>", parse_mode="HTML")
        else:
            await message.answer(f"{level_icon} <b>Информация об уровне недоступна</b>", parse_mode="HTML")

@dp.message(Command("levelup"))
async def cmd_levelup(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    result = db.level_up(message.from_user.id)
    
    if isinstance(result, tuple) and not result[0]:
        await message.answer(f"❌ {result[1]}")
        return
    
    if isinstance(result, tuple) and result[0]:
        data = result[1]
        
        text = (
            f"✅ <b>Уровень повышен!</b>\n\n"
            f"📊 <b>{data['old_level']} → {data['new_level']}</b>\n"
            f"💰 Потрачено: {data['ton_cost']} тон\n"
            f"✨ Потрачено: {data['exp_cost']} опыта\n\n"
        )
        
        if data['reward']["ton"] > 0 or data['reward']["exp"] > 0:
            text += f"<b>🎁 Награда за уровень:</b>\n"
            if data['reward']["ton"] > 0:
                text += f"├ +{data['reward']['ton']} тон\n"
            if data['reward']["exp"] > 0:
                text += f"├ +{data['reward']['exp']} опыта\n"
            text += f"└ {data['reward']['bonus']}\n\n"
        else:
            text += f"<b>🎁 Бонус:</b> {data['reward']['bonus']}\n\n"
        
        text += f"🌟 Продолжайте в том же духе!"
        
        await message.answer(text, parse_mode="HTML")

@dp.message(Command("daily"))
async def cmd_daily(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    success, ton, exp, streak, extra = db.get_daily_bonus(message.from_user.id)
    
    if success:
        streak_icon = "🔥" if streak >= 7 else "📅"
        text = (
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"💰 <b>+{ton} тон</b>\n"
            f"✨ <b>+{exp} опыта</b>\n"
            f"{streak_icon} <b>Стрик:</b> {streak} дней\n"
            f"{extra}"
        )
    else:
        # Показываем, сколько осталось до следующего бонуса
        db.cursor.execute('SELECT last_bonus FROM daily_bonus WHERE user_id = ?', (message.from_user.id,))
        result = db.cursor.fetchone()
        if result:
            try:
                last = datetime.strptime(result[0], '%Y-%m-%d').date()
                tomorrow = last + timedelta(days=1)
                text = f"⏳ Следующий бонус будет доступен завтра ({tomorrow.strftime('%d.%m.%Y')})"
            except:
                text = "⏳ Следующий бонус будет доступен завтра"
        else:
            text = "❌ Ошибка при получении бонуса"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("events"))
async def cmd_events(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    db.cursor.execute('''
        SELECT event_name, event_time, reward FROM events_log 
        WHERE user_id = ? 
        ORDER BY event_time DESC LIMIT 10
    ''', (message.from_user.id,))
    events = db.cursor.fetchall()
    
    if not events:
        text = "📜 <b>История событий пуста</b>\n\nУ вас пока не было случайных событий!"
    else:
        text = "📜 <b>Последние события:</b>\n\n"
        for event in events:
            event_name = event[0]
            event_time = datetime.fromisoformat(event[1]).strftime('%d.%m.%Y %H:%M')
            text += f"• {event_time}: {event_name}\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("boxes"))
async def cmd_boxes(message: Message):
    """Просмотр своих коробок"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    boxes_count = user[19] if len(user) > 19 else 0
    
    if boxes_count == 0:
        await message.answer("📦 У тебя пока нет коробок! Майни, чтобы получить коробки.")
        return
    
    boxes = db.get_user_boxes(message.from_user.id)
    
    text = f"📦 <b>Твои коробки:</b> {boxes_count} шт.\n\n"
    text += "Нажми на коробку, чтобы открыть:"
    
    await message.answer(
        text,
        reply_markup=get_boxes_keyboard(message.from_user.id, 0, True),
        parse_mode="HTML"
    )

# ==================== АДМИН КОМАНДЫ ====================
@dp.message(Command("pay"))
async def cmd_pay(message: Message):
    """/pay [ID или MID] [сумма] - выдать тон игроку"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "❌ Использование: /pay [ID или MID] [сумма]\n"
            "Пример: /pay 123456789 1000\n"
            "Или: /pay mid:105 1000"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        amount = int(args[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        db.add_gems(target_user[0], amount, message.from_user.id)
        
        await message.answer(
            f"✅ Выдано {amount} тон\n"
            f"Пользователь: {target_user[3]} (MID: {target_user[1]})\n"
            f"💰 Новый баланс: {target_user[4] + amount:.0f} тон"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_user[0],
                f"💰 Вам начислено {amount} тон администратором!"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат ID или суммы!")

@dp.message(Command("take"))
async def cmd_take(message: Message):
    """/take [ID или MID] [сумма] - забрать тон у игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "❌ Использование: /take [ID или MID] [сумма]\n"
            "Пример: /take 123456789 1000\n"
            "Или: /take mid:105 1000"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        amount = int(args[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        if target_user[4] < amount:
            await message.answer(f"❌ У пользователя недостаточно тон! Баланс: {target_user[4]:.0f}")
            return
        
        db.remove_gems(target_user[0], amount, message.from_user.id)
        
        await message.answer(
            f"✅ Забрано {amount} тон\n"
            f"Пользователь: {target_user[3]} (MID: {target_user[1]})\n"
            f"💰 Новый баланс: {target_user[4] - amount:.0f} тон"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_user[0],
                f"💸 У вас списано {amount} тон администратором!"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат ID или суммы!")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    """/ban [ID или MID] [причина] [дни] - забанить игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /ban [ID или MID] [причина] [дни]\n"
            "Пример: /ban 123456789 Нарушение 7\n"
            "Если не указывать дни - бан навсегда"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        reason = "Не указана"
        days = None
        
        if len(args) >= 3:
            # Пытаемся определить, последний аргумент - дни или часть причины
            last_arg = args[-1]
            try:
                days = int(last_arg)
                if len(args) >= 4:
                    reason = args[2]
                elif len(args) == 3:
                    reason = "Не указана"
            except ValueError:
                # Последний аргумент не число, значит это причина без указания дней
                reason = args[2] if len(args) >= 3 else "Не указана"
                days = None
        
        ban_result = db.ban_user(target_user[0], reason, days, message.from_user.id)
        
        if days:
            ban_until = datetime.now() + timedelta(days=days)
            await message.answer(
                f"✅ Пользователь {target_user[3]} (MID: {target_user[1]}) забанен!\n"
                f"📅 До: {ban_until.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 Причина: {reason}"
            )
        else:
            await message.answer(
                f"✅ Пользователь {target_user[3]} (MID: {target_user[1]}) забанен навсегда!\n"
                f"📝 Причина: {reason}"
            )
        
        # Уведомляем пользователя
        try:
            ban_text = f"⛔ Вы забанены администратором!\n📝 Причина: {reason}"
            if days:
                ban_text += f"\n📅 До: {ban_until.strftime('%d.%m.%Y %H:%M')}"
            await bot.send_message(target_user[0], ban_text)
        except:
            pass
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    """/unban [ID или MID] - разбанить игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /unban [ID или MID]\n"
            "Пример: /unban 123456789\n"
            "Или: /unban mid:105"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        if target_user[9] == 0:
            await message.answer(f"⚠️ Пользователь {target_user[3]} не забанен!")
            return
        
        db.unban_user(target_user[0], message.from_user.id)
        
        await message.answer(
            f"✅ Пользователь {target_user[3]} (MID: {target_user[1]}) разбанен!"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(target_user[0], "✅ Вы разбанены администратором!")
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат ID!")

@dp.message(Command("skl"))
async def cmd_skl(message: Message):
    """Управление складом"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    # Получаем информацию о последнем пополнении
    db.cursor.execute('SELECT last_restock FROM auto_restock_log ORDER BY id DESC LIMIT 1')
    result = db.cursor.fetchone()
    
    # Получаем общее количество карт на складе
    db.cursor.execute('SELECT SUM(stock) FROM shop')
    total_stock = db.cursor.fetchone()[0] or 0
    
    # Получаем количество уникальных карт
    db.cursor.execute('SELECT COUNT(*) FROM shop')
    total_cards = db.cursor.fetchone()[0]
    
    text = f"📦 <b>Управление складом</b>\n\n"
    
    if result:
        last = datetime.fromisoformat(result[0])
        text += f"🕐 <b>Последнее пополнение:</b> {last.strftime('%d.%m.%Y %H:%M')}\n"
    else:
        text += f"🕐 <b>Последнее пополнение:</b> никогда\n"
    
    text += f"📊 <b>Всего карт на складе:</b> {total_stock} шт.\n"
    text += f"🃏 <b>Уникальных карт:</b> {total_cards} шт.\n\n"
    text += f"👇 <b>Выбери действие:</b>"
    
    await message.answer(text, reply_markup=get_skl_keyboard(), parse_mode="HTML")

@dp.message(Command("referals"))  # с одной 'r' для просмотра рефералов игрока
async def cmd_referals(message: Message):
    """Просмотр рефералов игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /referals [ID или MID]\n"
            "Пример: /referals 123456789\n"
            "Или: /referals mid:105"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        referrals = db.get_user_referrals(target_user[0])
        
        text = f"👥 <b>Рефералы игрока {target_user[3]}</b>\n\n"
        
        if not referrals:
            text += "У игрока пока нет рефералов."
        else:
            for i, ref in enumerate(referrals[:20], 1):
                name = ref[1] or ref[2] or f"Player_{ref[0]}"
                level = ref[3]
                gems = ref[4]
                date = datetime.fromisoformat(ref[5]).strftime('%d.%m.%Y')
                
                text += f"{i}. {escape_html(name)} (MID: {ref[0]})\n"
                text += f"   ├ 🌱 Ур. {level}\n"
                text += f"   ├ 💰 {gems} тон\n"
                text += f"   └ 📅 {date}\n\n"
            
            if len(referrals) > 20:
                text += f"... и ещё {len(referrals) - 20} рефералов"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("logs"))
async def cmd_logs(message: Message):
    """Просмотр логов игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /logs [ID или MID]\n"
            "Пример: /logs 123456789\n"
            "Или: /logs mid:105"
        )
        return
    
    try:
        # Определяем, ID это или MID
        target = args[1]
        
        target_user = None
        if target.startswith("mid:"):
            # Поиск по MID
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
            # Поиск по Telegram ID
            target_user = db.get_user(int(target))
        
        if not target_user:
            await message.answer(f"❌ Пользователь {target} не найден!")
            return
        
        logs = db.get_user_logs(target_user[0], 30)
        
        text = f"📋 <b>Логи игрока {target_user[3]}</b>\n\n"
        
        if not logs:
            text += "Логов не найдено."
        else:
            for log in logs[:20]:
                log_type = log[0]
                log_time = datetime.fromisoformat(log[1]).strftime('%d.%m.%Y %H:%M') if log[1] else "Неизвестно"
                log_action = log[2]
                log_details = log[3] if len(log) > 3 else ""
                
                if log_type == 'event':
                    icon = "✨"
                else:
                    icon = "📈"
                
                text += f"{icon} [{log_time}] {log_action}\n"
                if log_details:
                    text += f"   └ {escape_html(log_details)}\n"
                text += "\n"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ==================== ОБРАБОТЧИКИ КНОПОК ПОМОЩИ ====================
@dp.callback_query(F.data == "help_menu")
async def help_menu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    help_text = (
        "📚 Добро пожаловать в раздел помощи!\n\n"
        "Здесь вы можете узнать подробную информацию о каждом разделе бота.\n"
        "Выберите интересующий вас раздел ниже:"
    )
    await callback.message.edit_text(help_text, reply_markup=get_help_keyboard())

@dp.callback_query(F.data == "back_to_help")
async def back_to_help(callback: CallbackQuery):
    await callback.answer()
    help_text = (
        "📚 Добро пожаловать в раздел помощи!\n\n"
        "Здесь вы можете узнать подробную информацию о каждом разделе бота.\n"
        "Выберите интересующий вас раздел ниже:"
    )
    await callback.message.edit_text(help_text, reply_markup=get_help_keyboard())

@dp.callback_query(F.data == "help_mine")
async def help_mine(callback: CallbackQuery):
    await callback.answer()
    text = (
        "⛏ Майнинг\n\n"
        "Как работает:\n"
        "• Майнинг доступен 1 раз в час\n"
        "• Базовая награда: 10 тон\n"
        "• Каждая видеокарта добавляет бонус к награде\n"
        "• Чем больше хешрейт, тем больше тон\n"
        "• Есть шанс получить коробку с лутом (10%)\n\n"
        "Команда: /mine"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_shop")
async def help_shop(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🛒 ДНС (Магазин)\n\n"
        "Здесь вы можете покупать новые видеокарты.\n\n"
        "Характеристики карт:\n"
        "• Хешрейт (MH/s) - влияет на доход\n"
        "• Цена (тон) - стоимость покупки\n"
        "• Наличие - ✅ в наличии, ⛔ нет на складе\n\n"
        "Команда: /shop"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_wallet")
async def help_wallet(callback: CallbackQuery):
    await callback.answer()
    text = (
        "💼 Кошелек\n\n"
        "Здесь отображается ваш баланс тон.\n\n"
        "Функции:\n"
        "• Просмотр текущего баланса\n"
        "• Пополнение (в разработке)\n"
        "• Вывод (в разработке)\n\n"
        "Команда: /wallet"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_cards")
async def help_cards(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🖥 Видеокарты\n\n"
        "Здесь показаны все ваши видеокарты.\n\n"
        "Типы карт:\n"
        "• 🔰 Стартовая - не ломается, всегда с вами\n"
        "• ✅ Рабочие - приносят доход\n"
        "• ⚠️ Сломанные - требуют ремонта\n\n"
        "Команда: /profile"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_repair")
async def help_repair(callback: CallbackQuery):
    await callback.answer()
    text = (
        f"🔧 Ремонт видеокарт\n\n"
        f"Видеокарты изнашиваются после каждого майнинга.\n\n"
        f"Правила ремонта:\n"
        f"• Базовая стоимость: {config.REPAIR_COST} тон\n"
        f"• Скидка от уровня и привилегии\n"
        f"• Ремонтируются ВСЕ сломанные карты сразу\n"
        f"• Стартовая карта не ломается\n\n"
        f"Команда: /repair"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_referrals")
async def help_referrals(callback: CallbackQuery):
    await callback.answer()
    text = (
        f"👥 Реферальная система\n\n"
        f"Приглашайте друзей и получайте бонусы!\n\n"
        f"Бонусы:\n"
        f"• За друга: +{config.REFERRAL_BONUS} тон и {config.REFERRAL_EXP_BONUS} опыта\n"
        f"• Другу: +{config.REFERRAL_BONUS_FOR_NEW} тон и {config.REFERRAL_EXP_FOR_NEW} опыта\n\n"
        f"Команда: /referrals"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_top")
async def help_top(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🏆 Топ игроков\n\n"
        "Рейтинг лучших игроков бота.\n\n"
        "Категории:\n"
        "• По тонам\n"
        "• По уровню\n"
        "• По хешрейту\n"
        "• По рефералам\n\n"
        "Команда: /top"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_stats")
async def help_stats(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📊 Статистика бота\n\n"
        "Общая статистика по всем пользователям.\n\n"
        "Показатели:\n"
        "• Онлайн за 24ч\n"
        "• Всего пользователей\n"
        "• Продано видеокарт\n"
        "• Добыто тон\n"
        "• Всего майнингов\n"
        "• Открыто коробок\n\n"
        "Команда: /stats"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

@dp.callback_query(F.data == "help_boxes")
async def help_boxes(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📦 Коробки с лутом\n\n"
        "Коробки можно получить во время майнинга (шанс 10%).\n\n"
        "В коробке можно найти:\n"
        "• Тоны\n"
        "• Опыт\n"
        "• Компоненты для крафта\n"
        "• Привилегии (редкий шанс)\n\n"
        "Команда: /boxes"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_help_keyboard())

# ==================== ОБРАБОТЧИКИ ОСНОВНЫХ КНОПОК ====================
@dp.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    
    menu_text = (
        f"👋 <b>Главное меню</b>\n\n"
        f"<blockquote>"
        f"Здесь ты можешь зарабатывать тон, майнить криптовалюту и покупать видеокарты в магазине"
        f"</blockquote>\n\n"
        f"👇 <b>Выбери действие:</b>"
    )
    
    await callback.message.edit_text(
        menu_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    await send_main_menu(callback.from_user.id)

@dp.callback_query(F.data == "daily_bonus")
async def process_daily_bonus(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    success, ton, exp, streak, extra = db.get_daily_bonus(callback.from_user.id)
    
    if success:
        streak_icon = "🔥" if streak >= 7 else "📅"
        text = (
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"💰 <b>+{ton} тон</b>\n"
            f"✨ <b>+{exp} опыта</b>\n"
            f"{streak_icon} <b>Стрик:</b> {streak} дней\n"
            f"{extra}"
        )
    else:
        db.cursor.execute('SELECT last_bonus FROM daily_bonus WHERE user_id = ?', (callback.from_user.id,))
        result = db.cursor.fetchone()
        if result:
            try:
                last = datetime.strptime(result[0], '%Y-%m-%d').date()
                tomorrow = last + timedelta(days=1)
                text = f"⏳ Следующий бонус будет доступен завтра ({tomorrow.strftime('%d.%m.%Y')})"
            except:
                text = "⏳ Следующий бонус будет доступен завтра"
        else:
            text = "❌ Ошибка при получении бонуса"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "mine")
async def process_mine(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    success, result = db.mine(callback.from_user.id)
    
    # Отправляем ответ с HTML-форматированием
    await callback.message.edit_text(result, parse_mode="HTML")

@dp.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await show_user_profile(callback, callback.from_user.id, is_own=True)

@dp.callback_query(F.data.startswith("view_profile_"))
async def process_view_profile(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    target_user_id = int(callback.data.split("_")[2])
    await show_user_profile(callback, target_user_id, is_own=False)

@dp.callback_query(F.data == "my_cards")
async def process_my_cards(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    cards = db.get_user_cards(callback.from_user.id)
    
    if not cards:
        await callback.message.edit_text(
            "🖥 У тебя нет видеокарт!",
            reply_markup=get_profile_keyboard()
        )
        return
    
    await callback.message.edit_text(
        "🖥 Твои видеокарты - Страница 1\n\n"
        "🔰 - Стартовая (не ломается)\n"
        "✅ - Рабочая\n"
        "⚠️ - Сломана (нужен ремонт)",
        reply_markup=get_mycards_keyboard(callback.from_user.id, 0)
    )

@dp.callback_query(F.data.startswith("view_cards_"))
async def process_view_cards(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    target_user_id = int(callback.data.split("_")[2])
    cards = db.get_user_cards(target_user_id)
    
    if not cards:
        await callback.message.edit_text(
            "🖥 У игрока нет видеокарт!",
            reply_markup=get_profile_keyboard(target_user_id)
        )
        return
    
    await callback.message.edit_text(
        f"🖥 Видеокарты игрока - Страница 1\n\n"
        "🔰 - Стартовая (не ломается)\n"
        "✅ - Рабочая\n"
        "⚠️ - Сломана",
        reply_markup=get_view_cards_keyboard(target_user_id, 0)
    )

@dp.callback_query(F.data.startswith("view_cards_page_"))
async def view_cards_page_handler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    parts = callback.data.split("_")
    target_user_id = int(parts[3])
    page = int(parts[4])
    
    await callback.message.edit_text(
        f"🖥 Видеокарты игрока - Страница {page+1}\n\n"
        "🔰 - Стартовая (не ломается)\n"
        "✅ - Рабочая\n"
        "⚠️ - Сломана",
        reply_markup=get_view_cards_keyboard(target_user_id, page)
    )

@dp.callback_query(F.data.startswith("mycards_page_"))
async def mycards_page_handler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    page = int(callback.data.split("_")[2])
    
    await callback.message.edit_text(
        f"🖥 Твои видеокарты - Страница {page+1}\n\n"
        "🔰 - Стартовая (не ломается)\n"
        "✅ - Рабочая\n"
        "⚠️ - Сломана (нужен ремонт)",
        reply_markup=get_mycards_keyboard(callback.from_user.id, page)
    )

@dp.callback_query(F.data.startswith("mycard_detail_"))
async def mycard_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    card_id = int(callback.data.split("_")[2])
    
    db.cursor.execute('SELECT * FROM user_cards WHERE id = ?', (card_id,))
    card = db.cursor.fetchone()
    
    if not card:
        await callback.message.edit_text("Карта не найдена!", reply_markup=get_profile_keyboard())
        return
    
    # Определяем статус
    if card[5] == 1:
        status = "🔰 Стартовая (не ломается)"
        wear_text = "∞"
    elif card[4] <= config.MIN_WEAR_FOR_MINING:
        status = "⚠️ Сломана"
        wear_text = f"{card[4]}%"
    else:
        status = "✅ Рабочая"
        wear_text = f"{card[4]}%"
    
    detail_text = (
        f"🖥 {card[2]}\n\n"
        f"📊 Статус: {status}\n"
        f"⚡ Хешрейт: {card[3]} MH/s\n"
        f"🔧 Износ: {wear_text}\n\n"
    )
    
    if card[4] <= config.MIN_WEAR_FOR_MINING and card[5] == 0:
        detail_text += f"⚠️ Карта сломана! Используй /repair для ремонта."
    
    await callback.message.edit_text(detail_text, reply_markup=get_mycard_detail_keyboard(card_id))

@dp.callback_query(F.data.startswith("view_card_detail_"))
async def view_card_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    card_id = int(callback.data.split("_")[3])
    
    db.cursor.execute('SELECT * FROM user_cards WHERE id = ?', (card_id,))
    card = db.cursor.fetchone()
    
    if not card:
        await callback.message.edit_text("Карта не найдена!")
        return
    
    # Определяем статус
    if card[5] == 1:
        status = "🔰 Стартовая (не ломается)"
        wear_text = "∞"
    elif card[4] <= config.MIN_WEAR_FOR_MINING:
        status = "⚠️ Сломана"
        wear_text = f"{card[4]}%"
    else:
        status = "✅ Рабочая"
        wear_text = f"{card[4]}%"
    
    detail_text = (
        f"🖥 {card[2]}\n\n"
        f"📊 Статус: {status}\n"
        f"⚡ Хешрейт: {card[3]} MH/s\n"
        f"🔧 Износ: {wear_text}\n\n"
    )
    
    await callback.message.edit_text(
        detail_text, 
        reply_markup=get_view_card_detail_keyboard(card_id, card[1])
    )

@dp.callback_query(F.data == "my_boxes")
async def process_my_boxes(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    user = db.get_user(callback.from_user.id)
    boxes_count = user[19] if len(user) > 19 else 0
    
    if boxes_count == 0:
        await callback.message.edit_text(
            "📦 У тебя пока нет коробок! Майни, чтобы получить коробки.",
            reply_markup=get_profile_keyboard()
        )
        return
    
    boxes = db.get_user_boxes(callback.from_user.id)
    
    text = f"📦 <b>Твои коробки:</b> {boxes_count} шт.\n\n"
    text += "Нажми на коробку, чтобы открыть:"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_boxes_keyboard(callback.from_user.id, 0, True),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("view_boxes_"))
async def process_view_boxes(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    target_user_id = int(callback.data.split("_")[2])
    
    user = db.get_user(target_user_id)
    boxes_count = user[19] if len(user) > 19 else 0
    
    if boxes_count == 0:
        await callback.message.edit_text(
            "📦 У игрока нет коробок.",
            reply_markup=get_profile_keyboard(target_user_id)
        )
        return
    
    boxes = db.get_user_boxes(target_user_id)
    
    text = f"📦 <b>Коробки игрока {escape_html(user[3])}:</b> {boxes_count} шт.\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_boxes_keyboard(target_user_id, 0, False),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("boxes_page_"))
async def boxes_page_handler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    parts = callback.data.split("_")
    user_id = int(parts[2])
    page = int(parts[3])
    is_own = parts[4] == "True"
    
    user = db.get_user(user_id)
    boxes_count = user[19] if len(user) > 19 else 0
    
    if is_own:
        text = f"📦 <b>Твои коробки:</b> {boxes_count} шт.\n\nНажми на коробку, чтобы открыть:"
    else:
        text = f"📦 <b>Коробки игрока {escape_html(user[3])}:</b> {boxes_count} шт."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_boxes_keyboard(user_id, page, is_own),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("open_box_"))
async def process_open_box(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    box_id = int(callback.data.split("_")[2])
    
    success, result = db.open_box(box_id)
    
    if success:
        await callback.message.edit_text(
            result,
            parse_mode="HTML"
        )
        
        # Добавляем кнопку назад
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 К коробкам", callback_data="my_boxes")],
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    else:
        await callback.answer(result, show_alert=True)

@dp.callback_query(F.data == "stats")
async def process_stats(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    stats = db.get_stats()
    
    text = (
        f"⚡️<b>Статистика бота:</b>\n\n"
        f"<blockquote>"
        f"⤷<b>Общий онлайн ››</b> {stats['total_users']}\n"
        f"  ⤷ Онлайн за 24 часа ›› {stats['online_24h']}\n"
        f"  ⤷ Текущий онлайн ›› {stats['current_online']}\n\n"
        f"⤷<b>Тон у игроков ››</b> {stats['total_ton']:.0f}\n"
        f"  ⤷ Тон на чел ›› {stats['avg_ton']:.0f}\n"
        f"⤷<b>Общий HM/s ››</b> {stats['total_hash']:.0f}\n"
        f"  ⤷ HM/s на чел ›› {stats['avg_hash']:.1f}\n\n"
        f"⤷<b>Товара на Складе ››</b> {stats['total_stock']} шт.\n"
        f"⤷<b>Куплено видеокарт ››</b> {stats['total_cards_sold']} шт.\n"
        f"⤷<b>Получено коробок ››</b> {stats['total_boxes_opened']} шт.\n"
        f"</blockquote>"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML")

@dp.callback_query(F.data == "top_menu")
async def top_menu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await callback.message.edit_text(
        "🏆 <b>Выбери топ, который хочешь увидеть</b>",
        reply_markup=get_top_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("top_"))
async def process_top(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    category = callback.data.split("_")[1]
    
    results = db.get_top(category)
    
    # Заголовки для разных категорий
    titles = {
        "gems": "💰 <b>Топ по тонам</b>",
        "level": "📶 <b>Топ по уровню</b>",
        "hash": "⚡ <b>Топ по хешрейту</b>",
        "referrals": "👥 <b>Топ по рефералам</b>"
    }
    
    title = titles.get(category, "🏆 Топ")
    
    if not results:
        text = f"{title}\n\n<blockquote>Пока нет данных...</blockquote>"
    else:
        text = f"{title}\n\n<blockquote>"
        
        for i, res in enumerate(results, 1):
            user_id = res[0]
            
            # Формируем имя с ссылкой на профиль в боте
            if res[1]:  # если есть username
                name_display = f"@{res[1]}"
            else:
                name_display = escape_html(res[2] or f"Игрок {i}")
            
            # Добавляем иконку для топ-3
            if i == 1:
                icon = "🥇"
            elif i == 2:
                icon = "🥈"
            elif i == 3:
                icon = "🥉"
            else:
                icon = f"{i}."
            
            # Форматируем значение в зависимости от категории
            if category == "gems":
                value = f"{res[3]:.0f} тон"
                profile_link = f"/profile {res[0]}"
            elif category == "level":
                value = f"{res[3]} ур. ({res[4]} опыта)"
                profile_link = f"/profile {res[0]}"
            elif category == "hash":
                value = f"{res[3]:.1f} MH/s"
                profile_link = f"/profile {res[0]}"
            elif category == "referrals":
                value = f"{res[3]} рефералов"
                profile_link = f"/profile {res[0]}"
            else:
                value = str(res[2])
                profile_link = f"/profile {res[0]}"
            
            text += f"{icon} <a href=\"{profile_link}\">{name_display}</a> — {value}\n"
        
        text += "</blockquote>"
    
    # Добавляем кнопку для возврата к выбору топа
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К выбору топа", callback_data="top_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "level")
async def process_level(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    
    nick = user[3] or user[2] or f"Player_{user[1]}"
    current_level = user[11]
    current_exp = user[12]
    current_ton = int(user[4])
    
    # Получаем информацию о следующем уровне
    next_level = current_level + 1
    ton_cost, exp_cost, error = db.get_level_up_cost(current_level)
    
    # Получаем награду за следующий уровень
    next_reward = config.LEVEL_REWARDS.get(next_level, {"ton": 0, "exp": 0, "bonus": "Нет награды"})
    
    level_icon = get_level_icon(current_level)
    
    if current_level < config.MAX_LEVEL and ton_cost and exp_cost:
        text = (
            f"{level_icon} <b>Повышение уровня: {current_level} ›› {next_level}</b>\n\n"
            f"<blockquote>"
            f"[👤 {escape_html(nick)}\n\n"
            f"💰 Тон ›› {current_ton} | {ton_cost}\n"
            f"✨ Опыт ›› {current_exp} | {exp_cost}\n\n"
            f"🎖️ Награда ›› {next_reward['bonus']}"
            f"]"
            f"</blockquote>\n\n"
            f"При повышении с вас вычтут необходимый опыт и тон!"
        )
        
        # Только кнопка повышения
        await callback.message.edit_text(text, reply_markup=get_level_keyboard(), parse_mode="HTML")
    else:
        if current_level >= config.MAX_LEVEL:
            await callback.message.edit_text(f"{level_icon} <b>Достигнут максимальный уровень!</b>", parse_mode="HTML")
        else:
            await callback.message.edit_text(f"{level_icon} <b>Информация об уровне недоступна</b>", parse_mode="HTML")

@dp.callback_query(F.data == "level_up")
async def process_level_up(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    result = db.level_up(callback.from_user.id)
    
    if isinstance(result, tuple) and not result[0]:
        await callback.message.edit_text(f"❌ {result[1]}")
        return
    
    if isinstance(result, tuple) and result[0]:
        data = result[1]
        
        text = (
            f"✅ <b>Уровень повышен!</b>\n\n"
            f"📊 <b>{data['old_level']} → {data['new_level']}</b>\n"
            f"💰 Потрачено: {data['ton_cost']} тон\n"
            f"✨ Потрачено: {data['exp_cost']} опыта\n\n"
        )
        
        if data['reward']["ton"] > 0 or data['reward']["exp"] > 0:
            text += f"<b>🎁 Награда за уровень:</b>\n"
            if data['reward']["ton"] > 0:
                text += f"├ +{data['reward']['ton']} тон\n"
            if data['reward']["exp"] > 0:
                text += f"├ +{data['reward']['exp']} опыта\n"
            text += f"└ {data['reward']['bonus']}\n\n"
        else:
            text += f"<b>🎁 Бонус:</b> {data['reward']['bonus']}\n\n"
        
        text += f"🌟 Продолжайте в том же духе!"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 К уровню", callback_data="level")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "donate_menu")
async def donate_menu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    user = db.get_user(callback.from_user.id)
    current_privilege, until = db.get_user_privilege(callback.from_user.id)
    
    # Красивое оформление меню доната
    text = (
        f"🪙 <b>Поддержать проект</b>\n\n"
        f"Приобрети привилегию и получи уникальные бонусы в игре!\n"
        f"Все средства идут на развитие бота 🚀\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    # Премиум
    text += (
        f"<b>⭐ ПРЕМИУМ</b> — 50 ★\n"
        f"<blockquote>"
        f"• x1.5 к доходу от майнинга\n"
        f"• x1.5 к опыту\n"
        f"• -10% к ремонту\n"
        f"• Макс. карт: 15"
        f"</blockquote>\n\n"
    )
    
    # VIP
    text += (
        f"<b>👑 VIP</b> — 150 ★\n"
        f"<blockquote>"
        f"• x2 к доходу от майнинга\n"
        f"• x2 к опыту\n"
        f"• -20% к ремонту\n"
        f"• +5 MH/s ко всем картам\n"
        f"• Макс. карт: 20"
        f"</blockquote>\n\n"
    )
    
    # Легенда
    text += (
        f"<b>🌟 ЛЕГЕНДА</b> — 500 ★\n"
        f"<blockquote>"
        f"• x3 к доходу от майнинга\n"
        f"• x3 к опыту\n"
        f"• -30% к ремонту\n"
        f"• +10 MH/s ко всем картам\n"
        f"• Макс. карт: 25\n"
        f"• Увеличен шанс событий"
        f"</blockquote>\n\n"
    )
    
    text += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Информация о текущей привилегии
    if current_privilege != "player":
        priv_data = config.PRIVILEGES[current_privilege]
        until_str = datetime.fromisoformat(until).strftime('%d.%m.%Y') if until else "навсегда"
        text += f"✨ <b>Твоя привилегия:</b> {priv_data['icon']} {priv_data['name']}\n"
        text += f"📅 <b>Действует до:</b> {until_str}\n\n"
    else:
        text += f"✨ <b>Твоя привилегия:</b> Обычный игрок\n\n"
    
    # Баланс
    text += (
        f"💰 <b>Твой баланс:</b> {int(user[4])} тон\n"
        f"💎 <b>Звезд:</b> {user[18] if len(user) > 18 and user[18] else 0} ★\n\n"
    )
    
    text += f"👇 <b>Выбери привилегию для покупки:</b>"
    
    await callback.message.edit_text(text, reply_markup=get_donate_keyboard(), parse_mode="HTML")

# ==================== АДМИН КНОПКИ (СКЛАД) ====================
@dp.callback_query(F.data == "admin_show_stock")
async def admin_show_stock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    items = db.get_all_shop_items()
    
    if not items:
        await callback.message.edit_text("📦 На складе пока нет товаров!")
        await callback.answer()
        return
    
    text = "📦 Текущее состояние склада:\n\n"
    for item in items:
        text += f"🆔 ID: {item[0]}\n"
        text += f"🖥 {item[1]}\n"
        text += f"   ⚡ Хешрейт: {item[2]} MH/s\n"
        text += f"   💎 Цена: {item[3]} тон\n"
        text += f"   📦 В наличии: {item[4]} шт.\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_skl")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data == "admin_add_stock")
async def admin_add_stock_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    items = db.get_all_shop_items()
    
    if not items:
        await callback.message.edit_text("❌ В магазине нет товаров!")
        await callback.answer()
        return
    
    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(
            text=f"{item[1]} (сейчас: {item[4]} шт.)",
            callback_data=f"admin_select_card_{item[0]}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_skl")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(
        "📦 Выбери карту для пополнения:",
        reply_markup=keyboard
    )
    await state.set_state(AdminStates.waiting_for_card_id)
    await callback.answer()

@dp.callback_query(F.data == "admin_remove_stock")
async def admin_remove_stock_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    items = db.get_all_shop_items()
    
    if not items:
        await callback.message.edit_text("❌ В магазине нет товаров!")
        await callback.answer()
        return
    
    # Показываем только карты, у которых есть наличие
    items_with_stock = [item for item in items if item[4] > 0]
    
    if not items_with_stock:
        await callback.message.edit_text("📦 На складе нет карт для удаления!")
        await callback.answer()
        return
    
    buttons = []
    for item in items_with_stock:
        buttons.append([InlineKeyboardButton(
            text=f"{item[1]} (в наличии: {item[4]} шт.)",
            callback_data=f"admin_remove_select_{item[0]}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_skl")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(
        "📦 Выбери карту для удаления со склада:",
        reply_markup=keyboard
    )
    await state.set_state(AdminStates.waiting_for_remove_stock)
    await callback.answer()

@dp.callback_query(F.data == "admin_stock_stats")
async def admin_stock_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    # Получаем статистику по складу
    db.cursor.execute('SELECT SUM(stock) FROM shop')
    total_stock = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute('SELECT COUNT(*) FROM shop WHERE stock > 0')
    cards_in_stock = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT card_name, stock FROM shop WHERE stock > 0 ORDER BY stock DESC LIMIT 5')
    top_cards = db.cursor.fetchall()
    
    db.cursor.execute('SELECT card_name, price FROM shop ORDER BY price DESC LIMIT 3')
    most_expensive = db.cursor.fetchall()
    
    db.cursor.execute('SELECT SUM(stock * price) FROM shop')
    total_value = db.cursor.fetchone()[0] or 0
    
    text = f"📊 <b>Статистика склада</b>\n\n"
    text += f"📦 <b>Всего карт:</b> {total_stock} шт.\n"
    text += f"🃏 <b>Типов карт в наличии:</b> {cards_in_stock}\n"
    text += f"💎 <b>Общая стоимость:</b> {total_value:.0f} тон\n\n"
    
    if top_cards:
        text += f"📈 <b>Топ карт по наличию:</b>\n"
        for card in top_cards:
            text += f"  • {card[0]} — {card[1]} шт.\n"
        text += "\n"
    
    if most_expensive:
        text += f"💰 <b>Самые дорогие карты:</b>\n"
        for card in most_expensive:
            text += f"  • {card[0]} — {card[1]} тон\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_skl")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "admin_back_to_skl")
async def admin_back_to_skl(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    await callback.answer()
    
    # Получаем информацию о последнем пополнении
    db.cursor.execute('SELECT last_restock FROM auto_restock_log ORDER BY id DESC LIMIT 1')
    result = db.cursor.fetchone()
    
    # Получаем общее количество карт на складе
    db.cursor.execute('SELECT SUM(stock) FROM shop')
    total_stock = db.cursor.fetchone()[0] or 0
    
    # Получаем количество уникальных карт
    db.cursor.execute('SELECT COUNT(*) FROM shop')
    total_cards = db.cursor.fetchone()[0]
    
    text = f"📦 <b>Управление складом</b>\n\n"
    
    if result:
        last = datetime.fromisoformat(result[0])
        text += f"🕐 <b>Последнее пополнение:</b> {last.strftime('%d.%m.%Y %H:%M')}\n"
    else:
        text += f"🕐 <b>Последнее пополнение:</b> никогда\n"
    
    text += f"📊 <b>Всего карт на складе:</b> {total_stock} шт.\n"
    text += f"🃏 <b>Уникальных карт:</b> {total_cards} шт.\n\n"
    text += f"👇 <b>Выбери действие:</b>"
    
    await callback.message.edit_text(text, reply_markup=get_skl_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("admin_select_card_"))
async def admin_select_card(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    card_id = int(callback.data.split("_")[3])
    card = db.get_card_by_id(card_id)
    
    if not card:
        await callback.message.edit_text("❌ Карта не найдена!")
        await state.clear()
        await callback.answer()
        return
    
    await state.update_data(selected_card_id=card_id, card_name=card[1], current_stock=card[4])
    
    await callback.message.edit_text(
        f"🖥 {card[1]}\n"
        f"📦 Текущее количество: {card[4]} шт.\n\n"
        f"Введи количество для добавления (целое число):\n\n"
        f"Или отправь /cancel для отмены"
    )
    await state.set_state(AdminStates.waiting_for_new_stock)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_remove_select_"))
async def admin_remove_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    card_id = int(callback.data.split("_")[3])
    card = db.get_card_by_id(card_id)
    
    if not card:
        await callback.message.edit_text("❌ Карта не найдена!")
        await state.clear()
        await callback.answer()
        return
    
    await state.update_data(selected_card_id=card_id, card_name=card[1], current_stock=card[4])
    
    await callback.message.edit_text(
        f"🖥 {card[1]}\n"
        f"📦 Текущее количество: {card[4]} шт.\n\n"
        f"Введи количество для удаления (целое число):\n\n"
        f"Или отправь /cancel для отмены"
    )
    await state.set_state(AdminStates.waiting_for_remove_stock)
    await callback.answer()

@dp.message(AdminStates.waiting_for_new_stock)
async def admin_process_new_stock(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Операция отменена")
        return
    
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Количество должно быть положительным числом! Отправь /cancel для отмены:")
            return
        
        data = await state.get_data()
        card_id = data.get('selected_card_id')
        card_name = data.get('card_name')
        old_stock = data.get('current_stock')
        
        if not all([card_id, card_name, old_stock is not None]):
            await message.answer("❌ Ошибка данных. Начни заново с /skl")
            await state.clear()
            return
        
        new_stock = old_stock + amount
        db.update_stock(card_id, new_stock)
        
        await message.answer(
            f"✅ Склад обновлен!\n\n"
            f"🖥 {card_name}\n"
            f"➕ Добавлено: +{amount} шт.\n"
            f"📦 Было: {old_stock} шт.\n"
            f"📦 Стало: {new_stock} шт."
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введи целое число! Или отправь /cancel для отмены")

@dp.message(AdminStates.waiting_for_remove_stock)
async def admin_process_remove_stock(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        await state.clear()
        return
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Операция отменена")
        return
    
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Количество должно быть положительным числом! Отправь /cancel для отмены:")
            return
        
        data = await state.get_data()
        card_id = data.get('selected_card_id')
        card_name = data.get('card_name')
        old_stock = data.get('current_stock')
        
        if not all([card_id, card_name, old_stock is not None]):
            await message.answer("❌ Ошибка данных. Начни заново с /skl")
            await state.clear()
            return
        
        if amount > old_stock:
            await message.answer(f"❌ Нельзя удалить больше, чем есть на складе! Доступно: {old_stock} шт.")
            return
        
        new_stock = old_stock - amount
        db.update_stock(card_id, new_stock)
        
        await message.answer(
            f"✅ Склад обновлен!\n\n"
            f"🖥 {card_name}\n"
            f"➖ Удалено: -{amount} шт.\n"
            f"📦 Было: {old_stock} шт.\n"
            f"📦 Стало: {new_stock} шт."
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введи целое число! Или отправь /cancel для отмены")

# ==================== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ПОКУПКИ ПРИВИЛЕГИЙ ====================
async def buy_privilege(message: Message, privilege_name):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    privilege_data = config.PRIVILEGES.get(privilege_name)
    if not privilege_data:
        await message.answer("❌ Привилегия не найдена")
        return
    
    # Проверяем текущую привилегию
    current_privilege, until = db.get_user_privilege(message.from_user.id)
    if current_privilege != "player":
        priv_data = config.PRIVILEGES[current_privilege]
        await message.answer(
            f"❌ У вас уже есть привилегия {priv_data['icon']} {priv_data['name']}!\n"
            f"Дождитесь её окончания или обратитесь к администратору."
        )
        return
    
    price = privilege_data["price"]
    title = f"Покупка привилегии {privilege_data['icon']} {privilege_data['name']}"
    description = privilege_data["description"]
    
    # Создаем инвойс для оплаты звездами
    prices = [LabeledPrice(label=title, amount=price)]
    
    # Отправляем счет на оплату
    await message.answer_invoice(
        title=title,
        description=description,
        payload=f"buy_privilege_{privilege_name}",
        provider_token=config.STARS_PAYMENT_PROVIDER_TOKEN,
        currency=config.STARS_CURRENCY,
        prices=prices,
        start_parameter="buy_privilege"
    )

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_callback(callback: CallbackQuery):
    await callback.answer()
    await buy_privilege(callback.message, "premium")

@dp.callback_query(F.data == "buy_vip")
async def buy_vip_callback(callback: CallbackQuery):
    await callback.answer()
    await buy_privilege(callback.message, "vip")

@dp.callback_query(F.data == "buy_legend")
async def buy_legend_callback(callback: CallbackQuery):
    await callback.answer()
    await buy_privilege(callback.message, "legend")

# ==================== ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ====================
@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("buy_privilege_"):
        privilege_name = payload.replace("buy_privilege_", "")
        privilege_data = config.PRIVILEGES.get(privilege_name)
        
        if privilege_data:
            success, result = db.apply_privilege(
                message.from_user.id, 
                privilege_name, 
                privilege_data["duration"]
            )
            
            if success:
                await message.answer(
                    f"✅ Оплата прошла успешно!\n\n{result}\n\n"
                    f"Спасибо за поддержку бота! 🙏"
                )
            else:
                await message.answer(f"❌ Ошибка: {result}")

# ==================== ЗАПУСК БОТА ====================
async def main():
    print("🤖 Бот запущен!")
    print(f"👑 Админы: {config.ADMIN_IDS}")
    print(f"📦 Автопополнение: {'Включено' if config.AUTO_RESTOCK_ENABLED else 'Выключено'}")
    print(f"⏰ Время пополнения: {config.AUTO_RESTOCK_TIME} МСК")
    print("⚡ Нажми Ctrl+C для остановки")
    
    # Запускаем фоновую задачу для автоматического пополнения
    asyncio.create_task(auto_restock_scheduler())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")