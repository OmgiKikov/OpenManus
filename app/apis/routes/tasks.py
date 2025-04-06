import asyncio
from json import dumps
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse

from app.agent.manus import Manus
from app.apis.services.task_manager import task_manager
from app.config import LLMSettings
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState
from app.tool.ask_human import HumanInterventionRequired

router = APIRouter(prefix="/tasks", tags=["tasks"])

AGENT_NAME = "Manus"

# Определяем константу для сигнализации о взаимодействии с человеком
# Это согласуется с тем, что используется в app/flow/planning.py
HUMAN_INTERACTION_SIGNAL = "__HUMAN_INTERACTION_OCCURRED__"


async def handle_agent_event(task_id: str, event_name: str, step: int, **kwargs):
    """Handle agent events and update task status.

    Args:
        event_name: Name of the event
        **kwargs: Additional parameters related to the event
    """
    if not task_id:
        logger.warning(f"No task_id provided for event: {event_name}")
        return

    # Update task step
    await task_manager.update_task_progress(
        task_id=task_id, event_name=event_name, step=step, **kwargs
    )


async def run_task(task_id: str, language: Optional[str] = None):
    """Run the task and set up corresponding event handlers.

    Args:
        task_id: Task ID
        prompt: Task prompt
        llm_config: Optional LLM configuration
    """
    try:
        task = task_manager.tasks[task_id]
        agent = task.agent

        # Вместо вызова initialize, установим атрибуты напрямую, т.к. в классе Manus нет такого метода
        if language:
            # Если нужно установить язык, можно это сделать через атрибуты
            agent.task_id = task_id
        else:
            agent.task_id = task_id

        # Set up event handlers based on all event types defined in the Agent class hierarchy
        event_patterns = [r"agent:.*"]
        # Register handlers for each event pattern
        for pattern in event_patterns:
            # Создаем асинхронную вспомогательную функцию, чтобы корректно вызывать await
            async def event_handler_wrapper(event_name, step, **kwargs):
                await handle_agent_event(
                    task_id=task_id,
                    event_name=event_name,
                    step=step,
                    **kwargs,
                )

            agent.on(pattern, event_handler_wrapper)

        try:
            # Run the agent
            await agent.run(task.prompt)
        except HumanInterventionRequired as hir:
            # Catch the exception raised by AskHuman (and re-raised by the agent)
            logger.info(f"Agent requested human input for tool_call_id: {hir.tool_call_id}")
            logger.info(f"Question: {hir.question}")

            # Добавляем прерванное сообщение инструмента, как в оригинальной системе
            interrupted_tool_content = f"Tool execution interrupted to ask user: {hir.question}"
            agent.update_memory(
                role="tool",
                content=interrupted_tool_content,
                tool_call_id=hir.tool_call_id,
                name="ask_human"
            )
            logger.info(f"Added interrupted tool result message to agent memory for ID {hir.tool_call_id}.")

            # Создадим событие, чтобы фронтенд знал о запросе
            if hasattr(agent, "emit"):
                agent.emit(
                    "agent:tool:ask_human",
                    agent.current_step,
                    query=hir.question,
                    interaction_id=hir.tool_call_id
                )

            # Задача будет продолжена, когда пользователь ответит через API endpoint

        # Ensure all events have been processed
        queue = task_manager.queues[task_id]
        while not queue.empty():
            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Error in task {task_id}: {str(e)}")


async def event_generator(task_id: str):
    if task_id not in task_manager.queues:
        yield f"event: error\ndata: {dumps({'message': 'Task not found'})}\n\n"
        return

    queue = task_manager.queues[task_id]

    while True:
        try:
            event = await queue.get()
            formatted_event = dumps(event)

            # Send actual event data
            if event.get("type"):
                yield f"data: {formatted_event}\n\n"

                # Проверяем, закончилось ли выполнение задачи
                if event.get("event_name") == Manus.Events.LIFECYCLE_COMPLETE:
                    logger.info(f"Task {task_id} completed, closing event stream")
                    break

                # Выводим информацию о событии для отладки
                logger.debug(f"Event sent to client: {event}")

            # Send heartbeat
            yield ":heartbeat\n\n"

        except asyncio.CancelledError:
            logger.info(f"Client disconnected for task {task_id}")
            break
        except Exception as e:
            logger.error(f"Error in event stream: {str(e)}")
            yield f"event: error\ndata: {dumps({'message': str(e)})}\n\n"
            break


@router.post("")
async def create_task(
    task_id: str = Body(..., embed=True),
    prompt: str = Body(..., embed=True),
    preferences: Optional[dict] = Body(None, embed=True),
    llm_config: Optional[LLMSettings] = Body(None, embed=True),
):
    task = task_manager.create_task(
        task_id,
        prompt,
        Manus(
            name=AGENT_NAME,
            description="A versatile agent that can solve various tasks using multiple tools",
            llm=(
                LLM(config_name=task_id, llm_config=llm_config) if llm_config else None
            ),
            enable_event_queue=True,  # Enable event queue
        ),
    )
    asyncio.create_task(
        run_task(
            task.id,
            language=preferences.get("language", "English") if preferences else None,
        )
    )
    return {"task_id": task.id}


@router.get("/{organization_id}/{task_id}/events")
async def task_events(organization_id: str, task_id: str):
    return StreamingResponse(
        event_generator(f"{organization_id}/{task_id}"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("")
async def get_tasks():
    sorted_tasks = sorted(
        task_manager.tasks.values(), key=lambda task: task.created_at, reverse=True
    )
    return JSONResponse(
        content=[task.model_dump() for task in sorted_tasks],
        headers={"Content-Type": "application/json"},
    )


@router.post("/{organization_id}/{task_id}/tool/ask_human/respond")
async def respond_to_ask_human(
    organization_id: str,
    task_id: str,
    interaction_id: str = Body(..., embed=True),
    response: str = Body(..., embed=True),
):
    """Endpoint to handle responses to ask_human tool requests.

    Args:
        organization_id: The organization ID
        task_id: The task ID
        interaction_id: The interaction ID (tool_call_id)
        response: The user's response
    """
    full_task_id = f"{organization_id}/{task_id}"
    try:
        if full_task_id not in task_manager.tasks:
            return JSONResponse(
                status_code=404,
                content={"message": f"Task {full_task_id} not found"},
            )

        task = task_manager.tasks[full_task_id]
        agent = task.agent

        # Получаем последнее сообщение с вопросом, чтобы включить его в ответ
        question = None
        for msg in reversed(agent.messages):
            if msg.role == "tool" and msg.name == "ask_human" and msg.tool_call_id == interaction_id:
                # Извлекаем вопрос из сообщения tool
                import re
                match = re.search(r"Tool execution interrupted to ask user: (.*)", msg.content)
                if match:
                    question = match.group(1)
                break

        # Если не нашли вопрос, используем общую формулировку
        if not question:
            question = "your question"

        # Добавляем ответ пользователя - в точности как в оригинальной системе
        response_content = f'Regarding your question "{question}": {response}'
        agent.update_memory(role="user", content=response_content)

        # Emit an event for logging
        if hasattr(agent, "emit"):
            agent.emit(
                "agent:message",
                agent.current_step,
                content=response_content,
                role="user",
                human_response=True,
            )

        logger.info(f"User response injected into agent memory for task {full_task_id}")

        # Создаем новую задачу для продолжения работы агента
        asyncio.create_task(continue_agent_execution(agent, full_task_id))

        return JSONResponse(content={"status": "success"})
    except Exception as e:
        logger.error(f"Error processing response for task {full_task_id}: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"Error: {str(e)}"},
        )


async def continue_agent_execution(agent, task_id):
    """Continue agent execution after receiving user response."""
    try:
        logger.info(f"Continuing agent execution for task {task_id} after human response")

        # Сохраняем текущее состояние и шаг
        original_state = agent.state
        remaining_steps = agent.max_steps - agent.current_step

        # Если у нас осталось слишком мало шагов, увеличим лимит
        if remaining_steps < 3:
            logger.warning(f"Too few steps remaining ({remaining_steps}), extending max_steps")
            agent.max_steps += 10
            remaining_steps = agent.max_steps - agent.current_step

        logger.info(f"Continuing execution with up to {remaining_steps} remaining steps")

        # Выполняем цикл, используя тот же паттерн, что и метод run()
        results = []

        # Переводим агента в состояние RUNNING с помощью контекстного менеджера
        async with agent.state_context(AgentState.RUNNING):
            while (agent.current_step < agent.max_steps and
                   agent.state != AgentState.FINISHED):
                # Увеличиваем счетчик шагов
                agent.current_step += 1

                # Выполняем очередной шаг
                logger.info(f"Executing continuation step {agent.current_step}/{agent.max_steps}")
                try:
                    step_result = await agent.step()
                    logger.info(f"Step completed with result: {step_result[:50]}..." if len(str(step_result)) > 50 else step_result)

                    # Проверяем, не застрял ли агент
                    if agent.is_stuck():
                        agent.handle_stuck_state()

                    results.append(f"Step {agent.current_step}: {step_result}")

                except HumanInterventionRequired as hir:
                    # Обработка запроса на взаимодействие с пользователем
                    logger.info(f"Agent requested human input: {hir.question}")

                    # Добавляем прерванное сообщение инструмента
                    interrupted_tool_content = f"Tool execution interrupted to ask user: {hir.question}"
                    agent.update_memory(
                        role="tool",
                        content=interrupted_tool_content,
                        tool_call_id=hir.tool_call_id,
                        name="ask_human"
                    )

                    # Отправляем событие интерфейсу
                    if hasattr(agent, "emit"):
                        agent.emit(
                            "agent:tool:ask_human",
                            agent.current_step,
                            query=hir.question,
                            interaction_id=hir.tool_call_id
                        )
                    # Выходим из цикла, чтобы дождаться ответа пользователя
                    break

                except Exception as e:
                    error_msg = f"Error in step {agent.current_step}: {str(e)}"
                    logger.error(error_msg)
                    results.append(f"Step {agent.current_step}: {error_msg}")

            # Проверяем, достигнут ли максимум шагов
            if agent.current_step >= agent.max_steps:
                logger.warning(f"Reached maximum steps ({agent.max_steps})")
                agent.state = AgentState.IDLE  # Сброс состояния, как в BaseAgent.run()
                if hasattr(agent, "emit"):
                    agent.emit(
                        "agent:lifecycle:complete",
                        agent.current_step,
                        result="Task completed: reached maximum steps"
                    )

        # Если агент завершил задачу, отправляем событие о завершении
        if agent.state == AgentState.FINISHED and hasattr(agent, "emit"):
            agent.emit(
                "agent:lifecycle:complete",
                agent.current_step,
                result="Task completed successfully"
            )

        # Убедимся, что все события обработаны
        queue = task_manager.queues[task_id]
        await asyncio.sleep(0.1)  # Небольшая пауза для обработки событий
        while not queue.empty():
            await asyncio.sleep(0.1)

        # Возвращаем агента в исходное состояние, если выполнение не было завершено
        if agent.state != AgentState.FINISHED and agent.state != original_state:
            agent.state = original_state

    except Exception as e:
        logger.error(f"Error in continue_agent_execution for {task_id}: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
