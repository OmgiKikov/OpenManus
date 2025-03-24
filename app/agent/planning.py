import time
from typing import Dict, List, Optional, Any

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.planning import NEXT_STEP_PROMPT, PLANNING_SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, Message, ToolCall, ToolChoice
from app.tool import PlanningTool, Terminate, ToolCollection


class PlanningAgent(ToolCallAgent):
    """
    An agent that creates and manages plans to solve tasks.

    This agent uses a planning tool to create and manage structured plans,
    and tracks progress through individual steps until task completion.
    It implements a Manus-style planning approach with step-by-step execution
    and dynamic plan adaptation.
    """

    name: str = "planning"
    description: str = "An agent that creates and manages plans to solve tasks"

    system_prompt: str = PLANNING_SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(PlanningTool(), Terminate())
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    tool_calls: List[ToolCall] = Field(default_factory=list)
    active_plan_id: Optional[str] = Field(default=None)

    # Add a dictionary to track the step status for each tool call
    step_execution_tracker: Dict[str, Dict] = Field(default_factory=dict)
    current_step_index: Optional[int] = None

    # Track the overall task progress
    task_status: Dict[str, Any] = Field(default_factory=lambda: {
        "started_at": None,
        "last_updated": None,
        "completion_percentage": 0,
        "completed_steps": 0,
        "total_steps": 0,
        "status": "not_started"
    })

    max_steps: int = 30  # Increased from 20 to allow for more complex tasks

    @model_validator(mode="after")
    def initialize_plan_and_verify_tools(self) -> "PlanningAgent":
        """Initialize the agent with a default plan ID and validate required tools."""
        self.active_plan_id = f"plan_{int(time.time())}"
        self.task_status["started_at"] = time.time()
        self.task_status["status"] = "initializing"

        if "planning" not in self.available_tools.tool_map:
            self.available_tools.add_tool(PlanningTool())

        return self

    async def act(self) -> str:
        """Execute a step and track its completion status."""
        # Update task status before acting
        self.task_status["last_updated"] = time.time()
        if self.task_status["status"] == "initializing":
            self.task_status["status"] = "in_progress"

        # Execute the action
        result = await super().act()

        # After executing the tool, update the plan status
        if self.tool_calls:
            latest_tool_call = self.tool_calls[0]

            # Update the execution status to completed
            if latest_tool_call.id in self.step_execution_tracker:
                self.step_execution_tracker[latest_tool_call.id]["status"] = "completed"
                self.step_execution_tracker[latest_tool_call.id]["result"] = result

                # Update the plan status if this was a non-planning, non-special tool
                if (
                    latest_tool_call.function.name != "planning"
                    and latest_tool_call.function.name not in self.special_tool_names
                ):
                    await self.update_plan_status(latest_tool_call.id)

                    # Проверяем, стоит ли пропустить оставшиеся шаги
                    await self.check_if_can_skip_steps(result)

            # Check if the terminate tool was called
            if latest_tool_call.function.name == "finish":
                self.task_status["status"] = "completed"
                self.task_status["completion_percentage"] = 100
                logger.info("Task completed. Agent terminated.")

        # Update task completion percentage
        await self._update_task_progress()

        return result

    async def get_plan(self) -> str:
        """Retrieve the current plan status."""
        if not self.active_plan_id:
            return "No active plan. Please create a plan first."

        result = await self.available_tools.execute(
            name="planning",
            tool_input={"command": "get", "plan_id": self.active_plan_id},
        )
        return result.output if hasattr(result, "output") else str(result)

    async def run(self, request: Optional[str] = None) -> str:
        """Run the agent with an optional initial request."""
        if request:
            # Create a new plan for the request
            await self.create_initial_plan(request)

        return await super().run()

    async def think(self) -> Optional[ToolCall]:
        """
        Think about the next action to take.

        Enhanced to prioritize plan-oriented thinking and to maintain focus on the
        current step in the plan.
        """
        # Get the current plan state
        plan_state = await self.get_plan()

        # Add the plan state to the messages for context
        plan_context = Message.system_message(
            f"Current Plan Status:\n{plan_state}\n\nUse this plan to guide your next action."
        )

        # Add the next step prompt to guide thinking
        next_step_guidance = Message.system_message(self.next_step_prompt)

        # Get the messages for thinking
        messages = self.memory.get_messages()

        # Make the tool call with the enhanced context
        response = await self.llm.ask_tool(
            messages=messages,
            system_msgs=[plan_context, next_step_guidance],
            tools=self.available_tools.to_params(),
            tool_choice=self.tool_choices,
        )

        # Process and return the tool call
        if not response.tool_calls:
            return None

        return response.tool_calls[0]

    async def update_plan_status(self, tool_call_id: str) -> None:
        """Update the plan status based on a completed tool call."""
        if tool_call_id not in self.step_execution_tracker:
            return

        tracker_info = self.step_execution_tracker[tool_call_id]
        step_index = tracker_info.get("step_index")

        if step_index is not None:
            # Mark the step as completed
            await self.available_tools.execute(
                name="planning",
                tool_input={
                    "command": "mark_step",
                    "plan_id": self.active_plan_id,
                    "step_index": step_index,
                    "step_status": "completed",
                    "step_notes": f"Completed at {time.strftime('%Y-%m-%d %H:%M:%S')}",
                },
            )

            # Find the next incomplete step and mark it as in_progress
            await self._mark_next_step_in_progress(step_index + 1)

    async def _mark_next_step_in_progress(self, start_index: int = 0) -> None:
        """Mark the next incomplete step as in_progress."""
        if not self.active_plan_id:
            return

        # Get the current plan
        result = await self.available_tools.execute(
            name="planning",
            tool_input={"command": "get", "plan_id": self.active_plan_id},
        )

        if not hasattr(result, "output"):
            return

        # Parse the plan to find the next incomplete step
        plan_steps = self._parse_plan_output(result.output)
        if not plan_steps:
            return

        # Find the first step that's not completed, starting from start_index
        next_step_index = None
        for i in range(start_index, len(plan_steps)):
            if plan_steps[i]["status"] != "completed":
                next_step_index = i
                break

        # If there's a next step, mark it as in_progress
        if next_step_index is not None:
            self.current_step_index = next_step_index
            await self.available_tools.execute(
                name="planning",
                tool_input={
                    "command": "mark_step",
                    "plan_id": self.active_plan_id,
                    "step_index": next_step_index,
                    "step_status": "in_progress",
                },
            )

            # Log the transition to the next step
            logger.info(f"Moving to step {next_step_index}: {plan_steps[next_step_index]['description']}")

    def _parse_plan_output(self, plan_output: str) -> List[Dict]:
        """Parse the plan output to extract step information."""
        steps = []
        lines = plan_output.split("\n")
        step_lines = []

        # Find the "Steps:" section
        for i, line in enumerate(lines):
            if line.strip() == "Steps:":
                step_lines = lines[i + 1 :]
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

    async def create_initial_plan(self, request: str) -> None:
        """Create an initial plan based on the request."""
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        messages = [
            Message.user_message(
                f"Analyze the following request thoroughly and create a comprehensive, well-structured plan with ID {self.active_plan_id}: {request}"
            )
        ]
        self.memory.add_messages(messages)
        response = await self.llm.ask_tool(
            messages=messages,
            system_msgs=[Message.system_message(self.system_prompt)],
            tools=self.available_tools.to_params(),
            tool_choice=ToolChoice.AUTO,
        )
        assistant_msg = Message.from_tool_calls(
            content=response.content, tool_calls=response.tool_calls
        )

        self.memory.add_message(assistant_msg)

        plan_created = False
        for tool_call in response.tool_calls:
            if tool_call.function.name == "planning":
                result = await self.execute_tool(tool_call)
                logger.info(
                    f"Executed tool {tool_call.function.name} with result: {result}"
                )

                # Add tool response to memory
                tool_msg = Message.tool_message(
                    content=result,
                    tool_call_id=tool_call.id,
                    name=tool_call.function.name,
                )
                self.memory.add_message(tool_msg)
                plan_created = True

                # Initialize task tracking
                self.task_status["status"] = "plan_created"

                # Mark the first step as in_progress
                await self._mark_next_step_in_progress()
                break

        if not plan_created:
            logger.warning("No plan created from initial request")
            tool_msg = Message.assistant_message(
                "Error: Parameter `plan_id` is required for command: create"
            )
            self.memory.add_message(tool_msg)

    async def _update_task_progress(self) -> None:
        """Update the task progress statistics based on the current plan."""
        if not self.active_plan_id:
            return

        # Get the current plan
        result = await self.available_tools.execute(
            name="planning",
            tool_input={"command": "get", "plan_id": self.active_plan_id},
        )

        if not hasattr(result, "output"):
            return

        # Parse the plan to count completed steps
        plan_steps = self._parse_plan_output(result.output)
        if not plan_steps:
            return

        # Count completed steps
        completed_steps = sum(1 for step in plan_steps if step["status"] == "completed")
        total_steps = len(plan_steps)

        # Update task status
        self.task_status["completed_steps"] = completed_steps
        self.task_status["total_steps"] = total_steps
        self.task_status["completion_percentage"] = (completed_steps / total_steps * 100) if total_steps > 0 else 0

        logger.info(f"Task progress: {completed_steps}/{total_steps} steps completed ({self.task_status['completion_percentage']:.1f}%)")

    async def check_if_can_skip_steps(self, result: str) -> None:
        """
        Использует интеллектуальный анализ для определения, можно ли пропустить оставшиеся шаги плана.
        Если основная цель задачи уже достигнута, остальные шаги помечаются как выполненные.

        Args:
            result: Результат выполнения текущего шага
        """
        if not self.active_plan_id:
            return

        # Получаем текущий план
        plan_status = await self.get_plan()

        # Анализируем план
        steps = self._parse_plan_output(plan_status)

        # Если шагов не осталось или остался только один, нет нужды в проверке
        remaining_steps = sum(1 for step in steps if step["status"] != "completed")
        if remaining_steps <= 1:
            return

        # Извлекаем информацию о выполненных и невыполненных шагах
        completed_steps = [step for step in steps if step["status"] == "completed"]
        incomplete_steps = [step for step in steps if step["status"] != "completed"]

        # Подготавливаем системное сообщение для LLM
        system_message = Message.system_message(
            "Ты эксперт по анализу выполнения задач. Твоя задача - определить, достигнута ли основная цель, "
            "даже если формально не все шаги плана выполнены. Учитывай следующие факторы:\n"
            "1. Основная цель задачи важнее, чем выполнение каждого отдельного шага\n"
            "2. Если последний выполненный шаг дал нам всю необходимую информацию, остальные шаги могут быть избыточными\n"
            "3. Некоторые шаги могли быть запланированы как запасной вариант или для проверки\n"
            "Отвечай только 'YES' если основная цель полностью достигнута и шаги можно пропустить, "
            "или 'NO' если необходимо продолжить выполнение плана."
        )

        # Подготавливаем пользовательское сообщение
        user_message = Message.user_message(
            f"Текущий план выполнения задачи:\n\n{plan_status}\n\n"
            f"Выполненные шаги: {len(completed_steps)}/{len(steps)}\n"
            f"Результат последнего выполненного шага:\n\n{result}\n\n"
            f"Оставшиеся невыполненные шаги:\n" +
            "\n".join([f"- {step['description']}" for step in incomplete_steps]) +
            "\n\nНа основе результата последнего шага, была ли достигнута основная цель задачи? "
            "Можно ли пропустить оставшиеся шаги? Отвечай только 'YES' или 'NO'."
        )

        # Запрашиваем оценку у LLM
        response = await self.llm.ask(
            messages=[user_message],
            system_msgs=[system_message]
        )

        response_text = response.content if hasattr(response, 'content') else str(response)

        # Анализируем ответ
        if response_text.strip().upper().startswith("YES"):
            logger.info("Агент определил, что основная цель достигнута и оставшиеся шаги можно пропустить")

            # Запрашиваем обоснование
            reason_message = Message.user_message(
                "Объясни, почему мы можем пропустить оставшиеся шаги? "
                "Что именно в результате указывает на то, что цель уже достигнута?"
            )

            reason_response = await self.llm.ask(
                messages=[user_message, Message.assistant_message(response_text), reason_message],
                system_msgs=[system_message]
            )

            skip_reason = reason_response.content if hasattr(reason_response, 'content') else str(reason_response)

            # Помечаем все оставшиеся шаги как выполненные
            for step in steps:
                if step["status"] != "completed":
                    await self.available_tools.execute(
                        name="planning",
                        tool_input={
                            "command": "mark_step",
                            "plan_id": self.active_plan_id,
                            "step_index": step["index"],
                            "step_status": "completed",
                            "step_notes": f"Пропущено: {skip_reason[:100]}..."
                        }
                    )

            # Обновляем статус задачи
            self.task_status["status"] = "completed"
            self.task_status["completion_percentage"] = 100
            logger.info(f"Все оставшиеся шаги пропущены: {skip_reason[:200]}...")


async def main():
    # Configure and run the agent
    agent = PlanningAgent(available_tools=ToolCollection(PlanningTool(), Terminate()))
    result = await agent.run("Help me plan a trip to the moon")
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
