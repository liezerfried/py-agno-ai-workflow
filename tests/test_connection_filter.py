"""
Tests for the Windows-only ConnectionResetError filter.

Background: when running Chainlit on Windows with the default ProactorEventLoop,
asyncio's default exception handler logs a noisy traceback every time the
browser closes a websocket abruptly (refresh, navigate away, close tab).
The exception is `ConnectionResetError [WinError 10054]` raised inside
`_call_connection_lost` — it is benign transport noise, not a bug in this
app. Without filtering, real errors get drowned out.

We want to silence exactly those events without masking anything else.
The function _should_silence_connection_reset is the pure decision rule
isolated so we can test it without standing up an event loop.
"""
from __future__ import annotations

from app import _should_silence_connection_reset


def test_drops_connection_reset_error_instance() -> None:
    assert _should_silence_connection_reset({"exception": ConnectionResetError()}) is True


def test_drops_message_mentioning_winerror_10054() -> None:
    ctx = {"message": "Fatal error in _call_connection_lost: ConnectionResetError(10054, 'An existing connection was forcibly closed by the remote host', None, 10054, None)"}
    assert _should_silence_connection_reset(ctx) is True


def test_drops_message_mentioning_call_connection_lost() -> None:
    # Some Python versions don't include the WinError code in the message but
    # do include the frame name. Both indicators should count.
    ctx = {"message": "exception in _call_connection_lost"}
    assert _should_silence_connection_reset(ctx) is True


def test_does_not_drop_unrelated_exception() -> None:
    # A real RuntimeError must reach the default handler — filter mustn't
    # become a global mute.
    assert _should_silence_connection_reset({"exception": RuntimeError("real bug")}) is False


def test_does_not_drop_unrelated_message() -> None:
    assert _should_silence_connection_reset({"message": "Task was destroyed but it is pending!"}) is False


def test_empty_context_returns_false() -> None:
    # No exception and no message means asyncio is reporting something we
    # have no way to classify — default handler should see it.
    assert _should_silence_connection_reset({}) is False
