"""AST-sandboxed rule evaluation engine.

Rules are Python expressions evaluated in a restricted namespace.
Only safe operations (comparisons, arithmetic, boolean logic) are allowed.
No function calls, imports, or attribute access to arbitrary objects.
"""

from __future__ import annotations

import ast
from typing import Any

from artha.governance.rules.models import Rule, RuleEvaluation, RuleSet

# Whitelist of safe AST node types
SAFE_NODES = frozenset({
    ast.Expression,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Subscript,
    ast.Index,  # Python 3.8 compat, removed in 3.9+ but kept for safety
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
    ast.IfExp,
    ast.Tuple,
    ast.List,
})


class UnsafeExpressionError(Exception):
    """Raised when a rule condition contains unsafe operations."""

    def __init__(self, node_type: str, expression: str) -> None:
        super().__init__(
            f"Unsafe AST node '{node_type}' in expression: {expression}"
        )


def _validate_ast(tree: ast.AST, expression: str) -> None:
    """Walk the AST and reject any node type not in the whitelist."""
    for node in ast.walk(tree):
        if type(node) not in SAFE_NODES:
            raise UnsafeExpressionError(type(node).__name__, expression)


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a rule condition in a sandboxed context.

    Args:
        condition: Python expression string (e.g., "max_single_position <= 0.25")
        context: Variable namespace for the expression

    Returns:
        True if condition passes (is satisfied), False if violated.

    Raises:
        UnsafeExpressionError: If the expression contains disallowed operations.
    """
    tree = ast.parse(condition, mode="eval")
    _validate_ast(tree, condition)
    code = compile(tree, "<rule>", "eval")
    return bool(eval(code, {"__builtins__": {}}, context))


class RuleEngine:
    """Deterministic rule evaluation engine."""

    def evaluate_action(
        self,
        rule_set: RuleSet,
        action_context: dict[str, Any],
    ) -> list[RuleEvaluation]:
        """Evaluate all enabled rules against an action context.

        Args:
            rule_set: The versioned rule set currently in force.
            action_context: Variables available to rule conditions.

        Returns:
            List of RuleEvaluation results, one per enabled rule.
        """
        results: list[RuleEvaluation] = []

        for rule in rule_set.rules:
            if not rule.enabled:
                continue

            # Merge rule parameters into context
            eval_context = {**action_context, **rule.parameters}

            try:
                passed = evaluate_condition(rule.condition, eval_context)
                message = "" if passed else f"Rule '{rule.name}' violated"
            except UnsafeExpressionError:
                raise
            except Exception as e:
                passed = False
                message = f"Rule evaluation error: {e}"

            results.append(
                RuleEvaluation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    passed=passed,
                    condition=rule.condition,
                    context_snapshot=eval_context,
                    message=message,
                )
            )

        return results
