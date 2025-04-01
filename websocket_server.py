import asyncio
import json
import uuid # For unique tool call IDs if needed by frontend
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

# Import agent components
# Remove original Manus import
# from app.agent.manus import Manus
# Import the NEW WebSocketManus
from app.agent.websocket_manus import WebSocketManus
# Import the NEW WebSocketPlanningFlow
from app.flow.websocket_planning import WebSocketPlanningFlow
from app.tool.planning import PlanningTool
from app.tool.ask_human import HumanInterventionRequired # Import for type checking

app = FastAPI()

# Store active connections and their associated state
class ConnectionState:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.flow_task: Optional[asyncio.Task] = None
        self.human_wait_events: Dict[str, asyncio.Event] = {}
        self.human_responses: Dict[str, str] = {}
        self.flow_instance: Optional[WebSocketPlanningFlow] = None # Store flow instance
        self.agent_instance: Optional[WebSocketManus] = None # Store agent instance

active_connections: Dict[str, ConnectionState] = {}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    logger.info(f"Client connected: {client_id} ({websocket.client})")
    connection_state = ConnectionState(websocket)
    active_connections[client_id] = connection_state

    # --- Callback function to send updates ---
    async def send_update(update_data: dict):
        # Ensure websocket is still valid before sending
        if client_id in active_connections and active_connections[client_id].websocket == websocket:
            try:
                await websocket.send_text(json.dumps(update_data))
                logger.debug(f"Sent update to {client_id}: {update_data}")
            except Exception as e:
                logger.error(f"Failed to send update to client {client_id}: {e}. Connection state: {websocket.client_state}")
                # Consider cleaning up connection here if send fails repeatedly
        else:
             logger.warning(f"Attempted to send update to closed/invalid websocket for {client_id}")

    # --- Main execution function (runs in background) ---
    async def run_agent_flow(prompt: str, conn_state: ConnectionState):
        try:
            # 1. Initialize Agent and Flow (if not already initialized for this connection)
            # This allows reusing the same agent/flow if connection persists but new prompt comes?
            # For now, let's re-initialize each time run_agent_flow is called.
            logger.info(f"[{client_id}] Initializing agent and flow...")
            # Pass the dictionaries for human input handling
            agent = WebSocketManus(
                websocket_callback=send_update,
                # Pass other Manus specific args if needed
            )
            planning_tool_instance = PlanningTool()
            agent.available_tools.add_tool(planning_tool_instance)
            agents = {"manus": agent}

            flow = WebSocketPlanningFlow(
                agents=agents,
                planning_tool=planning_tool_instance,
                websocket_callback=send_update,
                # Pass the shared state for human input
                human_wait_events=conn_state.human_wait_events,
                human_responses=conn_state.human_responses
            )
            conn_state.flow_instance = flow # Store instances
            conn_state.agent_instance = agent

            logger.info(f"[{client_id}] Agent and Flow initialized.")
            await send_update({"type": "status", "text": "Agent initialized. Starting execution..."})

            # 2. Execute the Flow
            start_time = asyncio.get_event_loop().time()
            await flow.execute(prompt)
            elapsed_time = asyncio.get_event_loop().time() - start_time
            logger.info(f"[{client_id}] Flow execution task completed or paused in {elapsed_time:.2f} seconds")
            # Final status/result messages are now sent from within the flow overrides

        except HumanInterventionRequired:
            # This is now expected if the flow pauses for input
            logger.info(f"[{client_id}] Flow execution paused, waiting for human input via WebSocket.")
            # The flow's _execute_step is waiting on an event
        except asyncio.CancelledError:
             logger.warning(f"[{client_id}] Flow execution task was cancelled.")
             await send_update({"type": "status", "text": "Execution cancelled."})
        except Exception as e:
            logger.error(f"[{client_id}] Error during flow execution task: {e}", exc_info=True)
            await send_update({"type": "error", "text": f"An critical error occurred during execution: {str(e)}"})
        finally:
            # Task finished (or paused for HIR), remove reference?
            # Or keep it in case we need to resume?
            # For now, let's nullify the task reference, assuming a new one starts on resume/new prompt
            if client_id in active_connections:
                 active_connections[client_id].flow_task = None
            logger.info(f"[{client_id}] Background flow task finished or paused.")

    # --- Main message handling loop ---
    try:
        await send_update({"type": "status", "text": "Connected. Waiting for prompt..."})
        while True:
            message_text = await websocket.receive_text()
            logger.debug(f"Received message from {client_id}: {message_text[:100]}...")
            try:
                data = json.loads(message_text)
                msg_type = data.get("type")

                # --- Handle Initial Prompt ---
                if "prompt" in data and not connection_state.flow_task:
                    prompt = data.get("prompt")
                    if prompt and prompt.strip():
                        logger.info(f"[{client_id}] Received prompt: '{prompt}'")
                        await send_update({"type": "status", "text": f"Received prompt. Starting agent..."})
                        # Start execution in a background task
                        connection_state.flow_task = asyncio.create_task(
                            run_agent_flow(prompt, connection_state)
                        )
                    else:
                         await send_update({"type": "error", "text": "Empty prompt received."})

                # --- Handle Human Response ---
                elif msg_type == "human_response":
                    tool_call_id = data.get("tool_call_id")
                    response_text = data.get("response")
                    if tool_call_id and response_text is not None: # Allow empty string response
                        logger.info(f"[{client_id}] Received human response for {tool_call_id}: '{response_text}'")
                        event = connection_state.human_wait_events.get(tool_call_id)
                        if event:
                            connection_state.human_responses[tool_call_id] = response_text
                            event.set() # Signal the waiting flow task
                            await send_update({"type": "status", "text": f"Received response. Resuming agent...", "tool_call_id": tool_call_id})
                        else:
                            logger.warning(f"[{client_id}] Received human response for unknown/inactive tool_call_id: {tool_call_id}")
                            await send_update({"type": "error", "text": f"Agent wasn't waiting for response with ID {tool_call_id}", "tool_call_id": tool_call_id})
                    else:
                        logger.warning(f"[{client_id}] Invalid human_response message: {data}")
                        await send_update({"type": "error", "text": "Invalid human response format."})

                # --- Handle Other Message Types (Optional) ---
                # elif msg_type == "cancel_request":
                #    if connection_state.flow_task:
                #        connection_state.flow_task.cancel()
                #        await send_update({"type": "status", "text": "Cancellation request received."})
                else:
                    logger.warning(f"[{client_id}] Received unhandled message data/type: {data}")
                    # Optionally send an error back to client
                    # await send_update({"type": "error", "text": "Unhandled message type received."})

            except json.JSONDecodeError:
                logger.warning(f"[{client_id}] Received invalid JSON: {message_text}")
                await send_update({"type": "error", "text": "Invalid message format. Expected JSON."})
            except Exception as e:
                 logger.error(f"[{client_id}] Error processing message: {e}", exc_info=True)
                 # Don't close connection, but inform client
                 await send_update({"type": "error", "text": f"Error processing your message: {e}"})

    except WebSocketDisconnect:
        logger.warning(f"Client disconnected: {client_id} ({websocket.client})")
    except Exception as e:
        logger.error(f"WebSocket Error for {client_id}: {e}", exc_info=True)
        # Attempt to close gracefully if possible (FastAPI might handle this)
    finally:
        logger.info(f"Cleaning up connection for {client_id}")
        conn_state = active_connections.pop(client_id, None)
        if conn_state:
            # Cancel the flow task if it's still running
            if conn_state.flow_task and not conn_state.flow_task.done():
                logger.info(f"[{client_id}] Cancelling background flow task due to disconnect.")
                conn_state.flow_task.cancel()
            # Signal any waiting events to prevent tasks hanging forever
            for tool_id, event in conn_state.human_wait_events.items():
                 logger.warning(f"[{client_id}] Signaling abandoned human wait event for {tool_id}")
                 # Optionally store a specific 'disconnected' response?
                 conn_state.human_responses[tool_id] = "__DISCONNECTED__"
                 event.set()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("websocket_server:app", host="0.0.0.0", port=8000, reload=True)
