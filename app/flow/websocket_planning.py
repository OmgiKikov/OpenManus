import asyncio
import json
from typing import Dict, List, Optional, Union, Callable, Coroutine

from loguru import logger

from app.agent.base import BaseAgent
from app.flow.base import WebSocketCallback # Import callback type hint
from app.flow.planning import PlanningFlow, PlanStepStatus, HUMAN_INTERACTION_SIGNAL # Import original flow and constants
from app.tool.ask_human import HumanInterventionRequired
from app.schema import AgentState


class WebSocketPlanningFlow(PlanningFlow):
    """
    A PlanningFlow subclass that adds WebSocket updates for frontend integration.
    It inherits the core planning logic from PlanningFlow and adds send_update calls.
    It also handles pausing execution for human input via WebSockets.
    """

    # Inherits llm, planning_tool, executor_keys, active_plan_id, current_step_index
    # The websocket_callback is handled by the BaseFlow via super().__init__

    # Add fields to store the shared state dictionaries
    human_wait_events: Optional[Dict[str, asyncio.Event]] = None
    human_responses: Optional[Dict[str, str]] = None

    def __init__(
        self,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        websocket_callback: Optional[WebSocketCallback] = None,
        human_wait_events: Optional[Dict[str, asyncio.Event]] = None, # Accept dicts
        human_responses: Optional[Dict[str, str]] = None,
        **data
    ):
        """Initialize the flow, passing the callback and human input state to the parent class."""
        # Pass the websocket_callback up to BaseFlow via PlanningFlow's __init__ chain
        super().__init__(agents=agents, websocket_callback=websocket_callback, **data)
        # Store the shared dictionaries
        self.human_wait_events = human_wait_events
        self.human_responses = human_responses
        logger.info(f"WebSocketPlanningFlow initialized. Callback {'present' if websocket_callback else 'not present'}. Human input handling: {'enabled' if human_wait_events is not None else 'disabled'}")

    # We inherit the send_update method from BaseFlow, no need to redefine it here
    # async def send_update(self, update_data: dict):
    #    ... (logic is in BaseFlow) ...

    # --- Method Overrides with WebSocket Updates --- #

    async def execute(self, input_text: str) -> str:
        """Override execute to add WebSocket updates around the core logic."""
        await self.send_update({"type": "status", "text": "Planning flow started."}) # START
        try:
            # Call the original PlanningFlow execute method
            result = await super().execute(input_text)
            await self.send_update({"type": "status", "text": "Planning flow finished."}) # END (Success)
            return result
        except ValueError as ve:
            # Specific handling for errors potentially raised early in super().execute()
            logger.error(f"ValueError in PlanningFlow execution: {ve}")
            await self.send_update({"type": "error", "text": f"Execution failed: {str(ve)}"}) # END (Error)
            # Re-raise or return error string?
            # For consistency with original, return the error string it likely would have generated
            return f"Execution failed: {str(ve)}"
        except HumanInterventionRequired:
            # This exception will now be caught by the run_agent_flow task in server
            logger.info(f"PlanningFlow execute caught HumanInterventionRequired, flow will pause.")
            # We don't return a string here, just let the exception propagate
            raise
        except Exception as e:
            logger.error(f"Error in PlanningFlow execution: {e}", exc_info=True)
            await self.send_update({"type": "error", "text": f"Execution failed: {str(e)}"}) # END (Error)
            return f"Execution failed: {str(e)}"

    async def _create_initial_plan(self, request: str) -> None:
        """Override to add updates around plan creation."""
        await self.send_update({"type": "thinking", "text": "Creating initial plan..."})
        await self.send_update({"type": "thinking", "text": "Calling LLM to generate plan steps..."})

        try:
            await super()._create_initial_plan(request)
            # Verify plan creation and send update/plan
            if self.active_plan_id in self.planning_tool.plans:
                await self.send_update({"type": "status", "text": "Initial plan created."})
                plan_text = await self._get_plan_text(include_status=False)
                await self.send_update({"type": "plan", "text": "Initial Plan:", "plan": plan_text})
            else:
                 # This case might be handled within super().execute, but good to log here too
                 logger.error(f"_create_initial_plan finished but plan {self.active_plan_id} not found.")
                 # Update might have already been sent by execute's error handling

        except Exception as e:
             logger.error(f"Error during _create_initial_plan: {e}", exc_info=True)
             await self.send_update({"type": "error", "text": f"Failed to create initial plan: {e}"})
             raise # Re-raise the exception so execute() can handle it

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """Override to add thinking update."""
        await self.send_update({"type": "thinking", "text": "Determining next step..."})
        try:
            # This internally calls the original PlanningFlow._get_current_step_info
            index, info = await super()._get_current_step_info()

            # IMPORTANT: The original PlanningFlow._get_current_step_info might already call
            # its own _mark_step_status(PlanStepStatus.IN_PROGRESS).
            # We should NOT call our overridden _mark_step_status here again,
            # especially not with step_index, as the original doesn't expect it.
            # The update for IN_PROGRESS will be sent when the original
            # _mark_step_status is called by the super()._get_current_step_info execution,
            # and our overridden _mark_step_status catches that call.

            # If the original _get_current_step_info *doesn't* mark as IN_PROGRESS,
            # we might need to call it here, but without step_index:
            # if index is not None:
            #     await self._mark_step_status(PlanStepStatus.IN_PROGRESS.value)
            # Let's assume for now the original handles marking IN_PROGRESS.

            return index, info
        except Exception as e:
            logger.error(f"Error during _get_current_step_info: {e}", exc_info=True)
            await self.send_update({"type": "error", "text": f"Error determining next step: {e}"})
            return None, None

    async def _get_plan_text(self, include_status: bool = True) -> str:
        """
        Override _get_plan_text to handle include_status argument
        without modifying the original PlanningFlow.
        """
        # Call the original method from PlanningFlow (which ignores include_status)
        original_plan_text = await super()._get_plan_text()

        if include_status:
            return original_plan_text
        else:
            # Manually remove status markers if needed
            lines = original_plan_text.split('\n')
            processed_lines = []
            status_markers = ["[✓]", "[→]", "[!]", "[ ]"]
            for line in lines:
                stripped_line = line.strip()
                # Check if line starts with a step number and a status marker
                import re
                match = re.match(r"^(\d+)\.\s+(\[.?\])\s+(.*)", stripped_line)
                if match:
                    step_num, _, step_text = match.groups()
                    processed_lines.append(f"{step_num}. {step_text}") # Append without status marker
                else:
                    processed_lines.append(line) # Keep lines that don't match the pattern (headers, etc.)
            return '\n'.join(processed_lines)

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """Override _execute_step to directly call agent.run() and handle HIR via WebSocket/Events.
           This avoids calling the original _execute_step with its terminal input logic.
        """
        step_text = step_info.get("text", f"Step {self.current_step_index}")
        retry_count = 0 # How to get retry count accurately without calling super execute loop?
                      # For now, it's not critical for HIR logic.

        await self.send_update({
            "type": "task",
            "text": f"Executing step {self.current_step_index}: {step_text}",
            "step_index": self.current_step_index,
            "step_text": step_text,
            "retry_count": retry_count
        })

        # Prepare the prompt for the agent (similar to original _execute_step)
        plan_status_text = await self._get_plan_text() # Use our overridden version
        step_prompt = f"""
        CURRENT PLAN STATUS:
        {plan_status_text}

        YOUR CURRENT TASK:
        You are now working on step {self.current_step_index}: "{step_text}"

        YOUR OBJECTIVE:
        1. Execute the current step using the appropriate tools.
        2. Analyze recent messages and update future plan steps if needed using the 'planning' tool.
        3. If you need clarification or a decision from the user, use the 'ask_human' tool.
        4. Provide a summary of your actions for this step.
        """

        try:
            # Directly call the agent's run method for this step
            step_result_str = await executor.run(step_prompt)

            # If agent run completes without HIR, mark step completed
            await self._mark_step_status(PlanStepStatus.COMPLETED.value)
            # Send result update
            await self.send_update({
                "type": "task_result",
                "text": f"Step {self.current_step_index} finished.",
                "step_index": self.current_step_index,
                "result_summary": step_result_str[:100] + ('...' if len(step_result_str) > 100 else '')
            })
            return step_result_str

        except HumanInterventionRequired as hir:
            logger.info(f"Caught HumanInterventionRequired in step {self.current_step_index}. Pausing for WebSocket input.")
            tool_call_id = hir.tool_call_id

            if self.human_wait_events is None or self.human_responses is None:
                 logger.error("HIR occurred but human input handling is not configured!")
                 err_msg = "Agent requires input, but WebSocket handling is not configured."
                 await self._mark_step_status(PlanStepStatus.BLOCKED.value, err_msg)
                 await self.send_update({"type": "error", "text": err_msg})
                 return err_msg

            # --- Start Wait Logic ---
            event = asyncio.Event()
            self.human_wait_events[tool_call_id] = event

            await self.send_update({
                "type": "human_input_required",
                "text": f"Agent needs help with step {self.current_step_index}: {step_text}",
                "question": hir.question,
                "step_index": self.current_step_index,
                "tool_call_id": tool_call_id
            })

            try:
                 logger.info(f"Step {self.current_step_index} waiting for event {tool_call_id}...")
                 await asyncio.wait_for(event.wait(), timeout=3600.0)
                 logger.info(f"Event {tool_call_id} received! Resuming step {self.current_step_index}.")
            except asyncio.TimeoutError:
                 logger.error(f"Timeout waiting for human response for {tool_call_id}.")
                 err_msg = "Timeout waiting for user response."
                 self.human_wait_events.pop(tool_call_id, None)
                 self.human_responses.pop(tool_call_id, None)
                 await self._mark_step_status(PlanStepStatus.BLOCKED.value, err_msg)
                 await self.send_update({"type": "error", "text": err_msg, "tool_call_id": tool_call_id})
                 return err_msg
            except Exception as wait_e:
                logger.error(f"Error waiting for event {tool_call_id}: {wait_e}", exc_info=True)
                self.human_wait_events.pop(tool_call_id, None)
                self.human_responses.pop(tool_call_id, None)
                raise wait_e

            # Event was set, retrieve the response
            user_response = self.human_responses.pop(tool_call_id, None)
            self.human_wait_events.pop(tool_call_id, None) # Clean up event

            if user_response is None:
                 logger.error(f"Event {tool_call_id} set, but no response found!")
                 err_msg = "Internal error: Response not found after wait."
                 await self._mark_step_status(PlanStepStatus.BLOCKED.value, err_msg)
                 await self.send_update({"type": "error", "text": err_msg, "tool_call_id": tool_call_id})
                 return err_msg
            elif user_response == "__DISCONNECTED__":
                 logger.warning(f"Client disconnected while waiting for {tool_call_id}.")
                 err_msg = "Client disconnected before providing response."
                 await self._mark_step_status(PlanStepStatus.BLOCKED.value, err_msg)
                 await self.send_update({"type": "error", "text": err_msg, "tool_call_id": tool_call_id})
                 return err_msg

            # --- Inject response into agent memory ---
            logger.info(f"Injecting tool result and user response for {tool_call_id} into agent memory: '{user_response}'")

            # 1. Add the Tool Result message FIRST
            if hasattr(executor, 'update_memory'):
                executor.update_memory(
                    role="tool",
                    content=user_response, # The user's answer is the result of the 'ask_human' tool
                    tool_call_id=tool_call_id,
                    name="ask_human" # Make sure this matches the tool name used in the call
                )
                await self.send_update({"type": "memory_update", "role": "tool", "content": user_response, "tool_call_id": tool_call_id, "name": "ask_human"})
            else:
                logger.error(f"Executor {type(executor).__name__} does not have update_memory method! Cannot add tool result.")

            # 2. OPTIONAL: Add a separate User message?
            # Usually, the tool result is sufficient context for the LLM.
            # Adding a user message might be redundant or confuse the model.
            # Let's comment this out for now.
            # response_content = f'Regarding your question "{hir.question}": {user_response}'
            # if hasattr(executor, 'update_memory'):
            #      executor.update_memory(role="user", content=response_content)
            #      await self.send_update({"type": "memory_update", "role": "user", "content": response_content, "tool_call_id": tool_call_id})
            # else:
            #      logger.error("Executor does not have update_memory method!")
            # --- End Memory Injection ---

            # Return the signal to retry the step
            return HUMAN_INTERACTION_SIGNAL

        except Exception as e:
            # Handle other errors during agent.run()
            logger.error(f"Error during agent execution for step {self.current_step_index}: {e}", exc_info=True)
            err_msg = f"Error executing step {self.current_step_index}: {str(e)}"
            await self._mark_step_status(PlanStepStatus.BLOCKED.value, err_msg)
            await self.send_update({"type": "error", "text": err_msg})
            return err_msg # Return error string to the main execute loop

    async def _mark_step_status(self, status: str, notes: Optional[str] = None, step_index: Optional[int] = None) -> None:
        """Override to send update AFTER the original method runs.
           Handles the fact that the original _mark_step_status does not accept step_index.
        """
        # Determine the index that the *original* method will use (it uses self.current_step_index)
        index_that_will_be_marked = self.current_step_index

        # If an explicit step_index was passed to *this* overridden method,
        # we need to temporarily set self.current_step_index for the super() call.
        original_current_step_index = self.current_step_index
        temporarily_changed_index = False
        if step_index is not None and step_index != self.current_step_index:
            logger.debug(f"Temporarily setting current_step_index to {step_index} for super()._mark_step_status call.")
            self.current_step_index = step_index
            index_that_will_be_marked = step_index # Update the index we expect to be marked
            temporarily_changed_index = True

        if index_that_will_be_marked is None:
             logger.warning("WebSocketPlanningFlow: Attempted to mark step status with no index determined.")
             # Restore index if we changed it
             if temporarily_changed_index:
                 self.current_step_index = original_current_step_index
             return

        try:
            # Call the original method. It implicitly uses self.current_step_index
            # and does NOT accept step_index as an argument.
            await super()._mark_step_status(status=status, notes=notes)

            # Get the updated plan text AFTER marking the step
            updated_plan_text = await self._get_plan_text(include_status=True)

            # THEN, send the update via WebSocket using the index that was actually marked.
            await self.send_update({
                "type": "plan_update",
                "text": f"Step {index_that_will_be_marked} marked as {status}.",
                "plan_id": self.active_plan_id,
                "step_index": index_that_will_be_marked,
                "status": status,
                "notes": notes,
                "plan": updated_plan_text # Include the full updated plan text
            })
        except Exception as e:
            logger.error(f"Error during _mark_step_status override for step {index_that_will_be_marked}: {e}", exc_info=True)
        finally:
            # Restore the original current_step_index if we changed it temporarily
            if temporarily_changed_index:
                self.current_step_index = original_current_step_index
                logger.debug("Restored original current_step_index.")

    async def _finalize_plan(self) -> str:
        """Override to add updates around final summary generation."""
        await self.send_update({"type": "thinking", "text": "Generating final summary..."})
        try:
            summary = await super()._finalize_plan()
            await self.send_update({"type": "result", "text": "Final summary generated.", "summary": summary})
            return summary
        except Exception as e:
            logger.error(f"Error during _finalize_plan: {e}", exc_info=True)
            err_msg = f"Error generating final summary: {e}"
            await self.send_update({"type": "error", "text": err_msg})
            return "Plan completed. Error generating summary."
