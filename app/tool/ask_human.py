# app/tool/ask_human.py
from typing import Literal

from app.tool.base import BaseTool, ToolResult


class HumanInterventionRequired(Exception):
    """
    Custom exception to signal that human input is needed during agent/tool execution.
    Carries the question and tool_call_id for context.
    """

    def __init__(self, question: str, tool_call_id: str):
        self.question = question
        self.tool_call_id = tool_call_id
        super().__init__(question)


class AskHuman(BaseTool):
    """
    A tool that allows the agent to pause execution and ask the human user for input,
    clarification, or a decision when blocked or needing guidance.
    Always raises HumanInterventionRequired, which should be caught by the flow/agent.
    """

    name: str = "ask_human"
    description: str = (
        "Asks the human user for input, clarification, or a decision. "
        "Use this when you are blocked (e.g., after 2-3 failed attempts on a step), need information you cannot find, "
        "or require a decision that only the user can make (e.g., ambiguous instructions, choice between options). "
        "Formulate a clear and specific question for the user."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "description": "The specific question to ask the human user.",
                "type": "string",
            }
        },
        "required": ["question"],
    }

    async def execute(self, *, question: str, **kwargs) -> ToolResult:
        """
        Always signals that human intervention is required by raising HumanInterventionRequired.
        The flow/agent should catch this exception and handle the user interaction.
        """
        raise HumanInterventionRequired(question=question, tool_call_id="UNKNOWN")
