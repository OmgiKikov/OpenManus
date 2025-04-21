import sys
from datetime import datetime
from typing import Dict, Optional

from loguru import logger as _logger

from app.config import PROJECT_ROOT


class TaskLogger:
    def __init__(self):
        self._logger = _logger
        self._print_level = "INFO"
        self._task_logs_queue: Optional[Dict] = None
        self._current_task_id: Optional[str] = None

    def set_task_context(self, task_id: str, logs_queue: Dict):
        """Set the current task context for logging"""
        self._task_logs_queue = logs_queue
        self._current_task_id = task_id

    def clear_task_context(self):
        """Clear the current task context"""
        self._task_logs_queue = None
        self._current_task_id = None

    def get_task_id(self) -> Optional[str]:
        """Get the current task ID from the context"""
        return self._current_task_id

    def _task_sink(self, message):
        """Custom sink to add logs to task queue"""
        if self._task_logs_queue is not None and self._current_task_id is not None:
            record = message.record
            log_entry = {
                "timestamp": record["time"].timestamp(),
                "level": record["level"].name,
                "message": record["message"],
            }
            self._task_logs_queue[self._current_task_id].append(log_entry)

    def setup(self, print_level="INFO", logfile_level="DEBUG", name: str = None):
        """Setup logger with appropriate configuration"""
        self._print_level = print_level

        current_date = datetime.now()
        formatted_date = current_date.strftime("%Y%m%d%H%M%S")
        log_name = f"{name}_{formatted_date}" if name else formatted_date

        self._logger.remove()
        self._logger.add(sys.stderr, level=print_level)
        self._logger.add(PROJECT_ROOT / f"logs/{log_name}.log", level=logfile_level)
        self._logger.add(self._task_sink, level=print_level)

    def info(self, message):
        self._logger.info(message)

    def debug(self, message):
        self._logger.debug(message)

    def warning(self, message):
        self._logger.warning(message)

    def error(self, message):
        self._logger.error(message)

    def critical(self, message):
        self._logger.critical(message)

    def exception(self, message):
        self._logger.exception(message)


# Create a global instance
logger = TaskLogger()
logger.setup()  # Setup with default configuration

if __name__ == "__main__":
    logger.info("Starting application")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")

    try:
        raise ValueError("Test error")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
