class HiveError(Exception):
    """Base class for all errors raised by the Hive engine."""


class IllegalMoveError(HiveError):
    """Raised when a move is not legal in the given game state."""


class InvalidBoardError(HiveError):
    """Raised when a board does not describe a valid game state."""
