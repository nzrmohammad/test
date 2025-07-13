import pytz
from datetime import datetime, timedelta
from config import EMOJIS, PAGE_SIZE
from database import db
from api_handler import api_handler
import jdatetime
from utils import (
    create_progress_bar, persian_date,
    format_daily_usage, escape_markdown,
    format_relative_time, load_service_plans
)

def fmt_one(info: dict, daily_usage_gb: float) -> str:
    if not info: return "❌ خطا در دریافت اطلاعات"
    
    name = escape_markdown(info.get("name", "کاربر ناشناس"))
    bar = create_progress_bar(info.get("usage_percentage", 0))
    status_emoji = "🟢" if info.get("is_active") else "🔴"
    status_text = "فعال" if info.get("is_active") else "غیرفعال"
    
    total_usage = escape_markdown(f"{info.get('current_usage_GB', 0):.2f}")
    limit = escape_markdown(f"{info.get('usage_limit_GB', 0):.2f}")
    remaining = escape_markdown(f"{info.get('remaining_GB', 0):.2f}")
    uuid = escape_markdown(info.get('uuid', ''))
    
    last_online = persian_date(info.get('last_online'))
    daily_usage_str = format_daily_usage(daily_usage_gb)
    
    expire_days = info.get("expire")
    expire_label = "نامحدود"
    if expire_days is not None:
        expire_label = f"{expire_days} روز" if expire_days >= 0 else "منقضی شده"
        
    report = (f"{EMOJIS['user']} *{name}* \\({status_emoji} {status_text}\\)\n`{bar}`\n\n"
              f"{EMOJIS['chart']} *مجموع مصرف:* `{total_usage} / {limit} GB`\n"
              f"{EMOJIS['download']} *مجموع باقیمانده:* `{remaining} GB`\n"
              f"{EMOJIS['lightning']} *مصرف امروز:* `{escape_markdown(daily_usage_str)}`")

    if 'breakdown' in info:
        report += "\n\n" + "─" * 15 + "\n*تفکیک مصرف سرورها:*"
        
        h_usage = info['breakdown']['hiddify']['usage']
        h_limit = info['breakdown']['hiddify']['limit']
        report += f"\n`•` *آلمان (Hiddify):* `{h_usage:.2f} / {h_limit:.2f} GB`"

        if 'marzban' in info['breakdown']:
            m_usage = info['breakdown']['marzban']['usage']
            m_limit = info['breakdown']['marzban']['limit']
            report += f"\n`•` *فرانسه (Marzban):* `{m_usage:.2f} / {m_limit:.2f} GB`"

    report += (f"\n\n{EMOJIS['calendar']} *انقضا:* {escape_markdown(expire_label)}\n"
               f"{EMOJIS['time']} *آخرین اتصال:* {escape_markdown(last_online)}\n"
               f"{EMOJIS['key']} *UUID:* `{uuid}`")
               
    return report

def fmt_users_list(users: list, list_type: str, page: int) -> str:
    title_map = {
        'active': "✅ کاربران فعال (۲۴ ساعت اخیر)",
        'inactive': "⏳ کاربران غیرفعال (۱ تا ۷ روز)",
        'never_connected': "🚫 کاربرانی که هرگز متصل نشده‌اند"
    }
    title = title_map.get(list_type, "لیست کاربران")
    
    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این دسته یافت نشد\\."

    lines = [f"*{escape_markdown(title)}*"]
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        lines.append(f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)")

    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]

    for user in paginated_users:
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        line = f"`•` *{name}*"
        
        if list_type == 'active':
            last_online_str = persian_date(user.get('last_online')).split(' - ')[-1] # فقط ساعت
            usage_p = user.get('usage_percentage', 0)
            line += f" `|` Last Seen: `{last_online_str}` `|` Usage: `{usage_p:.1f}%`"

        elif list_type == 'inactive':
            last_online_str = format_relative_time(user.get('last_online'))
            status = "Expired" if user.get('expire', 0) < 0 else "Active"
            line += f" `|` Last Seen: `{last_online_str}` `|` Status: `{status}`"
            
        elif list_type == 'never_connected':
            created_at_str = format_relative_time(user.get('created_at'))
            limit_gb = user.get('usage_limit_GB', 0)
            line += f" `|` Registered: `{created_at_str}` `|` Limit: `{limit_gb} GB`"
            
        lines.append(line)
        
    return "\n".join(lines)

def fmt_online_users_list(users: list, page: int) -> str:
    title = "⚡️ کاربران آنلاین (۳ دقیقه اخیر)"
    if not users:
        return f"*{escape_markdown(title)}*\n\nهیچ کاربری در این لحظه آنلاین نیست."

    uuid_to_bot_user = db.get_uuid_to_bot_user_map()
    header_lines = [f"*{escape_markdown(title)}*"]
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        page_info_text = f"(صفحه {page + 1} از {total_pages} | کل: {len(users)})"
        header_lines.append(escape_markdown(page_info_text))

    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    user_lines = []

    for user in paginated_users:
        panel_name_raw = user.get('name', 'کاربر ناشناس')
        bot_user_info = uuid_to_bot_user.get(user.get('uuid'))

        # --- شروع تغییرات ---
        name_str = escape_markdown(panel_name_raw)  # حالت پیش‌فرض اگر کاربر در ربات نباشد

        if bot_user_info and bot_user_info.get('user_id'):
            user_id = bot_user_info['user_id']
            username = bot_user_info.get('username')
            
            # بخش لینک: نام کاربر پنل، بدون escape شدن
            link_part = f"[{panel_name_raw}](tg://user?id={user_id})"
            
            # بخش نام کاربری: این بخش escape می‌شود تا با مارک‌داون تداخل نکند
            username_part = escape_markdown(f" (@{username})") if username else ""
            
            # ترکیب دو بخش برای ساخت خروجی نهایی
            name_str = f"{link_part}{username_part}"
        # --- پایان تغییرات ---

        daily_usage_output = escape_markdown(format_daily_usage(user.get('daily_usage_GB', 0)))
        expire_days = user.get("expire")
        expire_text = "Unlimited"
        if expire_days is not None:
            expire_text = f"{expire_days} Days" if expire_days >= 0 else "Expired"
        expire_output = escape_markdown(expire_text)
        
        line = f"{name_str} \\| {daily_usage_output} \\| {expire_output}"
        user_lines.append(line)

    header_text = "\n".join(header_lines)
    body_text = "\n".join(user_lines)
    return f"{header_text}\n\n{body_text}"

def quick_stats(uuid_rows: list) -> str:
    if not uuid_rows: return "هیچ اکانتی ثبت نشده است"

    all_user_info = api_handler.get_all_users()
    user_info_map = {user['uuid']: user for user in all_user_info}
    
    total_usage, total_limit, active_accounts, total_daily = 0.0, 0.0, 0, 0.0
    
    for row in uuid_rows:
        info = user_info_map.get(row['uuid'])
        if info:
            total_usage += info.get("current_usage_GB", 0)
            total_limit += info.get("usage_limit_GB", 0)
            if info.get("is_active"):
                active_accounts += 1
            total_daily += db.get_usage_since_midnight(row['id'])
            
    remaining_total = max(0, total_limit - total_usage)
    
    return (f"*خلاصه کلی اکانت‌ها*\n"
            f"{EMOJIS['user']} تعداد کل: {len(uuid_rows)} \\| {EMOJIS['success']} فعال: {active_accounts}\n"
            f"{EMOJIS['database']} مجموع حجم کل: `{total_limit:.2f} GB`\n"
            f"{EMOJIS['chart']} مجموع مصرف: `{total_usage:.2f} GB`\n"
            f"{EMOJIS['download']} مجموع باقیمانده: `{remaining_total:.2f} GB`\n"
            f"{EMOJIS['lightning']} مصرف امروز \\(کل\\): `{escape_markdown(format_daily_usage(total_daily))}`")


def fmt_admin_report(all_users_from_api: list, db_manager) -> str:
    if not all_users_from_api:
        return "هیچ کاربری در پنل یافت نشد\\."

    total_usage_all, total_daily_all, active_users = 0.0, 0.0, 0
    online_users, expiring_soon_users, new_users_today = [], [], []
    
    now_utc = datetime.now(pytz.utc)
    online_deadline = now_utc - timedelta(minutes=3)
    
    db_users_map = {u['uuid']: u.get('created_at') for u in db_manager.all_active_uuids()}

    for user_info in all_users_from_api:
        if user_info.get("is_active"):
            active_users += 1
        total_usage_all += user_info.get("current_usage_GB", 0)
        total_daily_all += db_manager.get_usage_since_midnight_by_uuid(user_info['uuid'])
        
        # Check for online users
        if user_info.get('is_active') and user_info.get('last_online') and user_info['last_online'].astimezone(pytz.utc) >= online_deadline:
            online_users.append(user_info)

        # Check for expiring soon users
        if user_info.get('expire') is not None and 0 <= user_info['expire'] <= 3:
            expiring_soon_users.append(user_info)
            
        # Check for new users (requires created_at from our DB)
        created_at = db_users_map.get(user_info['uuid'])
        if created_at and (now_utc - created_at.astimezone(pytz.utc)).days < 1:
            new_users_today.append(user_info)

    report_lines = [
        f"{EMOJIS['gear']} *خلاصه وضعیت کل پنل*",
        f"\\- {EMOJIS['user']} تعداد کل اکانت‌ها: *{len(all_users_from_api)}*",
        f"\\- {EMOJIS['success']} اکانت‌های فعال: *{active_users}*",
        f"\\- {EMOJIS['wifi']} کاربران آنلاین: *{len(online_users)}*",
        f"\\- {EMOJIS['chart']} *مجموع مصرف کل:* `{escape_markdown(f'{total_usage_all:.2f}')} GB`",
        f"\\- {EMOJIS['lightning']} *مصرف امروز کل:* `{escape_markdown(format_daily_usage(total_daily_all))}`"
    ]

    # ✅ [FIXED] افزودن مجدد لیست کاربران آنلاین
    if online_users:
        report_lines.append("\n" + "─" * 20 + f"\n*{EMOJIS['wifi']} کاربران آنلاین و مصرف امروزشان:*")
        online_users.sort(key=lambda u: u.get('name', ''))
        for user in online_users:
            daily_usage = db_manager.get_usage_since_midnight_by_uuid(user['uuid'])
            user_name = escape_markdown(user.get('name', 'کاربر ناشناس'))
            usage_str = escape_markdown(format_daily_usage(daily_usage))
            report_lines.append(f"`•` *{user_name}:* `{usage_str}`")

    # بخش کاربران در آستانه انقضا
    if expiring_soon_users:
        report_lines.append("\n" + "─" * 20 + f"\n*{EMOJIS['warning']} کاربرانی که به زودی منقضی می‌شوند (تا ۳ روز):*")
        expiring_soon_users.sort(key=lambda u: u.get('expire', 99))
        for user in expiring_soon_users:
            name = escape_markdown(user['name'])
            days = user['expire']
            report_lines.append(f"`•` *{name}:* `{days} روز باقیمانده`")

    # بخش کاربران جدید
    if new_users_today:
        report_lines.append("\n" + "─" * 20 + f"\n*{EMOJIS['star']} کاربران جدید (۲۴ ساعت اخیر):*")
        for user in new_users_today:
            name = escape_markdown(user['name'])
            report_lines.append(f"`•` *{name}*")

    return "\n".join(report_lines)

def fmt_user_report(user_infos: list) -> str:
    """Formats a daily report for a user, including individual daily usage."""
    if not user_infos: return "شما اکانت فعالی برای گزارش‌گیری ندارید\\."
    
    total_daily = 0.0
    accounts_details = []
    
    for info in user_infos:
        # دیگر نیازی به user_info(row['uuid']) نیست
        
        # برای get_usage_since_midnight به id از جدول user_uuids نیاز داریم
        # که در scheduler به دیکشنری info اضافه کردیم
        daily_usage = db.get_usage_since_midnight(info['db_id'])
        total_daily += daily_usage
        name = escape_markdown(info.get("name", "کاربر ناشناس"))
        
        usage_str = f"`{escape_markdown(f'{info.get("current_usage_GB", 0):.2f}')} / {escape_markdown(f'{info.get("usage_limit_GB", 0):.2f}')} GB`"
        
        expire_days = info.get("expire")
        expire_str = "نامحدود"
        if expire_days is not None:
            expire_str = f"`{expire_days} روز`" if expire_days >= 0 else "`منقضی شده`"
        
        daily_usage_str = escape_markdown(format_daily_usage(daily_usage))
            
        accounts_details.append(
            f"{EMOJIS['user']} *اکانت: {name}*\n"
            f"`  `{EMOJIS['chart']} *مصرف کل:* {usage_str}\n"
            f"`  `{EMOJIS['lightning']} *مصرف امروز:* `{daily_usage_str}`\n"
            f"`  `{EMOJIS['calendar']} *انقضا:* {expire_str}"
        )

    if not accounts_details: return "اطلاعات هیچ یک از اکانت‌های شما دریافت نشد\\."
    
    report_body = "\n\n".join(accounts_details)
    return f"{report_body}\n\n{EMOJIS['lightning']} *مجموع مصرف امروز شما:* `{escape_markdown(format_daily_usage(total_daily))}`"

def fmt_panel_info(info: dict) -> str:
    """Formats the panel health check info with emojis."""
    if not info: return "اطلاعاتی از پنل دریافت نشد\\."
    
    title = escape_markdown(info.get('title', 'N/A'))
    description = escape_markdown(info.get('description', 'N/A'))
    version = escape_markdown(info.get('version', 'N/A'))
    
    return (f"{EMOJIS['gear']} *اطلاعات پنل Hiddify*\n\n"
            f"**عنوان:** {title}\n"
            f"**توضیحات:** {description}\n"
            f"**نسخه:** {version}\n")

def fmt_top_consumers(users: list, page: int) -> str:
    """Formats a paginated list of top consumers in text format."""
    title = "پرمصرف‌ترین کاربران"
    if not users:
        return f"🏆 *{escape_markdown(title)}*\n\nهیچ کاربری برای نمایش وجود ندارد\\."

    header_lines = [f"🏆 *{escape_markdown(title)}*"]
    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        header_lines.append(f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)")

    paginated_users = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    user_lines = []

    for i, user in enumerate(paginated_users, start=page * PAGE_SIZE + 1):
        name = escape_markdown(user.get('name', 'کاربر ناشناس'))
        usage = user.get('current_usage_GB', 0)
        limit = user.get('usage_limit_GB', 0)
        usage_str = f"`{usage:.2f} GB / {limit:.2f} GB`"
        line = f"`{i}.` *{name}* `|` {EMOJIS['chart']} {usage_str}"
        user_lines.append(line)

    header_text = "\n".join(header_lines)
    body_text = "\n".join(user_lines)

    return f"{header_text}\n\n{body_text}"

def fmt_bot_users_list(bot_users: list, page: int) -> str:
    title = "کاربران ربات"
    if not bot_users:
        return f"🤖 *{escape_markdown(title)}*\n\nهیچ کاربری در ربات ثبت‌نام نکرده است\\."

    lines = [f"🤖 *{escape_markdown(title)}*"]
    total_users = len(bot_users)

    if total_users > PAGE_SIZE:
        total_pages = (total_users + PAGE_SIZE - 1) // PAGE_SIZE
        lines.append(f"\\(صفحه {page + 1} از {total_pages} \\| کل: {total_users}\\)")

    start_index = page * PAGE_SIZE
    paginated_users = bot_users[start_index : start_index + PAGE_SIZE]

    for user in paginated_users:
        user_id = user.get('user_id')
        first_name = escape_markdown(user.get('first_name') or 'ناشناس')
        username = escape_markdown(f"(@{user.get('username')})" if user.get('username') else '')
        lines.append(f"`•` {first_name} {username} `| ID:` `{user_id}`")

    return "\n".join(lines)

def fmt_birthdays_list(users: list, page: int) -> str:
    title = "لیست تولد کاربران"
    if not users:
        return f"🎂 *{escape_markdown(title)}*\n\nهیچ کاربری تاریخ تولد خود را ثبت نکرده است\\."
    
    lines = [f"🎂 *{escape_markdown(title)}* \\(مرتب شده بر اساس ماه\\)"]

    if len(users) > PAGE_SIZE:
        total_pages = (len(users) + PAGE_SIZE - 1) // PAGE_SIZE
        lines.append(f"\\(صفحه {page + 1} از {total_pages} \\| کل: {len(users)}\\)")

    start_index = page * PAGE_SIZE
    paginated_users = users[start_index : start_index + PAGE_SIZE]

    for user in paginated_users:
        name = escape_markdown(user.get('first_name', 'کاربر ناشناس'))
        
        gregorian_date = user['birthday']
        
        shamsi_date = jdatetime.date.fromgregorian(date=gregorian_date)
        shamsi_str = shamsi_date.strftime('%Y/%m/%d')
        
        gregorian_str = gregorian_date.strftime('%Y-%m-%d')
        
        lines.append(f"`•` *{name}* `|` solar: `{shamsi_str}` `|` lunar: `{gregorian_str}`")
        
    return "\n".join(lines)

def fmt_service_plans() -> str:
    SERVICE_PLANS = load_service_plans()

    if not SERVICE_PLANS:
        return "در حال حاضر پلن فعالی برای نمایش وجود ندارد\\."

    lines = [f"*{EMOJIS['rocket']} پلن‌های فروش سرویس*"]
    
    for plan in SERVICE_PLANS:
        lines.append("\n" + "─" * 20)
        lines.append(f"*{escape_markdown(plan['name'])}*")
        lines.append(f"*حجم کل:{escape_markdown(plan['total_volume'])}*")
        lines.append(f"حجم آلمان:{escape_markdown(plan['volume_de'])}")
        lines.append(f"حجم فرانسه:{escape_markdown(plan['volume_fr'])}")
        lines.append(f"مدت زمان:{escape_markdown(plan['duration'])}")
                
    lines.append("\n" + "─" * 20)
    lines.append("نکته : حجم 🇫🇷 قابل تبدیل به 🇩🇪 هست ولی 🇩🇪 قابل تبدیل به 🇫🇷 نیست")
    lines.append("برای اطلاع از قیمت‌ها و دریافت مشاوره، لطفاً به ادمین پیام دهید\\.")
    return "\n".join(lines)
