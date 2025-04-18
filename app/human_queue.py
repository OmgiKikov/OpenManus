import asyncio
from typing import Dict, Optional


class HumanQueue:
    """Queue for managing questions to humans and their responses.

    This queue manages the communication flow between the agent asking questions
    and humans providing answers through the UI.
    """

    def __init__(self):
        # Map task_id -> question_future
        self.pending_questions: Dict[str, asyncio.Future] = {}
        # Map task_id -> latest question
        self.current_questions: Dict[str, str] = {}

    def add_question(self, task_id: str, question: str) -> asyncio.Future:
        """Add a question to the queue and return a future that will be resolved with the answer.

        Args:
            task_id: The ID of the current task/conversation
            question: The question being asked to the human

        Returns:
            A future that will be resolved when the human provides an answer
        """
        # Cancel any existing questions for this task
        if task_id in self.pending_questions:
            old_future = self.pending_questions[task_id]
            if not old_future.done():
                old_future.cancel()

        # Create a new future bound to the current running loop
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_questions[task_id] = future
        self.current_questions[task_id] = question

        return future

    def add_response(self, task_id: str, response: str) -> bool:
        """Add a human response to a pending question.

        Args:
            task_id: The ID of the task/conversation
            response: The human's response to the question

        Returns:
            True if the response was successfully added, False otherwise
        """
        if task_id not in self.pending_questions:
            return False

        future = self.pending_questions[task_id]
        if future.done():
            return False

        # Resolve the future in a thread‑safe manner using its loop
        loop = future.get_loop()
        loop.call_soon_threadsafe(future.set_result, response)
        return True

    def get_current_question(self, task_id: str) -> Optional[str]:
        """Get the current question for a given task.

        Args:
            task_id: The ID of the task/conversation

        Returns:
            The current question if one exists, None otherwise
        """
        return self.current_questions.get(task_id)

    def has_pending_question(self, task_id: str) -> bool:
        """Check if a task has a pending question.

        Args:
            task_id: The ID of the task/conversation

        Returns:
            True if there is a pending question, False otherwise
        """
        if task_id not in self.pending_questions:
            return False

        future = self.pending_questions[task_id]
        return not future.done()

# Global instance to be used by the application
human_queue = HumanQueue()
