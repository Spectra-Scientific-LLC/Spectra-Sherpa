"""
Data classes and enums used by the DAG execution engine.

Extracted from executor.py for module size reduction.
All types are re-exported from executor.py for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class WorkflowEdge:
    """Represents a connection between two nodes in a workflow."""

    from_node: str  # source node ID
    to_node: str  # target node ID
    from_output: str = "default"  # output port name
    to_input: str = "default"  # input port name


@dataclass
class WorkflowNode:
    """Represents a node instance in a workflow."""

    node_id: str
    node_type: str
    parameters: Dict[str, Any]
    position: Optional[Dict[str, float]] = None  # x, y coordinates for UI


@dataclass
class ValidationIssue:
    """A single workflow validation issue."""

    level: str  # "error" or "warning"
    node_id: Optional[str]  # None for graph-level issues
    port: Optional[str]  # Port name if applicable
    message: str


@dataclass
class ValidationResult:
    """Structured result from workflow validation."""

    issues: List["ValidationIssue"]

    @property
    def is_valid(self) -> bool:
        """True if no errors (warnings are OK)."""
        return not any(i.level == "error" for i in self.issues)

    @property
    def errors(self) -> List["ValidationIssue"]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List["ValidationIssue"]:
        return [i for i in self.issues if i.level == "warning"]

    def to_error_strings(self) -> List[str]:
        """Backward-compatible: return error messages as list of strings."""
        return [i.message for i in self.issues if i.level == "error"]
