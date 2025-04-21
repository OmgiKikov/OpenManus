import asyncio
import logging
import os
import queue
import sys
import threading
import time
import uuid
from io import StringIO
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# Configure Werkzeug logger to only show WARNING and above
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# 导入OpenAgent组件
from app.agent.manus import Manus
from app.config import config
from app.flow.flow_factory import FlowFactory, FlowType
from app.human_queue import human_queue
from app.logger import logger
from app.tool.base import ToolResult

# 创建Flask应用
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# 全局变量
manus_agent = None
active_tasks = {}
task_results = {}
saved_files = {}  # 保存文件记录
task_logs_queue = {}  # 存储每个任务的日志队列


# Move add_log function definition before RealTimeStringIO class
def add_log(task_id, message, level="INFO"):
    log_entry = {"timestamp": time.time(), "level": level, "message": message}
    task_logs_queue[task_id].append(log_entry)
    # Use sys.__stdout__ to avoid recursion
    sys.__stdout__.write(f"[{level}] {message}\n")
    sys.__stdout__.flush()


# Add this custom StringIO class
class RealTimeStringIO(StringIO):
    def __init__(self, task_id, task_logs_queue, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_id = task_id
        self.task_logs_queue = task_logs_queue
        self.buffer = []

    def write(self, s):
        # Process the line in real-time
        if s.strip():
            # Determine log level from the content
            level = "INFO"
            if "[WARNING]" in s or "WARNING" in s:
                level = "WARNING"
            elif "[ERROR]" in s or "ERROR" in s:
                level = "ERROR"

            # Add to task logs without recursive printing
            log_entry = {"timestamp": time.time(), "level": level, "message": s.strip()}
            task_logs_queue[self.task_id].append(log_entry)

        # Still maintain the StringIO functionality
        return super().write(s)


# 初始化Manus
def initialize_agent():
    global manus_agent
    if manus_agent is None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info("初始化Manus Agent...")
        manus_agent = loop.run_until_complete(async_initialize_agent())
        logger.info("Manus Agent初始化完成")
    return manus_agent


async def async_initialize_agent():
    return Manus()


# 处理用户输入的异步函数
async def process_prompt(task_id, message):
    global manus_agent, task_results, saved_files, task_logs_queue
    # Import FlowFactory for planning flow
    from app.flow.flow_factory import FlowFactory, FlowType

    # 获取当前任务的 flow_type
    flow_type = active_tasks.get(task_id, {}).get("flow_type", "default")

    task_logs_queue[task_id] = []

    # Set up logging context
    logger.set_task_context(task_id, task_logs_queue)

    captured_output = RealTimeStringIO(task_id, task_logs_queue)
    captured_error = RealTimeStringIO(task_id, task_logs_queue)

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = captured_output
    sys.stderr = captured_error

    try:
        logger.info(f"开始处理任务 {task_id}...")

        # 运行处理，根据 flow_type 选择标准执行或规划流
        if flow_type == FlowType.PLANNING.value:
            # Передаём plan_id в PlanningFlow
            plan_id = active_tasks[task_id].get("plan_id")
            flow = FlowFactory.create_flow(
                flow_type=FlowType.PLANNING,
                agents={"manus": manus_agent},
                plan_id=plan_id,
            )
            result = await flow.execute(message)
        else:
            result = await manus_agent.run(message)

        # 恢复标准输出和错误
        sys.stdout = old_stdout
        sys.stderr = old_stderr

        # 保存结果
        task_results[task_id] = {
            "status": "completed",
            "result": result,
            "has_logs": True,
            "plan_id": active_tasks[task_id].get("plan_id"),
        }

        logger.info(f"任务 {task_id} 完成")

    except Exception as e:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

        error_msg = f"处理请求时发生错误: {str(e)}"
        logger.error(error_msg)

        import traceback

        traceback_str = traceback.format_exc()
        logger.error(traceback_str)

        task_results[task_id] = {
            "status": "error",
            "result": error_msg,
            "has_logs": True,
        }
    finally:
        # Clear logging context
        logger.clear_task_context()

    if task_id in active_tasks:
        del active_tasks[task_id]


# 运行异步任务的函数
def run_async_task(task_id, coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)
    loop.close()


@app.route("/api/send", methods=["POST"])
def send_message():
    # Ensure agent is initialized
    initialize_agent()

    # Get user message
    data = request.json
    message = data.get("message", "").strip()
    # Get optional flow_type, default is "default"
    flow_type = data.get("flow_type", "default").strip().lower()
    # Get optional plan_id, create new if not provided
    plan_id = data.get("plan_id") or str(uuid.uuid4())

    if not message:
        return jsonify({"status": "error", "message": "Message cannot be empty"}), 400

    # Create task ID
    task_id = str(uuid.uuid4())

    # Create task
    active_tasks[task_id] = {
        "message": message,
        "created_at": time.time(),
        "flow_type": flow_type,
        "plan_id": plan_id,
    }

    # Add info log
    logger.info(f"New task created: {task_id}, flow: {flow_type}, plan: {plan_id}")
    logger.info(f"Message: {message[:100]}{'...' if len(message) > 100 else ''}")

    # Start asynchronous processing thread
    thread = threading.Thread(
        target=run_async_task,
        args=(task_id, process_prompt(task_id, message)),
    )
    thread.start()

    return jsonify(
        {
            "status": "processing",
            "task_id": task_id,
            "plan_id": plan_id,
            "flow_type": flow_type,
        }
    )


@app.route("/api/status/<task_id>", methods=["GET"])
def check_status(task_id):
    # Проверяем, ожидает ли задача ответа от человека
    if human_queue.has_pending_question(task_id):
        return jsonify(
            {
                "status": "awaiting_human",
                "question": human_queue.get_current_question(task_id),
                "message": "Задача ожидает ответа от пользователя",
            }
        )

    # 检查任务是否完成
    if task_id in task_results:
        result = task_results[task_id]
        # 任务完成后，可以选择性地删除结果
        # del task_results[task_id]
        return jsonify(result)

    # 检查任务是否正在处理
    if task_id in active_tasks:
        return jsonify({"status": "processing", "message": "Задача обрабатывается"})

    # 任务不存在
    return jsonify({"status": "not_found", "message": "Задача не найдена"}), 404


# Endpoint to fetch the current todo plan
@app.route("/api/todo", methods=["GET"])
def get_todo():
    """
    Retrieve the current plan from todo.md with additional metadata.
    Supports query parameters:
    - plan_id: Optional specific plan ID to retrieve
    - format: Optional format (markdown or json, default: markdown)
    """
    plan_id = request.args.get("plan_id")
    output_format = request.args.get("format", "markdown").lower()

    # Default path to todo.md
    todo_path = Path(config.workspace_root) / "todo.md"

    # If we have an active PlanningTool instance available, use it to get plan data
    try:
        from app.flow.flow_factory import FlowFactory, FlowType

        flow = FlowFactory.create_flow(
            flow_type=FlowType.PLANNING, agents={"manus": manus_agent}
        )

        if hasattr(flow, "planning_tool") and flow.planning_tool:
            planning_tool = flow.planning_tool

            # If plan_id is specified, get that specific plan
            if plan_id and plan_id in planning_tool.plans:
                plan_data = planning_tool.plans[plan_id]

                if output_format == "json":
                    # Return JSON data about the plan
                    steps = plan_data.get("steps", [])
                    statuses = plan_data.get("step_statuses", [])
                    notes = plan_data.get("step_notes", [])

                    # Calculate statistics
                    total_steps = len(steps)
                    completed = statuses.count("completed") if statuses else 0
                    in_progress = statuses.count("in_progress") if statuses else 0
                    blocked = statuses.count("blocked") if statuses else 0

                    # Format step information
                    formatted_steps = []
                    for i, (step, status, note) in enumerate(
                        zip(steps, statuses, notes)
                    ):
                        formatted_steps.append(
                            {
                                "number": i + 1,
                                "text": step,
                                "status": status,
                                "notes": note,
                            }
                        )

                    return jsonify(
                        {
                            "plan_id": plan_id,
                            "title": plan_data.get("title", "Untitled Plan"),
                            "steps": formatted_steps,
                            "stats": {
                                "total": total_steps,
                                "completed": completed,
                                "in_progress": in_progress,
                                "blocked": blocked,
                                "completion_percentage": (
                                    (completed / total_steps * 100)
                                    if total_steps > 0
                                    else 0
                                ),
                            },
                        }
                    )
                else:
                    # Use the planning tool's formatter
                    formatted_plan = planning_tool._format_plan(plan_data)
                    return jsonify({"content": formatted_plan})
    except Exception as e:
        logger.error(f"Error retrieving plan data: {str(e)}")
        # Fall back to reading the file directly

    # If we couldn't get the plan via the planning tool, read the file directly
    if todo_path.exists():
        content = todo_path.read_text(encoding="utf-8")
    else:
        content = "No active plan found."

    return jsonify({"content": content})


# 获取实时日志的API端点
@app.route("/api/logs/<task_id>", methods=["GET"])
def get_logs(task_id):
    # 获取上次请求的日志索引
    last_index = request.args.get("last_index", 0)
    try:
        last_index = int(last_index)
    except ValueError:
        last_index = 0

    # 获取新日志
    if task_id in task_logs_queue:
        logs = task_logs_queue[task_id][last_index:]
        return jsonify({"logs": logs, "next_index": last_index + len(logs)})

    return jsonify({"logs": [], "next_index": last_index})


# endpoint для ответов пользователя
@app.route("/api/human_response", methods=["POST"])
def submit_human_response():
    data = request.json
    task_id = data.get("task_id")
    response = data.get("response", "").strip()

    if not task_id or not response:
        return (
            jsonify({"status": "error", "message": "ID задачи и ответ обязательны"}),
            400,
        )

    # Проверяем, есть ли активный вопрос для этой задачи
    if not human_queue.has_pending_question(task_id):
        return (
            jsonify(
                {"status": "error", "message": "Для этой задачи нет активных вопросов"}
            ),
            400,
        )

    # Добавляем ответ в очередь
    success = human_queue.add_response(task_id, response)

    if success:
        # Добавляем ответ в логи для отображения в UI
        add_log(task_id, f"[USER_RESPONSE] {response}", "INFO")

        return jsonify({"status": "success", "message": "Ответ успешно обработан"})
    else:
        return (
            jsonify({"status": "error", "message": "Не удалось обработать ответ"}),
            500,
        )


# Endpoint to execute a specific plan step
@app.route("/api/plan/execute", methods=["POST"])
def execute_plan_step():
    """
    Execute a specific step of a plan.

    Request body parameters:
    - plan_id: The ID of the plan
    - step_index: The index of the step to execute (0-based)

    Returns the task_id of the execution task.
    """
    # Ensure agent is initialized
    initialize_agent()

    # Get request data
    data = request.json
    plan_id = data.get("plan_id")
    step_index = data.get("step_index")

    # Validate input
    if not plan_id:
        return jsonify({"status": "error", "message": "plan_id is required"}), 400

    if step_index is None:
        return jsonify({"status": "error", "message": "step_index is required"}), 400

    try:
        step_index = int(step_index)
    except ValueError:
        return (
            jsonify({"status": "error", "message": "step_index must be an integer"}),
            400,
        )

    # Create instruction to execute the specific step
    instruction = f"Execute step {step_index + 1} of plan {plan_id}"

    # Create task ID
    task_id = str(uuid.uuid4())

    # Create task
    active_tasks[task_id] = {
        "message": instruction,
        "created_at": time.time(),
        "flow_type": FlowType.PLANNING.value,
        "plan_id": plan_id,
        "step_index": step_index,
    }

    # Log the execution request
    logger.info(
        f"Executing plan step: plan_id={plan_id}, step_index={step_index}, task_id={task_id}"
    )

    # Create a custom process function for step execution
    async def process_step_execution(task_id, plan_id, step_index):
        try:
            # Create a PlanningFlow instance
            flow = FlowFactory.create_flow(
                flow_type=FlowType.PLANNING,
                agents={"manus": manus_agent},
                plan_id=plan_id,
            )

            # Set up logging context
            logger.set_task_context(task_id, task_logs_queue)

            # Initialize logs queue if not already
            if task_id not in task_logs_queue:
                task_logs_queue[task_id] = []

            # Set the step index manually and execute only that step
            flow.current_step_index = step_index

            # Get the step info
            _, step_info = await flow._get_current_step_info()
            if not step_info:
                error_msg = f"Step {step_index} not found in plan {plan_id}"
                logger.error(error_msg)
                task_results[task_id] = {
                    "status": "error",
                    "result": error_msg,
                    "has_logs": True,
                }
                return

            # Execute the step
            executor = flow.get_executor(step_info.get("type"))
            step_result = await flow._execute_step(executor, step_info)

            # Evaluate result and update step status
            step_success = await flow._evaluate_step_result(step_result)
            if step_success:
                await flow._mark_step_completed()
                status = "completed"
            else:
                await flow.planning_tool.execute(
                    command="mark_step",
                    plan_id=plan_id,
                    step_index=step_index,
                    step_status="blocked",
                    step_notes=f"Execution failed: {step_result[:100]}...",
                )
                status = "error"

            # Store the result
            task_results[task_id] = {
                "status": status,
                "result": step_result,
                "has_logs": True,
                "plan_id": plan_id,
                "step_index": step_index,
            }

            logger.info(
                f"Step execution completed: plan_id={plan_id}, step_index={step_index}, status={status}"
            )

        except Exception as e:
            logger.error(f"Error executing step: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())

            task_results[task_id] = {
                "status": "error",
                "result": f"Error executing step: {str(e)}",
                "has_logs": True,
            }
        finally:
            # Clear logging context
            logger.clear_task_context()

            # Remove from active tasks
            if task_id in active_tasks:
                del active_tasks[task_id]

    # Start asynchronous processing thread
    thread = threading.Thread(
        target=run_async_task,
        args=(task_id, process_step_execution(task_id, plan_id, step_index)),
    )
    thread.start()

    return jsonify(
        {
            "status": "processing",
            "task_id": task_id,
            "plan_id": plan_id,
            "step_index": step_index,
        }
    )


# 主程序
if __name__ == "__main__":
    # 确保templates目录存在
    os.makedirs("templates", exist_ok=True)

    # 初始化agent
    initialize_agent()

    # 启动Flask应用
    app.run(host="0.0.0.0", port=8009, debug=True)
