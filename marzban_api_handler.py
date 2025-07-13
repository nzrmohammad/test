import requests
import logging
from config import MARZBAN_API_BASE_URL, MARZBAN_API_USERNAME, MARZBAN_API_PASSWORD, API_TIMEOUT

logger = logging.getLogger(__name__)

class MarzbanAPIHandler:
    def __init__(self):
        self.base_url = MARZBAN_API_BASE_URL
        self.username = MARZBAN_API_USERNAME
        self.password = MARZBAN_API_PASSWORD
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        """Fetches the access token from Marzban panel."""
        try:
            url = f"{self.base_url}/api/admin/token"
            data = {"username": self.username, "password": self.password}
            response = requests.post(url, data=data, timeout=API_TIMEOUT)
            response.raise_for_status()
            return response.json().get("access_token")
        except requests.exceptions.RequestException as e:
            logger.error(f"Marzban: Failed to get access token: {e}")
            return None

    def get_user_info(self, uuid: str) -> dict | None:
        """Fetches user info from Marzban using their UUID as username."""
        if not self.access_token:
            return None
        try:
            # In Marzban, the user's config name is often the UUID.
            # We assume the 'username' in Marzban is the user's UUID.
            url = f"{self.base_url}/api/user/{uuid}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

            if response.status_code == 404:
                logger.warning(f"Marzban: User with UUID {uuid} not found.")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # Convert bytes to GB
            usage_gb = data.get('used_traffic', 0) / (1024 ** 3)
            limit_gb = data.get('data_limit', 0) / (1024 ** 3)
            
            return {
                "current_usage_GB": usage_gb,
                "usage_limit_GB": limit_gb,
                "is_active": data.get('status') == 'active'
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Marzban: Failed to get user info for {uuid}: {e}")
            # If token expired, try to refresh it once
            if "Token has expired" in str(e):
                self.access_token = self._get_access_token()
                return self.get_user_info(uuid) # Retry
            return None

marzban_handler = MarzbanAPIHandler()