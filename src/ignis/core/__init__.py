"""Core logic: host command execution, catalog, hardware, state, logging.

Nothing in this package may import ``gi`` — these modules must stay
importable (and unit-testable) on any OS. See CLAUDE.md.
"""
