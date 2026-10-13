from __future__ import annotations

from langchain_core.tools import tool
from simpleeval import InvalidExpression, simple_eval


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression and return the result as a string.

    Use this for arithmetic the question requires (sums, percentages, comparisons)
    that isn't already stated verbatim in the document.

    Args:
        expression: A math expression, e.g. "12 * (7 + 3) / 2".

    Returns:
        The numeric result as a string, or "Error: <reason>" if the expression is invalid.
    """
    try:
        result = simple_eval(expression)
    except (InvalidExpression, ZeroDivisionError, SyntaxError, TypeError) as e:
        return f"Error: {e}"
    return str(result)
