"""
Backward-compatible template shim.

Canonical workflow templates live in ``spectra_sherpa/data/templates/*.yaml``.
This module remains so older imports keep working while the rest of the
application reads templates through the declarative loader.
"""

from spectra_sherpa.app.core.template_loader import TemplateLoader

WORKFLOW_TEMPLATES = TemplateLoader().load_all()
