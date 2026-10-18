# Ring 1: Single tool, single turn.

import json

import anthropic


def main():
    # Create a client. It reads ANTHROPIC_API_KEY from the environment.
    client = anthropic.Anthropic()

    # Define one tool. The input_schema is a JSON Schema object describing
    # the arguments Claude should pass when it calls this tool. This schema
    # includes nested objects (recurrence), arrays (attendees), and optional
    # fields, which is closer to real-world tools than a flat string argument.
    tools = [
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
        }
    ]

    # Send the user's request along with the tool definition. Claude decides
    # whether to call the tool based on the request and the tool description.
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=1024,
        tools=tools,
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=[
            {
                "role": "user",
                "content": "Schedule a 30-minute sync with alice@example.com and bob@example.com on Monday, March 30, 2026 at 10am.",
            }
        ],
    )

    # When Claude calls a tool, the response has stop_reason "tool_use"
    # and the content array contains a tool_use block alongside any text.
    print(f"stop_reason: {response.stop_reason}")


    # Print each block in the response content. The tool_use block is an SDK object
    for block in response.content:
        print(f"block type: {block.type}")
        if block.type == "text":
            print(block.text)
        elif block.type == "tool_use":
            print(f"tool_use name: {block.name}")
            print(f"tool_use input: {block.input}")


    # Execute the tool. In a real system this would call your calendar API.
    # Here the result is hardcoded to keep the example self-contained.
    result = {"event_id": "evt_123", "status": "created"}

    # Send the result back. The tool_result block goes in a user message and
    # its tool_use_id must match the id from the tool_use block above. The
    # assistant's previous response is included so Claude has the full history.
    followup = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=1024,
        tools=tools,
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=[
            {
                "role": "user",
                "content": "Schedule a 30-minute sync with alice@example.com and bob@example.com on Monday, March 30, 2026 at 10am.",
            },
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": json.dumps(result),
                    }
                ],
            },
        ],
    )

    # With the tool result in hand, Claude produces a final natural-language
    # answer and stop_reason becomes "end_turn".
    print(f"stop_reason: {followup.stop_reason}")
    final_text = next(block for block in followup.content if block.type == "text")
    print(final_text.text)

if __name__ == "__main__":
    main()