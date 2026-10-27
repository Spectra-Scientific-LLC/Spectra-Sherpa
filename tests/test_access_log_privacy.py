"""Access logs retain diagnostics, not URL query credentials."""

import io
import logging
from pathlib import Path

import pytest
from uvicorn.logging import AccessFormatter

from spectra_sherpa.app.core.logging import AccessPathFilter, configure_access_logging


@pytest.mark.parametrize(
    "target",
    [
        "/api/v1/billing/verify-email?token=synthetic-secret",
        "/api/v1/auth/email-change/confirm?token=synthetic-secret&next=/",
        "/api/data?selection=synthetic-secret",
        "/api/ready",
    ],
)
def test_access_formatter_keeps_path_and_status_without_query(target):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:42", "GET", target, "1.1", 200),
        None,
    )
    formatter = AccessFormatter('%(client_addr)s "%(request_line)s" %(status_code)s', use_colors=False)
    before = formatter.format(record)
    if "?" in target:
        assert "synthetic-secret" in before  # negative control: actual formatter would leak
    assert AccessPathFilter().filter(record)
    after = formatter.format(record)
    assert "synthetic-secret" not in after
    assert "?" not in after
    assert f"GET {target.partition('?')[0]} HTTP/1.1" in after
    assert "200" in after and "127.0.0.1:42" in after


def test_access_filter_installed_once_before_existing_handler():
    logger = logging.getLogger("uvicorn.access")
    old = logger.handlers[:], logger.filters[:], logger.level, logger.propagate
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(AccessFormatter("%(request_line)s %(status_code)s", use_colors=False))
    try:
        logger.handlers, logger.filters = [handler], []
        logger.setLevel(logging.INFO)
        logger.propagate = False
        configure_access_logging()
        configure_access_logging()
        assert len(logger.filters) == 1
        logger.info('%s - "%s %s HTTP/%s" %d', "local", "POST", "/verify?token=synthetic-secret", "1.1", 403)
        assert output.getvalue().strip() == "POST /verify HTTP/1.1 403 Forbidden"
    finally:
        logger.handlers, logger.filters, logger.level, logger.propagate = old


def test_public_proxy_access_format_omits_query_and_referrer():
    config = (Path(__file__).resolve().parents[1] / "frontend/nginx.conf").read_text()
    format_body = config.split("log_format sherpa_access ", 1)[1].split(";", 1)[0]
    assert "$request_method $uri $server_protocol" in format_body
    assert "$status" in format_body
    for forbidden in ("$request'", '$request"', "$request_uri", "$args", "$query_string", "$http_referer"):
        assert forbidden not in format_body
    assert "access_log /var/log/nginx/access.log sherpa_access;" in config
