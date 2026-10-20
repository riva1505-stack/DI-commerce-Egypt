"""Fail-closed WhatsApp sandbox policy tests; no outbound messaging."""
import pytest

from whatsapp_trial_policy import sandbox_ready, sandbox_status


@pytest.mark.parametrize("enabled,recipient,verified,expected", [
    (False, "201000000000", "201000000000", False),
    (True, "201000000000", "201000000001", False),
    (True, "", "201000000000", False),
    (True, "invalid-number", "invalid-number", False),
    (True, "201000000000", "", False),
    (True, "+201000000000", "201000000000", True),
    (True, "201000000000", "+201000000000", True),
])
def test_test_recipient_opt_in_and_exact_match(enabled, recipient, verified, expected):
    assert sandbox_ready(enabled, recipient, verified) is expected
    assert sandbox_status(enabled, recipient, verified) == (
        "test_recipient_verified" if expected else "disabled"
    )


def test_sandbox_module_has_no_network_sender():
    import whatsapp_trial_policy as module
    assert not hasattr(module, "send_message")
    assert not hasattr(module, "send_whatsapp")
