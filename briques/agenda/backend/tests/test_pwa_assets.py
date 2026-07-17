def test_png_icone_signature():
    from services.icones import png_icone
    data = png_icone(192)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100
