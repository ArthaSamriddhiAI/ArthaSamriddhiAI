"""Intent validation and parsing."""

from __future__ import annotations

from artha.common.errors import ValidationError
from artha.governance.intent.models import GovernanceIntent, IntentType


def validate_intent(intent: GovernanceIntent) -> GovernanceIntent:
    """Validate a governance intent before processing."""
    if not intent.symbols:
        raise ValidationError("Intent must specify at least one symbol")

    if intent.intent_type == IntentType.REBALANCE and not intent.holdings:
        raise ValidationError("Rebalance intent requires current holdings")

    if intent.intent_type == IntentType.TRADE_PROPOSAL:
        if "proposed_trades" not in intent.parameters:
            raise ValidationError("Trade proposal requires 'proposed_trades' in parameters")

    return intent
