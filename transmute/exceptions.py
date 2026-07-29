"""Custom exceptions for transmute."""


class TransmuteError(Exception):
    """Base exception for all transmute errors."""


class ConfigurationError(TransmuteError):
    """Raised when configuration is missing or invalid."""


class MigrationError(TransmuteError):
    """Raised when a migration fails to execute."""


class RepositoryError(TransmuteError):
    """Raised when the migrations tracking table has an issue."""


class ScriptError(TransmuteError):
    """Raised when a migration file cannot be loaded or parsed."""

