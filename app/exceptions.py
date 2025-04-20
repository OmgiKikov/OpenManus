class ToolError(Exception):
    """Raised when a tool encounters an error."""

    def __init__(self, message):
        self.message = message


class OpenAgentError(Exception):
    """Base exception for all OpenAgent errors"""


class TokenLimitExceeded(OpenAgentError):
    """Exception raised when the token limit is exceeded"""
