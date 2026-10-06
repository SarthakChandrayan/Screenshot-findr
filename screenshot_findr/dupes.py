"""Find screenshots that look (almost) the same, using a perceptual 'difference hash'."""

from __future__ import annotations

import re
from typing import Callable, Optional

from PIL import Image

HASH_SIZE = 16  # 16x16 bits = 256-bit hash: fine enough to tell similar UIs apart
DEFAULT_MAX_DISTANCE = 10  # bits out of 256 that may differ


def dhash(path: str) -> Optional[str]:
    """256-bit difference hash as a hex string, or None if the image can't be read."""
    try:
        with Image.open(path) as img:
            small = img.convert("L").resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS)
    except Exception:
        return None
    px = small.tobytes()  # one byte per pixel in "L" mode
    bits = 0
    for row in range(HASH_SIZE):
        offset = row * (HASH_SIZE + 1)
        for col in range(HASH_SIZE):
            bits = (bits << 1) | (px[offset + col] > px[offset + col + 1])
    return f"{bits:0{HASH_SIZE * HASH_SIZE // 4}x}"


def distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def similar_text(a: str, b: str, min_overlap: float = 0.6) -> bool:
    """True when two OCR texts share most of their words (or both have none).

    Mostly-white screenshots (documents, chats) can have close hashes even when
    they show different things; the text tells them apart.
    """
    wa = set(re.findall(r"\w{2,}", a.lower()))
    wb = set(re.findall(r"\w{2,}", b.lower()))
    if not wa and not wb:
        return True
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= min_overlap


def group(items: list[tuple[int, str]], max_distance: int = DEFAULT_MAX_DISTANCE,
          same: Optional[Callable[[int, int], bool]] = None) -> list[list[int]]:
    """Group ids whose hashes are within max_distance of each other (union-find).

    `same(id_a, id_b)` can veto a match, e.g. when the texts differ.

    Pigeonhole trick: split the hash into max_distance+1 bands. Two hashes that
    differ in at most max_distance bits must agree exactly on at least one band,
    so only hashes sharing a band are compared. Fast even for huge folders.
    """
    ids = [i for i, _ in items]
    values = [int(h, 16) for _, h in items]
    parent = list(range(len(ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    total_bits = HASH_SIZE * HASH_SIZE
    bands = max_distance + 1
    edges = [round(k * total_bits / bands) for k in range(bands + 1)]
    checked: set[tuple[int, int]] = set()
    for b in range(bands):
        lo, width = edges[b], edges[b + 1] - edges[b]
        mask = (1 << width) - 1
        buckets: dict[int, list[int]] = {}
        for idx, v in enumerate(values):
            buckets.setdefault((v >> lo) & mask, []).append(idx)
        for members in buckets.values():
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    i, j = members[x], members[y]
                    if (i, j) in checked:
                        continue
                    checked.add((i, j))
                    if bin(values[i] ^ values[j]).count("1") <= max_distance and (
                        same is None or same(ids[i], ids[j])
                    ):
                        ri, rj = find(i), find(j)
                        if ri != rj:
                            parent[rj] = ri

    groups: dict[int, list[int]] = {}
    for idx in range(len(ids)):
        groups.setdefault(find(idx), []).append(ids[idx])
    return [g for g in groups.values() if len(g) > 1]
