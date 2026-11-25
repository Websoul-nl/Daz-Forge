"""Decode the two supported UV cache encodings without rescaling float coordinates."""

import numpy as np


def decode_uv_lookup(encoded):
    """Return normalized float32 coordinates from uint16 or normalized float data."""
    data = np.asarray(encoded)
    if data.ndim != 3 or data.shape[-1] != 2 or not data.size:
        raise ValueError("Expected a nonempty H x W x 2 UV lookup")
    if data.dtype.kind == "u" and data.dtype.itemsize == 2:
        return data.astype(np.float32) / 65535
    if data.dtype.kind == "f":
        if not np.isfinite(data).all() or data.min() < -1e-6 or data.max() > 1 + 1e-6:
            raise ValueError("Float UV lookup coordinates must be normalized")
        return np.clip(data, 0, 1).astype(np.float32, copy=False)
    raise ValueError(f"Unsupported UV lookup dtype: {data.dtype}")
