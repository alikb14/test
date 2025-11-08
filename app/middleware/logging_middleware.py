from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.utils.logger import logger

class LoggingMiddleware(BaseMiddleware):
    """Middleware to log all bot interactions and state changes."""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Skip logging if it's not a message or callback query
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # Extract the originating Update if available
        update: Update | None = data.get("event_update")
        update_id = getattr(event, "update_id", None)
        if update_id is None and update is not None:
            update_id = getattr(update, "update_id", None)

        # Get user and chat info
        user = data.get("event_from_user")
        chat = event.chat if hasattr(event, 'chat') else None
        
        # Get current state
        state: FSMContext = data.get("state")
        from_state = await state.get_state() if state else None
        
        # Log the incoming update
        update_type = "message" if isinstance(event, Message) else "callback_query"
        update_data = {
            "update_id": update_id,
            "update_type": update_type,
            "user_id": user.id if user else None,
            "chat_id": chat.id if chat else None,
            "from_state": from_state,
        }
        
        if isinstance(event, Message):
            update_data.update({
                "message_id": event.message_id,
                "text": event.text,
                "content_type": event.content_type,
            })
        elif isinstance(event, CallbackQuery):
            update_data.update({
                "callback_data": event.data,
                "message_id": event.message.message_id if event.message else None,
            })
        
        logger.debug("Processing update", **{"update": update_data})
        
        try:
            # Process the update
            result = await handler(event, data)
            
            # Log state change if it happened
            if state:
                to_state = await state.get_state()
                if to_state != from_state:
                    logger.log_state_change(
                        user_id=user.id if user else None,
                        from_state=from_state,
                        to_state=to_state,
                        update_id=update_id,
                        handler=handler.__name__,
                    )
            
            return result
            
        except Exception as e:
            # Log any errors that occur during handling
            logger.error(
                f"Error in {handler.__name__}",
                exception=e,
                user_id=user.id if user else None,
                from_state=from_state,
                update=update_data,
            )
            raise
