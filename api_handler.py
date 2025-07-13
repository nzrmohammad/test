import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import pytz
import requests
from requests.adapters import HTTPAdapter, Retry
from cachetools import cached

from config import HIDDIFY_DOMAIN, ADMIN_PROXY_PATH, ADMIN_UUID, API_TIMEOUT, api_cache
from utils import safe_float

logger = logging.getLogger(__name__)

class HiddifyAPIHandler:
    def __init__(self):
        self.base_url = f"{HIDDIFY_DOMAIN.rstrip('/')}/{ADMIN_PROXY_PATH.strip('/')}/api/v2/admin"
        self.api_key = ADMIN_UUID
        self.tehran_tz = pytz.timezone("Asia/Tehran")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Hiddify-API-Key": self.api_key,
            "Accept": "application/json"
        })
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def _parse_api_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str or date_str.startswith('0001-01-01'):
            return None
        try:
            clean_str = date_str.split('.')[0].replace('T', ' ')
            naive_dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")

            local_dt = self.tehran_tz.localize(naive_dt)

            return local_dt.astimezone(pytz.utc)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse datetime string '{date_str}'")
            return None

    def _calculate_remaining_days(self, start_date_str: Optional[str], package_days: Optional[int]) -> Optional[int]:
        if package_days in [None, 0]:
            return None

        # --- اصلاح باگ تاریخ انقضا ---
        # اگر تاریخ شروع توسط API ارسال نشده بود، تاریخ امروز را به عنوان مبنا در نظر بگیر
        if not start_date_str:
            start_date = datetime.now(self.tehran_tz).date()
        else:
            try:
                # برخی تاریخ‌ها ممکن است شامل زمان هم باشند، فقط بخش تاریخ را جدا می‌کنیم
                start_date = datetime.strptime(start_date_str.split('T')[0], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                 logger.warning(f"Could not parse start_date string '{start_date_str}', using today's date.")
                 start_date = datetime.now(self.tehran_tz).date()

        expiration_date = start_date + timedelta(days=package_days)
        return (expiration_date - datetime.now(self.tehran_tz).date()).days

    def _norm(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict): return None
        try:
            usage_limit = safe_float(raw.get("usage_limit_GB", 0))
            current_usage = safe_float(raw.get("current_usage_GB", 0))
            return {
                "name": raw.get("name") or "کاربر ناشناس",
                "uuid": raw.get("uuid", ""),
                "is_active": bool(raw.get("is_active", raw.get("enable", False))),
                "last_online": self._parse_api_datetime(raw.get("last_online")),
                "usage_limit_GB": usage_limit,
                "current_usage_GB": current_usage,
                "remaining_GB": max(0, usage_limit - current_usage),
                "usage_percentage": (current_usage / usage_limit * 100) if usage_limit > 0 else 0,
                "expire": self._calculate_remaining_days(raw.get("start_date"), raw.get("package_days")),
                "mode": raw.get("mode", "no_reset")
            }
        except Exception as e:
            logger.error(f"Data normalization failed: {e}, raw data: {raw}")
            return None

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=API_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response.json() if response.status_code != 204 else True
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {method} {url} - {e}")
            return None

    def test_connection(self) -> bool:
        return self._request("GET", "/user/") is not None

    @cached(api_cache)
    def get_all_users(self) -> List[Dict[str, Any]]:
        # این تابع حالا فقط هر ۶۰ ثانیه یک بار واقعاً اجرا می‌شود
        data = self._request("GET", "/user/")
        if not data:
            return []
        
        if isinstance(data, list):
            raw_users = data
        elif isinstance(data, dict):
            raw_users = data.get("results") or data.get("users") or []
        else:
            return []

        return [norm_user for u in raw_users if (norm_user := self._norm(u))]

    def user_info(self, uuid: str) -> Optional[Dict[str, Any]]:
        raw_data = self._request("GET", f"/user/{uuid}/")
        return self._norm(raw_data) if raw_data else None

    def get_panel_info(self) -> Optional[Dict[str, Any]]:
        panel_info_url = f"{HIDDIFY_DOMAIN.rstrip('/')}/{ADMIN_PROXY_PATH.strip('/')}/api/v2/panel/info/"
        try:
            response = self.session.get(panel_info_url, timeout=API_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request for panel info failed: {e}")
            return None
        
    def get_top_consumers(self) -> List[Dict[str, Any]]:
        """
        Fetches all users and sorts them by current usage in descending order.
        """
        all_users = self.get_all_users()
        if not all_users:
            return []
        
        # Sort users by the 'current_usage_GB' key
        sorted_users = sorted(
            all_users, 
            key=lambda u: u.get('current_usage_GB', 0), 
            reverse=True
        )
        return sorted_users

    def online_users(self) -> List[Dict[str, Any]]:
        all_users = self.get_all_users()
        online = []
        three_minutes_ago = datetime.now(pytz.utc) - timedelta(minutes=3)
        for user in all_users:
            if user.get('is_active') and user.get('last_online') and user['last_online'].astimezone(pytz.utc) >= three_minutes_ago:
                online.append(user)
        return online

    def get_active_users(self, days: int) -> List[Dict[str, Any]]:
        all_users = self.get_all_users()
        active = []
        deadline = datetime.now(pytz.utc) - timedelta(days=days)
        for user in all_users:
            if user.get('last_online') and user['last_online'].astimezone(pytz.utc) >= deadline:
                active.append(user)
        return active

    def get_inactive_users(self, min_days: int, max_days: int) -> List[Dict[str, Any]]:
        all_users = self.get_all_users()
        inactive = []
        now_utc = datetime.now(pytz.utc)
        for user in all_users:
            last_online = user.get('last_online')
            if min_days == -1 and last_online is None:
                inactive.append(user)
                continue
            if last_online:
                days_since_online = (now_utc - last_online.astimezone(pytz.utc)).days
                if min_days <= days_since_online < max_days:
                    inactive.append(user)
        return inactive

    def add_user(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        new_user_raw = self._request("POST", "/user/", json=data)
        if new_user_raw and new_user_raw.get('uuid'):
            return self.user_info(new_user_raw['uuid'])
        logger.error(f"Failed to add user. Data: {data}, Response: {new_user_raw}")
        return None

    def modify_user(self, uuid: str, data: dict = None, add_usage_gb: float = 0, add_days: int = 0) -> bool:
        """
        کاربر را ویرایش می‌کند. می‌تواند یک دیکشنری خام از داده‌ها را بپذیرد
        یا مقادیر جدید را بر اساس اطلاعات فعلی کاربر محاسبه کند.
        """
        # اگر داده خام ارسال شده باشد (برای موارد قدیمی مانند ریست مصرف)
        if data:
            return self._request("PATCH", f"/user/{uuid}/", json=data) is not None

        payload = {}
        
        # اگر نیاز به محاسبه مقادیر جدید باشد (برای هدیه تولد و ویرایش ادمین)
        if add_usage_gb or add_days:
            current_info = self.user_info(uuid)
            if not current_info:
                logger.error(f"Cannot modify user {uuid}: Could not fetch current info.")
                return False

            # محاسبه و افزودن حجم جدید
            if add_usage_gb:
                current_limit_gb = current_info.get("usage_limit_GB", 0)
                payload["usage_limit_GB"] = current_limit_gb + add_usage_gb

            # محاسبه و افزودن روزهای جدید
            if add_days:
                current_expire_days = current_info.get("expire", 0)
                # اگر اکانت منقضی شده باشد، از امروز محاسبه کن
                if current_expire_days < 0:
                    current_expire_days = 0
                payload["package_days"] = current_expire_days + add_days
        
        if not payload:
            return True # کاری برای انجام دادن نیست
        
        # ارسال درخواست به API
        return self._request("PATCH", f"/user/{uuid}/", json=payload) is not None

    def delete_user(self, uuid: str) -> bool:
        return self._request("DELETE", f"/user/{uuid}/") is True

    def reset_user_usage(self, uuid: str) -> bool:
        return self.modify_user(uuid, {"current_usage_GB": 0})

api_handler = HiddifyAPIHandler()