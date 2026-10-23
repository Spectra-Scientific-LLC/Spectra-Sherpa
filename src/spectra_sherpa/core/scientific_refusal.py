"""Closed public projections of scientific admission failures.

Internal exception details remain available to operators and SDK callers.
HTTP consumers use these codes and approved fields, never exception text.
"""

from __future__ import annotations

_MESSAGES = {
    "reference_targets_required": "This workflow requires reference targets for training/evaluation.",
    "target_mismatch": "The saved model's target could not be matched. Bind the matching target before application.",
}


def scientific_refusal_reason(code: str, *, target_name: str | None = None) -> str:
    """Render literal advice and declared public context, not exception args.

    target_name is supplied separately from an authorized model snapshot. It
    must never be recovered from an exception or a client-supplied error field.
    """
    message = _MESSAGES[code]
    if code == "target_mismatch" and target_name is not None:
        return f"Saved model target {target_name!r} could not be matched. Bind the matching target before application."
    return message


class ScientificInputRefusal(ValueError):
    """Scientific refusal whose public classification is independent of args."""

    def __init__(self, code: str, *, detail: str | None = None):
        public_reason = scientific_refusal_reason(code)
        self.code = code
        super().__init__(public_reason if detail is None else detail)

    def __reduce__(self):
        return type(self), (self.code,), {**self.__dict__, "args": self.args}
