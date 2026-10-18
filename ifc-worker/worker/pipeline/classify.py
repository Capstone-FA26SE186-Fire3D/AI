from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from worker.pipeline.extract import Element, SpaceInfo

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass
class Candidate:
    catalog_key: str
    confidence: float
    source: Literal["ifc", "inferred"] = "ifc"


def load_keywords(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def tokenize(text: str | None) -> list[str]:
    return _TOKEN.findall(text.lower()) if text else []


def _has(seqs: list[list[str]], keywords: list[str]) -> bool:
    """Whole-token match; multi-word keywords match consecutive tokens."""
    for kw in keywords:
        k = tokenize(kw)
        if not k:
            continue
        n = len(k)
        for toks in seqs:
            for i in range(len(toks) - n + 1):
                if toks[i : i + n] == k:
                    return True
    return False


def _field_tokens(*values: str | None) -> list[list[str]]:
    return [tokenize(v) for v in values if v]


def _el_tokens(el: Element) -> list[list[str]]:
    return _field_tokens(el.name, el.object_type, el.long_name, el.type_name)


def _pset_value(psets: dict, key: str):
    for props in psets.values():
        if isinstance(props, dict) and key in props:
            return props[key]
    return None


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", ".t.")
    return bool(v)


def classify_space(space: SpaceInfo, kw: dict) -> str | None:
    seqs = _field_tokens(space.name, space.long_name)
    for cat in ("wc", "kitchen", "corridor", "stair", "elevator"):
        if _has(seqs, kw["spaces"].get(cat, [])):
            return cat
    return None


def _water(el: Element, seqs, kw: dict, conf: float) -> Candidate | None:
    pt = (el.predefined_type or "").upper()
    if pt in ("TOILETPAN", "URINAL", "CISTERN", "SANITARYFOUNTAIN", "BIDET", "WCSEAT"):
        return None
    if pt in ("WASHHANDBASIN", "SINK"):
        return Candidate("water.sink", conf)
    if pt == "BATH":
        return Candidate("water.bath", conf)
    if pt == "SHOWER":
        return Candidate("water.shower", conf)
    if _has(seqs, kw["toilet"]):
        return None
    for key in ("sink", "bath", "shower"):
        if _has(seqs, kw["water"][key]):
            return Candidate(f"water.{key}", conf)
    return None


def classify_element(el: Element, kw: dict) -> Candidate | None:
    c = el.ifc_class
    seqs = _el_tokens(el)
    pt = (el.predefined_type or "").upper()

    if c == "IfcDoor":
        psets = el.psets
        if _truthy(_pset_value(psets, "FireExit")) or _has(seqs, kw["exit"]):
            return Candidate("door.exit", 0.95)
        if _truthy(_pset_value(psets, "IsExternal")):
            return Candidate("door.exit", 0.7, "inferred")
        rating = _pset_value(psets, "FireRating")
        if rating is not None and str(rating).strip().lower() not in ("", "-", "none"):
            return Candidate("door.fire", 0.9)
        return Candidate("door.standard", 0.95)

    if c == "IfcTransportElement":
        if pt == "ELEVATOR" or _has(seqs, kw["elevator"]):
            return Candidate("transport.elevator", 0.9)
        return None

    if c in ("IfcAlarm", "IfcSensor"):
        if _has(seqs, kw["alarm"]["call_point"]) or pt in ("BREAKGLASSBUTTON", "MANUALPULLBOX"):
            return Candidate("alarm.call_point", 0.9)
        if c == "IfcAlarm":
            return Candidate("alarm.detector", 0.9)
        flat = [t for s in seqs for t in s]
        if pt in ("SMOKESENSOR", "HEATSENSOR") or "smoke" in flat or "heat" in flat:
            return Candidate("alarm.detector", 0.9)
        return None

    if c == "IfcFireSuppressionTerminal":
        if pt == "SPRINKLER" or _has(seqs, kw["sprinkler"]):
            return Candidate("suppression.sprinkler", 0.95)
        if pt in ("HOSEREEL", "FIREHYDRANT") or _has(seqs, kw["extinguisher"]["hose_reel"]):
            return Candidate("extinguisher.hose_reel", 0.95)
        if pt == "FIREEXTINGUISHER" or _has(seqs, kw["extinguisher"]["portable"]):
            return Candidate("extinguisher.portable", 0.95)
        return None

    if c == "IfcSanitaryTerminal":
        return _water(el, seqs, kw, 0.95)

    if c in ("IfcFlowTerminal", "IfcBuildingElementProxy", "IfcFurnishingElement"):
        fire_typed = c == "IfcFlowTerminal" and el.type_class == "IfcFireSuppressionTerminalType"
        conf_fire = 0.95 if fire_typed else 0.7
        if pt == "SPRINKLER" or _has(seqs, kw["sprinkler"]):
            return Candidate("suppression.sprinkler", 0.9 if c == "IfcFlowTerminal" else 0.7)
        if fire_typed and pt in ("HOSEREEL", "FIREHYDRANT"):
            return Candidate("extinguisher.hose_reel", 0.95)
        if fire_typed and pt == "FIREEXTINGUISHER":
            return Candidate("extinguisher.portable", 0.95)
        if c != "IfcFurnishingElement":
            if _has(seqs, kw["extinguisher"]["hose_reel"]):
                return Candidate("extinguisher.hose_reel", conf_fire)
            if _has(seqs, kw["extinguisher"]["portable"]):
                return Candidate("extinguisher.portable", conf_fire)
            if c == "IfcBuildingElementProxy":
                if _has(seqs, kw["alarm"]["call_point"]):
                    return Candidate("alarm.call_point", 0.7)
                if _has(seqs, kw["alarm"]["detector"]):
                    return Candidate("alarm.detector", 0.7)
        sanitary_typed = c == "IfcFlowTerminal" and el.type_class == "IfcSanitaryTerminalType"
        return _water(el, seqs, kw, 0.95 if sanitary_typed else 0.6)

    return None


def _is_hidden(name: str, hidden: list[str]) -> bool:
    toks = tokenize(name)
    for h in hidden:
        h = h.lower()
        for t in toks:
            if t == h or (len(h) > 3 and t.startswith(h)):
                return True
    return False


def _visible(names: list[str], materials: dict) -> list[str]:
    return [n for n in names if n and not _is_hidden(n, materials.get("hidden", []))]


def _match_rule(names: list[str], materials: dict) -> str | None:
    for n in names:
        seqs = [tokenize(n)]
        for rule in materials["rules"]:  # ceiling rules come before tile rules in config order
            if _has(seqs, rule["keywords"]):
                return rule["key"]
    return None


def material_key(names: list[str], ifc_class: str, predefined: str | None, materials: dict) -> str | None:
    """Library key for a material: first matching rule over visible (non-hidden) names,
    else the class default (IfcSlab FLOOR/ROOF, IfcCovering CEILING, walls), else None.

    A named material matching no rule still returns the class default; use
    `is_mapped(names, materials)` to decide whether to report IFC_UNMAPPED_MATERIAL.
    """
    key = _match_rule(_visible(names, materials), materials)
    if key:
        return key
    d = materials.get("defaults", {})
    pt = (predefined or "").upper()
    return d.get(f"{ifc_class}:{pt}") or d.get(ifc_class)


def is_mapped(names: list[str], materials: dict) -> bool:
    """False when there are visible material names but none matches a rule
    (callers report these as unmapped; no names at all counts as mapped)."""
    vis = _visible(names, materials)
    return not vis or _match_rule(vis, materials) is not None
