import os
import email_envoi


def test_envoyer_sans_smtp_host_configure_retourne_simule(monkeypatch):
    """Sans JEU_FACTIONS_PUBLIC_SMTP_HOST configuré, envoyer() retourne "simule"
    et ne tente aucune connexion SMTP."""
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SMTP_HOST", raising=False)
    # Monkeypatch smtplib.SMTP pour attraper les appels (ne devrait pas arriver ici)
    import smtplib
    smtp_called = []
    original_smtp = smtplib.SMTP

    def mock_smtp(*args, **kwargs):
        smtp_called.append(True)
        return original_smtp(*args, **kwargs)

    monkeypatch.setattr("smtplib.SMTP", mock_smtp)

    resultat = email_envoi.envoyer("test@example.com", "Sujet", "Corps")
    assert resultat == "simule"
    assert not smtp_called


def test_envoyer_avec_smtp_host_configure_retourne_envoye(monkeypatch):
    """Avec SMTP configuré, envoyer() retourne "envoye" et appelle les bonnes méthodes."""
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_PORT", "587")
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_USER", "user@example.com")
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_PASSWORD", "password123")
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_FROM", "noreply@example.com")

    # Mock smtplib.SMTP
    calls = {"starttls": 0, "login": 0, "send_message": 0}

    class MockSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            calls["starttls"] += 1

        def login(self, user, password):
            calls["login"] += 1

        def send_message(self, msg):
            calls["send_message"] += 1

    monkeypatch.setattr("smtplib.SMTP", MockSMTP)

    resultat = email_envoi.envoyer("test@example.com", "Sujet", "Corps")
    assert resultat == "envoye"
    assert calls["starttls"] == 1
    assert calls["login"] == 1
    assert calls["send_message"] == 1


def test_envoyer_login_seulement_si_user_configure(monkeypatch):
    """login() n'est appelé que si JEU_FACTIONS_PUBLIC_SMTP_USER est configuré."""
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_PORT", "587")
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SMTP_USER", raising=False)
    monkeypatch.delenv("JEU_FACTIONS_PUBLIC_SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("JEU_FACTIONS_PUBLIC_SMTP_FROM", "noreply@example.com")

    calls = {"login": 0}

    class MockSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            calls["login"] += 1

        def send_message(self, msg):
            pass

    monkeypatch.setattr("smtplib.SMTP", MockSMTP)

    resultat = email_envoi.envoyer("test@example.com", "Sujet", "Corps")
    assert resultat == "envoye"
    assert calls["login"] == 0
