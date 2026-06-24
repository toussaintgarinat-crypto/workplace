"""Filtres de source HuntR : blocklist (propagande/désinfo) + allowlist boost/strict."""
from dataclasses import dataclass

import source_filters


@dataclass
class Faux:
    url: str


def _res(*urls):
    return [Faux(u) for u in urls]


def test_starter_blocklist_retire_la_propagande_detat():
    res = _res("https://rt.com/x", "https://example.com/a", "https://edition.rt.com/y")
    out, rapport = source_filters.apply_source_filters(res, {"use_starter_blocklist": True})
    assert [r.url for r in out] == ["https://example.com/a"]   # rt.com et son sous-domaine retirés
    assert rapport["blocked_count"] == 2


def test_blocklist_user():
    res = _res("https://spam.test/a", "https://ok.test/b")
    out, rapport = source_filters.apply_source_filters(res, {"blocklist": ["spam.test"]})
    assert [r.url for r in out] == ["https://ok.test/b"]
    assert rapport["blocked_count"] == 1


def test_allowlist_boost_remonte_sans_supprimer():
    res = _res("https://autre.test/a", "https://prefere.test/b", "https://autre.test/c")
    out, rapport = source_filters.apply_source_filters(
        res, {"allowlist": ["prefere.test"], "allowlist_mode": "boost"})
    assert out[0].url == "https://prefere.test/b"             # remonté en tête
    assert len(out) == 3                                       # rien supprimé
    assert rapport["boosted_count"] == 1


def test_allowlist_strict_ne_garde_que_les_autorises():
    res = _res("https://autre.test/a", "https://prefere.test/b")
    out, _ = source_filters.apply_source_filters(
        res, {"allowlist": ["prefere.test"], "allowlist_mode": "strict"})
    assert [r.url for r in out] == ["https://prefere.test/b"]


def test_sans_filtre_actif_passe_tout():
    res = _res("https://a.test", "https://b.test")
    assert source_filters.has_active_filters({}) is False
    out, _ = source_filters.apply_source_filters(res, {})
    assert len(out) == 2


def test_faux_positif_evite():
    # `notrt.com` ne doit PAS matcher `rt.com`.
    res = _res("https://notrt.com/x")
    out, _ = source_filters.apply_source_filters(res, {"use_starter_blocklist": True})
    assert len(out) == 1
