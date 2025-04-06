#!/usr/bin/env python
import os
import threading
import tomli
import webbrowser
from functools import partial
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.apis import router
from app.logger import logger
from app.config import config

app = FastAPI(title="OpenManus API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем статические файлы
workspace_path = config.root_path / "workspace"
if workspace_path.exists():
    app.mount("/static", StaticFiles(directory=str(workspace_path)), name="static")

# Настраиваем шаблоны
templates_path = config.root_path / "workspace"
templates = Jinja2Templates(directory=str(templates_path))

# Добавляем API маршруты
app.include_router(router)

# Маршрут для отображения HTML-страницы
@app.get("/", response_class=HTMLResponse)
async def get_html(request: Request):
    html_file = workspace_path / "api_test.html"
    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as file:
            content = file.read()
        return HTMLResponse(content=content)
    else:
        return HTMLResponse(content="<h1>HTML файл не найден</h1>")


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Server error: {str(exc)}")
    return JSONResponse(
        status_code=500, content={"message": f"Server error: {str(exc)}"}
    )


def open_local_browser(api_config):
    webbrowser.open_new_tab(
        f"http://{api_config.get('host', 'localhost')}:{api_config.get('port', 5172)}"
    )


def load_config():
    try:
        config_path = config.root_path / "config" / "api_config.toml"

        if not config_path.exists():
            logger.warning("API config file not found, using default configuration")
            return {"host": "localhost", "port": 5172}

        with open(config_path, "rb") as f:
            api_config = tomli.load(f)

        return {"host": api_config["server"]["host"], "port": api_config["server"]["port"]}
    except FileNotFoundError:
        logger.warning("API config file not found, using default configuration")
        return {"host": "localhost", "port": 5172}
    except KeyError as e:
        logger.warning(f"The configuration file is missing necessary fields: {str(e)}, using default configuration")
        return {"host": "localhost", "port": 5172}


if __name__ == "__main__":
    import uvicorn

    api_config = load_config()
    logger.info(f"Starting API server at http://{api_config['host']}:{api_config['port']}")

    open_with_config = partial(open_local_browser, api_config)
    threading.Timer(3, open_with_config).start()

    uvicorn.run(app, host=api_config["host"], port=api_config["port"])
