# main.py
import os
import asyncio
import io
import logging
import sys
from html import escape
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile, CallbackQuery, Message, BotCommand, Update
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# === FastAPI & Webhook ===
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")  # ✅ إزالة / الزائد

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not found in .env")

DATA_DIR = Path(os.getenv("BOT_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.getenv("BOT_DB_PATH", str(DATA_DIR / "management_system_v3.db"))

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


# ============================================================
# 1. قاعدة البيانات
# ============================================================
class DatabaseManager:
    def __init__(self, path: str):
        self.path = path
        self._db: aiosqlite.Connection | None = None  # ✅ اتصال دائم

    async def _get_conn(self) -> aiosqlite.Connection:
        """استخدام اتصال دائم بدل فتح اتصال جديد لكل استعلام"""
        if self._db is None:
            self._db = await aiosqlite.connect(self.path, timeout=30)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.execute("PRAGMA busy_timeout = 30000")
            await self._db.execute("PRAGMA journal_mode = WAL")
        return self._db

    async def init_db(self):
        db = await self._get_conn()
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                role TEXT DEFAULT 'مستخدم'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id INTEGER,
                permission TEXT,
                PRIMARY KEY (user_id, permission),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_id INTEGER,
                activity TEXT,
                proposed_time TEXT,
                status TEXT DEFAULT 'مقترح',
                converted_to_task INTEGER DEFAULT NULL,
                converted_to_meeting INTEGER DEFAULT NULL,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(dept_id) REFERENCES departments(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS proposal_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id INTEGER,
                update_text TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(proposal_id) REFERENCES proposals(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT DEFAULT 'متوسطة',
                status TEXT DEFAULT 'قيد التنفيذ',
                due_date TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by) REFERENCES users(user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS task_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                update_text TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                meeting_date TEXT,
                location TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by) REFERENCES users(user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS meeting_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER,
                item_type TEXT,
                item_text TEXT,
                FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                file_name TEXT,
                file_type TEXT,
                ref_type TEXT,
                ref_id INTEGER,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_attachments_ref ON attachments (ref_type, ref_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)")
        await db.commit()

    async def execute(self, query: str, params: tuple = ()):
        try:
            db = await self._get_conn()
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"DB Error: {e} | {query}")
            raise

    async def fetchall(self, query: str, params: tuple = ()):
        try:
            db = await self._get_conn()
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"DB Fetch Error: {e} | {query}")
            return []

    async def fetchone(self, query: str, params: tuple = ()):
        try:
            db = await self._get_conn()
            async with db.execute(query, params) as cursor:
                return await cursor.fetchone()
        except Exception as e:
            logger.error(f"DB FetchOne Error: {e} | {query}")
            return None

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None


db = DatabaseManager(DB_PATH)
router = Router()


# ============================================================
# 2. الصلاحيات
# ============================================================
PERMISSIONS_LIST = [
    "manage_tasks", "manage_meetings", "manage_proposals",
    "manage_attachments", "view_reports", "manage_users"
]
PERMISSION_NAMES = {
    "manage_tasks": "📋 المهام",
    "manage_meetings": "📅 الاجتماعات",
    "manage_proposals": "💡 المقترحات",
    "manage_attachments": "📂 الأرشيف",
    "view_reports": "📊 التقارير",
    "manage_users": "👥 المستخدمين"
}

# خريطة بادئات الـ callback → الصلاحية المطلوبة
_CALLBACK_PREFIX_MAP = {
    "t_": "manage_tasks", "prio_": "manage_tasks", "m_tasks": "manage_tasks",
    "mt_": "manage_meetings", "mitem_": "manage_meetings", "m_meets": "manage_meetings",
    "p_": "manage_proposals", "seldept_": "manage_proposals", "d_": "manage_proposals",
    "m_props": "manage_proposals", "m_depts": "manage_proposals",
    "att_": "manage_attachments", "dl_": "manage_attachments", "m_arch": "manage_attachments",
    "exp_": "view_reports", "dash": "view_reports", "m_reps": "view_reports",
    "u_": "manage_users", "tog_": "manage_users", "m_users": "manage_users",
}


async def get_user_role(user_id: int) -> str:
    u = await db.fetchone("SELECT role FROM users WHERE user_id = ?", (user_id,))
    return u['role'] if u else 'مستخدم'


async def has_permission(user_id: int, perm: str) -> bool:
    role = await get_user_role(user_id)
    if role == 'مدير نظام':
        return True
    row = await db.fetchone(
        "SELECT 1 FROM user_permissions WHERE user_id = ? AND permission = ?",
        (user_id, perm)
    )
    return row is not None


async def get_user_permissions(user_id: int) -> list:
    role = await get_user_role(user_id)
    if role == 'مدير نظام':
        return PERMISSIONS_LIST.copy()
    rows = await db.fetchall(
        "SELECT permission FROM user_permissions WHERE user_id = ?",
        (user_id,)
    )
    return [r['permission'] for r in rows]


async def set_user_permission(user_id: int, perm: str, value: bool):
    if value:
        await db.execute(
            "INSERT OR IGNORE INTO user_permissions (user_id, permission) VALUES (?,?)",
            (user_id, perm)
        )
    else:
        await db.execute(
            "DELETE FROM user_permissions WHERE user_id = ? AND permission = ?",
            (user_id, perm)
        )


def _get_required_permission(callback_data: str) -> str | None:
    """تحديد الصلاحية المطلوبة من بادئة الـ callback_data"""
    for prefix, perm in _CALLBACK_PREFIX_MAP.items():
        if callback_data.startswith(prefix):
            return perm
    return None


# ============================================================
# 3. Middleware للصلاحيات (مُصحَّح)
# ============================================================
class PermissionMiddleware(BaseMiddleware):  # ✅ يرث من BaseMiddleware
    async def __call__(self, handler, event, data):
        value = event.data or ""
        permission = _get_required_permission(value)
        if permission and not await has_permission(event.from_user.id, permission):
            await event.answer("⛔ لا تملك الصلاحية اللازمة لهذا الإجراء", show_alert=True)
            return
        return await handler(event, data)


# ✅ تسجيل الـ middleware بعد تعريف الكلاس
router.callback_query.outer_middleware(PermissionMiddleware())


# ============================================================
# 4. دوال مساعدة
# ============================================================
def clean_text(value, max_length=3500) -> str:
    """تهريب HTML لمنع XSS"""
    if value is None:
        return ""
    return escape(str(value).strip()[:max_length])


def parse_callback_id(data: str, prefix: str):
    try:
        return int(data.removeprefix(prefix))
    except (TypeError, ValueError):
        return None


def cancel_kb():
    b = InlineKeyboardBuilder()
    b.button(text="❌ إلغاء", callback_data="cancel")
    return b.as_markup()


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None):
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            await cb.answer("⏳ أنت بالفعل في هذه الصفحة", show_alert=False)
        else:
            logger.error(f"Edit Error: {e}")


async def main_menu_kb(user_id: int):
    perms = await get_user_permissions(user_id)
    b = InlineKeyboardBuilder()
    if "manage_tasks" in perms:
        b.button(text="📋 المهام", callback_data="m_tasks")
    if "manage_meetings" in perms:
        b.button(text="📅 الاجتماعات", callback_data="m_meets")
    if "manage_proposals" in perms:
        b.button(text="💡 المقترحات", callback_data="m_props")
    if "manage_attachments" in perms:
        b.button(text="📂 الأرشيف", callback_data="m_arch")
    if "view_reports" in perms:
        b.button(text="📊 التقارير", callback_data="m_reps")
    if "manage_users" in perms:
        b.button(text="👥 المستخدمين", callback_data="m_users")
    b.button(text="👤 ملفي", callback_data="m_prof")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


# ============================================================
# 5. التنقل الأساسي
# ============================================================
@router.message(CommandStart())
async def start_cmd(msg: Message, state: FSMContext):
    await state.clear()
    # ✅ معالجة سباق البيانات: INSERT أولاً ثم فحص
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, full_name, username, role) VALUES (?,?,?,?)",
        (msg.from_user.id, msg.from_user.full_name, msg.from_user.username, 'مستخدم')
    )
    await db.execute(
        "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
        (msg.from_user.full_name, msg.from_user.username, msg.from_user.id)
    )
    # تعيين أول مستخدم كمدير نظام (آمنًا)
    count_row = await db.fetchone("SELECT COUNT(*) as c FROM users")
    if count_row and count_row['c'] == 1:
        await db.execute(
            "UPDATE users SET role = 'مدير نظام' WHERE user_id = ? AND role = 'مستخدم'",
            (msg.from_user.id,)
        )
        for p in PERMISSIONS_LIST:
            await set_user_permission(msg.from_user.id, p, True)

    kb = await main_menu_kb(msg.from_user.id)
    await msg.answer(
        f"أهلاً بك <b>{clean_text(msg.from_user.first_name)}</b> "
        f"في نظام متابعة الأداء المتكامل 🚀",
        reply_markup=kb
    )


@router.message(Command("cancel"))
async def cancel_command(msg: Message, state: FSMContext):
    await state.clear()
    kb = await main_menu_kb(msg.from_user.id)
    await msg.answer("🏠 تم إلغاء العملية الحالية والعودة للرئيسية:", reply_markup=kb)


@router.callback_query(F.data == "cancel")
async def cancel_action(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = await main_menu_kb(cb.from_user.id)
    await safe_edit(cb, "🏠 القائمة الرئيسية:", reply_markup=kb)


@router.callback_query(F.data.startswith("m_"))
async def menu_nav(cb: CallbackQuery):
    target = cb.data.split("_", 1)[1] if "_" in cb.data else cb.data

    if target == "main":
        kb = await main_menu_kb(cb.from_user.id)
        await safe_edit(cb, "🏠 الرئيسية:", reply_markup=kb)

    elif target == "prof":
        u = await db.fetchone("SELECT * FROM users WHERE user_id = ?", (cb.from_user.id,))
        if not u:
            return await cb.answer("⚠️ السجل غير موجود", show_alert=True)
        perms = await get_user_permissions(cb.from_user.id)
        perms_txt = ", ".join([PERMISSION_NAMES.get(p, p) for p in perms]) or "لا يوجد"
        txt = (
            f"👤 <b>{clean_text(u['full_name'])}</b>\n"
            f"معرف المستخدم: <code>{u['user_id']}</code>\n"
            f"الدور: {u['role']}\n\n"
            f"الصلاحيات المتاحة:\n{perms_txt}"
        )
        b = InlineKeyboardBuilder()
        b.button(text="🔙 عودة", callback_data="m_main")
        await safe_edit(cb, txt, reply_markup=b.as_markup())

    elif target == "tasks":
        if not await has_permission(cb.from_user.id, "manage_tasks"):
            return await cb.answer("⛔ لا تملك صلاحية إدارة المهام", show_alert=True)
        b = InlineKeyboardBuilder()
        b.button(text="➕ مهمة جديدة", callback_data="t_add")
        b.button(text="🔍 قيد التنفيذ", callback_data="t_list_pend")
        b.button(text="🟢 مكتملة", callback_data="t_list_done")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(1, 2, 1)
        await safe_edit(cb, "📋 <b>إدارة المهام:</b>", reply_markup=b.as_markup())

    elif target == "meets":
        if not await has_permission(cb.from_user.id, "manage_meetings"):
            return await cb.answer("⛔ لا تملك صلاحية إدارة الاجتماعات", show_alert=True)
        b = InlineKeyboardBuilder()
        b.button(text="➕ جدولة اجتماع", callback_data="mt_add")
        b.button(text="📋 قائمة الاجتماعات", callback_data="mt_list")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(2, 1)
        await safe_edit(cb, "📅 <b>إدارة الاجتماعات:</b>", reply_markup=b.as_markup())

    elif target == "props":
        if not await has_permission(cb.from_user.id, "manage_proposals"):
            return await cb.answer("⛔ لا تملك صلاحية إدارة المقترحات", show_alert=True)
        b = InlineKeyboardBuilder()
        b.button(text="➕ مقترح جديد", callback_data="p_add")
        b.button(text="📋 عرض حسب الإدارة", callback_data="p_list_depts")
        b.button(text="🏢 تنظيم الإدارات", callback_data="m_depts")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(1, 2, 1)
        await safe_edit(cb, "💡 <b>إدارة المقترحات:</b>", reply_markup=b.as_markup())

    elif target == "depts":
        depts = await db.fetchall("SELECT * FROM departments ORDER BY name")
        # ✅ إصلاح منطق or
        if depts:
            lines = "\n".join(f"▪️ {clean_text(d['name'])}" for d in depts)
            txt = f"🏢 <b>الإدارات المسجلة بالنظام:</b>\n\n{lines}"
        else:
            txt = "🏢 لا يوجد إدارات حالياً."
        b = InlineKeyboardBuilder()
        b.button(text="➕ إضافة إدارة", callback_data="d_add")
        for d in depts:
            b.button(text=f"🗑 حذف: {d['name'][:22]}", callback_data=f"d_delete_{d['id']}")
        b.button(text="🔙 عودة", callback_data="m_props")
        b.adjust(1)
        await safe_edit(cb, txt, reply_markup=b.as_markup())

    elif target == "arch":
        if not await has_permission(cb.from_user.id, "manage_attachments"):
            return await cb.answer("⛔ لا تملك صلاحية الأرشيف", show_alert=True)
        atts = await db.fetchall("SELECT * FROM attachments ORDER BY id DESC LIMIT 10")
        if not atts:
            b = InlineKeyboardBuilder()
            b.button(text="🔙 الرئيسية", callback_data="m_main")
            await safe_edit(cb, "📂 الأرشيف المركزي فارغ.", reply_markup=b.as_markup())
            return
        txt = "📂 <b>أحدث الملفات المؤرشفة:</b>\n\n"
        b = InlineKeyboardBuilder()
        for a in atts:
            txt += (
                f"📎 {clean_text(a['file_name'])}\n"
                f"نوع الارتباط: {a['ref_type']} #{a['ref_id']} | "
                f"📅 {a['uploaded_at'][:16]}\n\n"
            )
            b.button(text=f"📥 تحميل {a['file_name'][:15]}...", callback_data=f"dl_{a['id']}")
            b.button(text=f"🗑 حذف #{a['id']}", callback_data=f"att_delete_{a['id']}")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(1)
        await safe_edit(cb, txt, reply_markup=b.as_markup())

    elif target == "reps":
        if not await has_permission(cb.from_user.id, "view_reports"):
            return await cb.answer("⛔ لا تملك صلاحية التقارير", show_alert=True)
        b = InlineKeyboardBuilder()
        b.button(text="📊 تقرير المهام", callback_data="exp_tasks")
        b.button(text="📊 تقرير المقترحات", callback_data="exp_props")
        b.button(text="📊 تقرير المتابعات", callback_data="exp_updates")
        b.button(text="📈 لوحة المؤشرات", callback_data="dash")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(2, 2, 1)
        await safe_edit(cb, "📊 <b>مركز التقارير والإحصائيات:</b>", reply_markup=b.as_markup())

    elif target == "users":
        if not await has_permission(cb.from_user.id, "manage_users"):
            return await cb.answer("⛔ لا تملك صلاحية إدارة المستخدمين", show_alert=True)
        users = await db.fetchall("SELECT * FROM users ORDER BY user_id")
        b = InlineKeyboardBuilder()
        b.button(text="➕ تسجيل مستخدم جديد", callback_data="u_add")
        for u in users:
            icon = "👑" if u['role'] == 'مدير نظام' else "👤"
            b.button(text=f"{icon} {u['full_name']}", callback_data=f"u_view_{u['user_id']}")
        b.button(text="🔙 الرئيسية", callback_data="m_main")
        b.adjust(1)
        await safe_edit(cb, "👥 <b>إدارة هيكل المستخدمين:</b>", reply_markup=b.as_markup())


# ============================================================
# 6. المهام
# ============================================================
class TaskFSM(StatesGroup):
    title = State(); desc = State(); prio = State(); due = State()

class TaskUpdateFSM(StatesGroup):
    text = State()


@router.callback_query(F.data == "t_add")
async def task_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TaskFSM.title)
    await safe_edit(cb, "✏️ <b>أدخل عنوان المهمة الجديدة:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(TaskFSM.title))
async def task_title(msg: Message, state: FSMContext):
    if not msg.text or len(msg.text.strip()) < 3:
        return await msg.answer("⚠️ العنوان قصير جداً. حاول مرة أخرى:", reply_markup=cancel_kb())
    await state.update_data(title=msg.text.strip())
    await state.set_state(TaskFSM.desc)
    await msg.answer("📝 <b>أدخل تفاصيل ووصف المهمة:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(TaskFSM.desc))
async def task_desc(msg: Message, state: FSMContext):
    await state.update_data(desc=msg.text or "بدون وصف")
    await state.set_state(TaskFSM.prio)
    b = InlineKeyboardBuilder()
    b.button(text="🔴 أولوية عالية", callback_data="prio_عالية")
    b.button(text="🟡 أولوية متوسطة", callback_data="prio_متوسطة")
    b.button(text="🟢 أولوية عادية", callback_data="prio_عادية")
    b.adjust(1)
    await msg.answer("🎯 <b>حدد مستوى الأولوية:</b>", reply_markup=b.as_markup())


@router.callback_query(StateFilter(TaskFSM.prio), F.data.startswith("prio_"))
async def task_prio(cb: CallbackQuery, state: FSMContext):
    prio = cb.data.split("_", 1)[1]
    await state.update_data(prio=prio)
    await state.set_state(TaskFSM.due)
    await safe_edit(cb, "📅 <b>أدخل الموعد النهائي (مثال: 2026-12-31):</b>", reply_markup=cancel_kb())


@router.message(StateFilter(TaskFSM.due))
async def task_due(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO tasks (title, description, priority, due_date, created_by) VALUES (?,?,?,?,?)",
        (data['title'], data['desc'], data['prio'], msg.text, msg.from_user.id)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="➕ إضافة مهمة أخرى", callback_data="t_add")
    b.button(text="🔙 عودة للمهام", callback_data="m_tasks")
    b.adjust(1)
    await msg.answer("✅ تم إدراج المهمة بنجاح ضمن دورة العمل.", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("t_list_"))
async def tasks_list(cb: CallbackQuery):
    status = 'قيد التنفيذ' if cb.data == "t_list_pend" else 'مكتملة'
    tasks = await db.fetchall(
        "SELECT * FROM tasks WHERE status = ? ORDER BY id DESC LIMIT 40",
        (status,)
    )
    if not tasks:
        b = InlineKeyboardBuilder()
        b.button(text="🔙 عودة", callback_data="m_tasks")
        await safe_edit(cb, f"📭 سجل المهام فارغ للحالة: {status}.", reply_markup=b.as_markup())
        return
    b = InlineKeyboardBuilder()
    for t in tasks:
        icon = "🔴" if t['priority'] == 'عالية' else "🟡" if t['priority'] == 'متوسطة' else "🟢"
        b.button(text=f"{icon} #{t['id']} | {t['title'][:25]}", callback_data=f"t_view_{t['id']}")
    b.button(text="🔙 عودة للمهام", callback_data="m_tasks")
    b.adjust(1)
    await safe_edit(cb, f"📋 <b>استعراض المهام ({status}):</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("t_view_"))
async def task_view(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2])
    t = await db.fetchone("SELECT * FROM tasks WHERE id = ?", (tid,))
    if not t:
        return await cb.answer("⚠️ السجل غير موجود", show_alert=True)
    updates_cnt = (await db.fetchone(
        "SELECT COUNT(*) as c FROM task_updates WHERE task_id=?", (tid,)
    ))['c']

    txt = (
        f"📌 <b>المهمة #{t['id']}: {clean_text(t['title'])}</b>\n"
        f"──────────────\n"
        f"📝 الوصف: {clean_text(t['description'])}\n"
        f"🎯 الأولوية: {t['priority']}\n"
        f"📅 الاستحقاق: {clean_text(t['due_date'])}\n"
        f"🔄 الحالة الحالية: {t['status']}\n"
        f"💬 حجم الإفادات والمتابعة: {updates_cnt}\n"
    )

    b = InlineKeyboardBuilder()
    if t['status'] != 'مكتملة':
        b.button(text="✅ إغلاق واعتماد الإكمال", callback_data=f"t_done_{tid}")
        b.button(text="💬 رفع إفادة/متابعة", callback_data=f"t_add_upd_{tid}")
        b.button(text="📜 عرض سجل الإفادات", callback_data=f"t_upds_{tid}")
        b.button(text="📎 إرفاق مستند", callback_data=f"att_start_task_{tid}")
        b.button(text="🗑 حذف المهمة", callback_data=f"t_delete_{tid}")
        b.button(text="🔙 القائمة", callback_data="m_tasks")
        b.adjust(1, 2, 2, 1)
    else:
        b.button(text="📜 عرض سجل الإفادات", callback_data=f"t_upds_{tid}")
        b.button(text="📎 إرفاق مستند", callback_data=f"att_start_task_{tid}")
        b.button(text="🗑 حذف المهمة", callback_data=f"t_delete_{tid}")
        b.button(text="🔙 القائمة", callback_data="m_tasks")
        b.adjust(2, 2, 1)
    await safe_edit(cb, txt, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("t_delete_") & ~F.data.startswith("t_delete_confirm_"))
async def task_delete_confirm(cb: CallbackQuery):
    tid = parse_callback_id(cb.data, "t_delete_")
    task = await db.fetchone("SELECT title FROM tasks WHERE id = ?", (tid,)) if tid is not None else None
    if not task:
        return await cb.answer("⚠️ المهمة غير موجودة", show_alert=True)
    b = InlineKeyboardBuilder()
    b.button(text="✅ نعم، احذف نهائياً", callback_data=f"t_delete_confirm_{tid}")
    b.button(text="❌ إلغاء", callback_data=f"t_view_{tid}")
    b.adjust(1)
    await safe_edit(
        cb,
        f"⚠️ <b>تأكيد حذف المهمة #{tid}</b>\n\n"
        f"{clean_text(task['title'])}\n\n"
        f"سيتم حذف المتابعات والمرفقات المرتبطة بها.",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("t_delete_confirm_"))
async def task_delete_execute(cb: CallbackQuery):
    tid = parse_callback_id(cb.data, "t_delete_confirm_")
    if tid is None:
        return await cb.answer("⚠️ رقم غير صالح", show_alert=True)
    await db.execute("DELETE FROM task_updates WHERE task_id=?", (tid,))
    await db.execute("DELETE FROM attachments WHERE ref_type='task' AND ref_id=?", (tid,))
    await db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    await cb.answer("✅ تم حذف المهمة نهائياً")
    await menu_nav(cb)


@router.callback_query(F.data.startswith("mt_delete_") & ~F.data.startswith("mt_delete_confirm_"))
async def meeting_delete_confirm(cb: CallbackQuery):
    mid = parse_callback_id(cb.data, "mt_delete_")
    row = await db.fetchone("SELECT title FROM meetings WHERE id=?", (mid,)) if mid is not None else None
    if not row:
        return await cb.answer("⚠️ الاجتماع غير موجود", show_alert=True)
    b = InlineKeyboardBuilder()
    b.button(text="✅ نعم، احذف نهائياً", callback_data=f"mt_delete_confirm_{mid}")
    b.button(text="❌ إلغاء", callback_data=f"mt_view_{mid}")
    b.adjust(1)
    await safe_edit(
        cb,
        f"⚠️ <b>تأكيد حذف الاجتماع #{mid}</b>\n\n"
        f"{clean_text(row['title'])}\n\n"
        f"سيتم حذف البنود والمرفقات المرتبطة به.",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("mt_delete_confirm_"))
async def meeting_delete_execute(cb: CallbackQuery):
    mid = parse_callback_id(cb.data, "mt_delete_confirm_")
    if mid is None:
        return await cb.answer("⚠️ رقم غير صالح", show_alert=True)
    await db.execute("DELETE FROM meeting_items WHERE meeting_id=?", (mid,))
    await db.execute("DELETE FROM attachments WHERE ref_type='meet' AND ref_id=?", (mid,))
    await db.execute("DELETE FROM meetings WHERE id=?", (mid,))
    await cb.answer("✅ تم حذف الاجتماع نهائياً")
    await menu_nav(cb)


@router.callback_query(F.data.startswith("p_delete_") & ~F.data.startswith("p_delete_confirm_"))
async def proposal_delete_confirm(cb: CallbackQuery):
    pid = parse_callback_id(cb.data, "p_delete_")
    row = await db.fetchone("SELECT activity FROM proposals WHERE id=?", (pid,)) if pid is not None else None
    if not row:
        return await cb.answer("⚠️ المقترح غير موجود", show_alert=True)
    b = InlineKeyboardBuilder()
    b.button(text="✅ نعم، احذف نهائياً", callback_data=f"p_delete_confirm_{pid}")
    b.button(text="❌ إلغاء", callback_data=f"p_view_{pid}")
    b.adjust(1)
    await safe_edit(
        cb,
        f"⚠️ <b>تأكيد حذف المقترح #{pid}</b>\n\n"
        f"{clean_text(row['activity'])}\n\n"
        f"سيتم حذف سجل المتابعات فقط، ولن تُحذف المهمة أو الاجتماع الناتج عنه.",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("p_delete_confirm_"))
async def proposal_delete_execute(cb: CallbackQuery):
    pid = parse_callback_id(cb.data, "p_delete_confirm_")
    if pid is None:
        return await cb.answer("⚠️ رقم غير صالح", show_alert=True)
    await db.execute("DELETE FROM proposal_updates WHERE proposal_id=?", (pid,))
    await db.execute("DELETE FROM proposals WHERE id=?", (pid,))
    await cb.answer("✅ تم حذف المقترح نهائياً")
    await menu_nav(cb)


@router.callback_query(F.data.startswith("d_delete_") & ~F.data.startswith("d_delete_confirm_"))
async def department_delete_confirm(cb: CallbackQuery):
    did = parse_callback_id(cb.data, "d_delete_")
    row = await db.fetchone("SELECT name FROM departments WHERE id=?", (did,)) if did is not None else None
    if not row:
        return await cb.answer("⚠️ الإدارة غير موجودة", show_alert=True)
    count = await db.fetchone("SELECT COUNT(*) AS c FROM proposals WHERE dept_id=?", (did,))
    if count and count['c']:
        return await cb.answer("⛔ احذف مقترحات الإدارة أولاً", show_alert=True)
    b = InlineKeyboardBuilder()
    b.button(text="✅ نعم، احذف الإدارة", callback_data=f"d_delete_confirm_{did}")
    b.button(text="❌ إلغاء", callback_data="m_depts")
    b.adjust(1)
    await safe_edit(cb, f"⚠️ <b>تأكيد حذف الإدارة</b>\n\n{clean_text(row['name'])}", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("d_delete_confirm_"))
async def department_delete_execute(cb: CallbackQuery):
    did = parse_callback_id(cb.data, "d_delete_confirm_")
    if did is None:
        return await cb.answer("⚠️ رقم غير صالح", show_alert=True)
    await db.execute("DELETE FROM departments WHERE id=?", (did,))
    await cb.answer("✅ تم حذف الإدارة")
    await menu_nav(cb)


@router.callback_query(F.data.startswith("att_delete_") & ~F.data.startswith("att_delete_confirm_"))
async def attachment_delete_confirm(cb: CallbackQuery):
    aid = parse_callback_id(cb.data, "att_delete_")
    row = await db.fetchone("SELECT file_name FROM attachments WHERE id=?", (aid,)) if aid is not None else None
    if not row:
        return await cb.answer("⚠️ المرفق غير موجود", show_alert=True)
    b = InlineKeyboardBuilder()
    b.button(text="✅ نعم، احذف المرفق", callback_data=f"att_delete_confirm_{aid}")
    b.button(text="❌ إلغاء", callback_data="m_arch")
    b.adjust(1)
    await safe_edit(cb, f"⚠️ <b>تأكيد حذف المرفق</b>\n\n{clean_text(row['file_name'])}", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("att_delete_confirm_"))
async def attachment_delete_execute(cb: CallbackQuery):
    aid = parse_callback_id(cb.data, "att_delete_confirm_")
    if aid is None:
        return await cb.answer("⚠️ رقم غير صالح", show_alert=True)
    await db.execute("DELETE FROM attachments WHERE id=?", (aid,))
    await cb.answer("✅ تم حذف المرفق")
    await menu_nav(cb)


@router.callback_query(F.data.startswith("t_done_"))
async def task_done(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2])
    await db.execute("UPDATE tasks SET status='مكتملة' WHERE id=?", (tid,))
    await cb.answer("✅ تم اعتماد إكمال المهمة وتحديث المؤشرات")
    await task_view(cb)


@router.callback_query(F.data.startswith("t_add_upd_"))
async def task_add_upd_start(cb: CallbackQuery, state: FSMContext):
    tid = int(cb.data.split("_")[3])
    await state.update_data(task_id=tid)
    await state.set_state(TaskUpdateFSM.text)
    await safe_edit(cb, "💬 <b>الرجاء كتابة نص الإفادة لتوثيق المتابعة:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(TaskUpdateFSM.text))
async def task_add_upd_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO task_updates (task_id, update_text, created_by) VALUES (?,?,?)",
        (data['task_id'], msg.text, msg.from_user.id)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="🔙 معاينة المهمة", callback_data=f"t_view_{data['task_id']}")
    await msg.answer("✅ تم توثيق الإفادة بنجاح وحفظها بالأرشيف.", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("t_upds_"))
async def task_upds_list(cb: CallbackQuery):
    tid = int(cb.data.split("_")[2])
    upds = await db.fetchall(
        '''SELECT u.update_text, u.created_at, us.full_name
           FROM task_updates u LEFT JOIN users us ON u.created_by = us.user_id
           WHERE task_id = ? ORDER BY u.id ASC''',
        (tid,)
    )
    txt = f"📜 <b>سجل متابعة وإفادات المهمة #{tid}:</b>\n\n"
    if not upds:
        txt += "لم يتم تسجيل أي إفادات بعد."
    else:
        for idx, u in enumerate(upds, 1):
            name = clean_text(u['full_name'] or "مستخدم غير معروف")
            txt += f"<b>{idx}. {name}</b> <i>({u['created_at'][:16]})</i>:\n🔹 {clean_text(u['update_text'])}\n\n"
    b = InlineKeyboardBuilder()
    b.button(text="🔙 عودة للمهمة", callback_data=f"t_view_{tid}")
    await safe_edit(cb, txt, reply_markup=b.as_markup())


# ============================================================
# 7. الاجتماعات واللجان
# ============================================================
class MeetFSM(StatesGroup):
    title = State(); date = State(); loc = State()

class MeetItemFSM(StatesGroup):
    type = State(); text = State()


@router.callback_query(F.data == "mt_add")
async def meet_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(MeetFSM.title)
    await safe_edit(cb, "✏️ <b>أدخل موضوع/عنوان الاجتماع:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(MeetFSM.title))
async def meet_title(msg: Message, state: FSMContext):
    if not msg.text or len(msg.text.strip()) < 3:
        return await msg.answer("⚠️ العنوان قصير جداً. حاول مرة أخرى:", reply_markup=cancel_kb())
    await state.update_data(title=msg.text.strip())
    await state.set_state(MeetFSM.date)
    await msg.answer("📅 <b>تاريخ وتوقيت الانعقاد:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(MeetFSM.date))
async def meet_date(msg: Message, state: FSMContext):
    await state.update_data(date=msg.text)
    await state.set_state(MeetFSM.loc)
    await msg.answer("📍 <b>مكان الانعقاد / القاعة:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(MeetFSM.loc))
async def meet_loc(msg: Message, state: FSMContext):
    data = await state.get_data()
    mid = await db.execute(
        "INSERT INTO meetings (title, meeting_date, location, created_by) VALUES (?,?,?,?)",
        (data['title'], data['date'], msg.text, msg.from_user.id)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="➕ إضافة بند أعمال", callback_data=f"mt_add_item_{mid}")
    b.button(text="🔙 القائمة", callback_data="m_meets")
    b.adjust(1)
    await msg.answer(f"✅ تم تأسيس سجل الاجتماع رقم #{mid}.", reply_markup=b.as_markup())


@router.callback_query(F.data == "mt_list")
async def meets_list(cb: CallbackQuery):
    meets = await db.fetchall("SELECT * FROM meetings ORDER BY id DESC LIMIT 20")
    if not meets:
        b = InlineKeyboardBuilder()
        b.button(text="🔙 عودة", callback_data="m_meets")
        await safe_edit(cb, "📭 لا توجد اجتماعات مجدولة بالنظام.", reply_markup=b.as_markup())
        return
    b = InlineKeyboardBuilder()
    for m in meets:
        b.button(text=f"📅 {m['title'][:20]} | {m['meeting_date']}", callback_data=f"mt_view_{m['id']}")
    b.button(text="🔙 عودة للاجتماعات", callback_data="m_meets")
    b.adjust(1)
    await safe_edit(cb, "📋 <b>أجندة الاجتماعات:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mt_view_"))
async def meet_view(cb: CallbackQuery):
    mid = int(cb.data.split("_")[2])
    m = await db.fetchone("SELECT * FROM meetings WHERE id = ?", (mid,))
    if not m:
        return await cb.answer("⚠️ غير موجود")
    items = await db.fetchall("SELECT * FROM meeting_items WHERE meeting_id = ?", (mid,))

    txt = (
        f"📅 <b>عنوان الاجتماع:</b> {clean_text(m['title'])}\n"
        f"📆 <b>التاريخ:</b> {clean_text(m['meeting_date'])}\n"
        f"📍 <b>المقر:</b> {clean_text(m['location'])}\n"
        f"──────────────\n"
        f"📌 <b>جدول الأعمال والمقررات:</b>\n"
    )
    for idx, i in enumerate(items, 1):
        icon = "⚖️" if i['item_type'] == 'مقرر' else "📝"
        txt += f"<b>{idx}.</b> {icon} [{i['item_type']}] {clean_text(i['item_text'])}\n"
    if not items:
        txt += "<i>لم يتم إدراج بنود بعد.</i>"

    b = InlineKeyboardBuilder()
    b.button(text="➕ إدراج بند/مقرر", callback_data=f"mt_add_item_{mid}")
    b.button(text="📎 إرفاق محضر", callback_data=f"att_start_meet_{mid}")
    b.button(text="🗑 حذف الاجتماع", callback_data=f"mt_delete_{mid}")
    b.button(text="🔙 القائمة", callback_data="m_meets")
    b.adjust(2, 1)
    await safe_edit(cb, txt, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mt_add_item_"))
async def meet_add_item_start(cb: CallbackQuery, state: FSMContext):
    mid = int(cb.data.split("_")[3])
    await state.update_data(meet_id=mid)
    b = InlineKeyboardBuilder()
    b.button(text="📝 بند أعمال (للنقاش)", callback_data="mitem_بند")
    b.button(text="⚖️ مقرر (قرار معتمد)", callback_data="mitem_مقرر")
    b.adjust(1)
    await safe_edit(cb, "<b>حدد تصنيف الإدراج المطلوب:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mitem_"))
async def meet_item_text_start(cb: CallbackQuery, state: FSMContext):
    itype = cb.data.split("_", 1)[1]
    await state.update_data(itype=itype)
    await state.set_state(MeetItemFSM.text)
    await safe_edit(cb, f"✏️ <b>أدخل الصياغة النهائية للـ {itype}:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(MeetItemFSM.text))
async def meet_item_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO meeting_items (meeting_id, item_type, item_text) VALUES (?,?,?)",
        (data['meet_id'], data['itype'], msg.text)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="🔙 استعراض الاجتماع", callback_data=f"mt_view_{data['meet_id']}")
    await msg.answer("✅ تم التوثيق بنجاح ضمن محضر الاجتماع.", reply_markup=b.as_markup())


# ============================================================
# 8. إدارة المقترحات والتطوير
# ============================================================
class PropFSM(StatesGroup):
    dept_id = State(); activity = State(); time = State()

class DeptFSM(StatesGroup):
    name = State()

class PropUpdateFSM(StatesGroup):
    text = State()


@router.callback_query(F.data == "d_add")
async def dept_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(DeptFSM.name)
    await safe_edit(cb, "✏️ <b>أدخل المسمى الرسمي للإدارة:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(DeptFSM.name))
async def dept_save(msg: Message, state: FSMContext):
    name = msg.text.strip() if msg.text else ""
    if not name:
        return await msg.answer("⚠️ الاسم لا يمكن أن يكون فارغاً.", reply_markup=cancel_kb())
    await db.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (name,))
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="🔙 عودة للإدارات", callback_data="m_depts")
    await msg.answer("✅ تم تعريف الإدارة بالنظام بنجاح.", reply_markup=b.as_markup())


@router.callback_query(F.data == "p_add")
async def prop_add_step1(cb: CallbackQuery, state: FSMContext):
    depts = await db.fetchall("SELECT * FROM departments ORDER BY name")
    if not depts:
        return await cb.answer("⚠️ يرجى تأسيس الإدارات أولاً لربط المقترحات.", show_alert=True)
    b = InlineKeyboardBuilder()
    for d in depts:
        b.button(text=f"🏢 {d['name']}", callback_data=f"seldept_{d['id']}")
    b.button(text="❌ إلغاء", callback_data="cancel")
    b.adjust(2)
    await safe_edit(cb, "🎯 <b>حدد الإدارة المعنية بالمقترح:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("seldept_"))
async def prop_add_step2(cb: CallbackQuery, state: FSMContext):
    dept_id = int(cb.data.split("_")[1])
    await state.update_data(dept_id=dept_id)
    await state.set_state(PropFSM.activity)
    await safe_edit(cb, "✏️ <b>اكتب وصف النشاط أو المقترح التطويري:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(PropFSM.activity))
async def prop_add_step3(msg: Message, state: FSMContext):
    if not msg.text or len(msg.text.strip()) < 5:
        return await msg.answer("⚠️ الوصف قصير جداً. حاول مرة أخرى:", reply_markup=cancel_kb())
    await state.update_data(activity=msg.text.strip())
    await state.set_state(PropFSM.time)
    await msg.answer("⏱ <b>حدد الإطار الزمني المقدر للتنفيذ:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(PropFSM.time))
async def prop_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO proposals (dept_id, activity, proposed_time, created_by) VALUES (?,?,?,?)",
        (data['dept_id'], data['activity'], msg.text, msg.from_user.id)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="🔙 إدارة المقترحات", callback_data="m_props")
    b.adjust(1)
    await msg.answer("✅ تم إدراج المقترح ضمن بنك الأفكار التطويرية.", reply_markup=b.as_markup())


@router.callback_query(F.data == "p_list_depts")
async def prop_list_depts(cb: CallbackQuery):
    depts = await db.fetchall("SELECT * FROM departments ORDER BY name")
    if not depts:
        b = InlineKeyboardBuilder()
        b.button(text="🔙 عودة", callback_data="m_props")
        await safe_edit(cb, "📭 لا يوجد هيكل إداري مسجل.", reply_markup=b.as_markup())
        return
    b = InlineKeyboardBuilder()
    for d in depts:
        cnt = (await db.fetchone(
            "SELECT COUNT(*) as c FROM proposals WHERE dept_id = ?", (d['id'],)
        ))['c']
        b.button(text=f"{d['name']} (مقترحات: {cnt})", callback_data=f"p_list_{d['id']}")
    b.button(text="🔙 عودة", callback_data="m_props")
    b.adjust(1)
    await safe_edit(cb, "📋 <b>حدد الإدارة لاستعراض مقترحاتها:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("p_list_"))
async def prop_list_by_dept(cb: CallbackQuery):
    dept_id = int(cb.data.split("_")[2])
    props = await db.fetchall(
        "SELECT * FROM proposals WHERE dept_id = ? ORDER BY id DESC", (dept_id,)
    )
    if not props:
        b = InlineKeyboardBuilder()
        b.button(text="🔙 عودة للإدارات", callback_data="p_list_depts")
        await safe_edit(cb, "📭 لا توجد مقترحات مسجلة لهذه الإدارة.", reply_markup=b.as_markup())
        return
    b = InlineKeyboardBuilder()
    for p in props:
        status_icon = "🟡" if p['status'] == 'مقترح' else "🟢" if p['status'] == 'مكتمل' else "🔵"
        b.button(text=f"{status_icon} {p['activity'][:30]}...", callback_data=f"p_view_{p['id']}")
    b.button(text="🔙 تنظيم الإدارات", callback_data="p_list_depts")
    b.adjust(1)
    await safe_edit(cb, "📋 <b>بنك المقترحات للإدارة المحددة:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("p_view_"))
async def prop_view(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    p = await db.fetchone("SELECT * FROM proposals WHERE id = ?", (pid,))
    if not p:
        return await cb.answer("⚠️ السجل مفقود", show_alert=True)
    dept = await db.fetchone("SELECT name FROM departments WHERE id = ?", (p['dept_id'],))
    dept_name = dept['name'] if dept else "غير محدد"
    updates_cnt = (await db.fetchone(
        "SELECT COUNT(*) as c FROM proposal_updates WHERE proposal_id=?", (pid,)
    ))['c']

    txt = (
        f"💡 <b>بطاقة مقترح رقم #{p['id']}</b>\n"
        f"──────────────\n"
        f"🏢 الإدارة المستفيدة: {clean_text(dept_name)}\n"
        f"📝 نص النشاط المقترح:\n{clean_text(p['activity'])}\n"
        f"⏱ التقدير الزمني: {clean_text(p['proposed_time'])}\n"
        f"📌 دورة الاعتماد (الحالة): {p['status']}\n"
        f"💬 إجراءات المتابعة: {updates_cnt}\n\n"
        f"🔽 <b>التوجيه الإداري للمقترح:</b>"
    )

    b = InlineKeyboardBuilder()
    if p['status'] == 'مقترح':
        b.button(text="✅ تحويل لمهام تنفيذية", callback_data=f"p_conv_task_{pid}")
        b.button(text="📅 إدراج بجدول اجتماع", callback_data=f"p_conv_meet_{pid}")
        b.button(text="✔️ اعتماد الإغلاق", callback_data=f"p_done_{pid}")
    else:
        b.button(text="🔄 إعادة التنشيط", callback_data=f"p_reopen_{pid}")
    b.button(text="💬 رفع إفادة", callback_data=f"p_add_upd_{pid}")
    b.button(text="📜 السجل التاريخي", callback_data=f"p_upds_{pid}")
    b.button(text="🗑 حذف المقترح", callback_data=f"p_delete_{pid}")
    b.button(text="🔙 القائمة", callback_data="p_list_depts")
    b.adjust(1, 2, 1)
    await safe_edit(cb, txt, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("p_conv_task_"))
async def prop_convert_task(cb: CallbackQuery):
    pid = int(cb.data.split("_")[3])
    p = await db.fetchone("SELECT * FROM proposals WHERE id = ?", (pid,))
    if not p:
        return await cb.answer("⚠️ خطأ في الاستعلام")
    task_id = await db.execute(
        "INSERT INTO tasks (title, description, due_date, created_by) VALUES (?,?,?,?)",
        (
            f"تنفيذ مقترح: {p['activity'][:20]}",
            f"مُحال من مقترح #{pid}:\n{p['activity']}",
            p['proposed_time'], cb.from_user.id
        )
    )
    await db.execute(
        "UPDATE proposals SET status = 'قيد التنفيذ', converted_to_task = ? WHERE id = ?",
        (task_id, pid)
    )
    await cb.answer("✅ تمت إحالة المقترح إلى مسار المهام التنفيذية")
    await prop_view(cb)


@router.callback_query(F.data.startswith("p_conv_meet_"))
async def prop_convert_meeting(cb: CallbackQuery):
    pid = int(cb.data.split("_")[3])
    p = await db.fetchone("SELECT * FROM proposals WHERE id = ?", (pid,))
    if not p:
        return await cb.answer("⚠️ خطأ")
    meeting_id = await db.execute(
        "INSERT INTO meetings (title, meeting_date, location, created_by) VALUES (?,?,?,?)",
        (f"جلسة مراجعة مقترح #{pid}", p['proposed_time'], "يحدد لاحقاً", cb.from_user.id)
    )
    await db.execute(
        "INSERT INTO meeting_items (meeting_id, item_type, item_text) VALUES (?,?,?)",
        (meeting_id, "بند", f"استعراض ودراسة الجدوى للمقترح:\n{p['activity']}")
    )
    await db.execute(
        "UPDATE proposals SET status = 'قيد التنفيذ', converted_to_meeting = ? WHERE id = ?",
        (meeting_id, pid)
    )
    await cb.answer("✅ تم تشكيل أجندة اجتماع خاصة بالمقترح")
    await prop_view(cb)


@router.callback_query(F.data.startswith("p_done_"))
async def prop_done(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    await db.execute("UPDATE proposals SET status = 'مكتمل' WHERE id = ?", (pid,))
    await cb.answer("✅ تم تحديث دورة الاعتماد للإنهاء")
    await prop_view(cb)


@router.callback_query(F.data.startswith("p_reopen_"))
async def prop_reopen(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    await db.execute("UPDATE proposals SET status = 'مقترح' WHERE id = ?", (pid,))
    await cb.answer("🔄 تم إعادة تنشيط السجل")
    await prop_view(cb)


@router.callback_query(F.data.startswith("p_add_upd_"))
async def prop_add_upd_start(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split("_")[3])
    await state.update_data(prop_id=pid)
    await state.set_state(PropUpdateFSM.text)
    await safe_edit(cb, "💬 <b>أدخل إفادة الدعم والمتابعة للمقترح:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(PropUpdateFSM.text))
async def prop_add_upd_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "INSERT INTO proposal_updates (proposal_id, update_text, created_by) VALUES (?,?,?)",
        (data['prop_id'], msg.text, msg.from_user.id)
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text="🔙 عودة للبطاقة", callback_data=f"p_view_{data['prop_id']}")
    await msg.answer("✅ تم قيد الإفادة بالسجل التاريخي.", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("p_upds_"))
async def prop_upds_list(cb: CallbackQuery):
    pid = int(cb.data.split("_")[2])
    upds = await db.fetchall(
        '''SELECT u.update_text, u.created_at, us.full_name
           FROM proposal_updates u LEFT JOIN users us ON u.created_by = us.user_id
           WHERE proposal_id = ? ORDER BY u.id ASC''',
        (pid,)
    )
    txt = f"📜 <b>السجل التوثيقي للمقترح #{pid}:</b>\n\n"
    if not upds:
        txt += "السجل فارغ من التدخلات."
    else:
        for idx, u in enumerate(upds, 1):
            name = clean_text(u['full_name'] or "مستخدم النظام")
            txt += f"<b>{idx}. {name}</b> <i>({u['created_at'][:16]})</i>:\n🔹 {clean_text(u['update_text'])}\n\n"
    b = InlineKeyboardBuilder()
    b.button(text="🔙 رجوع", callback_data=f"p_view_{pid}")
    await safe_edit(cb, txt, reply_markup=b.as_markup())


# ============================================================
# 9. إدارة الأرشيف المركزي
# ============================================================
class AttachFSM(StatesGroup):
    file = State()


@router.callback_query(F.data.startswith("att_start_"))
async def attach_start(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    ref_type = parts[2]
    ref_id = int(parts[3])
    await state.update_data(ref_type=ref_type, ref_id=ref_id)
    await state.set_state(AttachFSM.file)
    await safe_edit(cb, "📎 <b>الرجاء توجيه أو رفع المستند (وثيقة PDF أو صور):</b>", reply_markup=cancel_kb())


@router.message(StateFilter(AttachFSM.file), F.content_type.in_({'document', 'photo'}))
async def attach_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    if msg.document:
        fid = msg.document.file_id
        fname = msg.document.file_name or "document"
        ftype = 'document'
    else:
        fid = msg.photo[-1].file_id
        fname = f"IMG_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        ftype = 'photo'
    await db.execute(
        "INSERT INTO attachments (file_id, file_name, file_type, ref_type, ref_id) VALUES (?,?,?,?,?)",
        (fid, fname, ftype, data['ref_type'], data['ref_id'])
    )
    await state.clear()
    b = InlineKeyboardBuilder()
    if data['ref_type'] == 'task':
        b.button(text="🔙 للمهمة المعنية", callback_data=f"t_view_{data['ref_id']}")
    else:
        b.button(text="🔙 لمحضر الاجتماع", callback_data=f"mt_view_{data['ref_id']}")
    await msg.answer("✅ تمت أرشفة المستند وربطه آلياً بالسجل المطلوب.", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("dl_"))
async def file_download(cb: CallbackQuery):
    att_id = int(cb.data.split("_")[1])
    att = await db.fetchone("SELECT * FROM attachments WHERE id = ?", (att_id,))
    if not att:
        return await cb.answer("⚠️ المستند مفقود من قاعدة البيانات")
    # ✅ استخدام file_type من قاعدة البيانات بدل try/except
    try:
        if att['file_type'] == 'photo':
            await cb.message.answer_photo(att['file_id'], caption=f"🖼 صورة مرفقة: {att['file_name']}")
        else:
            await cb.message.answer_document(att['file_id'], caption=f"📥 مستخرج: {att['file_name']}")
    except Exception as e:
        logger.error(f"Download error: {e}")
        await cb.answer("⚠️ تعذر استخراج الملف", show_alert=True)
    else:
        await cb.answer("تم المعالجة والاستخراج")


# ============================================================
# 10. توليد التقارير والمؤشرات (Pandas)
# ============================================================
@router.callback_query(F.data.startswith("exp_"))
async def export_excel(cb: CallbackQuery):
    await cb.answer("⏳ جاري سحب ومعالجة البيانات...", show_alert=False)
    exp_type = cb.data.split("_", 1)[1]
    df = pd.DataFrame()
    fname = "System_Report"
    col_map = {}

    if exp_type == "tasks":
        data = await db.fetchall(
            "SELECT id, title, description, priority, status, due_date, created_at FROM tasks"
        )
        df = pd.DataFrame([dict(d) for d in data])
        fname = "سجل_المهام_التنفيذية"
        col_map = {
            "id": "الرقم المرجعي", "title": "عنوان المهمة", "description": "التفاصيل",
            "priority": "مستوى الأولوية", "status": "الحالة الراهنة",
            "due_date": "موعد الاستحقاق", "created_at": "تاريخ التأسيس"
        }
    elif exp_type == "props":
        data = await db.fetchall(
            '''SELECT p.id, d.name as dept, p.activity, p.proposed_time, p.status
               FROM proposals p LEFT JOIN departments d ON p.dept_id = d.id'''
        )
        df = pd.DataFrame([dict(d) for d in data])
        fname = "حصاد_المقترحات_التطويرية"
        col_map = {
            "id": "الرقم", "dept": "الإدارة المستفيدة", "activity": "التدخل المقترح",
            "proposed_time": "الإطار الزمني", "status": "دورة الاعتماد"
        }
    elif exp_type == "updates":
        data = await db.fetchall('''
            SELECT t.id as task_id, t.title, u.update_text, u.created_at,
                   us.full_name as updated_by
            FROM task_updates u
            LEFT JOIN tasks t ON u.task_id = t.id
            LEFT JOIN users us ON u.created_by = us.user_id
            ORDER BY u.created_at DESC
        ''')
        df = pd.DataFrame([dict(d) for d in data])
        fname = "مؤشرات_المتابعة_والإفادات"
        col_map = {
            "task_id": "رقم الربط (مهمة)", "title": "عنوان المهمة",
            "update_text": "نص الإفادة", "created_at": "تاريخ الحركة",
            "updated_by": "القائم بالتحديث"
        }

    if df.empty:
        return await cb.message.answer("⚠️ لم يتم رصد بيانات في هذا المسار لتوليد تقرير.")

    df.rename(columns=col_map, inplace=True)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='المستخرج الآلي')
    output.seek(0)

    doc = BufferedInputFile(
        output.read(),
        filename=f"{fname}_{datetime.now().strftime('%Y_%m_%d')}.xlsx"
    )
    await cb.message.answer_document(
        doc,
        caption="📊 <b>تم إصدار التقرير بنجاح.</b>\nيمكنك استخدام البيانات في تحليلات PowerBI أو Dashboard الإدارة."
    )


@router.callback_query(F.data == "dash")
async def dashboard(cb: CallbackQuery):
    t_cnt = (await db.fetchone("SELECT COUNT(*) as c FROM tasks"))['c']
    t_done = (await db.fetchone("SELECT COUNT(*) as c FROM tasks WHERE status='مكتملة'"))['c']
    p_cnt = (await db.fetchone("SELECT COUNT(*) as c FROM proposals"))['c']
    m_cnt = (await db.fetchone("SELECT COUNT(*) as c FROM meetings"))['c']
    a_cnt = (await db.fetchone("SELECT COUNT(*) as c FROM attachments"))['c']

    comp_rate = round((t_done / t_cnt * 100), 1) if t_cnt > 0 else 0

    txt = (
        f"📈 <b>لوحة المؤشرات التشغيلية للنظام:</b>\n\n"
        f"✅ <b>المهام الكلية:</b> {t_cnt} (المنجز: {t_done})\n"
        f"🎯 <b>معدل الإنجاز العام:</b> {comp_rate}%\n"
        f"──────────────\n"
        f"💡 <b>بنك المقترحات:</b> {p_cnt} نشاط مسجل\n"
        f"📅 <b>لجان واجتماعات:</b> {m_cnt} محضر\n"
        f"📂 <b>وثائق الأرشيف:</b> {a_cnt} مستند مرفق"
    )

    b = InlineKeyboardBuilder()
    b.button(text="🔙 عودة للتقارير", callback_data="m_reps")
    await safe_edit(cb, txt, reply_markup=b.as_markup())


# ============================================================
# 11. الصلاحيات وإدارة المستخدمين
# ============================================================
class UserAddFSM(StatesGroup):
    target_id = State(); perm_set = State()


@router.callback_query(F.data == "u_add")
async def user_add_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(UserAddFSM.target_id)
    await safe_edit(cb, "✏️ <b>أدخل المعرف الرقمي (Telegram ID) للموظف:</b>", reply_markup=cancel_kb())


@router.message(StateFilter(UserAddFSM.target_id))
async def user_add_target(msg: Message, state: FSMContext):
    try:
        user_id = int(msg.text.strip())
    except ValueError:
        return await msg.answer("⚠️ المعرف يجب أن يتكون من أرقام فقط.", reply_markup=cancel_kb())

    existing = await db.fetchone("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    if existing:
        await state.clear()
        kb = await main_menu_kb(msg.from_user.id)
        return await msg.answer("⚠️ حساب الموظف مسجل ومفعل مسبقاً بالنظام.", reply_markup=kb)

    await state.update_data(target_id=user_id)
    await state.set_state(UserAddFSM.perm_set)
    await show_permission_toggle(msg, user_id, state)


async def show_permission_toggle(msg_or_cb, user_id: int, state: FSMContext, edit: bool = False):
    b = InlineKeyboardBuilder()
    perms = await get_user_permissions(user_id)

    for p in PERMISSIONS_LIST:
        checked = "✅" if p in perms else "⬜"
        b.button(text=f"{checked} {PERMISSION_NAMES[p]}", callback_data=f"tog_{p}")

    b.button(text="💾 اعتماد التوجيه وحفظ الصلاحيات", callback_data="u_save")
    b.button(text="❌ إنهاء", callback_data="cancel")
    b.adjust(2, 2, 2, 1)

    txt = f"🔧 <b>لوحة التحكم في الصلاحيات</b> (رقم المستخدم: <code>{user_id}</code>):"
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(txt, reply_markup=b.as_markup())
    else:
        if edit:
            await safe_edit(msg_or_cb, txt, reply_markup=b.as_markup())
        else:
            await msg_or_cb.message.answer(txt, reply_markup=b.as_markup())


@router.callback_query(StateFilter(UserAddFSM.perm_set), F.data.startswith("tog_"))
async def toggle_perm(cb: CallbackQuery, state: FSMContext):
    perm = cb.data.split("_", 1)[1]
    data = await state.get_data()
    user_id = data['target_id']

    current = await has_permission(user_id, perm)
    await set_user_permission(user_id, perm, not current)
    await show_permission_toggle(cb, user_id, state, edit=True)


@router.callback_query(StateFilter(UserAddFSM.perm_set), F.data == "u_save")
async def save_new_user(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data['target_id']

    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, full_name, username, role) VALUES (?,?,?,?)",
        (user_id, f"موظف_{user_id}", f"u{user_id}", 'مستخدم')
    )
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text="🔙 عودة للهيكل التنظيمي", callback_data="m_users")
    await safe_edit(
        cb,
        f"✅ تم تفعيل حساب الموظف برقم (<code>{user_id}</code>) بنجاح وإدراجه بالهيكل.",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("u_view_"))
async def user_view(cb: CallbackQuery):
    uid = int(cb.data.split("_")[2])
    u = await db.fetchone("SELECT * FROM users WHERE user_id = ?", (uid,))
    if not u:
        return await cb.answer("⚠️ السجل الوظيفي مفقود")

    perms = await get_user_permissions(uid)
    perms_txt = "\n".join([f"▪️ {PERMISSION_NAMES.get(p, p)}" for p in perms]) or "بدون صلاحيات إدارية"

    txt = (
        f"👤 <b>بطاقة الموظف:</b> {clean_text(u['full_name'])} (@{clean_text(u['username'])})\n"
        f"المستوى: {u['role']}\n"
        f"──────────────\n"
        f"<b>محددات الوصول والنطاق:</b>\n{perms_txt}"
    )

    b = InlineKeyboardBuilder()
    if uid != cb.from_user.id:
        b.button(text="🔧 تعديل النطاق (الصلاحيات)", callback_data=f"u_edit_{uid}")
        if u['role'] == 'مستخدم':
            b.button(text="👑 ترقية لمدير نظام", callback_data=f"u_mk_admin_{uid}")
        else:
            b.button(text="👤 سحب الصلاحية العليا", callback_data=f"u_mk_user_{uid}")
        b.button(text="🗑 طي القيد (حذف)", callback_data=f"u_del_{uid}")
    b.button(text="🔙 القائمة", callback_data="m_users")
    b.adjust(1)
    await safe_edit(cb, txt, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("u_edit_"))
async def user_edit_perms(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.split("_")[2])
    await state.set_state(UserAddFSM.perm_set)
    await state.update_data(target_id=uid)
    await show_permission_toggle(cb, uid, state, edit=True)


@router.callback_query(F.data.startswith("u_mk_admin_"))
async def user_mk_admin(cb: CallbackQuery):
    uid = int(cb.data.split("_")[3])
    await db.execute("UPDATE users SET role = 'مدير نظام' WHERE user_id = ?", (uid,))
    for p in PERMISSIONS_LIST:
        await set_user_permission(uid, p, True)
    await cb.answer("✅ تمت الترقية التشغيلية بنجاح")
    await user_view(cb)


@router.callback_query(F.data.startswith("u_mk_user_"))
async def user_mk_user(cb: CallbackQuery):
    uid = int(cb.data.split("_")[3])
    await db.execute("UPDATE users SET role = 'مستخدم' WHERE user_id = ?", (uid,))
    await cb.answer("✅ تم إعادة تعيين المستوى الإداري للموظف")
    await user_view(cb)


@router.callback_query(F.data.startswith("u_del_") & ~F.data.startswith("u_del_exec_"))
async def user_del_confirm(cb: CallbackQuery):
    uid = int(cb.data.split("_")[2])
    b = InlineKeyboardBuilder()
    b.button(text="✅ تأكيد الإجراء", callback_data=f"u_del_exec_{uid}")
    b.button(text="❌ تراجع", callback_data=f"u_view_{uid}")
    b.adjust(2)
    await safe_edit(
        cb,
        "⚠️ هل أنت متأكد من قرار طي قيد هذا المستخدم وإلغاء ارتباطه بالنظام؟",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("u_del_exec_"))
async def user_del_exec(cb: CallbackQuery):
    uid = int(cb.data.split("_")[3])
    await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    await db.execute("DELETE FROM user_permissions WHERE user_id = ?", (uid,))
    await cb.answer("✅ تم تطبيق طي القيد وإلغاء الوصول بنجاح")
    await menu_nav(cb)


# ============================================================
# 12. تشغيل بيئة العمل (Webhook + Polling)
# ============================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # بدء التشغيل
    await db.init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="تحديث واستدعاء القائمة المركزية"),
        BotCommand(command="cancel", description="إلغاء الأمر الراهن وإفراغ الذاكرة")
    ])

    if WEBHOOK_URL:
        webhook_path = f"/webhook/{BOT_TOKEN}"
        # ✅ ضمان عدم تكرار /
        webhook_endpoint = f"{WEBHOOK_URL}{webhook_path}"
        await bot.set_webhook(
            webhook_endpoint,
            allowed_updates=dp.resolve_used_update_types()
        )
        logger.info(f"✅ Webhook set to {webhook_endpoint}")
    else:
        # وضع Polling المحلي
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🚀 Polling mode active...")
        import threading
        def run_polling():
            asyncio.run(dp.start_polling(bot))
        t = threading.Thread(target=run_polling, daemon=True)
        t.start()

    yield

    # إيقاف التشغيل
    if WEBHOOK_URL:
        await bot.delete_webhook()
    await bot.session.close()
    await db.close()


app = FastAPI(lifespan=lifespan)


# ✅ Health check endpoint لمراقبة الخادم
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post(f"/webhook/{BOT_TOKEN}")
async def bot_webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update.model_validate(update_data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception:
        logger.exception("Webhook update processing failed")
        return {"status": "error"}


# تشغيل محلي (Polling)
async def main():
    await db.init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="تحديث واستدعاء القائمة المركزية"),
        BotCommand(command="cancel", description="إلغاء الأمر الراهن وإفراغ الذاكرة")
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 System Core is Active and Listening (Polling Mode)...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        if WEBHOOK_URL:
            port = int(os.getenv("PORT", 8000))
            uvicorn.run(app, host="0.0.0.0", port=port)
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ System Terminated Safely.")