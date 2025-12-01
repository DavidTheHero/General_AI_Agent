import ast
import operator
from typing import Any, Union

Number = Union[int, float]

OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}

UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(Exception):
    """Raised when the calculator encounters invalid expressions."""


def _eval(node: ast.AST) -> Number:
    if isinstance(node, ast.Num):  # type: ignore[attr-defined]
        return node.n

    if isinstance(node, ast.BinOp):
        left = _eval(node.left)
        right = _eval(node.right)
        op_type = type(node.op)
        if op_type not in OPERATORS:
            raise CalculatorError(f"Unsupported operator: {op_type.__name__}")
        return OPERATORS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand)
        op_type = type(node.op)
        if op_type not in UNARY_OPERATORS:
            raise CalculatorError(f"Unsupported unary operator: {op_type.__name__}")
        return UNARY_OPERATORS[op_type](operand)

    if isinstance(node, ast.Expression):
        return _eval(node.body)

    raise CalculatorError(f"Unsupported expression component: {type(node).__name__}")


def calculate(expression: str) -> Any:
    """
    Safely evaluate a math expression.

    Supports +, -, *, /, %, //, ** and parentheses.
    """
    if not expression or not expression.strip():
        raise CalculatorError("Expression cannot be empty.")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Invalid expression: {exc}") from exc

    return _eval(tree.body if isinstance(tree, ast.Expression) else tree)
