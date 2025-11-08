import json
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Callable, TypeVar, cast
from functools import wraps

T = TypeVar('T', bound=Callable[..., Any])

class StructuredLogger:
    def __init__(self, log_dir: str = "logs"):
        """
        Initialize the structured logger.
        
        Args:
            log_dir: Base directory for storing logs (both logs and errors)
        """
        self.base_dir = Path(log_dir)
        self.current_year = str(datetime.now().year)
        self.current_month = f"{datetime.now().month:02d}"
        self._ensure_directories_exist()

    def _ensure_directories_exist(self) -> None:
        """Ensure that the required log directories exist."""
        self.current_month_dir = self.base_dir / self.current_year / self.current_month
        self.current_month_dir.mkdir(parents=True, exist_ok=True)

    def _check_date_changed(self) -> None:
        """Check if the date has changed and update directories if needed."""
        now = datetime.now()
        current_year = str(now.year)
        current_month = f"{now.month:02d}"
        
        if current_year != self.current_year or current_month != self.current_month:
            self.current_year = current_year
            self.current_month = current_month
            self._ensure_directories_exist()

    def _write_log(self, data: Dict[str, Any], log_type: str = "log") -> None:
        """Write log entry to the appropriate file with pretty-printed JSON."""
        try:
            self._check_date_changed()
            
            # Add timestamp if not present
            if "timestamp" not in data:
                data["timestamp"] = datetime.now().isoformat()
            
            # Format the JSON with proper indentation
            formatted_json = json.dumps(
                data, 
                ensure_ascii=False, 
                indent=2, 
                sort_keys=True,
                default=str  # Handle datetime serialization
            )
            
            # Write to appropriate file
            filename = "logs.json" if log_type == "log" else "errors.json"
            log_file = self.current_month_dir / filename
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted_json + "\n\n")
                
        except Exception as e:
            print(f"Failed to write log: {e}")

    # ===== Core Logging Methods =====
    
    def log(self, message: str, **kwargs: Any) -> None:
        """Log a general message with INFO level."""
        self._write_log({"level": "INFO", "message": message, **kwargs}, "log")

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message."""
        self._write_log({"level": "DEBUG", "message": message, **kwargs}, "log")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an informational message."""
        self._write_log({"level": "INFO", "message": message, **kwargs}, "log")

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message."""
        self._write_log({"level": "WARNING", "message": message, **kwargs}, "log")

    def error(self, message: str, exception: Optional[Exception] = None, **kwargs: Any) -> None:
        """Log an error message with optional exception details."""
        error_data = {
            "level": "ERROR",
            "message": message,
            **kwargs
        }
        
        if exception is not None:
            error_data.update({
                "exception_type": exception.__class__.__name__,
                "exception_message": str(exception),
                "exception_traceback": self._get_traceback(exception)
            })
        
        self._write_log(error_data, "error")

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log a critical error message."""
        self._write_log({"level": "CRITICAL", "message": message, **kwargs}, "error")

    # ===== Specialized Logging Methods =====
    
    def log_auth(self, event: str, user_id: int, **kwargs: Any) -> None:
        """Log authentication-related events."""
        self._write_log({
            "event_type": "authentication",
            "event": event,
            "user_id": user_id,
            **kwargs
        }, "log")

    def log_state_change(self, user_id: int, from_state: str, to_state: str, **kwargs: Any) -> None:
        """Log state machine transitions."""
        self._write_log({
            "event_type": "state_change",
            "user_id": user_id,
            "from_state": from_state,
            "to_state": to_state,
            **kwargs
        }, "log")

    def log_card_operation(self, operation: str, card_id: int, user_id: int | None, **kwargs: Any) -> None:
        """Log card-related operations."""
        self._write_log({
            "event_type": "card_operation",
            "operation": operation,
            "card_id": card_id,
            "user_id": user_id,
            **kwargs
        }, "log")

    def log_admin_action(self, action: str, admin_id: int, target_type: str, **kwargs: Any) -> None:
        """Log administrative actions."""
        self._write_log({
            "event_type": "admin_action",
            "action": action,
            "admin_id": admin_id,
            "target_type": target_type,
            **kwargs
        }, "log")

    def log_api_call(self, endpoint: str, method: str, status_code: int, **kwargs: Any) -> None:
        """Log API interactions."""
        self._write_log({
            "event_type": "api_call",
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            **kwargs
        }, "log")

    # ===== Helper Methods =====
    
    def _get_traceback(self, exception: Exception) -> str:
        """Get formatted traceback from exception."""
        import traceback
        return ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    
    def log_exception(self, exception: Exception, context: str = "", **kwargs: Any) -> None:
        """Log an exception with context."""
        self.error(
            f"{context}: {str(exception)}" if context else str(exception),
            exception=exception,
            **kwargs
        )
    
    def log_deprecated(self, feature: str, alternative: str = "", **kwargs: Any) -> None:
        """Log usage of a deprecated feature."""
        message = f"Deprecated feature used: {feature}"
        if alternative:
            message += f", please use {alternative} instead"
        
        # Get the caller's information
        frame = inspect.currentframe().f_back
        caller_info = ""
        if frame:
            try:
                caller_info = f" at {frame.f_code.co_filename}:{frame.f_lineno}"
            finally:
                del frame
        
        self.warning(message, deprecation_notice=True, caller=caller_info, **kwargs)

    # ===== Decorators =====
    
    def log_function_call(self, func: T) -> T:
        """Decorator to log function calls with arguments and return values."""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            func_name = func.__name__
            try:
                self.debug(
                    f"Calling {func_name}",
                    function=func_name,
                    args=args,
                    kwargs=kwargs
                )
                result = await func(*args, **kwargs)
                self.debug(
                    f"Function {func_name} completed successfully",
                    function=func_name,
                    result=result
                )
                return result
            except Exception as e:
                self.error(
                    f"Error in {func_name}",
                    function=func_name,
                    error=str(e),
                    exc_info=True
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            func_name = func.__name__
            try:
                self.debug(
                    f"Calling {func_name}",
                    function=func_name,
                    args=args,
                    kwargs=kwargs
                )
                result = func(*args, **kwargs)
                self.debug(
                    f"Function {func_name} completed successfully",
                    function=func_name,
                    result=result
                )
                return result
            except Exception as e:
                self.error(
                    f"Error in {func_name}",
                    function=func_name,
                    error=str(e),
                    exc_info=True
                )
                raise
        
        return cast(T, async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper)


# Create a singleton instance
logger = StructuredLogger()
