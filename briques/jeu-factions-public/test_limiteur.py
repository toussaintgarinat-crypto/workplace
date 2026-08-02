import limiteur as L


def test_autorise_sous_le_seuil():
    for _ in range(L.MAX_TENTATIVES):
        assert L.autorise("1.2.3.4") is True


def test_refuse_au_dela_du_seuil():
    for _ in range(L.MAX_TENTATIVES):
        L.autorise("1.2.3.4")
    assert L.autorise("1.2.3.4") is False


def test_ip_differente_nest_pas_affectee():
    for _ in range(L.MAX_TENTATIVES + 1):
        L.autorise("1.2.3.4")
    assert L.autorise("5.6.7.8") is True


def test_fenetre_glissante_libere_apres_expiration():
    t0 = 1000.0
    for _ in range(L.MAX_TENTATIVES):
        L.autorise("1.2.3.4", maintenant=t0)
    assert L.autorise("1.2.3.4", maintenant=t0) is False
    assert L.autorise("1.2.3.4", maintenant=t0 + L.FENETRE_S + 1) is True
