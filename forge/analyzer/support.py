from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET


class SupportParseError(ValueError):
    """Raised when support DSX metadata cannot be parsed."""


@dataclass(frozen=True)
class SupportAssetHint:
    path: str
    content_type: str = ""
    audience: str = ""
    categories: tuple[str, ...] = ()
    compatibility_base: str = ""
    compatibilities: tuple[str, ...] = ()
    userwords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupportMetadata:
    product_name: str
    store_id: str
    global_id: str
    product_token: str
    artists: tuple[str, ...]
    assets: tuple[SupportAssetHint, ...]


def parse_support_metadata(data: bytes) -> SupportMetadata:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SupportParseError(f"Invalid support DSX XML: {exc}") from exc

    product = root.find("./Products/Product")
    if product is None:
        raise SupportParseError("Support DSX does not contain Products/Product.")

    return SupportMetadata(
        product_name=_value(product),
        store_id=_child_value(product, "StoreID"),
        global_id=_child_value(product, "GlobalID"),
        product_token=_child_value(product, "ProductToken"),
        artists=tuple(_values(product.findall("./Artists/Artist"))),
        assets=tuple(_parse_asset(asset) for asset in product.findall("./Assets/Asset")),
    )


def _parse_asset(asset: ET.Element) -> SupportAssetHint:
    return SupportAssetHint(
        path=_value(asset),
        content_type=_child_value(asset, "ContentType"),
        audience=_child_value(asset, "Audience"),
        categories=tuple(_values(asset.findall("./Categories/Category"))),
        compatibility_base=_child_value(asset, "CompatibilityBase"),
        compatibilities=tuple(_values(asset.findall("./Compatibilities/Compatibility"))),
        userwords=tuple(_values(asset.findall("./Userwords/Userword"))),
    )


def _child_value(parent: ET.Element, name: str) -> str:
    child = parent.find(name)
    if child is None:
        return ""
    return _value(child)


def _values(elements: list[ET.Element]) -> list[str]:
    return [_value(element) for element in elements if _value(element)]


def _value(element: ET.Element) -> str:
    return element.attrib.get("VALUE", "")