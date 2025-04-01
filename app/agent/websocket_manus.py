import asyncio
import json
from typing import Dict, List, Optional, Union, Callable, Coroutine

from loguru import logger
from pydantic import Field

# Import the original Manus agent
from app.agent.manus import Manus
# Import base agent components and callback type
from app.agent.base import BaseAgent, WebSocketCallback
from app.llm import LLM
from app.schema import Message, ToolCall, ToolChoice
from app.tool.base import BaseTool, ToolResult
from app.tool.ask_human import HumanInterventionRequired



class WebSocketManus(Manus):
    """
    A Manus subclass that adds WebSocket updates for frontend integration.
    Inherits core logic from Manus and overrides methods to call send_update.
    """

    # Inherit all fields from Manus (name, description, llm, memory, state, etc.)
    # The websocket_callback is handled by BaseAgent's initialization chain

    def __init__(
        self,
        websocket_callback: Optional[WebSocketCallback] = None,
        **data # Pass other Manus-specific args if any
    ):
        """Initialize the agent, passing the callback to the parent class."""
        # Pass callback up to BaseAgent via Manus initialization
        super().__init__(websocket_callback=websocket_callback, **data)
        logger.info(f"WebSocketManus initialized. Callback {'present' if websocket_callback else 'not present'}.")
        # Ensure tools also get the callback
        if websocket_callback:
            # Check if available_tools has a .tools attribute which is iterable (like a dict)
            if hasattr(self.available_tools, 'tools') and isinstance(self.available_tools.tools, dict):
                 logger.debug(f"Iterating over tools in {type(self.available_tools).__name__}.tools dictionary")
                 tools_iterable = self.available_tools.tools.values()
            # Check if available_tools itself is iterable
            elif hasattr(self.available_tools, '__iter__'):
                 logger.debug(f"Iterating directly over {type(self.available_tools).__name__}")
                 # If it's a list or tuple of tools directly
                 tools_iterable = self.available_tools
            else:
                 logger.warning(f"Could not determine how to iterate over tools in {type(self.available_tools).__name__}. Skipping callback injection for tools.")
                 tools_iterable = [] # Avoid error

            for tool in tools_iterable:
                 # Check if it's actually a tool instance before setting attribute
                 if isinstance(tool, BaseTool) and hasattr(tool, 'websocket_callback'):
                     tool.websocket_callback = websocket_callback
                     logger.debug(f"Injected websocket_callback into tool: {tool.name}")
                 elif not isinstance(tool, BaseTool):
                      logger.warning(f"Item in tools_iterable is not a BaseTool: {type(tool)}")

    # We inherit send_update from BaseAgent

    # --- Method Overrides --- #

    # Override step or methods called by step (like _process_step, _execute_tool_calls)
    # Let's look at the original Manus code to see which methods are best to override.
    # Assuming Manus has methods like _think, _call_llm, execute_tool...

    # Example: Override a method that calls the LLM
    async def _call_llm_with_tools(self, messages: List[Message], tools: List[BaseTool]) -> Message:
        """Override LLM call to add thinking/response updates."""
        tool_names = [t.name for t in tools]
        await self.send_update({
            "type": "thinking",
            "agent": self.name,
            "text": f"Calling LLM with tools: {', '.join(tool_names)}..."
        })
        try:
            llm_response = await super()._call_llm_with_tools(messages, tools)
            await self.send_update({
                "type": "llm_response",
                "agent": self.name,
                "text": "Received response from LLM.",
                "content": llm_response.content,
                "tool_calls": llm_response.tool_calls # Send tool calls if any
            })
            return llm_response
        except Exception as e:
            logger.error(f"Error during _call_llm_with_tools override: {e}", exc_info=True)
            await self.send_update({"type": "error", "agent": self.name, "text": f"Error calling LLM: {e}"})
            raise # Re-raise the exception

    # Example: Override execute_tool method
    async def execute_tool(self, tool_call: ToolCall) -> Optional[str]:
        """Override tool execution to add updates before and after, and handle file events."""
        tool_name = tool_call.function.name
        args_str = str(tool_call.function.arguments)
        await self.send_update({
            "type": "tool_call",
            "agent": self.name,
            "tool_name": tool_name,
            "arguments": args_str,
            "text": f"Executing tool: {tool_name}..."
        })
        try:
            tool_result_raw = await super().execute_tool(tool_call)

            # --- Handle File Event ---
            file_event_to_send = None
            output_for_processing = None # This will hold the STRING output

            if isinstance(tool_result_raw, dict):
                file_event_data = tool_result_raw.get('file_event')
                output_for_processing = tool_result_raw.get('output', '')

                if file_event_data:
                    file_event_to_send = file_event_data
                    logger.info(f"[WSManus.execute_tool] Extracted file_event: {file_event_to_send.get('type')}, file: {file_event_to_send.get('filename')}")
                else:
                    logger.debug("[WSManus.execute_tool] file_event key exists but value is None/empty.")
            else:
                output_for_processing = tool_result_raw

            # Send the specific file event update if it exists
            if file_event_to_send:
                if 'type' in file_event_to_send:
                     await self.send_update(file_event_to_send)
                else:
                     logger.warning("[WSManus.execute_tool] File event data missing 'type', not sending.")
            else:
                 logger.debug("[WSManus.execute_tool] No file_event_to_send.")
            # --- End Handle File Event ---

            # Prepare standard tool_result update data using output_for_processing (should be string now)
            update_payload = {
                "type": "tool_result",
                "agent": self.name,
                "tool_name": tool_name,
                "status": "unknown", # Default status
                "output_summary": "",
                "text": f"Tool {tool_name} finished."
            }
            tool_status = "unknown"
            output_summary_text = ""
            return_value_for_agent = None
            if isinstance(output_for_processing, ToolResult):
                logger.warning("[WSManus.execute_tool] output_for_processing is unexpectedly a ToolResult object.")
                output_summary_text = str(output_for_processing.output)[:200] + ('...' if len(str(output_for_processing.output)) > 200 else '')
                tool_status = output_for_processing.status
                return_value_for_agent = output_for_processing.output # Extract string
            elif isinstance(output_for_processing, str):
                output_summary_text = output_for_processing[:200] + ('...' if len(output_for_processing) > 200 else '')
                tool_status = "completed"
                return_value_for_agent = output_for_processing
            else:
                # Handle other types (None, etc.)
                output_summary_text = str(output_for_processing)[:200] + ('...' if len(str(output_for_processing)) > 200 else '')
                tool_status = "error"
                logger.warning(f"[WSManus.execute_tool] output_for_processing was unexpected type: {type(output_for_processing)}")
                return_value_for_agent = f"Error: Tool returned unusable data type: {type(output_for_processing).__name__}"

            # Update payload
            update_payload["status"] = tool_status
            update_payload["output_summary"] = output_summary_text
            update_payload["text"] = f"Tool {tool_name} finished with status: {tool_status}. Result: {output_summary_text}"

            # Send the standard tool_result update
            await self.send_update(update_payload)

            # Return the STRING value expected by the agent's core logic
            return return_value_for_agent if return_value_for_agent is not None else ""

        except HumanInterventionRequired as hir:
            logger.info(f"HumanInterventionRequired during execute_tool ({tool_name})")
            raise hir
        except Exception as e:
            logger.error(f"Error during execute_tool override ({tool_name}): {e}", exc_info=True)
            await self.send_update({
                "type": "error",
                "agent": self.name,
                "text": f"Error executing tool {tool_name}: {e}",
                "tool_name": tool_name
            })
            raise # Re-raise for the flow/caller to handle

    # NOTE: We might need to override more methods from Manus depending on its structure
    # For example, the main `step` method or specific processing methods within it.
    # The goal is to wrap key actions (LLM calls, tool calls) with send_update.

    async def step(self) -> str:
        """Override the main step method if necessary to add more granular updates."""
        # Example: Add an update before calling the main logic
        await self.send_update({"type": "agent_thinking", "agent": self.name, "text": "Processing next step..."})
        try:
            # Call the original step logic
            result = await super().step()
            # Potentially add update after step logic completes successfully
            # await self.send_update({ ... })
            return result
        except HumanInterventionRequired as hir:
            # Allow HIR exception to propagate upwards to be handled by the Flow
            logger.debug(f"WebSocketManus step caught and re-raising HumanInterventionRequired")
            raise hir
        except Exception as e:
            logger.error(f"Error during WebSocketManus step override: {e}", exc_info=True)
            await self.send_update({"type": "error", "agent": self.name, "text": f"Error processing agent step: {e}"})
            raise # Re-raise exception to be handled by the run loop

    # --- Override think method to send llm_response ---
    async def think(self) -> bool:
        """Override think to send llm_response update after super().think()."""
        thinking_result = await super().think()
        if thinking_result:
            last_assistant_message = next((msg for msg in reversed(self.memory.messages) if msg.role == "assistant"), None)
            if last_assistant_message:
                content = last_assistant_message.content
                tool_calls = last_assistant_message.tool_calls

                # --- Convert ToolCall objects to JSON-serializable format ---
                serializable_tool_calls = None
                if tool_calls:
                    try:
                        # Assuming Pydantic v2+ .model_dump(), use mode='json' for best results
                        serializable_tool_calls = [tc.model_dump(mode='json') for tc in tool_calls]
                    except AttributeError:
                        # Fallback for older Pydantic or other objects: try .dict()
                        try:
                            serializable_tool_calls = [tc.dict() for tc in tool_calls]
                        except Exception as e:
                             logger.error(f"Failed to serialize tool calls for WebSocket: {e}", exc_info=True)
                             serializable_tool_calls = [{"error": "Serialization failed"}] # Send placeholder
                    except Exception as e:
                         logger.error(f"Failed to serialize tool calls using model_dump: {e}", exc_info=True)
                         serializable_tool_calls = [{"error": "Serialization failed"}] # Send placeholder
                # --- End Conversion ---

                logger.debug(f"[WSManus.think] Sending llm_response update. Content: '{str(content)[:50]}...', ToolCalls: {len(serializable_tool_calls) if serializable_tool_calls else 0}")
                await self.send_update({
                    "type": "llm_response",
                    "agent": self.name,
                    "text": "Received response from LLM.",
                    "content": content,
                    # Use the serializable list here
                    "tool_calls": serializable_tool_calls
                })
            else:
                logger.warning("[WSManus.think] thinking_result was True, but couldn't find last assistant message in memory.")
        return thinking_result
    # --- End Override think ---
