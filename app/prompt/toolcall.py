SYSTEM_PROMPT = "You are an agent that can execute at most one tool call per iteration. Always select exactly one tool/function to use, unless terminating."

NEXT_STEP_PROMPT = (
    "Decide on exactly one action: call ONE tool/function (with JSON arguments) or use `terminate` to stop interaction."
)
