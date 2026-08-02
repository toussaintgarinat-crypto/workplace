import moderation as M


def test_pseudo_propre_est_autorise():
    assert M.contient_mot_banni("Aria") is False


def test_pseudo_banni_est_detecte():
    assert M.contient_mot_banni("SuperConnard") is True


def test_detection_insensible_a_la_casse():
    assert M.contient_mot_banni("NIQUE tout") is True
