from enum import Enum

class Gate(Enum):
    """
    Execution gate state for nodes and edges.

    - `CLOSED`: excluded from current execution.
    - `OPEN`: participates in current execution.
    """
    CLOSED = "CLOSED"
    OPEN = "OPEN"   
