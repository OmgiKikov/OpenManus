import asyncio
import logging
import os
import queue
import sys
import threading
import time
import uuid
from io import StringIO

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# Configure Werkzeug logger to only show WARNING and above
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# 导入OpenManus组件
from app.agent.manus import Manus
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
    log_entry = {
        "timestamp": time.time(),
        "level": level,
        "message": message
    }
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
            log_entry = {
                "timestamp": time.time(),
                "level": level,
                "message": s.strip()
            }
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

        # 运行处理
        result = await manus_agent.run(message)

        # 恢复标准输出和错误
        sys.stdout = old_stdout
        sys.stderr = old_stderr

        # 保存结果
        task_results[task_id] = {
            "status": "completed",
            "result": result,
            "has_logs": True
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
            "has_logs": True
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

@app.route('/api/send', methods=['POST'])
def send_message():
    # 确保agent已初始化
    initialize_agent()

    # 获取用户消息
    data = request.json
    message = data.get('message', '').strip()

    if not message:
        return jsonify({
            "status": "error",
            "message": "消息不能为空"
        }), 400

    # 创建任务ID
    task_id = str(uuid.uuid4())

    # 创建任务
    active_tasks[task_id] = {
        "message": message,
        "created_at": time.time()
    }

    # 启动异步处理线程
    thread = threading.Thread(
        target=run_async_task,
        args=(task_id, process_prompt(task_id, message))
    )
    thread.start()

    return jsonify({
        "status": "processing",
        "task_id": task_id
    })

@app.route('/api/status/<task_id>', methods=['GET'])
def check_status(task_id):
    # Проверяем, ожидает ли задача ответа от человека
    if human_queue.has_pending_question(task_id):
        return jsonify({
            "status": "awaiting_human",
            "question": human_queue.get_current_question(task_id),
            "message": "Задача ожидает ответа от пользователя"
        })

    # 检查任务是否完成
    if task_id in task_results:
        result = task_results[task_id]
        # 任务完成后，可以选择性地删除结果
        # del task_results[task_id]
        return jsonify(result)

    # 检查任务是否正在处理
    if task_id in active_tasks:
        return jsonify({
            "status": "processing",
            "message": "Задача обрабатывается"
        })

    # 任务不存在
    return jsonify({
        "status": "not_found",
        "message": "Задача не найдена"
    }), 404

# 获取实时日志的API端点
@app.route('/api/logs/<task_id>', methods=['GET'])
def get_logs(task_id):
    # 获取上次请求的日志索引
    last_index = request.args.get('last_index', 0)
    try:
        last_index = int(last_index)
    except ValueError:
        last_index = 0

    # 获取新日志
    if task_id in task_logs_queue:
        logs = task_logs_queue[task_id][last_index:]
        return jsonify({
            "logs": logs,
            "next_index": last_index + len(logs)
        })

    return jsonify({
        "logs": [],
        "next_index": last_index
    })

# endpoint для ответов пользователя
@app.route('/api/human_response', methods=['POST'])
def submit_human_response():
    data = request.json
    task_id = data.get('task_id')
    response = data.get('response', '').strip()

    if not task_id or not response:
        return jsonify({
            "status": "error",
            "message": "ID задачи и ответ обязательны"
        }), 400

    # Проверяем, есть ли активный вопрос для этой задачи
    if not human_queue.has_pending_question(task_id):
        return jsonify({
            "status": "error",
            "message": "Для этой задачи нет активных вопросов"
        }), 400

    # Добавляем ответ в очередь
    success = human_queue.add_response(task_id, response)

    if success:
        # Добавляем ответ в логи для отображения в UI
        add_log(task_id, f"[USER_RESPONSE] {response}", "INFO")

        return jsonify({
            "status": "success",
            "message": "Ответ успешно обработан"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Не удалось обработать ответ"
        }), 500

# 主程序
if __name__ == "__main__":
    # 确保templates目录存在
    os.makedirs("templates", exist_ok=True)

    # 初始化agent
    initialize_agent()

    # 启动Flask应用
    app.run(host="0.0.0.0", port=8009, debug=True)
