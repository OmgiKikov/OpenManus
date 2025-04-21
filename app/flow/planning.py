import json
import time
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import Field

from app.agent.base import BaseAgent
from app.config import config
from app.flow.base import BaseFlow
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice
from app.tool import PlanningTool
from app.tool.ask_human import AskHuman
from app.tool.base import ToolResult

# Специальный сигнал для human-in-the-loop
HUMAN_INTERACTION_SIGNAL = "__HUMAN_INTERACTION_OCCURRED__"


class PlanStepStatus(str, Enum):
    """Enum class defining possible statuses of a plan step"""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """Return a list of all possible step status values"""
        return [status.value for status in cls]

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """Return a list of values representing active statuses (not started or in progress)"""
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """Return a mapping of statuses to their marker symbols"""
        return {
            cls.COMPLETED.value: "[✓]",
            cls.IN_PROGRESS.value: "[→]",
            cls.BLOCKED.value: "[!]",
            cls.NOT_STARTED.value: "[ ]",
        }


class PlanningFlow(BaseFlow):
    """
    Production-ready flow for planning and executing complex tasks with agents, LLM, and human-in-the-loop.
    Implements best practices for Manus.AI: retry, human-in-the-loop, tool-based planning, robust logging, and summary.
    """

    llm: LLM = Field(default_factory=lambda: LLM())
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)
    executor_keys: List[str] = Field(default_factory=list)
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")
    current_step_index: Optional[int] = None
    max_retries_per_step: int = 3

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        # Set executor keys before super().__init__
        if "executors" in data:
            data["executor_keys"] = data.pop("executors")

        # Set plan ID if provided
        if "plan_id" in data:
            data["active_plan_id"] = data.pop("plan_id")

        # Initialize the planning tool if not provided
        if "planning_tool" not in data:
            planning_tool = PlanningTool()
            data["planning_tool"] = planning_tool

        # Call parent's init with the processed data
        super().__init__(agents, **data)

        # Set executor_keys to all agent keys if not specified
        if not self.executor_keys:
            self.executor_keys = list(self.agents.keys())

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """
        Get an appropriate executor agent for the current step.
        Can be extended to select agents based on step type/requirements.
        """
        # If step type is provided and matches an agent key, use that agent
        if step_type and step_type in self.agents:
            return self.agents[step_type]

        # Otherwise use the first available executor or fall back to primary agent
        for key in self.executor_keys:
            if key in self.agents:
                return self.agents[key]

        # Fallback to primary agent
        return self.primary_agent

    async def execute(self, input_text: str) -> str:
        """
        Main execution loop: creates plan, executes steps with retry/human-in-the-loop, finalizes with LLM summary.
        """
        try:
            if not self.primary_agent:
                raise ValueError("No primary agent available")
            result = ""
            if input_text:
                await self._create_initial_plan(input_text)
                if self.active_plan_id not in self.planning_tool.plans:
                    logger.error(
                        f"Plan creation failed. Plan ID {self.active_plan_id} not found in planning tool."
                    )
                    return f"Failed to create plan for: {input_text}"
            current_step_retries = 0
            last_step_index = -1
            while True:
                self.current_step_index, step_info = await self._get_current_step_info()
                if self.current_step_index != last_step_index:
                    current_step_retries = 0
                    last_step_index = self.current_step_index
                else:
                    current_step_retries += 1
                if self.current_step_index is None:
                    result += await self._finalize_plan()
                    break
                if current_step_retries >= self.max_retries_per_step:
                    logger.error(
                        f"Maximum retries ({self.max_retries_per_step}) exceeded for step {self.current_step_index}. Aborting."
                    )
                    await self._mark_step_status(
                        PlanStepStatus.BLOCKED.value, "Max retries exceeded"
                    )
                    result += (
                        "\nExecution aborted: Maximum retries exceeded for a step."
                    )
                    break
                step_type = step_info.get("type") if step_info else None
                executor = self.get_executor(step_type)
                logger.info(
                    f"Executing step {self.current_step_index} (Retry: {current_step_retries})"
                )
                step_result = await self._execute_step(executor, step_info)
                if step_result == HUMAN_INTERACTION_SIGNAL:
                    logger.info(
                        f"Human interaction occurred for step {self.current_step_index}. Retrying step."
                    )
                    continue
                result += step_result + "\n"
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:
                    logger.warning(
                        f"Executor {executor.name} entered FINISHED state. Stopping flow."
                    )
                    break
            return result
        except Exception as e:
            logger.error(f"Error in PlanningFlow: {str(e)}")
            return f"Execution failed: {str(e)}"

    async def _create_initial_plan(self, request: str) -> None:
        """
        Create an initial plan using LLM and PlanningTool. Only tool call is accepted. Strict system prompt.
        """
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")
        system_message = Message.system_message(
            """
You are an expert planning assistant. Your goal is to create a detailed, step-by-step plan to accomplish a given task using available tools.
<planning_approach>
1.  **Decomposition:** Break down the main task into smaller, logically ordered, actionable steps. Each step should represent a clear, manageable unit of work. Avoid overly broad or vague steps.
2.  **Tool Awareness (Implicit):** Although you don't need to specify exact tool calls in the plan, formulate steps in a way that they likely correspond to actions achievable with tools like web search, browsing, code execution, or file manipulation. (For example, "Search for reviews of product X", "Extract key features from webpage Y", "Write a Python script to analyze data Z").
3.  **Clarity and Order:** Ensure the steps are in a logical sequence. The output of one step might be needed for the next.
4.  **Completeness:** The plan should cover all necessary stages from start to finish to fully address the user's request.
5.  **Conciseness:** While detailed, avoid unnecessary verbosity in step descriptions.
</planning_approach>
<output_format>
- You MUST call the 'planning' tool to submit the generated plan.
- Provide the plan as a list of strings in the 'steps' parameter of the tool call.
- Provide a concise 'title' for the plan.
</output_format>
Analyze the user's request carefully and generate the plan by calling the 'planning' tool.
"""
        )
        user_message = Message.user_message(
            f"Create a detailed, step-by-step plan to accomplish the task: {request}"
        )
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
            temperature=0.2,
        )
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse tool arguments: {args}")
                            continue
                    args["plan_id"] = self.active_plan_id
                    await self.planning_tool.execute(**args)
                    logger.info(f"Plan creation result: {args}")
                    return
        logger.warning("Creating default plan")
        await self.planning_tool.execute(
            command="create",
            plan_id=self.active_plan_id,
            title=f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
            steps=["Analyze request", "Execute task", "Verify results"],
        )

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """
        Returns index and info of the first non-completed step. None if all done.
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"Plan with ID {self.active_plan_id} not found")
            return None, None
        try:
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            for i, step in enumerate(steps):
                status = (
                    step_statuses[i]
                    if i < len(step_statuses)
                    else PlanStepStatus.NOT_STARTED.value
                )
                if status in PlanStepStatus.get_active_statuses():
                    step_info = {"text": step}
                    import re

                    type_match = re.search(r"\[([A-Z_]+)\]", step)
                    if type_match:
                        step_info["type"] = type_match.group(1).lower()
                    await self._mark_step_status(PlanStepStatus.IN_PROGRESS.value)
                    return i, step_info
            return None, None
        except Exception as e:
            logger.warning(f"Error finding current step index: {e}")
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """
        Execute the current step with the specified agent. Handles human-in-the-loop and all errors.
        """
        plan_status = await self._get_plan_text()
        step_text = step_info.get("text", f"Step {self.current_step_index}")
        step_prompt = f"""
CURRENT PLAN STATUS:
{plan_status}

YOUR CURRENT TASK:
You are now working on step {self.current_step_index}: \"{step_text}\"

YOUR OBJECTIVE:
1. Execute the current step using the appropriate tools.
2. **Analyze recent messages (especially user responses).** If information from the user indicates that any **FUTURE** steps in the plan (check CURRENT PLAN STATUS) are already completed or irrelevant, you MUST use the 'planning' tool to update their status BEFORE proceeding with the current step's main action.
   - Use command 'mark_step' with the correct 'step_index' for each future step that needs updating.
   - Set 'status' to 'completed' or 'blocked'.
   - Add a brief explanation in 'step_notes' (e.g., 'User confirmed completion', 'Made irrelevant by user input').
3. If you get stuck on the current step (e.g., after 2-3 failed attempts), need information you cannot find, or require a user decision, use the 'ask_human' tool.
4. When you are finished with this step (either successfully, by updating future steps, or by asking the human), provide a summary of what you accomplished or why you need help.
"""
        try:
            step_result_str = await executor.run(step_prompt)
            await self._mark_step_status(PlanStepStatus.COMPLETED.value)
            return step_result_str
        except Exception as e:
            # Human-in-the-loop: если агент вызывает AskHuman через input или исключение
            if "ask_human" in str(e).lower() or isinstance(e, KeyboardInterrupt):
                logger.info(
                    f"Agent requested human input for step {self.current_step_index}"
                )
                try:
                    user_response = input(
                        f'\n🤖 Agent needs help with step {self.current_step_index} ("{step_text}"):\n   Question: {str(e)}\n👤 Your answer: '
                    )
                except EOFError:
                    logger.warning("EOF received, assuming no input.")
                    user_response = "(No input provided)"
                executor.update_memory(
                    role="user", content=f"Regarding your question: {user_response}"
                )
                logger.info("User response injected into agent memory.")
                return HUMAN_INTERACTION_SIGNAL
            logger.error(
                f"Unexpected error during agent execution for step {self.current_step_index}: {e}"
            )
            await self._mark_step_status(
                PlanStepStatus.BLOCKED.value, f"Agent execution error: {str(e)}"
            )
            return f"Error during agent execution for step {self.current_step_index}: {str(e)}"

    async def _mark_step_status(self, status: str, notes: Optional[str] = None) -> None:
        """
        Universal function to mark the current step with any status and optional notes.
        """
        if self.current_step_index is None:
            return
        try:
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=self.current_step_index,
                step_status=status,
                step_notes=notes,
            )
            logger.info(
                f"Marked step {self.current_step_index} as {status} in plan {self.active_plan_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to update plan status to {status}: {e}")
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])
                step_notes_list = plan_data.get("step_notes", [])
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                while len(step_notes_list) <= self.current_step_index:
                    step_notes_list.append("")
                step_statuses[self.current_step_index] = status
                if notes:
                    step_notes_list[self.current_step_index] = notes
                plan_data["step_statuses"] = step_statuses
                plan_data["step_notes"] = step_notes_list

    async def _get_plan_text(self) -> str:
        """
        Get the current plan as formatted markdown and save to todo.md.
        """
        try:
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            # Сохраняем в todo.md
            if hasattr(result, "output"):
                self.planning_tool._write_todo_file(result.output)
                return result.output
            else:
                return str(result)
        except Exception as e:
            logger.error(f"Error getting plan: {e}")
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """
        Fallback: generate plan text directly from storage if the planning tool fails.
        """
        try:
            if self.active_plan_id not in self.planning_tool.plans:
                return f"Error: Plan with ID {self.active_plan_id} not found"
            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "Untitled Plan")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
            while len(step_notes) < len(steps):
                step_notes.append("")
            status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}
            for status in step_statuses:
                if status in status_counts:
                    status_counts[status] += 1
            completed = status_counts[PlanStepStatus.COMPLETED.value]
            total = len(steps)
            progress = (completed / total) * 100 if total > 0 else 0
            plan_text = f"Plan: {title} (ID: {self.active_plan_id})\n"
            plan_text += "=" * len(plan_text) + "\n\n"
            plan_text += (
                f"Progress: {completed}/{total} steps completed ({progress:.1f}%)\n"
            )
            plan_text += f"Status: {status_counts[PlanStepStatus.COMPLETED.value]} completed, {status_counts[PlanStepStatus.IN_PROGRESS.value]} in progress, "
            plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} blocked, {status_counts[PlanStepStatus.NOT_STARTED.value]} not started\n\n"
            plan_text += "Steps:\n"
            status_marks = PlanStepStatus.get_status_marks()
            for i, (step, status, notes) in enumerate(
                zip(steps, step_statuses, step_notes)
            ):
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]
                )
                plan_text += f"{i}. {status_mark} {step}\n"
                if notes:
                    plan_text += f"   Notes: {notes}\n"
            self.planning_tool._write_todo_file(plan_text)
            return plan_text
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

    async def _finalize_plan(self) -> str:
        """
        Finalize the plan and provide a summary using the flow's LLM directly. Also saves summary to todo.md.
        """
        plan_text = await self._get_plan_text()
        try:
            system_message = Message.system_message(
                "You are a planning assistant. Your task is to summarize the completed plan."
            )
            user_message = Message.user_message(
                f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
            )
            response = await self.llm.ask(
                messages=[user_message], system_msgs=[system_message]
            )
            summary = f"Plan completed:\n\n{response}"
            self.planning_tool._write_todo_file(plan_text + "\n\n" + summary)
            return summary
        except Exception as e:
            logger.error(f"Error finalizing plan with LLM: {e}")
            self.planning_tool._write_todo_file(plan_text)
            return "Plan completed. Error generating summary."
