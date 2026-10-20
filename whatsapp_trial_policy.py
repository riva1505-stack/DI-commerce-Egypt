"""Pure validation for an opt-in WhatsApp test recipient.

No network requests or credentials are handled by this module.
"""
import re


def sandbox_ready(enabled: bool, configured_recipient: str, verified_test_number: str) -> bool:
    if not enabled:
        return False
    recipient = configured_recipient.strip().lstrip("+")
    verified = verified_test_number.strip().lstrip("+")
    return bool(re.fullmatch(r"[1-9][0-9]{9,14}", recipient)
                and recipient == verified)


def sandbox_status(enabled: bool, configured_recipient: str, verified_test_number: str) -> str:
    return "test_recipient_verified" if sandbox_ready(
        enabled, configured_recipient, verified_test_number
    ) else "disabled"
