import logging
import time
from telebot import types, telebot
from database import db
from api_handler import api_handler
from menu import menu
from formatters import (
    fmt_one, fmt_users_list, fmt_panel_info, fmt_top_consumers,
    fmt_online_users_list, fmt_bot_users_list, fmt_birthdays_list
)
from utils import escape_markdown
from datetime import datetime
from config import ADMIN_IDS, DATABASE_PATH, TELEGRAM_FILE_SIZE_LIMIT_BYTES
import os
from telebot.apihelper import ApiTelegramException


logger = logging.getLogger(__name__)
admin_conversations = {}
bot = telebot.TeleBot("YOUR_BOT_TOKEN")

def is_admin(message: types.Message) -> bool:
    """A filter function to check if the message sender is an admin."""
    return message.from_user.id in ADMIN_IDS

def _safe_edit(chat_id: int, msg_id: int, text: str, **kwargs):
    """A helper function to safely edit messages."""
    try:
        bot.edit_message_text(text, chat_id, msg_id, **kwargs)
    except Exception as e:
        if 'message is not modified' not in str(e):
            logger.error(f"Admin safe edit error: {e}")

def register_admin_handlers(b: telebot.TeleBot):
    """Registers all admin-related handlers and callbacks."""
    global bot
    bot = b

def _clear_and_start(uid, start_function, msg_id=None):
    """Clears any pending step handlers before starting a new conversation."""
    bot.clear_step_handler_by_chat_id(uid)
    if msg_id:
        start_function(uid, msg_id)
    else:
        start_function(uid)

# --- User Creation Flow ---
def _start_add_user_convo(uid, msg_id):
    admin_conversations[uid] = {'msg_id': msg_id} 
    prompt = "1\\. لطفاً یک **نام** برای کاربر جدید وارد کنید:"
    _safe_edit(uid, msg_id, prompt)
    bot.register_next_step_handler_by_chat_id(uid, _get_name_for_add_user)

def _get_name_for_add_user(msg: types.Message):
    uid, name = msg.from_user.id, msg.text.strip()

    if name.startswith('/'):
        bot.clear_step_handler_by_chat_id(uid)
        bot.send_message(uid, "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel())
        return

    msg_id = admin_conversations[uid].get('msg_id')
    admin_conversations[uid]['name'] = name
    prompt = f"نام کاربر: `{name}`\n\n2\\. حالا **مدت زمان** پلن \\(به روز\\) را وارد کنید \\(مثلاً: `30`\\)\\."
    _safe_edit(uid, msg_id, prompt)
    bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)

def _get_days_for_add_user(msg: types.Message):
    uid = msg.from_user.id
    days_text = msg.text.strip()
    
    if days_text.startswith('/'):
        bot.clear_step_handler_by_chat_id(uid)
        bot.send_message(uid, "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel())
        return

    msg_id = admin_conversations[uid].get('msg_id')
    try:
        days = int(days_text)
        admin_conversations[uid]['package_days'] = days
        name = admin_conversations[uid]['name']
        prompt = f"نام: `{name}`, مدت: `{days}` روز\n\n3\\. در نهایت، **حجم کل مصرف** \\(به گیگابایت\\) را وارد کنید \\(مثلاً: `50`\\)\\."
        _safe_edit(uid, msg_id, prompt)
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)
    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر\\. لطفاً یک عدد صحیح برای روز وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_days_for_add_user)

def _get_limit_for_add_user(msg: types.Message):
    uid = msg.from_user.id
    limit_text = msg.text.strip()
    
    if limit_text.startswith('/'):
        bot.clear_step_handler_by_chat_id(uid)
        bot.send_message(uid, "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel())
        return
        
    msg_id = admin_conversations[uid].get('msg_id')
    try:
        limit = float(limit_text)
        admin_conversations[uid]['usage_limit_GB'] = limit
        prompt = (
            "4\\. لطفاً **حالت مصرف** را با ارسال عدد مورد نظر انتخاب کنید:\n\n"
            "`1` \\- **ماهانه \\(monthly\\)**\n"
            "`2` \\- **هفتگی \\(weekly\\)**\n"
            "`3` \\- **روزانه \\(daily\\)**\n"
            "`4` \\- **بدون ریست** \\(حجم کل برای تمام دوره\\)"
        )
        _safe_edit(uid, msg_id, prompt)
        bot.register_next_step_handler_by_chat_id(uid, _get_mode_for_add_user)
    except (ValueError, TypeError):
        bot.send_message(uid, "❌ ورودی نامعتبر\\. لطفاً یک عدد برای حجم وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_limit_for_add_user)

def _get_mode_for_add_user(msg: types.Message):
    uid = msg.from_user.id
    choice = msg.text.strip()

    if choice.startswith('/'):
        bot.clear_step_handler_by_chat_id(uid)
        bot.send_message(uid, "عملیات ساخت کاربر لغو شد\\.", reply_markup=menu.admin_panel())
        return

    msg_id = admin_conversations[uid].get('msg_id')
    mode_map = {'1': 'monthly', '2': 'weekly', '3': 'daily', '4': 'no_reset'}
    if choice not in mode_map:
        bot.send_message(uid, "❌ انتخاب نامعتبر است\\. لطفاً عددی بین ۱ تا ۴ وارد کنید\\.")
        bot.register_next_step_handler_by_chat_id(uid, _get_mode_for_add_user)
        return
    _finish_user_creation(uid, msg_id, mode_map[choice])

def _finish_user_creation(uid, msg_id, mode):
    admin_conversations[uid]['mode'] = mode
    user_data = admin_conversations.pop(uid)
    user_data.pop('msg_id', None)
    name = escape_markdown(user_data['name'])
    wait_msg_text = f"⏳ در حال ساخت کاربر با اطلاعات زیر:\n> نام: `{name}`\n> حجم: `{user_data['usage_limit_GB']} GB`\n> مدت: `{user_data['package_days']}` روز\n> حالت: `{user_data['mode']}`"
    _safe_edit(uid, msg_id, wait_msg_text)
    new_user_info = api_handler.add_user(user_data)
    if new_user_info:
        report = fmt_one(new_user_info, 0)
        uuid_escaped = escape_markdown(new_user_info['uuid'])
        success_text = f"✅ کاربر با موفقیت ساخته شد\\.\n\n{report}\n\n`{uuid_escaped}`"
        bot.send_message(uid, success_text)
    else:
        bot.send_message(uid, "❌ خطا در ساخت کاربر\\. ممکن است نام تکراری باشد یا پنل در دسترس نباشد\\.")

# --- User Search Flow ---
def _ask_for_search_query(uid, msg_id):
    prompt = "لطفاً نام یا UUID کاربر مورد نظر برای مدیریت را وارد کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.admin_management_menu(), parse_mode=None)
    bot.register_next_step_handler_by_chat_id(uid, _handle_user_search)

def _handle_user_search(message: types.Message):
    uid, query = message.from_user.id, message.text.strip().lower()
    if not query:
        bot.send_message(uid, "جستجو لغو شد\\.")
        return
        
    bot.send_message(uid, "⏳ در حال جستجو\\.\\.\\.") 
    all_users = api_handler.get_all_users()
    found_user = next((u for u in all_users if u['uuid'] == query or query in u['name'].lower()), None)
    
    if found_user:
        uuid = found_user['uuid']
        daily_usage = db.get_usage_since_midnight_by_uuid(uuid)
        text = fmt_one(found_user, daily_usage)

        linked_bot_user = db.get_bot_user_by_uuid(uuid)
        if linked_bot_user:
            tg_name = escape_markdown(linked_bot_user.get('first_name', 'N/A'))
            tg_username = f" (@{linked_bot_user.get('username')})" if linked_bot_user.get('username') else ""
            tg_id = linked_bot_user.get('user_id')
            linked_text = (
                f"\n\n*🔗 کاربر تلگرام متصل به این اکانت:*\n"
                f"[`{tg_name}{escape_markdown(tg_username)}`](tg://user?id={tg_id})"
            )
            text += linked_text
        else:
            text += "\n\n*⚠️ این اکانت به هیچ کاربر تلگرامی در ربات متصل نیست\\.*"

        kb = menu.admin_user_interactive_management(uuid, found_user['is_active'])
        bot.send_message(uid, text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        bot.send_message(uid, f"❌ کاربری با مشخصات `{escape_markdown(query)}` یافت نشد\\.", reply_markup=menu.admin_management_menu())

# --- Broadcast Flow ---
def _start_broadcast_flow(uid, msg_id):
    prompt = "لطفاً جامعه هدف برای ارسال پیام همگانی را انتخاب کنید:"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.broadcast_target_menu())

def _ask_for_broadcast_message(uid, msg_id, target_group):
    admin_conversations[uid] = {'broadcast_target': target_group}
    prompt = f"پیام شما برای گروه «<b>{target_group.replace('_', ' ').title()}</b>» ارسال خواهد شد.\n\nلطفاً پیام خود را بنویسید (متن، عکس، ویدیو و...):"
    _safe_edit(uid, msg_id, prompt, reply_markup=menu.cancel_action("admin_panel"), parse_mode="HTML")
    bot.register_next_step_handler_by_chat_id(uid, _send_broadcast)

def _send_broadcast(message: types.Message):
    admin_id = message.from_user.id
    if admin_id not in admin_conversations or 'broadcast_target' not in admin_conversations[admin_id]: return
    target_group = admin_conversations.pop(admin_id)['broadcast_target']
    uuids_to_fetch, target_user_ids = [], []
    if target_group == 'online': uuids_to_fetch = [u['uuid'] for u in api_handler.online_users()]
    elif target_group == 'active_1': uuids_to_fetch = [u['uuid'] for u in api_handler.get_active_users(1)]
    elif target_group == 'inactive_7': uuids_to_fetch = [u['uuid'] for u in api_handler.get_inactive_users(1, 7)]
    elif target_group == 'inactive_0': uuids_to_fetch = [u['uuid'] for u in api_handler.get_inactive_users(-1, -1)]
    if target_group == 'all': target_user_ids = db.get_all_user_ids()
    else: target_user_ids = db.get_user_ids_by_uuids(uuids_to_fetch)
    if admin_id in target_user_ids: target_user_ids.remove(admin_id)
    if not target_user_ids:
        bot.send_message(admin_id, "هیچ کاربری در گروه هدف یافت نشد\\. پیامی ارسال نشد\\.")
        return
    unique_targets = set(target_user_ids)
    bot.send_message(admin_id, f"⏳ شروع ارسال پیام برای {len(unique_targets)} کاربر\\.\\.\\.")
    success_count, fail_count = 0, 0
    for user_id in unique_targets:
        try:
            bot.copy_message(chat_id=user_id, from_chat_id=admin_id, message_id=message.message_id)
            success_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to user {user_id}: {e}")
            fail_count += 1
        time.sleep(0.1)
    bot.send_message(admin_id, f"✅ ارسال پیام همگانی تمام شد\\.\n\n\\- ✔️ موفق: {success_count}\n\\- ❌ ناموفق: {fail_count}")

def _ask_for_new_value(uid, msg_id, uuid, edit_type):
    """Asks the admin for the new value to apply."""
    prompt_map = {
        "addgb": "لطفاً مقدار حجم برای افزودن \\(به گیگابایت\\) را وارد کنید:",
        "adddays": "لطفاً تعداد روز برای افزودن را وارد کنید:"
    }
    prompt = prompt_map.get(edit_type, "مقدار جدید را وارد کنید:")
    
    # ذخیره کردن اطلاعات برای مرحله بعد
    admin_conversations[uid] = {'uuid': uuid, 'edit_type': edit_type, 'msg_id': msg_id}
    
    _safe_edit(uid, msg_id, prompt)
    bot.register_next_step_handler_by_chat_id(uid, _apply_user_edit)

def _apply_user_edit(msg: types.Message):
    """Applies the modification to the user."""
    uid, text = msg.from_user.id, msg.text.strip()
    
    if uid not in admin_conversations: return
    
    convo = admin_conversations.pop(uid)
    uuid, edit_type, msg_id = convo['uuid'], convo['edit_type'], convo['msg_id']
    
    try:
        value = float(text)
        add_gb, add_days = 0, 0
        
        if edit_type == "addgb":
            add_gb = value
        elif edit_type == "adddays":
            add_days = int(value)
            
        if api_handler.modify_user(uuid, add_usage_gb=add_gb, add_days=add_days):
            new_info = api_handler.user_info(uuid)
            daily_usage = db.get_usage_since_midnight_by_uuid(uuid)
            text = fmt_one(new_info, daily_usage) + "\n\n✅ *کاربر با موفقیت ویرایش شد\\.*"
            _safe_edit(uid, msg_id, text, reply_markup=menu.admin_user_interactive_management(uuid, new_info['is_active']))
        else:
            _safe_edit(uid, msg_id, "❌ خطا در ویرایش کاربر\\.", reply_markup=menu.admin_user_interactive_management(uuid, True))
            
    except ValueError:
        _safe_edit(uid, msg_id, "❌ مقدار وارد شده نامعتبر است\\.", reply_markup=menu.admin_user_interactive_management(uuid, True))
    except Exception as e:
        logger.error(f"Admin edit error: {e}")
        _safe_edit(uid, msg_id, "❌ خطای ناشناخته رخ داد\\.", reply_markup=menu.admin_user_interactive_management(uuid, True))


def _show_panel(call: types.CallbackQuery):
    _safe_edit(call.from_user.id, call.message.message_id, "👑 پنل مدیریت", reply_markup=menu.admin_panel())

def _show_management_menu(call: types.CallbackQuery):
    _safe_edit(call.from_user.id, call.message.message_id, "👥 مدیریت کاربران", reply_markup=menu.admin_management_menu())

def _show_reports_menu(call: types.CallbackQuery):
    _safe_edit(call.from_user.id, call.message.message_id, "📜 *گزارش‌گیری کاربران*", reply_markup=menu.admin_reports_menu())

def _show_analytics_menu(call: types.CallbackQuery):
    _safe_edit(call.from_user.id, call.message.message_id, "📊 *تحلیل و آمار*", reply_markup=menu.admin_analytics_menu())

def _handle_add_user(call: types.CallbackQuery):
    _start_add_user_convo(call.from_user.id, call.message.message_id)

def _handle_search_user(call: types.CallbackQuery):
    _ask_for_search_query(call.from_user.id, call.message.message_id)

def _handle_broadcast(call: types.CallbackQuery):
    _start_broadcast_flow(call.from_user.id, call.message.message_id)

def _handle_health_check(call: types.CallbackQuery):
    try:
        bot.answer_callback_query(call.id, "در حال دریافت اطلاعات پنل...")
        panel_info = api_handler.get_panel_info()
        text = fmt_panel_info(panel_info)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به تحلیل‌ها", callback_data="admin_analytics"))
        _safe_edit(call.from_user.id, call.message.message_id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"ADMIN HEALTH CHECK Error for chat {call.from_user.id}: {e}")
        _safe_edit(call.from_user.id, call.message.message_id, "❌ خطایی در دریافت اطلاعات سلامت پنل رخ داد\\.", reply_markup=menu.admin_analytics_menu())

def _handle_backup_request(call: types.CallbackQuery):
    chat_id = call.from_user.id
    log_adapter = logging.LoggerAdapter(logger, {'user_id': chat_id})
    log_adapter.info("Admin requested a database backup.")

    bot.answer_callback_query(call.id, "در حال پردازش\\.\\.\\.")

    if not os.path.exists(DATABASE_PATH):
        bot.send_message(chat_id, "❌ فایل دیتابیس یافت نشد\\.")
        return

    try:
        file_size = os.path.getsize(DATABASE_PATH)
        
        if file_size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
            size_in_mb = file_size / (1024 * 1024)
            error_message = (
                f"❌ خطا: حجم فایل دیتابیس ({size_in_mb:.2f} MB) "
                f"بیشتر از حد مجاز تلگرام (50 MB) است.\n\n"
                "امکان ارسال آن از طریق ربات وجود ندارد. لطفاً فایل را به صورت دستی از سرور کپی کنید."
            )
            bot.send_message(chat_id, error_message)
            return

        bot.send_message(chat_id, "⏳ در حال آماده‌سازی و ارسال فایل پشتیبان \\.\\.\\.")
        
        with open(DATABASE_PATH, "rb") as db_file:
            bot.send_document(chat_id, db_file, caption="✅ فایل پشتیبان دیتابیس\\.")
            
    except ApiTelegramException as e:
        logger.error(f"Backup failed due to Telegram API error: {e}")
        bot.send_message(chat_id, f"❌ خطای API تلگرام: {e.description}")
        
    except Exception as e:
        logger.error(f"Backup failed with a general error: {e}")
        bot.send_message(chat_id, f"❌ یک خطای ناشناخته رخ داد: {e}")

# --- دیکشنری مپ‌کننده Callback به توابع ---
# این دیکشنری، callback_data های ثابت را به تابع مربوطه‌شان متصل می‌کند.
STATIC_CALLBACK_MAP = {
    "admin_panel": _show_panel,
    "admin_management_menu": _show_management_menu,
    "admin_reports_menu": _show_reports_menu,
    "admin_analytics": _show_analytics_menu,
    "admin_add_user": _handle_add_user,
    "admin_search_user": _handle_search_user,
    "admin_broadcast": _handle_broadcast,
    "admin_health_check": _handle_health_check,
    "admin_backup": _handle_backup_request,

}

# --- هندلر اصلی و بازآرایی شده ---
# این تابع تمام callback های ادمین را مدیریت می‌کند.
def handle_admin_callbacks(call: types.CallbackQuery):
    uid, data, msg_id = call.from_user.id, call.data, call.message.message_id

    handler = STATIC_CALLBACK_MAP.get(data)
    if handler:
        bot.clear_step_handler_by_chat_id(uid)
        handler(call)
        return
    
    if any(data.startswith(prefix) for prefix in ["admin_online_", "admin_active_1_", "admin_inactive_7_", "admin_inactive_0_", "admin_birthdays_", "admin_list_bot_users_", "admin_top_consumers_"]):
        try:
            parts = data.split('_')
            base_callback = '_'.join(parts[:-1])
            page = int(parts[-1])
            bot.answer_callback_query(call.id, "در حال دریافت لیست")
            
            user_list, text, kb = [], "", None

            if base_callback == "admin_online":
                user_list = api_handler.online_users()
                if user_list is None:
                    _safe_edit(uid, msg_id, "❌ امکان اتصال به پنل وجود ندارد. لطفاً بعداً دوباره تلاش کنید\\.", reply_markup=menu.admin_reports_menu())
                for user in user_list: user['daily_usage_GB'] = db.get_usage_since_midnight_by_uuid(user['uuid'])
                text = fmt_online_users_list(user_list, page)

            elif base_callback == "admin_active_1":
                user_list = api_handler.get_active_users(1)
                if user_list is None:
                    _safe_edit(uid, msg_id, "❌ امکان اتصال به پنل وجود ندارد. لطفاً بعداً دوباره تلاش کنید\\.", reply_markup=menu.admin_reports_menu())
                text = fmt_users_list(user_list, 'active', page)
            elif base_callback == "admin_inactive_7":
                user_list = api_handler.get_inactive_users(1, 7)
                if user_list is None:
                    _safe_edit(uid, msg_id, "❌ امکان اتصال به پنل وجود ندارد. لطفاً بعداً دوباره تلاش کنید\\.", reply_markup=menu.admin_reports_menu())
                text = fmt_users_list(user_list, 'inactive', page)
            elif base_callback == "admin_inactive_0":
                user_list = api_handler.get_inactive_users(-1, -1)
                if user_list is None:
                    _safe_edit(uid, msg_id, "❌ امکان اتصال به پنل وجود ندارد. لطفاً بعداً دوباره تلاش کنید\\.", reply_markup=menu.admin_reports_menu())
                db_users = db.all_active_uuids()
                uuid_to_created_at = {u['uuid']: u['created_at'] for u in db_users}
                for user in user_list:
                    user['created_at'] = uuid_to_created_at.get(user['uuid'])
                text = fmt_users_list(user_list, 'never_connected', page)
            elif base_callback == "admin_birthdays":
                user_list = db.get_users_with_birthdays()
                text = fmt_birthdays_list(user_list, page)
            elif base_callback == "admin_list_bot_users":
                user_list = db.get_all_bot_users()
                text = fmt_bot_users_list(user_list, page)
            elif base_callback == "admin_top_consumers":
                user_list = api_handler.get_top_consumers()
                text = fmt_top_consumers(user_list, page)

            back_callback_map = {
                "admin_online": "admin_reports_menu", "admin_active_1": "admin_reports_menu",
                "admin_inactive_7": "admin_reports_menu", "admin_inactive_0": "admin_reports_menu",
                "admin_birthdays": "admin_reports_menu", "admin_list_bot_users": "admin_management_menu",
                "admin_top_consumers": "admin_analytics"
            }
            back_callback = back_callback_map.get(base_callback, "admin_panel")
            kb = menu.create_pagination_menu(base_callback, page, len(user_list), back_callback)
            
            if kb: _safe_edit(uid, msg_id, text, reply_markup=kb)

        except Exception as e:
            logger.exception(f"ADMIN LIST Error for chat {uid}, data: {data}")
            _safe_edit(uid, msg_id, "❌ خطایی در پردازش لیست رخ داد\\.", reply_markup=menu.admin_panel())

    # مدیریت عملیات روی یک کاربر خاص
    elif data.startswith("admin_toggle_"):
        uuid = data.replace("admin_toggle_", "")
        info = api_handler.user_info(uuid)
        if info and api_handler.modify_user(uuid, data={'is_active': not info['is_active']}):
            bot.answer_callback_query(call.id, f"کاربر {'فعال' if not info['is_active'] else 'غیرفعال'} شد.")
            new_info = api_handler.user_info(uuid)
            daily_usage = db.get_usage_since_midnight_by_uuid(uuid)
            _safe_edit(uid, msg_id, fmt_one(new_info, daily_usage), reply_markup=menu.admin_user_interactive_management(uuid, new_info['is_active']))
        else: bot.answer_callback_query(call.id, "❌ خطا در تغییر وضعیت.")

    elif data.startswith("admin_reset_bday_"):
        uuid = data.replace("admin_reset_bday_", "")
        user_id_to_reset = db.get_user_id_by_uuid(uuid)
        if user_id_to_reset:
            db.reset_user_birthday(user_id_to_reset)
            bot.answer_callback_query(call.id, "✅ تاریخ تولد کاربر با موفقیت ریست شد\\.")
            _safe_edit(uid, msg_id, call.message.text + "\n\n*تاریخ تولد کاربر ریست شد\\.*", reply_markup=call.message.reply_markup)
        else: bot.answer_callback_query(call.id, "❌ خطا: کاربری برای این UUID یافت نشد\\.")

    elif data.startswith("admin_reset_usage_"):
        uuid = data.replace("admin_reset_usage_", "")
        if api_handler.reset_user_usage(uuid):
            bot.answer_callback_query(call.id, "✅ مصرف کاربر صفر شد.")
            new_info = api_handler.user_info(uuid)
            daily_usage = db.get_usage_since_midnight_by_uuid(uuid)
            _safe_edit(uid, msg_id, fmt_one(new_info, daily_usage), reply_markup=menu.admin_user_interactive_management(uuid, new_info['is_active']))
        else: bot.answer_callback_query(call.id, "❌ خطا در ریست کردن مصرف.")

    elif data.startswith("admin_delete_"):
        uuid = data.replace("admin_delete_", "")
        _safe_edit(uid, msg_id, f"⚠️ *آیا از حذف کامل کاربر با UUID زیر اطمینان دارید؟*\n`{escape_markdown(uuid)}`", reply_markup=menu.confirm_delete(uuid))

    elif data.startswith("admin_confirm_delete_"):
        uuid = data.replace("admin_confirm_delete_", "")
        _safe_edit(uid, msg_id, "⏳ در حال حذف کامل کاربر...")
        if api_handler.delete_user(uuid):
            db.delete_user_by_uuid(uuid)
            _safe_edit(uid, msg_id, "✅ کاربر با موفقیت از پنل و ربات حذف شد\\.", reply_markup=menu.admin_management_menu())
        else: _safe_edit(uid, msg_id, "❌ خطا در حذف کاربر از پنل\\.", reply_markup=menu.admin_management_menu())

    elif data.startswith("admin_cancel_delete_"):
        _safe_edit(uid, msg_id, "عملیات حذف لغو شد.", reply_markup=menu.admin_management_menu())

    # مدیریت مکالمه پیام همگانی
    elif data.startswith("broadcast_target_"):
        target_group = data.replace("broadcast_target_", "")
        _ask_for_broadcast_message(uid, msg_id, target_group)

    # مدیریت مکالمه ویرایش کاربر
    elif data.startswith("admin_edit_"):
        uuid = data.replace("admin_edit_", "")
        if data.startswith("admin_edit_addgb_"):
            _ask_for_new_value(uid, msg_id, uuid.replace("addgb_", ""), "addgb")
        elif data.startswith("admin_edit_adddays_"):
            _ask_for_new_value(uid, msg_id, uuid.replace("adddays_", ""), "adddays")
        else:
            _safe_edit(uid, msg_id, "🔧 *کدام ویژگی را می‌خواهید ویرایش کنید؟*", reply_markup=menu.admin_edit_user_menu(uuid))

    elif data.startswith("admin_search_result_"):
        uuid = data.replace("admin_search_result_", "")
        info = api_handler.user_info(uuid)
        daily_usage = db.get_usage_since_midnight_by_uuid(uuid)
        _safe_edit(uid, msg_id, fmt_one(info, daily_usage), reply_markup=menu.admin_user_interactive_management(uuid, info['is_active']))

