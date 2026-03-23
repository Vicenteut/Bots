"""
Personal Assistant Agent — powered by Claude (Anthropic)
Uses claude-opus-4-6 with adaptive thinking and tool use.
"""
import os
import json
import anthropic
from datetime import datetime
from database import (
    add_task, list_tasks, update_task_status, delete_task,
    set_reminder, list_reminders, delete_reminder, check_due_reminders
)

# ─── Tool definitions (Anthropic format) ─────────────────────────────────────

TOOLS = [
    {
        "name": "add_task",
        "description": "Add a new task to the TODO list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":       {"type": "string",  "description": "Short task title"},
                "description": {"type": "string",  "description": "Optional details about the task"},
                "due_date":    {"type": "string",  "description": "Due date in ISO format (YYYY-MM-DD), optional"},
                "priority":    {"type": "string",  "enum": ["low", "medium", "high"], "description": "Task priority"}
            },
            "required": ["title"]
        }
    },
    {
        "name": "list_tasks",
        "description": "List tasks from the TODO list. Can filter by status and/or priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status":   {"type": "string", "enum": ["pending", "in_progress", "completed"],
                             "description": "Filter by status (optional)"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"],
                             "description": "Filter by priority (optional)"}
            }
        }
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The numeric task ID"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "delete_task",
        "description": "Permanently delete a task by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The numeric task ID"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder for a specific date and time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":     {"type": "string", "description": "Reminder title"},
                "remind_at": {"type": "string",
                              "description": "Date and time in ISO format (YYYY-MM-DDTHH:MM:SS)"},
                "message":   {"type": "string", "description": "Optional reminder message/note"}
            },
            "required": ["title", "remind_at"]
        }
    },
    {
        "name": "list_reminders",
        "description": "List upcoming (non-triggered) reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_triggered": {"type": "boolean",
                                      "description": "If true, also show already-triggered reminders"}
            }
        }
    },
    {
        "name": "delete_reminder",
        "description": "Delete a reminder by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "The numeric reminder ID"}
            },
            "required": ["reminder_id"]
        }
    },
    {
        "name": "check_due_reminders",
        "description": "Check if any reminders are currently due and return them.",
        "input_schema": {"type": "object", "properties": {}}
    }
]

SYSTEM_PROMPT = f"""You are a helpful personal assistant. Today is {datetime.now().strftime('%A, %B %d, %Y %H:%M')}.

You help the user manage their tasks and reminders through natural conversation.
- Use tools to read/write data — never make up task IDs or data.
- When listing tasks, format them clearly with ID, priority, and status.
- When listing reminders, show the due date/time clearly.
- Be concise and friendly in your responses.
- Proactively check for due reminders at the start of each conversation turn."""


# ─── Tool executor ────────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == "add_task":
            result = add_task(**inputs)
        elif name == "list_tasks":
            result = list_tasks(**inputs)
        elif name == "complete_task":
            result = update_task_status(inputs["task_id"], "completed")
        elif name == "delete_task":
            result = delete_task(inputs["task_id"])
        elif name == "set_reminder":
            result = set_reminder(**inputs)
        elif name == "list_reminders":
            result = list_reminders(inputs.get("include_triggered", False))
        elif name == "delete_reminder":
            result = delete_reminder(inputs["reminder_id"])
        elif name == "check_due_reminders":
            result = check_due_reminders()
        else:
            result = {"error": f"Unknown tool: {name}"}
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─── Agent loop ───────────────────────────────────────────────────────────────

class ClaudeAssistant:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})
        full_response = ""

        while True:
            # Use streaming with adaptive thinking
            with self.client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                tools=TOOLS,
                messages=self.history
            ) as stream:
                response = stream.get_final_message()

            # Collect text from response
            text_parts = [b.text for b in response.content if b.type == "text"]
            current_text = "".join(text_parts)

            if response.stop_reason == "end_turn":
                self.history.append({"role": "assistant", "content": response.content})
                full_response += current_text
                break

            if response.stop_reason == "tool_use":
                self.history.append({"role": "assistant", "content": response.content})
                if current_text:
                    full_response += current_text + "\n"

                # Execute all requested tools
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"  [tool] {block.name}({json.dumps(block.input)})")
                        result = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })

                self.history.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                self.history.append({"role": "assistant", "content": response.content})
                full_response += current_text
                break

        return full_response

    def reset(self):
        self.history = []


# ─── Interactive CLI ──────────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("  Personal Assistant — Claude (claude-opus-4-6)")
    print("  Type 'exit' to quit, 'reset' to start new conversation")
    print("=" * 60)

    assistant = ClaudeAssistant()

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye!")
            break
        if user_input.lower() == "reset":
            assistant.reset()
            print("Conversation reset.")
            continue

        response = assistant.chat(user_input)
        print(f"\nAssistant: {response}")


if __name__ == "__main__":
    run()
