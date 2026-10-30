"""Host logging adapter; shared sinks contain no application configuration imports."""

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.core.diagnostic_logging import (
    REDACTION_RULES as REDACTION_RULES,
)
from spectra_sherpa.core.diagnostic_logging import (
    AccessPathFilter as AccessPathFilter,
)
from spectra_sherpa.core.diagnostic_logging import (
    BufferHandler as BufferHandler,
)
from spectra_sherpa.core.diagnostic_logging import (
    LockedRotatingFileHandler as LockedRotatingFileHandler,
)
from spectra_sherpa.core.diagnostic_logging import (
    LoggingConfiguration,
)
from spectra_sherpa.core.diagnostic_logging import (
    RedactingFormatter as RedactingFormatter,
)
from spectra_sherpa.core.diagnostic_logging import (
    _is_console_handler as _is_console_handler,
)
from spectra_sherpa.core.diagnostic_logging import (
    configure_access_logging as configure_access_logging,
)
from spectra_sherpa.core.diagnostic_logging import (
    configure_logging as _configure_logging,
)
from spectra_sherpa.core.diagnostic_logging import (
    log_buffer as log_buffer,
)
from spectra_sherpa.core.diagnostic_logging import (
    os as os,
)
from spectra_sherpa.core.diagnostic_logging import (
    redact_message as redact_message,
)
from spectra_sherpa.core.diagnostic_logging import (
    sys as sys,
)


def configure_logging(level: int | None = None) -> None:
    _configure_logging(
        level,
        configuration=LoggingConfiguration(
            log_buffer_size=settings.log_buffer_size,
            log_file_path=settings.log_file_path,
            log_file_max_bytes=settings.log_file_max_bytes,
            log_file_backup_count=settings.log_file_backup_count,
        ),
    )
