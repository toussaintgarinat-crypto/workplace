"""Point de contrôle avant éviction d'une session (relai propre entre appareils).

$ cd core && python3 -m pytest test_checkpoint_session.py -v
"""
import logging

import checkpoint_session  # noqa: E402


def test_declencher_checkpoint_ne_leve_jamais(caplog):
    with caplog.at_level(logging.INFO):
        checkpoint_session.declencher_checkpoint("marina")
    assert "marina" in caplog.text
