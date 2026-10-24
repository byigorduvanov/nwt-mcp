"""Hand-written meaning of node types and relations. Everything else in a card (counts, links, inherited fields)
is computed from graph.db, so only this file needs editing when a type or relation is added to the graph."""

# Relation kinds. Only "is_a" passes fields from parent to child; "made_from" is production and passes nothing.
#   is_a       child is a kind of parent (HDPE is a PE): child inherits the parent's fields
#   contains   classification tree (collection > category > subcategory > symbol): child lives inside parent
#   made_from  production chain (ethylene -> PE): nothing is inherited
#   link       cross-reference between layers (material <-> market symbol)
RELS = {
    # rel in graph.db: (kind, name read from src, name read from dst, meaning)
    "has_variety":       ("is_a",      "varieties",   "is_a",        "variety is a kind of the polymer"),
    "has_category":      ("contains",  "categories",  "in",          "collection contains category"),
    "has_subcategory":   ("contains",  "subcategories", "in",        "category contains subcategory"),
    "has_symbol":        ("contains",  "symbols",     "in",          "subcategory contains market symbol"),
    "has_family":        ("contains",  "families",    "in",          "subcategory publishes data family"),
    "has_field":         ("contains",  "fields",      "in_families", "family record has this field"),
    "in_domain":         ("is_a",      "domain",      "families",    "family is a kind of data domain: inherits the domain's fields"),
    "in_field_category": ("contains",  "field_category", "fields",   "field belongs to field category"),
    "converted_to":      ("made_from", "used_for",    "made_from",   "src is converted into dst (production step)"),
    "priced_as":         ("link",      "priced_as",   "prices",      "material is traded/priced under market symbol"),
    "produced_by":       ("link",      "produced_by", "plant_of",    "material is produced in plant tracked by symbol"),
    "metric_of":         ("link",      "metric_of",   "metrics",     "symbol is a metric (spread, margin, rate) about material"),
}

# Node types: (layer, level in its tree, parent type, one-line meaning)
TYPES = {
    "feedstock":    ("plastics", 0, None, "raw natural resource at the start of the chain (crude oil, gas, salt)"),
    "intermediate": ("plastics", 1, None, "processed chemical between feedstock and monomer (naphtha, ethane, benzene)"),
    "monomer":      ("plastics", 2, None, "building block that is polymerised (ethylene, propylene, styrene)"),
    "polymer":      ("plastics", 3, None, "polymer family (PE, PP, PVC, PS, PET, ABS)"),
    "variety":      ("plastics", 4, "polymer", "commercial kind of a polymer (HDPE, LDPE, PP homopolymer); has properties and market symbols"),
    "substance":    ("plastics", None, None, "other traded chemical outside the main chain; linked only to market symbols"),
    "collection":   ("catalogue", 0, None, "top section of the NWT data catalogue (Commodities, Equity, Debt...)"),
    "category":     ("catalogue", 1, "collection", "section inside a collection (Petrochemicals & Chemicals)"),
    "subcategory":  ("catalogue", 2, "category", "product group; owns market symbols and data families (Polyethylene)"),
    "symbol":       ("catalogue", 3, "subcategory", "one market product/quote that can have prices (HDPE film CFR China)"),
    "family":       ("catalogue", 3, "subcategory", "data product of a subcategory: one record schema (Polyethylene: Prices)"),
    "field":        ("catalogue", 4, "family", "column of a family record"),
    "data_domain":  ("catalogue", None, None, "kind of data family (pricing, reference, events...): fields shared by all its families"),
    "field_category": ("catalogue", None, None, "group of fields by meaning (identifiers, prices, technical)"),
}

FIELD_MEANING = {
    "name": "English name", "name_en": "English name (shown as name)", "abbr": "abbreviation", "formula": "chemical formula", "repeat_unit": "polymer repeat unit",
    "description": "short description", "code": "code inside parent", "unit": "trading unit, UN/CEFACT code (TNE tonne, KGM kg, C62 piece, CCY currency, IDX index)",
    "realtime": "true if data is published in real time", "summary": "what the family covers", "cadence": "how often data is published",
    "data_type": "value type", "subcategory": "catalogue subcategory code", "identifiers": "CAS, HS code, resin code",
    "ranges": "typical property ranges [min, max, unit]", "class": "symbol class: series (priced quote), grade, substance, metric, futures, asset, trade, policy",
    "base": "product the symbol is about", "region": "region code (see nwt_map regions)", "basis": "delivery basis as written in the symbol",
    "incoterm": "Incoterm (FOB, CFR, CIF...)", "price_type": "assessment, contract, spot...",
    "name_ru": "Russian name (detail=full)", "description_ru": "Russian description (detail=full)", "sources": "source URLs (detail=full)",
    "properties": "measured properties by grade (detail=full)", "recycled": "true for recycled material", "gaps": "data not found yet (detail=full)",
}
