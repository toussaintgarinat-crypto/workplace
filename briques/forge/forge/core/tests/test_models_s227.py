"""S227 : colonnes ajoutées au socle Entité Entreprise unifiée."""
from app.models.generated import OrganizationMembers, Ventures


def test_ventures_a_les_colonnes_s227():
    colonnes = set(Ventures.__table__.columns.keys())
    assert {"geo_object_id", "audit_id", "profil_entreprise"} <= colonnes


def test_organization_members_a_venture_scope():
    assert "venture_scope" in OrganizationMembers.__table__.columns.keys()


def test_init_db_declare_les_migrations_s227():
    from scripts.init_db import MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS geo_object_id TEXT" in MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS audit_id TEXT" in MIGRATIONS_S227
    assert "ALTER TABLE ventures ADD COLUMN IF NOT EXISTS profil_entreprise JSONB" in MIGRATIONS_S227
    assert "ALTER TABLE organization_members ADD COLUMN IF NOT EXISTS venture_scope TEXT" in MIGRATIONS_S227
