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
from app.tool.base import ToolResult


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
    """A flow that manages planning and execution of tasks using agents."""

    llm: LLM = Field(default_factory=lambda: LLM())
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)
    executor_keys: List[str] = Field(default_factory=list)
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")
    current_step_index: Optional[int] = None

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
        """Execute the planning flow with agents using the Manus iterative agent loop."""
        try:
            if not self.primary_agent:
                raise ValueError("No primary agent available")

            result = ""
            # If there's input text, update existing plan or create a new one
            if input_text:
                if self.active_plan_id in self.planning_tool.plans:
                    # Update existing plan
                    result += await self._update_plan_from_message(input_text)
                else:
                    # Create new plan
                    await self._create_initial_plan(input_text)
                    # Check creation success
                    if self.active_plan_id not in self.planning_tool.plans:
                        logger.error(
                            f"Plan creation failed. Plan ID {self.active_plan_id} not found in planning tool."
                        )
                        return f"Failed to create plan for: {input_text}"
                    result += await self._get_plan_text()

            # Manus Iterative Agent Loop
            # Instead of executing all steps at once, we'll execute one step per iteration
            # and then decide whether to continue based on the results

            # 1. ANALYZE: Get the current state and identify next step
            self.current_step_index, step_info = await self._get_current_step_info()

            # Exit if no more steps or plan completed
            if self.current_step_index is None:
                result += await self._finalize_plan()
                return result

            # 2. PLAN: Determine how to execute the current step
            step_type = step_info.get("type") if step_info else None
            executor = self.get_executor(step_type)

            # Get step content and prepare context
            step_content = step_info.get("content", "Unknown step")
            logger.info(f"Executing step {self.current_step_index + 1}: {step_content}")

            # Update step status to in_progress
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=self.current_step_index,
                step_status="in_progress",
            )

            # 3. EXECUTE: Execute the step with the appropriate agent
            step_result = await self._execute_step(executor, step_info)
            result += f"Step {self.current_step_index + 1} result:\n{step_result}\n"

            # 4. OBSERVE: Evaluate the step result and update plan accordingly
            step_success = await self._evaluate_step_result(step_result)

            if step_success:
                # Mark step as completed
                await self._mark_step_completed()
                logger.info(
                    f"Step {self.current_step_index + 1} completed successfully"
                )
            else:
                # Mark step as blocked if execution failed
                await self.planning_tool.execute(
                    command="mark_step",
                    plan_id=self.active_plan_id,
                    step_index=self.current_step_index,
                    step_status="blocked",
                    step_notes=f"Execution failed: {step_result[:100]}...",
                )
                logger.warning(f"Step {self.current_step_index + 1} execution failed")

            # Return the current plan status
            result += await self._get_plan_text()
            return result

        except Exception as e:
            logger.error(f"Error in PlanningFlow: {str(e)}")
            return f"Execution failed: {str(e)}"

    async def _evaluate_step_result(self, step_result: str) -> bool:
        """
        Evaluate the result of a step execution to determine if it was successful.
        This method can be extended to implement more sophisticated evaluation.

        Args:
            step_result: The result string from step execution

        Returns:
            bool: True if the step was successful, False otherwise
        """
        # Simple implementation - consider the step successful unless it contains explicit failure indicators
        failure_indicators = [
            "error:",
            "failed:",
            "exception:",
            "could not",
            "unable to",
            "execution failed",
            "terminated with code",
            "critical failure",
        ]

        # Check for failure indicators (case-insensitive)
        step_result_lower = step_result.lower()
        for indicator in failure_indicators:
            if indicator in step_result_lower:
                return False

        return True

    async def _create_initial_plan(self, request: str) -> None:
        """
        Create an initial plan based on the request using the flow's LLM and PlanningTool.
        Generates a structured plan with detailed steps following the Manus architecture.
        """
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        # Create a system message with specific planning instructions
        system_message = Message.system_message(
            """
You are a planning assistant responsible for breaking down complex tasks into clear, achievable steps.
Your plans should follow these principles:

1. Break tasks into 3-7 concrete, actionable steps
2. Each step should produce a clear output or state change
3. Steps should be sequential and dependent on previous steps
4. Include enough detail for execution without being too granular
5. Ensure steps are measurable and have clear completion criteria

For technical tasks:
- Start with information gathering/analysis steps
- Include validation/testing steps
- End with summarization or result delivery steps

Format steps as imperative statements ("Analyze data", not "Data will be analyzed").
"""
        )

        # Create a user message with the request
        user_message = Message.user_message(
            f"Create a clear, actionable plan with sequential steps to accomplish this task: {request}"
        )

        # Call LLM with PlanningTool
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
        )

        # Process tool calls if present
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    # Parse the arguments
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse tool arguments: {args}")
                            continue

                    # Ensure plan_id is set correctly and execute the tool
                    args["plan_id"] = self.active_plan_id

                    # Make sure the title is not too long
                    if "title" in args and len(args["title"]) > 100:
                        args["title"] = args["title"][:97] + "..."

                    # Add plan description if not present
                    if "title" in args and "steps" in args:
                        # Execute the tool via ToolCollection instead of directly
                        result = await self.planning_tool.execute(**args)
                        logger.info(f"Plan creation result: {str(result)}")
                        return

        # If no valid tool call was processed, create a default plan with basic steps
        logger.warning("No valid planning tool calls found, creating default plan")

        # Create a simplified title from the request
        title = f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}"

        # Create default steps for any task
        default_steps = [
            "Analyze and understand the requirements",
            "Research needed information and gather resources",
            "Create implementation plan with specific deliverables",
            "Execute the implementation",
            "Test and validate results",
            "Summarize findings and deliver results",
        ]

        # Create default plan
        await self.planning_tool.execute(
            command="create",
            plan_id=self.active_plan_id,
            title=title,
            steps=default_steps,
        )

    async def _update_plan_from_message(self, message: str) -> str:
        """
        Update existing plan based on a new user message.

        This method allows users to modify plans by adding steps, changing existing steps,
        or providing additional context/requirements.
        """
        logger.info(
            f"Updating plan {self.active_plan_id} based on new message: {message}"
        )

        # Get the current plan for context
        current_plan = await self._get_plan_text()

        # Prepare system message with specific update instructions
        system_message = Message.system_message(
            """
You are a planning assistant responsible for updating existing plans based on new user input.
You should maintain the overall structure of the plan while incorporating the user's feedback.

When updating a plan:
1. Keep completed steps unchanged when possible
2. Add new steps where necessary
3. Modify future steps to accommodate new requirements
4. Break down complex steps into smaller ones if needed
5. Ensure all steps remain concrete and actionable

Respond by making the appropriate changes to the plan structure.
"""
        )

        # Create user message with context and new input
        user_message = Message.user_message(
            f"""
Current plan:
{current_plan}

User wants to update this plan with the following:
{message}

Please update the plan appropriately.
"""
        )

        # Call LLM with PlanningTool for plan updates
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
        )

        # Process tool calls if present
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    # Parse the arguments
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse arguments: {args}")
                            continue

                    # Ensure plan_id is set correctly
                    args["plan_id"] = self.active_plan_id

                    # Execute the planning tool with the parsed arguments
                    result: ToolResult = await self.planning_tool.execute(**args)
                    logger.info(f"Plan update result: {result.output}")

                    # Return the updated plan text
                    return result.output

        # If no valid tool calls were processed, return the current plan with a note
        logger.warning("No valid planning tool calls returned, keeping current plan.")
        return f"No updates made to plan. Current plan:\n\n{current_plan}"

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """
        Parse the current plan to identify the first non-completed step's index and info.
        Returns (None, None) if no active step is found.
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"Plan with ID {self.active_plan_id} not found")
            return None, None

        try:
            # Direct access to plan data from planning tool storage
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])

            # Find first non-completed step
            for i, step in enumerate(steps):
                if i >= len(step_statuses):
                    status = PlanStepStatus.NOT_STARTED.value
                else:
                    status = step_statuses[i]

                if status in PlanStepStatus.get_active_statuses():
                    # Extract step type/category if available
                    step_info = {"text": step}

                    # Try to extract step type from the text (e.g., [SEARCH] or [CODE])
                    import re

                    type_match = re.search(r"\[([A-Z_]+)\]", step)
                    if type_match:
                        step_info["type"] = type_match.group(1).lower()

                    # Mark current step as in_progress
                    try:
                        await self.planning_tool.execute(
                            command="mark_step",
                            plan_id=self.active_plan_id,
                            step_index=i,
                            step_status=PlanStepStatus.IN_PROGRESS.value,
                        )
                    except Exception as e:
                        logger.warning(f"Error marking step as in_progress: {e}")
                        # Update step status directly if needed
                        if i < len(step_statuses):
                            step_statuses[i] = PlanStepStatus.IN_PROGRESS.value
                        else:
                            while len(step_statuses) < i:
                                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                            step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                        plan_data["step_statuses"] = step_statuses

                    return i, step_info

            return None, None  # No active step found

        except Exception as e:
            logger.warning(f"Error finding current step index: {e}")
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """
        Execute a single step of the plan using the specified agent.

        Args:
            executor: The agent that will execute the step
            step_info: Information about the step to execute

        Returns:
            str: The result of the step execution
        """
        if not step_info:
            return "No step information provided"

        # Extract step content and step number
        step_content = step_info.get("content", "")
        step_index = self.current_step_index

        # Get the full plan context for the agent
        plan_context = self._generate_plan_text_from_storage()

        # Create a context message that includes:
        # 1. The current plan status and progress
        # 2. The specific step being executed
        # 3. Any relevant information from previous steps

        context_message = (
            f"You are currently executing a plan with the following information:\n\n"
            f"{plan_context}\n\n"
            f"CURRENT TASK: Execute Step {step_index + 1}: {step_content}\n\n"
            "You should complete this specific step only, not the entire plan. "
            "Focus on producing a concrete, actionable result for this step. "
            "If you need more information, specify what's missing."
        )

        try:
            # Execute the step with the constructed context
            step_result = await executor.run(context_message)

            # Format the step result
            formatted_result = (
                f"Step {step_index + 1} completed.\n\n" f"Result:\n{step_result}\n\n"
            )

            # Add notes if needed
            notes = f"Executed by {executor.__class__.__name__}"
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=step_index,
                step_notes=notes,
            )

            return formatted_result

        except Exception as e:
            error_message = f"Step {step_index + 1} execution failed: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _mark_step_completed(self) -> None:
        """Mark the current step as completed."""
        if self.current_step_index is None:
            return

        try:
            # Mark the step as completed
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=self.current_step_index,
                step_status=PlanStepStatus.COMPLETED.value,
            )
            logger.info(
                f"Marked step {self.current_step_index} as completed in plan {self.active_plan_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to update plan status: {e}")
            # Update step status directly in planning tool storage
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])

                # Ensure the step_statuses list is long enough
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)

                # Update the status
                step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                plan_data["step_statuses"] = step_statuses

    async def _get_plan_text(self) -> str:
        """Get the current plan as formatted text."""
        try:
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            logger.error(f"Error getting plan: {e}")
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """Generate plan text directly from storage if the planning tool fails."""
        try:
            if self.active_plan_id not in self.planning_tool.plans:
                return f"Error: Plan with ID {self.active_plan_id} not found"

            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "Untitled Plan")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])

            # Ensure step_statuses and step_notes match the number of steps
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
            while len(step_notes) < len(steps):
                step_notes.append("")

            # Count steps by status
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
                # Use status marks to indicate step status
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]
                )

                plan_text += f"{i}. {status_mark} {step}\n"
                if notes:
                    plan_text += f"   Notes: {notes}\n"

            return plan_text
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

    async def _finalize_plan(self) -> str:
        """
        Generate a final summary of the completed plan.
        This method is called when all steps are completed or when execution terminates.

        Returns:
            str: A summary of the plan execution including results and outcomes
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            return "Plan not found or invalid."

        plan_data = self.planning_tool.plans[self.active_plan_id]
        title = plan_data.get("title", "Untitled Plan")
        steps = plan_data.get("steps", [])
        statuses = plan_data.get("step_statuses", [])
        notes = plan_data.get("step_notes", [])

        # Calculate plan completion statistics
        total_steps = len(steps)
        completed_steps = statuses.count("completed")
        blocked_steps = statuses.count("blocked")
        success_rate = (completed_steps / total_steps * 100) if total_steps > 0 else 0

        # Generate a formatted summary
        summary = f"# Plan Summary: {title}\n\n"

        # Add completion status
        if completed_steps == total_steps:
            summary += "## ✅ Plan Completed Successfully\n\n"
        elif blocked_steps > 0:
            summary += f"## ⚠️ Plan Partially Completed ({success_rate:.1f}%)\n\n"
        else:
            summary += f"## ℹ️ Plan Execution Status: {success_rate:.1f}% Complete\n\n"

        # Add statistics
        summary += f"- Total Steps: {total_steps}\n"
        summary += f"- Completed Steps: {completed_steps}\n"
        summary += f"- Blocked Steps: {blocked_steps}\n"
        summary += f"- Success Rate: {success_rate:.1f}%\n\n"

        # Add step details
        summary += "## Step Details\n\n"

        for i, (step, status, note) in enumerate(zip(steps, statuses, notes)):
            status_icon = {
                "completed": "✓",
                "in_progress": "→",
                "blocked": "⚠",
                "not_started": "○",
            }.get(status, "○")

            summary += f"### Step {i+1}: [{status_icon}] {step}\n"
            summary += f"**Status**: {status.capitalize()}\n"

            if note:
                summary += f"**Notes**: {note}\n"

            summary += "\n"

        # Write summary to a file
        try:
            workspace = config.workspace_root
            summary_path = workspace / "plan_summary.md"
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(summary)

            # Add reference to the summary file
            summary += f"\nDetailed summary saved to: {summary_path}\n"
        except Exception as e:
            logger.error(f"Failed to write plan summary: {e}")

        return summary
