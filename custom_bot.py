# main.py
# ─────────────────────── اجرای ربات هیدیفای ───────────────────────

import logging
import sys
import signal
import time
from datetime import datetime
from telebot import TeleBot

from config import LOG_LEVEL, LOG_FORMAT, ADMIN_IDS, BOT_TOKEN
from database import db
from api_handler import api_handler

# --- تغییر: وارد کردن چرخه‌ای حذف شد و فقط کلاس وارد می‌شود ---
from scheduler import SchedulerManager

# Import the new handler registration functions
from user_handlers import register_user_handlers
from admin_handlers import register_admin_handlers
from callback_router import register_callback_router

# ==================== بخش تنظیمات لاگ ====================

# فرمت جدید لاگ که شامل یوزر آیدی هم می‌شود
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — [User:%(user_id)s] — %(message)s"
# یک فرمت ساده‌تر برای لاگ‌هایی که به کاربر خاصی مربوط نیستند
DEFAULT_LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"

# گرفتن لاگر اصلی
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

# پاک کردن هندلرهای قبلی برای جلوگیری از لاگ تکراری
if root_logger.hasHandlers():
    root_logger.handlers.clear()

# ۱. ساخت هندلر برای فایل bot.log (تمام لاگ‌ها از سطح INFO به بالا)
info_handler = logging.FileHandler("bot.log", encoding="utf-8")
info_handler.setLevel(logging.INFO)
info_formatter = logging.Formatter(DEFAULT_LOG_FORMAT) # فرمت پیش‌فرض
info_handler.setFormatter(info_formatter)

# ۲. ساخت هندلر برای فایل error.log (فقط لاگ‌های از سطح ERROR به بالا)
error_handler = logging.FileHandler("error.log", encoding="utf-8")
error_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter(LOG_FORMAT) # فرمت کامل با یوزر آیدی
error_handler.setFormatter(error_formatter)

# ۳. ساخت هندلر برای نمایش در کنسول (stdout)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(info_formatter)

# افزودن هندلرها به لاگر اصلی
root_logger.addHandler(info_handler)
root_logger.addHandler(error_handler)
root_logger.addHandler(stream_handler)


# لاگر اصلی این ماژول
logger = logging.getLogger(__name__)

# Create the single bot instance
bot = TeleBot(BOT_TOKEN, parse_mode="MarkdownV2")

# --- تغییر: نمونه scheduler اینجا با پاس دادن bot ساخته می‌شود ---
scheduler = SchedulerManager(bot)

def _notify_admins_start() -> None:
    """پس از ریاستارت ربات، یک پیام وضعیت برای ادمین‌ها بفرستد."""
    text = "🚀 ربات با موفقیت فعال شد"
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, parse_mode=None)
        except Exception:
            continue

class HiddifyBot:
    """مدیر چرخهٔ حیات ربات"""

    def __init__(self) -> None:
        self.bot = bot
        self.running = False
        self.started_at: datetime | None = None
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    def _on_signal(self, signum, _frame):
        logger.info("Received signal %s → shutting down …", signum)
        self.shutdown()
        sys.exit(0)

    def start(self) -> None:
        if self.running:
            logger.warning("Bot already running")
            return
        try:
            logger.info("Registering handlers...")
            register_user_handlers(self.bot)
            register_admin_handlers(self.bot)
            register_callback_router(self.bot)
            logger.info("✅ Handlers registered")

            logger.info("Testing API connectivity …")
            if api_handler.test_connection():
                logger.info("✅ API reachable")
            else:
                logger.warning("⚠️ API unreachable")

            db.user(0)  # Test DB connection
            logger.info("✅ SQLite ready (users table reachable)")

            scheduler.start()
            logger.info("✅ Scheduler thread started")

            _notify_admins_start()

            self.running = True
            self.started_at = datetime.now()

            logger.info("🚀 Polling …")
            while self.running:
                try:
                    self.bot.infinity_polling(timeout=20, skip_pending=True)
                except Exception as e:
                    logger.error(f"FATAL ERROR: Bot polling failed: {e}", exc_info=True)
                    logger.info("Restarting polling in 15 seconds...")
                    time.sleep(15)

        except Exception as exc:
            logger.exception("Start-up failed: %s", exc)
            self.shutdown()
            raise

    def shutdown(self) -> None:
        if not self.running: return
        logger.info("Graceful shutdown …")
        self.running = False
        try:
            scheduler.shutdown()
            logger.info("Scheduler stopped")
            self.bot.stop_polling()
            logger.info("Telegram polling stopped")
            if self.started_at:
                logger.info("Uptime: %s", datetime.now() - self.started_at)
        finally:
            self.running = False
            logger.info("Shutdown complete")

if __name__ == "__main__":
    bot_instance = HiddifyBot()
    try:
        bot_instance.start()
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}", exc_info=True)