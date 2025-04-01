import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Coroutine, Dict, List, Optional, Union

from pydantic import BaseModel
from loguru import logger

from app.agent.base import BaseAgent

# Define the type hint for the async callback function
WebSocketCallback = Callable[[Dict], Coroutine[None, None, None]]


class BaseFlow(BaseModel, ABC):
    """Base class for execution flows supporting multiple agents"""

    agents: Dict[str, BaseAgent]
    tools: Optional[List] = None
    primary_agent_key: Optional[str] = None
    # Add optional websocket_callback attribute
    websocket_callback: Optional[WebSocketCallback] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(
        self,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        websocket_callback: Optional[WebSocketCallback] = None, # Add callback to __init__
        **data
    ):
        # Handle different ways of providing agents
        if isinstance(agents, BaseAgent):
            agents_dict = {"default": agents}
        elif isinstance(agents, list):
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}
        else:
            agents_dict = agents

        # If primary agent not specified, use first agent
        primary_key = data.get("primary_agent_key")
        if not primary_key and agents_dict:
            primary_key = next(iter(agents_dict))
            data["primary_agent_key"] = primary_key

        # Set the agents dictionary
        data["agents"] = agents_dict

        # Store the websocket callback
        data["websocket_callback"] = websocket_callback

        # Initialize using BaseModel's init
        super().__init__(**data)

        # Pass the callback to all agents managed by this flow
        if websocket_callback:
            for agent in self.agents.values():
                # Check if agent has the attribute before setting
                if hasattr(agent, 'websocket_callback'):
                    agent.websocket_callback = websocket_callback
                else:
                    # Optionally log a warning if an agent can't accept the callback
                    logger.warning(f"Agent {type(agent).__name__} does not support websocket_callback.")


    async def send_update(self, update_data: dict):
        """Helper method to safely send updates via the WebSocket callback."""
        if self.websocket_callback:
            try:
                # Ensure the callback is awaited if it's a coroutine
                # Get current loop and create task to run it concurrently
                loop = asyncio.get_running_loop()
                loop.create_task(self.websocket_callback(update_data))
                # Alternatively, if this method itself is always called from an async context:
                # await self.websocket_callback(update_data)
            except Exception as e:
                logger.error(f"Error sending WebSocket update from Flow: {e}", exc_info=True)
        else:
            # Optional: Log if trying to send update without callback
            logger.debug(f"No websocket_callback configured, update not sent: {update_data}")

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """Get the primary agent for the flow"""
        return self.agents.get(self.primary_agent_key)

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """Get a specific agent by key"""
        return self.agents.get(key)

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """Add a new agent to the flow"""
        self.agents[key] = agent
        # Also update the new agent's callback if the flow has one
        if self.websocket_callback and hasattr(agent, 'websocket_callback'):
            agent.websocket_callback = self.websocket_callback

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """Execute the flow with given input"""
        pass # Ensure pass is here if no other code in the block
