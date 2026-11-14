"""Static domain knowledge: material library, defect taxonomy, cause hypotheses, recommended actions.

IMPORTANT: cause entries are *hypotheses* looked up from this table by (defect type, material
family). They are not inferred from the image and the UI/report label them as such.
"""
from __future__ import annotations

MATERIALS = [
    {"key": "metals", "name": "Metals and alloys", "family": "metal",
     "description": "Rolled, cast, machined or stamped steel, aluminium, copper and alloys.",
     "common_defects": ["scratch", "crack", "dent", "pore", "discoloration", "contamination", "deformation"],
     "imaging_notes": "Specular surfaces: use diffuse dome or dark-field lighting; avoid direct glare."},
    {"key": "plastics", "name": "Plastics and polymers", "family": "polymer",
     "description": "Injection-moulded, extruded and thermoformed parts.",
     "common_defects": ["bubble", "discoloration", "deformation", "scratch", "contamination", "dimensional"],
     "imaging_notes": "Back-lighting reveals voids in translucent parts; polarizers reduce glare."},
    {"key": "wood", "name": "Wood", "family": "wood", "description": "Sawn timber, veneer, engineered boards.",
     "common_defects": ["crack", "hole", "discoloration", "texture_inconsistency", "dent"],
     "imaging_notes": "Natural grain varies widely: train anomaly models per species and finish."},
    {"key": "glass", "name": "Glass", "family": "glass", "description": "Flat, container and optical glass.",
     "common_defects": ["bubble", "scratch", "crack", "contamination"],
     "imaging_notes": "Use back-light or dark-field; front-lit photos mostly show reflections."},
    {"key": "ceramics", "name": "Ceramics", "family": "ceramic", "description": "Tiles, sintered ferrites, technical ceramics.",
     "common_defects": ["crack", "pore", "blowhole", "break", "fray", "uneven", "discoloration"],
     "imaging_notes": "Low-angle lighting accentuates surface relief (pores, chips)."},
    {"key": "textiles", "name": "Textiles and fabrics", "family": "textile", "description": "Woven, knitted and non-woven fabrics.",
     "common_defects": ["hole", "texture_inconsistency", "contamination", "discoloration", "misalignment"],
     "imaging_notes": "Keep fabric flat and tensioned; periodic weave suits reference/anomaly models."},
    {"key": "leather", "name": "Leather and hides", "family": "leather",
     "description": "Finished and crust leather, hides and cut panels for footwear, upholstery, automotive and leather goods.",
     "common_defects": ["cut", "scratch", "wrinkle", "insect_bite", "brand_mark", "grain_defect", "hole", "discoloration", "fold_mark"],
     "imaging_notes": "Lay the hide flat. Low-angle (raking) light reveals scratches, wrinkles and grain defects; diffuse light reveals stains "
                      "and colour variation. Natural grain differs per hide and finish: learn the reference from the same article and colour."},
    {"key": "rubber", "name": "Rubber", "family": "elastomer", "description": "Seals, tyres, moulded elastomer parts.",
     "common_defects": ["bubble", "crack", "contamination", "deformation", "missing_component"],
     "imaging_notes": "Black, low-contrast surfaces need strong directional lighting."},
    {"key": "paper", "name": "Paper and cardboard", "family": "paper", "description": "Paper web, cartons, corrugated board.",
     "common_defects": ["hole", "discoloration", "contamination", "deformation", "misalignment"],
     "imaging_notes": "Transmitted light exposes thin spots and holes."},
    {"key": "composites", "name": "Composites", "family": "composite", "description": "CFRP/GFRP laminates and sandwich panels.",
     "common_defects": ["crack", "bubble", "texture_inconsistency", "contamination", "deformation"],
     "imaging_notes": "Sub-surface delamination is not visible optically; pair with NDT."},
    {"key": "electronics", "name": "Electronic components", "family": "electronics", "description": "Bare and assembled PCBs, components, connectors.",
     "common_defects": ["open", "short", "mousebite", "spur", "copper", "pin-hole", "missing_component", "misalignment"],
     "imaging_notes": "Golden-template comparison needs fixed magnification and registration."},
    {"key": "construction", "name": "Construction materials", "family": "mineral", "description": "Concrete, asphalt, masonry, stone.",
     "common_defects": ["crack", "pore", "discoloration", "deformation"],
     "imaging_notes": "Shoot perpendicular to the surface with a scale reference for crack widths."},
    {"key": "custom", "name": "Other / custom material", "family": "generic", "description": "Any other industrial material: define your own profile.",
     "common_defects": [], "imaging_notes": "Start with the screening detector, collect good samples, then fit an anomaly model."},
]

# type -> (display label, category, structural/functional criticality 0..1)
TAXONOMY: dict[str, tuple[str, str, float]] = {
    "crack": ("Crack / fracture", "structural", 0.9),
    "break": ("Break / chipped edge", "structural", 0.9),
    "scratch": ("Scratch", "surface", 0.4),
    "dent": ("Dent", "deformation", 0.5),
    "deformation": ("Deformation", "deformation", 0.6),
    "discoloration": ("Discoloration", "appearance", 0.3),
    "contamination": ("Contamination", "contamination", 0.4),
    "bubble": ("Bubble / air pocket", "inclusion", 0.5),
    "pore": ("Pore", "inclusion", 0.5),
    "blowhole": ("Blowhole", "inclusion", 0.6),
    "hole": ("Hole", "structural", 0.7),
    "fray": ("Fray", "surface", 0.5),
    "uneven": ("Uneven surface", "texture", 0.4),
    "misalignment": ("Misalignment", "assembly", 0.6),
    "missing_component": ("Missing component", "assembly", 0.9),
    "dimensional": ("Dimensional irregularity", "dimensional", 0.6),
    "texture_inconsistency": ("Texture inconsistency", "texture", 0.3),
    "cut": ("Cut / knife mark", "structural", 0.8),
    "wrinkle": ("Wrinkle / loose grain", "texture", 0.4),
    "insect_bite": ("Insect bite / tick mark", "surface", 0.4),
    "brand_mark": ("Brand mark / scar", "surface", 0.5),
    "grain_defect": ("Grain defect", "texture", 0.4),
    "fold_mark": ("Fold / crease mark", "deformation", 0.4),
    "open": ("Open circuit", "electrical", 1.0),
    "short": ("Short circuit", "electrical", 1.0),
    "mousebite": ("Mouse bite", "electrical", 0.7),
    "spur": ("Spur", "electrical", 0.6),
    "copper": ("Spurious copper", "electrical", 0.7),
    "pin-hole": ("Pin hole", "electrical", 0.6),
    # outputs of detectors that localize but cannot name the defect
    "anomaly": ("Unclassified anomaly", "unclassified", 0.5),
    "linear_mark": ("Linear mark (crack or scratch candidate)", "unclassified", 0.6),
    "dark_spot": ("Dark spot (pore, hole or contamination candidate)", "unclassified", 0.5),
    "bright_spot": ("Bright spot (inclusion, glare or residue candidate)", "unclassified", 0.4),
    "blotch": ("Blotch (stain or discoloration candidate)", "unclassified", 0.3),
}

_GENERIC_CAUSES: dict[str, list[str]] = {
    "crack": ["Thermal or mechanical stress exceeding material strength", "Too-rapid cooling or drying", "Handling or clamping damage"],
    "break": ["Impact during handling or transport", "Ejection / demoulding force too high", "Brittle edge from incorrect sintering or curing"],
    "scratch": ["Abrasive contact with tooling, conveyors or other parts", "Debris trapped between part and fixture"],
    "dent": ["Impact from handling or part-to-part contact", "Foreign particle pressed into the surface during forming"],
    "deformation": ["Residual stress release", "Uneven cooling or shrinkage", "Excessive forming or clamping force"],
    "discoloration": ["Overheating / oxidation", "Chemical residue or uneven coating", "Raw-material lot variation"],
    "contamination": ["Airborne particles or fibres", "Lubricant, release agent or cleaning residue", "Carry-over from upstream process"],
    "bubble": ["Trapped gas or moisture", "Insufficient venting or degassing", "Process temperature too high"],
    "pore": ["Gas porosity", "Incomplete compaction or fill", "Moisture in raw material"],
    "blowhole": ["Gas trapped during pressing/sintering or casting", "Binder burn-out too fast", "Moisture in powder or mould"],
    "hole": ["Tool breakthrough or puncture", "Missing material from incomplete fill", "Insect/knot fallout (wood)"],
    "fray": ["Worn cutting or grinding tool", "Incorrect feed rate at the edge"],
    "uneven": ["Grinding wheel wear or chatter", "Inconsistent pressing density", "Tool or die wear"],
    "misalignment": ["Fixture or registration error", "Feeder / placement offset", "Thermal drift"],
    "missing_component": ["Feeder empty or pick-up failure", "Component dislodged after placement", "Skipped process step"],
    "dimensional": ["Tool wear", "Process parameter drift", "Shrinkage variation"],
    "texture_inconsistency": ["Raw-material variation", "Process speed or tension fluctuation", "Tool surface wear"],
    "cut": ["Flaying (knife) damage at the abattoir", "Blade damage in splitting, shaving or cutting", "Handling damage from sharp fixtures"],
    "wrinkle": ["Loose grain from the belly / flank area of the hide", "Over-drying or uneven staking", "Poor fat-liquoring"],
    "insect_bite": ["Tick, mite or fly damage on the living animal", "Healed parasite lesions"],
    "brand_mark": ["Hot-iron or freeze branding of the animal", "Healed wound or scar tissue"],
    "grain_defect": ["Growth marks or veins of the hide", "Grain damage from bacterial action before curing", "Uneven buffing or embossing"],
    "fold_mark": ["Storage or transport folded under load", "Creasing during drying or toggling"],
    "open": ["Over-etching", "Scratch through a trace", "Resist or imaging defect"],
    "short": ["Under-etching", "Resist bridging or debris during imaging", "Copper sliver"],
    "mousebite": ["Local over-etching", "Resist adhesion failure at the trace edge"],
    "spur": ["Local under-etching", "Resist scum or phototool defect"],
    "copper": ["Under-etching leaving residual copper", "Contamination on the phototool or resist"],
    "pin-hole": ["Pinholes in resist or plating", "Dust on the phototool"],
}
_MATERIAL_CAUSES: dict[tuple[str, str], list[str]] = {
    ("crack", "ceramic"): ["Thermal shock during sintering or cooling", "Density gradients from pressing", "Grinding stress"],
    ("crack", "mineral"): ["Shrinkage during curing", "Load or settlement stress", "Freeze-thaw cycling"],
    ("crack", "metal"): ["Fatigue or hot tearing", "Hydrogen embrittlement", "Quench cracking"],
    ("crack", "polymer"): ["Environmental stress cracking", "Moulded-in stress", "Brittle regrind content"],
    ("bubble", "glass"): ["Incomplete fining of the melt", "Refractory outgassing"],
    ("bubble", "polymer"): ["Moisture in resin (insufficient drying)", "Trapped air from poor venting"],
    ("discoloration", "metal"): ["Heat tint / oxidation", "Pickling or passivation residue"],
    ("scratch", "leather"): ["Barbed wire, thorn or horn scratches on the living animal", "Abrasion in drums, conveyors or stacking", "Handling damage after finishing"],
    ("hole", "leather"): ["Warble-fly (grub) holes", "Flaying cuts through the hide", "Mechanical damage in fleshing or splitting"],
    ("discoloration", "leather"): ["Uneven dye uptake", "Finish spray or coating variation", "Salt, fat or water stains", "Light or heat exposure"],
    ("contamination", "leather"): ["Residual hair, flesh or dung", "Finish or adhesive spots"],
    ("hole", "textile"): ["Broken needle or yarn", "Snagging on machine parts"],
}
_UNCLASSIFIED = {"anomaly", "linear_mark", "dark_spot", "bright_spot", "blotch"}


def defect_label(defect_type: str) -> str:
    return TAXONOMY.get(defect_type, (defect_type.replace("_", " ").title(), "other", 0.5))[0]


def defect_category(defect_type: str) -> str:
    return TAXONOMY.get(defect_type, ("", "other", 0.5))[1]


def criticality(defect_type: str) -> float:
    return TAXONOMY.get(defect_type, ("", "other", 0.5))[2]


def material_family(material_key: str) -> str:
    return next((m["family"] for m in MATERIALS if m["key"] == material_key), "generic")


def cause_hypotheses(defect_type: str, material_key: str) -> list[str]:
    """Knowledge-base lookup. Returns [] for unclassified regions: no type, no basis for a cause."""
    if defect_type in _UNCLASSIFIED:
        return []
    fam = material_family(material_key)
    return _MATERIAL_CAUSES.get((defect_type, fam)) or _GENERIC_CAUSES.get(defect_type, [])


def recommended_action(defect_type: str, severity: str, type_source: str) -> str:
    if type_source != "model":
        return "Manual visual inspection of the marked area to confirm whether this is a real defect and of what type."
    if severity == "critical":
        return "Quarantine the part and its batch neighbours; escalate to the process engineer before releasing further parts."
    if severity == "major":
        return "Hold the part for inspector disposition (rework or scrap) and check the last process step for the listed hypotheses."
    return "Record the finding; accept if within the product's cosmetic specification and monitor the trend."
