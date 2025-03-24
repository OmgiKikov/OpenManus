import json
import time
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import Field

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice
from app.tool import PlanningTool


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
        """Execute the planning flow with agents."""
        try:
            if not self.primary_agent:
                raise ValueError("No primary agent available")

            # Use the enhanced Manus-style planning approach
            return await self.plan_actions(input_text)

        except Exception as e:
            logger.error(f"Error in PlanningFlow: {str(e)}")
            return f"Execution failed: {str(e)}"

    async def _create_initial_plan(self, request: str) -> None:
        """Create an initial plan based on the request using the flow's LLM and PlanningTool."""
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        # Create a system message for plan creation
        system_message = Message.system_message(
            "You are a planning assistant specialized in creating structured, actionable plans. "
            "Break complex tasks into  clear, manageable steps with specific outcomes. "
            "Include verification steps where appropriate and consider dependencies between steps. "
            "Focus on creating a comprehensive plan that addresses all aspects of the request. "
            "Each step should have a clear objective and completion criteria."
        )

        # Create a user message with the request
        user_message = Message.user_message(
            f"Thoroughly analyze this request and create a detailed plan with ID {self.active_plan_id}:\n\n{request}\n\n"
            f"Consider all aspects of the task, potential challenges, and verification needs."
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

                    # Execute the tool via ToolCollection instead of directly
                    result = await self.planning_tool.execute(**args)

                    logger.info(f"Plan creation result: {str(result)}")

                    # Mark the first step as in_progress
                    await self._mark_first_step_in_progress()
                    return

        # If execution reached here, create a default plan
        logger.warning("Creating default plan")

        # Create default plan using the ToolCollection
        await self.planning_tool.execute(
            **{
                "command": "create",
                "plan_id": self.active_plan_id,
                "title": f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
                "steps": [
                    "Analyze request thoroughly",
                    "Research necessary information",
                    "Develop initial approach",
                    "Execute core task elements",
                    "Verify results and quality",
                    "Finalize and document outcomes"
                ],
            }
        )

        # Mark the first step as in_progress
        await self._mark_first_step_in_progress()

    async def _mark_first_step_in_progress(self):
        """Mark the first step of the plan as in progress."""
        try:
            await self.planning_tool.execute(
                **{
                    "command": "mark_step",
                    "plan_id": self.active_plan_id,
                    "step_index": 0,
                    "step_status": "in_progress",
                }
            )
            self.current_step_index = 0
            logger.info("Marked first step as in progress")
        except Exception as e:
            logger.error(f"Failed to mark first step as in progress: {e}")

    async def _update_step_progress(self, step_index: int, status: str, notes: Optional[str] = None):
        """Update a step's progress status and optional notes."""
        if self.active_plan_id and step_index is not None:
            try:
                await self.planning_tool.execute(
                    **{
                        "command": "mark_step",
                        "plan_id": self.active_plan_id,
                        "step_index": step_index,
                        "step_status": status,
                        "step_notes": notes,
                    }
                )
                logger.info(f"Updated step {step_index} to status: {status}")

                # If marking a step as completed, advance to the next step
                if status == "completed":
                    await self._advance_to_next_step(step_index)
            except Exception as e:
                logger.error(f"Failed to update step {step_index}: {e}")

    async def _advance_to_next_step(self, completed_step_index: int):
        """Move to the next step after completing the current one."""
        # Get the current plan
        result = await self.planning_tool.execute(
            **{
                "command": "get",
                "plan_id": self.active_plan_id,
            }
        )

        if not hasattr(result, "output"):
            return

        # Parse the plan to find the total number of steps
        plan_output = result.output
        steps = self._parse_plan_output(plan_output)

        # If all steps are completed, we're done
        if completed_step_index >= len(steps) - 1:
            logger.info("All steps completed. Plan execution finished.")
            return

        # Mark the next step as in progress
        next_step_index = completed_step_index + 1
        await self._update_step_progress(next_step_index, "in_progress")
        self.current_step_index = next_step_index

    def _parse_plan_output(self, plan_output: str) -> List[Dict]:
        """Parse the plan output to extract step information."""
        steps = []
        lines = plan_output.split("\n")
        step_lines = []

        # Find the "Steps:" section
        for i, line in enumerate(lines):
            if line.strip() == "Steps:":
                step_lines = lines[i + 1:]
                break

        # Process the step lines
        for line in step_lines:
            line = line.strip()
            if not line or line.startswith("   Notes:"):
                continue

            # Extract step information
            parts = line.split(" ", 1)
            if len(parts) < 2 or not parts[0].rstrip(".").isdigit():
                continue

            step_index = int(parts[0].rstrip("."))
            step_text = parts[1].strip()

            # Extract status from the step text
            status = "not_started"
            if "[✓]" in step_text:
                status = "completed"
            elif "[→]" in step_text:
                status = "in_progress"
            elif "[!]" in step_text:
                status = "blocked"

            # Clean up the step description
            description = step_text.replace("[✓]", "").replace("[→]", "").replace("[!]", "").replace("[ ]", "").strip()
            if "(CURRENT)" in description:
                description = description.replace("(CURRENT)", "").strip()
                status = "in_progress"

            steps.append(
                {
                    "index": step_index,
                    "description": description,
                    "status": status,
                }
            )

        return steps

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
        """Execute the current step with the specified agent using agent.run()."""
        # Prepare context for the agent with current plan status
        plan_status = await self._get_plan_text()
        step_text = step_info.get("text", f"Step {self.current_step_index}")

        # Create a prompt for the agent to execute the current step
        step_prompt = f"""
        CURRENT PLAN STATUS:
        {plan_status}

        YOUR CURRENT TASK:
        You are now working on step {self.current_step_index}: "{step_text}"

        Please execute this step using the appropriate tools. When you're done, provide a summary of what you accomplished.
        """

        # Use agent.run() to execute the step
        try:
            step_result = await executor.run(step_prompt)

            # Mark the step as completed after successful execution
            await self._mark_step_completed()

            return step_result
        except Exception as e:
            logger.error(f"Error executing step {self.current_step_index}: {e}")
            return f"Error executing step {self.current_step_index}: {str(e)}"

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

    async def skip_unnecessary_steps(self, result: str) -> bool:
        """
        Интеллектуально определяет, можно ли пропустить оставшиеся шаги плана, если основная цель уже достигнута.
        Использует LLM для анализа результата последнего шага и оценки достижения цели.

        Args:
            result: Результат выполнения текущего шага

        Returns:
            bool: True если оставшиеся шаги можно пропустить, False в противном случае
        """
        if not self.active_plan_id:
            return False

        # Получаем текущий план
        current_plan = await self.planning_tool.execute(
            command="get",
            plan_id=self.active_plan_id
        )

        if not hasattr(current_plan, "output"):
            return False

        # Анализируем шаги плана
        steps = self._parse_plan_output(current_plan.output)
        total_steps = len(steps)
        completed_steps = [step for step in steps if step["status"] == "completed"]
        incomplete_steps = [step for step in steps if step["status"] != "completed"]

        # Если остался только 1 шаг, нет смысла пропускать его
        if len(incomplete_steps) <= 1:
            return False

        # Готовим системное сообщение
        system_message = "Ты эксперт по анализу выполнения задач. Твоя задача - определить, достигнута ли основная цель, " \
                         "даже если формально не все шаги плана выполнены. Учитывай следующие факторы:\n" \
                         "1. Основная цель задачи важнее, чем выполнение каждого отдельного шага\n" \
                         "2. Если последний выполненный шаг дал нам всю необходимую информацию, остальные шаги могут быть избыточными\n" \
                         "3. Некоторые шаги могли быть запланированы как запасной вариант или для проверки\n" \
                         "Отвечай только 'YES' если основная цель полностью достигнута и шаги можно пропустить, " \
                         "или 'NO' если необходимо продолжить выполнение плана."

        # Готовим пользовательское сообщение
        user_message = f"Текущий план выполнения задачи:\n\n{current_plan.output}\n\n" \
                       f"Выполненные шаги: {len(completed_steps)}/{total_steps}\n" \
                       f"Результат последнего выполненного шага:\n\n{result}\n\n" \
                       f"Оставшиеся невыполненные шаги:\n" + \
                       "\n".join([f"- {step['description']}" for step in incomplete_steps]) + \
                       "\n\nНа основе результата последнего шага, была ли достигнута основная цель задачи? " \
                       "Можно ли пропустить оставшиеся шаги? Отвечай только 'YES' или 'NO'."

        # Запрашиваем анализ у LLM
        messages = [Message.system_message(system_message), Message.user_message(user_message)]
        response = await self.llm.ask(messages=messages)

        response_text = response.content if hasattr(response, 'content') else str(response)

        # Анализируем ответ
        if response_text.strip().upper().startswith("YES"):
            logger.info("LLM определил, что основная цель достигнута и оставшиеся шаги можно пропустить")

            # Запрашиваем обоснование
            reason_message = "Объясни, почему мы можем пропустить оставшиеся шаги? " \
                            "Что именно в результате указывает на то, что цель уже достигнута?"

            messages.append(Message.assistant_message(response_text))
            messages.append(Message.user_message(reason_message))

            reason_response = await self.llm.ask(messages=messages)
            skip_reason = reason_response.content if hasattr(reason_response, 'content') else str(reason_response)

            # Добавляем полученное обоснование к параметрам отметки шагов
            logger.info(f"Причина пропуска шагов: {skip_reason[:200]}...")

            # Сохраняем причину для использования в mark_remaining_steps_completed
            self._skip_reason = skip_reason
            return True

        return False

    async def mark_remaining_steps_completed(self, note: str = None) -> None:
        """
        Отмечает все оставшиеся шаги как выполненные с указанной пометкой.

        Args:
            note: Пометка, почему шаги были пропущены (если None, используется сохраненная причина)
        """
        if not self.active_plan_id:
            return

        # Получаем текущий план
        result = await self.planning_tool.execute(
            command="get",
            plan_id=self.active_plan_id
        )

        if not hasattr(result, "output"):
            return

        # Анализируем шаги
        steps = self._parse_plan_output(result.output)

        # Используем сохраненную причину, если доступна и не передан явный note
        if note is None and hasattr(self, "_skip_reason"):
            note = f"Пропущено: {self._skip_reason[:100]}..."
        elif note is None:
            note = "Пропущено: основная цель задачи уже достигнута"

        # Отмечаем все незавершенные шаги как выполненные
        for step in steps:
            if step["status"] != "completed":
                await self.planning_tool.execute(
                    command="mark_step",
                    plan_id=self.active_plan_id,
                    step_index=step["index"],
                    step_status="completed",
                    step_notes=note
                )

        logger.info(f"Отмечены все оставшиеся шаги как выполненные: {note[:100]}...")

    async def plan_actions(self, request: str) -> str:
        """
        Plan and execute actions based on the given request.

        This method creates an initial plan and then executes it step by step,
        managing progress through each step until completion.
        """
        # Create a new plan
        await self._create_initial_plan(request)

        # Get current plan step info (index and step details)
        step_index, step_info = await self._get_current_step_info()

        # Log the current plan status
        plan_status = await self.planning_tool.execute(
            command="get",
            plan_id=self.active_plan_id
        )
        if hasattr(plan_status, "output"):
            logger.info(f"CURRENT PLAN STATUS:\n{plan_status.output}")

        # Set a counter to prevent infinite loops
        iterations = 0
        max_iterations = 30  # Set a reasonable limit

        # Execute plan steps until completion or we hit the iteration limit
        while step_index is not None and iterations < max_iterations:
            # Log current step progress
            current_step = step_info.get("description", "Unknown step")
            logger.info(f"Executing step {step_index}: {current_step}")

            # Choose appropriate executor for this step
            executor = self.get_executor(step_info.get("type"))

            # Format step message with context
            step_message = (
                f"Execute step {step_index}: {current_step}\n\n"
                f"This is part of a larger plan to address: {request}\n\n"
                f"Focus specifically on completing this step thoroughly before moving on."
            )

            # Execute the step with the appropriate agent
            result = await executor.run(step_message)

            # Mark the step as complete
            await self._update_step_progress(step_index, "completed",
                notes=f"Completed with result: {result[:100]}..." if len(result) > 100 else result)

            # Log the updated plan after step completion
            updated_plan = await self.planning_tool.execute(
                command="get",
                plan_id=self.active_plan_id
            )
            if hasattr(updated_plan, "output"):
                logger.info(f"PLAN AFTER STEP {step_index}:\n{updated_plan.output}")

            # Проверяем, можно ли пропустить оставшиеся шаги
            can_skip = await self.skip_unnecessary_steps(result)
            if can_skip:
                logger.info("Main objective achieved, skipping remaining steps")
                await self.mark_remaining_steps_completed()
                break

            # Get the next step (should be automatically marked as in_progress)
            step_index, step_info = await self._get_current_step_info()

            # Increment iteration counter
            iterations += 1

            # If we've completed all steps, break
            if step_index is None:
                logger.info("Plan execution completed successfully.")
                break

        # Get the final plan status
        final_plan = await self.planning_tool.execute(
            command="get",
            plan_id=self.active_plan_id,
        )

        # Return a summary of what was accomplished
        if iterations >= max_iterations:
            return f"Plan execution reached iteration limit. Current status:\n\n{final_plan.output}"
        else:
            return f"Task completed successfully. Final plan status:\n\n{final_plan.output}"

    async def run(self, request: str) -> str:
        """
        Execute the planning flow for the given request.
        """
        logger.info(f"Starting PlanningFlow with request: {request}")

        try:
            result = await self.plan_actions(request)
            return result
        except Exception as e:
            logger.error(f"Error during plan execution: {e}")
            return f"An error occurred during plan execution: {str(e)}"
