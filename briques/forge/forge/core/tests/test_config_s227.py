"""S227 : settings des ponts vers geo/audit/ingestion."""
from app.config import Settings


def test_settings_s227_existent():
    s = Settings()
    assert hasattr(s, "GEO_URL")
    assert hasattr(s, "GEO_KEY")
    assert hasattr(s, "AUDIT_URL")
    assert hasattr(s, "INGESTION_URL")
    assert hasattr(s, "INGESTION_KEY")
    assert s.GEO_URL == ""  # vide par défaut = section "indisponible" au lieu de 500
