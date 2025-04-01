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
    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Override tool execution to add updates before and after."""
        tool_name = tool_call.function.name
        args_str = str(tool_call.function.arguments)
        await self.send_update({
            "type": "tool_call",
            "agent": self.name,
            "tool_name": tool_name,
            "arguments": args_str[:200] + ('...' if len(args_str) > 200 else ''),
            "text": f"Executing tool: {tool_name}..."
        })
        try:
            # Call the original execution logic
            tool_result_raw = await super().execute_tool(tool_call)

            # Prepare update data, handling different result types
            update_payload = {
                "type": "tool_result",
                "agent": self.name,
                "tool_name": tool_name,
                "status": "unknown", # Default status
                "output_summary": "",
                "text": f"Tool {tool_name} finished."
            }

            # Check if the result is a ToolResult object
            if isinstance(tool_result_raw, ToolResult):
                output_summary = str(tool_result_raw.output)[:200] + ('...' if len(str(tool_result_raw.output)) > 200 else '')
                update_payload["status"] = tool_result_raw.status
                update_payload["output_summary"] = output_summary
                update_payload["text"] = f"Tool {tool_name} finished with status: {tool_result_raw.status}."
                tool_result_to_return = tool_result_raw # Return the original object
            # Check if the result is just a string
            elif isinstance(tool_result_raw, str):
                output_summary = tool_result_raw[:200] + ('...' if len(tool_result_raw) > 200 else '')
                update_payload["status"] = "completed" # Assume completed if string is returned
                update_payload["output_summary"] = output_summary
                update_payload["text"] = f"Tool {tool_name} finished. Result: {output_summary}"
                # We need to return a ToolResult for type consistency,
                # or change the signature? Let's create a minimal one.
                tool_result_to_return = ToolResult(status="completed", output=tool_result_raw, error=None)
            # Handle other unexpected types
            else:
                output_summary = str(tool_result_raw)[:200] + ('...' if len(str(tool_result_raw)) > 200 else '')
                update_payload["output_summary"] = output_summary
                update_payload["text"] = f"Tool {tool_name} finished with unexpected result type: {type(tool_result_raw).__name__}."
                logger.warning(f"Tool {tool_name} returned unexpected type: {type(tool_result_raw)}")
                # Return a ToolResult indicating the issue
                tool_result_to_return = ToolResult(status="error", output=f"Unexpected result type: {type(tool_result_raw).__name__}", error=f"Unexpected result type: {type(tool_result_raw)}")

            # Send the update
            await self.send_update(update_payload)

            # Return a ToolResult object consistently
            # return tool_result_to_return # <<< OLD RETURN

            # --- NEW RETURN ---
            # Return only the output, which is likely what the original step logic expects.
            # Ensure we handle cases where output might be None or not string.
            output_to_return = getattr(tool_result_to_return, 'output', None)
            logger.debug(f"execute_tool override returning output: {str(output_to_return)[:100]}...")
            # The original execute_tool likely returned the output string directly or None
            return output_to_return

        except HumanInterventionRequired as hir:
             logger.info(f"HumanInterventionRequired during execute_tool ({tool_name})")
             # No specific update needed here, the Flow override handles it
             raise hir # Re-raise for the Flow/caller to handle
        except Exception as e:
            logger.error(f"Error during execute_tool override ({tool_name}): {e}", exc_info=True)
            await self.send_update({
                "type": "error",
                "agent": self.name,
                "text": f"Error executing tool {tool_name}: {e}",
                "tool_name": tool_name
             })
            raise

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
