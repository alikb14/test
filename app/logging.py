from __future__ import annotations

import logging
from pathlib import Path

# Import our structured logger
from app.utils.logger import logger as structured_logger

# Keep the standard logger for compatibility
logger = logging.getLogger("rasid.bot")


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging for the application.
    
    This is a compatibility layer that uses our structured logger internally.
    """
    # Set up basic logging to console
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    
    # Log the logging system initialization
    structured_logger.log("Logging system initialized", log_level=level)
