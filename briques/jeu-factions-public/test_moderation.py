import moderation as M


def test_pseudo_propre_est_autorise():
    assert M.contient_mot_banni("Aria") is False


def test_pseudo_banni_est_detecte():
    assert M.contient_mot_banni("SuperConnard") is True


def test_detection_insensible_a_la_casse():
    assert M.contient_mot_banni("NIQUE tout") is True


# Tests pour éviter les faux positifs (Task 4 review)
def test_faux_positif_dominique_ne_contient_pas_nique_comme_mot():
    """'Dominique' contient 'nique' en substring mais 'nique' n'est pas un mot autonome."""
    assert M.contient_mot_banni("Dominique") is False


def test_faux_positif_dispute_ne_contient_pas_pute_comme_mot():
    """'dispute' contient 'pute' en substring mais 'pute' n'est pas un mot autonome."""
    assert M.contient_mot_banni("dispute") is False


def test_faux_positif_reputee_ne_contient_pas_pute_comme_mot():
    """'réputée' contient 'pute' en substring mais 'pute' n'est pas un mot autonome."""
    assert M.contient_mot_banni("réputée") is False


def test_faux_positif_amputee_ne_contient_pas_pute_comme_mot():
    """'amputée' contient 'pute' en substring mais 'pute' n'est pas un mot autonome."""
    assert M.contient_mot_banni("amputée") is False


def test_mot_banni_frontiere_en_mot_autonome_est_detecte():
    """'pute' seul est un mot autonome et doit être détecté."""
    assert M.contient_mot_banni("pute") is True


def test_mot_banni_frontiere_au_debut_avec_espace_est_detecte():
    """'pute ' en début est un mot autonome et doit être détecté."""
    assert M.contient_mot_banni("pute avec ponctuation") is True


def test_mot_banni_frontiere_entre_espaces_est_detecte():
    """'nique' entre espaces est un mot autonome et doit être détecté."""
    assert M.contient_mot_banni("salut nique toi") is True
