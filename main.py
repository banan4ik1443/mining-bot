import asyncio
import logging
import sqlite3
import os
import sys
import random
import re
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, ContentType, InputMediaPhoto, InlineQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import config
from cards_config import GPU_CARDS, COOLERS, ASICS, GPU_RIGS, STARTER_ASIC

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class WalletStates(StatesGroup):
    waiting_stars_amount = State()

# Функция для экранирования специальных символов HTML
def escape_html(text):
    """Экранирует специальные символы для HTML"""
    if text is None:
        return ""
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('mining_bot.db', check_same_thread=False, timeout=30)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA busy_timeout=30000')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self.conn.execute('PRAGMA cache_size=-32000')
        self.conn.execute('PRAGMA temp_store=MEMORY')
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        """Инициализация всех таблиц базы данных"""
        
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                custom_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                gems REAL DEFAULT 1000,
                hash_rate REAL DEFAULT 0,
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
                boxes_count INTEGER DEFAULT 0,
                privilege TEXT DEFAULT "player",
                privilege_until TIMESTAMP DEFAULT NULL,
                total_stars_spent INTEGER DEFAULT 0,
                stars_balance INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица видеокарт пользователя
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_gpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gpu_key TEXT,
                name TEXT,
                hash_rate REAL,
                wear INTEGER DEFAULT 100,
                is_installed INTEGER DEFAULT 0,
                rig_id INTEGER DEFAULT NULL,
                slot_index INTEGER DEFAULT NULL,
                is_crafted INTEGER DEFAULT 0,
                wear_multiplier REAL DEFAULT 1.0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Миграция: таблица барахолки
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    hash_rate REAL DEFAULT 0,
                    cooling_power INTEGER DEFAULT 0,
                    wear INTEGER DEFAULT 100,
                    price INTEGER NOT NULL,
                    is_crafted INTEGER DEFAULT 0,
                    listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            ''')
        except Exception:
            pass

        # Миграция: добавляем поля крафта в user_gpus если нет
        try:
            self.cursor.execute("ALTER TABLE user_gpus ADD COLUMN is_crafted INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE user_gpus ADD COLUMN wear_multiplier REAL DEFAULT 1.0")
        except Exception:
            pass

        # Таблица барахолки (вторичный рынок)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,        -- 'gpu' or 'cooler'
                item_id INTEGER NOT NULL,        -- id из user_gpus / user_coolers
                item_name TEXT NOT NULL,
                hash_rate REAL DEFAULT 0,
                cooling_power INTEGER DEFAULT 0,
                wear INTEGER DEFAULT 100,
                price INTEGER NOT NULL,
                is_crafted INTEGER DEFAULT 0,
                listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Таблица куллеров пользователя
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_coolers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                cooler_key TEXT,
                name TEXT,
                cooling_power INTEGER,
                wear INTEGER DEFAULT 100,
                is_installed INTEGER DEFAULT 0,
                rig_id INTEGER DEFAULT NULL,
                slot_index INTEGER DEFAULT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица ASIC-майнеров пользователя
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_asics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                asic_key TEXT,
                name TEXT,
                hash_rate REAL,
                wear INTEGER DEFAULT 100,
                is_working INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица GPU-ригов пользователя
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_rigs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                rig_key TEXT,
                name TEXT,
                gpu_slots INTEGER,
                cooler_slots INTEGER,
                gpu_installed TEXT DEFAULT '[]',
                coolers_installed TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица магазина видеокарт
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_gpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gpu_key TEXT UNIQUE,
                name TEXT,
                hash_rate REAL,
                price INTEGER,
                stock INTEGER,
                power INTEGER,
                memory INTEGER,
                release_year INTEGER,
                description TEXT
            )
        ''')
        
        # Таблица магазина куллеров
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_coolers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cooler_key TEXT UNIQUE,
                name TEXT,
                price INTEGER,
                stock INTEGER,
                cooling_power INTEGER,
                noise_level INTEGER,
                power_consumption INTEGER,
                wear_reduction INTEGER,
                description TEXT
            )
        ''')
        
        # Таблица магазина ASIC
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_asics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asic_key TEXT UNIQUE,
                name TEXT,
                hash_rate REAL,
                price INTEGER,
                stock INTEGER,
                power_consumption INTEGER,
                wear_rate INTEGER,
                noise_level INTEGER,
                description TEXT
            )
        ''')
        
        # Таблица магазина ригов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_rigs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rig_key TEXT UNIQUE,
                name TEXT,
                price INTEGER,
                stock INTEGER,
                gpu_slots INTEGER,
                cooler_slots INTEGER,
                max_power INTEGER,
                size TEXT,
                description TEXT
            )
        ''')
        
        # Таблица фотографий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS gpu_photos (
                gpu_key TEXT PRIMARY KEY,
                photo_id TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS cooler_photos (
                cooler_key TEXT PRIMARY KEY,
                photo_id TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS asic_photos (
                asic_key TEXT PRIMARY KEY,
                photo_id TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS rig_photos (
                rig_key TEXT PRIMARY KEY,
                photo_id TEXT
            )
        ''')
        
        # Таблица коробок
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
        
        # Таблица компонентов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                component_name TEXT,
                amount INTEGER DEFAULT 0,
                UNIQUE(user_id, component_name)
            )
        ''')
        
        # Таблица статистики
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_cards_sold INTEGER DEFAULT 0,
                total_gems_earned REAL DEFAULT 0,
                total_mining_actions INTEGER DEFAULT 0,
                total_boxes_opened INTEGER DEFAULT 0,
                total_coolers_sold INTEGER DEFAULT 0,
                total_asics_sold INTEGER DEFAULT 0,
                total_rigs_sold INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица событий
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
        
        # Таблица логов админов
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
        
        # Таблица автопополнения
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_restock_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_restock TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица анкет игроков
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                birthday TEXT DEFAULT NULL,
                gender TEXT DEFAULT NULL,
                about TEXT DEFAULT NULL,
                city TEXT DEFAULT NULL,
                show_birthday INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица чеков и счётов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                creator_id INTEGER,
                target_username TEXT DEFAULT NULL,
                amount REAL,
                activations_left INTEGER,
                activations_total INTEGER,
                check_type TEXT DEFAULT 'check',
                comment TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES users (creator_id)
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS check_activations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER,
                user_id INTEGER,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (check_id) REFERENCES checks (id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Таблица переводов тон
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                amount REAL,
                comment TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users (from_user_id),
                FOREIGN KEY (to_user_id) REFERENCES users (to_user_id)
            )
        ''')

        # Таблица фото профиля
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profile_photos (
                user_id INTEGER PRIMARY KEY,
                photo_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Таблица ежедневных бонусов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_bonus (
                user_id INTEGER PRIMARY KEY,
                last_bonus DATE,
                streak INTEGER DEFAULT 0,
                total_bonus INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Индексы для ускорения запросов
        for _idx in [
            'CREATE INDEX IF NOT EXISTS idx_gpus_user ON user_gpus(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_coolers_user ON user_coolers(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_asics_user ON user_asics(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_rigs_user ON user_rigs(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_market_active ON market_listings(is_active,item_type)',
            'CREATE INDEX IF NOT EXISTS idx_events_user ON events_log(user_id)',
        ]:
            try:
                self.cursor.execute(_idx)
            except Exception:
                pass
        # Миграция: промокоды на ник
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS nick_promos "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
            "code TEXT UNIQUE, used INTEGER DEFAULT 0, used_at TIMESTAMP)"
        )
        # Миграция: таблица заданий
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS user_quests '
            '(user_id INTEGER PRIMARY KEY, quest_data TEXT DEFAULT \'{}\')'
        )
        # Миграция: колонки системы усталости (anti-autoclicker)
        for _col, _td in [
            ('fatigue_count', 'INTEGER DEFAULT 0'),
            ('fatigue_reset_at', 'TIMESTAMP DEFAULT NULL'),
            ('daily_mines', 'INTEGER DEFAULT 0'),
            ('daily_mines_date', 'DATE DEFAULT NULL'),
        ]:
            try:
                self.cursor.execute(f'ALTER TABLE users ADD COLUMN {_col} {_td}')
                self.conn.commit()
            except Exception:
                pass  # колонка уже существует
        # Миграция: баланс звёзд
        try:
            self.cursor.execute('ALTER TABLE users ADD COLUMN stars_balance INTEGER DEFAULT 0')
            self.conn.commit()
        except Exception:
            pass
        # Восстанавливаем все сломанные асики (они больше не ломаются)
        try:
            self.cursor.execute('UPDATE user_asics SET is_working=1 WHERE is_working=0')
            self.conn.commit()
        except Exception:
            pass
        self.conn.commit()
        self.init_shop()

    def init_shop(self):
        """Заполнение магазина товарами из конфигов"""
        
        # Видеокарты
        self.cursor.execute("SELECT COUNT(*) FROM shop_gpus")
        if self.cursor.fetchone()[0] == 0:
            for gpu_key, gpu_data in GPU_CARDS.items():
                self.cursor.execute('''
                    INSERT INTO shop_gpus 
                    (gpu_key, name, hash_rate, price, stock, power, memory, release_year, description) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    gpu_key,
                    gpu_data['name'],
                    gpu_data['hash_rate'],
                    gpu_data['price'],
                    gpu_data['stock'],
                    gpu_data['power'],
                    gpu_data['memory'],
                    gpu_data['release_year'],
                    gpu_data['description']
                ))
        
        # Куллеры
        self.cursor.execute("SELECT COUNT(*) FROM shop_coolers")
        if self.cursor.fetchone()[0] == 0:
            for cooler_key, cooler_data in COOLERS.items():
                self.cursor.execute('''
                    INSERT INTO shop_coolers 
                    (cooler_key, name, price, stock, cooling_power, noise_level, power_consumption, wear_reduction, description) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    cooler_key,
                    cooler_data['name'],
                    cooler_data['price'],
                    cooler_data['stock'],
                    cooler_data['cooling_power'],
                    cooler_data['noise_level'],
                    cooler_data['power_consumption'],
                    cooler_data['wear_reduction'],
                    cooler_data['description']
                ))
        
        # ASIC-майнеры
        self.cursor.execute("SELECT COUNT(*) FROM shop_asics")
        if self.cursor.fetchone()[0] == 0:
            for asic_key, asic_data in ASICS.items():
                self.cursor.execute('''
                    INSERT INTO shop_asics 
                    (asic_key, name, hash_rate, price, stock, power_consumption, wear_rate, noise_level, description) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    asic_key,
                    asic_data['name'],
                    asic_data['hash_rate'],
                    asic_data['price'],
                    asic_data['stock'],
                    asic_data['power_consumption'],
                    asic_data['wear_rate'],
                    asic_data['noise_level'],
                    asic_data['description']
                ))
        
        # GPU-риги
        self.cursor.execute("SELECT COUNT(*) FROM shop_rigs")
        if self.cursor.fetchone()[0] == 0:
            for rig_key, rig_data in GPU_RIGS.items():
                self.cursor.execute('''
                    INSERT INTO shop_rigs 
                    (rig_key, name, price, stock, gpu_slots, cooler_slots, max_power, size, description) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    rig_key,
                    rig_data['name'],
                    rig_data['price'],
                    rig_data['stock'],
                    rig_data['gpu_slots'],
                    rig_data['cooler_slots'],
                    rig_data['max_power'],
                    rig_data['size'],
                    rig_data['description']
                ))
        
        # Статистика
        self.cursor.execute("SELECT COUNT(*) FROM stats")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO stats DEFAULT VALUES")
        
        self.conn.commit()
        print("✅ Магазин инициализирован")

    # ========== МЕТОДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    def add_user(self, user_id, username, first_name, referrer_id=None):
        """Добавляет нового пользователя"""
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if self.cursor.fetchone():
                return
            
            self.cursor.execute("SELECT COUNT(*) FROM users")
            count = self.cursor.fetchone()[0]
            custom_id = count + 1
            
            if username:
                default_nick = username
            else:
                random_num = random.randint(1000, 9999)
                default_nick = f"miner_{random_num}"
                while self.is_nickname_taken(default_nick):
                    random_num = random.randint(1000, 9999)
                    default_nick = f"miner_{random_num}"
            
            # Добавляем пользователя (без стартовой видеокарты)
            self.cursor.execute('''
                INSERT INTO users 
                (user_id, custom_id, username, first_name, gems, referrer_id, level, exp, boxes_count) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, custom_id, username, default_nick, config.START_BALANCE, referrer_id, 1, 0, 0))
            
            # Выдаем стартовый ASIC (вместо видеокарты)
            self.cursor.execute('''
                INSERT INTO user_asics 
                (user_id, asic_key, name, hash_rate, wear) 
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                'starter_asic',
                STARTER_ASIC['name'],
                STARTER_ASIC['hash_rate'],
                100
            ))
            
            # Обновляем хешрейт
            self.cursor.execute('''
                UPDATE users SET hash_rate = hash_rate + ? WHERE user_id = ?
            ''', (STARTER_ASIC['hash_rate'], user_id))
            
            if referrer_id:
                referrer = self.get_user(referrer_id)
                if referrer:
                    self.cursor.execute('''
                        UPDATE users SET 
                            gems = gems + ?,
                            exp = exp + ?,
                            referrals = referrals + 1 
                        WHERE user_id = ?
                    ''', (config.REFERRAL_BONUS, config.REFERRAL_EXP_BONUS, referrer_id))
                    
                    self.cursor.execute('''
                        UPDATE users SET 
                            gems = gems + ?,
                            exp = exp + ? 
                        WHERE user_id = ?
                    ''', (config.REFERRAL_BONUS_FOR_NEW, config.REFERRAL_EXP_FOR_NEW, user_id))
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding user: {e}")

    def get_user(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        return list(result) if result else None

    def get_stars(self, user_id: int) -> int:
        """Читает stars_balance напрямую из БД по имени колонки."""
        c = self.conn.cursor()
        c.execute("SELECT stars_balance FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


    def get_user_by_custom_id(self, custom_id):
        self.cursor.execute('SELECT * FROM users WHERE custom_id = ?', (custom_id,))
        result = self.cursor.fetchone()
        return list(result) if result else None

    def is_nickname_taken(self, nickname, exclude_user_id=None):
        if exclude_user_id:
            self.cursor.execute('SELECT user_id FROM users WHERE first_name = ? AND user_id != ?', (nickname, exclude_user_id))
        else:
            self.cursor.execute('SELECT user_id FROM users WHERE first_name = ?', (nickname,))
        return self.cursor.fetchone() is not None

    def change_nickname(self, user_id, new_nickname):
        if self.is_nickname_taken(new_nickname, user_id):
            return False, "🚫 Данный никнейм уже занят!"
        
        if len(new_nickname) > 32:
            return False, "❌ Ник не может быть длиннее 32 символов!"
        
        self.cursor.execute('UPDATE users SET first_name = ? WHERE user_id = ?', (new_nickname, user_id))
        self.conn.commit()
        return True, f"✅ Ник успешно изменен на {new_nickname}!"

    def check_ban_status(self, user_id):
        self.cursor.execute('SELECT banned, ban_until FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if not result or not result[0]:
            return False
        
        banned, ban_until = result
        
        if ban_until:
            ban_time = datetime.fromisoformat(ban_until)
            if datetime.now() > ban_time:
                self.unban_user(user_id)
                return False
        
        return banned

    # ========== МЕТОДЫ ДЛЯ ASIC-МАЙНЕРОВ ==========
    
    def get_user_asics(self, user_id):
        """Получает все ASIC-майнеры пользователя"""
        self.cursor.execute('SELECT * FROM user_asics WHERE user_id = ? ORDER BY id', (user_id,))
        return self.cursor.fetchall()

    def get_working_asics(self, user_id):
        """Получает все ASIC-майнеры пользователя (не ломаются)"""
        self.cursor.execute(
            'SELECT * FROM user_asics WHERE user_id = ?', (user_id,))
        return self.cursor.fetchall()

    def get_asic_by_id(self, asic_id):
        self.cursor.execute('SELECT * FROM user_asics WHERE id = ?', (asic_id,))
        return self.cursor.fetchone()

    # ========== МЕТОДЫ ДЛЯ GPU-РИГОВ ==========
    
    def get_user_rigs(self, user_id):
        self.cursor.execute('SELECT * FROM user_rigs WHERE user_id = ? ORDER BY id', (user_id,))
        return self.cursor.fetchall()

    def get_rig_by_id(self, rig_id):
        self.cursor.execute('SELECT * FROM user_rigs WHERE id = ?', (rig_id,))
        return self.cursor.fetchone()

    def create_rig(self, user_id, rig_key):
        rig_data = GPU_RIGS.get(rig_key)
        if not rig_data:
            return None
        
        self.cursor.execute('''
            INSERT INTO user_rigs 
            (user_id, rig_key, name, gpu_slots, cooler_slots) 
            VALUES (?, ?, ?, ?, ?)
        ''', (
            user_id,
            rig_key,
            rig_data['name'],
            rig_data['gpu_slots'],
            rig_data['cooler_slots']
        ))
        
        rig_id = self.cursor.lastrowid
        self.conn.commit()
        return rig_id

    def get_rig_gpus(self, rig_id):
        # Используем отдельный cursor чтобы не сбивать основной
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM user_rigs WHERE id = ?', (rig_id,))
        rig = cur.fetchone()
        if not rig:
            return []
        try:
            gpu_ids = json.loads(rig[6]) if rig[6] and rig[6] != '[]' else []
            gpu_ids = [g for g in gpu_ids if g is not None]
            if not gpu_ids:
                return []
            placeholders = ','.join(['?'] * len(gpu_ids))
            cur2 = self.conn.cursor()
            cur2.execute(f'SELECT * FROM user_gpus WHERE id IN ({placeholders})', gpu_ids)
            return cur2.fetchall()
        except Exception as e:
            logger.error(f"get_rig_gpus error: {e}")
            return []

    def get_rig_coolers(self, rig_id):
        # Используем отдельный cursor чтобы не сбивать основной
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM user_rigs WHERE id = ?', (rig_id,))
        rig = cur.fetchone()
        if not rig:
            return []
        try:
            cooler_ids = json.loads(rig[7]) if rig[7] and rig[7] != '[]' else []
            cooler_ids = [c for c in cooler_ids if c is not None]
            if not cooler_ids:
                return []
            placeholders = ','.join(['?'] * len(cooler_ids))
            cur2 = self.conn.cursor()
            cur2.execute(f'SELECT * FROM user_coolers WHERE id IN ({placeholders})', cooler_ids)
            return cur2.fetchall()
        except Exception as e:
            logger.error(f"get_rig_coolers error: {e}")
            return []

    def install_gpu(self, rig_id, gpu_id, slot_index):
        try:
            rig = self.get_rig_by_id(rig_id)
            if not rig:
                return False, "Риг не найден"
            
            self.cursor.execute('SELECT * FROM user_gpus WHERE id = ? AND is_installed = 0', (gpu_id,))
            gpu = self.cursor.fetchone()
            if not gpu:
                return False, "Видеокарта не найдена или уже установлена"
            
            gpu_installed = json.loads(rig[6]) if rig[6] and rig[6] != '[]' else []
            
            if slot_index < 0 or slot_index >= rig[4]:
                return False, "Неверный номер слота"
            
            while len(gpu_installed) <= slot_index:
                gpu_installed.append(None)
            
            if gpu_installed[slot_index] is not None:
                return False, "Слот уже занят"
            
            gpu_installed[slot_index] = gpu_id
            self.cursor.execute('UPDATE user_rigs SET gpu_installed = ? WHERE id = ?', 
                              (json.dumps(gpu_installed), rig_id))
            self.cursor.execute('UPDATE user_gpus SET is_installed = 1, rig_id = ?, slot_index = ? WHERE id = ?',
                              (rig_id, slot_index, gpu_id))
            
            self.conn.commit()
            
            # Пересчитываем общий хешрейт пользователя (ПОСЛЕ commit)
            new_hash = self.recalculate_user_hashrate(rig[1])
            
            return True, f"✅ Видеокарта установлена! Хешрейт: {new_hash:.1f} MH/s"
        except Exception as e:
            logger.error(f"Error installing GPU: {e}")
            return False, str(e)

    def remove_gpu(self, rig_id, slot_index):
        try:
            rig = self.get_rig_by_id(rig_id)
            if not rig:
                return False, "Риг не найден"
            
            gpu_installed = json.loads(rig[6]) if rig[6] and rig[6] != '[]' else []
            
            if slot_index >= len(gpu_installed) or gpu_installed[slot_index] is None:
                return False, "Слот пуст"
            
            gpu_id = gpu_installed[slot_index]
            gpu_installed[slot_index] = None
            
            self.cursor.execute('UPDATE user_rigs SET gpu_installed = ? WHERE id = ?', 
                              (json.dumps(gpu_installed), rig_id))
            self.cursor.execute('UPDATE user_gpus SET is_installed = 0, rig_id = NULL, slot_index = NULL WHERE id = ?',
                              (gpu_id,))
            
            self.conn.commit()
            
            new_hash = self.recalculate_user_hashrate(rig[1])
            
            return True, f"✅ Видеокарта извлечена! Хешрейт: {new_hash:.1f} MH/s"
        except Exception as e:
            logger.error(f"Error removing GPU: {e}")
            return False, str(e)

    def install_cooler(self, rig_id, cooler_id, slot_index):
        try:
            rig = self.get_rig_by_id(rig_id)
            if not rig:
                return False, "Риг не найден"
            
            self.cursor.execute('SELECT * FROM user_coolers WHERE id = ? AND is_installed = 0', (cooler_id,))
            cooler = self.cursor.fetchone()
            if not cooler:
                return False, "Куллер не найден или уже установлен"
            
            coolers_installed = json.loads(rig[7]) if rig[7] and rig[7] != '[]' else []
            
            if slot_index < 0 or slot_index >= rig[5]:
                return False, "Неверный номер слота"
            
            while len(coolers_installed) <= slot_index:
                coolers_installed.append(None)
            
            if coolers_installed[slot_index] is not None:
                return False, "Слот уже занят"
            
            coolers_installed[slot_index] = cooler_id
            self.cursor.execute('UPDATE user_rigs SET coolers_installed = ? WHERE id = ?', 
                              (json.dumps(coolers_installed), rig_id))
            self.cursor.execute('UPDATE user_coolers SET is_installed = 1, rig_id = ?, slot_index = ? WHERE id = ?',
                              (rig_id, slot_index, cooler_id))
            
            self.conn.commit()
            
            new_hash = self.recalculate_user_hashrate(rig[1])
            
            return True, f"✅ Куллер установлен! Хешрейт: {new_hash:.1f} MH/s"
        except Exception as e:
            logger.error(f"Error installing cooler: {e}")
            return False, str(e)

    def remove_cooler(self, rig_id, slot_index):
        try:
            rig = self.get_rig_by_id(rig_id)
            if not rig:
                return False, "Риг не найден"
            
            coolers_installed = json.loads(rig[7]) if rig[7] and rig[7] != '[]' else []
            
            if slot_index >= len(coolers_installed) or coolers_installed[slot_index] is None:
                return False, "Слот пуст"
            
            cooler_id = coolers_installed[slot_index]
            coolers_installed[slot_index] = None
            
            self.cursor.execute('UPDATE user_rigs SET coolers_installed = ? WHERE id = ?', 
                              (json.dumps(coolers_installed), rig_id))
            self.cursor.execute('UPDATE user_coolers SET is_installed = 0, rig_id = NULL, slot_index = NULL WHERE id = ?',
                              (cooler_id,))
            
            self.conn.commit()
            
            new_hash = self.recalculate_user_hashrate(rig[1])
            
            return True, f"✅ Куллер извлечен! Хешрейт: {new_hash:.1f} MH/s"
        except Exception as e:
            logger.error(f"Error removing cooler: {e}")
            return False, str(e)

    def update_rig_hashrate(self, rig_id, user_id=None):
        """Считает хешрейт рига. Если передан user_id — пересчитывает общий хешрейт."""
        try:
            total_hash = self._calc_rig_hash_sql(rig_id)
            if user_id:
                self.recalculate_user_hashrate(user_id)
            return total_hash
        except Exception as e:
            logger.error(f"Error updating rig hashrate: {e}")
            return 0

    def recalculate_user_hashrate(self, user_id):
        try:
            # Каждый запрос — отдельный cursor, чтобы не было конфликтов
            
            # 1. Хешрейт от ASIC (прямой SQL)
            c1 = self.conn.cursor()
            c1.execute(
                'SELECT COALESCE(SUM(hash_rate), 0) FROM user_asics WHERE user_id = ?',
                (user_id,)
            )
            asic_hash = float(c1.fetchone()[0] or 0)
            
            # 2. Хешрейт от ригов — полностью через SQL без вложенных вызовов
            c2 = self.conn.cursor()
            c2.execute('SELECT id FROM user_rigs WHERE user_id = ?', (user_id,))
            rig_ids = [r[0] for r in c2.fetchall()]
            
            rig_hash = 0.0
            for rig_id in rig_ids:
                rig_hash += self._calc_rig_hash_sql(rig_id)
            
            total_hash = asic_hash + rig_hash
            
            c3 = self.conn.cursor()
            c3.execute('UPDATE users SET hash_rate = ? WHERE user_id = ?', (total_hash, user_id))
            self.conn.commit()
            
            return total_hash
        except Exception as e:
            logger.error(f"Error recalculating hashrate: {e}")
            return 0

    def _calc_rig_hash_sql(self, rig_id):
        """Считает хешрейт рига через чистый SQL без конфликтов курсора"""
        try:
            # Получаем список gpu_ids из json поля
            c = self.conn.cursor()
            c.execute('SELECT gpu_installed, coolers_installed FROM user_rigs WHERE id = ?', (rig_id,))
            row = c.fetchone()
            if not row:
                return 0.0
            
            gpu_installed_raw, coolers_installed_raw = row
            
            # GPU хешрейт
            gpu_hash = 0.0
            try:
                gpu_ids = json.loads(gpu_installed_raw) if gpu_installed_raw and gpu_installed_raw != '[]' else []
                gpu_ids = [g for g in gpu_ids if g is not None]
                if gpu_ids:
                    placeholders = ','.join(['?'] * len(gpu_ids))
                    c2 = self.conn.cursor()
                    c2.execute(
                        f'SELECT COALESCE(SUM(hash_rate), 0) FROM user_gpus WHERE id IN ({placeholders})',
                        gpu_ids
                    )
                    gpu_hash = float(c2.fetchone()[0] or 0)
            except Exception as e:
                logger.error(f"GPU hash calc error: {e}")
            
            # Куллер бонус
            cooler_bonus = 0.0
            try:
                cooler_ids = json.loads(coolers_installed_raw) if coolers_installed_raw and coolers_installed_raw != '[]' else []
                cooler_ids = [c for c in cooler_ids if c is not None]
                if cooler_ids:
                    placeholders = ','.join(['?'] * len(cooler_ids))
                    c3 = self.conn.cursor()
                    c3.execute(
                        f'SELECT COALESCE(SUM(cooling_power), 0) FROM user_coolers WHERE id IN ({placeholders})',
                        cooler_ids
                    )
                    total_cooling = float(c3.fetchone()[0] or 0)
                    cooler_bonus = total_cooling * 0.1  # 0.1% за единицу мощности
            except Exception as e:
                logger.error(f"Cooler bonus calc error: {e}")
            
            total = gpu_hash + (gpu_hash * cooler_bonus / 100.0) if gpu_hash > 0 else 0.0
            return total
        except Exception as e:
            logger.error(f"_calc_rig_hash_sql error: {e}")
            return 0.0

    # ========== МЕТОДЫ ДЛЯ ВИДЕОКАРТ И КУЛЛЕРОВ ==========
    
    def get_user_gpus(self, user_id, include_installed=True):
        c = self.conn.cursor()
        if include_installed:
            c.execute('SELECT * FROM user_gpus WHERE user_id = ? ORDER BY id', (user_id,))
        else:
            c.execute('SELECT * FROM user_gpus WHERE user_id = ? AND is_installed = 0 ORDER BY id', (user_id,))
        return c.fetchall()

    def get_free_gpus(self, user_id):
        """Получает видеокарты, не установленные в риги и не на барахолке"""
        self.cursor.execute('''
            SELECT * FROM user_gpus 
            WHERE user_id = ? AND (is_installed = 0 OR is_installed IS NULL)
            ORDER BY id
        ''', (user_id,))
        return self.cursor.fetchall()

    def get_free_gpus_for_sale(self, user_id):
        """Только свободные карты (не в риге, не на барахолке)"""
        self.cursor.execute(
            'SELECT * FROM user_gpus WHERE user_id = ? AND is_installed = 0 ORDER BY id',
            (user_id,)
        )
        return self.cursor.fetchall()

    def get_free_coolers(self, user_id):
        """Получает куллеры, не установленные в риги и не на барахолке"""
        self.cursor.execute('''
            SELECT * FROM user_coolers 
            WHERE user_id = ? AND (rig_id IS NULL) AND (is_installed = 0 OR is_installed IS NULL)
            ORDER BY id
        ''', (user_id,))
        return self.cursor.fetchall()

    def get_free_coolers_for_sale(self, user_id):
        """Только свободные куллеры (не в риге, не на барахолке)"""
        self.cursor.execute(
            'SELECT * FROM user_coolers WHERE user_id = ? AND rig_id IS NULL AND (is_installed = 0 OR is_installed IS NULL) ORDER BY id',
            (user_id,)
        )
        return self.cursor.fetchall()

    def get_user_coolers(self, user_id, include_installed=True):
        c = self.conn.cursor()
        if include_installed:
            c.execute('SELECT * FROM user_coolers WHERE user_id = ? ORDER BY id', (user_id,))
        else:
            c.execute('SELECT * FROM user_coolers WHERE user_id = ? AND is_installed = 0 ORDER BY id', (user_id,))
        return c.fetchall()

    def get_gpu_by_id(self, gpu_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM user_gpus WHERE id = ?', (gpu_id,))
        return c.fetchone()

    def get_cooler_by_id(self, cooler_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM user_coolers WHERE id = ?', (cooler_id,))
        return c.fetchone()

    def repair_gpu(self, gpu_id):
        self.cursor.execute('UPDATE user_gpus SET wear = 100 WHERE id = ?', (gpu_id,))
        self.conn.commit()
        return True

    def repair_cooler(self, cooler_id):
        self.cursor.execute('UPDATE user_coolers SET wear = 100 WHERE id = ?', (cooler_id,))
        self.conn.commit()
        return True

    def repair_asic(self, asic_id):
        pass  # ASIC не ломаются
        return True

    # ========== МЕТОДЫ ДЛЯ МАГАЗИНА ==========
    
    def get_shop_gpus(self):
        self.cursor.execute('SELECT * FROM shop_gpus ORDER BY price')
        return self.cursor.fetchall()

    def get_shop_coolers(self):
        self.cursor.execute('SELECT * FROM shop_coolers ORDER BY price')
        return self.cursor.fetchall()

    def get_shop_asics(self):
        self.cursor.execute('SELECT * FROM shop_asics ORDER BY price')
        return self.cursor.fetchall()

    def get_shop_rigs(self):
        self.cursor.execute('SELECT * FROM shop_rigs ORDER BY price')
        return self.cursor.fetchall()

    def buy_gpu(self, user_id, gpu_key):
        try:
            self.cursor.execute('SELECT * FROM shop_gpus WHERE gpu_key = ?', (gpu_key,))
            gpu = self.cursor.fetchone()
            
            if not gpu or gpu[5] <= 0:
                return False, "Нет в наличии"
            
            user = self.get_user(user_id)
            if user[4] < gpu[4]:
                return False, f"Недостаточно средств! Нужно {gpu[4]} тон"
            
            self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (gpu[4], user_id))
            
            self.cursor.execute('''
                INSERT INTO user_gpus 
                (user_id, gpu_key, name, hash_rate, wear) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, gpu_key, gpu[2], gpu[3], 100))
            
            self.cursor.execute('UPDATE shop_gpus SET stock = stock - 1 WHERE gpu_key = ?', (gpu_key,))
            self.cursor.execute('UPDATE stats SET total_cards_sold = total_cards_sold + 1')
            
            self.conn.commit()
            return True, f"✅ Куплена видеокарта: {gpu[2]}"
        except Exception as e:
            logger.error(f"Error buying GPU: {e}")
            return False, str(e)

    def buy_cooler(self, user_id, cooler_key):
        try:
            self.cursor.execute('SELECT * FROM shop_coolers WHERE cooler_key = ?', (cooler_key,))
            cooler = self.cursor.fetchone()
            
            if not cooler or cooler[4] <= 0:
                return False, "Нет в наличии"
            
            user = self.get_user(user_id)
            if user[4] < cooler[3]:
                return False, f"Недостаточно средств! Нужно {cooler[3]} тон"
            
            self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (cooler[3], user_id))
            
            self.cursor.execute('''
                INSERT INTO user_coolers 
                (user_id, cooler_key, name, cooling_power, wear) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, cooler_key, cooler[2], cooler[5], 100))
            
            self.cursor.execute('UPDATE shop_coolers SET stock = stock - 1 WHERE cooler_key = ?', (cooler_key,))
            self.cursor.execute('UPDATE stats SET total_coolers_sold = total_coolers_sold + 1')
            
            self.conn.commit()
            return True, f"✅ Куплен куллер: {cooler[1]}"
        except Exception as e:
            logger.error(f"Error buying cooler: {e}")
            return False, str(e)

    def buy_asic(self, user_id, asic_key):
        try:
            self.cursor.execute('SELECT * FROM shop_asics WHERE asic_key = ?', (asic_key,))
            asic = self.cursor.fetchone()
            
            if not asic or asic[5] <= 0:
                return False, "Нет в наличии"
            
            user = self.get_user(user_id)
            if user[4] < asic[4]:
                return False, f"Недостаточно средств! Нужно {asic[4]} тон"
            
            self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (asic[4], user_id))
            
            self.cursor.execute('''
                INSERT INTO user_asics 
                (user_id, asic_key, name, hash_rate, wear) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, asic_key, asic[2], asic[3], 100))
            
            self.cursor.execute('UPDATE users SET hash_rate = hash_rate + ? WHERE user_id = ?', (asic[3], user_id))
            
            self.cursor.execute('UPDATE shop_asics SET stock = stock - 1 WHERE asic_key = ?', (asic_key,))
            self.cursor.execute('UPDATE stats SET total_asics_sold = total_asics_sold + 1')
            
            self.conn.commit()
            return True, f"✅ Куплен ASIC: {asic[1]}"
        except Exception as e:
            logger.error(f"Error buying ASIC: {e}")
            return False, str(e)

    def buy_rig(self, user_id, rig_key):
        try:
            self.cursor.execute('SELECT * FROM shop_rigs WHERE rig_key = ?', (rig_key,))
            rig = self.cursor.fetchone()
            
            if not rig or rig[4] <= 0:
                return False, "Нет в наличии"
            
            user = self.get_user(user_id)
            if user[4] < rig[3]:
                return False, f"Недостаточно средств! Нужно {rig[3]} тон"
            
            self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (rig[3], user_id))
            
            self.cursor.execute('''
                INSERT INTO user_rigs 
                (user_id, rig_key, name, gpu_slots, cooler_slots) 
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id, 
                rig_key, 
                rig[1],  # name
                rig[5],  # gpu_slots
                rig[6]   # cooler_slots
            ))
            
            self.cursor.execute('UPDATE shop_rigs SET stock = stock - 1 WHERE rig_key = ?', (rig_key,))
            self.cursor.execute('UPDATE stats SET total_rigs_sold = total_rigs_sold + 1')
            
            self.conn.commit()
            return True, f"✅ Куплен риг: {rig[1]}"
        except Exception as e:
            logger.error(f"Error buying rig: {e}")
            return False, str(e)

    # ========== МЕТОДЫ ДЛЯ ФОТОГРАФИЙ ==========
    
    def set_gpu_photo(self, gpu_key, photo_id):
        self.cursor.execute('REPLACE INTO gpu_photos (gpu_key, photo_id) VALUES (?, ?)', (gpu_key, photo_id))
        self.conn.commit()

    def get_gpu_photo(self, gpu_key):
        self.cursor.execute('SELECT photo_id FROM gpu_photos WHERE gpu_key = ?', (gpu_key,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def set_cooler_photo(self, cooler_key, photo_id):
        self.cursor.execute('REPLACE INTO cooler_photos (cooler_key, photo_id) VALUES (?, ?)', (cooler_key, photo_id))
        self.conn.commit()

    def get_cooler_photo(self, cooler_key):
        self.cursor.execute('SELECT photo_id FROM cooler_photos WHERE cooler_key = ?', (cooler_key,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def set_asic_photo(self, asic_key, photo_id):
        self.cursor.execute('REPLACE INTO asic_photos (asic_key, photo_id) VALUES (?, ?)', (asic_key, photo_id))
        self.conn.commit()

    def get_asic_photo(self, asic_key):
        self.cursor.execute('SELECT photo_id FROM asic_photos WHERE asic_key = ?', (asic_key,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def set_rig_photo(self, rig_key, photo_id):
        self.cursor.execute('REPLACE INTO rig_photos (rig_key, photo_id) VALUES (?, ?)', (rig_key, photo_id))
        self.conn.commit()

    def get_rig_photo(self, rig_key):
        self.cursor.execute('SELECT photo_id FROM rig_photos WHERE rig_key = ?', (rig_key,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    # ========== МЕТОДЫ ДЛЯ ЧЕКОВ И СЧЁТОВ ==========

    def create_check(self, creator_id, amount, activations, target_username=None, comment=None, check_type='check'):
        """Создаёт чек или счёт"""
        try:
            user = self.get_user(creator_id)
            if not user:
                return False, "❌ Пользователь не найден"
            if amount <= 0:
                return False, "❌ Сумма должна быть больше нуля"
            if activations < 1:
                return False, "❌ Минимум 1 активация"
            total_cost = amount * activations
            if check_type == 'check' and user[4] < total_cost:
                return False, f"❌ Недостаточно тон! Нужно: {total_cost}, у тебя: {int(user[4])}"
            
            import uuid
            code = str(uuid.uuid4())[:8].upper()
            while True:
                self.cursor.execute('SELECT id FROM checks WHERE code = ?', (code,))
                if not self.cursor.fetchone():
                    break
                code = str(uuid.uuid4())[:8].upper()
            
            if check_type == 'check':
                self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (total_cost, creator_id))
            
            self.cursor.execute('''
                INSERT INTO checks (code, creator_id, target_username, amount, activations_left, activations_total, check_type, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (code, creator_id, target_username, amount, activations, activations, check_type, comment))
            self.conn.commit()
            return True, code
        except Exception as e:
            logger.error(f"Error creating check: {e}")
            return False, str(e)

    def activate_check(self, code, user_id):
        """Активирует чек"""
        try:
            self.cursor.execute('SELECT * FROM checks WHERE code = ? AND is_active = 1', (code.upper(),))
            check = self.cursor.fetchone()
            if not check:
                return False, "❌ Чек не найден или уже использован"
            
            check_id, code_, creator_id, target_username, amount, activations_left, activations_total, check_type, comment, is_active, created_at = check
            
            
            # Для чека — нельзя активировать дважды, для счёта — можно оплачивать сколько угодно раз
            if check_type != 'invoice':
                self.cursor.execute('SELECT id FROM check_activations WHERE check_id = ? AND user_id = ?', (check_id, user_id))
                if self.cursor.fetchone():
                    return False, "❌ Ты уже активировал этот чек!"
            
            # Проверяем target_username
            if target_username:
                activator = self.get_user(user_id)
                if not activator:
                    return False, "❌ Пользователь не найден"
                username = activator[2] or ""
                nick = activator[3] or ""
                if target_username.lstrip('@').lower() not in [username.lower(), nick.lower()]:
                    return False, f"❌ Этот чек предназначен для @{target_username}"
            
            if check_type == 'invoice':
                # Счёт — пользователь платит создателю
                payer = self.get_user(user_id)
                if not payer or payer[4] < amount:
                    return False, f"❌ Недостаточно тон! Нужно: {int(amount)}"
                self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (amount, user_id))
                self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (amount, creator_id))
            else:
                # Чек — пользователь получает тоны
                self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (amount, user_id))
            
            self.cursor.execute('''
                INSERT INTO check_activations (check_id, user_id) VALUES (?, ?)
            ''', (check_id, user_id))
            
            new_activations = activations_left - 1
            if new_activations <= 0:
                self.cursor.execute('UPDATE checks SET activations_left = 0, is_active = 0 WHERE id = ?', (check_id,))
            else:
                self.cursor.execute('UPDATE checks SET activations_left = ? WHERE id = ?', (new_activations, check_id))
            
            self.conn.commit()
            creator = self.get_user(creator_id)
            return True, {"amount": amount, "creator": creator, "check_type": check_type, "activations_left": new_activations}
        except Exception as e:
            logger.error(f"Error activating check: {e}")
            return False, str(e)

    def get_user_checks(self, user_id, limit=10):
        """Получает чеки созданные пользователем"""
        self.cursor.execute('''
            SELECT * FROM checks WHERE creator_id = ? ORDER BY created_at DESC LIMIT ?
        ''', (user_id, limit))
        return self.cursor.fetchall()

    def get_check_by_code(self, code):
        self.cursor.execute('SELECT * FROM checks WHERE code = ?', (code.upper(),))
        return self.cursor.fetchone()

    def cancel_check(self, check_id, user_id):
        """Отменяет чек и возвращает тоны"""
        try:
            self.cursor.execute('SELECT * FROM checks WHERE id = ? AND creator_id = ? AND is_active = 1', (check_id, user_id))
            check = self.cursor.fetchone()
            if not check:
                return False, "❌ Чек не найден или уже использован"
            check_id_, code, creator_id, target_username, amount, activations_left, activations_total, check_type, comment, is_active, created_at = check
            
            if check_type == 'check':
                refund = amount * activations_left
                self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (refund, user_id))
            
            self.cursor.execute('UPDATE checks SET is_active = 0 WHERE id = ?', (check_id,))
            self.conn.commit()
            return True, amount * activations_left if check_type == 'check' else 0
        except Exception as e:
            logger.error(f"Error cancelling check: {e}")
            return False, str(e)

    # ========== МЕТОДЫ ДЛЯ ПЕРЕВОДОВ ==========

    def transfer_tons(self, from_user_id, to_user_id, amount, comment=None):
        """Переводит тоны от одного игрока другому"""
        try:
            sender = self.get_user(from_user_id)
            receiver = self.get_user(to_user_id)

            if not sender:
                return False, "❌ Отправитель не найден"
            if not receiver:
                return False, "❌ Получатель не найден"
            if from_user_id == to_user_id:
                return False, "❌ Нельзя переводить самому себе!"
            if amount <= 0:
                return False, "❌ Сумма должна быть больше нуля"
            if sender[4] < amount:
                return False, f"❌ Недостаточно тон! У тебя: {int(sender[4])} тон"

            self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (amount, from_user_id))
            self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (amount, to_user_id))
            self.cursor.execute('''
                INSERT INTO transfers (from_user_id, to_user_id, amount, comment)
                VALUES (?, ?, ?, ?)
            ''', (from_user_id, to_user_id, amount, comment))
            self.conn.commit()
            return True, receiver
        except Exception as e:
            logger.error(f"Error in transfer_tons: {e}")
            return False, str(e)

    def get_user_transfers(self, user_id, limit=10):
        """Получает историю переводов пользователя (входящие и исходящие)"""
        self.cursor.execute('''
            SELECT t.id, t.from_user_id, t.to_user_id, t.amount, t.comment, t.created_at,
                   u_from.first_name as from_name, u_to.first_name as to_name
            FROM transfers t
            LEFT JOIN users u_from ON t.from_user_id = u_from.user_id
            LEFT JOIN users u_to ON t.to_user_id = u_to.user_id
            WHERE t.from_user_id = ? OR t.to_user_id = ?
            ORDER BY t.created_at DESC
            LIMIT ?
        ''', (user_id, user_id, limit))
        return self.cursor.fetchall()

    # ========== МЕТОДЫ ДЛЯ ФОТО ПРОФИЛЯ ==========

    def set_profile_photo(self, user_id, photo_id):
        """Сохраняет фото профиля"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO user_profile_photos (user_id, photo_id, updated_at)
            VALUES (?, ?, ?)
        ''', (user_id, photo_id, datetime.now()))
        self.conn.commit()

    def get_profile_photo(self, user_id):
        """Получает фото профиля"""
        self.cursor.execute('SELECT photo_id FROM user_profile_photos WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def delete_profile_photo(self, user_id):
        """Удаляет фото профиля"""
        self.cursor.execute('DELETE FROM user_profile_photos WHERE user_id = ?', (user_id,))
        self.conn.commit()

    # ========== МЕТОДЫ ДЛЯ МАЙНИНГА ==========
    

    # ========== СИСТЕМА УСТАЛОСТИ (anti-autoclicker) ==========

    def get_fatigue_info(self, user_id: int):
        """
        Возвращает (multiplier, count, secs_to_reset).
        Пороги: 0-4 = 100%, 5-14 = 50%, 15-29 = 20%, 30+ = 8%.
        Сброс каждые 8 часов.
        """
        RESET_HOURS = 8
        TIERS = [(5, 1.0), (15, 0.50), (30, 0.20), (9999, 0.08)]
        c = self.conn.cursor()
        c.execute('SELECT fatigue_count, fatigue_reset_at FROM users WHERE user_id=?', (user_id,))
        row = c.fetchone()
        if not row:
            return 1.0, 0, 0
        count = row[0] or 0
        reset_at = row[1]
        now = datetime.now()
        if reset_at:
            try:
                rt = datetime.fromisoformat(reset_at)
                if now >= rt:
                    nxt = now + timedelta(hours=RESET_HOURS)
                    self.cursor.execute(
                        'UPDATE users SET fatigue_count=0, fatigue_reset_at=? WHERE user_id=?',
                        (nxt.isoformat(), user_id))
                    self.conn.commit()
                    count = 0
                    reset_at = nxt.isoformat()
            except Exception:
                count = 0
        else:
            nxt = now + timedelta(hours=RESET_HOURS)
            self.cursor.execute(
                'UPDATE users SET fatigue_reset_at=? WHERE user_id=?',
                (nxt.isoformat(), user_id))
            self.conn.commit()
            reset_at = nxt.isoformat()
        mult = 0.08
        for thr, m in TIERS:
            if count < thr:
                mult = m
                break
        secs = 0
        if reset_at:
            try:
                secs = max(0, int((datetime.fromisoformat(reset_at) - now).total_seconds()))
            except Exception:
                pass
        return mult, count, secs

    def bump_fatigue(self, user_id: int):
        """Увеличить усталость на 1 и обновить daily_mines."""
        self.cursor.execute(
            'UPDATE users SET fatigue_count=COALESCE(fatigue_count,0)+1 WHERE user_id=?',
            (user_id,))
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            'SELECT daily_mines_date FROM users WHERE user_id=?', (user_id,))
        row2 = self.cursor.fetchone()
        if row2 and row2[0] == today:
            self.cursor.execute(
                'UPDATE users SET daily_mines=daily_mines+1 WHERE user_id=?', (user_id,))
        else:
            self.cursor.execute(
                'UPDATE users SET daily_mines=1, daily_mines_date=? WHERE user_id=?',
                (today, user_id))
        self.conn.commit()

    def mine(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return False, "❌ Пользователь не найден"
        
        if user[8]:
            return False, "⛔ Вы забанены!"
        
        if user[13]:
            try:
                last_time = datetime.fromisoformat(user[13])
                time_diff = datetime.now() - last_time
                if time_diff.total_seconds() < config.MINING_COOLDOWN:
                    remaining = config.MINING_COOLDOWN - time_diff.total_seconds()
                    rem_m = int(remaining // 60)
                    rem_s = int(remaining % 60)
                    time_str = f"{rem_m:02d}:{rem_s:02d}"
                    return False, (
                        f"⏳ <b>Рано!</b>\n\n"
                        f"Следующий майнинг через: <b>{time_str}</b>"
                    )
            except Exception as e:
                logger.error(f"Ошибка парсинга времени: {e}")
        
        # Получаем работающие ASIC
        asics = self.get_working_asics(user_id)
        asic_hash = 0
        if asics:
            for asic in asics:
                try:
                    if len(asic) > 4 and asic[4] is not None:
                        asic_hash += float(asic[4])
                except (ValueError, TypeError):
                    continue
        
        # Получаем хешрейт от ригов
        rigs = self.get_user_rigs(user_id)
        rig_hash = 0
        for rig in rigs:
            rig_hash += self.update_rig_hashrate(rig[0])
        
        total_hash = asic_hash + rig_hash
        if total_hash == 0:
            total_hash = 5  # Минимальный хешрейт для старта
        
        # ── Система усталости (diminishing returns) ──
        _fatigue_mult, _fatigue_cnt, _fatigue_secs = self.get_fatigue_info(user_id)
        self.bump_fatigue(user_id)
        raw_ton = int(total_hash * config.HASHRATE_MULTIPLIER) + config.BASE_REWARD
        base_ton = max(1, int(raw_ton * _fatigue_mult))
        exp_gain = config.EXP_FROM_MINING_BASE + int(total_hash * config.EXP_FROM_HASHRATE)

        wear_per_use = config.WEAR_PER_USE
        
        # ASIC не изнашиваются
        
        # Износ для GPU в ригах
        if rigs:
            for rig in rigs:
                gpus = self.get_rig_gpus(rig[0])
                coolers = self.get_rig_coolers(rig[0])
                
                wear_reduction = 0
                if coolers:
                    for cooler in coolers:
                        try:
                            if len(cooler) > 4 and cooler[4] is not None:
                                wear_reduction += float(cooler[4]) * 0.2
                        except (ValueError, TypeError):
                            continue
                
                effective_wear = max(1, wear_per_use - int(wear_reduction))
                
                if gpus:
                    for gpu in gpus:
                        try:
                            # Крафтовые GPU изнашиваются вдвое медленнее
                            gpu_wear_mult = float(gpu[10]) if len(gpu) > 10 and gpu[10] is not None else 1.0
                            gpu_effective_wear = max(1, int(effective_wear * gpu_wear_mult))
                            new_wear = gpu[5] - gpu_effective_wear
                            if new_wear <= 0:
                                self.cursor.execute('UPDATE user_gpus SET wear = 0 WHERE id = ?', (gpu[0],))
                            else:
                                self.cursor.execute('UPDATE user_gpus SET wear = ? WHERE id = ?', (new_wear, gpu[0]))
                        except (ValueError, TypeError):
                            continue
        
        # Шанс на коробку
        box_reward = None
        if random.random() < 0.1:
            box_id = self.add_box(user_id)
            self.cursor.execute('UPDATE users SET boxes_count = boxes_count + 1 WHERE user_id = ?', (user_id,))
            box_reward = "📦 Вы получили коробку с лутом!"
        
        # Обновляем данные пользователя
        self.cursor.execute('''
            UPDATE users SET 
                gems = gems + ?,
                total_mined = total_mined + ?,
                last_mining = ?,
                exp = exp + ?
            WHERE user_id = ?
        ''', (base_ton, base_ton, datetime.now(), exp_gain, user_id))
        
        self.conn.commit()
        
        # Пересчитываем общий хешрейт
        self.recalculate_user_hashrate(user_id)
        
        # Формируем ответ
        # Строка усталости
        if _fatigue_mult >= 1.0:
            _f_line = ""
        else:
            _fh = _fatigue_secs // 3600
            _fm = (_fatigue_secs % 3600) // 60
            _pct = int((1 - _fatigue_mult) * 100)
            _ico = "😴" if _fatigue_mult >= 0.5 else ("😫" if _fatigue_mult >= 0.2 else "💀")
            _f_line = f"\n{_ico} <i>Усталость -{_pct}% (сброс через {_fh}ч {_fm}м)</i>"

        result = f"<b>⛏ Успешный майнинг!</b>\n\n"
        result += f"<blockquote>"
        result += f"Твой HM/s ›› {total_hash:.0f}\n"
        result += f"Тон ›› {base_ton}"
        if _fatigue_mult < 1.0:
            result += f" (было бы {raw_ton})"
        result += f"\nОпыт ›› {exp_gain}"
        result += f"</blockquote>\n\n"

        if box_reward:
            result += f"{box_reward}\n"

        result += _f_line

        # Считаем реальный оставшийся КД
        _next_mine = datetime.now() + timedelta(seconds=config.MINING_COOLDOWN)
        _rem = config.MINING_COOLDOWN
        _rem_m = int(_rem // 60)
        _rem_s = int(_rem % 60)
        result += f"\n⏳ <b>Следующий майнинг</b> через {_rem_m:02d}:{_rem_s:02d}"
        
        return True, result, bool(box_reward)

    # ========== МЕТОДЫ ДЛЯ КОРОБОК ==========
    
    def add_box(self, user_id, box_type='common'):
        self.cursor.execute('''
            INSERT INTO boxes (user_id, box_type) VALUES (?, ?)
        ''', (user_id, box_type))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_user_boxes(self, user_id, unopened_only=True):
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
        self.cursor.execute('SELECT user_id, box_type FROM boxes WHERE id = ? AND opened = 0', (box_id,))
        box = self.cursor.fetchone()
        if not box:
            return None, "Коробка не найдена или уже открыта"
        user_id, box_type = box

        # Базовые награды
        ton_reward = random.randint(50, 200)
        exp_reward = random.randint(20, 100)
        self.cursor.execute('UPDATE users SET gems=gems+?, exp=exp+? WHERE user_id=?',
                            (ton_reward, exp_reward, user_id))

        # Компоненты — суммируем одинаковые
        comp_summary = {}
        if random.random() < 0.3:
            components = ["Чип", "Вентилятор", "Кабель", "Радиатор", "Микросхема"]
            comp = random.choice(components)
            amt = random.randint(1, 3)
            self.add_component(user_id, "🧩 " + comp, amt)
            comp_summary["🧩 " + comp] = comp_summary.get("🧩 " + comp, 0) + amt

        # Куллер (5%)
        cooler_drop = None
        if random.random() < 0.05:
            cooler_key = random.choice(list(COOLERS.keys()))
            cd = COOLERS[cooler_key]
            self.cursor.execute(
                "INSERT INTO user_coolers (user_id,cooler_key,name,cooling_power,wear) VALUES (?,?,?,?,?)",
                (user_id, cooler_key, cd["name"], cd["cooling_power"], 100))
            cooler_drop = cd["name"]

        # Промокод на ник (1%) — вместо привилегии
        promo_drop = None
        if random.random() < 0.01:
            import string
            code = "NICK-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            self.cursor.execute(
                "INSERT OR IGNORE INTO nick_promos (user_id, code, used) VALUES (?,?,0)",
                (user_id, code))
            promo_drop = code

        self.cursor.execute("UPDATE boxes SET opened=1, opened_at=? WHERE id=?",
                            (datetime.now(), box_id))
        self.cursor.execute("UPDATE users SET boxes_count=boxes_count-1 WHERE user_id=?", (user_id,))
        self.cursor.execute("UPDATE stats SET total_boxes_opened=total_boxes_opened+1")
        self.conn.commit()

        # Формируем текст — объединяем одинаковое
        lines = []
        lines.append(f"💰 {ton_reward} тон")
        lines.append(f"✨ {exp_reward} опыта")
        for comp, cnt in comp_summary.items():
            lines.append(f"{comp} ×{cnt}" if cnt > 1 else comp)
        if cooler_drop:
            lines.append(f"💨 {cooler_drop}")
        if promo_drop:
            lines.append(f"🎟 Промокод на ник: <code>{promo_drop}</code>")
        reward_text = "🎁 <b>В коробке:</b>\n" + "\n".join(f"• {l}" for l in lines)
        return True, reward_text

    def add_component(self, user_id, component_name, amount):
        self.cursor.execute('''
            INSERT INTO components (user_id, component_name, amount) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, component_name) DO UPDATE SET amount = amount + ?
        ''', (user_id, component_name, amount, amount))
        self.conn.commit()

    def get_user_components(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT component_name, amount FROM components WHERE user_id = ?', (user_id,))
        return c.fetchall()

    # ========== МЕТОДЫ ДЛЯ СТАТИСТИКИ ==========
    
    def get_stats(self):
        def q(sql, params=()):
            c = self.conn.cursor()
            c.execute(sql, params)
            return c.fetchone()

        day_ago = datetime.now() - timedelta(days=1)
        hour_ago = datetime.now() - timedelta(hours=1)

        stats          = q('SELECT * FROM stats')
        total_users    = q('SELECT COUNT(*) FROM users')[0]
        online_24h     = q('SELECT COUNT(*) FROM users WHERE last_mining > ?', (day_ago,))[0]
        current_online = q('SELECT COUNT(*) FROM users WHERE last_mining > ?', (hour_ago,))[0]
        total_ton      = q('SELECT COALESCE(SUM(gems),0) FROM users')[0]
        total_hash     = q('SELECT COALESCE(SUM(hash_rate),0) FROM users')[0]
        gpu_stock      = q('SELECT COALESCE(SUM(stock),0) FROM shop_gpus')[0]
        cooler_stock   = q('SELECT COALESCE(SUM(stock),0) FROM shop_coolers')[0]
        asic_stock     = q('SELECT COALESCE(SUM(stock),0) FROM shop_asics')[0]
        rig_stock      = q('SELECT COALESCE(SUM(stock),0) FROM shop_rigs')[0]

        return {
            'total_users':         total_users,
            'online_24h':          online_24h,
            'current_online':      current_online,
            'total_ton':           total_ton,
            'avg_ton':             total_ton / total_users if total_users > 0 else 0,
            'total_hash':          total_hash,
            'avg_hash':            total_hash / total_users if total_users > 0 else 0,
            'total_stock':         gpu_stock + cooler_stock + asic_stock + rig_stock,
            'gpu_stock':           gpu_stock,
            'cooler_stock':        cooler_stock,
            'asic_stock':          asic_stock,
            'rig_stock':           rig_stock,
            'total_cards_sold':    stats[1] if stats else 0,
            'total_gems_earned':   stats[2] if stats else 0,
            'total_mining_actions':stats[3] if stats else 0,
            'total_boxes_opened':  stats[4] if stats and len(stats) > 4 else 0,
            'total_coolers_sold':  stats[5] if stats and len(stats) > 5 else 0,
            'total_asics_sold':    stats[6] if stats and len(stats) > 6 else 0,
            'total_rigs_sold':     stats[7] if stats and len(stats) > 7 else 0,
        }

    # ========== МЕТОДЫ ДЛЯ ТОПОВ ==========
    
    def get_top(self, category):
        """Получает топ пользователей"""
        try:
            if category == "gems":
                self.cursor.execute('''
                    SELECT user_id, username, first_name, gems 
                    FROM users 
                    WHERE gems > 0
                    ORDER BY gems DESC LIMIT 10
                ''')
            elif category == "level":
                self.cursor.execute('''
                    SELECT user_id, username, first_name, level, exp 
                    FROM users 
                    ORDER BY level DESC, exp DESC LIMIT 10
                ''')
            elif category == "hash":
                self.cursor.execute('''
                    SELECT user_id, username, first_name, hash_rate 
                    FROM users 
                    WHERE hash_rate > 0
                    ORDER BY hash_rate DESC LIMIT 10
                ''')
            elif category == "referrals":
                self.cursor.execute('''
                    SELECT user_id, username, first_name, referrals 
                    FROM users 
                    WHERE referrals > 0
                    ORDER BY referrals DESC LIMIT 10
                ''')
            else:
                return []
            
            results = self.cursor.fetchall()
            return results
        except Exception as e:
            logger.error(f"Error in get_top: {e}")
            return []

    # ========== МЕТОДЫ ДЛЯ ПРИВИЛЕГИЙ ==========
    
    def get_user_privilege(self, user_id):
        self.cursor.execute('SELECT privilege, privilege_until FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if not result:
            return "player", None
        
        privilege, privilege_until = result
        
        if privilege is None:
            privilege = "player"
        
        if privilege_until and privilege != "player":
            try:
                if isinstance(privilege_until, str):
                    until = datetime.fromisoformat(privilege_until)
                    if datetime.now() > until:
                        self.cursor.execute('UPDATE users SET privilege = "player", privilege_until = NULL WHERE user_id = ?', (user_id,))
                        self.conn.commit()
                        return "player", None
            except:
                pass
        
        return privilege, privilege_until

    def get_privilege_bonuses(self, privilege_name):
        if privilege_name is None:
            privilege_name = "player"
        return config.PRIVILEGES.get(privilege_name, config.PRIVILEGES["player"])["bonuses"]

    def apply_privilege(self, user_id, privilege_name, days):
        if privilege_name not in config.PRIVILEGES:
            return False, "Привилегия не найдена"
        
        privilege_data = config.PRIVILEGES[privilege_name]
        price = privilege_data["price"]
        
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


    def get_user_profile(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if not row:
            self.conn.cursor().execute(
                'INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,)
            )
            self.conn.commit()
            c2 = self.conn.cursor()
            c2.execute('SELECT * FROM user_profiles WHERE user_id = ?', (user_id,))
            row = c2.fetchone()
        return row  # user_id, birthday, gender, about, city, show_birthday

    def update_user_profile(self, user_id, field, value):
        allowed = {'birthday', 'gender', 'about', 'city', 'show_birthday'}
        if field not in allowed:
            return False
        c = self.conn.cursor()
        c.execute(f'INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,))
        c.execute(f'UPDATE user_profiles SET {field} = ? WHERE user_id = ?', (value, user_id))
        self.conn.commit()
        return True


    def get_user_referrals(self, user_id, limit=50):
        """Получить список рефералов пользователя"""
        c = self.conn.cursor()
        c.execute("""
            SELECT user_id, first_name, username, level, gems, created_at
            FROM users WHERE referrer_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (user_id, limit))
        return c.fetchall()

    # ========== АДМИН МЕТОДЫ ==========
    
    def add_gems(self, user_id, amount, admin_id=None):
        self.cursor.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (amount, user_id))
        if admin_id:
            self.log_admin_action(admin_id, 'add_gems', user_id, f'+{amount} тон')
        self.conn.commit()

    def get_level_up_cost(self, current_level):
        """Возвращает (ton_cost, exp_cost, error). error=None если всё ок."""
        if current_level >= config.MAX_LEVEL:
            return None, None, "Максимальный уровень"
        # Кастомная стоимость
        custom = config.CUSTOM_LEVEL_COSTS.get(current_level + 1)
        if custom:
            return custom["ton"], custom["exp"], None
        # Базовая формула: base * multiplier^(level-1)
        ton = int(config.LEVEL_UP_BASE_TON * (config.LEVEL_COST_MULTIPLIER ** (current_level - 1)))
        exp = int(config.LEVEL_UP_BASE_EXP * (config.LEVEL_COST_MULTIPLIER ** (current_level - 1)))
        return ton, exp, None

    def level_up(self, user_id):
        """Повысить уровень. Возвращает (True, data) или (False, msg)."""
        user = self.get_user(user_id)
        if not user:
            return False, "Профиль не найден"
        current_level = user[10]
        current_exp   = user[11]
        current_ton   = int(user[4])
        ton_cost, exp_cost, error = self.get_level_up_cost(current_level)
        if error:
            return False, error
        if current_ton < ton_cost:
            return False, f"Недостаточно тон! Нужно {ton_cost}, у тебя {current_ton}"
        if current_exp < exp_cost:
            return False, f"Недостаточно опыта! Нужно {exp_cost}, у тебя {current_exp}"
        new_level = current_level + 1
        reward = config.LEVEL_REWARDS.get(new_level, {"ton": 0, "exp": 0, "bonus": "Нет награды"})
        self.cursor.execute(
            "UPDATE users SET level=?, gems=gems-?+?, exp=exp-?+? WHERE user_id=?",
            (new_level, ton_cost, reward["ton"], exp_cost, reward["exp"], user_id)
        )
        self.conn.commit()
        return True, {
            "old_level": current_level, "new_level": new_level,
            "ton_cost": ton_cost, "exp_cost": exp_cost, "reward": reward
        }

    def remove_gems(self, user_id, amount, admin_id):
        self.cursor.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (amount, user_id))
        self.log_admin_action(admin_id, 'remove_gems', user_id, f'-{amount} тон')
        self.conn.commit()

    def ban_user(self, user_id, reason=None, days=None, admin_id=None):
        if days:
            ban_until = datetime.now() + timedelta(days=days)
            self.cursor.execute('''
                UPDATE users SET banned = 1, ban_until = ? WHERE user_id = ?
            ''', (ban_until, user_id))
            details = f"Бан на {days} дн. Причина: {reason if reason else 'Не указана'}"
        else:
            self.cursor.execute('''
                UPDATE users SET banned = 1, ban_until = NULL WHERE user_id = ?
            ''', (user_id,))
            details = f"Бан навсегда. Причина: {reason if reason else 'Не указана'}"
        
        if admin_id:
            self.log_admin_action(admin_id, 'ban', user_id, details)
        
        self.conn.commit()

    def unban_user(self, user_id, admin_id=None):
        self.cursor.execute('UPDATE users SET banned = 0, ban_until = NULL WHERE user_id = ?', (user_id,))
        if admin_id:
            self.log_admin_action(admin_id, 'unban', user_id, 'Разбан')
        self.conn.commit()

    def log_admin_action(self, admin_id, action, target_id, details):
        self.cursor.execute('''
            INSERT INTO admin_logs (admin_id, action, target_id, details) 
            VALUES (?, ?, ?, ?)
        ''', (admin_id, action, target_id, details))
        self.conn.commit()


    def migrate_hashrates(self):
        """
        Миграция: исправляет hash_rate=0 в user_asics и user_gpus
        из-за старого бага с индексами при покупке.
        Читает hash_rate из shop_asics/shop_gpus по asic_key/gpu_key.
        """
        try:
            fixed_asics = 0
            fixed_gpus = 0

            # Фикс ASIC
            c = self.conn.cursor()
            c.execute("SELECT id, user_id, asic_key FROM user_asics WHERE hash_rate = 0 OR hash_rate IS NULL")
            broken_asics = c.fetchall()
            for asic_id, user_id, asic_key in broken_asics:
                # Сначала ищем в shop_asics
                c2 = self.conn.cursor()
                c2.execute("SELECT hash_rate FROM shop_asics WHERE asic_key = ?", (asic_key,))
                row = c2.fetchone()
                if not row and asic_key == "starter_asic":
                    from cards_config import STARTER_ASIC
                    hr = float(STARTER_ASIC.get("hash_rate", 5))
                elif row:
                    hr = float(row[0])
                else:
                    from cards_config import ASICS
                    hr = float(ASICS.get(asic_key, {}).get("hash_rate", 0))
                if hr > 0:
                    self.conn.cursor().execute(
                        "UPDATE user_asics SET hash_rate = ? WHERE id = ?", (hr, asic_id)
                    )
                    fixed_asics += 1

            # Фикс GPU
            c3 = self.conn.cursor()
            c3.execute("SELECT id, user_id, gpu_key FROM user_gpus WHERE hash_rate = 0 OR hash_rate IS NULL")
            broken_gpus = c3.fetchall()
            for gpu_id, user_id, gpu_key in broken_gpus:
                c4 = self.conn.cursor()
                c4.execute("SELECT hash_rate FROM shop_gpus WHERE gpu_key = ?", (gpu_key,))
                row = c4.fetchone()
                if not row:
                    from cards_config import GPU_CARDS
                    hr = float(GPU_CARDS.get(gpu_key, {}).get("hash_rate", 0))
                else:
                    hr = float(row[0])
                if hr > 0:
                    self.conn.cursor().execute(
                        "UPDATE user_gpus SET hash_rate = ? WHERE id = ?", (hr, gpu_id)
                    )
                    fixed_gpus += 1

            self.conn.commit()

            # Пересчитываем хешрейт всем юзерам у кого было 0
            if fixed_asics > 0 or fixed_gpus > 0:
                cu = self.conn.cursor()
                cu.execute("SELECT DISTINCT user_id FROM users")
                all_users = [r[0] for r in cu.fetchall()]
                for uid in all_users:
                    self.recalculate_user_hashrate(uid)

            return fixed_asics, fixed_gpus
        except Exception as e:
            logger.error(f"migrate_hashrates error: {e}")
            return 0, 0


    # ========== БАРАХОЛКА ==========

    def market_list_item(self, seller_id, item_type, item_id, price, comp_name=None, comp_amount=None):
        """Выставить предмет на барахолку. item_type: 'gpu'|'cooler'|'component'"""
        import sqlite3 as _sqlite3
        conn2 = _sqlite3.connect('mining_bot.db', timeout=30)
        conn2.execute('PRAGMA journal_mode=WAL')
        try:
            c = conn2.cursor()
            hash_rate, cooling_power, wear, is_crafted = 0, 0, 100, 0

            if item_type == 'gpu':
                c.execute('SELECT name, hash_rate, wear, is_crafted FROM user_gpus WHERE id = ? AND user_id = ? AND is_installed = 0', (item_id, seller_id))
                row = c.fetchone()
                if not row:
                    return False, "❌ Видеокарта не найдена или установлена в риг"
                name, hash_rate, wear, is_crafted = row
                c.execute('UPDATE user_gpus SET is_installed = 2 WHERE id = ?', (item_id,))

            elif item_type == 'cooler':
                c.execute('SELECT name, cooling_power, wear FROM user_coolers WHERE id = ? AND user_id = ? AND rig_id IS NULL', (item_id, seller_id))
                row = c.fetchone()
                if not row:
                    return False, "❌ Куллер не найден или установлен в риг"
                name, cooling_power, wear = row
                c.execute('UPDATE user_coolers SET rig_id = -1 WHERE id = ?', (item_id,))

            else:
                return False, "❌ Неизвестный тип"

            expires_at = datetime.now() + timedelta(days=3)
            c.execute("""
                INSERT INTO market_listings
                (seller_id, item_type, item_id, item_name, hash_rate, cooling_power, wear, price, is_crafted, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (seller_id, item_type, item_id, name, hash_rate, cooling_power, wear, price, is_crafted, expires_at))

            conn2.commit()
            return True, c.lastrowid
        except Exception as e:
            logger.error(f"market_list_item error: {e}")
            return False, str(e)
        finally:
            conn2.close()

    def market_cancel_listing(self, listing_id, user_id):
        """Снять предмет с барахолки"""
        try:
            c = self.conn.cursor()
            c.execute('SELECT seller_id, item_type, item_id FROM market_listings WHERE id = ? AND is_active = 1', (listing_id,))
            row = c.fetchone()
            if not row:
                return False, "❌ Объявление не найдено"
            seller_id, item_type, item_id = row
            if seller_id != user_id:
                return False, "❌ Это не твой лот"
            # Получаем item_name для компонентов (там хранится "🧩 Чип ×5")
            c.execute('SELECT item_name FROM market_listings WHERE id = ?', (listing_id,))
            name_row = c.fetchone()
            item_name_str = name_row[0] if name_row else ""

            c.execute('UPDATE market_listings SET is_active = 0 WHERE id = ?', (listing_id,))
            if item_type == 'gpu':
                c.execute('UPDATE user_gpus SET is_installed = 0 WHERE id = ?', (item_id,))
            elif item_type == 'cooler':
                c.execute('UPDATE user_coolers SET rig_id = NULL WHERE id = ?', (item_id,))
            elif item_type == 'component':
                # item_id = количество, comp_name из item_name "🧩 Чип ×5"
                comp_amount = item_id
                comp_name = item_name_str.rsplit(' ×', 1)[0] if ' ×' in item_name_str else item_name_str
                c.execute("""INSERT INTO components (user_id, component_name, amount) VALUES (?, ?, ?)
                             ON CONFLICT(user_id, component_name) DO UPDATE SET amount = amount + ?""",
                          (seller_id, comp_name, comp_amount, comp_amount))
            self.conn.commit()
            return True, "✅ Товар снят с продажи"
        except Exception as e:
            return False, str(e)

    def market_buy_item(self, buyer_id, listing_id):
        """Купить предмет с барахолки"""
        try:
            c = self.conn.cursor()
            c.execute("""
                SELECT seller_id, item_type, item_id, item_name, price, hash_rate, cooling_power, wear, is_crafted
                FROM market_listings WHERE id = ? AND is_active = 1
            """, (listing_id,))
            row = c.fetchone()
            if not row:
                return False, "❌ Лот не найден или уже продан"
            seller_id, item_type, item_id, item_name, price, hash_rate, cooling_power, wear, is_crafted = row
            if seller_id == buyer_id:
                return False, "❌ Нельзя купить свой товар"

            buyer = self.get_user(buyer_id)
            if not buyer or buyer[4] < price:
                return False, f"❌ Недостаточно тон! Нужно: {price}"

            # Снимаем деньги у покупателя, отдаём продавцу
            c.execute('UPDATE users SET gems = gems - ? WHERE user_id = ?', (price, buyer_id))
            c.execute('UPDATE users SET gems = gems + ? WHERE user_id = ?', (price, seller_id))

            # Переводим предмет покупателю
            if item_type == 'gpu':
                c.execute('UPDATE user_gpus SET user_id = ?, is_installed = 0 WHERE id = ?', (buyer_id, item_id))
            elif item_type == 'cooler':
                c.execute('UPDATE user_coolers SET user_id = ?, rig_id = NULL WHERE id = ?', (buyer_id, item_id))
            elif item_type == 'component':
                # item_id = количество, comp_name из item_name "🧩 Чип ×5"
                comp_amount = item_id
                comp_name = item_name.rsplit(' ×', 1)[0] if ' ×' in item_name else item_name
                c.execute("""INSERT INTO components (user_id, component_name, amount) VALUES (?, ?, ?)
                             ON CONFLICT(user_id, component_name) DO UPDATE SET amount = amount + ?""",
                          (buyer_id, comp_name, comp_amount, comp_amount))

            c.execute('UPDATE market_listings SET is_active = 0 WHERE id = ?', (listing_id,))
            self.conn.commit()
            return True, {"item_name": item_name, "price": price, "seller_id": seller_id, "item_type": item_type}
        except Exception as e:
            logger.error(f"market_buy_item error: {e}")
            return False, str(e)

    def market_get_listings(self, item_type=None, sort='price_asc', exclude_user=None, only_user=None, limit=20, offset=0):
        """Получить лоты барахолки"""
        c = self.conn.cursor()
        where = ["is_active = 1", "expires_at > datetime('now')"]
        params = []
        if item_type:
            where.append("item_type = ?")
            params.append(item_type)
        if exclude_user:
            where.append("seller_id != ?")
            params.append(exclude_user)
        if only_user:
            where.append("seller_id = ?")
            params.append(only_user)

        order = {
            'price_asc': 'price ASC',
            'price_desc': 'price DESC',
            'hash_desc': 'hash_rate DESC',
            'wear_desc': 'wear DESC',
            'new': 'listed_at DESC',
        }.get(sort, 'price ASC')

        sql = f"SELECT * FROM market_listings WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?"
        params += [limit, offset]
        c.execute(sql, params)
        return c.fetchall()

    def market_expire_listings(self):
        """Возвращает просроченные лоты продавцам"""
        try:
            c = self.conn.cursor()
            c.execute("""
                SELECT id, item_type, item_id, seller_id, item_name
                FROM market_listings WHERE is_active = 1 AND expires_at <= datetime('now')
            """)
            expired = c.fetchall()
            for listing_id, item_type, item_id, seller_id, item_name in expired:
                c.execute('UPDATE market_listings SET is_active = 0 WHERE id = ?', (listing_id,))
                if item_type == 'gpu':
                    c.execute('UPDATE user_gpus SET user_id = ?, is_installed = 0 WHERE id = ?', (seller_id, item_id))
                elif item_type == 'cooler':
                    c.execute('UPDATE user_coolers SET user_id = ?, rig_id = NULL WHERE id = ?', (seller_id, item_id))
                elif item_type == 'component':
                    comp_amount = item_id
                    comp_name = item_name.rsplit(' ×', 1)[0] if ' ×' in item_name else item_name
                    c.execute("""INSERT INTO components (user_id, component_name, amount) VALUES (?, ?, ?)
                                 ON CONFLICT(user_id, component_name) DO UPDATE SET amount = amount + ?""",
                              (seller_id, comp_name, comp_amount, comp_amount))
            self.conn.commit()
            return len(expired)
        except Exception as e:
            logger.error(f"market_expire_listings error: {e}")
            return 0

    def market_get_shop_price(self, item_type, gpu_key=None, cooler_key=None):
        """Получить цену предмета в магазине для расчёта 30%"""
        c = self.conn.cursor()
        if item_type == 'gpu' and gpu_key:
            c.execute('SELECT price FROM shop_gpus WHERE gpu_key = ?', (gpu_key,))
        elif item_type == 'cooler' and cooler_key:
            c.execute('SELECT price FROM shop_coolers WHERE cooler_key = ?', (cooler_key,))
        else:
            return 0
        row = c.fetchone()
        return row[0] if row else 0


    def market_list_component(self, seller_id, comp_name, qty, price_each):
        """Выставить компоненты на барахолку"""
        import sqlite3 as _sqlite3
        conn2 = _sqlite3.connect('mining_bot.db', timeout=30)
        conn2.execute('PRAGMA journal_mode=WAL')
        try:
            c = conn2.cursor()
            c.execute("SELECT amount FROM components WHERE user_id = ? AND component_name = ?",
                      (seller_id, comp_name))
            row = c.fetchone()
            actual = row[0] if row else 0
            logger.info(f"market_list_component: user={seller_id} comp={comp_name!r} qty={qty} actual={actual}")
            if actual < qty:
                return False, f"Недостаточно: нужно {qty}, есть {actual}"

            c.execute("UPDATE components SET amount = amount - ? WHERE user_id = ? AND component_name = ?",
                      (qty, seller_id, comp_name))
            c.execute("DELETE FROM components WHERE user_id = ? AND component_name = ? AND amount <= 0",
                      (seller_id, comp_name))

            expires_at = datetime.now() + timedelta(days=3)
            total_price = price_each * qty
            c.execute("""
                INSERT INTO market_listings
                (seller_id, item_type, item_id, item_name, hash_rate, cooling_power, wear, price, is_crafted, expires_at)
                VALUES (?, 'component', 0, ?, ?, ?, 100, ?, 0, ?)
            """, (seller_id, f"{comp_name} ×{qty}", float(qty), price_each, total_price, expires_at))
            lid = c.lastrowid
            conn2.commit()
            return True, lid
        except Exception as e:
            logger.error(f"market_list_component error: {e}")
            return False, str(e)
        finally:
            conn2.close()

    def market_buy_component(self, buyer_id, listing_id):
        """Купить компоненты с барахолки"""
        try:
            c = self.conn.cursor()
            c.execute("""SELECT seller_id, item_name, price, hash_rate, cooling_power
                         FROM market_listings WHERE id = ? AND is_active = 1 AND item_type = 'component'""",
                      (listing_id,))
            row = c.fetchone()
            if not row:
                return False, "❌ Лот не найден"
            seller_id, item_name, total_price, qty, price_each = row
            if seller_id == buyer_id:
                return False, "❌ Нельзя купить своё"

            buyer = self.get_user(buyer_id)
            if not buyer or buyer[4] < total_price:
                return False, f"❌ Нужно {total_price} тон"

            # Извлекаем название компонента из item_name (формат "🧩 Чип ×5")
            comp_name = item_name.rsplit(" ×", 1)[0]

            c.execute("UPDATE users SET gems = gems - ? WHERE user_id = ?", (total_price, buyer_id))
            c.execute("UPDATE users SET gems = gems + ? WHERE user_id = ?", (total_price, seller_id))
            self.add_component(buyer_id, comp_name, int(qty))
            c.execute("UPDATE market_listings SET is_active = 0 WHERE id = ?", (listing_id,))
            self.conn.commit()
            return True, {"item_name": item_name, "price": total_price, "seller_id": seller_id, "comp_name": comp_name, "qty": int(qty)}
        except Exception as e:
            logger.error(f"market_buy_component error: {e}")
            return False, str(e)

    # ========== МЕТОДЫ ДЛЯ АВТОПОПОЛНЕНИЯ ==========
    
    def get_price_category(self, price):
        try:
            price = int(price)
            if price < 1000:
                return "low"
            elif price < 3000:
                return "medium"
            elif price < 6000:
                return "high"
            else:
                return "very_high"
        except:
            return "medium"

    def auto_restock(self):
        try:
            total_restocked = 0
            restock_log = []
            
            self.cursor.execute('SELECT gpu_key, name, price, stock FROM shop_gpus')
            gpus = self.cursor.fetchall()
            for gpu in gpus:
                gpu_key, name, price, stock = gpu
                category = self.get_price_category(price)
                chance = config.RESTOCK_CHANCE_BY_PRICE.get(category, 50)
                
                if random.randint(1, 100) <= chance:
                    amount = random.randint(config.AUTO_RESTOCK_MIN_ITEMS, config.AUTO_RESTOCK_MAX_ITEMS)
                    self.cursor.execute('UPDATE shop_gpus SET stock = stock + ? WHERE gpu_key = ?', (amount, gpu_key))
                    total_restocked += amount
                    restock_log.append(f"  • {name}: +{amount} шт.")
            
            self.cursor.execute('SELECT cooler_key, name, price, stock FROM shop_coolers')
            coolers = self.cursor.fetchall()
            for cooler in coolers:
                cooler_key, name, price, stock = cooler
                category = self.get_price_category(price)
                chance = config.RESTOCK_CHANCE_BY_PRICE.get(category, 50)
                
                if random.randint(1, 100) <= chance:
                    amount = random.randint(config.AUTO_RESTOCK_MIN_ITEMS, config.AUTO_RESTOCK_MAX_ITEMS)
                    self.cursor.execute('UPDATE shop_coolers SET stock = stock + ? WHERE cooler_key = ?', (amount, cooler_key))
                    total_restocked += amount
                    restock_log.append(f"  • {name}: +{amount} шт.")
            
            self.cursor.execute('SELECT asic_key, name, price, stock FROM shop_asics')
            asics = self.cursor.fetchall()
            for asic in asics:
                asic_key, name, price, stock = asic
                category = self.get_price_category(price)
                chance = config.RESTOCK_CHANCE_BY_PRICE.get(category, 50)
                
                if random.randint(1, 100) <= chance:
                    amount = random.randint(1, 3)
                    self.cursor.execute('UPDATE shop_asics SET stock = stock + ? WHERE asic_key = ?', (amount, asic_key))
                    total_restocked += amount
                    restock_log.append(f"  • {name}: +{amount} шт.")
            
            self.cursor.execute('SELECT rig_key, name, price, stock FROM shop_rigs')
            rigs = self.cursor.fetchall()
            for rig in rigs:
                rig_key, name, price, stock = rig
                category = self.get_price_category(price)
                chance = config.RESTOCK_CHANCE_BY_PRICE.get(category, 30)
                
                if random.randint(1, 100) <= chance:
                    amount = random.randint(1, 2)
                    self.cursor.execute('UPDATE shop_rigs SET stock = stock + ? WHERE rig_key = ?', (amount, rig_key))
                    total_restocked += amount
                    restock_log.append(f"  • {name}: +{amount} шт.")
            
            self.conn.commit()
            
            print(f"📦 Автоматическое пополнение склада выполнено! Добавлено: {total_restocked} товаров")
            for log in restock_log:
                print(log)
            
            return total_restocked, restock_log
            
        except Exception as e:
            print(f"❌ Ошибка при автоматическом пополнении: {e}")
            import traceback
            traceback.print_exc()
            return 0, []

    def check_and_restock(self):
        if not config.AUTO_RESTOCK_ENABLED:
            return False
        
        try:
            self.cursor.execute('SELECT last_restock FROM auto_restock_log ORDER BY id DESC LIMIT 1')
            result = self.cursor.fetchone()
            now = datetime.now()
            
            if not result:
                self.cursor.execute('INSERT INTO auto_restock_log (last_restock) VALUES (?)', (now,))
                self.conn.commit()
                return True
            
            last_restock = datetime.fromisoformat(result[0])
            
            if now.date() > last_restock.date():
                target_time = datetime.strptime(config.AUTO_RESTOCK_TIME, "%H:%M").time()
                target_datetime = datetime.combine(now.date(), target_time)
                
                if now >= target_datetime and last_restock.date() < now.date():
                    self.cursor.execute('INSERT INTO auto_restock_log (last_restock) VALUES (?)', (now,))
                    self.conn.commit()
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Ошибка при проверке времени пополнения: {e}")
            return False

    # ========== МЕТОДЫ ДЛЯ ЕЖЕДНЕВНЫХ БОНУСОВ ==========
    
    def get_daily_bonus(self, user_id):
        today = datetime.now().date()
        
        self.cursor.execute('SELECT last_bonus, streak FROM daily_bonus WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if result:
            try:
                last_bonus = datetime.strptime(result[0], '%Y-%m-%d').date()
                streak = result[1]
                
                if last_bonus == today:
                    return False, 0, 0, streak, "Сегодня бонус уже получен!"
                
                if (today - last_bonus).days == 1:
                    streak += 1
                else:
                    streak = 1
            except:
                streak = 1
        else:
            streak = 1
        
        privilege, _ = self.get_user_privilege(user_id)
        priv_bonuses = self.get_privilege_bonuses(privilege)
        
        base_ton = config.DAILY_BONUS_AMOUNT
        base_exp = config.DAILY_BONUS_EXP
        
        ton_bonus = base_ton
        exp_bonus = base_exp
        
        if config.DAILY_STREAK_BONUS:
            for days, multiplier in config.STREAK_MULTIPLIER.items():
                if streak >= days:
                    ton_bonus = base_ton * multiplier
                    exp_bonus = base_exp * multiplier
        
        ton_bonus = int(ton_bonus * priv_bonuses["daily_bonus_multiplier"])
        exp_bonus = int(exp_bonus * priv_bonuses["daily_bonus_multiplier"])
        
        self.cursor.execute('UPDATE users SET gems = gems + ?, exp = exp + ? WHERE user_id = ?', 
                           (ton_bonus, exp_bonus, user_id))
        
        self.cursor.execute('''
            INSERT OR REPLACE INTO daily_bonus (user_id, last_bonus, streak, total_bonus) 
            VALUES (?, ?, ?, COALESCE((SELECT total_bonus FROM daily_bonus WHERE user_id = ?), 0) + ?)
        ''', (user_id, today, streak, user_id, ton_bonus))
        
        self.conn.commit()
        
        extra_reward = ""
        if streak in [7, 30, 100, 365]:
            extra_reward = f"\n🎉 Поздравляем с {streak} днями стрика!"
        
        return True, ton_bonus, exp_bonus, streak, extra_reward


# Создаем экземпляр БД
db = Database()


# ==================== ЗАДАНИЯ (ежедневные / еженедельные) ====================

import json as _json

# ── Шаблоны ежедневных заданий ─────────────────────────────────────────────
DAILY_QUEST_TEMPLATES = [
    {"key": "mine_3",       "desc": "Сделай 3 майнинга",         "icon": "⛏",  "type": "mine",        "target": 3,   "reward_ton": 150,  "reward_exp": 30},
    {"key": "mine_5",       "desc": "Сделай 5 майнингов",        "icon": "⛏",  "type": "mine",        "target": 5,   "reward_ton": 280,  "reward_exp": 50},
    {"key": "mine_10",      "desc": "Сделай 10 майнингов",       "icon": "⛏",  "type": "mine",        "target": 10,  "reward_ton": 600,  "reward_exp": 100},
    {"key": "open_box_1",   "desc": "Открой 1 бокс",             "icon": "📦",  "type": "open_box",    "target": 1,   "reward_ton": 200,  "reward_exp": 40},
    {"key": "open_box_3",   "desc": "Открой 3 бокса",            "icon": "📦",  "type": "open_box",    "target": 3,   "reward_ton": 500,  "reward_exp": 80},
    {"key": "earn_500",     "desc": "Заработай 500 тон за день", "icon": "💰",  "type": "earn",        "target": 500, "reward_ton": 250,  "reward_exp": 50},
    {"key": "earn_1000",    "desc": "Заработай 1000 тон за день","icon": "💰",  "type": "earn",        "target": 1000,"reward_ton": 500,  "reward_exp": 100},
    {"key": "daily_bonus",  "desc": "Получи ежедневный бонус",   "icon": "🎁",  "type": "daily_bonus", "target": 1,   "reward_ton": 100,  "reward_exp": 20},
    {"key": "craft_1",      "desc": "Скрафти 1 GPU",             "icon": "⚒",  "type": "craft",       "target": 1,   "reward_ton": 400,  "reward_exp": 80},
]

# ── Шаблоны еженедельных заданий ───────────────────────────────────────────
WEEKLY_QUEST_TEMPLATES = [
    {"key": "w_mine_50",    "desc": "Сделай 50 майнингов",       "icon": "⛏",  "type": "mine",        "target": 50,  "reward_ton": 2000,  "reward_exp": 400},
    {"key": "w_mine_100",   "desc": "Сделай 100 майнингов",      "icon": "⛏",  "type": "mine",        "target": 100, "reward_ton": 4000,  "reward_exp": 800},
    {"key": "w_earn_5000",  "desc": "Заработай 5000 тон за неделю","icon": "💰","type": "earn",        "target": 5000,"reward_ton": 2500,  "reward_exp": 500},
    {"key": "w_earn_10000", "desc": "Заработай 10000 тон за неделю","icon": "💰","type": "earn",       "target": 10000,"reward_ton": 5000, "reward_exp": 1000},
    {"key": "w_open_10",    "desc": "Открой 10 боксов",          "icon": "📦",  "type": "open_box",    "target": 10,  "reward_ton": 2000,  "reward_exp": 400},
    {"key": "w_streak_7",   "desc": "Стрик 7 дней подряд",       "icon": "🔥",  "type": "streak",      "target": 7,   "reward_ton": 3000,  "reward_exp": 600},
    {"key": "w_buy_gpu",    "desc": "Купи любую GPU",            "icon": "🖼",  "type": "buy_gpu",     "target": 1,   "reward_ton": 1500,  "reward_exp": 300},
    {"key": "w_buy_asic",   "desc": "Купи любой ASIC",           "icon": "⚡",  "type": "buy_asic",    "target": 1,   "reward_ton": 3000,  "reward_exp": 600},
    {"key": "w_craft_3",    "desc": "Скрафти 3 GPU",             "icon": "⚒",  "type": "craft",       "target": 3,   "reward_ton": 3000,  "reward_exp": 600},
    {"key": "w_referral",   "desc": "Пригласи реферала",         "icon": "👥",  "type": "referral",    "target": 1,   "reward_ton": 4000,  "reward_exp": 800},
]


def _get_week_start():
    """Понедельник текущей недели (YYYY-MM-DD)."""
    today = datetime.now().date()
    return (today - timedelta(days=today.weekday())).isoformat()


def _pick_quests(templates, n, seed_str):
    """Выбирает n заданий из шаблонов детерминированно по seed."""
    import hashlib
    h = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    idxs = []
    pool = list(range(len(templates)))
    while len(idxs) < n and pool:
        i = h % len(pool)
        idxs.append(pool.pop(i))
        h = h * 6364136223846793005 + 1442695040888963407
    return [templates[i] for i in idxs]


def get_user_quests(user_id: int) -> dict:
    """
    Возвращает {
      "daily": [{"key","desc","icon","type","target","reward_ton","reward_exp","progress","done","claimed"},...],
      "weekly": [...],
      "daily_date": "YYYY-MM-DD",
      "weekly_start": "YYYY-MM-DD"
    }
    Автоматически обновляет задания при смене дня/недели.
    """
    today = datetime.now().date().isoformat()
    week_start = _get_week_start()

    c = db.conn.cursor()
    c.execute(
        "SELECT quest_data FROM user_quests WHERE user_id=?", (user_id,))
    row = c.fetchone()
    data = _json.loads(row[0]) if row else {}

    changed = False

    # Обновляем ежедневные
    if data.get("daily_date") != today:
        seed = f"daily:{user_id}:{today}"
        chosen = _pick_quests(DAILY_QUEST_TEMPLATES, 3, seed)
        data["daily"] = [
            {**q, "progress": 0, "done": False, "claimed": False}
            for q in chosen
        ]
        data["daily_date"] = today
        changed = True

    # Обновляем еженедельные
    if data.get("weekly_start") != week_start:
        seed = f"weekly:{user_id}:{week_start}"
        chosen = _pick_quests(WEEKLY_QUEST_TEMPLATES, 3, seed)
        data["weekly"] = [
            {**q, "progress": 0, "done": False, "claimed": False}
            for q in chosen
        ]
        data["weekly_start"] = week_start
        changed = True

    if changed:
        _save_quests(user_id, data)

    return data


def _save_quests(user_id: int, data: dict):
    c = db.conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO user_quests (user_id, quest_data) VALUES (?,?)",
        (user_id, _json.dumps(data, ensure_ascii=False)))
    db.conn.commit()


def advance_quest(user_id: int, quest_type: str, amount: int = 1) -> list:
    """Продвинуть прогресс, авто-выдать награду при выполнении. Вернуть список выполненных."""
    data = get_user_quests(user_id)
    changed = False
    completed = []
    for group in ("daily", "weekly"):
        for q in data.get(group, []):
            if q["type"] == quest_type and not q["done"]:
                q["progress"] = min(q["progress"] + amount, q["target"])
                if q["progress"] >= q["target"]:
                    q["done"] = True
                    if not q.get("claimed"):
                        q["claimed"] = True
                        # Авто-выдаём награду
                        db.add_gems(user_id, q["reward_ton"])
                        db.cursor.execute(
                            "UPDATE users SET exp=exp+? WHERE user_id=?",
                            (q["reward_exp"], user_id))
                        db.conn.commit()
                        completed.append(q)
                changed = True
    if changed:
        _save_quests(user_id, data)
    return completed


async def _show_quests(user_id: int, target, group: str = "daily"):
    data = get_user_quests(user_id)
    quests = data.get(group, [])
    title = "📋 <b>Ежедневные задания</b>" if group == "daily" else "📅 <b>Еженедельные задания</b>"

    if group == "daily":
        reset_label = "Сброс в полночь"
    else:
        mon = _get_week_start()
        reset_label = f"Сброс в понедельник (с {mon})"

    lines = [title, f"<i>{reset_label}</i>", ""]

    for i, q in enumerate(quests):
        bar_filled = int(q["progress"] / q["target"] * 10) if q["target"] else 10
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        pct = int(q["progress"] / q["target"] * 100) if q["target"] else 100
        status = "✅" if q["done"] else ("🎁" if False else "▶️")
        claimed = " <i>(получено)</i>" if q["claimed"] else ""
        line = q["icon"] + " <b>" + q["desc"] + "</b>" + claimed + "\n"
        line += "  " + bar + " " + str(pct) + "%"
        line += "  (" + str(q["progress"]) + "/" + str(q["target"]) + ")\n"
        rton = str(q["reward_ton"])
        rexp = str(q["reward_exp"])
        line += "  +" + rton + " ton  +" + rexp + " exp"
        if q["done"]:
            line += " " + status
        lines.append(line)

    text = "\n".join(lines)


    # Кнопки навигации (награды выдаются автоматически)
    buttons = []

    nav = []
    if group == "daily":
        nav.append(InlineKeyboardButton(text="📅 Еженедельные", callback_data="quests_weekly"))
    else:
        nav.append(InlineKeyboardButton(text="📋 Ежедневные", callback_data="quests"))
    nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data="profile"))
    buttons.append(nav)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.message(Command("quests"))
async def cmd_quests(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    await _show_quests(message.from_user.id, message, "daily")


@dp.callback_query(F.data == "quests")
async def cb_quests(callback: CallbackQuery):
    await callback.answer()
    await _show_quests(callback.from_user.id, callback, "daily")


@dp.callback_query(F.data == "quests_weekly")
async def cb_quests_weekly(callback: CallbackQuery):
    await callback.answer()
    await _show_quests(callback.from_user.id, callback, "weekly")


@dp.callback_query(F.data.startswith("quest_claim:"))
async def cb_quest_claim(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, group, idx_str = parts
    idx = int(idx_str)

    data = get_user_quests(callback.from_user.id)
    quests = data.get(group, [])
    if idx >= len(quests):
        return
    q = quests[idx]
    if not q["done"] or q["claimed"]:
        await callback.answer("❌ Нельзя получить эту награду", show_alert=True)
        return

    q["claimed"] = True
    _save_quests(callback.from_user.id, data)

    db.add_gems(callback.from_user.id, q["reward_ton"])
    db.cursor.execute(
        "UPDATE users SET exp=exp+? WHERE user_id=?",
        (q["reward_exp"], callback.from_user.id))
    db.conn.commit()

    await callback.answer(
        f"✅ Получено: +{q['reward_ton']} тон, +{q['reward_exp']} опыта!", show_alert=True)
    await _show_quests(callback.from_user.id, callback, group)


@dp.message(Command("givestars"))
async def cmd_givestars(message: Message):
    """Только для админов: /givestars USER_ID AMOUNT"""
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        await message.answer("Использование: /givestars USER_ID AMOUNT")
        return
    uid, amount = int(args[1]), int(args[2])
    db.cursor.execute(
        "UPDATE users SET stars_balance=COALESCE(stars_balance,0)+? WHERE user_id=?",
        (amount, uid)
    )
    db.conn.commit()
    if db.cursor.rowcount:
        await message.answer(f"✅ Выдано {amount} ★ пользователю {uid}")
    else:
        await message.answer("❌ Пользователь не найден")


# ==================== ФУНКЦИИ ДЛЯ ИКОНОК ====================
def get_level_icon(level):
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

def get_cooler_power_icon(power):
    if power < 40:
        return "🍃"
    elif power < 60:
        return "💨"
    else:
        return "🌪️"

def get_asic_power_icon(power):
    if power < 50:
        return "🔋"
    elif power < 100:
        return "⚡"
    else:
        return "💥"

def get_rig_size_icon(size):
    icons = {
        "компактный": "📏",
        "средний": "📐",
        "большой": "🏭"
    }
    return icons.get(size, "📦")

def get_top_icon(position):
    icons = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    if 1 <= position <= len(icons):
        return icons[position - 1]
    return "📊"

# ==================== ПРОВЕРКИ ====================
def is_admin(user_id):
    return user_id in config.ADMIN_IDS

async def check_ban(user_id):
    return db.check_ban_status(user_id)

async def send_ban_message(message_or_callback):
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
            f"обратитесь @admin"
        )
    else:
        ban_text = (
            "⛔ Ваш аккаунт заблокирован навсегда!\n\n"
            "Если вы не согласны с решением администрации, "
            "обратитесь @admin"
        )
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(ban_text)
    else:
        await message_or_callback.message.edit_text(ban_text)

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    """Главная клавиатура без кнопок майнить и коробки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus")],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🛒 Магазин", callback_data="shop_menu"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help_menu")
        ],
        [
            InlineKeyboardButton(text="📯 Топ", callback_data="top_menu"),
            InlineKeyboardButton(text="🌟 Уровень", callback_data="level"),
            InlineKeyboardButton(text="🪙 Донат", callback_data="donate_menu")
        ],
        [InlineKeyboardButton(text="➕ Добавить бота", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true")]
    ])
    return keyboard

def get_back_to_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_menu")]
    ])
    return keyboard

def get_cancel_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    return keyboard

def get_help_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Майнинг", callback_data="help_mine"),
         InlineKeyboardButton(text="🛒 Магазин", callback_data="help_shop")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="help_profile"),
         InlineKeyboardButton(text="🖥 Оборудование", callback_data="help_equipment")],
        [InlineKeyboardButton(text="🔧 Ремонт", callback_data="help_repair"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="help_referrals")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="help_top"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="help_stats")],
        [InlineKeyboardButton(text="📦 Коробки", callback_data="help_boxes")]
    ])
    return keyboard

def get_back_to_help_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в помощь", callback_data="back_to_help")]
    ])
    return keyboard

# Цены привилегий и наборов (звёзды)
_PRIV_INFO = {
    "premium": ("Премиум", 50),
    "vip":     ("VIP",     125),
    "legend":  ("Легенда", 500),
}
_BUNDLE_INFO = {
    "start":  ("Старт",      99),
    "deluxe": ("Делюкс",    250),
    "cosmic": ("Космический",999),
}


def get_donate_keyboard():
    """Главное меню доната — список в цитате, кнопки управления снизу."""
    rows = [
        # Ряд 1: Купить + Кошелёк
        [
            InlineKeyboardButton(text="🛒 Купить",    callback_data="donate_buy_menu"),
            InlineKeyboardButton(text="👛 Кошелёк",   callback_data="donate_wallet"),
        ],
        # Ряд 2: Назад + Промокоды
        [
            InlineKeyboardButton(text="◀️ Назад",     callback_data="back_to_menu"),
            InlineKeyboardButton(text="🎟 Промокоды", callback_data="my_nick_promos"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_donate_buy_keyboard():
    """Меню покупки — только кнопки привилегий и наборов, без разделителей."""
    priv_row = [
        InlineKeyboardButton(text=label, callback_data=f"donate_buy:{k}")
        for k, (label, price) in _PRIV_INFO.items()
    ]
    bundle_row = [
        InlineKeyboardButton(text=label, callback_data=f"donate_buy:{k}")
        for k, (label, price) in _BUNDLE_INFO.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        priv_row,
        bundle_row,
        [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_menu")],
    ])


# Данные наборов
BUNDLES = {
    "start": {
        "name": "Старт", "stars": 99,
        "desc": "Набор для новичка",
        "items": ["500 тон", "Мини-риг", "GTX 1050 Ti"]
    },
    "deluxe": {
        "name": "Делюкс", "stars": 299,
        "desc": "Для опытных майнеров",
        "items": ["2000 тон", "Midi-rig", "RTX 3060", "Премиум 14 дней"]
    },
    "cosmic": {
        "name": "Космический", "stars": 999,
        "desc": "Максимальный старт",
        "items": ["10000 тон", "Mega-rig", "RTX 3090", "VIP 30 дней", "Antminer S9"]
    },
}


async def _show_priv_info(target, priv_key: str):
    """Карточка привилегии"""
    p = config.PRIVILEGES.get(priv_key)
    if not p:
        return
    b = p["bonuses"]
    text = (
        f"{p['icon']} <b>{p['name']}</b> — {p['price']} ★\n\n"
        f"<blockquote>"
        f"x{b['ton_multiplier']} к доходу от майнинга\n"
        f"x{b['exp_multiplier']} к опыту\n"
        f"-{b['repair_discount']}% к ремонту\n"
        f"+{b['hash_bonus']} MH/s ко всем картам\n"
        f"Макс. карт: {b['max_cards']}\n"
        f"</blockquote>\n\n"
        f"Действует 30 дней."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Купить {p['name']} ({p['price']} ★)",
                              callback_data=f"buy_{priv_key}")],
        [InlineKeyboardButton(text="◀️ Донат магазин", callback_data="donate_menu")],
    ])
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="HTML")


DONATE_PRIV_KEYS = {"premium", "vip", "legend"}
DONATE_BUNDLE_KEYS = {"start", "deluxe", "cosmic"}
DONATE_PRIV_LABELS = {"premium": "Премиум", "vip": "VIP", "legend": "Легенда"}
DONATE_BUNDLE_LABELS = {"start": "Старт", "deluxe": "Делюкс", "cosmic": "Космический"}


def _donate_main_text(user, current_privilege, until) -> str:
    """Текст главного меню доната с цитатой-списком."""
    if current_privilege != "player":
        pd = config.PRIVILEGES[current_privilege]
        until_str = datetime.fromisoformat(until).strftime("%d.%m.%Y") if until else "навсегда"
        priv_line = f"{pd['icon']} {pd['name']} (до {until_str})"
    else:
        priv_line = "Обычный игрок"
    stars = db.get_stars(user[0])

    return (
        f"🪙 <b>Донат магазин</b>\n\n"
        f"<blockquote>"
        f"Привилегии:\n"
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=priv_premium">Премиум</a> » 50 ⭐\n'
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=priv_vip">VIP</a> » 125 ⭐\n'
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=priv_legend">Легенда</a> » 500 ⭐\n'
        f"Наборы:\n"
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=bundle_start">Старт</a> » 99 ⭐\n'
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=bundle_deluxe">Делюкс</a> » 250 ⭐\n'
        f' <a href="https://t.me/{config.BOT_USERNAME}?start=bundle_cosmic">Космический</a> » 999 ⭐'
        f"</blockquote>\n\n"
        f"Привилегия: {priv_line}\n"
        f"Баланс: {int(user[4])} тон | {stars} ⭐\n\n"
        f"Выберите действие:"
    )


@dp.callback_query(F.data.startswith("donate_select:"))
async def callback_donate_select(callback: CallbackQuery):
    """Нажатие на название товара — показывает его описание."""
    await callback.answer()
    selected = callback.data.split(":")[1]
    await _show_priv_or_bundle(callback, selected)


async def _show_priv_or_bundle(target, key: str):
    """Показывает карточку привилегии или набора с кнопкой Купить."""
    if key in DONATE_PRIV_KEYS:
        await _show_priv_info(target, key)
    elif key in DONATE_BUNDLE_KEYS:
        bun = BUNDLES.get(key)
        if not bun:
            return
        items_str = "\n".join(f"• {i}" for i in bun["items"])
        text = (
            f"📦 <b>Набор «{bun['name']}»</b> — {bun['stars']} ⭐\n\n"
            f"{bun['desc']}\n"
            f"<blockquote>{items_str}</blockquote>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Купить {bun['stars']} ⭐", callback_data=f"donate_buy:{key}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_buy_menu")],
        ])
        if isinstance(target, Message):
            await target.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await target.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "donate_buy_menu")
async def callback_donate_buy_menu(callback: CallbackQuery):
    """Меню покупки — список всех товаров."""
    await callback.answer()
    bu = config.BOT_USERNAME
    text = (
        "🛒 <b>Выберите товар</b>\n\n"
        "<blockquote>"
        "Привилегии:\n"
        f' <a href="https://t.me/{bu}?start=priv_premium">Премиум</a> » 50 ⭐\n'
        f' <a href="https://t.me/{bu}?start=priv_vip">VIP</a> » 125 ⭐\n'
        f' <a href="https://t.me/{bu}?start=priv_legend">Легенда</a> » 500 ⭐\n'
        "Наборы:\n"
        f' <a href="https://t.me/{bu}?start=bundle_start">Старт</a> » 99 ⭐\n'
        f' <a href="https://t.me/{bu}?start=bundle_deluxe">Делюкс</a> » 250 ⭐\n'
        f' <a href="https://t.me/{bu}?start=bundle_cosmic">Космический</a> » 999 ⭐'
        "</blockquote>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_donate_buy_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=get_donate_buy_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "donate_agreement")
async def callback_donate_agreement(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📋 <b>Пользовательское соглашение</b>\n\n"
        "<blockquote>"
        "• Все покупки совершаются добровольно.\n"
        "• Звёзды Telegram используются как внутренняя валюта бота.\n"
        "• Возврат средств не предусмотрен.\n"
        "• Привилегии действуют 30 дней с момента покупки.\n"
        "• Администрация оставляет за собой право изменять условия."
        "</blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_menu")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")




@dp.callback_query(F.data.startswith("donate_buy:"))
async def callback_donate_buy(callback: CallbackQuery):
    """Кнопка Купить — перенаправляет на покупку привилегии или набора"""
    await callback.answer()
    key = callback.data.split(":")[1]
    if key in DONATE_PRIV_KEYS:
        await buy_privilege(callback.message, key)
    elif key in DONATE_BUNDLE_KEYS:
        await callback.answer("🚧 Покупка наборов скоро будет доступна!", show_alert=True)


@dp.callback_query(F.data.startswith("priv_info:"))
async def callback_priv_info(callback: CallbackQuery):
    await callback.answer()
    priv_key = callback.data.split(":")[1]
    await _show_priv_info(callback, priv_key)


@dp.message(Command("premium"))
async def cmd_premium(message: Message):
    await _show_priv_info(message, "premium")


@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    await _show_priv_info(message, "vip")


@dp.message(Command("legend"))
async def cmd_legend(message: Message):
    await _show_priv_info(message, "legend")


@dp.callback_query(F.data.startswith("bundle_info:"))
async def callback_bundle_info(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":")[1]
    b = BUNDLES.get(key)
    if not b:
        return
    items_str = "\n".join(f"• {i}" for i in b["items"])
    text = (
        f"📦 <b>Набор «{b['name']}»</b> — {b['stars']} ★\n\n"
        f"{b['desc']}\n\n"
        f"<blockquote>{items_str}</blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Купить ({b['stars']} ★)", callback_data=f"buy_bundle:{key}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("buy_bundle:"))
async def callback_buy_bundle(callback: CallbackQuery):
    await callback.answer("🚧 Покупка наборов скоро будет доступна!", show_alert=True)


def _wallet_text_kb(ton_bal, stars_bal):
    """Текст и клавиатура кошелька."""
    text = (
        f"👛 <b>Кошелёк</b>\n\n"
        f"<blockquote>"
        f"💰 Тон ›› {ton_bal}\n"
        f"⭐ Звёзды ›› {stars_bal}\n"
        f"</blockquote>\n\n"
        f"Курс обмена: 1 ⭐ = 100 💰 тон\n"
        f"<i>Выбери количество звёзд для обмена или введи своё:</i>"
    )
    # Пресеты: 1 5 10 25 50 — показываем только если есть звёзды
    presets = [1, 5, 10, 25, 50]
    preset_row = [
        InlineKeyboardButton(text=str(n), callback_data=f"stars_ex_do:{n}")
        for n in presets
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        preset_row,
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="stars_ex_input")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_menu")],
    ])
    return text, kb


@dp.callback_query(F.data == "donate_wallet")
async def callback_donate_wallet(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user = db.get_user(callback.from_user.id)
    ton_bal = int(user[4]) if user[4] else 0
    stars_bal = db.get_stars(callback.from_user.id)
    text, kb = _wallet_text_kb(ton_bal, stars_bal)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "stars_ex_input")
async def callback_stars_ex_input(callback: CallbackQuery, state: FSMContext):
    """Запрашиваем ввод количества звёзд вручную."""
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    stars_bal = db.get_stars(callback.from_user.id)
    await state.set_state(WalletStates.waiting_stars_amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="donate_wallet")]
    ])
    await callback.message.edit_text(
        f"👛 <b>Обмен звёзд</b>\n\n"
        f"У тебя: <b>{stars_bal} ⭐</b>\n\n"
        f"Введи количество звёзд для обмена (1 ⭐ = 100 💰):",
        reply_markup=kb, parse_mode="HTML"
    )


@dp.message(WalletStates.waiting_stars_amount, F.text[0] != "/")
async def process_stars_amount(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Введи целое число больше 0")
        return
    amount = int(message.text)
    await state.clear()
    await _do_stars_exchange(message, amount)


@dp.callback_query(F.data.startswith("stars_ex_do:"))
async def callback_stars_ex_do(callback: CallbackQuery, state: FSMContext):
    """Обмен по пресету."""
    await callback.answer()
    await state.clear()
    amount = int(callback.data.split(":")[1])
    await _do_stars_exchange(callback, amount)


async def _do_stars_exchange(target, amount: int):
    """Основная логика обмена. target — Message или CallbackQuery."""
    user_id = target.from_user.id
    user = db.get_user(user_id)
    stars_bal = db.get_stars(user_id)
    ton_bal = int(user[4]) if user[4] else 0

    if stars_bal >= amount:
        # Достаточно звёзд — меняем сразу
        ton_gain = amount * 100
        db.cursor.execute(
            "UPDATE users SET stars_balance=stars_balance-?, gems=gems+? WHERE user_id=?",
            (amount, ton_gain, user_id)
        )
        db.conn.commit()
        text = (
            f"✅ <b>Обмен выполнен!</b>\n\n"
            f"⭐ {amount} звёзд → 💰 {ton_gain} тон\n\n"
            f"Баланс: 💰 {ton_bal + ton_gain} тон | ⭐ {stars_bal - amount} звёзд"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👛 Кошелёк", callback_data="donate_wallet")],
            [InlineKeyboardButton(text="◀️ Донат магазин", callback_data="donate_menu")],
        ])
    else:
        # Не хватает — предлагаем купить недостающее через Telegram Stars
        need = amount - stars_bal
        text = (
            f"⭐ <b>Недостаточно звёзд</b>\n\n"
            f"Нужно: {amount} ⭐\n"
            f"Есть: {stars_bal} ⭐\n"
            f"Не хватает: <b>{need} ⭐</b>\n\n"
            f"Купи недостающие {need} ⭐ через Telegram и они автоматически зачислятся на баланс."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"⭐ Купить {need} звёзд в Telegram",
                url=f"https://t.me/stars?amount={need}"
            )],
            [InlineKeyboardButton(text="👛 Кошелёк", callback_data="donate_wallet")],
        ])

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "my_nick_promos")
async def callback_my_nick_promos(callback: CallbackQuery):
    await callback.answer()
    c = db.conn.cursor()
    c.execute("SELECT code, used FROM nick_promos WHERE user_id=? ORDER BY id DESC",
              (callback.from_user.id,))
    rows = c.fetchall()
    if not rows:
        text = "🎟 <b>Твои промокоды на ник</b>\n\nПока нет промокодов.\nИх можно получить из боксов (шанс 1%)."
    else:
        lines = []
        for code, used in rows:
            status = "✅ Использован" if used else "🟢 Активен"
            lines.append(f"<code>{code}</code> — {status}")
        text = "🎟 <b>Твои промокоды на ник</b>\n\n" + "\n".join(lines)
        text += "\n\n<i>Используй: /nick НОВЫЙ_НИК ПРОМОКОД</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="donate_menu")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

def get_level_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Повысить уровень", callback_data="level_up")]
    ])
    return keyboard

def get_profile_keyboard(target_user_id=None):
    """Клавиатура для профиля"""
    if target_user_id:
        # Чужой профиль
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖥 Оборудование", callback_data=f"view_equipment_{target_user_id}")],
            [InlineKeyboardButton(text="📦 Коробки", callback_data=f"view_boxes_{target_user_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    else:
        # Свой профиль
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Склад", callback_data="my_storage"),
             InlineKeyboardButton(text="💿 Мои майнеры", callback_data="my_rigs")],
            [InlineKeyboardButton(text="📋 Задания", callback_data="quests"),
             InlineKeyboardButton(text="⚙️ Настройки", callback_data="profile_settings")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
    return keyboard

def get_shop_menu_keyboard():
    """Главное меню магазина без кнопки склад"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🖥 Видеокарты", callback_data="shop_gpus"),
            InlineKeyboardButton(text="💨 Куллеры", callback_data="shop_coolers")
        ],
        [
            InlineKeyboardButton(text="💽 ASIC-майнеры", callback_data="shop_asics"),
            InlineKeyboardButton(text="💿 GPU-риги", callback_data="shop_rigs")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

def get_shop_gpus_keyboard(items, page=0):
    items_per_page = 9
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, item in enumerate(page_items, 1):
        in_stock = item[5] > 0
        emoji = "✅" if in_stock else "⛔"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {item[2]}",
            callback_data=f"buy_gpu_{item[1]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_gpus_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_gpus_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="shop_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_shop_coolers_keyboard(items, page=0):
    items_per_page = 9
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, item in enumerate(page_items, 1):
        in_stock = item[4] > 0
        emoji = "✅" if in_stock else "⛔"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {item[2]}",
            callback_data=f"buy_cooler_{item[1]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_coolers_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_coolers_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="shop_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_shop_asics_keyboard(items, page=0):
    items_per_page = 6
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, item in enumerate(page_items, 1):
        in_stock = item[5] > 0
        emoji = "✅" if in_stock else "⛔"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {item[2]}",
            callback_data=f"buy_asic_{item[1]}"
        ))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_asics_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_asics_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="shop_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_shop_rigs_keyboard(items, page=0):
    items_per_page = 6
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, item in enumerate(page_items, 1):
        in_stock = item[4] > 0
        emoji = "✅" if in_stock else "⛔"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {item[2]}",
            callback_data=f"buy_rig_{item[1]}"
        ))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_rigs_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_rigs_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="shop_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_continue_shopping_keyboard(shop_type="gpus"):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Продолжить покупки", callback_data=f"shop_{shop_type}")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_menu")]
    ])
    return keyboard

def get_top_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Тоны", callback_data="top_gems"),
            InlineKeyboardButton(text="📶 Уровень", callback_data="top_level"),
            InlineKeyboardButton(text="⚡ HM/s", callback_data="top_hash")
        ],
        [
            InlineKeyboardButton(text="👥 Рефералы", callback_data="top_referrals")
        ]
    ])
    return keyboard

def get_skl_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Состояние склада", callback_data="admin_show_stock"),
            InlineKeyboardButton(text="➕ Пополнить", callback_data="admin_add_stock")
        ],
        [
            InlineKeyboardButton(text="➖ Убрать", callback_data="admin_remove_stock"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stock_stats")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    return keyboard

def get_mycards_keyboard(user_id, items, page=0):
    """Клавиатура для списка оборудования"""
    items_per_page = 8
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]
    
    buttons = []
    row = []
    
    for i, (item_type, item) in enumerate(page_items, 1):
        # Определяем иконку в зависимости от типа
        if item_type == 'gpu':
            base_icon = "🖼"
        elif item_type == 'cooler':
            base_icon = "💨"
        elif item_type == 'asic':
            base_icon = "💽"
        elif item_type == 'rig':
            base_icon = "💿"
        else:
            base_icon = "❓"
        
        # Проверяем, сломано ли (wear <= 20)
        is_broken = False
        if item_type in ['gpu', 'cooler', 'asic'] and len(item) > 5:
            try:
                is_broken = item[5] <= 20
            except (ValueError, TypeError):
                is_broken = False
        
        icon = "⚠️" if is_broken else base_icon
        
        # Короткое имя
        name = item[3] if len(item) > 3 else "Неизвестно"
        short_name = name[:15] + "..." if len(name) > 15 else name
        
        row.append(InlineKeyboardButton(
            text=f"{icon} {short_name}",
            callback_data=f"mycard_detail_{item_type}_{item[0]}"
        ))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Навигация
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

def get_boxes_keyboard(user_id, boxes, page=0, is_own=True):
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

def get_rigs_keyboard(user_id, rigs, page=0):
    items_per_page = 4
    total_pages = (len(rigs) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_rigs = rigs[start:end]
    
    buttons = []
    
    for rig in page_rigs:
        gpu_installed = json.loads(rig[6]) if rig[6] and rig[6] != '[]' else []
        coolers_installed = json.loads(rig[7]) if rig[7] and rig[7] != '[]' else []
        
        gpu_count = len([g for g in gpu_installed if g is not None])
        cooler_count = len([c for c in coolers_installed if c is not None])
        
        # Проверяем, есть ли сломанные GPU в риге
        has_broken = False
        gpus = db.get_rig_gpus(rig[0])
        for gpu in gpus:
            try:
                if len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20:
                    has_broken = True
                    break
            except (ValueError, TypeError):
                continue
        
        icon = "⚠️" if has_broken else "💿"
        
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {rig[3]} [{gpu_count}/{rig[4]} GPU | {cooler_count}/{rig[5]} 💨]",
            callback_data=f"rig_detail_{rig[0]}"
        )])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"rigs_page_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"rigs_page_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_rig_detail_keyboard(rig_id, gpu_slots, cooler_slots, gpu_installed, coolers_installed):
    """Клавиатура для детальной информации о риге"""
    buttons = []
    
    # Слоты для GPU
    row = []
    for i in range(gpu_slots):
        if i < len(gpu_installed) and gpu_installed[i] is not None:
            # Получаем информацию о GPU
            gpu = db.get_gpu_by_id(gpu_installed[i])
            if gpu:
                try:
                    is_broken = len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20
                    icon = "⚠️" if is_broken else "🖼"
                except (ValueError, TypeError):
                    icon = "🖼"
            else:
                icon = "❓"
        else:
            icon = "⬜"
        
        row.append(InlineKeyboardButton(text=icon, callback_data=f"rig_gpu_slot_{rig_id}_{i}"))
    
    buttons.append(row)
    
    # Слоты для куллеров
    if cooler_slots > 0:
        row = []
        for i in range(cooler_slots):
            if i < len(coolers_installed) and coolers_installed[i] is not None:
                cooler = db.get_cooler_by_id(coolers_installed[i])
                if cooler:
                    try:
                        is_broken = len(cooler) > 5 and cooler[5] is not None and cooler[5] <= 20
                        icon = "⚠️" if is_broken else "💨"
                    except (ValueError, TypeError):
                        icon = "💨"
                else:
                    icon = "❓"
            else:
                icon = "⬜"
            
            row.append(InlineKeyboardButton(text=icon, callback_data=f"rig_cooler_slot_{rig_id}_{i}"))
        
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="my_rigs")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_rig_gpu_slot_keyboard(rig_id, slot_index, is_empty, gpu_id=None, is_broken=False):
    """Клавиатура для слота GPU в риге"""
    buttons = []
    
    if is_empty:
        buttons.append([InlineKeyboardButton(text="➕ Установить GPU", callback_data=f"install_gpu_{rig_id}_{slot_index}")])
    else:
        # Кнопка просмотра/ремонта GPU
        if is_broken:
            buttons.append([InlineKeyboardButton(text="🔧 Починить GPU", callback_data=f"repair_gpu_{gpu_id}")])
        buttons.append([InlineKeyboardButton(text="📤 Вытащить GPU", callback_data=f"remove_gpu_{rig_id}_{slot_index}")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад к ригу", callback_data=f"rig_detail_{rig_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_rig_cooler_slot_keyboard(rig_id, slot_index, is_empty, cooler_id=None, is_broken=False):
    """Клавиатура для слота куллера в риге"""
    buttons = []
    
    if is_empty:
        buttons.append([InlineKeyboardButton(text="➕ Установить куллер", callback_data=f"install_cooler_{rig_id}_{slot_index}")])
    else:
        if is_broken:
            buttons.append([InlineKeyboardButton(text="🔧 Починить куллер", callback_data=f"repair_cooler_{cooler_id}")])
        buttons.append([InlineKeyboardButton(text="📤 Вытащить куллер", callback_data=f"remove_cooler_{rig_id}_{slot_index}")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад к ригу", callback_data=f"rig_detail_{rig_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_install_gpu_keyboard(user_id, rig_id, slot_index, gpus, page=0):
    items_per_page = 6
    total_pages = (len(gpus) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_gpus = gpus[start:end]
    
    buttons = []
    row = []
    
    for i, gpu in enumerate(page_gpus, 1):
        try:
            is_broken = len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20
            icon = "⚠️" if is_broken else "🖼"
        except (ValueError, TypeError):
            icon = "🖼"
        
        short_name = gpu[3][:10] + "..." if len(gpu[3]) > 10 else gpu[3]
        
        row.append(InlineKeyboardButton(
            text=f"{icon} {short_name}",
            callback_data=f"install_gpu_confirm_{rig_id}_{slot_index}_{gpu[0]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"install_gpu_page_{rig_id}_{slot_index}_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"install_gpu_page_{rig_id}_{slot_index}_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Назад к ригу", callback_data=f"rig_detail_{rig_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_install_cooler_keyboard(user_id, rig_id, slot_index, coolers, page=0):
    items_per_page = 6
    total_pages = (len(coolers) + items_per_page - 1) // items_per_page
    
    start = page * items_per_page
    end = start + items_per_page
    page_coolers = coolers[start:end]
    
    buttons = []
    row = []
    
    for i, cooler in enumerate(page_coolers, 1):
        try:
            is_broken = len(cooler) > 5 and cooler[5] is not None and cooler[5] <= 20
            icon = "⚠️" if is_broken else "💨"
        except (ValueError, TypeError):
            icon = "💨"
        
        short_name = cooler[3][:10] + "..." if len(cooler[3]) > 10 else cooler[3]
        
        row.append(InlineKeyboardButton(
            text=f"{icon} {short_name}",
            callback_data=f"install_cooler_confirm_{rig_id}_{slot_index}_{cooler[0]}"
        ))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"install_cooler_page_{rig_id}_{slot_index}_{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data="noop"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"install_cooler_page_{rig_id}_{slot_index}_{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data="noop"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton(text="◀️ Назад к ригу", callback_data=f"rig_detail_{rig_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_asic_detail_keyboard(asic_id, is_broken=False):
    """Клавиатура для детальной информации о ASIC"""
    buttons = []
    buttons.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="my_cards")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== СОСТОЯНИЯ FSM ====================
class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()
    waiting_for_ban_days = State()
    waiting_for_ban_reason = State()
    waiting_for_new_stock = State()
    waiting_for_remove_stock = State()
    waiting_for_photo = State()
    waiting_for_photo_key = State()

class UserStates(StatesGroup):
    waiting_for_nickname = State()
    waiting_for_transfer_target = State()
    waiting_for_transfer_amount = State()
    waiting_for_profile_photo = State()
    # Состояния для чеков/счётов
    check_type = State()
    check_username = State()
    check_amount = State()
    check_activations = State()
    check_comment = State()
    # Активация чека
    activate_check_code = State()
    # Анкета
    profile_about = State()

    profile_birthday = State()
    profile_city = State()
    profile_gender = State()


# ==================== ФОНОВАЯ ЗАДАЧА ====================
async def auto_restock_scheduler():
    while True:
        try:
            if db.check_and_restock():
                print("🔄 Запуск автоматического пополнения склада...")
                total, logs = db.auto_restock()
                
                if total > 0:
                    for admin_id in config.ADMIN_IDS:
                        try:
                            text = f"📦 Автоматическое пополнение склада\n\n"
                            text += f"✅ Добавлено: {total} товаров\n\n"
                            text += "Детали:\n"
                            text += "\n".join(logs[:15])
                            if len(logs) > 15:
                                text += f"\n... и ещё {len(logs) - 15} позиций"
                            
                            await bot.send_message(admin_id, text)
                        except:
                            pass
            
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"❌ Ошибка в авто-пополнении: {e}")
            await asyncio.sleep(60)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    referrer_id = None

    # Deeplink: /start priv_XXX — описание привилегии
    if len(args) > 1 and args[1].startswith("priv_"):
        db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        priv_key = args[1][5:]  # убираем "priv_"
        await _show_priv_info(message, priv_key)
        return

    # Deeplink: /start bundle_XXX — описание набора
    if len(args) > 1 and args[1].startswith("bundle_"):
        db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        bundle_key = args[1][7:]  # убираем "bundle_"
        await _show_priv_or_bundle(message, bundle_key)
        return

    # Deeplink: /start check_XXXXXXXX — активация чека/счёта
    if len(args) > 1 and args[1].startswith("check_"):
        code = args[1][6:].upper()
        db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        success, result = db.activate_check(code, message.from_user.id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 В профиль", callback_data="profile")]
        ])
        if success:
            amount = result["amount"]
            creator = result["creator"]
            check_type = result["check_type"]
            creator_name = creator[3] if creator else "Неизвестно"
            if check_type == "check":
                text = (
                    f"✅ <b>Чек активирован!</b>\n\n"
                    f"<blockquote>"
                    f"💰 Получено: <b>+{int(amount)} тон</b>\n"
                    f"👤 От: {escape_html(creator_name)}"
                    f"</blockquote>"
                )
                try:
                    await bot.send_message(creator[0],
                        f"🔔 Твой чек #{code} активирован! Осталось: {result['activations_left']}")
                except Exception:
                    pass
            else:
                text = (
                    f"✅ <b>Счёт оплачен!</b>\n\n"
                    f"<blockquote>"
                    f"💸 Оплачено: <b>{int(amount)} тон</b>\n"
                    f"👤 Получатель: {escape_html(creator_name)}"
                    f"</blockquote>"
                )
                try:
                    await bot.send_message(creator[0],
                        f"💰 Счёт #{code} оплачен! +{int(amount)} тон на твой счёт.")
                except Exception:
                    pass
        else:
            text = str(result)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        return

    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id == message.from_user.id:
            referrer_id = None

    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referrer_id
    )
    
    if referrer_id:
        referrer = db.get_user(referrer_id)
        if referrer:
            referrer_name = referrer[3] or referrer[2] or f"Player_{referrer[1]}"
            welcome_text = (
                f"👋 Добро пожаловать в <b>Mining Game</b>!\n\n"
                f"Ты пришел по приглашению от <b>{escape_html(referrer_name)}</b>! 🎉\n"
                f"Ты получил бонус: <b>{config.REFERRAL_BONUS_FOR_NEW} тон</b> и <b>{config.REFERRAL_EXP_FOR_NEW} опыта</b> ✨\n\n"
                f"<blockquote>"
                f"Здесь ты можешь зарабатывать тон, собирать GPU-риги и покупать ASIC-майнеры"
                f"</blockquote>\n\n"
                f"👇 <b>Выбери действие:</b>"
            )
        else:
            welcome_text = get_welcome_text()
    else:
        welcome_text = get_welcome_text()
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

def get_welcome_text():
    return (
        f"👋 Добро пожаловать в <b>Mining Game</b>!\n\n"
        f"<blockquote>"
        f"Здесь ты можешь зарабатывать тон, собирать GPU-риги и покупать ASIC-майнеры"
        f"</blockquote>\n\n"
        f"👇 <b>Выбери действие:</b>"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    help_text = (
        "📚 <b>Раздел помощи</b>\n\n"
        "<blockquote>"
        "Выбери интересующий тебя раздел ниже\n"
        "или введи команду напрямую"
        "</blockquote>"
    )
    
    await message.answer(help_text, reply_markup=get_help_keyboard(), parse_mode="HTML")

@dp.message(Command("mine"))
async def cmd_mine(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    mine_result = db.mine(message.from_user.id)
    # mine() возвращает (success, text) или (success, text, got_box)
    if len(mine_result) == 3:
        success, result, got_box = mine_result
    else:
        success, result = mine_result
        got_box = False

    if success and got_box:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Открыть бокс!", callback_data="open_box_now")]
        ])
    else:
        keyboard = None

    await message.answer(result, reply_markup=keyboard, parse_mode="HTML")
    if success:
        _qc = advance_quest(message.from_user.id, "mine")
        for _qq in _qc:
            await message.answer(
                f"✅ <b>Задание выполнено!</b>\n"
                f"{_qq['icon']} {_qq['desc']}\n"
                f"💰 +{_qq['reward_ton']} тон  ✨ +{_qq['reward_exp']} опыта",
                parse_mode="HTML")

@dp.message(Command("nick"))
async def cmd_nick(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        user = db.get_user(message.from_user.id)
        current_nick = user[3] if user else "неизвестно"
        await message.answer(
            f"❌ Использование: /nick новый_ник\n\n"
            f"Твой текущий ник: <b>{escape_html(current_nick)}</b>\n\n"
            f"Пример: /nick Крипто_Майнер",
            parse_mode="HTML"
        )
        return
    
    new_nick = args[1].strip()
    
    if len(new_nick) > 32:
        await message.answer("❌ Ник не может быть длиннее 32 символов!")
        return
    
    success, result = db.change_nickname(message.from_user.id, new_nick)
    await message.answer(result, parse_mode="HTML")

@dp.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        target_mid = int(args[1])
        target_user = db.get_user_by_custom_id(target_mid)
        if not target_user:
            await message.answer("❌ Игрок с таким MID не найден!")
            return
        await show_user_profile(message, target_user[0], is_own=False)
    else:
        await show_user_profile(message, message.from_user.id, is_own=True)

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
        await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
        advance_quest(message.from_user.id, "daily_bonus")
        return
    else:
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
    
    await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

@dp.message(Command("boxes"))
async def cmd_boxes(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    boxes_count = user[16] if user and len(user) > 16 else 0
    
    if boxes_count == 0:
        await message.answer("📦 У тебя пока нет коробок! Майни, чтобы получить коробки.")
        return
    
    boxes = db.get_user_boxes(message.from_user.id)
    
    text = f"📦 <b>Твои коробки:</b> {boxes_count} шт.\n\n"
    text += "Нажми на коробку, чтобы открыть:"
    
    await message.answer(
        text,
        reply_markup=get_boxes_keyboard(message.from_user.id, boxes, 0, True),
        parse_mode="HTML"
    )

@dp.message(Command("box"))
async def cmd_box(message: Message):
    """Меню боксов с кнопкой открытия"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return

    user = db.get_user(message.from_user.id)
    boxes_count = user[16] if user and len(user) > 16 else 0

    text = (
        f"📦 <b>Мои боксы</b>\n\n"
        f"<blockquote>"
        f"У тебя: <b>{boxes_count} 📦 боксов</b>\n\n"
        f"💡 Открыть один бокс:\n"
        f"   <code>/openbox</code>\n\n"
        f"💡 Открыть несколько (макс. 100):\n"
        f"   <code>/openbox 10</code>  или  <code>/openbox 100</code>"
        f"</blockquote>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📦 Открыть бокс ({boxes_count} шт.)" if boxes_count > 0 else "📦 Нет боксов",
            callback_data="open_box_now" if boxes_count > 0 else "no_boxes"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("rigs"))
async def cmd_rigs(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    rigs = db.get_user_rigs(message.from_user.id)
    
    if not rigs:
        text = "💿 <b>У тебя пока нет GPU-ригов!</b>\n\nКупи риг в магазине: /shop"
        await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
    else:
        text = "💿 <b>Твои GPU-риги</b>\n\nВыбери риг для настройки:"
        await message.answer(text, reply_markup=get_rigs_keyboard(message.from_user.id, rigs, 0), parse_mode="HTML")

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    shop_text = (
        f"🛒 <b>Здравствуйте! ДНС — ваш эксперт в графических решениях.</b>\n"
        f"<i>Подберем лучшую GPU или отличное охлаждение для твоей майнинг фермы!</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Каталог:</b>"
    )
    
    await message.answer(shop_text, reply_markup=get_shop_menu_keyboard(), parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    stats = db.get_stats()
    
    text = (
        f"⚡️<b>Статистика бота</b>\n\n"
        f"<blockquote>"
        f"⤷<b>Общий онлайн ››</b> {stats['total_users']}\n"
        f"  ⤷ Онлайн за 24ч ›› {stats['online_24h']}\n"
        f"  ⤷ Текущий онлайн ›› {stats['current_online']}\n\n"
        f"⤷<b>Тон у игроков ››</b> {stats['total_ton']:.0f}\n"
        f"  ⤷ Тон на чел ›› {stats['avg_ton']:.0f}\n"
        f"⤷<b>Общий HM/s ››</b> {stats['total_hash']:.0f}\n"
        f"  ⤷ HM/s на чел ›› {stats['avg_hash']:.1f}\n\n"
        f"⤷<b>Товара на складе ››</b> {stats['total_stock']} шт.\n"
        f"  ⤷ Видеокарты: {stats['gpu_stock']}\n"
        f"  ⤷ Куллеры: {stats['cooler_stock']}\n"
        f"  ⤷ ASIC: {stats['asic_stock']}\n"
        f"  ⤷ Риги: {stats['rig_stock']}\n\n"
        f"⤷<b>Продано всего:</b>\n"
        f"  ⤷ Видеокарт: {stats['total_cards_sold']}\n"
        f"  ⤷ Куллеров: {stats['total_coolers_sold']}\n"
        f"  ⤷ ASIC: {stats['total_asics_sold']}\n"
        f"  ⤷ Ригов: {stats['total_rigs_sold']}\n"
        f"⤷<b>Открыто коробок:</b> {stats['total_boxes_opened']}\n"
        f"⤷<b>Майнингов:</b> {stats['total_mining_actions']}\n"
        f"</blockquote>"
    )
    
    await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

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
    
    await show_level_info(message, message.from_user.id)

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
        
        text += f"🌟 Продолжай в том же духе!"
        
        await message.answer(text, parse_mode="HTML")

@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    user = db.get_user(message.from_user.id)
    referrals_count = user[6] if user[6] is not None else 0
    
    total_ton_bonus = referrals_count * config.REFERRAL_BONUS
    total_exp_bonus = referrals_count * config.REFERRAL_EXP_BONUS
    
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    
    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"<blockquote>"
        f"Каждому приглашённому другу начисляется бонус:\n"
        f"• Ему: +{config.REFERRAL_BONUS_FOR_NEW} тон и +{config.REFERRAL_EXP_FOR_NEW} опыта\n"
        f"• Тебе: +{config.REFERRAL_BONUS} тон и +{config.REFERRAL_EXP_BONUS} опыта\n"
        f"</blockquote>\n\n"
        f"📊 <b>Твоя статистика:</b>\n"
        f"├ 👤 Рефералов: {referrals_count}\n"
        f"├ 💰 Получено тон: {total_ton_bonus}\n"
        f"└ ✨ Получено опыта: {total_exp_bonus}\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{ref_link}</code>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=🔥 Присоединяйся к майнинг-боту! Получи бонус при регистрации!"),
            InlineKeyboardButton(text="👥 Отслеживать", callback_data="track_referrals")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(Command("inventory"))
async def cmd_inventory(message: Message):
    """Показывает весь инвентарь пользователя"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    # Получаем всё оборудование
    gpus = db.get_user_gpus(message.from_user.id, include_installed=True)
    coolers = db.get_user_coolers(message.from_user.id, include_installed=True)
    asics = db.get_user_asics(message.from_user.id)
    rigs = db.get_user_rigs(message.from_user.id)
    
    text = "📦 <b>Твой инвентарь</b>\n\n"
    
    # Видеокарты
    gpu_installed = len([g for g in gpus if g[6] == 1]) if gpus else 0
    gpu_free = len(gpus) - gpu_installed if gpus else 0
    text += f"🖼 Видеокарты: всего {len(gpus) if gpus else 0} шт. "
    text += f"(в ригах: {gpu_installed}, свободно: {gpu_free})\n"
    
    # Куллеры
    cooler_installed = len([c for c in coolers if c[6] == 1]) if coolers else 0
    cooler_free = len(coolers) - cooler_installed if coolers else 0
    text += f"💨 Куллеры: всего {len(coolers) if coolers else 0} шт. "
    text += f"(в ригах: {cooler_installed}, свободно: {cooler_free})\n"
    
    # ASIC
    text += f"💽 ASIC-майнеры: {len(asics) if asics else 0} шт.\n"
    
    # Риги
    text += f"💿 GPU-риги: {len(rigs) if rigs else 0} шт.\n\n"
    
    text += "Используй кнопки в профиле для управления."
    
    await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

# ==================== АДМИН КОМАНДЫ ====================

@dp.message(Command("pay"))
async def cmd_pay(message: Message):
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
        target = args[1]
        amount = int(args[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        target_user = None
        if target.startswith("mid:"):
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
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
        
        try:
            await message.bot.send_message(
                target_user[0],
                f"💰 Вам начислено {amount} тон администратором!"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат ID или суммы!")

@dp.message(Command("take"))
async def cmd_take(message: Message):
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
        target = args[1]
        amount = int(args[2])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной!")
            return
        
        target_user = None
        if target.startswith("mid:"):
            mid = int(target.replace("mid:", ""))
            target_user = db.get_user_by_custom_id(mid)
        else:
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
        
        try:
            await message.bot.send_message(
                target_user[0],
                f"💸 У вас списано {amount} тон администратором!"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат ID или суммы!")

@dp.message(Command("skl"))
async def cmd_skl(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа!")
        return
    
    db.cursor.execute('SELECT last_restock FROM auto_restock_log ORDER BY id DESC LIMIT 1')
    result = db.cursor.fetchone()
    
    db.cursor.execute('SELECT SUM(stock) FROM shop_gpus')
    gpu_stock = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute('SELECT SUM(stock) FROM shop_coolers')
    cooler_stock = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute('SELECT SUM(stock) FROM shop_asics')
    asic_stock = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute('SELECT SUM(stock) FROM shop_rigs')
    rig_stock = db.cursor.fetchone()[0] or 0
    
    total_stock = gpu_stock + cooler_stock + asic_stock + rig_stock
    
    text = f"📦 <b>Управление складом</b>\n\n"
    
    if result:
        last = datetime.fromisoformat(result[0])
        text += f"🕐 <b>Последнее пополнение:</b> {last.strftime('%d.%m.%Y %H:%M')}\n"
    else:
        text += f"🕐 <b>Последнее пополнение:</b> никогда\n"
    
    text += f"📊 <b>Всего товаров:</b> {total_stock} шт.\n"
    text += f"  ├ 🖥 Видеокарт: {gpu_stock}\n"
    text += f"  ├ 💨 Куллеров: {cooler_stock}\n"
    text += f"  ├ 💽 ASIC: {asic_stock}\n"
    text += f"  └ 💿 Ригов: {rig_stock}\n\n"
    text += f"👇 <b>Выбери действие:</b>"
    
    await message.answer(text, reply_markup=get_skl_keyboard(), parse_mode="HTML")

# ==================== ОБРАБОТЧИКИ КОЛБЭКОВ ====================

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    
    menu_text = (
        f"👋 <b>Главное меню</b>\n\n"
        f"<blockquote>"
        f"Здесь ты можешь зарабатывать тон, собирать GPU-риги и покупать ASIC-майнеры"
        f"</blockquote>\n\n"
        f"👇 <b>Выбери действие:</b>"
    )
    
    await callback.message.edit_text(
        menu_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

MKT_FILTER_OPTS = [
    ("all",       "Все товары"),
    ("gpu",       "Видеокарты (GPU)"),
    ("cooler",    "Куллеры"),
    ("component", "Компоненты"),
]


@dp.callback_query(F.data.startswith("mkt_filter_menu:"))
async def callback_mkt_filter_menu(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    sort = parts[1]
    page_str = parts[2]

    sorts = [
        ("Дешевле",  "price_asc"),
        ("Дороже",   "price_desc"),
        ("Хешрейт",  "hash_desc"),
        ("Износ",    "wear_desc"),
        ("Новые",    "new"),
    ]
    filter_labels = {"all": "Все", "gpu": "GPU", "cooler": "Куллеры", "component": "Компоненты"}

    buttons = []
    # Сортировка — 3 + 2
    buttons.append([
        InlineKeyboardButton(
            text=("✅ " if s[1] == sort else "") + s[0],
            callback_data=f"mkt_filter_menu:{s[1]}:{page_str}"
        ) for s in sorts[:3]
    ])
    buttons.append([
        InlineKeyboardButton(
            text=("✅ " if s[1] == sort else "") + s[0],
            callback_data=f"mkt_filter_menu:{s[1]}:{page_str}"
        ) for s in sorts[3:]
    ])
    # Категории
    buttons.append([
        InlineKeyboardButton(
            text=label,
            callback_data=f"mkt_sort:{sort}:{key}:{page_str}"
        ) for key, label in MKT_FILTER_OPTS
    ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"mkt_sort:{sort}:all:{page_str}")])

    await callback.message.edit_text(
        "🔍 <b>Фильтры барахолки</b>\n\nСортировка и категория:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()

@dp.callback_query(F.data == "daily_bonus")
async def callback_daily(callback: CallbackQuery):
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
        await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
        advance_quest(message.from_user.id, "daily_bonus")
        return
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
    
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "mine")
async def callback_mine(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    success, result = db.mine(callback.from_user.id)
    await callback.message.edit_text(result, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await show_user_profile(callback, callback.from_user.id, is_own=True)

@dp.callback_query(F.data.startswith("view_profile_"))
async def callback_view_profile(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    target_user_id = int(callback.data.split("_")[2])
    await show_user_profile(callback, target_user_id, is_own=False)

@dp.callback_query(F.data == "shop_menu")
async def callback_shop_menu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    shop_text = (
        f"🛒 <b>Здравствуйте! ДНС — ваш эксперт в графических решениях.</b>\n"
        f"<i>Подберем лучшую GPU или отличное охлаждение для твоей майнинг фермы!</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Каталог:</b>"
    )
    
    await callback.message.edit_text(shop_text, reply_markup=get_shop_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "shop_gpus")
async def callback_shop_gpus(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    items = db.get_shop_gpus()
    
    text = (
        f"🖥️ <b>Видеокарты на любой вкус и цвет:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_gpus_keyboard(items, 0), parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_gpus_page_"))
async def callback_shop_gpus_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    page = int(callback.data.split("_")[3])
    items = db.get_shop_gpus()
    
    text = (
        f"🖥️ <b>Видеокарты на любой вкус и цвет:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_gpus_keyboard(items, page), parse_mode="HTML")

@dp.callback_query(F.data == "shop_coolers")
async def callback_shop_coolers(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    items = db.get_shop_coolers()
    
    text = (
        f"💨 <b>Куллеры для охлаждения:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_coolers_keyboard(items, 0), parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_coolers_page_"))
async def callback_shop_coolers_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    page = int(callback.data.split("_")[3])
    items = db.get_shop_coolers()
    
    text = (
        f"💨 <b>Куллеры для охлаждения:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_coolers_keyboard(items, page), parse_mode="HTML")

@dp.callback_query(F.data == "shop_asics")
async def callback_shop_asics(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    items = db.get_shop_asics()
    
    text = (
        f"💽 <b>ASIC-майнеры для профессионального майнинга:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_asics_keyboard(items, 0), parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_asics_page_"))
async def callback_shop_asics_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    page = int(callback.data.split("_")[3])
    items = db.get_shop_asics()
    
    text = (
        f"💽 <b>ASIC-майнеры для профессионального майнинга:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_asics_keyboard(items, page), parse_mode="HTML")

@dp.callback_query(F.data == "shop_rigs")
async def callback_shop_rigs(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    items = db.get_shop_rigs()
    
    text = (
        f"💿 <b>GPU-риги для сборки майнинг фермы:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_rigs_keyboard(items, 0), parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_rigs_page_"))
async def callback_shop_rigs_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    page = int(callback.data.split("_")[3])
    items = db.get_shop_rigs()
    
    text = (
        f"💿 <b>GPU-риги для сборки майнинг фермы:</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ - в наличии\n"
        f"⛔ - нет на складе"
    )
    
    await callback.message.edit_text(text, reply_markup=get_shop_rigs_keyboard(items, page), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_gpu_"))
async def callback_buy_gpu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    gpu_key = callback.data.replace("buy_gpu_", "")
    
    db.cursor.execute('SELECT * FROM shop_gpus WHERE gpu_key = ?', (gpu_key,))
    gpu_data = db.cursor.fetchone()
    
    if not gpu_data:
        await callback.answer("❌ Карта не найдена!", show_alert=True)
        return
    
    gpu = {
        'key': gpu_key,
        'name': gpu_data[2],
        'hash_rate': gpu_data[3],
        'price': gpu_data[4],
        'stock': gpu_data[5],
        'power': gpu_data[6],
        'memory': gpu_data[7],
        'year': gpu_data[8]
    }
    
    photo_id = db.get_gpu_photo(gpu_key)
    
    user = db.get_user(callback.from_user.id)
    user_balance = int(user[4]) if user else 0
    in_stock = gpu['stock'] > 0
    
    detail_text = (
        f"🖥 <b>{gpu['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>Цена ››</b> {gpu['price']} тон\n"
        f"📦 <b>В наличии ››</b> {'✅' if in_stock else '⛔'} {gpu['stock'] if in_stock else 'нет на складе'}\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷⚡ Хешрейт ›› {gpu['hash_rate']} MH/s\n"
        f" ⤷⚡ Энергопотребление ›› {gpu['power']} Вт\n"
        f" ⤷💾 Память ›› {gpu['memory']} ГБ\n"
        f" ⤷📅 Год выпуска ›› {gpu['year']}\n\n"
        f"💰 <b>Твой баланс ››</b> {user_balance} тон"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_gpu_{gpu_key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_gpus")]
    ])
    
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=detail_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_cooler_"))
async def callback_buy_cooler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    cooler_key = callback.data.replace("buy_cooler_", "")
    
    db.cursor.execute('SELECT * FROM shop_coolers WHERE cooler_key = ?', (cooler_key,))
    cooler_data = db.cursor.fetchone()
    
    if not cooler_data:
        await callback.answer("❌ Куллер не найден!", show_alert=True)
        return
    
    cooler = {
        'key': cooler_key,
        'name': cooler_data[2],
        'price': cooler_data[3],
        'stock': cooler_data[4],
        'cooling_power': cooler_data[5],
        'noise': cooler_data[6],
        'power': cooler_data[7],
        'wear_reduction': cooler_data[8]
    }
    
    photo_id = db.get_cooler_photo(cooler_key)
    
    user = db.get_user(callback.from_user.id)
    user_balance = int(user[4]) if user else 0
    in_stock = cooler['stock'] > 0
    
    power_icon = get_cooler_power_icon(cooler['cooling_power'])
    
    detail_text = (
        f"💨 <b>{cooler['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>Цена ››</b> {cooler['price']} тон\n"
        f"📦 <b>В наличии ››</b> {'✅' if in_stock else '⛔'} {cooler['stock'] if in_stock else 'нет на складе'}\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷{power_icon} Мощность ›› {cooler['cooling_power']}\n"
        f" ⤷🔊 Шум ›› {cooler['noise']} дБ\n"
        f" ⤷⚡ Энергопотребление ›› {cooler['power']} Вт\n"
        f" ⤷🛡️ Защита от износа ›› {cooler['wear_reduction']}%\n\n"
        f"💰 <b>Твой баланс ››</b> {user_balance} тон"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_cooler_{cooler_key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_coolers")]
    ])
    
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=detail_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_asic_"))
async def callback_buy_asic(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    asic_key = callback.data.replace("buy_asic_", "")
    
    db.cursor.execute('SELECT * FROM shop_asics WHERE asic_key = ?', (asic_key,))
    asic_data = db.cursor.fetchone()
    
    if not asic_data:
        await callback.answer("❌ ASIC не найден!", show_alert=True)
        return
    
    asic = {
        'key': asic_key,
        'name': asic_data[2],
        'hash_rate': asic_data[3],
        'price': asic_data[4],
        'stock': asic_data[5],
        'power': asic_data[6],
        'wear_rate': asic_data[7],
        'noise': asic_data[8]
    }
    
    photo_id = db.get_asic_photo(asic_key)
    
    user = db.get_user(callback.from_user.id)
    user_balance = int(user[4]) if user else 0
    in_stock = asic['stock'] > 0
    
    power_icon = get_asic_power_icon(asic['hash_rate'])
    
    detail_text = (
        f"💽 <b>{asic['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>Цена ››</b> {asic['price']} тон\n"
        f"📦 <b>В наличии ››</b> {'✅' if in_stock else '⛔'} {asic['stock'] if in_stock else 'нет на складе'}\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷{power_icon} Хешрейт ›› {asic['hash_rate']} MH/s\n"
        f" ⤷⚡ Энергопотребление ›› {asic['power']} Вт\n"

        f" ⤷🔊 Шум ›› {asic['noise']} дБ\n\n"
        f"💰 <b>Твой баланс ››</b> {user_balance} тон"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_asic_{asic_key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_asics")]
    ])
    
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=detail_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_rig_"))
async def callback_buy_rig(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    rig_key = callback.data.replace("buy_rig_", "")
    
    db.cursor.execute('SELECT * FROM shop_rigs WHERE rig_key = ?', (rig_key,))
    rig_data = db.cursor.fetchone()
    
    if not rig_data:
        await callback.answer("❌ Риг не найден!", show_alert=True)
        return
    
    rig = {
        'key': rig_key,
        'name': rig_data[2],
        'price': rig_data[3],
        'stock': rig_data[4],
        'gpu_slots': rig_data[5],
        'cooler_slots': rig_data[6],
        'max_power': rig_data[7],
        'size': rig_data[8]
    }
    
    photo_id = db.get_rig_photo(rig_key)
    
    user = db.get_user(callback.from_user.id)
    user_balance = int(user[4]) if user else 0
    in_stock = rig['stock'] > 0
    
    size_icon = get_rig_size_icon(rig['size'])
    
    detail_text = (
        f"💿 <b>{rig['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 <b>Цена ››</b> {rig['price']} тон\n"
        f"📦 <b>В наличии ››</b> {'✅' if in_stock else '⛔'} {rig['stock'] if in_stock else 'нет на складе'}\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷{size_icon} Размер ›› {rig['size']}\n"
        f" ⤷🖥 Слотов для GPU ›› {rig['gpu_slots']}\n"
        f" ⤷💨 Слотов для куллеров ›› {rig['cooler_slots']}\n"
        f" ⤷⚡ Макс. мощность ›› {rig['max_power']} Вт\n\n"
        f"💰 <b>Твой баланс ››</b> {user_balance} тон"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить", callback_data=f"confirm_buy_rig_{rig_key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="shop_rigs")]
    ])
    
    if photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_id,
            caption=detail_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("confirm_buy_gpu_"))
async def callback_confirm_buy_gpu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    gpu_key = callback.data.replace("confirm_buy_gpu_", "")
    
    success, message = db.buy_gpu(callback.from_user.id, gpu_key)
    
    if success:
        text = f"✅ {message}\n\nКарта добавлена в твой инвентарь!"
    else:
        text = f"❌ {message}"
    
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_continue_shopping_keyboard("gpus"),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=get_continue_shopping_keyboard("gpus"), parse_mode="HTML")

@dp.callback_query(F.data.startswith("confirm_buy_cooler_"))
async def callback_confirm_buy_cooler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    cooler_key = callback.data.replace("confirm_buy_cooler_", "")
    
    success, message = db.buy_cooler(callback.from_user.id, cooler_key)
    
    if success:
        text = f"✅ {message}\n\nКуллер добавлен на твой склад!"
    else:
        text = f"❌ {message}"
    
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_continue_shopping_keyboard("coolers"),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=get_continue_shopping_keyboard("coolers"), parse_mode="HTML")

@dp.callback_query(F.data.startswith("confirm_buy_asic_"))
async def callback_confirm_buy_asic(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    asic_key = callback.data.replace("confirm_buy_asic_", "")
    
    success, message = db.buy_asic(callback.from_user.id, asic_key)
    
    if success:
        text = f"✅ {message}\n\nASIC-майнер добавлен в твой инвентарь!"
    else:
        text = f"❌ {message}"
    
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_continue_shopping_keyboard("asics"),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=get_continue_shopping_keyboard("asics"), parse_mode="HTML")

@dp.callback_query(F.data.startswith("confirm_buy_rig_"))
async def callback_confirm_buy_rig(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    rig_key = callback.data.replace("confirm_buy_rig_", "")
    
    success, message = db.buy_rig(callback.from_user.id, rig_key)
    
    if success:
        text = f"✅ {message}\n\nРиг добавлен в твой инвентарь! Используй /rigs для настройки."
    else:
        text = f"❌ {message}"
    
    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_continue_shopping_keyboard("rigs"),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=get_continue_shopping_keyboard("rigs"), parse_mode="HTML")

@dp.callback_query(F.data == "my_boxes")
async def callback_my_boxes(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    user = db.get_user(callback.from_user.id)
    boxes_count = user[16] if user and len(user) > 16 else 0
    
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
        reply_markup=get_boxes_keyboard(callback.from_user.id, boxes, 0, True),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("open_box_"))
async def callback_open_box(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    box_id = int(callback.data.split("_")[2])
    
    success, result = db.open_box(box_id)
    
    if success:
        await callback.message.edit_text(result, parse_mode="HTML")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 К коробкам", callback_data="my_boxes")],
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    else:
        await callback.answer(result, show_alert=True)

@dp.callback_query(F.data == "my_rigs")
async def callback_my_rigs(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()
    rigs = db.get_user_rigs(callback.from_user.id)
    asics = db.get_user_asics(callback.from_user.id)

    text = "💿 <b>Мои майнеры</b>\n\n"

    if asics:
        text += f"<b>💽 ASIC-майнеры ({len(asics)} шт.):</b>\n"
        for asic in asics:
            text += f"  ✅ {asic[3]} — {asic[4]} HM/s\n"
        text += "\n"

    if rigs:
        text += f"<b>💿 GPU-риги ({len(rigs)} шт.):</b>\nВыбери риг для настройки:"
        await callback.message.edit_text(text, reply_markup=get_rigs_keyboard(callback.from_user.id, rigs, 0), parse_mode="HTML")
    elif asics:
        text += "<i>GPU-ригов нет. Купи в /shop</i>"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop_menu")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="profile")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        text = "💿 <b>У тебя пока нет майнеров!</b>\n\nКупи ASIC или GPU-риг в магазине."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop_menu")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="profile")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("rig_detail_"))
async def callback_rig_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    rig_id = int(callback.data.split("_")[2])
    
    rig_data = db.get_rig_by_id(rig_id)
    if not rig_data:
        await callback.message.edit_text("❌ Риг не найден!")
        return
    
    gpus = db.get_rig_gpus(rig_id)
    coolers = db.get_rig_coolers(rig_id)
    
    # БЕЗОПАСНОЕ вычисление хешрейта
    total_hash = 0
    if gpus:
        for gpu in gpus:
            try:
                if len(gpu) > 4 and gpu[4] is not None:
                    total_hash += float(gpu[4])
            except (ValueError, TypeError, IndexError):
                continue
    
    cooler_bonus = 0
    if coolers:
        for cooler in coolers:
            try:
                if len(cooler) > 4 and cooler[4] is not None:
                    cooler_bonus += float(cooler[4]) * 0.1
            except (ValueError, TypeError, IndexError):
                continue
    
    total_hash_with_bonus = total_hash + (total_hash * cooler_bonus / 100) if total_hash > 0 else 0
    
    # Проверяем сломанные GPU
    broken_gpus = []
    if gpus:
        for gpu in gpus:
            try:
                if len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20:
                    broken_gpus.append(gpu)
            except (ValueError, TypeError, IndexError):
                continue
    
    # Проверяем сломанные куллеры
    broken_coolers = []
    if coolers:
        for cooler in coolers:
            try:
                if len(cooler) > 5 and cooler[5] is not None and cooler[5] <= 20:
                    broken_coolers.append(cooler)
            except (ValueError, TypeError, IndexError):
                continue
    
    warning = ""
    if broken_gpus or broken_coolers:
        warning = "⚠️ <b>Внимание!</b> Есть сломанное оборудование!\n\n"
    
    detail_text = (
        f"💿 <b>{rig_data[3]}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{warning}"
        f"📊 <b>Характеристики:</b>\n"
        f"├ 🖥 Слотов GPU: {rig_data[4]}\n"
        f"│  └ Установлено: {len(gpus) if gpus else 0}/{rig_data[4]}\n"
        f"├ 💨 Слотов куллеров: {rig_data[5]}\n"
        f"│  └ Установлено: {len(coolers) if coolers else 0}/{rig_data[5]}\n"
        f"└ ⚡ Хешрейт: {total_hash_with_bonus:.1f} MH/s\n\n"
        f"Слоты отмечены кнопками ниже:\n"
        f"🖼 - GPU, 💨 - Куллер, ⬜ - пусто, ⚠️ - сломано"
    )
    
    gpu_installed = json.loads(rig_data[6]) if rig_data[6] and rig_data[6] != '[]' else []
    coolers_installed = json.loads(rig_data[7]) if rig_data[7] and rig_data[7] != '[]' else []
    
    await callback.message.edit_text(
        detail_text,
        reply_markup=get_rig_detail_keyboard(rig_id, rig_data[4], rig_data[5], gpu_installed, coolers_installed),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("rig_gpu_slot_"))
async def callback_rig_gpu_slot(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[3])
    slot_index = int(parts[4])
    
    rig = db.get_rig_by_id(rig_id)
    if not rig:
        await callback.message.edit_text("❌ Риг не найден!")
        return
    
    gpu_installed = json.loads(rig[6]) if rig[6] and rig[6] != '[]' else []
    is_empty = slot_index >= len(gpu_installed) or gpu_installed[slot_index] is None
    
    text = f"Слот для GPU #{slot_index + 1}\n\n"
    gpu_id = None
    is_broken = False
    
    if not is_empty:
        gpu_id = gpu_installed[slot_index]
        gpu = db.get_gpu_by_id(gpu_id)
        if gpu:
            try:
                is_broken = len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20
                status = "⚠️ СЛОМАНА" if is_broken else "✅ РАБОЧАЯ"
                text += f"Установлена: {gpu[3]}\n"
                text += f"Состояние: {status} ({gpu[5]}%)\n"
                text += f"Хешрейт: {gpu[4]} MH/s\n"
                
                if is_broken:
                    text += f"\n⚠️ Карта сломана! Требуется ремонт."
            except (ValueError, TypeError):
                text += "❌ Ошибка: данные повреждены"
        else:
            text += "❌ Ошибка: GPU не найдена"
    else:
        text += "Слот пуст. Нажми 'Установить GPU', чтобы выбрать видеокарту."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_rig_gpu_slot_keyboard(rig_id, slot_index, is_empty, gpu_id, is_broken),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("rig_cooler_slot_"))
async def callback_rig_cooler_slot(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[3])
    slot_index = int(parts[4])
    
    rig = db.get_rig_by_id(rig_id)
    if not rig:
        await callback.message.edit_text("❌ Риг не найден!")
        return
    
    coolers_installed = json.loads(rig[7]) if rig[7] and rig[7] != '[]' else []
    is_empty = slot_index >= len(coolers_installed) or coolers_installed[slot_index] is None
    
    text = f"Слот для куллера #{slot_index + 1}\n\n"
    cooler_id = None
    is_broken = False
    
    if not is_empty:
        cooler_id = coolers_installed[slot_index]
        cooler = db.get_cooler_by_id(cooler_id)
        if cooler:
            try:
                is_broken = len(cooler) > 5 and cooler[5] is not None and cooler[5] <= 20
                status = "⚠️ СЛОМАН" if is_broken else "✅ РАБОЧИЙ"
                text += f"Установлен: {cooler[3]}\n"
                text += f"Состояние: {status} ({cooler[5]}%)\n"
                text += f"Мощность: {cooler[4]}\n"
                
                if is_broken:
                    text += f"\n⚠️ Куллер сломан! Требуется ремонт."
            except (ValueError, TypeError):
                text += "❌ Ошибка: данные повреждены"
        else:
            text += "❌ Ошибка: куллер не найден"
    else:
        text += "Слот пуст. Нажми 'Установить куллер', чтобы выбрать охлаждение."
    
    await callback.message.edit_text(
        text,
        reply_markup=get_rig_cooler_slot_keyboard(rig_id, slot_index, is_empty, cooler_id, is_broken),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("install_gpu_"))
async def callback_install_gpu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    if len(parts) == 4:
        rig_id = int(parts[2])
        slot_index = int(parts[3])
        
        gpus = db.get_free_gpus(callback.from_user.id)
        
        if not gpus:
            await callback.answer("❌ У тебя нет свободных видеокарт!", show_alert=True)
            return
        
        text = f"Выбери видеокарту для установки в слот #{slot_index + 1}:"
        await callback.message.edit_text(text, reply_markup=get_install_gpu_keyboard(callback.from_user.id, rig_id, slot_index, gpus, 0), parse_mode="HTML")
    elif len(parts) == 6:
        rig_id = int(parts[3])
        slot_index = int(parts[4])
        gpu_id = int(parts[5])
        
        success, message = db.install_gpu(rig_id, gpu_id, slot_index)
        
        if success:
            await callback.answer(message, show_alert=False)
            callback.data = f"rig_detail_{rig_id}"
            await callback_rig_detail(callback)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)

@dp.callback_query(F.data.startswith("install_cooler_"))
async def callback_install_cooler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    if len(parts) == 4:
        rig_id = int(parts[2])
        slot_index = int(parts[3])
        
        coolers = db.get_free_coolers(callback.from_user.id)
        
        if not coolers:
            await callback.answer("❌ У тебя нет свободных куллеров!", show_alert=True)
            return
        
        text = f"Выбери куллер для установки в слот #{slot_index + 1}:"
        await callback.message.edit_text(text, reply_markup=get_install_cooler_keyboard(callback.from_user.id, rig_id, slot_index, coolers, 0), parse_mode="HTML")
    elif len(parts) == 6:
        rig_id = int(parts[3])
        slot_index = int(parts[4])
        cooler_id = int(parts[5])
        
        success, message = db.install_cooler(rig_id, cooler_id, slot_index)
        
        if success:
            await callback.answer(message, show_alert=False)
            callback.data = f"rig_detail_{rig_id}"
            await callback_rig_detail(callback)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)

@dp.callback_query(F.data.startswith("install_gpu_page_"))
async def callback_install_gpu_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[4])
    slot_index = int(parts[5])
    page = int(parts[6])
    
    gpus = db.get_free_gpus(callback.from_user.id)
    
    text = f"Выбери видеокарту для установки в слот #{slot_index + 1}:"
    await callback.message.edit_text(text, reply_markup=get_install_gpu_keyboard(callback.from_user.id, rig_id, slot_index, gpus, page), parse_mode="HTML")

@dp.callback_query(F.data.startswith("install_cooler_page_"))
async def callback_install_cooler_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[4])
    slot_index = int(parts[5])
    page = int(parts[6])
    
    coolers = db.get_free_coolers(callback.from_user.id)
    
    text = f"Выбери куллер для установки в слот #{slot_index + 1}:"
    await callback.message.edit_text(text, reply_markup=get_install_cooler_keyboard(callback.from_user.id, rig_id, slot_index, coolers, page), parse_mode="HTML")

@dp.callback_query(F.data.startswith("remove_gpu_"))
async def callback_remove_gpu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[2])
    slot_index = int(parts[3])
    
    success, message = db.remove_gpu(rig_id, slot_index)
    
    if success:
        await callback.answer(message, show_alert=False)
        # Возвращаемся к деталям рига
        callback.data = f"rig_detail_{rig_id}"
        await callback_rig_detail(callback)
    else:
        await callback.answer(f"❌ {message}", show_alert=True)

@dp.callback_query(F.data.startswith("remove_cooler_"))
async def callback_remove_cooler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    parts = callback.data.split("_")
    rig_id = int(parts[2])
    slot_index = int(parts[3])
    
    success, message = db.remove_cooler(rig_id, slot_index)
    
    if success:
        await callback.answer(message, show_alert=False)
        callback.data = f"rig_detail_{rig_id}"
        await callback_rig_detail(callback)
    else:
        await callback.answer(f"❌ {message}", show_alert=True)

@dp.callback_query(F.data.startswith("repair_gpu_"))
async def callback_repair_gpu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    gpu_id = int(callback.data.split("_")[2])
    
    gpu = db.get_gpu_by_id(gpu_id)
    if not gpu or gpu[1] != callback.from_user.id:
        await callback.answer("❌ Эта видеокарта тебе не принадлежит!", show_alert=True)
        return
    
    if gpu[5] >= 100:
        await callback.answer("✅ Видеокарта уже в идеальном состоянии!", show_alert=True)
        return
    
    repair_cost = config.REPAIR_COST
    
    user = db.get_user(callback.from_user.id)
    if user[4] < repair_cost:
        await callback.answer(f"❌ Недостаточно тон! Нужно {repair_cost}", show_alert=True)
        return
    
    # Списываем деньги и чиним
    db.remove_gems(callback.from_user.id, repair_cost, callback.from_user.id)
    db.repair_gpu(gpu_id)
    
    # Обновляем хешрейт рига
    if gpu[7]:  # rig_id
        db.update_rig_hashrate(gpu[7], user_id=callback.from_user.id)
    
    await callback.answer("✅ Видеокарта отремонтирована!", show_alert=False)
    
    # Возвращаемся к слоту
    rig_id = gpu[7]
    slot_index = gpu[8]
    if rig_id and slot_index is not None:
        callback.data = f"rig_gpu_slot_{rig_id}_{slot_index}"
        await callback_rig_gpu_slot(callback)

@dp.callback_query(F.data.startswith("repair_cooler_"))
async def callback_repair_cooler(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    cooler_id = int(callback.data.split("_")[2])
    
    cooler = db.get_cooler_by_id(cooler_id)
    if not cooler or cooler[1] != callback.from_user.id:
        await callback.answer("❌ Этот куллер тебе не принадлежит!", show_alert=True)
        return
    
    if cooler[5] >= 100:
        await callback.answer("✅ Куллер уже в идеальном состоянии!", show_alert=True)
        return
    
    repair_cost = config.REPAIR_COST // 2
    
    user = db.get_user(callback.from_user.id)
    if user[4] < repair_cost:
        await callback.answer(f"❌ Недостаточно тон! Нужно {repair_cost}", show_alert=True)
        return
    
    db.remove_gems(callback.from_user.id, repair_cost, callback.from_user.id)
    db.repair_cooler(cooler_id)
    
    if cooler[7]:  # rig_id
        db.update_rig_hashrate(cooler[7], user_id=callback.from_user.id)
    
    await callback.answer("✅ Куллер отремонтирован!", show_alert=False)
    
    rig_id = cooler[7]
    slot_index = cooler[8]
    if rig_id and slot_index is not None:
        callback.data = f"rig_cooler_slot_{rig_id}_{slot_index}"
        await callback_rig_cooler_slot(callback)

# repair_asic удалён — ASIC не ломаются

@dp.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    stats = db.get_stats()
    
    text = (
        f"⚡️<b>Статистика бота</b>\n\n"
        f"<blockquote>"
        f"⤷<b>Общий онлайн ››</b> {stats['total_users']}\n"
        f"  ⤷ Онлайн за 24ч ›› {stats['online_24h']}\n"
        f"  ⤷ Текущий онлайн ›› {stats['current_online']}\n\n"
        f"⤷<b>Тон у игроков ››</b> {stats['total_ton']:.0f}\n"
        f"  ⤷ Тон на чел ›› {stats['avg_ton']:.0f}\n"
        f"⤷<b>Общий HM/s ››</b> {stats['total_hash']:.0f}\n"
        f"  ⤷ HM/s на чел ›› {stats['avg_hash']:.1f}\n\n"
        f"⤷<b>Товара на складе ››</b> {stats['total_stock']} шт.\n"
        f"  ⤷ Видеокарты: {stats['gpu_stock']}\n"
        f"  ⤷ Куллеры: {stats['cooler_stock']}\n"
        f"  ⤷ ASIC: {stats['asic_stock']}\n"
        f"  ⤷ Риги: {stats['rig_stock']}\n\n"
        f"⤷<b>Продано всего:</b>\n"
        f"  ⤷ Видеокарт: {stats['total_cards_sold']}\n"
        f"  ⤷ Куллеров: {stats['total_coolers_sold']}\n"
        f"  ⤷ ASIC: {stats['total_asics_sold']}\n"
        f"  ⤷ Ригов: {stats['total_rigs_sold']}\n"
        f"⤷<b>Открыто коробок:</b> {stats['total_boxes_opened']}\n"
        f"⤷<b>Майнингов:</b> {stats['total_mining_actions']}\n"
        f"</blockquote>"
    )
    
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "top_menu")
async def callback_top_menu(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.message.edit_text(
        "🏆 <b>Выбери топ, который хочешь увидеть</b>",
        reply_markup=get_top_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("top_"))
async def callback_top_category(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    category = callback.data.split("_")[1]
    results = db.get_top(category)
    
    titles = {
        "gems": "💰 Топ по тонам",
        "level": "📶 Топ по уровню",
        "hash": "⚡ Топ по хешрейту",
        "referrals": "👥 Топ по рефералам"
    }
    
    title = titles.get(category, "🏆 Топ")
    
    if not results:
        text = f"<b>{title}</b>\n\n<blockquote>Пока нет данных...</blockquote>"
    else:
        text = f"<b>{title}</b>\n\n<blockquote>"
        
        for i, res in enumerate(results, 1):
            # Проверяем структуру результата
            if len(res) >= 4:
                user_id = res[0]
                username = res[1]
                first_name = res[2]
                
                # Формируем имя
                if username:
                    name_display = f"@{username}"
                else:
                    name_display = escape_html(first_name or f"Игрок {i}")
                
                icon = get_top_icon(i)
                
                # Получаем значение в зависимости от категории
                if category == "gems":
                    value = f"{res[3]:.0f} тон"
                elif category == "level":
                    if len(res) >= 5:
                        value = f"{res[3]} ур. ({res[4]} опыта)"
                    else:
                        value = f"{res[3]} ур."
                elif category == "hash":
                    value = f"{res[3]:.1f} MH/s"
                elif category == "referrals":
                    value = f"{res[3]} рефералов"
                else:
                    value = str(res[3])
                
                profile_link = f"/profile {user_id}"
                text += f"{icon} <a href=\"{profile_link}\">{name_display}</a> — {value}\n"
        
        text += "</blockquote>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К выбору топа", callback_data="top_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "level")
async def callback_level(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await show_level_info(callback, callback.from_user.id)

@dp.callback_query(F.data == "level_up")
async def callback_level_up(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
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
        
        text += f"🌟 Продолжай в том же духе!"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 К уровню", callback_data="level")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "track_referrals")
async def callback_track_referrals(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()
    user = db.get_user(callback.from_user.id)
    referrals = db.get_user_referrals(callback.from_user.id)
    referrals_count = user[6] if user[6] is not None else 0
    
    total_ton_bonus = referrals_count * config.REFERRAL_BONUS
    total_exp_bonus = referrals_count * config.REFERRAL_EXP_BONUS
    
    if not referrals:
        text = (
            f"👥 <b>Отслеживание рефералов</b>\n\n"
            f"<blockquote>"
            f"У тебя пока нет рефералов"
            f"</blockquote>\n\n"
            f"📊 <b>Общая статистика:</b>\n"
            f"├ 👤 Рефералов: <b>0</b>\n"
            f"├ 💰 Получено тон: <b>0</b>\n"
            f"└ ✨ Получено опыта: <b>0</b>\n\n"
            f"💡 Пригласи друзей и получай бонусы!"
        )
    else:
        text = f"👥 <b>Отслеживание рефералов</b>\n\n"
        text += f"<blockquote>"
        text += f"📋 Список приглашенных:\n"
        text += f"━━━━━━━━━━━━━━━━━━━━\n"
        
        for i, ref in enumerate(referrals[:10], 1):
            name = ref[1] or ref[2] or f"Реферал {i}"
            level = ref[3]
            gems = ref[4]
            date = datetime.fromisoformat(ref[5]).strftime('%d.%m.%Y')
            
            if level < 5:
                level_icon = "🌱"
            elif level < 10:
                level_icon = "🌿"
            elif level < 20:
                level_icon = "🌳"
            else:
                level_icon = "👑"
            
            text += f"{i}. {escape_html(name)}\n"
            text += f"   ├ {level_icon} Ур. {level}\n"
            text += f"   ├ 💰 {gems} тон\n"
            text += f"   └ 📅 {date}\n\n"
        
        if len(referrals) > 10:
            text += f"... и ещё {len(referrals) - 10} рефералов\n"
        
        text += f"</blockquote>\n\n"
        
        text += f"📊 <b>Общая статистика:</b>\n"
        text += f"├ 👤 Рефералов: <b>{referrals_count}</b>\n"
        text += f"├ 💰 Получено тон: <b>{total_ton_bonus}</b>\n"
        text += f"└ ✨ Получено опыта: <b>{total_exp_bonus}</b>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="referrals_page")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "my_storage")
async def callback_my_storage(callback: CallbackQuery):
    """Показывает склад с компонентами, видеокартами и куллерами"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()

    gpus = db.get_free_gpus(callback.from_user.id)
    coolers = db.get_free_coolers(callback.from_user.id)
    components = {c[0]: c[1] for c in db.get_user_components(callback.from_user.id)}

    text = "📦 <b>Твой склад</b>\n\n"

    # Компоненты всегда вверху
    COMP_ICONS = {
        "🧩 Чип": "🧩", "⚙️ Вентилятор": "⚙️",
        "🔌 Кабель": "🔌", "🛡️ Радиатор": "🛡️", "💾 Микросхема": "💾"
    }
    total_comps = sum(components.values())
    text += f"<b>🔩 Компоненты для крафта ({total_comps} шт.):</b>\n"
    if components:
        for comp_name, icon in COMP_ICONS.items():
            amt = components.get(comp_name, 0)
            text += f"  {icon} {comp_name.split(' ', 1)[1]}: <b>{amt}</b>\n"
    else:
        text += "  Нет компонентов — открывай боксы\n"
    text += "\n"

    # Видеокарты
    if gpus:
        text += f"<b>🖼 Видеокарты ({len(gpus)} шт.):</b>\n"
        for gpu in gpus[:5]:
            try:
                is_broken = gpu[5] is not None and gpu[5] <= 20
                status = "⚠️" if is_broken else "✅"
                craft_tag = " ⚒️" if (len(gpu) > 9 and gpu[9]) else ""
                text += f"  {status} {gpu[3]}{craft_tag} — {gpu[4]} HM/s ({gpu[5]}%)\n"
            except:
                continue
        if len(gpus) > 5:
            text += f"  ... и ещё {len(gpus) - 5}\n"
        text += "\n"

    # Куллеры
    if coolers:
        text += f"<b>💨 Куллеры ({len(coolers)} шт.):</b>\n"
        for cooler in coolers[:5]:
            try:
                is_broken = cooler[5] is not None and cooler[5] <= 20
                status = "⚠️" if is_broken else "✅"
                text += f"  {status} {cooler[3]} — мощн. {cooler[4]} ({cooler[5]}%)\n"
            except:
                continue
        if len(coolers) > 5:
            text += f"  ... и ещё {len(coolers) - 5}\n"

    if not gpus and not coolers:
        text += "<i>Нет свободного оборудования. Купи в /shop</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Все видеокарты", callback_data="my_gpus"),
         InlineKeyboardButton(text="💨 Все куллеры", callback_data="my_coolers")],
        [InlineKeyboardButton(text="⚒️ Крафт", callback_data="craft_menu"),
         InlineKeyboardButton(text="🏪 Барахолка", callback_data="market")],
        [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "my_gpus")
async def callback_my_gpus(callback: CallbackQuery):
    """Показывает все видеокарты пользователя"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    await callback.answer()
    try:
        gpus = db.get_user_gpus(callback.from_user.id, include_installed=True)
        # Исключаем карты на барахолке (is_installed=2)
        gpus = [g for g in gpus if len(g) <= 6 or g[6] != 2]
        if not gpus:
            await callback.message.edit_text(
                "🖼 У тебя нет видеокарт!",
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        items = [('gpu', gpu) for gpu in gpus]
        text = "🖼 <b>Твои видеокарты</b>\n\nВыбери видеокарту для просмотра:"
        await callback.message.edit_text(
            text,
            reply_markup=get_mycards_keyboard(callback.from_user.id, items, 0),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"callback_my_gpus error: {e}")
        await callback.message.edit_text(f"❌ Ошибка загрузки: {e}", reply_markup=get_back_to_menu_keyboard())

@dp.callback_query(F.data == "my_coolers")
async def callback_my_coolers(callback: CallbackQuery):
    """Показывает все куллеры пользователя"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    await callback.answer()
    try:
        coolers = db.get_user_coolers(callback.from_user.id, include_installed=True)
        # Исключаем куллеры на барахолке (rig_id = -1)
        coolers = [c for c in coolers if len(c) <= 7 or c[7] != -1]
        if not coolers:
            await callback.message.edit_text(
                "💨 У тебя нет куллеров!",
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        items = [('cooler', cooler) for cooler in coolers]
        text = "💨 <b>Твои куллеры</b>\n\nВыбери куллер для просмотра:"
        await callback.message.edit_text(
            text,
            reply_markup=get_mycards_keyboard(callback.from_user.id, items, 0),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"callback_my_coolers error: {e}")
        await callback.message.edit_text(f"❌ Ошибка загрузки: {e}", reply_markup=get_back_to_menu_keyboard())

@dp.callback_query(F.data == "my_cards")
async def callback_my_cards(callback: CallbackQuery):
    """Показывает всё оборудование пользователя"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    # Получаем всё оборудование пользователя
    gpus = db.get_user_gpus(callback.from_user.id)
    coolers = db.get_user_coolers(callback.from_user.id)
    asics = db.get_user_asics(callback.from_user.id)
    rigs = db.get_user_rigs(callback.from_user.id)
    
    all_items = []
    
    # Добавляем GPU
    for gpu in gpus:
        all_items.append(('gpu', gpu))
    
    # Добавляем куллеры
    for cooler in coolers:
        all_items.append(('cooler', cooler))
    
    # Добавляем ASIC
    for asic in asics:
        all_items.append(('asic', asic))
    
    # Добавляем риги
    for rig in rigs:
        all_items.append(('rig', rig))
    
    if not all_items:
        await callback.message.edit_text(
            "🖥 У тебя нет оборудования!\n\n"
            "Купи что-нибудь в магазине: /shop",
            reply_markup=get_profile_keyboard()
        )
        return
    
    text = (
        "🖥 <b>Твое оборудование</b>\n\n"
        "🖼 - Видеокарта\n"
        "💨 - Куллер\n"
        "💽 - ASIC-майнер\n"
        "💿 - GPU-риг\n"
        "⚠️ - Сломано\n\n"
        "Выбери оборудование:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_mycards_keyboard(callback.from_user.id, all_items, 0),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("mycards_page_"))
async def callback_mycards_page(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    page = int(callback.data.split("_")[2])
    
    gpus = db.get_user_gpus(callback.from_user.id)
    coolers = db.get_user_coolers(callback.from_user.id)
    asics = db.get_user_asics(callback.from_user.id)
    rigs = db.get_user_rigs(callback.from_user.id)
    
    all_items = []
    for gpu in gpus:
        all_items.append(('gpu', gpu))
    for cooler in coolers:
        all_items.append(('cooler', cooler))
    for asic in asics:
        all_items.append(('asic', asic))
    for rig in rigs:
        all_items.append(('rig', rig))
    
    text = (
        "🖥 <b>Твое оборудование</b>\n\n"
        "🖼 - Видеокарта\n"
        "💨 - Куллер\n"
        "💽 - ASIC-майнер\n"
        "💿 - GPU-риг\n"
        "⚠️ - Сломано\n\n"
        "Выбери оборудование:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_mycards_keyboard(callback.from_user.id, all_items, page),
        parse_mode="HTML"
    )

def get_gpu_detail_keyboard(gpu_id, is_broken, is_installed, rig_id):
    """Клавиатура для детального просмотра видеокарты"""
    buttons = []
    if is_broken:
        buttons.append([InlineKeyboardButton(text="🔧 Починить", callback_data=f"repair_gpu_{gpu_id}")])
    if is_installed and rig_id:
        # Карта в риге - нужно знать slot_index для вытаскивания
        # Получим его из колонки slot_index
        buttons.append([InlineKeyboardButton(text="📤 Вытащить из рига", callback_data=f"gpu_pull_{gpu_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="my_gpus")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cooler_detail_keyboard(cooler_id, is_broken, is_installed, rig_id):
    """Клавиатура для детального просмотра куллера"""
    buttons = []
    if is_broken:
        buttons.append([InlineKeyboardButton(text="🔧 Починить", callback_data=f"repair_cooler_{cooler_id}")])
    if is_installed and rig_id:
        buttons.append([InlineKeyboardButton(text="📤 Вытащить из рига", callback_data=f"cooler_pull_{cooler_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="my_coolers")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data.startswith("mycard_detail_gpu_"))
async def callback_gpu_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    await callback.answer()
    try:
        # "mycard_detail_gpu_123" -> split("_") = [mycard, detail, gpu, 123]
        parts = callback.data.split("_")
        gpu_id = int(parts[-1])
    except (IndexError, ValueError) as e:
        await callback.message.edit_text(f"❌ Ошибка: {callback.data} -> {e}")
        return
    
    try:
        gpu = db.get_gpu_by_id(gpu_id)
        if not gpu:
            await callback.message.edit_text("❌ Видеокарта не найдена!")
            return

        is_broken = len(gpu) > 5 and gpu[5] is not None and gpu[5] <= 20
        status = "⚠️ СЛОМАНА" if is_broken else "✅ РАБОЧАЯ"
        is_installed = gpu[6] == 1
        rig_id = gpu[7] if is_installed else None
        craft_tag = " ⚒️" if (len(gpu) > 9 and gpu[9]) else ""

        detail_text = (
            f"🖼 <b>{gpu[3]}</b>{craft_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Характеристики:</b>\n"
            f" ⤷⚡ Хешрейт ›› {gpu[4]} MH/s\n"
            f" ⤷🔧 Состояние ›› {status} ({gpu[5]}%)\n"
        )
        if is_installed:
            detail_text += f" ⤷📌 Установлена в риг #{rig_id}\n"
        if is_broken:
            detail_text += f"\n⚠️ Карта сломана! Требуется ремонт."

        keyboard = get_gpu_detail_keyboard(gpu_id, is_broken, is_installed, rig_id)

        if not is_installed and gpu[6] == 0:
            try:
                c_price = db.conn.cursor()
                c_price.execute("SELECT gpu_key FROM user_gpus WHERE id = ?", (gpu_id,))
                gkey_row = c_price.fetchone()
                if gkey_row:
                    shop_price = db.market_get_shop_price("gpu", gpu_key=gkey_row[0])
                    quick_price = int(shop_price * 0.3) if shop_price else 0
                    if quick_price > 0:
                        kb_rows = list(keyboard.inline_keyboard)
                        kb_rows.append([InlineKeyboardButton(
                            text=f"💸 Быстрая продажа: {quick_price} тон (30%)",
                            callback_data=f"mkt_quick_sell_gpu:{gpu_id}:{quick_price}"
                        )])
                        keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)
            except Exception:
                pass

        await callback.message.edit_text(detail_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"gpu_detail error gpu_id={gpu_id}: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Ошибка открытия карты: {e}")
@dp.callback_query(F.data.startswith("mycard_detail_cooler_"))
async def callback_cooler_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    await callback.answer()
    try:
        parts = callback.data.split("_")
        cooler_id = int(parts[-1])
    except (IndexError, ValueError) as e:
        await callback.message.edit_text(f"❌ Ошибка: {callback.data} -> {e}")
        return
    
    cooler = db.get_cooler_by_id(cooler_id)
    if not cooler:
        await callback.message.edit_text("❌ Куллер не найден!")
        return
    
    is_broken = len(cooler) > 5 and cooler[5] is not None and cooler[5] <= 20
    status = "⚠️ СЛОМАН" if is_broken else "✅ РАБОЧИЙ"
    is_installed = cooler[6] == 1
    rig_id = cooler[7] if is_installed else None
    
    detail_text = (
        f"💨 <b>{cooler[3]}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷💨 Мощность ›› {cooler[4]}\n"
        f" ⤷🔧 Состояние ›› {status} ({cooler[5]}%)\n"
    )
    
    if is_installed:
        detail_text += f" ⤷📌 Установлен в риг #{rig_id}\n"
    
    if is_broken:
        detail_text += f"\n⚠️ Куллер сломан! Требуется ремонт."
    
    # Кнопки
    keyboard = get_cooler_detail_keyboard(cooler_id, is_broken, is_installed, rig_id)

    # Кнопка быстрой продажи 30% только если свободна
    if not is_installed and (cooler[6] == 0 if len(cooler) > 6 else True):
        c_price2 = db.conn.cursor()
        c_price2.execute("SELECT cooler_key, rig_id FROM user_coolers WHERE id = ?", (cooler_id,))
        crow = c_price2.fetchone()
        if crow and crow[1] is None:
            shop_price2 = db.market_get_shop_price("cooler", cooler_key=crow[0])
            quick_price2 = int(shop_price2 * 0.3) if shop_price2 else 0
            if quick_price2 > 0:
                kb_rows2 = list(keyboard.inline_keyboard)
                kb_rows2.append([InlineKeyboardButton(
                    text=f"💸 Быстрая продажа: {quick_price2} тон (30%)",
                    callback_data=f"mkt_quick_sell_cooler:{cooler_id}:{quick_price2}"
                )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows2)

    await callback.message.edit_text(
        detail_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("mycard_detail_asic_"))
async def callback_asic_detail(callback: CallbackQuery):
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    asic_id = int(callback.data.split("_")[3])
    
    asic = db.get_asic_by_id(asic_id)
    if not asic:
        await callback.message.edit_text("❌ ASIC не найден!")
        return
    
    is_broken = len(asic) > 5 and asic[5] is not None and asic[5] <= 20
    status = "⚠️ СЛОМАН" if is_broken else "✅ РАБОЧИЙ"
    
    detail_text = (
        f"💽 <b>{asic[3]}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Характеристики:</b>\n"
        f" ⤷⚡ Хешрейт ›› {asic[4]} MH/s\n"
        f" ⤷🔧 Состояние ›› {status} ({asic[5]}%)\n"
    )
    
    if is_broken:
        detail_text += f"\n⚠️ ASIC сломан! Требуется ремонт."
    
    # Кнопки
    keyboard = get_asic_detail_keyboard(asic_id, is_broken)
    
    await callback.message.edit_text(
        detail_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_menu")
async def callback_help_menu(callback: CallbackQuery):
    """Открывает меню помощи"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    help_text = (
        "📚 <b>Добро пожаловать в раздел помощи!</b>\n\n"
        "Здесь ты можешь узнать подробную информацию о каждом разделе бота.\n"
        "Выбери интересующий тебя раздел ниже:"
    )
    
    await callback.message.edit_text(
        help_text,
        reply_markup=get_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "back_to_help")
async def callback_back_to_help(callback: CallbackQuery):
    """Возврат в главное меню помощи"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    help_text = (
        "📚 <b>Добро пожаловать в раздел помощи!</b>\n\n"
        "Здесь ты можешь узнать подробную информацию о каждом разделе бота.\n"
        "Выбери интересующий тебя раздел ниже:"
    )
    
    await callback.message.edit_text(
        help_text,
        reply_markup=get_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_mine")
async def callback_help_mine(callback: CallbackQuery):
    """Помощь по майнингу"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "⛏ <b>Майнинг</b>\n\n"
        "Как работает:\n"
        "• Майнинг доступен 1 раз в час\n"
        "• Базовая награда: 10 тон\n"
        "• Каждое оборудование добавляет бонус к награде\n"
        "• Чем больше хешрейт, тем больше тон\n"
        "• Есть шанс получить коробку с лутом (10%)\n\n"
        "Команда: /mine"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_shop")
async def callback_help_shop(callback: CallbackQuery):
    """Помощь по магазину"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "🛒 <b>Магазин (ДНС)</b>\n\n"
        "Здесь ты можешь покупать оборудование для майнинга.\n\n"
        "<b>Категории:</b>\n"
        "• 🖥 Видеокарты - для установки в риги\n"
        "• 💨 Куллеры - охлаждение для ригов\n"
        "• 💽 ASIC-майнеры - готовые устройства\n"
        "• 💿 GPU-риги - корпуса для сборки\n\n"
        "✅ - в наличии\n"
        "⛔ - нет на складе\n\n"
        "Команда: /shop"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_profile")
async def callback_help_profile(callback: CallbackQuery):
    """Помощь по профилю"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "👤 <b>Профиль</b>\n\n"
        "В профиле отображается:\n"
        "• Твой MID (уникальный ID)\n"
        "• Уровень и опыт\n"
        "• Баланс тон\n"
        "• Общий хешрейт\n"
        "• Количество рефералов\n"
        "• Количество коробок\n\n"
        "Команды:\n"
        "• /profile - твой профиль\n"
        "• /profile [MID] - профиль другого игрока\n"
        "• /nick - сменить никнейм"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_equipment")
async def callback_help_equipment(callback: CallbackQuery):
    """Помощь по оборудованию"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "🖥 <b>Оборудование</b>\n\n"
        "<b>Типы:</b>\n"
        "• 🖼 Видеокарты - нужно устанавливать в риги\n"
        "• 💨 Куллеры - уменьшают износ видеокарт\n"
        "• 💽 ASIC-майнеры - работают сразу\n"
        "• 💿 GPU-риги - корпуса для сборки\n\n"
        "<b>Статусы:</b>\n"
        "• ✅ - рабочее\n"
        "• ⚠️ - сломано (нужен ремонт)\n\n"
        "Команда: /rigs - управление ригами"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_repair")
async def callback_help_repair(callback: CallbackQuery):
    """Помощь по ремонту"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        f"🔧 <b>Ремонт</b>\n\n"
        f"Оборудование изнашивается после каждого майнинга.\n\n"
        f"<b>Правила:</b>\n"
        f"• Базовая стоимость: {config.REPAIR_COST} тон\n"
        f"• Скидка от уровня и привилегии\n"
        f"• При износе ≤ 20% оборудование ломается\n"
        f"• Куллеры уменьшают износ видеокарт\n\n"
        f"Ремонт доступен в меню оборудования при нажатии на сломанный предмет."
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_referrals")
async def callback_help_referrals(callback: CallbackQuery):
    """Помощь по рефералам"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай бонусы!\n\n"
        f"<b>Бонусы:</b>\n"
        f"• За друга: +{config.REFERRAL_BONUS} тон и +{config.REFERRAL_EXP_BONUS} опыта\n"
        f"• Другу: +{config.REFERRAL_BONUS_FOR_NEW} тон и +{config.REFERRAL_EXP_FOR_NEW} опыта\n\n"
        f"Команда: /referrals"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_top")
async def callback_help_top(callback: CallbackQuery):
    """Помощь по топам"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "🏆 <b>Топ игроков</b>\n\n"
        "Рейтинг лучших игроков бота.\n\n"
        "<b>Категории:</b>\n"
        "• 💰 Топ по тонам\n"
        "• 📶 Топ по уровню\n"
        "• ⚡ Топ по хешрейту\n"
        "• 👥 Топ по рефералам\n\n"
        "Команда: /top"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_stats")
async def callback_help_stats(callback: CallbackQuery):
    """Помощь по статистике"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        "Общая статистика по всем пользователям.\n\n"
        "<b>Показатели:</b>\n"
        "• Онлайн за 24ч\n"
        "• Всего пользователей\n"
        "• Общее количество тон\n"
        "• Общий хешрейт\n"
        "• Товары на складах\n"
        "• Продажи\n"
        "• Открыто коробок\n\n"
        "Команда: /stats"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "help_boxes")
async def callback_help_boxes(callback: CallbackQuery):
    """Помощь по коробкам"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "📦 <b>Коробки с лутом</b>\n\n"
        "Коробки можно получить во время майнинга (шанс 10%).\n\n"
        "<b>В коробке можно найти:</b>\n"
        "• 💰 Тоны (50-200)\n"
        "• ✨ Опыт (20-100)\n"
        "• 🧩 Компоненты для крафта (30%)\n"
        "• 💨 Куллеры (5%)\n"
        "• 👑 Привилегии (1%)\n\n"
        "Команды: /boxes, /box"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_to_help_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "donate_menu")
async def callback_donate_menu(callback: CallbackQuery):
    """Меню доната (привилегий)"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    user = db.get_user(callback.from_user.id)
    current_privilege, until = db.get_user_privilege(callback.from_user.id)
    
    if current_privilege != "player":
        priv_data = config.PRIVILEGES[current_privilege]
        until_str = datetime.fromisoformat(until).strftime('%d.%m.%Y') if until else "навсегда"
        priv_line = f"{priv_data['icon']} {priv_data['name']} (до {until_str})"
    else:
        priv_line = "Обычный игрок"
    stars = user[18] if len(user) > 18 and user[18] else 0
    text = _donate_main_text(user, current_privilege, until)
    try:
        await callback.message.edit_text(text, reply_markup=get_donate_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=get_donate_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "buy_premium")
async def callback_buy_premium(callback: CallbackQuery):
    """Покупка премиум привилегии"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await buy_privilege(callback.message, "premium")

@dp.callback_query(F.data == "buy_vip")
async def callback_buy_vip(callback: CallbackQuery):
    """Покупка VIP привилегии"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await buy_privilege(callback.message, "vip")

@dp.callback_query(F.data == "buy_legend")
async def callback_buy_legend(callback: CallbackQuery):
    """Покупка легендарной привилегии"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await buy_privilege(callback.message, "legend")

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================


@dp.callback_query(F.data == "profile_settings")
async def callback_profile_settings(callback: CallbackQuery):
    """Меню настроек профиля"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    user = db.get_user(callback.from_user.id)
    current_nick = user[3] if user else "неизвестно"
    
    text = (
        f"⚙️ <b>Настройки профиля</b>\n\n"
        f"<blockquote>"
        f"👤 Текущий ник: <b>{escape_html(current_nick)}</b>\n\n"
        f"Что хочешь изменить?"
        f"</blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Сменить ник", callback_data="change_nickname_inline"),
         InlineKeyboardButton(text="🖼 Сменить фото", callback_data="change_profile_photo")],
        [InlineKeyboardButton(text="📋 Анкета", callback_data="profile_questionnaire")],
        [InlineKeyboardButton(text="🧾 Счета/Чеки", callback_data="checks_menu")],
        [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "change_nickname_inline")
async def callback_change_nickname_inline(callback: CallbackQuery, state: FSMContext):
    """Начинаем процесс смены ника"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    text = (
        "✏️ <b>Смена никнейма</b>\n\n"
        "Введи новый никнейм:\n"
        "<blockquote>"
        "• Максимум 32 символа\n"
        "• Ник должен быть уникальным"
        "</blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_settings")]
    ])
    
    await state.set_state(UserStates.waiting_for_nickname)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(UserStates.waiting_for_nickname, F.text[0] != "/")
async def process_nickname_change(message: Message, state: FSMContext):
    """Обрабатываем ввод нового ника"""
    await state.clear()
    
    new_nick = message.text.strip()
    
    if len(new_nick) > 32:
        await message.answer(
            "❌ Ник не может быть длиннее 32 символов!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в настройки", callback_data="profile_settings")]
            ])
        )
        return
    
    success, result = db.change_nickname(message.from_user.id, new_nick)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 В профиль", callback_data="profile")],
        [InlineKeyboardButton(text="⚙️ Назад в настройки", callback_data="profile_settings")]
    ])
    
    await message.answer(result, reply_markup=keyboard, parse_mode="HTML")


def build_questionnaire_text(user, profile, admin_tag=""):
    """Формирует текст анкеты"""
    created_at = datetime.fromisoformat(user[12])
    reg_str = created_at.strftime("%d.%m.%Y в %H:%M:%S")
    days_in_game = (datetime.now() - created_at).days

    # profile: user_id, birthday, gender, about, city, show_birthday
    birthday = profile[1] if profile and profile[1] else None
    gender_raw = profile[2] if profile and profile[2] else None
    about = profile[3] if profile and profile[3] else None
    city = profile[4] if profile and profile[4] else None
    show_bday = profile[5] if profile and profile[5] is not None else 1

    gender_icons = {"male": "♂️ Мужской", "female": "♀️ Женский", "other": "⚧️ Другой"}
    gender_str = gender_icons.get(gender_raw, "—")

    privilege, _ = db.get_user_privilege(user[0])
    priv_data = config.PRIVILEGES.get(privilege, config.PRIVILEGES["player"])

    text = f"📋 <b>Твоя анкета:</b>\n\n<blockquote>"
    text += f"✏️ Регистрация » {reg_str}\n\n"
    text += f"🖊 Никнейм » <b>{escape_html(user[3])}</b>{admin_tag}\n"
    text += f"🏙 Город » {escape_html(city) if city else '—'}\n"

    if show_bday and birthday:
        text += f"🗓 Дата рождения » {birthday}\n"
    elif not show_bday:
        text += f"🗓 Дата рождения » <i>скрыта</i>\n"
    else:
        text += f"🗓 Дата рождения » —\n"

    text += f"  └ Пол » {gender_str}\n\n"

    text += f"📝 О себе »\n"
    if about:
        text += f"\n{escape_html(about)}\n\n"
    else:
        text += f"\n<i>не заполнено</i>\n\n"

    text += f"{priv_data['icon']} Статус » {priv_data['name']}\n"
    text += f"📅 Дней в игре » {days_in_game}\n"
    text += f"</blockquote>"
    return text


@dp.callback_query(F.data == "profile_questionnaire")
async def callback_profile_questionnaire(callback: CallbackQuery):
    """Анкета игрока"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    await callback.answer()

    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Ошибка!", show_alert=True)
        return

    profile = db.get_user_profile(callback.from_user.id)
    admin_tag = " 👑 АДМИН" if is_admin(callback.from_user.id) else ""
    text = build_questionnaire_text(user, profile, admin_tag)

    show_bday = profile[5] if profile and profile[5] is not None else 1
    bday_btn = "🙈 Скрыть ДР" if show_bday else "👁 Показать ДР"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Никнейм", callback_data="q_edit_nick")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="q_edit_city"),
         InlineKeyboardButton(text="🗓 Дата рожд.", callback_data="q_edit_birthday")],
        [InlineKeyboardButton(text="⚧️ Пол", callback_data="q_edit_gender"),
         InlineKeyboardButton(text=bday_btn, callback_data="q_toggle_birthday")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="q_edit_about")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_settings")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# ── Редактирование анкеты: каждое поле ──────────────────────────────

@dp.callback_query(F.data == "q_toggle_birthday")
async def q_toggle_birthday(callback: CallbackQuery):
    await callback.answer()
    profile = db.get_user_profile(callback.from_user.id)
    current = profile[5] if profile and profile[5] is not None else 1
    db.update_user_profile(callback.from_user.id, 'show_birthday', 0 if current else 1)
    await callback_profile_questionnaire(callback)


@dp.callback_query(F.data == "q_edit_nick")
async def q_edit_nick(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserStates.waiting_for_nickname)
    await state.update_data(from_questionnaire=True)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_questionnaire")]
    ])
    await callback.message.edit_text(
        "✏️ <b>Введи новый никнейм:</b>\n\n"
        "<blockquote>От 2 до 20 символов. Без спецсимволов.</blockquote>",
        reply_markup=keyboard, parse_mode="HTML"
    )


@dp.callback_query(F.data == "q_edit_city")
async def q_edit_city(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserStates.profile_city)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_questionnaire")]
    ])
    await callback.message.edit_text(
        "🏙 <b>Введи свой город:</b>\n\n"
        "<blockquote>Например: Москва, Минск, Алматы</blockquote>",
        reply_markup=keyboard, parse_mode="HTML"
    )

@dp.message(UserStates.profile_city, F.text[0] != "/")
async def process_profile_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) > 50:
        await message.answer("❌ Слишком длинно! Макс. 50 символов.")
        return
    db.update_user_profile(message.from_user.id, 'city', city)
    await state.clear()
    user = db.get_user(message.from_user.id)
    profile = db.get_user_profile(message.from_user.id)
    admin_tag = " 👑 АДМИН" if is_admin(message.from_user.id) else ""
    text = build_questionnaire_text(user, profile, admin_tag)
    show_bday = profile[5] if profile and profile[5] is not None else 1
    bday_btn = "🙈 Скрыть ДР" if show_bday else "👁 Показать ДР"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Никнейм", callback_data="q_edit_nick")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="q_edit_city"),
         InlineKeyboardButton(text="🗓 Дата рожд.", callback_data="q_edit_birthday")],
        [InlineKeyboardButton(text="⚧️ Пол", callback_data="q_edit_gender"),
         InlineKeyboardButton(text=bday_btn, callback_data="q_toggle_birthday")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="q_edit_about")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_settings")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "q_edit_birthday")
async def q_edit_birthday(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserStates.profile_birthday)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_questionnaire")]
    ])
    await callback.message.edit_text(
        "🗓 <b>Введи дату рождения:</b>\n\n"
        "<blockquote>Формат: ДД.ММ  (например: 18.07)\n"
        "Или: ДД.ММ.ГГГГ  (например: 18.07.2000)</blockquote>",
        reply_markup=keyboard, parse_mode="HTML"
    )

@dp.message(UserStates.profile_birthday, F.text[0] != "/")
async def process_profile_birthday(message: Message, state: FSMContext):
    import re
    text_in = message.text.strip()
    if not re.match(r'^\d{2}\.\d{2}(\.\d{4})?$', text_in):
        await message.answer("❌ Неверный формат! Введи ДД.ММ или ДД.ММ.ГГГГ")
        return
    db.update_user_profile(message.from_user.id, 'birthday', text_in)
    await state.clear()
    user = db.get_user(message.from_user.id)
    profile = db.get_user_profile(message.from_user.id)
    admin_tag = " 👑 АДМИН" if is_admin(message.from_user.id) else ""
    text = build_questionnaire_text(user, profile, admin_tag)
    show_bday = profile[5] if profile and profile[5] is not None else 1
    bday_btn = "🙈 Скрыть ДР" if show_bday else "👁 Показать ДР"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Никнейм", callback_data="q_edit_nick")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="q_edit_city"),
         InlineKeyboardButton(text="🗓 Дата рожд.", callback_data="q_edit_birthday")],
        [InlineKeyboardButton(text="⚧️ Пол", callback_data="q_edit_gender"),
         InlineKeyboardButton(text=bday_btn, callback_data="q_toggle_birthday")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="q_edit_about")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_settings")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "q_edit_gender")
async def q_edit_gender(callback: CallbackQuery):
    await callback.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♂️ Мужской", callback_data="q_gender_male"),
         InlineKeyboardButton(text="♀️ Женский", callback_data="q_gender_female")],
        [InlineKeyboardButton(text="⚧️ Другой", callback_data="q_gender_other"),
         InlineKeyboardButton(text="❌ Не указывать", callback_data="q_gender_none")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_questionnaire")]
    ])
    await callback.message.edit_text(
        "⚧️ <b>Выбери пол:</b>", reply_markup=keyboard, parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("q_gender_"))
async def q_set_gender(callback: CallbackQuery):
    await callback.answer()
    val = callback.data.replace("q_gender_", "")
    if val == "none":
        db.update_user_profile(callback.from_user.id, 'gender', None)
    else:
        db.update_user_profile(callback.from_user.id, 'gender', val)
    await callback_profile_questionnaire(callback)


@dp.callback_query(F.data == "q_edit_about")
async def q_edit_about(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserStates.profile_about)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_questionnaire")]
    ])
    await callback.message.edit_text(
        "📝 <b>Расскажи о себе:</b>\n\n"
        "<blockquote>Макс. 200 символов. Это будет видно другим игрокам в твоей анкете.</blockquote>",
        reply_markup=keyboard, parse_mode="HTML"
    )

@dp.message(UserStates.profile_about, F.text[0] != "/")
async def process_profile_about(message: Message, state: FSMContext):
    about = message.text.strip()
    if len(about) > 200:
        await message.answer(f"❌ Слишком длинно! Макс. 200 символов (у тебя {len(about)}).")
        return
    db.update_user_profile(message.from_user.id, 'about', about)
    await state.clear()
    user = db.get_user(message.from_user.id)
    profile = db.get_user_profile(message.from_user.id)
    admin_tag = " 👑 АДМИН" if is_admin(message.from_user.id) else ""
    text = build_questionnaire_text(user, profile, admin_tag)
    show_bday = profile[5] if profile and profile[5] is not None else 1
    bday_btn = "🙈 Скрыть ДР" if show_bday else "👁 Показать ДР"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Никнейм", callback_data="q_edit_nick")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="q_edit_city"),
         InlineKeyboardButton(text="🗓 Дата рожд.", callback_data="q_edit_birthday")],
        [InlineKeyboardButton(text="⚧️ Пол", callback_data="q_edit_gender"),
         InlineKeyboardButton(text=bday_btn, callback_data="q_toggle_birthday")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="q_edit_about")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_settings")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")



# ==================== ПЕРЕВОДЫ ТОН ====================

@dp.callback_query(F.data == "transfer_start")
async def callback_transfer_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса перевода тон"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()

    text = (
        "💸 <b>Перевод тон</b>\n\n"
        "<blockquote>"
        "Введи MID игрока, которому хочешь отправить тоны.\n\n"
        "💡 MID можно найти в профиле игрока"
        "</blockquote>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
    ])

    await state.set_state(UserStates.waiting_for_transfer_target)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(UserStates.waiting_for_transfer_target, F.text[0] != "/")
async def process_transfer_target(message: Message, state: FSMContext):
    """Получаем MID получателя"""
    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "❌ MID должен быть числом! Попробуй ещё раз или нажми отмену.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
            ])
        )
        return

    target_mid = int(text)
    target_user = db.get_user_by_custom_id(target_mid)

    if not target_user:
        await message.answer(
            f"❌ Игрок с MID <b>{target_mid}</b> не найден!\n\nПроверь MID и попробуй ещё раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
            ]),
            parse_mode="HTML"
        )
        return

    if target_user[0] == message.from_user.id:
        await message.answer(
            "❌ Нельзя переводить самому себе!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
            ])
        )
        return

    await state.update_data(target_user_id=target_user[0], target_name=target_user[3], target_mid=target_mid)
    await state.set_state(UserStates.waiting_for_transfer_amount)

    sender = db.get_user(message.from_user.id)
    sender_balance = int(sender[4]) if sender else 0

    await message.answer(
        f"✅ Получатель найден: <b>{escape_html(target_user[3])}</b> (MID: {target_mid})\n\n"
        f"💰 Твой баланс: <b>{sender_balance} тон</b>\n\n"
        f"Введи сумму перевода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
        ]),
        parse_mode="HTML"
    )


@dp.message(UserStates.waiting_for_transfer_amount, F.text[0] != "/")
async def process_transfer_amount(message: Message, state: FSMContext):
    """Получаем сумму и совершаем перевод"""
    text = message.text.strip()

    if not text.isdigit() or int(text) <= 0:
        await message.answer(
            "❌ Введи корректную сумму (целое положительное число).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]
            ])
        )
        return

    amount = int(text)
    data = await state.get_data()
    target_user_id = data["target_user_id"]
    target_name = data["target_name"]
    target_mid = data["target_mid"]

    await state.clear()

    success, result = db.transfer_tons(message.from_user.id, target_user_id, amount)

    if success:
        receiver = result
        # Уведомление получателю
        sender = db.get_user(message.from_user.id)
        sender_name = sender[3] if sender else "Игрок"
        try:
            await bot.send_message(
                target_user_id,
                f"💸 <b>Входящий перевод!</b>\n\n"
                f"От: <b>{escape_html(sender_name)}</b>\n"
                f"Сумма: <b>+{amount} тон</b>\n\n"
                f"💰 Проверь свой баланс в профиле!",
                parse_mode="HTML"
            )
        except Exception:
            pass

        sender_after = db.get_user(message.from_user.id)
        new_balance = int(sender_after[4]) if sender_after else 0

        await message.answer(
            f"✅ <b>Перевод выполнен!</b>\n\n"
            f"<blockquote>"
            f"💸 Отправлено: <b>{amount} тон</b>\n"
            f"👤 Получатель: <b>{escape_html(target_name)}</b> (MID: {target_mid})\n"
            f"💰 Твой баланс: <b>{new_balance} тон</b>"
            f"</blockquote>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧾 Мои чеки", callback_data="my_transfers")],
                [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
            ]),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            result,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
            ])
        )


@dp.callback_query(F.data == "my_transfers")
async def callback_my_transfers(callback: CallbackQuery):
    """Показывает историю переводов"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()

    user_id = callback.from_user.id
    transfers = db.get_user_transfers(user_id, limit=15)

    if not transfers:
        text = (
            "🧾 <b>Мои чеки</b>\n\n"
            "<blockquote>У тебя пока нет переводов</blockquote>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Сделать перевод", callback_data="transfer_start")],
            [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    text = "🧾 <b>История переводов</b>\n\n<blockquote>"

    for t in transfers:
        t_id, from_id, to_id, amount, comment, created_at, from_name, to_name = t
        dt = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")

        if from_id == user_id:
            # Исходящий
            text += f"📤 <b>-{int(amount)} тон</b> → {escape_html(to_name or '?')}\n"
        else:
            # Входящий
            text += f"📥 <b>+{int(amount)} тон</b> ← {escape_html(from_name or '?')}\n"

        if comment:
            text += f"   💬 {escape_html(comment)}\n"
        text += f"   🕐 {dt}\n\n"

    text += "</blockquote>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Новый перевод", callback_data="transfer_start")],
        [InlineKeyboardButton(text="◀️ В профиль", callback_data="profile")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# ==================== ФОТО ПРОФИЛЯ ====================

@dp.callback_query(F.data == "change_profile_photo")
async def callback_change_profile_photo(callback: CallbackQuery, state: FSMContext):
    """Начало смены фото профиля"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()

    current_photo = db.get_profile_photo(callback.from_user.id)
    has_photo = current_photo is not None

    text = (
        "🖼 <b>Фото профиля</b>\n\n"
        "<blockquote>"
        + ("✅ Фото профиля установлено\n\n" if has_photo else "")
        + "Отправь новое фото или выбери действие:"
        "</blockquote>"
    )

    buttons = [
        [InlineKeyboardButton(text="📸 Отправить фото", callback_data="send_profile_photo_hint")]
    ]
    if has_photo:
        buttons.append([InlineKeyboardButton(text="🗑 Удалить фото", callback_data="delete_profile_photo")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад в настройки", callback_data="profile_settings")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await state.set_state(UserStates.waiting_for_profile_photo)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "send_profile_photo_hint")
async def callback_send_photo_hint(callback: CallbackQuery):
    await callback.answer("📸 Просто отправь фото в чат!", show_alert=True)


@dp.callback_query(F.data == "delete_profile_photo")
async def callback_delete_profile_photo(callback: CallbackQuery, state: FSMContext):
    """Удаляет фото профиля"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await state.clear()
    db.delete_profile_photo(callback.from_user.id)
    await callback.answer("🗑 Фото профиля удалено!", show_alert=False)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в настройки", callback_data="profile_settings")]
    ])
    await callback.message.edit_text(
        "✅ Фото профиля удалено.",
        reply_markup=keyboard
    )


@dp.message(UserStates.waiting_for_profile_photo, F.photo)
async def process_profile_photo(message: Message, state: FSMContext):
    """Сохраняем новое фото профиля"""
    await state.clear()

    # Берём максимальное разрешение
    photo = message.photo[-1]
    photo_id = photo.file_id

    db.set_profile_photo(message.from_user.id, photo_id)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 В профиль", callback_data="profile")],
        [InlineKeyboardButton(text="⚙️ В настройки", callback_data="profile_settings")]
    ])

    await message.answer_photo(
        photo=photo_id,
        caption="✅ <b>Фото профиля обновлено!</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.message(UserStates.waiting_for_profile_photo, F.text[0] != "/")
async def process_profile_photo_wrong(message: Message, state: FSMContext):
    """Если прислали не фото"""
    await message.answer(
        "❌ Пожалуйста, отправь именно <b>фото</b> (не файл и не стикер).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_settings")]
        ]),
        parse_mode="HTML"
    )


async def show_user_profile(message_or_callback, user_id, is_own=True):
    user = db.get_user(user_id)
    if not user:
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer("❌ Ошибка: профиль не найден")
        else:
            await message_or_callback.message.edit_text("❌ Ошибка: профиль не найден")
        return
    
    first_name = user[3]
    admin_tag = " АДМИН" if is_admin(user_id) else ""
    
    created_at = datetime.fromisoformat(user[12])
    hours_in_game = int((datetime.now() - created_at).total_seconds() / 3600)
    
    level = user[10] if user[10] is not None else 1
    exp = user[11] if user[11] is not None else 0
    ton = int(user[4]) if user[4] is not None else 0
    hash_rate = float(user[5]) if user[5] is not None else 0.0
    referrals = user[6] if user[6] is not None else 0
    boxes_count = user[16] if len(user) > 16 and user[16] is not None else 0
    
    mid = user[1]
    
    if is_own:
        profile_title = f"<b>👤 Твой профиль</b>"
    else:
        profile_title = f"<b>👤 Профиль игрока {escape_html(first_name)}</b>"
    
    profile_text = (
        f"{profile_title}\n\n"
        f"<blockquote>"
        f"{escape_html(first_name)}{admin_tag}\n"
        f"├ MID ›› {mid}\n"
        f"├ Уровень ›› {level}\n"
        f"│  └ Опыт ›› {exp}\n"
        f"└ В игре ›› {hours_in_game} ч\n"
        f"\n"
        f"<b>Баланс:</b>\n"
        f"├ Тон ›› {ton}\n"
        f"└ Хешрейт ›› {hash_rate:.1f} MH/s\n"
        f"\n"
        f"<b>Статистика:</b>\n"
        f"├ Рефералов ›› {referrals}\n"
        f"└ Коробок ›› {boxes_count}\n"
        f"</blockquote>\n\n"
    )
    
    if is_own:
        profile_text += f"💡 Смени ник в ⚙️ Настройках"
    
    keyboard = get_profile_keyboard(user_id if not is_own else None)
    profile_photo = db.get_profile_photo(user_id)
    
    if isinstance(message_or_callback, Message):
        if profile_photo:
            try:
                await message_or_callback.answer_photo(
                    photo=profile_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                await message_or_callback.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        if profile_photo:
            try:
                await message_or_callback.message.delete()
                await message_or_callback.message.answer_photo(
                    photo=profile_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                try:
                    await message_or_callback.message.edit_text(profile_text, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    await message_or_callback.message.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            try:
                await message_or_callback.message.edit_text(profile_text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                await message_or_callback.message.answer(profile_text, reply_markup=keyboard, parse_mode="HTML")

async def show_level_info(message_or_callback, user_id):
    user = db.get_user(user_id)
    if not user:
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer("❌ Ошибка: профиль не найден")
        else:
            await message_or_callback.message.edit_text("❌ Ошибка: профиль не найден")
        return
    
    nick = user[3] or user[2] or f"Player_{user[1]}"
    current_level = user[10]
    current_exp = user[11]
    current_ton = int(user[4])
    
    next_level = current_level + 1
    ton_cost, exp_cost, error = db.get_level_up_cost(current_level)
    
    next_reward = config.LEVEL_REWARDS.get(next_level, {"ton": 0, "exp": 0, "bonus": "Нет награды"})
    
    level_icon = get_level_icon(current_level)
    
    if current_level < config.MAX_LEVEL and ton_cost and exp_cost:
        text = (
            f"{level_icon} <b>Повышение уровня: {current_level} ›› {next_level}</b>\n\n"
            f"<blockquote>"
            f"👤 {escape_html(nick)}\n\n"
            f"💰 Тон ›› {current_ton} | {ton_cost}\n"
            f"✨ Опыт ›› {current_exp} | {exp_cost}\n\n"
            f"🎖️ Награда ›› {next_reward['bonus']}"
            f"</blockquote>\n\n"
            f"При повышении с вас вычтут необходимый опыт и тон!"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Повысить уровень", callback_data="level_up")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ])
    else:
        if current_level >= config.MAX_LEVEL:
            text = f"{level_icon} <b>🏆 Достигнут максимальный уровень!</b>"
        else:
            text = f"{level_icon} <b>Информация об уровне недоступна</b>"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ])
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        try:
            await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

async def buy_privilege(message: Message, privilege_name):
    """Функция для покупки привилегии"""
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
            f"❌ У тебя уже есть привилегия {priv_data['icon']} {priv_data['name']}!\n"
            f"Дождись её окончания или обратись к администратору."
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

# ==================== INLINE MODE ====================

@dp.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    """
    @бот            — статистика + профиль + мои чеки
    @бот 100 5      — предложить создать чек ИЛИ счёт на 100 тон × 5 раз
    @бот 100 5 @user — то же самое, но для конкретного юзера
    """
    from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

    user_id = inline_query.from_user.id
    raw = inline_query.query.strip()
    parts = raw.split()
    results = []

    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username

        def art(uid, title, desc, text, markup=None):
            kw = dict(
                id=uid,
                title=title,
                description=desc,
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="HTML"
                )
            )
            if markup:
                kw["reply_markup"] = markup
            return InlineQueryResultArticle(**kw)

        # ── РЕЖИМ: введены числа — предлагаем чек или счёт ───────────────
        # Формат: @бот <сумма> <активаций> [опционально @username]
        if parts and parts[0].lstrip("@").replace(".", "").isdigit() and len(parts) >= 2:
            try:
                amount = int(parts[0])
                activations = int(parts[1])
                target_username = parts[2].lstrip("@") if len(parts) >= 3 else None

                if amount > 0 and activations >= 1:
                    cu = db.conn.cursor()
                    cu.execute("SELECT gems FROM users WHERE user_id = ?", (user_id,))
                    row = cu.fetchone()
                    balance = int(row[0]) if row else 0
                    total_cost = amount * activations

                    for_who = f"для @{target_username}" if target_username else "публичный"

                    # ── Карточка 1: СОЗДАТЬ ЧЕК (ты отдаёшь тоны) ──
                    if balance >= total_cost:
                        # Сразу создаём чек
                        ok, res = db.create_check(user_id, amount, activations, target_username, None, "check")
                        if ok:
                            code = res
                            check_text = (
                                f"🧾 <b>Чек #{code}</b>\n\n"
                                f"<blockquote>"
                                f"💰 Сумма: {amount} тон за активацию\n"
                                f"🔁 Активаций: {activations}\n"
                                + (f"👤 Для: @{escape_html(target_username)}\n" if target_username else "👥 Публичный\n")
                                + f"💸 Заморожено: {total_cost} тон\n"
                                f"</blockquote>\n\n"
                                f"👆 Нажми кнопку ниже чтобы получить тоны!"
                            )
                            btn_check = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(
                                    text=f"💰 Получить {amount} тон",
                                    url=f"https://t.me/{bot_username}?start=check_{code}"
                                )
                            ]])
                            results.append(art(
                                f"check_{code}",
                                f"🧾 Создать чек — дать {amount} тон × {activations}",
                                f"Заморозить {total_cost} тон | {for_who} | баланс: {balance}",
                                check_text,
                                markup=btn_check
                            ))
                        else:
                            results.append(art("err_check", f"❌ Ошибка чека: {res}", str(res), f"❌ {res}"))
                    else:
                        results.append(art(
                            "no_bal_check",
                            f"🧾 Создать чек — недостаточно тон (нужно {total_cost}, у тебя {balance})",
                            "Пополни баланс через майнинг",
                            f"❌ Недостаточно тон для чека.\nНужно: {total_cost} тон, у тебя: {balance} тон"
                        ))

                    # ── Карточка 2: СОЗДАТЬ СЧЁТ (тебе платят) ──
                    ok2, res2 = db.create_check(user_id, amount, activations, target_username, None, "invoice")
                    if ok2:
                        code2 = res2
                        invoice_text = (
                            f"📄 <b>Счёт #{code2}</b>\n\n"
                            f"<blockquote>"
                            f"💸 Сумма к оплате: {amount} тон\n"
                            f"🔁 Активаций: {activations}\n"
                            + (f"👤 Для: @{escape_html(target_username)}\n" if target_username else "👥 Публичный\n")
                            + f"</blockquote>\n\n"
                            f"👆 Нажми кнопку ниже чтобы оплатить счёт!"
                        )
                        btn_invoice = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text=f"💳 Оплатить {amount} тон",
                                url=f"https://t.me/{bot_username}?start=check_{code2}"
                            )
                        ]])
                        results.append(art(
                            f"invoice_{code2}",
                            f"📄 Создать счёт — получить {amount} тон × {activations}",
                            f"Запрос на оплату | {for_who}",
                            invoice_text,
                            markup=btn_invoice
                        ))
                    else:
                        results.append(art("err_inv", f"❌ Ошибка счёта: {res2}", str(res2), f"❌ {res2}"))

                    await inline_query.answer(results, cache_time=0, is_personal=True)
                    return

            except (ValueError, IndexError):
                pass  # Упадём в дефолтный режим

        # ── РЕЖИМ ПО УМОЛЧАНИЮ: статистика + профиль + подсказка + чеки ──

        # 1. Статистика
        stats = db.get_stats()
        stats_text = (
            f"⚡ <b>Статистика Mining Game</b>\n\n"
            f"<blockquote>"
            f"├ 👥 Общий онлайн ›› {stats['total_users']}\n"
            f"│  ├ Онлайн за 24ч ›› {stats['online_24h']}\n"
            f"│  └ Текущий онлайн ›› {stats['current_online']}\n"
            f"│\n"
            f"├ 💰 Тон у игроков ›› {int(stats['total_ton'])}\n"
            f"│  └ Тон на чел ›› {int(stats['avg_ton'])}\n"
            f"├ ⚡ Общий HM/s ›› {stats['total_hash']:.0f}\n"
            f"│  └ HM/s на чел ›› {stats['avg_hash']:.1f}\n"
            f"│\n"
            f"├ 🛒 Товара на складе ›› {stats['total_stock']} шт.\n"
            f"│  ├ Видеокарты: {stats['gpu_stock']}\n"
            f"│  ├ Куллеры: {stats['cooler_stock']}\n"
            f"│  ├ ASIC: {stats['asic_stock']}\n"
            f"│  └ Риги: {stats['rig_stock']}\n"
            f"│\n"
            f"└ 📦 Продано всего:\n"
            f"   ├ Видеокарт: {stats['total_cards_sold']}\n"
            f"   ├ Куллеров: {stats['total_coolers_sold']}\n"
            f"   ├ ASIC: {stats['total_asics_sold']}\n"
            f"   ├ Ригов: {stats['total_rigs_sold']}\n"
            f"   ├ Открыто коробок: {stats['total_boxes_opened']}\n"
            f"   └ Майнингов: {stats['total_mining_actions']}"
            f"</blockquote>"
        )
        results.append(art(
            "stats",
            "⚡ Статистика бота",
            f"Игроков: {stats['total_users']} | HM/s: {stats['total_hash']:.0f} | Склад: {stats['total_stock']} шт.",
            stats_text
        ))

        # 2. Профиль
        cu = db.conn.cursor()
        cu.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cu.fetchone()

        if user:
            try:
                priv, _ = db.get_user_privilege(user_id)
                priv_data = config.PRIVILEGES.get(priv, config.PRIVILEGES["player"])
                created_at = datetime.fromisoformat(user[12])
                hours_in_game = int((datetime.now() - created_at).total_seconds() / 3600)
                my_text = (
                    f"👤 <b>Профиль {escape_html(user[3])}</b>\n\n"
                    f"<blockquote>"
                    f"├ 🆔 MID ›› {user[1]}\n"
                    f"├ {priv_data['icon']} {priv_data['name']}\n"
                    f"├ {get_level_icon(user[10])} Уровень ›› {user[10]}\n"
                    f"│  └ 📊 Опыт ›› {user[11]}\n"
                    f"└ ⏰ В игре ›› {hours_in_game} ч\n\n"
                    f"💰 Тон ›› {int(user[4])}\n"
                    f"⚡ HM/s ›› {float(user[5]):.1f}"
                    f"</blockquote>"
                )
                results.append(art(
                    "my_profile",
                    "👤 Мой профиль",
                    f"Тон: {int(user[4])} | HM/s: {float(user[5]):.1f} | Ур. {user[10]}",
                    my_text
                ))
            except Exception as e:
                logger.error(f"Inline profile error: {e}")

            # 3. Подсказка по чекам
            balance = int(user[4])
            hint = (
                f"📝 <b>Создание чека или счёта</b>\n\n"
                f"<blockquote>"
                f"Просто напиши <b>сумму и кол-во активаций</b>:\n"
                f"   <code>@{bot_username} 100 5</code>\n\n"
                f"И выбери что создать:\n"
                f"   🧾 <b>Чек</b> — ты даришь тоны получателю\n"
                f"   📄 <b>Счёт</b> — получатель платит тебе\n\n"
                f"💰 Твой баланс: {balance} тон"
                f"</blockquote>"
            )
            results.append(art(
                "help_checks",
                f"🧾 Чек / 📄 Счёт — напиши @{bot_username} 100 5",
                f"Пример: @{bot_username} 100 5  |  баланс: {balance} тон",
                hint
            ))

            # 4. Активные чеки пользователя
            cc = db.conn.cursor()
            cc.execute(
                "SELECT id,code,creator_id,target_username,amount,activations_left,"
                "activations_total,check_type,comment,is_active "
                "FROM checks WHERE creator_id = ? AND is_active = 1 "
                "ORDER BY created_at DESC LIMIT 5",
                (user_id,)
            )
            for ch in cc.fetchall():
                ch_id, code, cr_id, tg_un, amount, act_left, act_total, ch_type, comment, is_active = ch
                icon = "🧾" if ch_type == "check" else "📄"
                type_name_ch = "Чек" if ch_type == "check" else "Счёт"
                btn_text = f"💰 Получить {int(amount)} тон" if ch_type == "check" else f"💳 Оплатить {int(amount)} тон"
                check_text = (
                    f"{icon} <b>{type_name_ch} #{code}</b>\n\n"
                    f"<blockquote>"
                    f"💰 Сумма: {int(amount)} тон за активацию\n"
                    f"🔁 Активаций: {act_left}/{act_total}\n"
                    + (f"👤 Для: @{escape_html(tg_un)}\n" if tg_un else "👥 Публичный\n")
                    + (f"💬 {escape_html(comment)}\n" if comment else "")
                    + f"</blockquote>\n\n"
                    f"👆 Нажми кнопку ниже!"
                )
                btn_markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=btn_text,
                        url=f"https://t.me/{bot_username}?start=check_{code}"
                    )
                ]])
                results.append(art(
                    f"check_{code}",
                    f"{icon} {type_name_ch} #{code} — {int(amount)} тон × {act_left} ост.",
                    f"Активаций: {act_left}/{act_total}" + (f" | @{tg_un}" if tg_un else " | Публичный"),
                    check_text,
                    markup=btn_markup
                ))

    except Exception as e:
        logger.error(f"Inline handler error: {e}")

    await inline_query.answer(results, cache_time=0, is_personal=True)



# ==================== ЧЕКИ И СЧЕТА ====================

@dp.callback_query(F.data == "checks_menu")
async def callback_checks_menu(callback: CallbackQuery):
    """Меню чеков и счётов"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    
    checks = db.get_user_checks(callback.from_user.id, limit=5)
    active = [c for c in checks if c[9] == 1]
    
    text = (
        "🧾 <b>Чеки и счета</b>\n\n"
        "<blockquote>"
        "🧾 <b>Чек</b> — ты переводишь тоны заранее, получатель активирует и забирает\n"
        "📄 <b>Счёт</b> — ты создаёшь запрос на оплату, получатель платит тебе\n\n"
        f"Активных чеков: {len(active)}"
        "</blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Создать чек", callback_data="create_check"),
         InlineKeyboardButton(text="📄 Создать счёт", callback_data="create_invoice")],
        [InlineKeyboardButton(text="📋 Мои чеки/счета", callback_data="my_checks_list"),
         InlineKeyboardButton(text="🔑 Активировать", callback_data="activate_check_start")],
        [InlineKeyboardButton(text="◀️ Назад в настройки", callback_data="profile_settings")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.in_({"create_check", "create_invoice"}))
async def callback_create_check_start(callback: CallbackQuery, state: FSMContext):
    """Начало создания чека/счёта"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    check_type = "check" if callback.data == "create_check" else "invoice"
    await state.update_data(check_type=check_type)
    await state.set_state(UserStates.check_username)
    
    icon = "🧾" if check_type == "check" else "📄"
    type_name = "чека" if check_type == "check" else "счёта"
    
    text = (
        f"{icon} <b>Создание {type_name}</b>\n\n"
        "<blockquote>"
        "Введи <b>@username</b> Telegram получателя или нажми пропустить (публичный):"
        "</blockquote>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить (публичный)", callback_data="check_skip_username")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="checks_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "check_skip_username")
async def callback_check_skip_username(callback: CallbackQuery, state: FSMContext):
    await state.update_data(check_username=None)
    await state.set_state(UserStates.check_amount)
    await callback.answer()
    await _ask_check_amount(callback.message, edit=True)


@dp.message(UserStates.check_username, F.text[0] != "/")
async def process_check_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip('@')
    await state.update_data(check_username=username)
    await state.set_state(UserStates.check_amount)
    await _ask_check_amount(message, edit=False)


async def _ask_check_amount(msg, edit=False):
    user = db.get_user(msg.chat.id if hasattr(msg, 'chat') else msg.from_user.id)
    balance = int(user[4]) if user else 0
    text = (
        f"💰 <b>Сумма</b>\n\n"
        f"<blockquote>Введи сумму в тонах за одну активацию\n"
        f"Твой баланс: <b>{balance} тон</b></blockquote>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="checks_menu")]
    ])
    if edit:
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(UserStates.check_amount, F.text[0] != "/")
async def process_check_amount(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Введи корректную сумму (целое положительное число).")
        return
    await state.update_data(check_amount=int(message.text))
    await state.set_state(UserStates.check_activations)
    
    text = (
        "🔁 <b>Количество активаций</b>\n\n"
        "<blockquote>Сколько раз можно активировать этот чек/счёт?\n"
        "Например: 1 — одноразовый, 10 — для 10 человек</blockquote>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Одноразовый", callback_data="check_act_1"),
         InlineKeyboardButton(text="5️⃣ Пять раз", callback_data="check_act_5")],
        [InlineKeyboardButton(text="🔟 Десять раз", callback_data="check_act_10"),
         InlineKeyboardButton(text="♾ 100 раз", callback_data="check_act_100")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="checks_menu")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("check_act_"))
async def callback_check_activations_preset(callback: CallbackQuery, state: FSMContext):
    amount = int(callback.data.split("_")[2])
    await state.update_data(check_activations=amount)
    await state.set_state(UserStates.check_comment)
    await callback.answer()
    await _ask_check_comment(callback.message, edit=True)


@dp.message(UserStates.check_activations, F.text[0] != "/")
async def process_check_activations(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 1:
        await message.answer("❌ Введи корректное число (минимум 1).")
        return
    await state.update_data(check_activations=int(message.text))
    await state.set_state(UserStates.check_comment)
    await _ask_check_comment(message, edit=False)


async def _ask_check_comment(msg, edit=False):
    text = (
        "💬 <b>Комментарий (необязательно)</b>\n\n"
        "<blockquote>Добавь описание к чеку или пропусти</blockquote>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Без комментария", callback_data="check_skip_comment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="checks_menu")]
    ])
    if edit:
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "check_skip_comment")
async def callback_check_skip_comment(callback: CallbackQuery, state: FSMContext):
    await state.update_data(check_comment=None)
    await callback.answer()
    await _finalize_check(callback, state, callback.from_user.id)


@dp.message(UserStates.check_comment, F.text[0] != "/")
async def process_check_comment(message: Message, state: FSMContext):
    await state.update_data(check_comment=message.text.strip()[:100])
    await _finalize_check(message, state, message.from_user.id)


async def _finalize_check(msg_or_cb, state: FSMContext, user_id):
    data = await state.get_data()
    await state.clear()
    
    check_type = data.get("check_type", "check")
    username = data.get("check_username")
    amount = data.get("check_amount", 0)
    activations = data.get("check_activations", 1)
    comment = data.get("check_comment")
    
    success, result = db.create_check(user_id, amount, activations, username, comment, check_type)
    
    icon = "🧾" if check_type == "check" else "📄"
    type_name = "Чек" if check_type == "check" else "Счёт"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои чеки", callback_data="my_checks_list")],
        [InlineKeyboardButton(text="◀️ В меню чеков", callback_data="checks_menu")]
    ])
    
    if success:
        code = result
        total = amount * activations if check_type == "check" else 0
        text = (
            f"{icon} <b>{type_name} создан!</b>\n\n"
            f"<blockquote>"
            f"🔑 Код: <code>{code}</code>\n"
            f"💰 Сумма: {amount} тон за активацию\n"
            f"🔁 Активаций: {activations}\n"
            + (f"👤 Для: @{username}\n" if username else "👥 Публичный\n")
            + (f"💬 {escape_html(comment)}\n" if comment else "")
            + (f"💸 Заморожено: {total} тон\n" if check_type == "check" else "")
            + f"</blockquote>\n\n"
            f"Поделись кодом или отправь команду:\n"
            f"<code>/check {code}</code>"
        )
    else:
        text = f"❌ {result}"
    
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await msg_or_cb.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "my_checks_list")
async def callback_my_checks_list(callback: CallbackQuery):
    """Список чеков пользователя"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    checks = db.get_user_checks(callback.from_user.id, limit=10)
    
    if not checks:
        text = "📋 <b>Мои чеки и счета</b>\n\n<blockquote>У тебя пока нет чеков</blockquote>"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Создать чек", callback_data="create_check")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="checks_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        return
    
    text = "📋 <b>Мои чеки и счета</b>\n\n<blockquote>"
    buttons = []
    
    for ch in checks:
        ch_id, code, cr_id, tg_un, amount, act_left, act_total, ch_type, comment, is_active, cr_at = ch
        status = "✅" if is_active else "❌"
        icon = "🧾" if ch_type == "check" else "📄"
        text += f"{status} {icon} <b>#{code}</b> — {int(amount)} тон × {act_left}/{act_total}\n"
        if is_active:
            buttons.append([InlineKeyboardButton(
                text=f"{icon} #{code} ({act_left} ост.)",
                callback_data=f"check_detail_{ch_id}"
            )])
    
    text += "</blockquote>"
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="checks_menu")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@dp.callback_query(F.data.startswith("check_detail_"))
async def callback_check_detail(callback: CallbackQuery):
    """Детали чека"""
    check_id = int(callback.data.split("_")[2])
    db.cursor.execute('SELECT * FROM checks WHERE id = ? AND creator_id = ?', (check_id, callback.from_user.id))
    ch = db.cursor.fetchone()
    
    if not ch:
        await callback.answer("❌ Чек не найден!", show_alert=True)
        return
    
    await callback.answer()
    ch_id, code, cr_id, tg_un, amount, act_left, act_total, ch_type, comment, is_active, cr_at = ch
    icon = "🧾" if ch_type == "check" else "📄"
    type_name = "Чек" if ch_type == "check" else "Счёт"
    status = "✅ Активен" if is_active else "❌ Закрыт"
    
    text = (
        f"{icon} <b>{type_name} #{code}</b>\n\n"
        f"<blockquote>"
        f"💰 Сумма: {int(amount)} тон\n"
        f"🔁 Активаций: {act_left}/{act_total}\n"
        + (f"👤 Для: @{tg_un}\n" if tg_un else "👥 Публичный\n")
        + (f"💬 {escape_html(comment)}\n" if comment else "")
        + f"📊 Статус: {status}\n"
        + (f"💸 Остаток: {int(amount * act_left)} тон\n" if ch_type == "check" and is_active else "")
        + f"</blockquote>\n\n"
        f"Команда активации: <code>/check {code}</code>"
    )
    
    buttons = []
    if is_active:
        buttons.append([InlineKeyboardButton(text="❌ Отменить и вернуть тоны", callback_data=f"cancel_check_{ch_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="my_checks_list")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@dp.callback_query(F.data.startswith("cancel_check_"))
async def callback_cancel_check(callback: CallbackQuery):
    check_id = int(callback.data.split("_")[2])
    success, result = db.cancel_check(check_id, callback.from_user.id)
    
    if success:
        await callback.answer(f"✅ Чек отменён! Возвращено: {int(result)} тон", show_alert=True)
        await callback_my_checks_list(callback)
    else:
        await callback.answer(str(result), show_alert=True)


@dp.callback_query(F.data == "activate_check_start")
async def callback_activate_check_start(callback: CallbackQuery, state: FSMContext):
    """Начало активации чека"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return
    
    await callback.answer()
    await state.set_state(UserStates.activate_check_code)
    
    text = (
        "🔑 <b>Активация чека</b>\n\n"
        "<blockquote>Введи код чека (например: <code>ABC12345</code>)</blockquote>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="checks_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(UserStates.activate_check_code, F.text[0] != "/")
async def process_activate_check_code(message: Message, state: FSMContext):
    """Активируем чек по коду"""
    await state.clear()
    code = message.text.strip().upper()
    
    success, result = db.activate_check(code, message.from_user.id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню чеков", callback_data="checks_menu")],
        [InlineKeyboardButton(text="👤 В профиль", callback_data="profile")]
    ])
    
    if success:
        amount = result["amount"]
        creator = result["creator"]
        check_type = result["check_type"]
        creator_name = creator[3] if creator else "Неизвестно"
        
        if check_type == "check":
            text = (
                f"✅ <b>Чек активирован!</b>\n\n"
                f"<blockquote>"
                f"💰 Получено: <b>+{int(amount)} тон</b>\n"
                f"👤 От: {escape_html(creator_name)}"
                f"</blockquote>"
            )
            try:
                await bot.send_message(creator[0], f"🔔 Твой чек #{code} активирован! Осталось активаций: {result['activations_left']}")
            except Exception:
                pass
        else:
            text = (
                f"✅ <b>Счёт оплачен!</b>\n\n"
                f"<blockquote>"
                f"💸 Оплачено: <b>{int(amount)} тон</b>\n"
                f"👤 Получатель: {escape_html(creator_name)}"
                f"</blockquote>"
            )
    else:
        text = str(result)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(Command("check"))
async def cmd_check(message: Message):
    """Команда /check CODE для активации чека"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: <code>/check КОД</code>\n\nПример: /check ABC12345",
            parse_mode="HTML"
        )
        return
    
    code = args[1].strip().upper()
    success, result = db.activate_check(code, message.from_user.id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 В профиль", callback_data="profile")]
    ])
    
    if success:
        amount = result["amount"]
        creator = result["creator"]
        check_type = result["check_type"]
        creator_name = creator[3] if creator else "Неизвестно"
        
        if check_type == "check":
            text = (
                f"✅ <b>Чек активирован!</b>\n\n"
                f"<blockquote>"
                f"💰 Получено: <b>+{int(amount)} тон</b>\n"
                f"👤 От: {escape_html(creator_name)}"
                f"</blockquote>"
            )
            try:
                await bot.send_message(creator[0], f"🔔 Твой чек #{code} активирован! Осталось: {result['activations_left']}")
            except Exception:
                pass
        else:
            text = (
                f"✅ <b>Счёт оплачен!</b>\n\n"
                f"<blockquote>"
                f"💸 Оплачено: <b>{int(amount)} тон</b>\n"
                f"👤 Получатель: {escape_html(creator_name)}"
                f"</blockquote>"
            )
    else:
        text = str(result)
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ==================== КОМАНДЫ БАНА ====================

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    """
    /ban <MID> [дни] [причина]
    /ban 42 7 спам  — бан на 7 дней
    /ban 42 читерство — навсегда с причиной
    /ban 42 — навсегда без причины
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.answer(
            "❌ Использование:\n"
            "<code>/ban &lt;MID&gt; [дни] [причина]</code>\n\n"
            "Примеры:\n"
            "/ban 42 — бан навсегда\n"
            "/ban 42 7 спам — бан на 7 дней\n"
            "/ban 42 читерство — навсегда с причиной",
            parse_mode="HTML"
        )
        return

    target_str = args[1].lstrip("@")
    target = None

    if target_str.isdigit():
        target = db.get_user_by_custom_id(int(target_str))
        if not target:
            target = db.get_user(int(target_str))
    else:
        db.cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (target_str,))
        target = db.cursor.fetchone()

    if not target:
        await message.answer(f"❌ Игрок <b>{escape_html(target_str)}</b> не найден!", parse_mode="HTML")
        return

    target_id = target[0]
    target_name = target[3] or target[2] or f"MID:{target[1]}"

    if is_admin(target_id):
        await message.answer("❌ Нельзя забанить админа!")
        return

    days = None
    reason = None
    if len(args) >= 3:
        if args[2].isdigit():
            days = int(args[2])
            reason = args[3] if len(args) >= 4 else None
        else:
            reason = " ".join(args[2:])

    db.ban_user(target_id, reason=reason, days=days, admin_id=message.from_user.id)

    if days:
        ban_str = f"на {days} дн."
        until_str = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
    else:
        ban_str = "навсегда"
        until_str = "бессрочно"

    await message.answer(
        f"🔨 <b>Игрок забанен!</b>\n\n"
        f"<blockquote>"
        f"👤 {escape_html(target_name)} (MID: {target[1]})\n"
        f"⏱ Срок: {ban_str} ({until_str})\n"
        f"📝 Причина: {escape_html(reason) if reason else 'не указана'}"
        f"</blockquote>",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            target_id,
            f"🔨 <b>Ты забанен!</b>\n\n"
            f"<blockquote>⏱ Срок: {ban_str}\n"
            f"📝 Причина: {escape_html(reason) if reason else 'не указана'}</blockquote>",
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    """/unban <MID>"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/unban &lt;MID&gt;</code>", parse_mode="HTML")
        return

    target_str = args[1].lstrip("@")
    target = None
    if target_str.isdigit():
        target = db.get_user_by_custom_id(int(target_str))
        if not target:
            target = db.get_user(int(target_str))
    else:
        db.cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (target_str,))
        target = db.cursor.fetchone()

    if not target:
        await message.answer(f"❌ Игрок не найден!", parse_mode="HTML")
        return

    target_id = target[0]
    target_name = target[3] or target[2] or f"MID:{target[1]}"

    db.unban_user(target_id, admin_id=message.from_user.id)

    await message.answer(
        f"✅ <b>Игрок разбанен!</b>\n\n"
        f"<blockquote>👤 {escape_html(target_name)} (MID: {target[1]})</blockquote>",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(target_id, "✅ <b>Твой бан снят!</b> Добро пожаловать обратно!", parse_mode="HTML")
    except Exception:
        pass


@dp.message(Command("baninfo"))
async def cmd_baninfo(message: Message):
    """/baninfo <MID>"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/baninfo &lt;MID&gt;</code>", parse_mode="HTML")
        return

    target_str = args[1].lstrip("@")
    target = None
    if target_str.isdigit():
        target = db.get_user_by_custom_id(int(target_str))
        if not target:
            target = db.get_user(int(target_str))
    else:
        db.cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (target_str,))
        target = db.cursor.fetchone()

    if not target:
        await message.answer("❌ Игрок не найден!")
        return

    target_name = target[3] or target[2] or f"MID:{target[1]}"
    is_banned = target[8]
    ban_until = target[9]

    if is_banned:
        if ban_until:
            try:
                until_dt = datetime.fromisoformat(ban_until)
                if datetime.now() > until_dt:
                    status = "⏰ Бан истёк (не снят вручную)"
                else:
                    days_left = (until_dt - datetime.now()).days
                    status = f"🔨 Забанен до {until_dt.strftime('%d.%m.%Y')} ({days_left} дн. осталось)"
            except Exception:
                status = "🔨 Забанен (временный)"
        else:
            status = "🔨 Забанен навсегда"
    else:
        status = "✅ Не забанен"

    await message.answer(
        f"📋 <b>Информация о бане</b>\n\n"
        f"<blockquote>"
        f"👤 {escape_html(target_name)} (MID: {target[1]})\n"
        f"📊 Статус: {status}"
        f"</blockquote>",
        parse_mode="HTML"
    )

# ==================== РАСШИРЕННЫЕ АДМИН КОМАНДЫ ====================

def _find_user_by_arg(arg):
    """Ищет юзера по MID, tg_id или @username"""
    arg = arg.lstrip("@")
    if arg.isdigit():
        user = db.get_user_by_custom_id(int(arg))
        if not user:
            user = db.get_user(int(arg))
    else:
        db.cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (arg,))
        user = db.cursor.fetchone()
    return user


@dp.message(Command("userinfo"))
async def cmd_userinfo(message: Message):
    """/userinfo <MID> — полная информация об игроке"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/userinfo &lt;MID&gt;</code>", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    uid = user[0]
    priv, _ = db.get_user_privilege(uid)
    priv_data = config.PRIVILEGES.get(priv, config.PRIVILEGES["player"])

    # Оборудование
    asics = db.get_user_asics(uid)
    rigs = db.get_user_rigs(uid)
    gpus = db.get_user_gpus(uid)
    coolers = db.get_user_coolers(uid)
    checks_active = db.conn.cursor()
    checks_active.execute("SELECT COUNT(*) FROM checks WHERE creator_id = ? AND is_active = 1", (uid,))
    active_checks = checks_active.fetchone()[0]
    transfers_c = db.conn.cursor()
    transfers_c.execute("SELECT COUNT(*) FROM transfers WHERE from_user_id = ?", (uid,))
    sent_count = transfers_c.fetchone()[0]

    created_at = datetime.fromisoformat(user[12]) if user[12] else datetime.now()
    hours = int((datetime.now() - created_at).total_seconds() / 3600)
    ban_status = "🔨 Забанен" if user[8] else "✅ Активен"
    ban_until = f" до {user[9][:10]}" if user[8] and user[9] else ""

    referrer = db.get_user(user[7]) if user[7] else None
    referrer_str = f"{referrer[3]} (MID:{referrer[1]})" if referrer else "нет"

    text = (
        f"👤 <b>Инфо об игроке</b>\n\n"
        f"<blockquote>"
        f"├ 👤 Ник: {escape_html(user[3])}\n"
        f"├ 🆔 MID: {user[1]}\n"
        f"├ 📱 TG ID: <code>{uid}</code>\n"
        f"├ 🔗 Username: @{user[2] or '—'}\n"
        f"├ {priv_data['icon']} Привилегия: {priv_data['name']}\n"
        f"├ 🌟 Уровень: {user[10]} (опыт: {user[11]})\n"
        f"├ ⏰ В игре: {hours} ч\n"
        f"│\n"
        f"├ 💰 Тон: {int(user[4])}\n"
        f"├ ⚡ HM/s: {user[5]:.1f}\n"
        f"├ 💎 Всего намайнено: {int(user[14])}\n"
        f"│\n"
        f"├ 🖥 ASIC: {len(asics)} | Риги: {len(rigs)} | GPU: {len(gpus)} | Куллеры: {len(coolers)}\n"
        f"├ 👥 Рефералов: {user[6]} (от: {escape_html(referrer_str)})\n"
        f"├ 📦 Коробок: {user[16]}\n"
        f"├ 🧾 Активных чеков: {active_checks}\n"
        f"├ 💸 Переводов отправлено: {sent_count}\n"
        f"└ 🚦 Статус: {ban_status}{ban_until}"
        f"</blockquote>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("userlogs"))
async def cmd_userlogs(message: Message):
    """/userlogs <MID> [кол-во] — логи админ-действий над игроком"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/userlogs &lt;MID&gt; [кол-во]</code>", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    limit = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 10
    uid = user[0]

    c = db.conn.cursor()
    c.execute("""
        SELECT a.action, a.details, a.created_at, u.first_name
        FROM admin_logs a
        LEFT JOIN users u ON a.admin_id = u.user_id
        WHERE a.target_id = ?
        ORDER BY a.created_at DESC LIMIT ?
    """, (uid, limit))
    logs = c.fetchall()

    if not logs:
        await message.answer(f"📋 Логов для игрока <b>{escape_html(user[3])}</b> нет.", parse_mode="HTML")
        return

    text = f"📋 <b>Логи игрока {escape_html(user[3])} (MID: {user[1]})</b>\n\n<blockquote>"
    for action, details, created_at, admin_name in logs:
        dt = created_at[:16] if created_at else "?"
        text += f"[{dt}] <b>{action}</b> — {escape_html(admin_name or '?')}\n"
        if details:
            text += f"  └ {escape_html(details)}\n"
    text += "</blockquote>"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("adminlogs"))
async def cmd_adminlogs(message: Message):
    """/adminlogs [кол-во] — последние действия всех админов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 15

    c = db.conn.cursor()
    c.execute("""
        SELECT a.action, a.details, a.created_at, ua.first_name, ut.first_name, a.target_id
        FROM admin_logs a
        LEFT JOIN users ua ON a.admin_id = ua.user_id
        LEFT JOIN users ut ON a.target_id = ut.user_id
        ORDER BY a.created_at DESC LIMIT ?
    """, (limit,))
    logs = c.fetchall()

    if not logs:
        await message.answer("📋 Логов нет.")
        return

    text = f"📋 <b>Последние {limit} действий админов</b>\n\n<blockquote>"
    for action, details, created_at, admin_name, target_name, target_id in logs:
        dt = created_at[:16] if created_at else "?"
        text += f"[{dt}] <b>{action}</b>\n"
        text += f"  ├ Админ: {escape_html(admin_name or '?')}\n"
        text += f"  └ Цель: {escape_html(target_name or str(target_id))}\n"
        if details:
            text += f"      {escape_html(details[:60])}\n"
    text += "</blockquote>"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("referrals"))
async def cmd_referrals_admin(message: Message):
    """/referrals <MID> — рефералы игрока"""
    if not is_admin(message.from_user.id):
        # Для обычных пользователей — стандартная команда
        user_id = message.from_user.id
        if await check_ban(user_id):
            await send_ban_message(message)
            return
        user = db.get_user(user_id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйся через /start")
            return
        c = db.conn.cursor()
        c.execute("SELECT first_name, username, created_at FROM users WHERE referrer_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,))
        refs = c.fetchall()
        if not refs:
            await message.answer("👥 У тебя пока нет рефералов.")
            return
        text = f"👥 <b>Твои рефералы ({len(refs)})</b>\n\n<blockquote>"
        for name, uname, created in refs:
            dt = created[:10] if created else "?"
            text += f"• {escape_html(name or '?')}" + (f" (@{uname})" if uname else "") + f" — {dt}\n"
        text += "</blockquote>"
        await message.answer(text, parse_mode="HTML")
        return

    # Для админа — смотрим рефералов любого игрока
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/referrals &lt;MID&gt;</code>", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    uid = user[0]
    c = db.conn.cursor()
    c.execute("""
        SELECT first_name, username, custom_id, created_at, gems, level
        FROM users WHERE referrer_id = ? ORDER BY created_at DESC
    """, (uid,))
    refs = c.fetchall()

    text = (
        f"👥 <b>Рефералы игрока {escape_html(user[3])} (MID: {user[1]})</b>\n"
        f"Всего: {len(refs)}\n\n<blockquote>"
    )
    if not refs:
        text += "Рефералов нет"
    else:
        for name, uname, mid, created, gems, level in refs:
            dt = created[:10] if created else "?"
            text += f"• MID:{mid} {escape_html(name or '?')}"
            text += f" (@{uname})" if uname else ""
            text += f" | Ур.{level} | {int(gems)} тон | {dt}\n"
    text += "</blockquote>"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("transfers"))
async def cmd_transfers_admin(message: Message):
    """/transfers <MID> [кол-во] — история переводов игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/transfers &lt;MID&gt; [кол-во]</code>", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    limit = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 10
    uid = user[0]

    c = db.conn.cursor()
    c.execute("""
        SELECT t.amount, t.created_at, t.comment,
               uf.first_name, ut.first_name, t.from_user_id, t.to_user_id
        FROM transfers t
        LEFT JOIN users uf ON t.from_user_id = uf.user_id
        LEFT JOIN users ut ON t.to_user_id = ut.user_id
        WHERE t.from_user_id = ? OR t.to_user_id = ?
        ORDER BY t.created_at DESC LIMIT ?
    """, (uid, uid, limit))
    transfers = c.fetchall()

    if not transfers:
        await message.answer(f"💸 Переводов у игрока <b>{escape_html(user[3])}</b> нет.", parse_mode="HTML")
        return

    text = f"💸 <b>Переводы {escape_html(user[3])} (MID: {user[1]})</b>\n\n<blockquote>"
    for amount, created_at, comment, from_name, to_name, from_id, to_id in transfers:
        dt = created_at[:16] if created_at else "?"
        if from_id == uid:
            text += f"📤 <b>-{int(amount)}</b> → {escape_html(to_name or '?')} [{dt}]\n"
        else:
            text += f"📥 <b>+{int(amount)}</b> ← {escape_html(from_name or '?')} [{dt}]\n"
        if comment:
            text += f"   💬 {escape_html(comment)}\n"
    text += "</blockquote>"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("userchecks"))
async def cmd_userchecks(message: Message):
    """/userchecks <MID> — чеки и счета игрока"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/userchecks &lt;MID&gt;</code>", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    uid = user[0]
    c = db.conn.cursor()
    c.execute("""
        SELECT code, check_type, amount, activations_left, activations_total,
               target_username, is_active, created_at
        FROM checks WHERE creator_id = ? ORDER BY created_at DESC LIMIT 15
    """, (uid,))
    checks = c.fetchall()

    if not checks:
        await message.answer(f"🧾 Чеков у игрока <b>{escape_html(user[3])}</b> нет.", parse_mode="HTML")
        return

    text = f"🧾 <b>Чеки {escape_html(user[3])} (MID: {user[1]})</b>\n\n<blockquote>"
    for code, ch_type, amount, act_left, act_total, target_un, is_active, created_at in checks:
        icon = "🧾" if ch_type == "check" else "📄"
        status = "✅" if is_active else "❌"
        dt = created_at[:10] if created_at else "?"
        text += f"{status}{icon} <code>{code}</code> | {int(amount)} тон × {act_left}/{act_total}"
        if target_un:
            text += f" | @{target_un}"
        text += f" | {dt}\n"
    text += "</blockquote>"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("giveton"))
async def cmd_giveton(message: Message):
    """/giveton <MID> <сумма> — выдать тоны игроку"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 3 or not args[2].lstrip("-").isdigit():
        await message.answer("❌ Использование: <code>/giveton &lt;MID&gt; &lt;сумма&gt;</code>\nДля снятия используй отрицательное число.", parse_mode="HTML")
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    amount = int(args[2])
    uid = user[0]
    target_name = user[3] or user[2] or f"MID:{user[1]}"

    db.cursor.execute("UPDATE users SET gems = gems + ? WHERE user_id = ?", (amount, uid))
    db.conn.commit()
    db.log_admin_action(message.from_user.id, "giveton", uid, f"Выдано {amount} тон")

    new_balance_c = db.conn.cursor()
    new_balance_c.execute("SELECT gems FROM users WHERE user_id = ?", (uid,))
    new_balance = int(new_balance_c.fetchone()[0])

    sign = "+" if amount >= 0 else ""
    await message.answer(
        f"✅ <b>Тоны {'выданы' if amount >= 0 else 'сняты'}!</b>\n\n"
        f"<blockquote>"
        f"👤 {escape_html(target_name)} (MID: {user[1]})\n"
        f"💰 Изменение: {sign}{amount} тон\n"
        f"💼 Новый баланс: {new_balance} тон"
        f"</blockquote>",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            uid,
            f"{'💰' if amount >= 0 else '💸'} <b>{'Получено' if amount >= 0 else 'Снято'}: {sign}{amount} тон</b>\n"
            f"Твой баланс: {new_balance} тон",
            parse_mode="HTML"
        )
    except Exception:
        pass

@dp.message(Command("givebox"))
async def cmd_givebox(message: Message):
    """/givebox <MID> <кол-во> — выдать боксы игроку"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    args = message.text.split()
    if len(args) < 3 or not args[2].isdigit():
        await message.answer(
            "❌ Использование: <code>/givebox &lt;MID&gt; &lt;кол-во&gt;</code>\n"
            "Пример: /givebox 42 5",
            parse_mode="HTML"
        )
        return

    user = _find_user_by_arg(args[1])
    if not user:
        await message.answer("❌ Игрок не найден!")
        return

    count = max(1, int(args[2]))
    uid = user[0]
    target_name = user[3] or user[2] or f"MID:{user[1]}"

    for _ in range(count):
        db.add_box(uid)

    db.cursor.execute(
        "UPDATE users SET boxes_count = boxes_count + ? WHERE user_id = ?",
        (count, uid)
    )
    db.conn.commit()
    db.log_admin_action(message.from_user.id, "givebox", uid, f"Выдано {count} боксов")

    new_boxes_c = db.conn.cursor()
    new_boxes_c.execute("SELECT boxes_count FROM users WHERE user_id = ?", (uid,))
    new_boxes = new_boxes_c.fetchone()[0]

    await message.answer(
        f"✅ <b>Боксы выданы!</b>\n\n"
        f"<blockquote>"
        f"👤 {escape_html(target_name)} (MID: {user[1]})\n"
        f"📦 Выдано: +{count} боксов\n"
        f"📦 Всего теперь: {new_boxes} боксов"
        f"</blockquote>",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            uid,
            f"🎁 <b>Тебе выдали {count} 📦 боксов!</b>\n"
            f"Открой их командой /openbox",
            parse_mode="HTML"
        )
    except Exception:
        pass




@dp.message(Command("admhelp"))
async def cmd_admhelp(message: Message):
    """/admhelp — список всех админ команд"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    text = (
        "👑 <b>Админ команды</b>\n\n"
        "<blockquote>"
        "<b>👤 Игроки:</b>\n"
        "/userinfo &lt;MID&gt; — полная инфо об игроке\n"
        "/userlogs &lt;MID&gt; [N] — логи действий над игроком\n"
        "/referrals &lt;MID&gt; — рефералы игрока\n"
        "/transfers &lt;MID&gt; [N] — история переводов\n"
        "/userchecks &lt;MID&gt; — чеки и счета игрока\n"
        "\n"
        "<b>💰 Экономика:</b>\n"
        "/giveton &lt;MID&gt; &lt;сумма&gt; — выдать/снять тоны\n"
        "/pay &lt;MID&gt; &lt;сумма&gt; — перевод тон игроку\n"
        "/take &lt;MID&gt; &lt;сумма&gt; — снять тоны у игрока\n"
        "\n"
        "<b>🔨 Модерация:</b>\n"
        "/ban &lt;MID&gt; [дни] [причина] — забанить\n"
        "/unban &lt;MID&gt; — разбанить\n"
        "/baninfo &lt;MID&gt; — статус бана\n"
        "\n"
        "<b>📋 Логи:</b>\n"
        "/adminlogs [N] — последние действия всех админов\n"
        "/userlogs &lt;MID&gt; [N] — логи конкретного игрока\n"
        "\n"
        "<b>🛒 Магазин:</b>\n"
        "/skl — управление складом магазина"
        "</blockquote>"
    )
    await message.answer(text, parse_mode="HTML")


# ==================== БОКСЫ: НОВЫЕ ХЕНДЛЕРЫ ====================

@dp.callback_query(F.data == "open_box_now")
async def callback_open_box_now(callback: CallbackQuery):
    """Открыть один бокс по кнопке"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()
    user = db.get_user(callback.from_user.id)
    boxes_count = user[16] if user and len(user) > 16 else 0

    if boxes_count == 0:
        await callback.message.answer("📦 У тебя нет боксов!")
        return

    boxes = db.get_user_boxes(callback.from_user.id, unopened_only=True)
    if not boxes:
        await callback.message.answer("❌ Боксы не найдены")
        return

    box_id = boxes[0][0]
    success, result = db.open_box(box_id)

    # Обновляем количество
    user = db.get_user(callback.from_user.id)
    remaining = user[16] if user and len(user) > 16 else 0

    if success:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Открыть ещё" + (f" ({remaining} шт.)" if remaining > 0 else ""), callback_data="open_box_now")],
        ]) if remaining > 0 else None
        try:
            await callback.message.edit_text(result, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(result, reply_markup=keyboard, parse_mode="HTML")
    else:
        await callback.message.answer(f"❌ {result}")


@dp.callback_query(F.data == "no_boxes")
async def callback_no_boxes(callback: CallbackQuery):
    await callback.answer("📦 У тебя нет боксов! Майни чтобы получить.", show_alert=True)


@dp.message(Command("openbox"))
async def cmd_openbox(message: Message):
    """/openbox [кол-во] — открыть 1–100 боксов"""
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return

    user = db.get_user(message.from_user.id)
    boxes_count = user[16] if user and len(user) > 16 else 0

    if boxes_count == 0:
        await message.answer(
            "📦 У тебя нет боксов!\n\nМайни чтобы получить: /mine",
            parse_mode="HTML"
        )
        return

    # Парсим количество
    args = message.text.split()
    count = 1
    if len(args) >= 2 and args[1].isdigit():
        count = min(int(args[1]), 100)  # максимум 100

    count = min(count, boxes_count)  # не больше чем есть

    boxes = db.get_user_boxes(message.from_user.id, unopened_only=True)
    boxes_to_open = boxes[:count]

    total_ton = 0
    total_exp = 0
    components = []
    bonus_items = []

    for box in boxes_to_open:
        box_id = box[0]
        success, result = db.open_box(box_id)
        if success:
            # Парсим результат чтобы суммировать
            import re
            ton_match = re.search(r"💰 (\d+) тон", result)
            exp_match = re.search(r"✨ (\d+) опыта", result)
            if ton_match:
                total_ton += int(ton_match.group(1))
            if exp_match:
                total_exp += int(exp_match.group(1))
            # Ищем бонусные предметы (куллеры, привилегии)
            for line in result.split("\n"):
                if "💨" in line or "👑" in line:
                    bonus_items.append(line.strip("• ").strip())
                elif "🧩" in line or "⚙️" in line or "🔌" in line or "🛡️" in line or "💾" in line:
                    components.append(line.strip("• ").strip())

    # Итоговый текст
    user = db.get_user(message.from_user.id)
    remaining = user[16] if user and len(user) > 16 else 0

    text = (
        f"🎁 <b>Открыто боксов: {len(boxes_to_open)}</b>\n\n"
        f"<blockquote>"
        f"💰 Тон получено: <b>+{total_ton}</b>\n"
        f"✨ Опыта получено: <b>+{total_exp}</b>\n"
    )
    if components:
        from collections import Counter
        comp_counts = Counter(components)
        text += "\n🧩 Компоненты:\n"
        for comp, cnt in comp_counts.items():
            text += f"  • {comp}" + (f" ×{cnt}" if cnt > 1 else "") + "\n"
    if bonus_items:
        text += "\n🎉 Редкие предметы:\n"
        for item in bonus_items:
            text += f"  • {item}\n"
    text += f"\n📦 Осталось боксов: {remaining}"
    text += f"</blockquote>"

    keyboard = None
    if remaining > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📦 Открыть ещё ({remaining} шт.)",
                callback_data="open_box_now"
            )]
        ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ==================== РЕФЕРАЛЫ: ФИКС КНОПКИ НАЗАД ====================

@dp.callback_query(F.data == "referrals_page")
async def callback_referrals_page(callback: CallbackQuery):
    """Страница рефералов (кнопка назад из track_referrals)"""
    if await check_ban(callback.from_user.id):
        await send_ban_message(callback)
        return

    await callback.answer()
    user = db.get_user(callback.from_user.id)
    referrals_count = user[6] if user[6] is not None else 0

    total_ton_bonus = referrals_count * config.REFERRAL_BONUS
    total_exp_bonus = referrals_count * config.REFERRAL_EXP_BONUS

    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={callback.from_user.id}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"<blockquote>"
        f"Каждому приглашённому другу начисляется бонус:\n"
        f"• Ему: +{config.REFERRAL_BONUS_FOR_NEW} тон и +{config.REFERRAL_EXP_FOR_NEW} опыта\n"
        f"• Тебе: +{config.REFERRAL_BONUS} тон и +{config.REFERRAL_EXP_BONUS} опыта\n"
        f"</blockquote>\n\n"
        f"📊 <b>Твоя статистика:</b>\n"
        f"├ 👤 Рефералов: {referrals_count}\n"
        f"├ 💰 Получено тон: {total_ton_bonus}\n"
        f"└ ✨ Получено опыта: {total_exp_bonus}\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{ref_link}</code>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={ref_link}&text=🔥 Присоединяйся к майнинг-боту!"),
            InlineKeyboardButton(text="👥 Отслеживать", callback_data="track_referrals")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(Command("fixhash"))
async def cmd_fixhash(message: Message):
    """/fixhash — пересчитать хешрейт всех игроков (адм)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await message.answer("🔧 Запускаю пересчёт хешрейтов...")

    fa, fg = db.migrate_hashrates()

    # Дополнительно принудительно пересчитываем всех
    cu = db.conn.cursor()
    cu.execute("SELECT user_id FROM users")
    all_users = [r[0] for r in cu.fetchall()]
    for uid in all_users:
        db.recalculate_user_hashrate(uid)

    await message.answer(
        f"✅ <b>Готово!</b>\n\n"
        f"<blockquote>"
        f"🔧 Исправлено ASIC: {fa}\n"
        f"🔧 Исправлено GPU: {fg}\n"
        f"👥 Пересчитано игроков: {len(all_users)}"
        f"</blockquote>",
        parse_mode="HTML"
    )

# ==================== КРАФТ ВИДЕОКАРТ ====================

# Рецепты крафта: {result_key: {name, hash_rate, wear_mult, recipe: {компонент: кол-во}, description}}
CRAFT_RECIPES = {
    "craft_gtx_boost": {
        "name": "⚡ GTX Boost Edition",
        "base_gpu": "gtx_1080_ti",
        "hash_rate": 55,
        "wear_multiplier": 0.6,
        "recipe": {
            "🧩 Чип": 3,
            "🔌 Кабель": 2,
            "⚙️ Вентилятор": 2,
        },
        "description": "Разогнанный GTX 1080 Ti с усиленным охлаждением"
    },
    "craft_rtx_prime": {
        "name": "🔥 RTX Prime Edition",
        "base_gpu": "rtx_3070",
        "hash_rate": 80,
        "wear_multiplier": 0.5,
        "recipe": {
            "🧩 Чип": 5,
            "💾 Микросхема": 3,
            "⚙️ Вентилятор": 3,
            "🔌 Кабель": 2,
        },
        "description": "RTX 3070 с кастомной прошивкой и улучшенной памятью"
    },
    "craft_rx_turbo": {
        "name": "🔴 RX Turbo Edition",
        "base_gpu": "rx_6800_xt",
        "hash_rate": 100,
        "wear_multiplier": 0.5,
        "recipe": {
            "🧩 Чип": 6,
            "🛡️ Радиатор": 4,
            "🔌 Кабель": 3,
            "⚙️ Вентилятор": 3,
        },
        "description": "RX 6800 XT с AMD-оптимизацией под майнинг"
    },
    "craft_rtx_ultra": {
        "name": "💎 RTX Ultra Edition",
        "base_gpu": "rtx_3080_ti",
        "hash_rate": 115,
        "wear_multiplier": 0.45,
        "recipe": {
            "🧩 Чип": 8,
            "💾 Микросхема": 5,
            "🛡️ Радиатор": 4,
            "⚙️ Вентилятор": 4,
            "🔌 Кабель": 3,
        },
        "description": "RTX 3080 Ti с жидкостным охлаждением и оверклоком"
    },
    "craft_rtx_god": {
        "name": "🌟 RTX God Edition",
        "base_gpu": "rtx_3090",
        "hash_rate": 140,
        "wear_multiplier": 0.35,
        "recipe": {
            "🧩 Чип": 12,
            "💾 Микросхема": 8,
            "🛡️ Радиатор": 6,
            "⚙️ Вентилятор": 6,
            "🔌 Кабель": 5,
        },
        "description": "Легендарная RTX 3090 с полным разгоном — элита майнинга"
    },
}


def get_craft_menu_keyboard():
    buttons = []
    for key, recipe in CRAFT_RECIPES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{recipe['name']} — {recipe['hash_rate']} HM/s",
            callback_data=f"craft_view:{key}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("craft"))
async def cmd_craft(message: Message, state: FSMContext):
    """Меню крафта видеокарт"""
    await state.clear()
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    await state.clear()

    components = {c[0]: c[1] for c in db.get_user_components(message.from_user.id)}

    text = (
        "⚒️ <b>Крафт видеокарт</b>\n\n"
        "<blockquote>"
        "Крафтовые видеокарты мощнее магазинных и изнашиваются медленнее.\n\n"
        "Компоненты выпадают из 📦 боксов при майнинге.\n\n"
        "🧩 Чип — {}\n"
        "⚙️ Вентилятор — {}\n"
        "🔌 Кабель — {}\n"
        "🛡️ Радиатор — {}\n"
        "💾 Микросхема — {}"
        "</blockquote>\n\n"
        "Выбери рецепт:"
    ).format(
        components.get("🧩 Чип", 0),
        components.get("⚙️ Вентилятор", 0),
        components.get("🔌 Кабель", 0),
        components.get("🛡️ Радиатор", 0),
        components.get("💾 Микросхема", 0),
    )

    await message.answer(text, reply_markup=get_craft_menu_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "craft_menu")
async def callback_craft_menu(callback: CallbackQuery):
    await callback.answer()
    components = {c[0]: c[1] for c in db.get_user_components(callback.from_user.id)}

    text = (
        "⚒️ <b>Крафт видеокарт</b>\n\n"
        "<blockquote>"
        "Твои компоненты:\n"
        "🧩 Чип — {}\n"
        "⚙️ Вентилятор — {}\n"
        "🔌 Кабель — {}\n"
        "🛡️ Радиатор — {}\n"
        "💾 Микросхема — {}"
        "</blockquote>\n\n"
        "Выбери рецепт:"
    ).format(
        components.get("🧩 Чип", 0),
        components.get("⚙️ Вентилятор", 0),
        components.get("🔌 Кабель", 0),
        components.get("🛡️ Радиатор", 0),
        components.get("💾 Микросхема", 0),
    )

    await callback.message.edit_text(text, reply_markup=get_craft_menu_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("craft_view:"))
async def callback_craft_view(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    recipe = CRAFT_RECIPES.get(key)
    if not recipe:
        await callback.answer("❌ Рецепт не найден", show_alert=True)
        return

    components = {c[0]: c[1] for c in db.get_user_components(callback.from_user.id)}

    # Проверяем наличие компонентов
    can_craft = True
    recipe_lines = ""
    for comp, need in recipe["recipe"].items():
        have = components.get(comp, 0)
        ok = "✅" if have >= need else "❌"
        if have < need:
            can_craft = False
        recipe_lines += f"  {ok} {comp}: {have}/{need}\n"

    wear_pct = int(recipe["wear_multiplier"] * 100)

    text = (
        f"⚒️ <b>{recipe['name']}</b>\n\n"
        f"<blockquote>"
        f"📖 {recipe['description']}\n\n"
        f"⚡ Хешрейт: <b>{recipe['hash_rate']} HM/s</b>\n"
        f"🛡 Износ: <b>{wear_pct}% от обычного</b>\n\n"
        f"📦 Требуется компонентов:\n"
        f"{recipe_lines}"
        f"</blockquote>"
    )

    buttons = []
    if can_craft:
        buttons.append([InlineKeyboardButton(
            text=f"⚒️ Скрафтить {recipe['name']}",
            callback_data=f"craft_do:{key}"
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text="❌ Недостаточно компонентов",
            callback_data="craft_no_comp"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ К рецептам", callback_data="craft_menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@dp.callback_query(F.data == "craft_no_comp")
async def callback_craft_no_comp(callback: CallbackQuery):
    await callback.answer("📦 Открывай боксы чтобы получить компоненты!", show_alert=True)


@dp.callback_query(F.data.startswith("craft_do:"))
async def callback_craft_do(callback: CallbackQuery):
    await callback.answer()
    key = callback.data.split(":", 1)[1]
    recipe = CRAFT_RECIPES.get(key)
    if not recipe:
        await callback.answer("❌ Рецепт не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    components = {c[0]: c[1] for c in db.get_user_components(user_id)}

    # Финальная проверка компонентов
    for comp, need in recipe["recipe"].items():
        if components.get(comp, 0) < need:
            await callback.answer(f"❌ Не хватает: {comp}", show_alert=True)
            return

    # Списываем компоненты
    c = db.conn.cursor()
    for comp, need in recipe["recipe"].items():
        c.execute(
            "UPDATE components SET amount = amount - ? WHERE user_id = ? AND component_name = ?",
            (need, user_id, comp)
        )
        c.execute(
            "DELETE FROM components WHERE user_id = ? AND component_name = ? AND amount <= 0",
            (user_id, comp)
        )

    # Создаём крафтовую GPU
    c.execute(
        """INSERT INTO user_gpus
           (user_id, gpu_key, name, hash_rate, wear, is_crafted, wear_multiplier)
           VALUES (?, ?, ?, ?, 100, 1, ?)""",
        (user_id, key, recipe["name"], recipe["hash_rate"], recipe["wear_multiplier"])
    )
    db.conn.commit()

    # Пересчитываем хешрейт
    db.recalculate_user_hashrate(user_id)

    wear_pct = int(recipe["wear_multiplier"] * 100)
    recipe_used = "\n".join(f"  • {c}: {n}" for c, n in recipe["recipe"].items())

    text = (
        f"✅ <b>Крафт успешен!</b>\n\n"
        f"<blockquote>"
        f"🎉 Создана: <b>{recipe['name']}</b>\n\n"
        f"⚡ Хешрейт: <b>{recipe['hash_rate']} HM/s</b>\n"
        f"🛡 Износ: <b>{wear_pct}% от обычного</b>\n\n"
        f"Потрачено:\n{recipe_used}"
        f"</blockquote>\n\n"
        f"💡 Установи карту в риг через /rigs"
    )

    buttons = [
        [InlineKeyboardButton(text="⚒️ Крафтить ещё", callback_data="craft_menu")],
        [InlineKeyboardButton(text="💿 Мои риги", callback_data="my_rigs")]
    ]

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )

# ==================== БАРАХОЛКА ====================

async def market_expire_scheduler():
    """Каждый час возвращает просроченные лоты продавцам"""
    while True:
        try:
            expired = db.market_expire_listings()
            if expired:
                logger.info(f"Market: вернули {expired} просроченных лотов")
        except Exception as e:
            logger.error(f"market_expire_scheduler error: {e}")
        await asyncio.sleep(3600)


def market_sort_keyboard(current_sort, item_type_filter, page):
    """Только кнопка фильтров — сортировка внутри меню фильтров."""
    filter_labels = {"all": "Все товары", "gpu": "GPU", "cooler": "Куллеры", "component": "Компоненты"}
    buttons = [
        [InlineKeyboardButton(
            text="🔍 Фильтры: " + filter_labels.get(item_type_filter, "Все"),
            callback_data=f"mkt_filter_menu:{current_sort}:{page}"
        )],
    ]
    return buttons


def build_market_text_and_keyboard(user_id, sort, item_filter, page):
    PAGE_SIZE = 9
    type_arg = None if item_filter == 'all' else item_filter
    listings = db.market_get_listings(
        item_type=type_arg, sort=sort,
        exclude_user=user_id, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )
    total_list = db.market_get_listings(item_type=type_arg, sort=sort, exclude_user=user_id, limit=9999, offset=0)
    total_count = len(total_list)
    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)

    filter_labels = {"all": "Все товары", "gpu": "Видеокарты", "cooler": "Куллеры", "component": "Компоненты"}
    sort_labels = {
        "price_asc": "Сначала дешевле", "price_desc": "Сначала дороже",
        "hash_desc": "По хешрейту", "wear_desc": "По износу", "new": "Новые"
    }

    text = (
        f"🏪 <b>Барахолка</b> — {filter_labels.get(item_filter, 'Все')}\n"
        f"<i>Сортировка: {sort_labels.get(sort, sort)}</i>  |  "
        f"<i>стр. {page+1}/{total_pages}  ({total_count} лотов)</i>\n\n"
    )

    buttons = market_sort_keyboard(sort, item_filter, page)
    item_buttons = []

    if not listings:
        text += "😔 Товаров нет. Выставь своё оборудование!"
    else:
        for lst in listings:
            lid, seller_id, itype, iid, iname, hr, cp, wear, price, is_crafted, listed_at, expires_at, is_active = lst
            craft_tag = " ⚒️" if is_crafted else ""
            if itype == 'gpu':
                desc = f"⚡{hr:.0f} HM/s | 🛡{wear}%{craft_tag}"
            elif itype == 'cooler':
                desc = f"❄️{cp} | 🛡{wear}%"
            else:
                desc = "🔩 Компонент"
            short_name = iname[:18] + ("…" if len(iname) > 18 else "")
            item_buttons.append([InlineKeyboardButton(
                text=f"🛒 {short_name} — {price}т",
                callback_data=f"mkt_buy_view:{lid}"
            )])

    # Раскладываем кнопки товаров по 3 в ряд
    rows_3 = []
    row = []
    for btn_list in item_buttons:
        btn = btn_list[0]
        row.append(btn)
        if len(row) == 3:
            rows_3.append(row)
            row = []
    if row:
        rows_3.append(row)
    buttons += rows_3

    # Навигация ◀️ [1/N] ▶️
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"mkt_sort:{sort}:{item_filter}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * PAGE_SIZE < total_count:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"mkt_sort:{sort}:{item_filter}:{page+1}"))
    buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="📦 Мои лоты", callback_data="mkt_my_listings")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("market"))
async def cmd_market(message: Message, state: FSMContext):
    await state.clear()
    if await check_ban(message.from_user.id):
        await send_ban_message(message)
        return
    await state.clear()
    text, kb = build_market_text_and_keyboard(message.from_user.id, "price_asc", "all", 0)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "market")
async def callback_market(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    text, kb = build_market_text_and_keyboard(callback.from_user.id, "price_asc", "all", 0)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


MKT_FILTER_OPTS = [
    ("all",       "Все товары"),
    ("gpu",       "Видеокарты (GPU)"),
    ("cooler",    "Куллеры"),
    ("component", "Компоненты"),
]





@dp.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("mkt_sort:"))
async def callback_mkt_sort(callback: CallbackQuery):
    await callback.answer()
    _, sort, item_filter, page_str = callback.data.split(":")
    text, kb = build_market_text_and_keyboard(callback.from_user.id, sort, item_filter, int(page_str))
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("mkt_buy_view:"))
async def callback_mkt_buy_view(callback: CallbackQuery):
    await callback.answer()
    listing_id = int(callback.data.split(":")[1])
    c = db.conn.cursor()
    c.execute("SELECT * FROM market_listings WHERE id = ? AND is_active = 1", (listing_id,))
    lst = c.fetchone()
    if not lst:
        await callback.answer("❌ Лот уже не доступен", show_alert=True)
        return

    lid, seller_id, itype, iid, iname, hr, cp, wear, price, is_crafted, listed_at, expires_at, is_active = lst
    seller = db.get_user(seller_id)
    seller_name = seller[3] if seller else "Неизвестно"
    craft_tag = " ⚒️ Крафт" if is_crafted else ""
    expires_dt = datetime.fromisoformat(expires_at)
    days_left = max(0, (expires_dt - datetime.now()).days)

    if itype == 'gpu':
        stats = f"⚡ Хешрейт: {hr:.0f} HM/s\n🛡 Состояние: {wear}%{craft_tag}"
    elif itype == 'cooler':
        stats = f"❄️ Мощность охлаждения: {cp}\n🛡 Состояние: {wear}%"
    else:
        stats = "🔩 Компонент"

    user = db.get_user(callback.from_user.id)
    balance = int(user[4]) if user else 0
    can_buy = balance >= price and seller_id != callback.from_user.id

    text = (
        f"🛒 <b>{iname}</b>{craft_tag}\n\n"
        f"<blockquote>"
        f"{stats}\n\n"
        f"💰 Цена: <b>{price} тон</b>\n"
        f"👤 Продавец: {escape_html(seller_name)}\n"
        f"⏰ Истекает через: {days_left} дн."
        f"</blockquote>\n\n"
        f"Твой баланс: {balance} тон"
    )

    buttons = []
    if seller_id == callback.from_user.id:
        buttons.append([InlineKeyboardButton(text="❌ Это твой лот", callback_data="mkt_my_listings")])
    elif can_buy:
        buttons.append([InlineKeyboardButton(
            text=f"✅ Купить за {price} тон",
            callback_data=f"mkt_buy_confirm:{listing_id}"
        )])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Недостаточно тон", callback_data="mkt_no_funds")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="market")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@dp.callback_query(F.data == "mkt_no_funds")
async def callback_mkt_no_funds(callback: CallbackQuery):
    await callback.answer("❌ Недостаточно тон для покупки!", show_alert=True)


@dp.callback_query(F.data.startswith("mkt_buy_confirm:"))
async def callback_mkt_buy_confirm(callback: CallbackQuery):
    listing_id = int(callback.data.split(":")[1])
    success, result = db.market_buy_item(callback.from_user.id, listing_id)

    if success:
        await callback.answer("✅ Куплено!", show_alert=True)
        try:
            await bot.send_message(
                result["seller_id"],
                f"💰 <b>Твой товар куплен!</b>\n\n"
                f"📦 {result['item_name']}\n"
                f"💵 +{result['price']} тон на счёт",
                parse_mode="HTML"
            )
        except Exception:
            pass
        text, kb = build_market_text_and_keyboard(callback.from_user.id, "price_asc", "all", 0)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.answer(result, show_alert=True)


@dp.callback_query(F.data == "mkt_my_listings")
async def callback_mkt_my_listings(callback: CallbackQuery):
    await callback.answer()
    listings = db.market_get_listings(only_user=callback.from_user.id, limit=20, offset=0)

    text = "📦 <b>Мои лоты на барахолке</b>\n\n"
    buttons = []

    if not listings:
        text += "У тебя нет активных лотов.\n\nВыставь видеокарту или куллер со склада!"
    else:
        for lst in listings:
            lid, seller_id, itype, iid, iname, hr, cp, wear, price, is_crafted, listed_at, expires_at, is_active = lst
            craft_tag = " ⚒️" if is_crafted else ""
            expires_dt = datetime.fromisoformat(expires_at)
            days_left = max(0, (expires_dt - datetime.now()).days)
            if itype == 'gpu':
                desc = f"⚡{hr:.0f} HM/s | 🛡{wear}%"
            elif itype == 'cooler':
                desc = f"❄️{cp} | 🛡{wear}%"
            else:
                desc = f"🔩 {item_id} шт."
            text += f"• <b>{iname}</b>{craft_tag} — {price} тон | {desc} | ⏰{days_left}д\n"
            buttons.append([InlineKeyboardButton(
                text=f"❌ Снять: {iname}",
                callback_data=f"mkt_cancel:{lid}"
            )])

    buttons.append([InlineKeyboardButton(text="➕ Выставить товар", callback_data="mkt_sell_choose")])
    buttons.append([InlineKeyboardButton(text="◀️ Барахолка", callback_data="market")])
    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("mkt_cancel:"))
async def callback_mkt_cancel(callback: CallbackQuery):
    await callback.answer()
    listing_id = int(callback.data.split(":")[1])
    success, msg = db.market_cancel_listing(listing_id, callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    await callback_mkt_my_listings(callback)


# ── Выставление на продажу из инвентаря ─────────────────────────

class MarketStates(StatesGroup):
    waiting_price = State()


@dp.callback_query(F.data == "mkt_sell_choose")
async def callback_mkt_sell_choose(callback: CallbackQuery):
    """Показываем выбор категории: GPU / Куллер"""
    await callback.answer()
    buttons = [
        [InlineKeyboardButton(text="🖼 Видеокарты (GPU)", callback_data="mkt_inv_gpu")],
        [InlineKeyboardButton(text="💨 Куллеры",          callback_data="mkt_inv_cooler")],
        [InlineKeyboardButton(text="◀️ Назад",             callback_data="mkt_my_listings")],
    ]
    await callback.message.edit_text(
        "🏪 <b>Выставить товар</b>\n\nВыбери категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "mkt_inv_gpu")
async def callback_mkt_inv_gpu(callback: CallbackQuery):
    """Список свободных GPU для продажи"""
    await callback.answer()
    c = db.conn.cursor()
    # Только не установленные и не на барахолке
    c.execute("""
        SELECT g.id, g.name, g.hash_rate, g.wear, g.is_crafted
        FROM user_gpus g
        WHERE g.user_id = ? AND (g.is_installed = 0 OR g.is_installed IS NULL)
          AND g.id NOT IN (
              SELECT item_id FROM market_listings
              WHERE seller_id = ? AND item_type = 'gpu' AND is_active = 1
          )
        ORDER BY g.hash_rate DESC
    """, (callback.from_user.id, callback.from_user.id))
    rows = c.fetchall()

    if not rows:
        await callback.answer("❌ Нет свободных видеокарт для продажи", show_alert=True)
        return

    buttons = []
    for gid, name, hr, wear, is_crafted in rows:
        craft = " ⚒️" if is_crafted else ""
        buttons.append([InlineKeyboardButton(
            text=f"🖼 {name}{craft} | {hr:.0f} HM/s | {wear}%",
            callback_data=f"mkt_sell_gpu:{gid}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="mkt_sell_choose")])

    await callback.message.edit_text(
        "🖼 <b>Выбери видеокарту для продажи:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "mkt_inv_cooler")
async def callback_mkt_inv_cooler(callback: CallbackQuery):
    """Список свободных куллеров для продажи"""
    await callback.answer()
    c = db.conn.cursor()
    c.execute("""
        SELECT cl.id, cl.name, cl.cooling_power, cl.wear
        FROM user_coolers cl
        WHERE cl.user_id = ? AND cl.rig_id IS NULL
          AND cl.id NOT IN (
              SELECT item_id FROM market_listings
              WHERE seller_id = ? AND item_type = 'cooler' AND is_active = 1
          )
        ORDER BY cl.cooling_power DESC
    """, (callback.from_user.id, callback.from_user.id))
    rows = c.fetchall()

    if not rows:
        await callback.answer("❌ Нет свободных куллеров для продажи", show_alert=True)
        return

    buttons = []
    for cid, name, cp, wear in rows:
        buttons.append([InlineKeyboardButton(
            text=f"💨 {name} | ❄️{cp} | {wear}%",
            callback_data=f"mkt_sell_cooler:{cid}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="mkt_sell_choose")])

    await callback.message.edit_text(
        "💨 <b>Выбери куллер для продажи:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("mkt_sell_gpu:"))
async def callback_mkt_sell_gpu(callback: CallbackQuery, state: FSMContext):
    """Нажали 'Продать на барахолке' для GPU"""
    await callback.answer()
    gpu_id = int(callback.data.split(":")[1])
    gpu = db.conn.cursor()
    gpu.execute("SELECT name, hash_rate, wear, gpu_key FROM user_gpus WHERE id = ? AND user_id = ? AND is_installed = 0", (gpu_id, callback.from_user.id))
    row = gpu.fetchone()
    if not row:
        await callback.answer("❌ Видеокарта недоступна (установлена или не твоя)", show_alert=True)
        return

    name, hr, wear, gpu_key = row
    shop_price = db.market_get_shop_price('gpu', gpu_key=gpu_key)
    min_price = max(1, int(shop_price * 0.1)) if shop_price else 1

    await state.set_state(MarketStates.waiting_price)
    await state.update_data(item_type='gpu', item_id=gpu_id, item_name=name, shop_price=shop_price)

    quick_price = int(shop_price * 0.3) if shop_price else 0
    text = (
        f"💰 <b>Продажа: {escape_html(name)}</b>\n\n"
        f"<blockquote>"
        f"⚡ {hr:.0f} HM/s | 🛡 {wear}%\n"
        f"💵 Цена в магазине: {shop_price} тон\n"
        f"⚡ Быстрая продажа: {quick_price} тон (30%)"
        f"</blockquote>\n\n"
        f"Введи свою цену (тон):"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="my_gpus")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("mkt_sell_cooler:"))
async def callback_mkt_sell_cooler(callback: CallbackQuery, state: FSMContext):
    """Нажали 'Продать на барахолке' для куллера"""
    await callback.answer()
    cooler_id = int(callback.data.split(":")[1])
    c = db.conn.cursor()
    c.execute("SELECT name, cooling_power, wear, cooler_key FROM user_coolers WHERE id = ? AND user_id = ? AND rig_id IS NULL", (cooler_id, callback.from_user.id))
    row = c.fetchone()
    if not row:
        await callback.answer("❌ Куллер недоступен", show_alert=True)
        return

    name, cp, wear, cooler_key = row
    shop_price = db.market_get_shop_price('cooler', cooler_key=cooler_key)
    quick_price = int(shop_price * 0.3) if shop_price else 0

    await state.set_state(MarketStates.waiting_price)
    await state.update_data(item_type='cooler', item_id=cooler_id, item_name=name, shop_price=shop_price)

    text = (
        f"💰 <b>Продажа: {escape_html(name)}</b>\n\n"
        f"<blockquote>"
        f"❄️ Мощность: {cp} | 🛡 {wear}%\n"
        f"💵 Цена в магазине: {shop_price} тон\n"
        f"⚡ Быстрая продажа: {quick_price} тон (30%)"
        f"</blockquote>\n\n"
        f"Введи свою цену (тон):"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="my_coolers")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("mkt_sell_quick:"), MarketStates.waiting_price)
async def callback_mkt_sell_quick(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    price = int(callback.data.split(":")[1])
    await _do_list_item(callback, state, data, price)


@dp.message(MarketStates.waiting_price, F.text[0] != "/")
async def process_market_price(message: Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Введи корректную цену (целое число > 0)")
        return
    price = int(message.text)
    await _do_list_item(message, state, data, price)


async def _do_list_item(msg_or_cb, state, data, price):
    user_id = msg_or_cb.from_user.id
    item_type = data.get('item_type')
    item_id = data.get('item_id')
    item_name = data.get('item_name', '')

    success, result = db.market_list_item(user_id, item_type, item_id, price)
    await state.clear()

    text = (
        f"✅ <b>Выставлено на барахолку!</b>\n\n"
        f"<blockquote>"
        f"📦 {escape_html(item_name)}\n"
        f"💰 Цена: {price} тон\n"
        f"⏰ Вернётся через 3 дня если не купят"
        f"</blockquote>"
    ) if success else f"❌ {result}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Барахолка", callback_data="market")],
        [InlineKeyboardButton(text="📦 Мои лоты", callback_data="mkt_my_listings")]
    ])

    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await msg_or_cb.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("mkt_quick_sell_gpu:"))
async def callback_mkt_quick_sell_gpu(callback: CallbackQuery):
    """Быстрая продажа GPU за 30% без ввода цены"""
    await callback.answer()
    parts = callback.data.split(":")
    gpu_id, price = int(parts[1]), int(parts[2])

    c = db.conn.cursor()
    c.execute("SELECT name, hash_rate, wear FROM user_gpus WHERE id = ? AND user_id = ? AND is_installed = 0",
              (gpu_id, callback.from_user.id))
    row = c.fetchone()
    if not row:
        await callback.answer("❌ Видеокарта недоступна", show_alert=True)
        return

    success, result = db.market_list_item(callback.from_user.id, 'gpu', gpu_id, price)
    if success:
        await callback.answer(f"✅ Выставлено за {price} тон!", show_alert=True)
        # Возвращаем в список карточек
        gpus = db.get_user_gpus(callback.from_user.id, include_installed=True)
        items = [('gpu', gpu) for gpu in gpus]
        await callback.message.edit_text(
            "🖼 <b>Твои видеокарты</b>\n\nВыбери видеокарту для просмотра:",
            reply_markup=get_mycards_keyboard(callback.from_user.id, items, 0),
            parse_mode="HTML"
        )
    else:
        await callback.answer(result, show_alert=True)


@dp.callback_query(F.data.startswith("mkt_quick_sell_cooler:"))
async def callback_mkt_quick_sell_cooler(callback: CallbackQuery):
    """Быстрая продажа куллера за 30% без ввода цены"""
    await callback.answer()
    parts = callback.data.split(":")
    cooler_id, price = int(parts[1]), int(parts[2])

    c = db.conn.cursor()
    c.execute("SELECT name FROM user_coolers WHERE id = ? AND user_id = ? AND rig_id IS NULL",
              (cooler_id, callback.from_user.id))
    row = c.fetchone()
    if not row:
        await callback.answer("❌ Куллер недоступен", show_alert=True)
        return

    success, result = db.market_list_item(callback.from_user.id, 'cooler', cooler_id, price)
    if success:
        await callback.answer(f"✅ Выставлено за {price} тон!", show_alert=True)
        free_coolers = db.get_free_coolers(callback.from_user.id)
        items = [('cooler', c) for c in free_coolers]
        await callback.message.edit_text(
            "💨 <b>Твои куллеры</b>\n\nВыбери куллер для просмотра:",
            reply_markup=get_mycards_keyboard(callback.from_user.id, items, 0),
            parse_mode="HTML"
        )
    else:
        await callback.answer(result, show_alert=True)



# ==================== ЗАПУСК БОТА ====================
async def main():
    print("🤖 Бот запущен!")
    print(f"👑 Админы: {config.ADMIN_IDS}")
    # Автомиграция хешрейтов при старте
    fa, fg = db.migrate_hashrates()
    if fa > 0 or fg > 0:
        print(f"🔧 Миграция хешрейтов: исправлено ASIC={fa}, GPU={fg}")
    print(f"📦 Автопополнение: {'Включено' if config.AUTO_RESTOCK_ENABLED else 'Выключено'}")
    print(f"⏰ Время пополнения: {config.AUTO_RESTOCK_TIME} МСК")
    print("⚡ Нажми Ctrl+C для остановки")
    
    asyncio.create_task(auto_restock_scheduler())
    asyncio.create_task(market_expire_scheduler())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
