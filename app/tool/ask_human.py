import asyncio
import inspect

from app.human_queue import human_queue
from app.logger import logger
from app.tool import BaseTool


class AskHuman(BaseTool):
    """Add a tool to ask human for help."""

    name: str = "ask_human"
    description: str = "Use this tool to ask human for help."
    parameters: str = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question you want to ask human.",
            }
        },
        "required": ["inquire"],
    }

    async def execute(self, inquire: str) -> str:
        # Get the current task_id from the logger context
        task_id = logger._current_task_id
        if not task_id:
            # Fallback to direct input if no task context (e.g. during testing)
            return input(f"""Bot: {inquire}\n\nYou: """).strip()

        # Log the question so it appears in the chat
        logger.info(f"[ASK_HUMAN] {inquire}")

        # Add the question to the queue and get a future for the response
        future = human_queue.add_question(task_id, inquire)

        # Wait for the response
        try:
            # Wait for the human to respond
            response = await future
            return response.strip()
        except asyncio.CancelledError:
            # Handle cancellation (e.g., if the task is interrupted)
            logger.warning("Human question was cancelled before receiving a response")
            return "Question was cancelled"
