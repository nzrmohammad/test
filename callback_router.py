# callback_router.py

from telebot import types, telebot
from config import ADMIN_IDS
from admin_handlers import handle_admin_callbacks
from user_handlers import handle_user_callbacks

def register_callback_router(bot: telebot.TeleBot):

    @bot.callback_query_handler(func=lambda _: True)
    def main_callback_router(call: types.CallbackQuery):
        """Routes all callback queries to the appropriate handler."""
        uid = call.from_user.id
        data = call.data
        is_admin = uid in ADMIN_IDS
        
        # Always answer the callback query to remove the "loading" state on the user's side
        bot.answer_callback_query(call.id)

        if is_admin and (data.startswith("admin_") or data.startswith("broadcast_target_")):
            handle_admin_callbacks(call)
        else:
            handle_user_callbacks(call)