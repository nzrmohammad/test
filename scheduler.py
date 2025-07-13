import logging
import threading
import time
from datetime import datetime
import schedule
import pytz
from telebot import apihelper, TeleBot
from config import (DAILY_REPORT_TIME, TEHRAN_TZ, ADMIN_IDS,BIRTHDAY_GIFT_GB, BIRTHDAY_GIFT_DAYS, NOTIFY_ADMIN_ON_USAGE,
                     WARNING_USAGE_THRESHOLD,WARNING_DAYS_BEFORE_EXPIRY,
                     USAGE_WARNING_CHECK_HOURS, ONLINE_REPORT_UPDATE_HOURS)
from database import db
from api_handler import api_handler
from utils import escape_markdown
from menu import menu
from formatters import fmt_admin_report, fmt_user_report, fmt_online_users_list

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self, bot: TeleBot) -> None:
        self.bot = bot  # ذخیره نمونه bot
        self.running = False
        self.tz = pytz.timezone(TEHRAN_TZ) if isinstance(TEHRAN_TZ, str) else TEHRAN_TZ
        self.tz_str = str(self.tz)

    def _hourly_snapshots(self) -> None:
        """Takes a usage snapshot for all active UUIDs every hour."""
        logger.info("Scheduler: Running hourly usage snapshot job.")
        
        all_users_info = api_handler.get_all_users()
        if not all_users_info:
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info}

        all_uuids_from_db = db.all_active_uuids()
        if not all_uuids_from_db:
            return

        for u_row in all_uuids_from_db:
            try:
                uuid_str = u_row['uuid']
                if uuid_str in user_info_map:
                    info = user_info_map[uuid_str]
                    if info.get('current_usage_GB') is not None:
                        db.add_usage_snapshot(u_row['id'], info['current_usage_GB'])
                
            except Exception as e:
                logger.error(f"Scheduler: Failed to process snapshot for uuid_id {u_row['id']}: {e}")

    def _check_usage_warnings(self) -> None:
        """
        🔥 [NEW & FIXED]
        Checks for users exceeding the usage threshold and notifies admins,
        only if the feature is enabled in the config.
        """
        # ✅ [FIXED] ابتدا چک می‌کند که آیا قابلیت هشدار فعال است یا خیر
        if not NOTIFY_ADMIN_ON_USAGE:
            return
            
        logger.info("Scheduler: Running usage warning check.")
        all_users = api_handler.get_all_users()
        if not all_users: return
        
        # ✅ [FIXED] استفاده از متغیر صحیح از فایل کانفیگ
        threshold = WARNING_USAGE_THRESHOLD
        
        users_to_warn = [
            u for u in all_users 
            if u.get('is_active') and threshold <= u.get('usage_percentage', 0) < 100
        ]

        if not users_to_warn: return

        message_lines = [f"⚠️ *هشدار مصرف بالا \\(بیش از {threshold}%\\)*\n"]
        for user in users_to_warn:
            name = escape_markdown(user['name'])
            percentage = user['usage_percentage']
            message_lines.append(f"`•` *{name}* به `{percentage:.1f}%` از حجم خود رسیده است\\.")
        
        full_message = "\n".join(message_lines)
        
        for admin_id in ADMIN_IDS:
            try:
                self.bot.send_message(admin_id, full_message, parse_mode="MarkdownV2")
                time.sleep(0.2)
            except Exception as e:
                logger.error(f"Scheduler: Failed to send usage warning to admin {admin_id}: {e}")

    def _check_expiry_warnings(self) -> None:
        """Sends expiry warnings to users whose accounts are expiring soon."""
        logger.info("Scheduler: Running daily expiry warning job.")
        
        all_users_info = api_handler.get_all_users()
        if not all_users_info: return
            
        expiring_users_map = {
            user['uuid']: user for user in all_users_info
            if user.get('expire') is not None and 0 <= user['expire'] <= WARNING_DAYS_BEFORE_EXPIRY
        }

        if not expiring_users_map: return

        all_bot_uuids = db.all_active_uuids()
        
        # برای جلوگیری از ارسال پیام تکراری به یک کاربر
        notified_users = set()

        for u_row in all_bot_uuids:
            user_id = u_row['user_id']
            uuid_str = u_row['uuid']

            if user_id in notified_users: continue

            user_settings = db.get_user_settings(user_id)
            if not user_settings.get('expiry_warnings', True): continue

            if uuid_str in expiring_users_map:
                info = expiring_users_map[uuid_str]
                name = escape_markdown(info['name'])
                days = info['expire']
                
                message = (
                    f"⏰ *هشدار انقضای اکانت*\n\n"
                    f"کاربر گرامی، اکانت «*{name}*» شما تنها `{days}` روز دیگر اعتبار دارد\\.\n\n"
                    f"برای جلوگیری از قطع شدن سرویس، لطفاً نسبت به تمدید آن اقدام فرمایید\\."
                )
                try:
                    self.bot.send_message(user_id, message, parse_mode="MarkdownV2")
                    notified_users.add(user_id) # کاربر به لیست اطلاع‌داده‌شده‌ها اضافه می‌شود
                    time.sleep(0.3)
                except Exception as e:
                    logger.error(f"Scheduler: Failed to send expiry warning to user {user_id}: {e}")

    def _nightly_report(self) -> None:
        now = datetime.now(self.tz)
        now_str = now.strftime("%Y/%m/%d - %H:%M")
        logger.info(f"Scheduler: Running nightly reports at {now_str}")

        all_users_info_from_api = api_handler.get_all_users()
        if not all_users_info_from_api:
            logger.warning("Scheduler: Could not fetch user info from API for nightly report.")
            return
            
        user_info_map = {user['uuid']: user for user in all_users_info_from_api}
        all_bot_users = db.get_all_user_ids()
        separator = '\n' + '\\-' * 25 + '\n'

        for user_id in all_bot_users:
            user_settings = db.get_user_settings(user_id)
            if not user_settings.get('daily_reports', True):
                continue
            report_text, header = "", ""
            user_uuids_from_db = db.uuids(user_id)
            user_infos_for_report = []
            if user_uuids_from_db:
                for u_row in user_uuids_from_db:
                    if u_row['uuid'] in user_info_map:
                        user_data = user_info_map[u_row['uuid']]
                        user_data['db_id'] = u_row['id'] 
                        user_infos_for_report.append(user_data)

            try:
                if user_id in ADMIN_IDS:
                    header = f"👑 *گزارش جامع ادمین* \\- {escape_markdown(now_str)}{separator}"
                    report_text = fmt_admin_report(all_users_info_from_api, db)
                elif user_infos_for_report:
                    header = f"🌙 *گزارش روزانه شما* \\- {escape_markdown(now_str)}{separator}"
                    report_text = fmt_user_report(user_infos_for_report)

                if report_text:
                    self.bot.send_message(user_id, header + report_text, parse_mode="MarkdownV2")
                    time.sleep(0.5)
                
                if user_infos_for_report:
                    for info in user_infos_for_report:
                        db.delete_user_snapshots(info['db_id'])
                    logger.info(f"Scheduler: Cleaned up daily snapshots for user {user_id}.")
                    
            except Exception as e:
                logger.error(f"Scheduler: Failed to send nightly report or cleanup for user {user_id}: {e}")
                continue

    def _update_online_reports(self) -> None:
        """Scheduled job to update the online users report message every 3 hours."""
        logger.info("Scheduler: Running 3-hourly online user report update.")
        
        messages_to_update = db.get_scheduled_messages('online_users_report')
        
        for msg_info in messages_to_update:
            try:
                chat_id = msg_info['chat_id']
                message_id = msg_info['message_id']
                
                online_list = api_handler.online_users()
                for user in online_list:
                    user['daily_usage_GB'] = db.get_usage_since_midnight_by_uuid(user['uuid'])
                
                text = fmt_online_users_list(online_list, 0)
                kb = menu.create_pagination_menu("admin_online", 0, len(online_list))
                
                self.bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="MarkdownV2")
                time.sleep(0.5)
            except apihelper.ApiTelegramException as e:
                if 'message to edit not found' in str(e) or 'message is not modified' in str(e):
                    db.delete_scheduled_message(msg_info['id'])
                else:
                    logger.error(f"Scheduler: Failed to update online report for chat {chat_id}: {e}")
            except Exception as e:
                logger.error(f"Scheduler: Generic error updating online report for chat {chat_id}: {e}")

    def _birthday_gifts_job(self) -> None:
        """Checks for users' birthdays and sends them a gift."""
        logger.info("Scheduler: Running daily birthday gift job.")
        today_birthday_users = db.get_todays_birthdays()
        
        if not today_birthday_users:
            logger.info("Scheduler: No birthdays today.")
            return

        for user_id in today_birthday_users:
            user_uuids = db.uuids(user_id)
            if not user_uuids:
                continue
            
            gift_applied = False
            for row in user_uuids:
                uuid = row['uuid']
                # ✅ [FIXED] فراخوانی مستقیم api_handler به جای self.api_handler
                if api_handler.modify_user(uuid, add_usage_gb=BIRTHDAY_GIFT_GB, add_days=BIRTHDAY_GIFT_DAYS):
                    gift_applied = True
            
            if gift_applied:
                try:
                    gift_message = (
                        f"🎉 *تولدت مبارک\\!* 🎉\n\n"
                        f"امیدواریم سالی پر از شادی و موفقیت پیش رو داشته باشی\\.\n"
                        f"ما به همین مناسبت، هدیه‌ای برای شما فعال کردیم:\n\n"
                        f"🎁 `{BIRTHDAY_GIFT_GB} GB` حجم و `{BIRTHDAY_GIFT_DAYS}` روز به تمام اکانت‌های شما **به صورت خودکار اضافه شد\\!**\n\n"
                        f"می‌توانی با مراجعه به بخش مدیریت اکانت، جزئیات جدید را مشاهده کنی\\."
                    )
                    self.bot.send_message(user_id, gift_message, parse_mode="MarkdownV2")
                    logger.info(f"Scheduler: Sent birthday gift to user {user_id}.")
                except Exception as e:
                    logger.error(f"Scheduler: Failed to send birthday message to user {user_id}: {e}")

    def _run_monthly_vacuum(self) -> None:
        """A scheduled job to run the VACUUM command on the database."""
        today = datetime.now(self.tz)
        if today.day == 1:
            logger.info("Scheduler: It's the first of the month, running database VACUUM job.")
            try:
                db.vacuum_db()
                logger.info("Scheduler: Database VACUUM completed successfully.")
            except Exception as e:
                logger.error(f"Scheduler: Database VACUUM failed: {e}")

    def start(self) -> None:
        if self.running: return
        
        report_time_str = DAILY_REPORT_TIME.strftime("%H:%M")
        schedule.every().hour.at(":01").do(self._hourly_snapshots)
        schedule.every(USAGE_WARNING_CHECK_HOURS).hours.do(self._check_usage_warnings)
        schedule.every().day.at("23:55", self.tz_str).do(self._check_expiry_warnings)
        schedule.every().day.at("11:59", self.tz_str).do(self._nightly_report)
        schedule.every().day.at(report_time_str, self.tz_str).do(self._nightly_report)
        schedule.every(ONLINE_REPORT_UPDATE_HOURS).hours.do(self._update_online_reports)
        schedule.every().day.at("00:05", self.tz_str).do(self._birthday_gifts_job)
        schedule.every().day.at("04:00").do(self._run_monthly_vacuum)
        
        self.running = True
        threading.Thread(target=self._runner, daemon=True).start()
        logger.info(f"Scheduler started. Nightly report at {report_time_str} ({self.tz_str}). Online user reports will update every 3 hours && Birthday gift job scheduled for 00:05 ({self.tz_str}")

    def shutdown(self) -> None:
        logger.info("Scheduler: Shutting down...")
        schedule.clear()
        self.running = False

    def _runner(self) -> None:
        while self.running:
            try:
                schedule.run_pending()
            except Exception as exc:
                logger.error(f"Scheduler loop error: {exc}")
            time.sleep(60)