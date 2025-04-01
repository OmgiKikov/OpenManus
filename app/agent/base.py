import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.llm import LLM
from app.logger import logger
from app.sandbox.client import SANDBOX_CLIENT
from app.schema import ROLE_TYPE, AgentState, Memory, Message

# Define the type hint for the async callback function
WebSocketCallback = Callable[[Dict], Coroutine[None, None, None]]

# Add import for HumanInterventionRequired at the top of the file if not already present
# from app.tool.ask_human import HumanInterventionRequired
# Assuming it might be used elsewhere, let's ensure it's available
try:
    from app.tool.ask_human import HumanInterventionRequired
except ImportError:
    # Define a dummy exception if the tool isn't present,
    # so the except block below doesn't cause a NameError
    class HumanInterventionRequired(Exception): pass


class BaseAgent(BaseModel, ABC):
    """Abstract base class for managing agent state and execution.

    Provides foundational functionality for state transitions, memory management,
    and a step-based execution loop. Subclasses must implement the `step` method.
    """

    # Core attributes
    name: str = Field(..., description="Unique name of the agent")
    description: Optional[str] = Field(None, description="Optional agent description")

    # Prompts
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )

    # Dependencies
    llm: LLM = Field(default_factory=LLM, description="Language model instance")
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )

    # Execution control
    max_steps: int = Field(default=10, description="Maximum steps before termination")
    current_step: int = Field(default=0, description="Current step in execution")

    duplicate_threshold: int = 2

    # Add optional websocket_callback field
    websocket_callback: Optional[WebSocketCallback] = Field(
        default=None, description="Optional callback for sending WebSocket updates"
    )

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra fields for flexibility in subclasses

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """Initialize agent with default settings if not provided."""
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR  # Transition to ERROR on failure
            raise e
        finally:
            self.state = previous_state  # Revert to previous state

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            base64_image: Optional base64 encoded image.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    # Add the send_update helper method
    async def send_update(self, update_data: dict):
        """Helper method to safely send updates via the WebSocket callback."""
        if self.websocket_callback:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.websocket_callback(update_data))
            except Exception as e:
                logger.error(f"Error sending WebSocket update from Agent {self.name}: {e}", exc_info=True)
        else:
            logger.debug(f"Agent {self.name}: No websocket_callback configured, update not sent: {update_data}")

    async def run(self, request: Optional[str] = None) -> str:
        """Execute the agent's main loop asynchronously.

        Args:
            request: Optional initial user request to process.

        Returns:
            A string summarizing the execution results.

        Raises:
            RuntimeError: If the agent is not in IDLE state at start.
        """
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        await self.send_update({"type": "agent_status", "agent": self.name, "text": "Starting run..."})

        if request:
            self.update_memory("user", request)
            await self.send_update({"type": "memory_update", "agent": self.name, "role": "user", "content": request})

        results: List[str] = []
        final_status_text = "No steps executed"
        # Ensure state is reset correctly even if HIR occurs
        original_state = self.state
        try:
            # Use state_context for RUNNING state
            async with self.state_context(AgentState.RUNNING):
                while (
                    self.current_step < self.max_steps and self.state != AgentState.FINISHED
                ):
                    self.current_step += 1
                    logger.info(f"Agent '{self.name}' executing step {self.current_step}/{self.max_steps}")
                    await self.send_update({
                        "type": "agent_step",
                        "agent": self.name,
                        "text": f"Starting step {self.current_step}/{self.max_steps}",
                        "current_step": self.current_step,
                        "max_steps": self.max_steps
                    })
                    try:
                        step_result = await self.step()

                    except HumanInterventionRequired as hir:
                        # HIR is not a fatal step error, it should be handled by the caller (Flow)
                        logger.info(f"Agent '{self.name}' step {self.current_step} requires human input. Propagating.")
                        await self.send_update({
                            "type": "agent_status",
                            "agent": self.name,
                            "text": f"Step {self.current_step} requires human input.",
                            "step": self.current_step,
                            "needs_human_input": True # Add flag
                        })
                        # Re-raise the exception to be caught by the Flow
                        raise hir
                    except Exception as step_error:
                        # Handle other exceptions as fatal step errors
                        logger.error(f"Error during agent {self.name} step {self.current_step}: {step_error}", exc_info=True)
                        await self.send_update({
                            "type": "error",
                            "agent": self.name,
                            "text": f"Error in step {self.current_step}: {step_error}",
                            "step": self.current_step
                        })
                        self.state = AgentState.ERROR # Move to error state
                        results.append(f"Step {self.current_step}: Error - {step_error}")
                        break # Exit loop on step error

                    # --- Code after successful step execution (if no exception) ---
                    # Check for stuck state
                    if self.is_stuck():
                        await self.send_update({"type": "agent_status", "agent": self.name, "text": "Detected stuck state, attempting recovery..."})
                        self.handle_stuck_state()

                    results.append(f"Step {self.current_step}: {step_result}")
                    await self.send_update({
                        "type": "agent_step_result",
                        "agent": self.name,
                        "text": f"Step {self.current_step} finished.",
                        "step": self.current_step,
                        "result_summary": step_result[:100] + ('...' if len(step_result) > 100 else '')
                    })

                    # Check agent state after step (e.g., if step sets state to FINISHED)
                    if self.state == AgentState.FINISHED:
                        await self.send_update({"type": "agent_status", "agent": self.name, "text": "Agent entered FINISHED state."})
                        break

                # --- Loop finished --- #
                if self.state == AgentState.FINISHED:
                    final_status_text = "Execution finished successfully."
                elif self.current_step >= self.max_steps:
                    final_status_text = f"Terminated: Reached max steps ({self.max_steps})"
                    self.state = AgentState.IDLE # Reset state if terminated by max_steps
                elif self.state == AgentState.ERROR:
                     final_status_text = "Terminated due to error."
                     # State is already ERROR
                # Note: If loop exited due to HIR, state should still be RUNNING here
                # The finally block will reset it
                else:
                     # Should not happen if loop terminates correctly, but handle just in case
                     final_status_text = f"Execution ended with unexpected state ({self.state})."
                     self.state = AgentState.IDLE # Reset to idle as a fallback

        except HumanInterventionRequired as hir_main:
            # Catch HIR that propagated out of the loop
            logger.info(f"Agent '{self.name}' run paused for human input.")
            # State should be RUNNING here, state_context will revert it on exit
            final_status_text = "Paused for human input."
            # Re-raise it again so the absolute caller (websocket server via Flow) gets it
            raise hir_main
        except Exception as run_error:
            # Catch any other unexpected errors during the run setup or context exit
            logger.error(f"Unexpected error during agent '{self.name}' run: {run_error}", exc_info=True)
            self.state = AgentState.ERROR # Ensure state is error
            final_status_text = f"Run failed with unexpected error: {run_error}"
            await self.send_update({"type": "error", "agent": self.name, "text": final_status_text})
        finally:
            # This block executes even if HIR is raised
            # Reset step count and potentially state
            self.current_step = 0
            # If state is still RUNNING (e.g., HIR occurred), reset to IDLE.
            # If state is ERROR or FINISHED, leave it as is.
            if self.state == AgentState.RUNNING:
                self.state = AgentState.IDLE
                logger.debug(f"Agent '{self.name}' state reset to IDLE after run completion/pause.")

            # Send final status update (unless it was HIR?)
            # Let's always send a final status for clarity
            await self.send_update({"type": "agent_status", "agent": self.name, "text": f"Run ended. Final status: {self.state}. {final_status_text}"})
            logger.info(f"Agent '{self.name}' run finished. Final State: {self.state}. Result summary: {final_status_text}")

            # Sandbox cleanup remains important
            await SANDBOX_CLIENT.cleanup()

        # Return results collected before error/HIR, or the final status text
        return "\n".join(results) if results else final_status_text

    @abstractmethod
    async def step(self) -> str:
        """Execute a single step in the agent's workflow.

        Must be implemented by subclasses to define specific behavior.
        """

    def handle_stuck_state(self):
        """Handle stuck state by adding a prompt to change strategy"""
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    @property
    def messages(self) -> List[Message]:
        """Retrieve a list of messages from the agent's memory."""
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]):
        """Set the list of messages in the agent's memory."""
        self.memory.messages = value
