# tool/planning.py
import os
import json
from typing import Dict, List, Literal, Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, ToolResult


_PLANNING_TOOL_DESCRIPTION = """
A planning tool that allows the agent to create and manage plans for solving complex tasks.
The tool provides functionality for creating plans, updating plan steps, and tracking progress.
This tool helps with breaking down tasks, tracking completion, and ensuring methodical execution.
"""


class PlanningTool(BaseTool):
    """
    A planning tool that allows the agent to create and manage plans for solving complex tasks.
    The tool provides functionality for creating plans, updating plan steps, and tracking progress.
    """

    name: str = "planning"
    description: str = _PLANNING_TOOL_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "description": "The command to execute. Available commands: create, update, list, get, set_active, mark_step, delete, add_step, reorder_steps, save_to_file, load_from_file, adapt_plan.",
                "enum": [
                    "create",
                    "update",
                    "list",
                    "get",
                    "set_active",
                    "mark_step",
                    "delete",
                    "add_step",
                    "reorder_steps",
                    "save_to_file",
                    "load_from_file",
                    "adapt_plan"
                ],
                "type": "string",
            },
            "plan_id": {
                "description": "Unique identifier for the plan. Required for create, update, set_active, and delete commands. Optional for get and mark_step (uses active plan if not specified).",
                "type": "string",
            },
            "title": {
                "description": "Title for the plan. Required for create command, optional for update command.",
                "type": "string",
            },
            "steps": {
                "description": "List of plan steps. Required for create command, optional for update command.",
                "type": "array",
                "items": {"type": "string"},
            },
            "step_index": {
                "description": "Index of the step to update (0-based). Required for mark_step command.",
                "type": "integer",
            },
            "step_status": {
                "description": "Status to set for a step. Used with mark_step command.",
                "enum": ["not_started", "in_progress", "completed", "blocked"],
                "type": "string",
            },
            "step_notes": {
                "description": "Additional notes for a step. Optional for mark_step command.",
                "type": "string",
            },
            "context": {
                "description": "Context information to help with plan adaptation. Used with adapt_plan command.",
                "type": "string",
            },
            "progress_report": {
                "description": "Progress report on completed steps. Used with adapt_plan command.",
                "type": "string",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    plans: dict = {}  # Dictionary to store plans by plan_id
    _current_plan_id: Optional[str] = None  # Track the current active plan
    _workspace_dir: str = "workspace"  # Directory for saving plans

    def __init__(self, workspace_dir="workspace"):
        """Initialize the PlanningTool with optional workspace directory."""
        super().__init__()
        self._workspace_dir = workspace_dir
        # Create workspace directory if it doesn't exist
        os.makedirs(os.path.join(self._workspace_dir, "plans"), exist_ok=True)

    async def execute(
        self,
        *,
        command: Literal[
            "create", "update", "list", "get", "set_active", "mark_step", "delete",
            "add_step", "reorder_steps", "save_to_file", "load_from_file", "adapt_plan"
        ],
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        step_index: Optional[int] = None,
        step_status: Optional[
            Literal["not_started", "in_progress", "completed", "blocked"]
        ] = None,
        step_notes: Optional[str] = None,
        context: Optional[str] = None,
        progress_report: Optional[str] = None,
        **kwargs,
    ):
        """
        Execute the planning tool with the given command and parameters.

        Parameters:
        - command: The operation to perform
        - plan_id: Unique identifier for the plan
        - title: Title for the plan (used with create command)
        - steps: List of steps for the plan (used with create command)
        - step_index: Index of the step to update (used with mark_step command)
        - step_status: Status to set for a step (used with mark_step command)
        - step_notes: Additional notes for a step (used with mark_step command)
        - context: Context information for plan adaptation
        - progress_report: Report on completed steps for plan adaptation
        """

        if command == "create":
            result = self._create_plan(plan_id, title, steps)
            self._save_plan_to_file(plan_id)
            return result
        elif command == "update":
            result = self._update_plan(plan_id, title, steps)
            self._save_plan_to_file(plan_id)
            return result
        elif command == "list":
            return self._list_plans()
        elif command == "get":
            return self._get_plan(plan_id)
        elif command == "set_active":
            return self._set_active_plan(plan_id)
        elif command == "mark_step":
            result = self._mark_step(plan_id, step_index, step_status, step_notes)
            self._save_plan_to_file(plan_id)
            return result
        elif command == "delete":
            result = self._delete_plan(plan_id)
            self._delete_plan_file(plan_id)
            return result
        elif command == "add_step":
            result = self._add_step(plan_id, kwargs.get("new_step"), kwargs.get("position"))
            self._save_plan_to_file(plan_id)
            return result
        elif command == "reorder_steps":
            result = self._reorder_steps(plan_id, kwargs.get("new_order"))
            self._save_plan_to_file(plan_id)
            return result
        elif command == "save_to_file":
            return self._save_plan_to_file_command(plan_id)
        elif command == "load_from_file":
            return self._load_plan_from_file_command(plan_id)
        elif command == "adapt_plan":
            result = self._adapt_plan(plan_id, steps, context, progress_report)
            self._save_plan_to_file(plan_id)
            return result
        else:
            raise ToolError(
                f"Unrecognized command: {command}. Allowed commands are: create, update, list, get, set_active, mark_step, delete, add_step, reorder_steps, save_to_file, load_from_file, adapt_plan"
            )

    def _create_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """Create a new plan with the given ID, title, and steps."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: create")

        if plan_id in self.plans:
            raise ToolError(
                f"A plan with ID '{plan_id}' already exists. Use 'update' to modify existing plans."
            )

        if not title:
            raise ToolError("Parameter `title` is required for command: create")

        if (
            not steps
            or not isinstance(steps, list)
            or not all(isinstance(step, str) for step in steps)
        ):
            raise ToolError(
                "Parameter `steps` must be a non-empty list of strings for command: create"
            )

        # Create a new plan with initialized step statuses
        plan = {
            "plan_id": plan_id,
            "title": title,
            "steps": steps,
            "step_statuses": ["not_started"] * len(steps),
            "step_notes": [""] * len(steps),
        }

        self.plans[plan_id] = plan
        self._current_plan_id = plan_id  # Set as active plan

        return ToolResult(
            output=f"Plan created successfully with ID: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _update_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """Update an existing plan with new title or steps."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: update")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]

        if title:
            plan["title"] = title

        if steps:
            if not isinstance(steps, list) or not all(
                isinstance(step, str) for step in steps
            ):
                raise ToolError(
                    "Parameter `steps` must be a list of strings for command: update"
                )

            # Manus-style intelligent plan adaptation
            old_steps = plan["steps"]
            old_statuses = plan["step_statuses"]
            old_notes = plan["step_notes"]

            # Track mappings from new step indexes to old step indexes
            step_mappings = {}

            # First pass: Identify exact matches
            for new_idx, new_step in enumerate(steps):
                for old_idx, old_step in enumerate(old_steps):
                    if new_step.strip().lower() == old_step.strip().lower():
                        step_mappings[new_idx] = old_idx
                        break

            # Second pass: Try fuzzy matching for unmatched steps
            unmatched_new_idxs = [i for i in range(len(steps)) if i not in step_mappings]
            for new_idx in unmatched_new_idxs:
                new_step = steps[new_idx]

                # Find the best matching old step that hasn't been matched yet
                best_match_idx = None
                best_match_score = 0
                for old_idx, old_step in enumerate(old_steps):
                    if old_idx not in step_mappings.values():
                        # Simple similarity based on shared words
                        new_words = set(new_step.lower().split())
                        old_words = set(old_step.lower().split())
                        shared_words = len(new_words.intersection(old_words))

                        if shared_words > best_match_score:
                            best_match_score = shared_words
                            best_match_idx = old_idx

                if best_match_score > 0:
                    step_mappings[new_idx] = best_match_idx

            # Create new status and notes arrays
            new_statuses = []
            new_notes = []

            for new_idx in range(len(steps)):
                if new_idx in step_mappings:
                    # Use status and notes from the matching old step
                    old_idx = step_mappings[new_idx]
                    new_statuses.append(old_statuses[old_idx])
                    new_notes.append(old_notes[old_idx])
                else:
                    # No match found, mark as not_started
                    new_statuses.append("not_started")
                    new_notes.append("")

            # Check if steps that were in_progress but no longer in plan need to be replaced
            had_in_progress = False
            for old_idx, status in enumerate(old_statuses):
                if status == "in_progress" and old_idx not in step_mappings.values():
                    had_in_progress = True
                    break

            # If we lost an in_progress step, mark the first not_completed step as in_progress
            if had_in_progress:
                for i, status in enumerate(new_statuses):
                    if status != "completed":
                        new_statuses[i] = "in_progress"
                        break

            plan["steps"] = steps
            plan["step_statuses"] = new_statuses
            plan["step_notes"] = new_notes

        return ToolResult(
            output=f"Plan updated successfully: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _list_plans(self) -> ToolResult:
        """List all available plans."""
        if not self.plans:
            return ToolResult(
                output="No plans available. Create a plan with the 'create' command."
            )

        output = "Available plans:\n"
        for plan_id, plan in self.plans.items():
            current_marker = " (active)" if plan_id == self._current_plan_id else ""
            completed = sum(
                1 for status in plan["step_statuses"] if status == "completed"
            )
            total = len(plan["steps"])
            progress = f"{completed}/{total} steps completed"
            output += f"• {plan_id}{current_marker}: {plan['title']} - {progress}\n"

        return ToolResult(output=output)

    def _get_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Get details of a specific plan."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]
        return ToolResult(output=self._format_plan(plan))

    def _set_active_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Set a plan as the active plan."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: set_active")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        self._current_plan_id = plan_id
        return ToolResult(
            output=f"Plan '{plan_id}' is now the active plan.\n\n{self._format_plan(self.plans[plan_id])}"
        )

    def _mark_step(
        self,
        plan_id: Optional[str],
        step_index: Optional[int],
        step_status: Optional[str],
        step_notes: Optional[str],
    ) -> ToolResult:
        """Mark a step with a specific status and optional notes."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if step_index is None:
            raise ToolError("Parameter `step_index` is required for command: mark_step")

        plan = self.plans[plan_id]

        if step_index < 0 or step_index >= len(plan["steps"]):
            raise ToolError(
                f"Invalid step_index: {step_index}. Valid indices range from 0 to {len(plan['steps'])-1}."
            )

        if step_status and step_status not in [
            "not_started",
            "in_progress",
            "completed",
            "blocked",
        ]:
            raise ToolError(
                f"Invalid step_status: {step_status}. Valid statuses are: not_started, in_progress, completed, blocked"
            )

        if step_status:
            plan["step_statuses"][step_index] = step_status

        if step_notes:
            plan["step_notes"][step_index] = step_notes

        return ToolResult(
            output=f"Step {step_index} updated in plan '{plan_id}'.\n\n{self._format_plan(plan)}"
        )

    def _delete_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Delete a plan."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: delete")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        del self.plans[plan_id]

        # If the deleted plan was the active plan, clear the active plan
        if self._current_plan_id == plan_id:
            self._current_plan_id = None

        return ToolResult(output=f"Plan '{plan_id}' has been deleted.")

    def _add_step(self, plan_id: Optional[str], new_step: Optional[str], position: Optional[int] = None) -> ToolResult:
        """Add a new step to an existing plan at the specified position."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if not new_step:
            raise ToolError("Parameter `new_step` is required for command: add_step")

        plan = self.plans[plan_id]

        # If position is not specified, add to the end
        if position is None or position > len(plan["steps"]):
            position = len(plan["steps"])

        # Insert the new step at the specified position
        plan["steps"].insert(position, new_step)
        plan["step_statuses"].insert(position, "not_started")
        plan["step_notes"].insert(position, "")

        return ToolResult(
            output=f"Step added at position {position} in plan '{plan_id}'.\n\n{self._format_plan(plan)}"
        )

    def _reorder_steps(self, plan_id: Optional[str], new_order: Optional[List[int]]) -> ToolResult:
        """Reorder steps in a plan according to a new order (list of indices)."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if not new_order:
            raise ToolError("Parameter `new_order` is required for command: reorder_steps")

        plan = self.plans[plan_id]

        # Validate the new order
        if len(new_order) != len(plan["steps"]):
            raise ToolError(f"New order must contain exactly {len(plan['steps'])} indices")

        if set(new_order) != set(range(len(plan["steps"]))):
            raise ToolError("New order must contain each index exactly once")

        # Create reordered lists
        reordered_steps = [plan["steps"][i] for i in new_order]
        reordered_statuses = [plan["step_statuses"][i] for i in new_order]
        reordered_notes = [plan["step_notes"][i] for i in new_order]

        # Update the plan
        plan["steps"] = reordered_steps
        plan["step_statuses"] = reordered_statuses
        plan["step_notes"] = reordered_notes

        return ToolResult(
            output=f"Steps reordered in plan '{plan_id}'.\n\n{self._format_plan(plan)}"
        )

    def _format_plan(self, plan: Dict) -> str:
        """Format a plan for display."""
        output = f"Plan: {plan['title']} (ID: {plan['plan_id']})\n"
        output += "=" * len(output) + "\n\n"

        # Calculate progress statistics
        total_steps = len(plan["steps"])
        completed = sum(1 for status in plan["step_statuses"] if status == "completed")
        in_progress = sum(
            1 for status in plan["step_statuses"] if status == "in_progress"
        )
        blocked = sum(1 for status in plan["step_statuses"] if status == "blocked")
        not_started = sum(
            1 for status in plan["step_statuses"] if status == "not_started"
        )

        output += f"Progress: {completed}/{total_steps} steps completed "
        if total_steps > 0:
            percentage = (completed / total_steps) * 100
            output += f"({percentage:.1f}%)\n"
        else:
            output += "(0%)\n"

        output += f"Status: {completed} completed, {in_progress} in progress, {blocked} blocked, {not_started} not started\n\n"
        output += "Steps:\n"

        # Add each step with its status and notes
        for i, (step, status, notes) in enumerate(
            zip(plan["steps"], plan["step_statuses"], plan["step_notes"])
        ):
            status_symbol = {
                "not_started": "[ ]",
                "in_progress": "[→]",
                "completed": "[✓]",
                "blocked": "[!]",
            }.get(status, "[ ]")

            # Highlight the current in-progress step
            if status == "in_progress":
                output += f"{i}. {status_symbol} {step} (CURRENT)\n"
            else:
                output += f"{i}. {status_symbol} {step}\n"

            if notes:
                output += f"   Notes: {notes}\n"

        return output

    def _get_plan_file_path(self, plan_id: str) -> str:
        """Get the file path for a plan."""
        return os.path.join(self._workspace_dir, "plans", f"{plan_id}.json")

    def _get_todo_file_path(self, plan_id: str) -> str:
        """Get the file path for a todo.md file."""
        return os.path.join(self._workspace_dir, f"todo.md")

    def _save_plan_to_file(self, plan_id: Optional[str] = None) -> None:
        """Save a plan to a file."""
        if not plan_id:
            if not self._current_plan_id:
                return
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            return

        # Save as JSON for internal use
        plan_file_path = self._get_plan_file_path(plan_id)
        with open(plan_file_path, "w") as f:
            json.dump(self.plans[plan_id], f, indent=2)

        # Save as markdown todo.md for user visibility
        todo_file_path = self._get_todo_file_path(plan_id)
        with open(todo_file_path, "w") as f:
            f.write(self._format_plan_markdown(self.plans[plan_id]))

    def _save_plan_to_file_command(self, plan_id: Optional[str] = None) -> ToolResult:
        """Command to save a plan to a file."""
        if not plan_id:
            if not self._current_plan_id:
                raise ToolError("No active plan. Please specify a plan_id or set an active plan.")
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        self._save_plan_to_file(plan_id)
        return ToolResult(
            output=f"Plan '{plan_id}' saved to file successfully.\nJSON: {self._get_plan_file_path(plan_id)}\nMarkdown: {self._get_todo_file_path(plan_id)}"
        )

    def _load_plan_from_file(self, plan_id: str) -> None:
        """Load a plan from a file."""
        plan_file_path = self._get_plan_file_path(plan_id)
        if not os.path.exists(plan_file_path):
            raise ToolError(f"No plan file found for ID: {plan_id}")

        with open(plan_file_path, "r") as f:
            self.plans[plan_id] = json.load(f)

    def _load_plan_from_file_command(self, plan_id: Optional[str] = None) -> ToolResult:
        """Command to load a plan from a file."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: load_from_file")

        self._load_plan_from_file(plan_id)
        self._current_plan_id = plan_id

        return ToolResult(
            output=f"Plan '{plan_id}' loaded from file successfully.\n\n{self._format_plan(self.plans[plan_id])}"
        )

    def _delete_plan_file(self, plan_id: str) -> None:
        """Delete plan files."""
        plan_file_path = self._get_plan_file_path(plan_id)
        if os.path.exists(plan_file_path):
            os.remove(plan_file_path)

        # Only delete todo.md if it's for the current plan
        if plan_id == self._current_plan_id:
            todo_file_path = self._get_todo_file_path(plan_id)
            if os.path.exists(todo_file_path):
                os.remove(todo_file_path)

    def _format_plan_markdown(self, plan: Dict) -> str:
        """Format a plan for display in markdown format (todo.md)."""
        output = f"# {plan['title']}\n\n"
        output += f"**Plan ID:** {plan['plan_id']}\n\n"

        # Progress information
        total_steps = len(plan["steps"])
        completed = sum(1 for status in plan["step_statuses"] if status == "completed")

        output += f"**Progress:** {completed}/{total_steps} steps"
        if total_steps > 0:
            percentage = (completed / total_steps) * 100
            output += f" ({percentage:.1f}%)\n\n"
        else:
            output += " (0%)\n\n"

        # Steps list
        output += "## Steps\n\n"

        for i, (step, status, notes) in enumerate(
            zip(plan["steps"], plan["step_statuses"], plan["step_notes"])
        ):
            checkbox = {
                "not_started": "[ ]",
                "in_progress": "[→]",
                "completed": "[x]",
                "blocked": "[!]",
            }.get(status, "[ ]")

            output += f"{checkbox} {i+1}. {step}\n"

            if notes:
                output += f"   - Notes: {notes}\n"

        output += "\n\n_Generated by OpenManus Planner_"

        return output

    def _adapt_plan(
        self,
        plan_id: Optional[str],
        new_steps: Optional[List[str]],
        context: Optional[str] = None,
        progress_report: Optional[str] = None
    ) -> ToolResult:
        """
        Intelligently adapt a plan based on new information and progress.

        This implements the Manus-style plan adaptation with advanced matching
        and preservation of state. It uses context and progress information
        to make more informed decisions about plan structure.
        """
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if not new_steps or not isinstance(new_steps, list):
            raise ToolError("Parameter `steps` is required for command: adapt_plan")

        plan = self.plans[plan_id]
        original_plan = dict(plan)  # Make a copy for comparison

        # Extract current plan state
        old_steps = plan["steps"]
        old_statuses = plan["step_statuses"]
        old_notes = plan["step_notes"]

        # Step 1: Calculate semantic similarity between old and new steps
        mappings = {}  # Map new step indices to old step indices

        # First pass: exact matches (case-insensitive)
        for new_idx, new_step in enumerate(new_steps):
            for old_idx, old_step in enumerate(old_steps):
                if new_step.strip().lower() == old_step.strip().lower():
                    mappings[new_idx] = old_idx
                    break

        # Second pass: fuzzy matching for remaining steps
        unmatched_new = [i for i in range(len(new_steps)) if i not in mappings]
        matched_old = set(mappings.values())

        for new_idx in unmatched_new:
            new_step = new_steps[new_idx]
            best_match = None
            best_score = 0

            for old_idx, old_step in enumerate(old_steps):
                if old_idx in matched_old:
                    continue  # Skip already matched old steps

                # Compute similarity score (simplistic word overlap approach)
                new_words = set(new_step.lower().split())
                old_words = set(old_step.lower().split())

                # Calculate Jaccard similarity: size of intersection / size of union
                if not new_words or not old_words:
                    continue

                intersection = len(new_words.intersection(old_words))
                union = len(new_words.union(old_words))
                score = intersection / union if union > 0 else 0

                # If the score exceeds our threshold and is better than previous matches
                if score > 0.3 and score > best_score:  # 0.3 is arbitrary threshold
                    best_score = score
                    best_match = old_idx

            if best_match is not None:
                mappings[new_idx] = best_match
                matched_old.add(best_match)

        # Step 2: Check for completed work that was removed from plan
        completed_work_removed = False
        for old_idx, status in enumerate(old_statuses):
            if status == "completed" and old_idx not in mappings.values():
                completed_work_removed = True
                break

        # Step 3: Create new status and notes arrays
        new_statuses = []
        new_notes = []

        for new_idx, new_step in enumerate(new_steps):
            if new_idx in mappings:
                # This step maps to an old step - preserve its status and notes
                old_idx = mappings[new_idx]
                new_statuses.append(old_statuses[old_idx])

                # Augment notes if this step is completed and we have progress info
                if old_statuses[old_idx] == "completed" and progress_report:
                    old_note = old_notes[old_idx]
                    if old_note:
                        new_notes.append(f"{old_note} | {progress_report}")
                    else:
                        new_notes.append(f"Completed with: {progress_report}")
                else:
                    new_notes.append(old_notes[old_idx])
            else:
                # This is a new step
                new_statuses.append("not_started")
                if context:
                    new_notes.append(f"Added during adaptation based on: {context}")
                else:
                    new_notes.append("")

        # Step 4: Handle special cases

        # Case 1: If we had an "in_progress" step that was removed, mark the first non-completed step as in_progress
        had_in_progress_removed = any(
            status == "in_progress" and old_idx not in mappings.values()
            for old_idx, status in enumerate(old_statuses)
        )

        if had_in_progress_removed:
            for i, status in enumerate(new_statuses):
                if status != "completed":
                    new_statuses[i] = "in_progress"
                    new_notes[i] += " | Continuing from previous in-progress work"
                    break

        # Case 2: If no step is marked as in_progress, mark the first non-completed step
        if "in_progress" not in new_statuses and len(new_statuses) > 0:
            for i, status in enumerate(new_statuses):
                if status != "completed":
                    new_statuses[i] = "in_progress"
                    break

        # Update the plan
        plan["steps"] = new_steps
        plan["step_statuses"] = new_statuses
        plan["step_notes"] = new_notes

        # Generate a summary of changes
        output = f"Plan adapted successfully: {plan_id}\n\n"

        # Summarize structural changes
        steps_preserved = len(mappings)
        steps_added = len(new_steps) - steps_preserved
        steps_removed = len(old_steps) - len(mappings.values())

        output += f"Changes Summary:\n"
        output += f"• {steps_preserved} steps preserved from original plan\n"
        output += f"• {steps_added} new steps added\n"
        output += f"• {steps_removed} steps removed from original plan\n"

        if completed_work_removed:
            output += "• WARNING: Some completed work was removed from the plan\n"

        output += "\n" + self._format_plan(plan)

        return ToolResult(output=output)
