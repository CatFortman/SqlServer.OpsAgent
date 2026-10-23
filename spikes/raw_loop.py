from typing import Any

import json

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
                            "count": {"type": "integer", "minimum": 1},
                        },
                    },
                },
                "required": ["title", "start", "end"],
            },
            "strict": True,
            "additionalProperties": False
        },
        {
            "name": "list_calendar_events",
            "description": "List all calendar events on a given date.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                },
                "required": ["date"],
            },
            "strict": True,
            "additionalProperties": False
        },
    ]

    # Function definitions for handling different stop reasons.
    # Each function takes the response and returns a list of tool results or other relevant information.

    def run_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        if name == "create_calendar_event":
            if "attendees" in tool_input and len(tool_input["attendees"]) > 10:
                raise ValueError("Too many attendees (max 10)")
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
        raise ValueError(f"Unknown tool: {name}")

    # Handle all response types
    def handle_response(response: anthropic.types.Message) -> anthropic.types.Message:
        match response.stop_reason:
            case "tool_use":
                return handle_tool_use(response)
            case "max_tokens":
                return handle_truncation(response)
            case "model_context_window_exceeded":
                return handle_context_limit(response)
            case "pause_turn":
                return handle_pause(response)
            case "refusal":
                return handle_refusal(response)
            case _:
                # Handle end_turn and other cases
                return {"role": "user", "content":  next(
                    (block.text for block in response.content if block.type == "text"),
                    "",
                )}

    def handle_tool_use(response: anthropic.types.Message) -> anthropic.types.Message:
        tool_results: list[anthropic.types.ToolResultBlockParam] = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = run_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
                except Exception as exc:
                    # Signal failure so Claude can retry or ask for clarification.
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(exc),
                            "is_error": True,
                        }
                    )
        return {"role": "user", "content": tool_results}

    def handle_truncation(response: anthropic.types.Message) -> anthropic.types.Message:
        print("Response was truncated due to max_tokens limit.")
        # Implement logic to handle truncation, e.g., request more tokens or summarize.
        return {"role": "user", "content": []}

    def handle_context_limit(response: anthropic.types.Message) -> anthropic.types.Message:
        print("Response exceeded model context window.")
        # Implement logic to handle context limit, e.g., summarize or split conversation.
        return {"role": "user", "content": []}


    def handle_pause(response: anthropic.types.Message) -> anthropic.types.Message:
        print("Response was paused.")
        # Implement logic to handle pause, e.g., anthropic.types.Message.
        return {"role": "user", "content": []}


    def handle_refusal(response: anthropic.types.Message) -> list[Any]:
        print("Model refused to answer.")
        # Implement logic to handle refusal, e.g., provide more context or rephrase the question.
        return {"role": "user", "content": []}


    # Keep the full conversation history in a list so each turn sees prior context.
    messages: list[anthropic.types.MessageParam] = [
        {
            "role": "user",
            "content": "Schedule a one-hour all-hands on Monday, March 30, 2026 at 10am with everyone: "
            + ", ".join(f"user{i}@example.com" for i in range(15)),
        }
    ]

    # Send the initial message to Claude, which will likely result in a tool_use stop reason.
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        messages=messages,
    )

    # Print each block in the response content. The tool_use block is an SDK object
    for block in response.content:
        print(f"block type: {block.type}")
        if block.type == "text":
            print(f"text: {block.text}")
        elif block.type == "tool_use":
            print(f"tool_use name: {block.name}")
            print(f"tool_use input: {block.input}")

    # Loop until Claude stops asking for tools. Each iteration runs the requested
    # tool, appends the result to history, and asks Claude to continue.
    for turn in range(max_turns):
        # Handle the tool_use response and run the requested tool(s)
        if response.stop_reason == "tool_use":
            user_message = handle_response(response)
            continue

        messages.append({"role": "assistant", "content": response.content})
        messages.append(user_message)

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )

         # Primary stop condition: the model says why it stopped.
        if response.stop_reason == "end_turn":
            return next(
                (b.text for b in response.content if b.type == "text"), ""
            )

        # max_tokens, refusal, etc. are not success either.
        if turn == max_tokens:
            raise RuntimeError(f"Agent stopped unexpectedly: {response.stop_reason}")

    # Avoid the three anti-patterns on purpose, and write one line each on why they're wrong:
    # an iteration cap as the primary stop condition (keep one only as a backstop, logged as abnormal);
    # treating "the assistant produced text" as completion;
    # parsing the text for "done".

    # 1. Iteration cap as primary stop condition: This can prematurely terminate the conversation before the assistant has completed its task, leading to incomplete or incorrect results.
    # 2. Treating "the assistant produced text" as completion: The assistant may produce text that is not the final answer, and treating it as completion can lead to missing important follow-up actions or clarifications.
    # 3. Parsing the text for "done": This approach is brittle and can fail if the assistant uses different phrasing or if the word "done" appears in a different context, leading to incorrect assumptions about task completion.


if __name__ == "__main__":
    main()
