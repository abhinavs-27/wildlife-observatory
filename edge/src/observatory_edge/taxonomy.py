"""SpeciesNet 7-part label parsing and uncertainty rules."""

from __future__ import annotations

from dataclasses import dataclass

NON_SPECIES = {"animal", "blank", "unknown", "no cv result", "vehicle", ""}


@dataclass(frozen=True)
class Taxon:
    uuid: str
    cls: str
    order: str
    family: str
    genus: str
    species: str
    common_name: str

    @property
    def level(self) -> str:
        if self.common_name in NON_SPECIES or self.cls == "no cv result":
            return "none"
        if self.species:
            return "species"
        for name, val in (("genus", self.genus), ("family", self.family),
                          ("order", self.order), ("class", self.cls)):
            if val:
                return name
        return "none"


def parse_label(label: str) -> Taxon:
    parts = (label or "").split(";")
    if len(parts) != 7:
        name = (label or "").strip().lower()
        return Taxon("", "", "", "", "", "", name)
    parts = [p.strip().lower() for p in parts]
    return Taxon(*parts)


def is_uncertain(taxon: Taxon, score: float, threshold: float) -> bool:
    return taxon.level != "species" or score < threshold


def display_name(taxon: Taxon) -> str:
    if taxon.common_name and taxon.common_name != "no cv result":
        return taxon.common_name
    return "unknown"
