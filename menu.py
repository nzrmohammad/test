from telebot import types
from config import EMOJIS, PAGE_SIZE

class Menu:
    def main(self, is_admin: bool, has_birthday: bool = False) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(f"{EMOJIS['key']} مدیریت اکانت", callback_data="manage"),
            types.InlineKeyboardButton(f"{EMOJIS['lightning']} آمار فوری", callback_data="quick_stats")
        )

        btn_services = types.InlineKeyboardButton(f"{EMOJIS['money']} مشاهده سرویس ها", callback_data="view_plans")
        btn_settings = types.InlineKeyboardButton(f"{EMOJIS['bell']} تنظیمات", callback_data="settings")
        btn_birthday = types.InlineKeyboardButton("🎁 هدیه تولد", callback_data="birthday_gift")

        if not has_birthday:
            kb.add(btn_settings, btn_services)
            kb.add(btn_birthday)
        else:
            kb.add(btn_settings, btn_services)
        
        if is_admin:
            kb.add(types.InlineKeyboardButton(f"{EMOJIS['crown']} پنل مدیریت", callback_data="admin_panel"))
        return kb

    def accounts(self, rows) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in rows:
            name = r.get('name', 'کاربر ناشناس')
            kb.add(types.InlineKeyboardButton(f"📊 {name}", callback_data=f"acc_{r['id']}"))
        kb.add(types.InlineKeyboardButton("➕ افزودن اکانت جدید", callback_data="add"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back"))
        return kb

    def account_menu(self, uuid_id: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("⏱ مصرف بازه‌ای", callback_data=f"win_{uuid_id}"),
            types.InlineKeyboardButton(f"{EMOJIS['globe']} دریافت لینک‌ها", callback_data=f"getlinks_{uuid_id}")
        )
        kb.add(
            types.InlineKeyboardButton("🗑 حذف", callback_data=f"del_{uuid_id}"),
            types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="manage")
        )
        return kb

    def settings(self, settings_dict: dict) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        daily = settings_dict.get('daily_reports', True)
        expiry = settings_dict.get('expiry_warnings', True)
        kb.add(
            types.InlineKeyboardButton(f"📊 گزارش روزانه: {'✅' if daily else '❌'}", callback_data="toggle_daily_reports"),
            types.InlineKeyboardButton(f"⏰ هشدار انقضا: {'✅' if expiry else '❌'}", callback_data="toggle_expiry_warnings")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back"))
        return kb

    def admin_panel(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_reports = types.InlineKeyboardButton("📜 گزارش گیری", callback_data="admin_reports_menu")
        btn_manage = types.InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_management_menu")
        btn_analytics = types.InlineKeyboardButton("📊 تحلیل و آمار", callback_data="admin_analytics")
        btn_broadcast = types.InlineKeyboardButton("📤 پیام همگانی", callback_data="admin_broadcast")
        btn_backup = types.InlineKeyboardButton("🗄️ پشتیبان‌گیری دیتابیس", callback_data="admin_backup")
        btn_back = types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")
        kb.add(btn_reports, btn_manage)
        kb.add(btn_analytics, btn_broadcast)
        kb.add(btn_backup)
        kb.add(btn_back)
        return kb

    def admin_management_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("➕ افزودن کاربر جدید", callback_data="admin_add_user"),
            types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user")
        )
        kb.add(types.InlineKeyboardButton("🤖 لیست کاربران ربات", callback_data="admin_list_bot_users_0"))
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_panel"))
        return kb

    def admin_reports_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        btn_online = types.InlineKeyboardButton("📡 کاربران آنلاین", callback_data="admin_online_0")
        btn_active = types.InlineKeyboardButton("✅ فعال (۲۴ ساعت اخیر)", callback_data="admin_active_1_0")
        btn_inactive = types.InlineKeyboardButton("⏳ غیرفعال (۱ تا ۷ روز)", callback_data="admin_inactive_7_0")
        btn_never = types.InlineKeyboardButton("🚫 هرگز متصل نشده", callback_data="admin_inactive_0_0")
        btn_birthdays = types.InlineKeyboardButton("🎂 تولد کاربران", callback_data="admin_birthdays_0")
        btn_back = types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_panel")
        kb.add(btn_active, btn_online)
        kb.add(btn_never, btn_inactive)
        kb.add(btn_birthdays)
        kb.add(btn_back)
        return kb

    def create_pagination_menu(self, base_callback: str, current_page: int, total_items: int, back_callback: str = "admin_reports_menu") -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        back_text_map = {
            "admin_reports_menu": "🔙 بازگشت به گزارشات",
            "admin_management_menu": "🔙 بازگشت به مدیریت",
            "admin_analytics": "🔙 بازگشت به تحلیل‌ها",
        }
        back_text = back_text_map.get(back_callback, "🔙 بازگشت")

        if total_items <= PAGE_SIZE:
            kb.add(types.InlineKeyboardButton(back_text, callback_data=back_callback))
            return kb

        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"{base_callback}_{current_page - 1}"))
        
        if (current_page + 1) * PAGE_SIZE < total_items:
            nav_buttons.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"{base_callback}_{current_page + 1}"))
        
        if nav_buttons:
            kb.row(*nav_buttons)
        
        kb.add(types.InlineKeyboardButton(back_text, callback_data=back_callback))
        return kb

    def admin_user_interactive_management(self, uuid: str, is_active: bool) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        
        status_text = "🔴 غیرفعال کردن" if is_active else "🟢 فعال کردن"
        kb.add(types.InlineKeyboardButton(status_text, callback_data=f"admin_toggle_{uuid}"))

        kb.add(types.InlineKeyboardButton("🔄 ریست تاریخ تولد", callback_data=f"admin_reset_bday_{uuid}"))

        
        kb.add(
            types.InlineKeyboardButton("🔄 ریست مصرف", callback_data=f"admin_reset_usage_{uuid}"),
            types.InlineKeyboardButton("🗑 حذف کامل", callback_data=f"admin_delete_{uuid}")
        )
        kb.add(types.InlineKeyboardButton("🔧 ویرایش کاربر", callback_data=f"admin_edit_{uuid}"))
        
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="admin_management_menu"))
        return kb

    def confirm_delete(self, uuid: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"admin_confirm_delete_{uuid}"),
            types.InlineKeyboardButton("❌ خیر، لغو", callback_data=f"admin_cancel_delete_{uuid}")
        )
        return kb

    def admin_analytics_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🏆 پرمصرف‌ترین کاربران", callback_data="admin_top_consumers_0"),
            types.InlineKeyboardButton("🌡️ وضعیت سلامت پنل", callback_data="admin_health_check")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_panel"))
        return kb
    
    def broadcast_target_menu(self) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📡 آنلاین", callback_data="broadcast_target_online"),
            types.InlineKeyboardButton("✅ فعال اخیر", callback_data="broadcast_target_active_1")
        )
        kb.add(
            types.InlineKeyboardButton("⏳ غیرفعال اخیر", callback_data="broadcast_target_inactive_7"),
            types.InlineKeyboardButton("🚫 هرگز متصل نشده", callback_data="broadcast_target_inactive_0")
        )
        kb.add(types.InlineKeyboardButton("👥 همه کاربران ربات", callback_data="broadcast_target_all"))
        kb.add(types.InlineKeyboardButton("🔙 لغو و بازگشت", callback_data="admin_panel"))
        return kb
    
    def cancel_action(self, back_callback="back") -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔙 لغو عملیات", callback_data=back_callback))
        return kb

    def admin_edit_user_menu(self, uuid: str) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("➕ افزودن حجم", callback_data=f"admin_edit_addgb_{uuid}"),
            types.InlineKeyboardButton("➕ افزودن روز", callback_data=f"admin_edit_adddays_{uuid}")
        )
        kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_search_result_{uuid}"))
        return kb

menu = Menu()