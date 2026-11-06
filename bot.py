"""
ربات پیشرفته مدیریت کانفیگ و آموزش برای روبیکا
با پنل کاربر و ادمین - طراحی با معماری مدرن
"""

import asyncio
import json
import logging
import yaml
import aiosqlite
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, asdict
import hashlib

from rubpy import BotClient
from rubpy.bot import filters
from rubpy.bot.models import Update, Keypad, KeypadRow, Button, Message
from rubpy.bot.enums import ButtonTypeEnum, ChatTypeEnum, UpdateTypeEnum
from rubpy.bot.filters import states

# تنظیمات لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ساختارهای داده
# ============================================================================

@dataclass
class ConfigType:
    """نوع کانفیگ"""
    id: int
    name: str
    created_at: str
    created_by: str

@dataclass
class Config:
    """کانفیگ"""
    id: int
    type_id: int
    name: str
    content: str
    file_id: Optional[str]
    content_type: str  # text, image, file
    is_active: bool
    added_by: str
    added_date: str

@dataclass
class Tutorial:
    """آموزش"""
    id: int
    title: str
    content: str
    file_id: Optional[str]
    has_app_file: bool
    added_by: str
    added_date: str

@dataclass
class Channel:
    """چنل"""
    id: int
    channel_guid: str
    channel_name: str
    added_by: str
    added_date: str

@dataclass
class User:
    """کاربر"""
    user_guid: str
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_admin: bool
    start_date: str
    last_activity: str

# ============================================================================
# مدیریت دیتابیس
# ============================================================================

class Database:
    """مدیریت دیتابیس SQLite"""
    
    def __init__(self, db_path: str = "config_bot.db"):
        self.db_path = db_path
        self.conn = None
    
    async def connect(self):
        """اتصال به دیتابیس"""
        self.conn = await aiosqlite.connect(self.db_path)
        await self.create_tables()
    
    async def close(self):
        """بستن اتصال دیتابیس"""
        if self.conn:
            await self.conn.close()
    
    async def create_tables(self):
        """ایجاد جداول دیتابیس"""
        async with self.conn.cursor() as cursor:
            # جدول انواع کانفیگ
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS config_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL
                )
            ''')
            
            # جدول کانفیگ‌ها
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    file_id TEXT,
                    content_type TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    added_by TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (type_id) REFERENCES config_types(id)
                )
            ''')
            
            # جدول آموزش‌ها
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS tutorials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    file_id TEXT,
                    has_app_file BOOLEAN DEFAULT 0,
                    added_by TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول چنل‌ها
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_guid TEXT UNIQUE NOT NULL,
                    channel_name TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # جدول کاربران
            await cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_guid TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_admin BOOLEAN DEFAULT 0,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await self.conn.commit()
    
    # متدهای مدیریت انواع کانفیگ
    async def add_config_type(self, name: str, created_by: str) -> int:
        """افزودن نوع کانفیگ جدید"""
        async with self.conn.cursor() as cursor:
            try:
                await cursor.execute(
                    'INSERT INTO config_types (name, created_by) VALUES (?, ?)',
                    (name, created_by)
                )
                await self.conn.commit()
                return cursor.lastrowid
            except aiosqlite.IntegrityError:
                raise ValueError(f"نوع کانفیگ '{name}' از قبل وجود دارد")
    
    async def get_config_types(self) -> List[ConfigType]:
        """دریافت لیست انواع کانفیگ"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM config_types ORDER BY id')
            rows = await cursor.fetchall()
            return [
                ConfigType(
                    id=row[0],
                    name=row[1],
                    created_at=row[2],
                    created_by=row[3]
                ) for row in rows
            ]
    
    async def delete_config_type(self, type_id: int) -> bool:
        """حذف نوع کانفیگ"""
        async with self.conn.cursor() as cursor:
            # بررسی وجود کانفیگ‌های مرتبط
            await cursor.execute('SELECT COUNT(*) FROM configs WHERE type_id = ?', (type_id,))
            count = (await cursor.fetchone())[0]
            if count > 0:
                return False
            
            await cursor.execute('DELETE FROM config_types WHERE id = ?', (type_id,))
            await self.conn.commit()
            return cursor.rowcount > 0
    
    # متدهای مدیریت کانفیگ‌ها
    async def add_config(self, config_type_id: int, name: str, content: str, 
                        file_id: Optional[str], content_type: str, added_by: str) -> int:
        """افزودن کانفیگ جدید"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT INTO configs (type_id, name, content, file_id, content_type, added_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (config_type_id, name, content, file_id, content_type, added_by))
            await self.conn.commit()
            return cursor.lastrowid
    
    async def get_configs_by_type(self, type_id: int) -> List[Config]:
        """دریافت کانفیگ‌های یک نوع"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                SELECT * FROM configs 
                WHERE type_id = ? 
                ORDER BY added_date DESC
            ''', (type_id,))
            rows = await cursor.fetchall()
            return [
                Config(
                    id=row[0],
                    type_id=row[1],
                    name=row[2],
                    content=row[3],
                    file_id=row[4],
                    content_type=row[5],
                    is_active=bool(row[6]),
                    added_by=row[7],
                    added_date=row[8]
                ) for row in rows
            ]
    
    async def get_all_configs(self) -> List[Config]:
        """دریافت همه کانفیگ‌ها"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM configs ORDER BY type_id, added_date DESC')
            rows = await cursor.fetchall()
            return [
                Config(
                    id=row[0],
                    type_id=row[1],
                    name=row[2],
                    content=row[3],
                    file_id=row[4],
                    content_type=row[5],
                    is_active=bool(row[6]),
                    added_by=row[7],
                    added_date=row[8]
                ) for row in rows
            ]
    
    async def update_config_status(self, config_id: int, is_active: bool) -> bool:
        """به‌روزرسانی وضعیت کانفیگ"""
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                'UPDATE configs SET is_active = ? WHERE id = ?',
                (is_active, config_id)
            )
            await self.conn.commit()
            return cursor.rowcount > 0
    
    async def delete_config(self, config_id: int) -> bool:
        """حذف کانفیگ"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('DELETE FROM configs WHERE id = ?', (config_id,))
            await self.conn.commit()
            return cursor.rowcount > 0
    
    # متدهای مدیریت آموزش‌ها
    async def add_tutorial(self, title: str, content: str, file_id: Optional[str], 
                          has_app_file: bool, added_by: str) -> int:
        """افزودن آموزش جدید"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT INTO tutorials (title, content, file_id, has_app_file, added_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (title, content, file_id, has_app_file, added_by))
            await self.conn.commit()
            return cursor.lastrowid
    
    async def get_tutorials(self) -> List[Tutorial]:
        """دریافت لیست آموزش‌ها"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM tutorials ORDER BY added_date DESC')
            rows = await cursor.fetchall()
            return [
                Tutorial(
                    id=row[0],
                    title=row[1],
                    content=row[2],
                    file_id=row[3],
                    has_app_file=bool(row[4]),
                    added_by=row[5],
                    added_date=row[6]
                ) for row in rows
            ]
    
    async def delete_tutorial(self, tutorial_id: int) -> bool:
        """حذف آموزش"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('DELETE FROM tutorials WHERE id = ?', (tutorial_id,))
            await self.conn.commit()
            return cursor.rowcount > 0
    
    # متدهای مدیریت چنل‌ها
    async def add_channel(self, channel_guid: str, channel_name: str, added_by: str) -> int:
        """افزودن چنل جدید"""
        async with self.conn.cursor() as cursor:
            try:
                await cursor.execute('''
                    INSERT INTO channels (channel_guid, channel_name, added_by)
                    VALUES (?, ?, ?)
                ''', (channel_guid, channel_name, added_by))
                await self.conn.commit()
                return cursor.lastrowid
            except aiosqlite.IntegrityError:
                raise ValueError("چنل از قبل وجود دارد")
    
    async def get_channels(self) -> List[Channel]:
        """دریافت لیست چنل‌ها"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM channels ORDER BY added_date DESC')
            rows = await cursor.fetchall()
            return [
                Channel(
                    id=row[0],
                    channel_guid=row[1],
                    channel_name=row[2],
                    added_by=row[3],
                    added_date=row[4]
                ) for row in rows
            ]
    
    async def delete_channel(self, channel_id: int) -> bool:
        """حذف چنل"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
            await self.conn.commit()
            return cursor.rowcount > 0
    
    async def check_channel_membership(self, user_guid: str) -> bool:
        """بررسی عضویت کاربر در چنل‌ها"""
        channels = await self.get_channels()
        # در روبیکا باید API بررسی عضویت را پیاده کنیم
        # اینجا فرض می‌کنیم همیشه True است (برای تست)
        # در واقعیت باید با get_chat_member بررسی شود
        return True
    
    # متدهای مدیریت کاربران
    async def add_or_update_user(self, user_guid: str, username: Optional[str], 
                                first_name: Optional[str], last_name: Optional[str]) -> None:
        """افزودن یا به‌روزرسانی کاربر"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_guid, username, first_name, last_name, last_activity)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_guid, username, first_name, last_name))
            await self.conn.commit()
    
    async def get_user(self, user_guid: str) -> Optional[User]:
        """دریافت اطلاعات کاربر"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM users WHERE user_guid = ?', (user_guid,))
            row = await cursor.fetchone()
            if row:
                return User(
                    user_guid=row[0],
                    username=row[1],
                    first_name=row[2],
                    last_name=row[3],
                    is_admin=bool(row[4]),
                    start_date=row[5],
                    last_activity=row[6]
                )
            return None
    
    async def get_all_users(self) -> List[User]:
        """دریافت لیست همه کاربران"""
        async with self.conn.cursor() as cursor:
            await cursor.execute('SELECT * FROM users ORDER BY start_date DESC')
            rows = await cursor.fetchall()
            return [
                User(
                    user_guid=row[0],
                    username=row[1],
                    first_name=row[2],
                    last_name=row[3],
                    is_admin=bool(row[4]),
                    start_date=row[5],
                    last_activity=row[6]
                ) for row in rows
            ]
    
    async def is_admin(self, user_guid: str) -> bool:
        """بررسی ادمین بودن کاربر"""
        user = await self.get_user(user_guid)
        if user:
            return user.is_admin
        return False

# ============================================================================
# مدیریت State کاربران
# ============================================================================

class UserStateManager:
    """مدیریت state کاربران برای مکالمه"""
    
    def __init__(self, db: Database):
        self.db = db
        self.states = {}  # user_guid -> state_data
    
    def set_state(self, user_guid: str, state: str, data: Dict = None):
        """تنظیم state کاربر"""
        self.states[user_guid] = {
            'state': state,
            'data': data or {},
            'timestamp': datetime.now().isoformat()
        }
    
    def get_state(self, user_guid: str) -> Optional[Dict]:
        """دریافت state کاربر"""
        return self.states.get(user_guid)
    
    def clear_state(self, user_guid: str):
        """پاک کردن state کاربر"""
        if user_guid in self.states:
            del self.states[user_guid]
    
    def get_state_value(self, user_guid: str, key: str, default=None):
        """دریافت مقدار از state"""
        state = self.get_state(user_guid)
        if state and 'data' in state:
            return state['data'].get(key, default)
        return default
    
    def set_state_value(self, user_guid: str, key: str, value):
        """تنظیم مقدار در state"""
        state = self.get_state(user_guid)
        if state:
            if 'data' not in state:
                state['data'] = {}
            state['data'][key] = value

# ============================================================================
# کیپدها و منوها
# ============================================================================

class KeypadFactory:
    """سازنده کیپدهای ربات"""
    
    @staticmethod
    def user_panel() -> Keypad:
        """پنل کاربر"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="get_config",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="دریافت کانفیگ 🌐"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="tutorials",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="آموزش ها 📑"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="version",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="نسخه بات 💠"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=False
        )
    
    @staticmethod
    def admin_panel() -> Keypad:
        """پنل ادمین"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="add_config",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="اد کردن کانفیگ 🗄️"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="config_status",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="وضعیت کانفیگ 📡"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="config_types",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="تنظیم نوع کانفیگ 🔗"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="tutorials_admin",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="آموزشات 🎓"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="channels",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="چنل 🛡️"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="users_list",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="لیست کاربران 📁"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=False
        )
    
    @staticmethod
    def back_button(target: str = "main") -> Keypad:
        """دکمه بازگشت"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"back_{target}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="🔙 بازگشت"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )
    
    @staticmethod
    def config_type_actions() -> Keypad:
        """اقدامات نوع کانفیگ"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="add_type",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="تولید ➕"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="delete_type",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="حذف ➖"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="list_types",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="لیست 🗒️"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="back_admin",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="🔙 بازگشت"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )
    
    @staticmethod
    def config_management_actions() -> Keypad:
        """اقدامات مدیریت کانفیگ"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="add_config_file",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="اضافه کردن ➕"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="delete_config_file",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="حذف کردن ➖"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="back_admin",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="🔙 بازگشت"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )
    
    @staticmethod
    def tutorial_actions() -> Keypad:
        """اقدامات آموزش"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="add_tutorial",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="اضافه کردن ➕"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="delete_tutorial",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="حذف کردن ➖"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="back_admin",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="🔙 بازگشت"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )
    
    @staticmethod
    def channel_actions() -> Keypad:
        """اقدامات چنل"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id="add_channel",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="اضافه کردن ➕"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="list_channels",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="لیست 🗒️"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="delete_channel",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="حذف کردن ➖"
                        )
                    ]
                ),
                KeypadRow(
                    buttons=[
                        Button(
                            id="back_admin",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="🔙 بازگشت"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )
    
    @staticmethod
    def yes_no_buttons(action: str, data: str = "") -> Keypad:
        """دکمه‌های تایید/لغو"""
        return Keypad(
            rows=[
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"confirm_{action}_{data}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="✅ آره"
                        ),
                        Button(
                            id=f"cancel_{action}_{data}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text="❌ نه"
                        )
                    ]
                )
            ],
            resize_keyboard=True,
            on_time_keyboard=True
        )

# ============================================================================
# ربات اصلی
# ============================================================================

class ConfigBot:
    """ربات اصلی مدیریت کانفیگ"""
    
    def __init__(self, token: str):
        self.token = token
        self.bot = BotClient(token)
        self.db = Database()
        self.state_manager = UserStateManager(self.db)
        self.admin_username = "Hunter_sfcb"
        self.version = "2.1.0"
        
        # ثبت هندلرها
        self.register_handlers()
    
    async def initialize(self):
        """راه‌اندازی اولیه"""
        await self.db.connect()
        
        # افزودن ادمین اصلی اگر وجود ندارد
        await self.ensure_admin_exists()
        
        logger.info("ربات راه‌اندازی شد")
    
    async def ensure_admin_exists(self):
        """اطمینان از وجود ادمین اصلی"""
        # اینجا باید آیدی عددی ادمین را جایگزین کنیم
        # برای تست، یک کاربر ادمین ایجاد می‌کنیم
        pass
    
    def register_handlers(self):
        """ثبت هندلرهای ربات"""
        
        # هندلر شروع
        @self.bot.on_update(filters.commands("start"))
        async def start_handler(client, update: Update):
            await self.handle_start(client, update)
        
        # هندلر پیام‌های متنی
        @self.bot.on_update(filters.text)
        async def text_handler(client, update: Update):
            await self.handle_text(client, update)
        
        # هندلر دکمه‌ها
        @self.bot.on_update(filters.button)
        async def button_handler(client, update: Update):
            await self.handle_button(client, update)
        
        # هندلر فایل‌ها
        @self.bot.on_update(filters.file)
        async def file_handler(client, update: Update):
            await self.handle_file(client, update)
    
    async def handle_start(self, client, update: Update):
        """مدیریت دستور /start"""
        user_guid = update.chat_id
        
        # ذخیره کاربر
        await self.db.add_or_update_user(
            user_guid=user_guid,
            username=update.new_message.sender_id if update.new_message else None,
            first_name=None,  # اطلاعات بیشتر از API دریافت شود
            last_name=None
        )
        
        # بررسی عضویت در چنل‌ها
        is_member = await self.db.check_channel_membership(user_guid)
        
        if not is_member:
            channels = await self.db.get_channels()
            if channels:
                channel_list = "\n".join([f"• {ch.channel_name}" for ch in channels])
                message = (
                    "⚠️ برای استفاده از ربات باید در چنل‌های زیر عضو شوید:\n\n"
                    f"{channel_list}\n\n"
                    "پس از عضویت، دوباره /start را بفرستید."
                )
                await update.reply(message)
                return
        
        # نمایش پنل مناسب
        is_admin = await self.db.is_admin(user_guid)
        
        if is_admin:
            await update.reply(
                "👨‍💼 پنل ادمین",
                inline_keypad=KeypadFactory.admin_panel()
            )
        else:
            await update.reply(
                "👤 پنل کاربر",
                inline_keypad=KeypadFactory.user_panel()
            )
    
    async def handle_text(self, client, update: Update):
        """مدیریت پیام‌های متنی"""
        user_guid = update.chat_id
        text = update.new_message.text if update.new_message else ""
        state = self.state_manager.get_state(user_guid)
        
        if not state:
            return
        
        state_type = state.get('state', '')
        
        if state_type == 'awaiting_config_type_name':
            # ذخیره نوع کانفیگ جدید
            try:
                await self.db.add_config_type(text, user_guid)
                await update.reply(
                    f"✅ نوع کانفیگ '{text}' با موفقیت اضافه شد.",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            except ValueError as e:
                await update.reply(
                    str(e),
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            self.state_manager.clear_state(user_guid)
        
        elif state_type == 'awaiting_tutorial_title':
            # ذخیره عنوان آموزش
            self.state_manager.set_state_value(user_guid, 'tutorial_title', text)
            self.state_manager.set_state(user_guid, 'awaiting_tutorial_content')
            await update.reply(
                "📝 محتوای آموزش را ارسال کنید (متن، عکس یا فایل):",
                inline_keypad=KeypadFactory.back_button("admin")
            )
        
        elif state_type == 'awaiting_tutorial_content' and text:
            # ذخیره محتوای آموزش متنی
            self.state_manager.set_state_value(user_guid, 'tutorial_content', text)
            self.state_manager.set_state(user_guid, 'awaiting_tutorial_app_file')
            await update.reply(
                "📱 آیا فایل اپلیکیشن (زیپ) دارید؟\n\n"
                "اگر دارید فایل را ارسال کنید، در غیر این صورت روی دکمه رد کردن کلیک کنید.",
                inline_keypad=Keypad(
                    rows=[
                        KeypadRow(
                            buttons=[
                                Button(
                                    id="skip_app_file",
                                    type=ButtonTypeEnum.SIMPLE,
                                    button_text="رد کردن ⏭️"
                                )
                            ]
                        ),
                        KeypadRow(
                            buttons=[
                                Button(
                                    id="back_admin",
                                    type=ButtonTypeEnum.SIMPLE,
                                    button_text="🔙 بازگشت"
                                )
                            ]
                        )
                    ],
                    resize_keyboard=True,
                    on_time_keyboard=True
                )
            )
        
        elif state_type == 'awaiting_channel_guid':
            # ذخیره آیدی چنل
            # در روبیکا باید بررسی شود که ربات ادمین است و دسترسی دارد
            try:
                channel_info = await client.get_chat(text)
                await self.db.add_channel(text, channel_info.title if hasattr(channel_info, 'title') else "Unknown", user_guid)
                await update.reply(
                    f"✅ چنل با موفقیت اضافه شد.",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            except Exception as e:
                await update.reply(
                    f"❌ خطا در اضافه کردن چنل: {str(e)}",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            self.state_manager.clear_state(user_guid)
    
    async def handle_button(self, client, update: Update):
        """مدیریت کلیک روی دکمه‌ها"""
        user_guid = update.chat_id
        button_id = update.new_message.aux_data.button_id if update.new_message and update.new_message.aux_data else ""
        
        if not button_id:
            return
        
        # بررسی ادمین بودن
        is_admin = await self.db.is_admin(user_guid)
        
        # هندلرهای عمومی
        if button_id == "get_config":
            await self.show_config_types_for_user(client, update)
        
        elif button_id == "tutorials":
            await self.show_tutorials(client, update)
        
        elif button_id == "version":
            await update.reply(f"🔄 نسخه ربات: {self.version}")
        
        elif button_id == "back_main":
            if is_admin:
                await update.reply(
                    "👨‍💼 پنل ادمین",
                    inline_keypad=KeypadFactory.admin_panel()
                )
            else:
                await update.reply(
                    "👤 پنل کاربر",
                    inline_keypad=KeypadFactory.user_panel()
                )
        
        elif button_id == "back_admin":
            await update.reply(
                "👨‍💼 پنل ادمین",
                inline_keypad=KeypadFactory.admin_panel()
            )
        
        # هندلرهای ادمین
        if not is_admin:
            return
        
        if button_id == "add_config":
            await self.show_config_types_for_admin(client, update)
        
        elif button_id == "config_status":
            await self.show_config_status(client, update)
        
        elif button_id == "config_types":
            await update.reply(
                "⚙️ مدیریت انواع کانفیگ:",
                inline_keypad=KeypadFactory.config_type_actions()
            )
        
        elif button_id == "add_type":
            self.state_manager.set_state(user_guid, 'awaiting_config_type_name')
            await update.reply(
                "📝 نام نوع کانفیگ جدید را وارد کنید (مثال: npv tunnel):",
                inline_keypad=KeypadFactory.back_button("admin")
            )
        
        elif button_id == "list_types":
            await self.list_config_types(client, update)
        
        elif button_id == "delete_type":
            await self.show_config_types_for_deletion(client, update)
        
        elif button_id == "add_config_file":
            await self.show_config_types_for_addition(client, update)
        
        elif button_id == "delete_config_file":
            await self.show_config_types_for_config_deletion(client, update)
        
        elif button_id == "tutorials_admin":
            await update.reply(
                "📚 مدیریت آموزش‌ها:",
                inline_keypad=KeypadFactory.tutorial_actions()
            )
        
        elif button_id == "add_tutorial":
            self.state_manager.set_state(user_guid, 'awaiting_tutorial_title')
            await update.reply(
                "📝 عنوان آموزش را وارد کنید:",
                inline_keypad=KeypadFactory.back_button("admin")
            )
        
        elif button_id == "delete_tutorial":
            await self.show_tutorials_for_deletion(client, update)
        
        elif button_id == "channels":
            await update.reply(
                "🛡️ مدیریت چنل‌ها:",
                inline_keypad=KeypadFactory.channel_actions()
            )
        
        elif button_id == "add_channel":
            self.state_manager.set_state(user_guid, 'awaiting_channel_guid')
            await update.reply(
                "🆔 آیدی چنل را ارسال کنید:\n\n"
                "ربات را در چنل ادمین کنید و آیدی چنل را ارسال نمایید.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
        
        elif button_id == "list_channels":
            await self.list_channels(client, update)
        
        elif button_id == "delete_channel":
            await self.show_channels_for_deletion(client, update)
        
        elif button_id == "users_list":
            await self.show_users_list(client, update)
        
        elif button_id.startswith("confirm_delete_type_"):
            type_id = button_id.split("_")[-1]
            success = await self.db.delete_config_type(int(type_id))
            if success:
                await update.reply(
                    "✅ نوع کانفیگ با موفقیت حذف شد.",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            else:
                await update.reply(
                    "❌ امکان حذف این نوع کانفیگ وجود ندارد (کانفیگ‌های مرتبط وجود دارند).",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
        
        elif button_id.startswith("cancel_delete_type_"):
            await update.reply(
                "❌ حذف کنسل شد.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
        
        elif button_id == "skip_app_file":
            # ذخیره آموزش بدون فایل اپلیکیشن
            state = self.state_manager.get_state(user_guid)
            if state and state.get('state') == 'awaiting_tutorial_app_file':
                title = self.state_manager.get_state_value(user_guid, 'tutorial_title')
                content = self.state_manager.get_state_value(user_guid, 'tutorial_content')
                
                try:
                    await self.db.add_tutorial(title, content, None, False, user_guid)
                    await update.reply(
                        f"✅ آموزش '{title}' با موفقیت اضافه شد.",
                        inline_keypad=KeypadFactory.back_button("admin")
                    )
                except Exception as e:
                    await update.reply(
                        f"❌ خطا در ذخیره آموزش: {str(e)}",
                        inline_keypad=KeypadFactory.back_button("admin")
                    )
                self.state_manager.clear_state(user_guid)
    
    async def handle_file(self, client, update: Update):
        """مدیریت ارسال فایل"""
        user_guid = update.chat_id
        state = self.state_manager.get_state(user_guid)
        
        if not state:
            return
        
        state_type = state.get('state', '')
        
        if state_type == 'awaiting_tutorial_content' and update.new_message.file:
            # ذخیره فایل به عنوان محتوای آموزش
            file_id = update.new_message.file.file_id
            self.state_manager.set_state_value(user_guid, 'tutorial_content_file_id', file_id)
            self.state_manager.set_state_value(user_guid, 'tutorial_content_type', 'file')
            self.state_manager.set_state(user_guid, 'awaiting_tutorial_app_file')
            
            await update.reply(
                "📱 آیا فایل اپلیکیشن (زیپ) دارید؟\n\n"
                "اگر دارید فایل را ارسال کنید، در غیر این صورت روی دکمه رد کردن کلیک کنید.",
                inline_keypad=Keypad(
                    rows=[
                        KeypadRow(
                            buttons=[
                                Button(
                                    id="skip_app_file",
                                    type=ButtonTypeEnum.SIMPLE,
                                    button_text="رد کردن ⏭️"
                                )
                            ]
                        ),
                        KeypadRow(
                            buttons=[
                                Button(
                                    id="back_admin",
                                    type=ButtonTypeEnum.SIMPLE,
                                    button_text="🔙 بازگشت"
                                )
                            ]
                        )
                    ],
                    resize_keyboard=True,
                    on_time_keyboard=True
                )
            )
        
        elif state_type == 'awaiting_tutorial_app_file' and update.new_message.file:
            # ذخیره فایل اپلیکیشن
            file_id = update.new_message.file.file_id
            title = self.state_manager.get_state_value(user_guid, 'tutorial_title')
            content = self.state_manager.get_state_value(user_guid, 'tutorial_content')
            content_file_id = self.state_manager.get_state_value(user_guid, 'tutorial_content_file_id')
            content_type = self.state_manager.get_state_value(user_guid, 'tutorial_content_type', 'text')
            
            try:
                if content_type == 'file':
                    await self.db.add_tutorial(title, content, content_file_id, True, user_guid)
                else:
                    await self.db.add_tutorial(title, content, None, True, user_guid)
                
                await update.reply(
                    f"✅ آموزش '{title}' با فایل اپلیکیشن اضافه شد.",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            except Exception as e:
                await update.reply(
                    f"❌ خطا در ذخیره آموزش: {str(e)}",
                    inline_keypad=KeypadFactory.back_button("admin")
                )
            
            self.state_manager.clear_state(user_guid)
    
    async def show_config_types_for_user(self, client, update: Update):
        """نمایش انواع کانفیگ برای کاربر"""
        config_types = await self.db.get_config_types()
        
        if not config_types:
            await update.reply(
                "⚠️ هیچ نوع کانفیگی تعریف نشده است.",
                inline_keypad=KeypadFactory.back_button("main")
            )
            return
        
        rows = []
        for config_type in config_types:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"user_config_type_{config_type.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=config_type.name
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_main",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🌐 لطفا نوع کانفیگ مورد نظر را انتخاب کنید:",
            inline_keypad=keypad
        )
    
    async def show_config_types_for_admin(self, client, update: Update):
        """نمایش انواع کانفیگ برای ادمین (برای افزودن کانفیگ)"""
        config_types = await self.db.get_config_types()
        
        if not config_types:
            await update.reply(
                "⚠️ ابتدا نوع کانفیگ ایجاد کنید.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        rows = []
        for config_type in config_types:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"admin_add_to_type_{config_type.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=f"➕ {config_type.name}"
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_admin",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🗄️ افزودن کانفیگ به کدام نوع؟",
            inline_keypad=keypad
        )
    
    async def list_config_types(self, client, update: Update):
        """لیست انواع کانفیگ"""
        config_types = await self.db.get_config_types()
        
        if not config_types:
            await update.reply(
                "📭 لیست انواع کانفیگ خالی است.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        message = "📋 لیست انواع کانفیگ:\n\n"
        for i, config_type in enumerate(config_types, 1):
            message += f"{i}. {config_type.name}\n   👤 ایجاد کننده: {config_type.created_by}\n   🕒 تاریخ: {config_type.created_at[:10]}\n\n"
        
        await update.reply(
            message,
            inline_keypad=KeypadFactory.back_button("admin")
        )
    
    async def show_config_types_for_deletion(self, client, update: Update):
        """نمایش انواع کانفیگ برای حذف"""
        config_types = await self.db.get_config_types()
        
        if not config_types:
            await update.reply(
                "📭 لیست انواع کانفیگ خالی است.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        rows = []
        for config_type in config_types:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"delete_type_{config_type.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=config_type.name
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_admin",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🗑️ کدام نوع کانفیگ را حذف می‌کنید؟",
            inline_keypad=keypad
        )
    
    async def show_config_types_for_config_deletion(self, client, update: Update):
        """نمایش انواع کانفیگ برای حذف کانفیگ"""
        config_types = await self.db.get_config_types()
        
        if not config_types:
            await update.reply(
                "⚠️ ابتدا نوع کانفیگ ایجاد کنید.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        rows = []
        for config_type in config_types:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"admin_delete_from_type_{config_type.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=f"➖ {config_type.name}"
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_admin",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🗑️ حذف کانفیگ از کدام نوع؟",
            inline_keypad=keypad
        )
    
    async def show_config_status(self, client, update: Update):
        """نمایش وضعیت کانفیگ‌ها"""
        configs = await self.db.get_all_configs()
        config_types = await self.db.get_config_types()
        
        if not configs:
            await update.reply(
                "📭 هیچ کانفیگی وجود ندارد.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        # گروه‌بندی کانفیگ‌ها بر اساس نوع
        type_dict = {ct.id: ct.name for ct in config_types}
        
        message = "📡 وضعیت کانفیگ‌ها:\n\n"
        for config in configs:
            type_name = type_dict.get(config.type_id, "ناشناخته")
            status = "🟢 فعال" if config.is_active else "🔴 غیرفعال"
            message += f"• {type_name}: {config.name}\n  {status}\n\n"
        
        await update.reply(
            message,
            inline_keypad=Keypad(
                rows=[
                    KeypadRow(
                        buttons=[
                            Button(
                                id="toggle_config_status",
                                type=ButtonTypeEnum.SIMPLE,
                                button_text="تغییر وضعیت کانفیگ 🔄"
                            )
                        ]
                    ),
                    KeypadRow(
                        buttons=[
                            Button(
                                id="back_admin",
                                type=ButtonTypeEnum.SIMPLE,
                                button_text="🔙 بازگشت"
                            )
                        ]
                    )
                ],
                resize_keyboard=True,
                on_time_keyboard=True
            )
        )
    
    async def show_tutorials(self, client, update: Update):
        """نمایش آموزش‌ها برای کاربر"""
        tutorials = await self.db.get_tutorials()
        
        if not tutorials:
            await update.reply(
                "📭 هیچ آموزشی وجود ندارد.",
                inline_keypad=KeypadFactory.back_button("main")
            )
            return
        
        rows = []
        for tutorial in tutorials:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"view_tutorial_{tutorial.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=tutorial.title
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_main",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "📚 لیست آموزش‌ها:",
            inline_keypad=keypad
        )
    
    async def show_tutorials_for_deletion(self, client, update: Update):
        """نمایش آموزش‌ها برای حذف"""
        tutorials = await self.db.get_tutorials()
        
        if not tutorials:
            await update.reply(
                "📭 هیچ آموزشی برای حذف وجود ندارد.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        rows = []
        for tutorial in tutorials:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"delete_tutorial_{tutorial.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=tutorial.title
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_admin",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🗑️ کدام آموزش را حذف می‌کنید؟",
            inline_keypad=keypad
        )
    
    async def list_channels(self, client, update: Update):
        """لیست چنل‌ها"""
        channels = await self.db.get_channels()
        
        if not channels:
            await update.reply(
                "📭 هیچ چنلی ثبت نشده است.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        message = "🛡️ لیست چنل‌ها:\n\n"
        for i, channel in enumerate(channels, 1):
            message += f"{i}. {channel.channel_name}\n   🆔: {channel.channel_guid}\n   👤 اضافه کننده: {channel.added_by}\n\n"
        
        await update.reply(
            message,
            inline_keypad=KeypadFactory.back_button("admin")
        )
    
    async def show_channels_for_deletion(self, client, update: Update):
        """نمایش چنل‌ها برای حذف"""
        channels = await self.db.get_channels()
        
        if not channels:
            await update.reply(
                "📭 هیچ چنلی برای حذف وجود ندارد.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        rows = []
        for channel in channels:
            rows.append(
                KeypadRow(
                    buttons=[
                        Button(
                            id=f"delete_channel_{channel.id}",
                            type=ButtonTypeEnum.SIMPLE,
                            button_text=channel.channel_name
                        )
                    ]
                )
            )
        
        rows.append(
            KeypadRow(
                buttons=[
                    Button(
                        id="back_admin",
                        type=ButtonTypeEnum.SIMPLE,
                        button_text="🔙 بازگشت"
                    )
                ]
            )
        )
        
        keypad = Keypad(
            rows=rows,
            resize_keyboard=True,
            on_time_keyboard=True
        )
        
        await update.reply(
            "🗑️ کدام چنل را حذف می‌کنید؟",
            inline_keypad=keypad
        )
    
    async def show_users_list(self, client, update: Update):
        """نمایش لیست کاربران"""
        users = await self.db.get_all_users()
        
        if not users:
            await update.reply(
                "📭 هیچ کاربری ثبت نشده است.",
                inline_keypad=KeypadFactory.back_button("admin")
            )
            return
        
        message = "📁 لیست کاربران:\n\n"
        for i, user in enumerate(users, 1):
            admin_status = "👑 ادمین" if user.is_admin else "👤 کاربر"
            message += f"{i}. {user.first_name or ''} {user.last_name or ''}\n   🆔: {user.user_guid}\n   {admin_status}\n   📅 تاریخ شروع: {user.start_date[:10]}\n\n"
        
        await update.reply(
            message,
            inline_keypad=KeypadFactory.back_button("admin")
        )
    
    async def run(self):
        """اجرای ربات"""
        await self.initialize()
        await self.bot.run()
    
    async def cleanup(self):
        """تمیزکاری منابع"""
        await self.db.close()

# ============================================================================
# اجرای ربات
# ============================================================================

async def main():
    """تابع اصلی اجرای ربات"""
    
    # خواندن توکن از فایل یا متغیر محیطی
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    TOKEN = os.getenv("RUBIKA_BOT_TOKEN")
    
    if not TOKEN:
        logger.error("توکن ربات یافت نشد. لطفا متغیر محیطی RUBIKA_BOT_TOKEN را تنظیم کنید.")
        return
    
    # ساخت و اجرای ربات
    bot = ConfigBot(TOKEN)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("ربات متوقف شد.")
    finally:
        await bot.cleanup()

if __name__ == "__main__":
    # اجرای ربات
    asyncio.run(main())
