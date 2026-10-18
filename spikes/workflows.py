from concurrent.futures import ThreadPoolExecutor

from util import extract_xml, llm_call


def chain(input :str, prompts: list[str]) -> str:
    """
    Chains multiple prompts together, passing the output of one as the input to the next.
    """
    result = input
    for i, prompt in enumerate(prompts):
        print(f"Running prompt {i}: {prompt.format(input=result)}")
        result = llm_call(prompt.format(input=result))
        print(f"Result {i}: {result}")
    return result


def parallel(prompt: str, inputes: list[str], n_workers: int = 3) -> list[str]:
    """
    Processes multiple inputs in parallel using the same prompt.
    """
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(llm_call, prompt.format(input=input)) for input in inputes]
        return [future.result() for future in futures]


def route(input: str, routes: dict[str, str]) -> str:
    """
    Routes the input through a chain of prompts, and then processes multiple inputs in parallel.
    """
    # First determine appropriate route using LLM with chain-of-thought
    print(f"\Available routes: {list(routes.keys())}")
    selector_prompt = f"""
    Analyze the input and select the most appropriate route from the following options: {list(routes.keys())}.
    First explain your reasoning, then provide your selection in this XML format:

    <reasoning>
    Breif explanation of why this should be routed to the selected option.
    Consider key terms, user intent, and urgency level.
    </reasoning>

    <selection>
    The selected route from the available options.
    </selection>

    Input: {input}
    """.strip()

    route_response = llm_call(selector_prompt)
    reasoning = extract_xml(route_response, "reasoning")
    selection = extract_xml(route_response, "selection")

    print(f"Route reasoning: {reasoning}")
    print(f"\nSelected route: {selection}")

    # Process input with the selected specialized prompt
    specialized_prompt = routes[selection]
    return llm_call(specialized_prompt.format(input=input))


