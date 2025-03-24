import asyncio
import time

from app.agent.manus import Manus
from app.flow.flow_factory import FlowType, FlowFactory
from app.logger import logger


async def run_flow():
    agents = {
        "manus": Manus(),
    }

    try:
        prompt = input("Enter your prompt: ")

        if prompt.strip().isspace() or not prompt:
            logger.warning("Empty prompt provided.")
            return

        flow = FlowFactory.create_flow(
            flow_type=FlowType.PLANNING,
            agents=agents,
        )
        logger.warning("Processing your request...")

        try:
            if hasattr(flow, "planning_tool") and hasattr(flow, "active_plan_id"):
                logger.info(f"Using plan ID: {flow.active_plan_id}")

            start_time = time.time()
            result = await asyncio.wait_for(
                flow.execute(prompt),
                timeout=3600,  # 60 minute timeout for the entire execution
            )
            elapsed_time = time.time() - start_time
            logger.info(f"Request processed in {elapsed_time:.2f} seconds")

            if hasattr(flow, "planning_tool") and hasattr(flow, "active_plan_id"):
                final_plan_result = await flow.planning_tool.execute(
                    command="get",
                    plan_id=flow.active_plan_id
                )
                if hasattr(final_plan_result, "output"):
                    logger.info(f"FINAL PLAN STATUS:\n{final_plan_result.output}")

            logger.info(result)
        except asyncio.TimeoutError:
            logger.error("Request processing timed out after 1 hour")
            logger.info(
                "Operation terminated due to timeout. Please try a simpler request."
            )

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user.")
    except Exception as e:
        logger.error(f"Error: {str(e)}")


if __name__ == "__main__":
    asyncio.run(run_flow())
