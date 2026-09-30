"""Contest (layered incentive) allocation, reimplemented from the pinned calculator (R-016).

Source of truth: soma `mcp_platform/app/services/incentive_calculator.py`.
Layers are all subsets of the present categories, grouped by size; layer
weights come from the lock and are renormalized over the layers that exist.
Within a layer, weight is split evenly over its elements. Each element goes to
the top subset score (ties within 1e-12 split it). Raw weights are then
normalized over the winners and scaled by (1 - burn_ratio); empty elements are
therefore redistributed, not burned.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import isclose
from typing import Mapping, Sequence

from harness.upstream import load_lock

_I = load_lock()["incentives"]
LAYER_WEIGHTS = {int(size): weight for size, weight in _I["layer_weights_by_subset_size"].items()}
CATEGORY_ORDER = tuple(_I["category_order"])
CATEGORY_WEIGHTS = dict(_I["category_weights"])
TIE_REL, TIE_ABS = _I["tie_rel_tol"], _I["tie_abs_tol"]
FALLBACK = _I["fallback_category"]


@dataclass(frozen=True)
class Element:
    subset: tuple[str, ...]
    weight: float
    winners: tuple[str, ...]
    winning_score: float | None


@dataclass(frozen=True)
class Allocation:
    categories: tuple[str, ...]
    burn_ratio: float
    elements: tuple[Element, ...]
    raw_weights: dict[str, float]
    final_weights: dict[str, float]
    burn_weight: float


def present_categories(labels: Sequence[str | None]) -> tuple[str, ...]:
    """Categories present among task labels, in canonical order; unknown labels are ignored."""
    present = {str(label).strip().lower() for label in labels if label is not None}
    return tuple(c for c in CATEGORY_ORDER if c in present)


def allocate(
    scores: Mapping[str, Mapping[str, float]],
    categories: Sequence[str],
    *,
    burn_ratio: float,
) -> Allocation:
    """`scores[hotkey][category]` → allocation. Pass `[FALLBACK]` when nothing is classified."""
    cats = tuple(dict.fromkeys(str(c) for c in categories))
    layers = [tuple(combinations(cats, size)) for size in range(len(cats), 0, -1)]
    layers = [layer for layer in layers if layer]
    raw_layer = [LAYER_WEIGHTS.get(len(layer[0]), 0.0) for layer in layers]
    total = sum(raw_layer)
    layer_weights = [w / total for w in raw_layer] if total > 0 else [0.0] * len(raw_layer)

    raw: dict[str, float] = {}
    elements: list[Element] = []
    for layer, layer_weight in zip(layers, layer_weights):
        element_weight = layer_weight / len(layer)
        for subset in layer:
            subset_scores = {
                hotkey: value
                for hotkey, miner in scores.items()
                if (value := _subset_score(miner, subset)) is not None
            }
            if not subset_scores:
                elements.append(Element(subset, element_weight, (), None))
                continue
            best = max(subset_scores.values())
            winners = tuple(sorted(h for h, v in subset_scores.items() if isclose(v, best, rel_tol=TIE_REL, abs_tol=TIE_ABS)))
            for winner in winners:
                raw[winner] = raw.get(winner, 0.0) + element_weight / len(winners)
            elements.append(Element(subset, element_weight, winners, best))

    share = max(0.0, 1.0 - float(burn_ratio))
    raw_total = sum(raw.values())
    if raw_total > 0.0 and share > 0.0:
        final = {h: w * share / raw_total for h, w in sorted(raw.items()) if w > 0.0}
        burn = max(0.0, 1.0 - sum(final.values()))
    else:
        final, burn = {}, 1.0
    return Allocation(cats, float(burn_ratio), tuple(elements), dict(sorted(raw.items())), final, burn)


def _subset_score(miner: Mapping[str, float], subset: tuple[str, ...]) -> float | None:
    """Category-weighted mean over the subset; None if any member is missing."""
    total = weight_sum = 0.0
    for category in subset:
        if miner.get(category) is None:
            return None
        weight = float(CATEGORY_WEIGHTS.get(category, 1.0))
        total += weight * float(miner[category])
        weight_sum += weight
    return total / weight_sum if weight_sum > 0 else None
