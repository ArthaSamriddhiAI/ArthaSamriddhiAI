"""YAML rule loader — loads rule definitions from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from artha.common.clock import get_clock
from artha.governance.rules.models import (
    Rule,
    RuleCategory,
    RuleSet,
    RuleSeverity,
)


def load_rules_from_yaml(file_path: Path) -> list[Rule]:
    """Load rules from a YAML file."""
    with open(file_path) as f:
        data = yaml.safe_load(f)

    rules = []
    for rule_data in data.get("rules", []):
        rules.append(
            Rule(
                name=rule_data["name"],
                description=rule_data.get("description", ""),
                category=RuleCategory(rule_data["category"]),
                severity=RuleSeverity(rule_data.get("severity", "hard")),
                condition=rule_data["condition"],
                parameters=rule_data.get("parameters", {}),
                enabled=rule_data.get("enabled", True),
            )
        )
    return rules


def load_rule_set_from_directory(rules_dir: Path) -> RuleSet:
    """Load all YAML rule files from a directory into a single RuleSet."""
    all_rules: list[Rule] = []
    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        all_rules.extend(load_rules_from_yaml(yaml_file))
    return RuleSet(rules=all_rules, created_at=get_clock().now())
