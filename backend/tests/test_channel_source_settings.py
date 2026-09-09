"""ChannelSourceSettings — the declared per-channel provenance config.

The frozen telemetry contract carries six plain floats and no provenance
marker, so a placeholder constant is indistinguishable on the wire from a
measured value. This setting is how the backend is TOLD which is which. These
tests pin the two properties that matter: an undeclared channel is reported as
``unknown`` (never silently assumed), and a malformed declaration fails loudly
at read time rather than producing a wrong label on a dashboard.
"""

from __future__ import annotations

import pytest
from app.core.config import ChannelSourceSettings
from app.schemas.contracts import CHANNELS


def test_unset_env_declares_nothing_and_every_channel_is_unknown():
    settings = ChannelSourceSettings.from_env(env={})
    assert settings.sources == {}
    for channel in CHANNELS:
        assert settings.source_for(channel) == "unknown"


def test_blank_env_is_treated_as_unset():
    assert ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "   "}).sources == {}


def test_parses_live_and_placeholder_declarations():
    settings = ChannelSourceSettings.from_env(
        env={"SHTAPM_CHANNEL_SOURCES": "vibration=live, pressure=placeholder"}
    )
    assert settings.source_for("vibration") == "live"
    assert settings.source_for("pressure") == "placeholder"


def test_undeclared_channels_stay_unknown_alongside_declared_ones():
    settings = ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "vibration=live"})
    assert settings.source_for("vibration") == "live"
    assert settings.source_for("gas") == "unknown"


def test_unknown_channel_name_fails_loudly():
    with pytest.raises(RuntimeError, match="unknown channel"):
        ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "torque=live"})


def test_unknown_source_value_fails_loudly():
    with pytest.raises(RuntimeError, match="must be one of"):
        ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "vibration=probably"})


def test_a_source_is_never_guessed_from_a_bare_channel_name():
    """`vibration` with no `=live` is malformed, not an implicit claim."""
    with pytest.raises(RuntimeError):
        ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "vibration"})


def test_trailing_and_empty_items_are_tolerated():
    settings = ChannelSourceSettings.from_env(env={"SHTAPM_CHANNEL_SOURCES": "vibration=live,,"})
    assert settings.source_for("vibration") == "live"
