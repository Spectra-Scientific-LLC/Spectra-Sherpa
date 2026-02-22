import subprocess
from unittest.mock import patch

_original_check_output = subprocess.check_output


def _mock_check_output(*args, **kwargs):
    if args and isinstance(args[0], list) and args[0][:2] == ["system_profiler", "-xml"]:
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            b'<plist version="1.0">\n<array>\n<dict>\n'
            b"<key>_name</key><string>Fonts</string>\n"
            b"<key>_items</key><array></array>\n"
            b"</dict>\n</array>\n</plist>"
        )
    return _original_check_output(*args, **kwargs)


_patch = patch("subprocess.check_output", side_effect=_mock_check_output)
_patch.start()
