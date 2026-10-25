    # README
    # 
    # The Agent SDK takes over the following functionality in this loop: 
    #   tool execution - in this file I created a tool execution call and append the tool results to the user message param.
    #                    The SDK runs the whole tool loop, and it also comes with built-in tools.
    #   permissions - This is about whether a tool call is allowed to run (allow, deny or ask a person). This loop runs every tool Claude asks  #                 for, with no check.
    #   hooks - no hoooks are in the agentic loop here. The SDK runs the loop, so it gives you fixed points instead: PreToolUse, PostToolUse, #           Stop.
    #   context management - The SDK summarizes it automatically, while your loop just raises at the limit.
    #   sessions - Messages list lives only in memory and are gone when the script exits. The SDK saves and resumes sessions and conversation #              across runs

    # Avoid the three anti-patterns on purpose, and write one line each on why they're wrong:
    # an iteration cap as the primary stop condition (keep one only as a backstop, logged as abnormal);
    # treating "the assistant produced text" as completion;
    # parsing the text for "done".

    # 1. Iteration cap as primary stop condition: This can prematurely terminate the conversation before 
    # the assistant has completed its task, leading to incomplete or incorrect results.
    # If an agent response takes 12 turns, then an iteration cap of 10 blocks the model from completing the work.
    # Hitting the cap looks the same as a completed run. 
    # A cap can be used as a backup fail-safe to stop the loop after an exessive amount of turns.

    # 2. Treating "the assistant produced text" as completion: The assistant may produce text that is not
    # the final answer, and treating it as completion can lead to missing important follow-up actions or clarifications.
    # Text blocks often accompany tool blocks. Only rely on the stop_reason property, as this is the primary signal for
    # completion.

    # 3. Parsing the text for "done": This approach is brittle and can fail if the assistant 
    # uses different phrasing or if the word "done" appears in a different context, leading to incorrect assumptions about task completion.
    # Processing a keyword block can cause additional blocks that follow the keyword block to stop early.

