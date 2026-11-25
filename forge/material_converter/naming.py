"""Names for generated G9 materials, not for modifying source products."""

import re
import unicodedata


_GENERATION_LABEL = re.compile(
    r"(?P<long>\bGenesis\s+8(?:\.1)?\b(?!\.\d)(?:\s+(?:Female|Male)\b)?)"
    r"|\bG8(?:\.1)?(?:\s*[FM])?\b(?!\.\d)",
    re.IGNORECASE,
)


def g9_character_name(source_name: str) -> str:
    """Convert a trusted character name, without inferring one from a product."""
    name = source_name.strip()
    if not name:
        raise ValueError("A character name cannot be blank")
    if re.search(r"\s(?:G9|9|Genesis 9)$", name, re.IGNORECASE):
        return name
    converted, count = re.subn(r"\s+8(?:\.1)?$", " 9", name)
    return converted if count else f"{name} G9"


def g9_texture_filename(filename: str, *, character_name: str | None = None) -> str:
    """Prefix a texture basename and preserve its role, tile and extension."""
    if (
        not filename
        or filename.endswith((".", " "))
        or re.search(r'[\\/:%?#*"<>|\x00-\x1f\x7f]', filename)
    ):
        raise ValueError(f"Expected a texture basename: {filename!r}")
    prefix = "G9"
    if character_name and character_name.strip():
        name = g9_character_name(character_name)
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        # If transliteration removed the entire source name, use the generic prefix.
        original_ascii = unicodedata.normalize("NFKD", character_name).encode("ascii", "ignore")
        if re.search(rb"[A-Za-z0-9]", original_ascii):
            prefix = re.sub(r"[^A-Za-z0-9]", "", ascii_name)
    tag = prefix + "_"
    return filename if filename.casefold().startswith(tag.casefold()) else tag + filename


def g9_product_name(source_title: str, *, character_name: str | None = None) -> str:
    """Convert explicit generation labels and an optional known leading name."""
    title = source_title.strip()
    if character_name and character_name.strip():
        source_name = character_name.strip()
        target_name = g9_character_name(source_name)
        target_pattern = rf"^{re.escape(target_name)}(?![\w]|\.\d)"
        if not re.match(target_pattern, title, re.IGNORECASE):
            source_pattern = rf"^{re.escape(source_name)}(?![\w]|\.\d)"
            title = re.sub(source_pattern, lambda _: target_name, title, count=1, flags=re.IGNORECASE)
    return _GENERATION_LABEL.sub(lambda m: "Genesis 9" if m["long"] else "G9", title)
