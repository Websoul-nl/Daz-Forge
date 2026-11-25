import pytest

from forge.material_converter.naming import g9_character_name, g9_product_name, g9_texture_filename


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Kjaer 8", "Kjaer 9"),
        ("Leanne 8.1", "Leanne 9"),
        ("KOO Seth", "KOO Seth G9"),
        ("KOO Seth G9", "KOO Seth G9"),
        ("Agent 88", "Agent 88 G9"),
    ],
)
def test_character_name_uses_explicit_name(name, expected):
    assert g9_character_name(name) == expected


def test_texture_name_preserves_map_role_udim_and_extension():
    assert g9_texture_filename("Eyes_Color_01_1006.jpg", character_name="Kjaer 8") == (
        "Kjaer9_Eyes_Color_01_1006.jpg"
    )
    assert g9_texture_filename("Body Normal_1002.png", character_name="KOO Seth") == (
        "KOOSethG9_Body Normal_1002.png"
    )
    assert g9_texture_filename("ambiguous-map_1003.tif") == "G9_ambiguous-map_1003.tif"
    assert g9_texture_filename("G9_ambiguous-map_1003.tif") == "G9_ambiguous-map_1003.tif"
    assert g9_texture_filename("Kjaer9_Eye.png", character_name="Kjaer 8") == "Kjaer9_Eye.png"


@pytest.mark.parametrize("filename", ["../../Eye.png", r"C:\Eye.png", "Eye.png:stream", ""])
def test_texture_name_requires_a_basename(filename):
    with pytest.raises(ValueError):
        g9_texture_filename(filename)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Kjaer 8 for Genesis 8.1 Male (G8.1M)", "Kjaer 9 for Genesis 9 (G9)"),
        ("Kjaer 8 - G8F and G8.1F", "Kjaer 9 - G9 and G9"),
        ("Kjaer 8 PBR Skin for Genesis 9", "Kjaer 9 PBR Skin for Genesis 9"),
        ("Kjaer 80 for Genesis 8", "Kjaer 80 for Genesis 9"),
        ("8th Street G8.10 bundle", "8th Street G8.10 bundle"),
    ],
)
def test_product_name_only_replaces_explicit_tokens_or_known_leading_name(source, expected):
    assert g9_product_name(source, character_name="Kjaer 8") == expected


def test_product_name_leaves_ambiguous_character_number_alone():
    assert g9_product_name("Agent 8 for Genesis 8.1 Female") == "Agent 8 for Genesis 9"
