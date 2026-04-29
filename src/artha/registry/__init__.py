"""§15.13 — canonical schema registry."""

from artha.registry.schema_registry import (
    DEFAULT_REGISTRY,
    DEFAULT_SCHEMA_VERSION,
    RegistryEntry,
    SchemaNotRegisteredError,
    SchemaRegistry,
    SchemaValidationError,
    SchemaVersionFormatError,
    populate_default_registry,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "DEFAULT_SCHEMA_VERSION",
    "RegistryEntry",
    "SchemaNotRegisteredError",
    "SchemaRegistry",
    "SchemaValidationError",
    "SchemaVersionFormatError",
    "populate_default_registry",
]
