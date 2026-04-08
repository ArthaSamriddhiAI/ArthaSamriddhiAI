"""Domain exception hierarchy."""

from __future__ import annotations


class ArthaError(Exception):
    """Base exception for all Samriddhi AI errors."""


class ValidationError(ArthaError):
    """Invalid input or state."""


class NotFoundError(ArthaError):
    """Requested entity not found."""


class RuleViolationError(ArthaError):
    """Action violates a governance rule."""

    def __init__(self, rule_id: str, message: str) -> None:
        self.rule_id = rule_id
        super().__init__(f"Rule {rule_id}: {message}")


class ExecutionHaltedError(ArthaError):
    """Kill switch is active — execution is halted."""


class LLMError(ArthaError):
    """Error communicating with LLM provider."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"LLM [{provider}]: {message}")


class EscalationRequiredError(ArthaError):
    """Action requires human approval before proceeding."""

    def __init__(self, decision_id: str, reason: str) -> None:
        self.decision_id = decision_id
        self.reason = reason
        super().__init__(f"Escalation required for {decision_id}: {reason}")
