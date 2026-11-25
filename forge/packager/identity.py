"""Naming and identity for private DIM packages."""

from dataclasses import dataclass
import re
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DimPackageIdentity:
    product_name: str
    package_code: str
    token: str
    version: int
    global_id: str
    store_id: str

    @property
    def package_stem(self) -> str:
        return f"{self.package_code}{self.token.zfill(8)}-{self.version:02d}_{_compact_product_name(self.product_name)}"

    @property
    def support_store_name(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", self.store_id).strip("_").upper() or "LOCAL_USER"

    @property
    def support_path(self) -> str:
        return f"Runtime/Support/{self.support_store_name}_{self.token}_{_support_product_name(self.product_name)}.dsx"

    def metadata(self, product: dict) -> dict:
        return {
            **product, "product_name": self.product_name, "product_token": self.token,
            "global_id": self.global_id, "store_id": self.store_id, "package_version": self.version,
        }


def dim_package_identity(product: dict, product_name: str) -> DimPackageIdentity:
    name = product_name.strip()
    if not name or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF} for c in name):
        raise ValueError("Choose a nonempty XML-safe product name.")

    code = _package_code(product)
    if code.startswith("SHA") and ("&" in name or "#" in name):
        raise ValueError("Remove & and # from the Shards product name to protect Smart Content thumbnails.")
    token = str(product.get("product_token") or "1").strip()
    if not re.fullmatch(r"[0-9]{1,8}", token) or int(token) == 0:
        raise ValueError("The DIM product token must be a positive number with at most eight digits.")
    raw_version = str(product.get("package_version", 1)).strip()
    if not re.fullmatch(r"[0-9]{1,2}", raw_version) or int(raw_version) == 0:
        raise ValueError("Choose a DIM package version from 1 to 99.")
    global_id = str(product.get("global_id") or "").strip()
    if not global_id and int(raw_version) > 1:
        raise ValueError("Reuse the original DIM package GUID when building an update.")
    global_id = global_id or str(uuid4())
    try:
        UUID(global_id)
    except ValueError as exc:
        raise ValueError("Enter a valid DIM package GUID.") from exc
    store_id = str(product.get("store_id") or product.get("store_display_name") or "").strip()
    store_id = store_id or ("3D SHARDS" if code.startswith("SHA") else "LOCAL USER")
    return DimPackageIdentity(name, code, str(int(token)), int(raw_version), global_id, store_id)


def _package_code(product: dict) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]", "", str(product.get("store_prefix") or "")).upper()
    code = re.sub(r"[^A-Za-z0-9]", "", str(product.get("store_code") or "")).upper()
    if prefix.startswith("SHA"):
        artist = prefix[3:] + code
        if not 2 <= len(artist) <= 4:
            raise ValueError("Use a 2 to 4 character Shards artist code after SHA.")
        return "SHA" + artist
    combined = prefix + code or str(product.get("store_id") or product.get("store_display_name") or "LOCAL")
    cleaned = re.sub(r"[^A-Za-z0-9]", "", combined).upper()
    return cleaned[:6] or "LOCAL"


def _compact_product_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value)
    return cleaned or "Product"


def _support_product_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned or "Product"
