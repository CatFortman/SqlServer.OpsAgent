import json
from typing import Any

import anthropic


def main() -> None:
    # Create a client. It reads ANTHROPIC_API_KEY from the environment.
    client = anthropic.Anthropic()

    # Store model
    model = "claude-haiku-5-5"

    # Store max tokens
    max_tokens = 1024

    # Iteration cap
    max_turns = 20  # backstop only, set well above what a normal run needs

    # Define one tool. The input_schema is a JSON Schema object describing
    # the arguments Claude should pass when it calls this tool. This schema
    # includes nested objects (recurrence), arrays (attendees), and optional
    # fields, which is closer to real-world tools than a flat string argument.
    tools: list[anthropic.types.ToolParam] = [
        {
            "name": "create_calendar_event",
            "description": "Create a calendar event with attendees and optional recurrence.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "format": "date-time"},
                    "end": {"type": "string", "format": "date-time"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string", "format": "email"},
                    },
                    "recurrence": {
                        "type": "object",
                        "properties": {
                            "frequency": {"enum": ["daily", "weekly", "monthly"]},
                            "count": {
                                "type": "integer",
                                "description": "Number of occurrences. Must be at least 1.",
                            },
                        },
                        "additionalProperties": False
                    },
                },
                "additionalProperties": False,
                "required": ["title", "start", "end"]
            },
        },
        {
            "name" : "check_blocking",
            "description": "Checks if database is blocked.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "database_name": {"type": "string"},
                },
                "additionalProperties": False,
                "required": ["database_name"]
            },
        },
        {
            "name": "list_calendar_events",
            "description": "List all calendar events on a given date.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                },
                "required": ["date"],                
                "additionalProperties": False
            },
        },
    ]

    # Function definitions for handling different stop reasons.
    # Each function takes the response and returns a list of tool results or other relevant information.
    def run_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        if name == "create_calendar_event":
            if "attendees" in tool_input and len(tool_input["attendees"]) > 10:
                raise ValueError("Too many attendees (max 10)")
            recurrence = tool_input.get("recurrence")
            if recurrence and recurrence.get("count", 1) < 1:
                raise ValueError("recurrence.count must be at least 1")
            return {
                "event_id": "evt_123",
                "status": "created",
                "title": tool_input["title"],
            }
        if name == "list_calendar_events":
            return {
                "events": [
                    {"title": "Existing meeting", "start": "14:00", "end": "15:00"}
                ]
            }
        if name == "check_blocking":
            return {
                "database_name": tool_input["database_name"],
                "status": "non-blocking"
            }
        raise ValueError(f"Unknown tool: {name}")

    # Print every block in a response so each turn of the loop is visible.
    def print_response(response: anthropic.types.Message) -> None:
        print(f"[response] stop_reason={response.stop_reason}, {len(response.content)} block(s)")
        for i, block in enumerate(response.content):
            if block.type == "text":
                print(f"  [{i}] text: {block.text}")
            elif block.type == "tool_use":
                print(f"  [{i}] tool_use: {block.name} id={block.id} input={block.input}")
            else:
                print(f"  [{i}] {block.type}")

    # Handle all response types
    def handle_response(response: anthropic.types.Message) -> anthropic.types.MessageParam | None:
        print(f"[handle_response] branch: {response.stop_reason}")
        match response.stop_reason:
            case "tool_use":
                return handle_tool_use(response)
            case "max_tokens":
                return handle_truncation(response)
            case "model_context_window_exceeded":
                return handle_context_limit(response)
            case "pause_turn":
                return None
            case "refusal":
                return handle_refusal(response)
            case "end_turn": 
                return None
            case _:
                # Throw error
                raise RuntimeError(f"Unexpected agent stop reason: {response.stop_reason}")

    def handle_tool_use(response: anthropic.types.Message) -> anthropic.types.MessageParam:
        tool_results: list[anthropic.types.ToolResultBlockParam] = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"[handle_tool_use] running {block.name} (id={block.id})")
                try:
                    result = run_tool(block.name, block.input)
                    print(f"[handle_tool_use]   ok: {result}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
                except Exception as exc:
                    print(f"[handle_tool_use]   error: {exc}")
                    # Signal failure so Claude can retry or ask for clarification.
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(exc),
                            "is_error": True,
                        }
                    )
        print(f"[handle_tool_use] sending {len(tool_results)} tool_result(s) in one user message")
        return {"role": "user", "content": tool_results}

    def handle_truncation(response: anthropic.types.Message) -> anthropic.types.MessageParam:
        print("Response was truncated due to max_tokens limit.")
        
        # Print last text
        for b in response.content:
            if b.type == "text":
                print(b.text)

        # Throw exception or request more tokens or summarize.
        raise RuntimeError("Response truncated at max_tokens")

    def handle_context_limit(response: anthropic.types.Message) -> anthropic.types.MessageParam:
        print("Response exceeded model context window.")

        # Print last text
        for b in response.content:
            if b.type == "text":
                print(b.text)

        # Implement logic to handle context limit, e.g., summarize or split conversation.
        raise RuntimeError("Response exceeded model context window")

    def handle_refusal(response: anthropic.types.Message) -> anthropic.types.MessageParam:
        print("Model refused to answer.")
        # Implement logic to handle refusal, e.g., provide more context or rephrase the question.
        raise RuntimeError("Response declined for safety reasons")


    # Keep the full conversation history in a list so each turn sees prior context.
    messages: list[anthropic.types.MessageParam] = [
        {
            "role": "user",
            "content": "Schedule a one-hour all-hands on Monday, March 30, 2026 at 10am with everyone: "
            + ", ".join(f"user{i}@example.com" for i in range(15)) + ". Check blocking on SalesDB and InventoryDB.",
        }
    ]

    # Loop until Claude stops asking for tools. Each iteration runs the requested
    # tool, appends the result to history, and asks Claude to continue.
    for _ in range(max_turns):
        print(f"\n===== API call ({len(messages)} message(s) in history) =====")
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )
        print_response(response)

        # Handle the tool_use response and run the requested tool(s)
        user_message = handle_response(response)

        # Primary stop condition: the model says why it stopped.
        if user_message is None:
            if response.stop_reason == "end_turn":
                print("[loop] end_turn -> done")
                for b in response.content:
                    if b.type == "text":
                        print(b.text)
                return
            # Append the assistant response unchanged and call the API again with the same tools.
            # Repeat until you get a non-pause_turn stop reason.
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                print("[loop] pause_turn -> calling the API again")
                continue
            raise RuntimeError(f"No message to send for stop_reason={response.stop_reason}")

        messages.append({"role": "assistant", "content": response.content})
        print("[loop] appended assistant message")        

        messages.append(user_message)
        print("[loop] appended user message with tool results")

    # Max turns processed.
    raise RuntimeError(f"Agent exceeded {max_turns} turns")

if __name__ == "__main__":
    main()
