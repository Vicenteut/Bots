"""
Personal Assistant Agent — powered by OpenAI
Uses gpt-4o with function calling and streaming.
"""
import os
import json
from datetime import datetime
from openai import OpenAI
from database import (
    add_task, list_tasks, update_task_status, delete_task,
    set_reminder, list_reminders, delete_reminder, check_due_reminders
)

# ─── Tool definitions (OpenAI function-calling format) ────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new task to the TODO list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string",  "description": "Short task title"},
                    "description": {"type": "string",  "description": "Optional details about the task"},
                    "due_date":    {"type": "string",  "description": "Due date in ISO format (YYYY-MM-DD), optional"},
                    "priority":    {"type": "string",  "enum": ["low", "medium", "high"],
                                   "description": "Task priority"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks from the TODO list. Can filter by status and/or priority.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status":   {"type": "string", "enum": ["pending", "in_progress", "completed"],
                                 "description": "Filter by status (optional)"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"],
                                 "description": "Filter by priority (optional)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The numeric task ID"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Permanently delete a task by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The numeric task ID"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a reminder for a specific date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title":     {"type": "string", "description": "Reminder title"},
                    "remind_at": {"type": "string",
                                  "description": "Date and time in ISO format (YYYY-MM-DDTHH:MM:SS)"},
                    "message":   {"type": "string", "description": "Optional reminder message/note"}
                },
                "required": ["title", "remind_at"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List upcoming (non-triggered) reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_triggered": {"type": "boolean",
                                          "description": "If true, also show already-triggered reminders"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete a reminder by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "The numeric reminder ID"}
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_due_reminders",
            "description": "Check if any reminders are currently due and return them.",
            "parameters": {"type": "object", "properties": {}}
        }
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

class OpenAIAssistant:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.history: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        while True:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=self.history,
                tools=TOOLS,
                tool_choice="auto"
            )

            message = response.choices[0].message
            self.history.append(message)

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    name = tool_call.function.name
                    inputs = json.loads(tool_call.function.arguments)
                    print(f"  [tool] {name}({json.dumps(inputs)})")
                    result = execute_tool(name, inputs)
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
            else:
                return message.content or ""

    def reset(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]


# ─── Interactive CLI ──────────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("  Personal Assistant — OpenAI (gpt-4o)")
    print("  Type 'exit' to quit, 'reset' to start new conversation")
    print("=" * 60)

    assistant = OpenAIAssistant()

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
