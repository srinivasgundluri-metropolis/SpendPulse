"""Normalize dining merchants and assign cuisine labels."""

from __future__ import annotations

import re
from typing import Any

# (cuisine, patterns) — first match wins; keep specific before broad.
_CUISINE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Delivery platforms",
        (r"UBER\s*EATS", r"DOORDASH", r"\bDD\s*\*", r"SHAREBITE", r"^GRUBHUB$"),
    ),
    (
        "Indian / South Asian",
        (
            r"DESI\s*BOYS",
            r"DESI\s*DISTRICT",
            r"BIKANERVALA",
            r"TAWAKKUL",
            r"KARACHI\s*CHAAT",
            r"T'?S\s*INDIAN",
            r"THIRU\s*KUPPUSAMY",
            r"SURGURU",
            r"AL-HALAL",
            r"DASTARKHWAN",
            r"NAWABI\s*HYDERABAD",
            r"UTSAV",
            r"HONEST\s*KITCHEN",
            r"SIRI\s*CHICAGO",
        ),
    ),
    (
        "Chinese",
        (
            r"PANDA\s*EXPRESS",
            r"JOY\s*YEE",
            r"KEN\s*KEE",
            r"HING\s*KEE",
            r"HONS\s*WUN",
            r"CHIU\s*QUON",
            r"CHOWBUS",
            r"UFOUU",
        ),
    ),
    (
        "Japanese / Sushi",
        (r"BLUE\s*SUS", r"ONI\s*MAKI", r"KOMOREBI", r"\bSUSHI\b", r"\bPOKE\b", r"MAMMOTH\s*POKE"),
    ),
    ("Korean", (r"GANGNAM",)),
    ("Thai", (r"SABAI\s*SABAI", r"TRISARA",)),
    ("Vietnamese / SE Asian", (r"DABAO\s*SINGAPORE",)),
    ("Filipino", (r"MAMA\s*GO",)),
    (
        "Cafe / Bakery / Sweets",
        (
            r"LEVAIN",
            r"FENG\s*CHA",
            r"GATHERS\s*TEA",
            r"MANGO\s*MANGO",
            r"COLD\s*STONE",
            r"JENI'?S",
            r"JENISS",
            r"MAGNOLIA\s*BAKERY",
            r"ROCKY\s*MOUNTAIN\s*CHOCO",
            r"MARIOS\s*ITALIAN\s*LEMONADE",
            r"CHIU\s*QUON",
        ),
    ),
    (
        "Mediterranean",
        (r"\bROTI\b", r"PITAKI", r"\bGYRO",),
    ),
    ("Italian", (r"CICCO\s*MIO",)),
    ("Greek", (r"THE\s*VILLAGE\b",)),
    (
        "American / Burgers",
        (
            r"BUSY\s*BURGER",
            r"BUCKHORN\s*GRILL",
            r"FRANK\s*N\s*FRIES",
            r"PORTILLO",
            r"RAISING\s*CANE",
            r"CULVER",
            r"THE\s*BITE",
            r"GOT\s*CHA",
            r"INFUSE",
            r"RIVER\s*ROUX",
        ),
    ),
    (
        "Fast food",
        (
            r"CHICK-FIL-A",
            r"CHICKFILA",
            r"MCDONALD",
            r"SUBWAY",
            r"JERSEY\s*MIKE",
            r"JERSEYMIKES",
            r"POPEYES",
            r"NOODLES\s*AND\s*COMPANY",
        ),
    ),
    ("Plant-based", (r"\bPLANTA\b",)),
    ("Breakfast / Eggs", (r"EGGHOLIC",)),
    (
        "Cafeteria / Vending",
        (
            r"CANTEEN",
            r"FARMER'?S\s*FRIDGE",
            r"UIC\s*SCW",
            r"USCONNECT",
            r"MOSCONE\s*CENTER\s*F&B",
            r"SFORD\s*-\s*FB",
            r"HYATT.*F&B",
        ),
    ),
    ("Bars / Nightlife", (r"HOWL\s*AT\s*THE\s*MOON", r"O2\s*LOUNGE", r"ACEBOUNCE")),
]

# Collapse noisy Amex strings into a stable restaurant name.
_CHAIN_ALIASES: list[tuple[str, str]] = [
    (r"CHICK-?FIL-?A|CHICKFILA", "Chick-fil-A"),
    (r"PANDA\s*EXPRESS", "Panda Express"),
    (r"UBER\s*EATS", "Uber Eats"),
    (r"DOORDASH|\bDD\s*\*DOORDASH", "DoorDash"),
    (r"SHAREBITE", "Sharebite"),
    (r"NOODLES\s*AND\s*COMPANY", "Noodles & Company"),
    (r"JERSEY\s*MIKES?|JERSEYMIKES", "Jersey Mike's"),
    (r"MCDONALD", "McDonald's"),
    (r"SUBWAY", "Subway"),
    (r"FARMER'?S\s*FRIDGE", "Farmer's Fridge"),
    (r"CANTEEN|NYX=CANTEEN|CPI\*CANTEEN", "Canteen Vending"),
    (r"UIC\s*SCW\s*MARKET", "UIC SCW Marketplace"),
    (r"BLUE\s*SUS(?:HI)?", "Blue Sushi Sake Grill"),
    (r"EGGHOLIC", "Eggholic"),
    (r"DESI\s*BOYS", "Desi Boys"),
    (r"TAWAKKUL", "Tawakkul Restaurant"),
    (r"FENG\s*CHA", "Feng Cha"),
    (r"LEVAIN", "Levain Bakery"),
    (r"PITAKI", "Pitaki"),
    (r"\bROTI\b", "Roti"),
    (r"T'?S\s*INDIAN", "T's Indian Kitchen"),
    (r"BIKANERVALA", "Bikanervala"),
    (r"JOY\s*YEE", "Joy Yee Noodle"),
    (r"GANGNAM\s*EXPRESS", "Gangnam Express"),
    (r"KEN\s*KEE", "Ken Kee Restaurant"),
    (r"PLANTA", "Planta"),
    (r"KARACHI\s*CHAAT", "Karachi Chaat House"),
    (r"MARIOS\s*ITALIAN", "Mario's Italian Lemonade"),
    (r"KOMOREBI", "Komorebi"),
    (r"SABAI\s*SABAI", "Sabai Sabai Thai"),
    (r"CICCO\s*MIO", "Cicco Mio"),
    (r"ONI\s*MAKI", "Oni Maki"),
    (r"RAISING\s*CANE", "Raising Cane's"),
    (r"CULVER", "Culver's"),
    (r"POPEYES", "Popeyes"),
    (r"PORTILLO", "Portillo's"),
    (r"COLD\s*STONE", "Cold Stone Creamery"),
    (r"JENI'?S|JENISS", "Jeni's Splendid Ice Creams"),
    (r"THE\s*BITE\b", "The Bite"),
    (r"GOT\s*CHA\b", "Got Cha"),
    (r"FRANK\s*N\s*FRIES", "Frank N Fries"),
    (r"MANGO\s*MANGO", "Mango Mango Dessert"),
    (r"THIRU\s*KUPPUSAMY", "Thiru Kuppusamy"),
    (r"SURGURU", "Surguru Masalas"),
    (r"AL-HALAL", "Al-Halal Zaiqa"),
    (r"DASTARKHWAN", "Dastarkhwan Restaurant"),
    (r"NAWABI\s*HYDERABAD", "Nawabi Hyderabad House"),
    (r"SIRI\s*CHICAGO", "Siri Chicago"),
    (r"HING\s*KEE", "Hing Kee"),
    (r"HONS\s*WUN", "Hon's Wun-Tun House"),
    (r"CHIU\s*QUON", "Chiu Quon Bakery"),
    (r"MAGNOLIA\s*BAKERY", "Magnolia Bakery"),
    (r"GATHERS\s*TEA", "Gathers Tea Bar"),
    (r"MAMMOTH\s*POKE", "Mammoth Poke"),
    (r"BUSY\s*BURGER", "Chicago Busy Burger"),
    (r"BUCKHORN\s*GRILL", "Buckhorn Grill"),
    (r"DABAO\s*SINGAPORE", "Dabao Singapore"),
    (r"MAMA\s*GO", "Mama Go's Filipino"),
    (r"TRISARA", "Trisara Restaurant"),
    (r"THE\s*VILLAGE\b", "The Village"),
    (r"HOWL\s*AT\s*THE\s*MOON", "Howl at the Moon"),
    (r"O2\s*LOUNGE", "O2 Lounge"),
    (r"UTSAV", "Utsav"),
    (r"DESI\s*DISTRICT", "Desi District"),
    (r"HONEST\s*KITCHEN", "Honest Kitchen"),
    (r"INFUSE|RIVER\s*ROUX", "Infuse River Roux"),
    (r"MOSCONE\s*CENTER\s*F&B", "Moscone Center F&B"),
    (r"SFORD\s*-\s*FB|HYATT.*F&B", "Hotel F&B"),
    (r"USCONNECT", "USConnect Vending"),
    (r"ROCKY\s*MOUNTAIN\s*CHOCO", "Rocky Mountain Chocolate"),
    (r"ACEBOUNCE", "Acebounce"),
    (r"CHOWBUS|UFOUU", "Chowbus"),
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().upper()


def cuisine_for(description: str) -> str:
    text = _clean(description)
    # Grubhub embeds restaurant in descriptor — classify that first
    m = re.search(r"GRUBHUB\*([A-Z0-9]+)", text)
    if m:
        embedded = m.group(1)
        for cuisine, patterns in _CUISINE_RULES:
            if cuisine == "Delivery platforms":
                continue
            if any(re.search(p, embedded) for p in patterns):
                return cuisine
        return "Delivery platforms"
    for cuisine, patterns in _CUISINE_RULES:
        if any(re.search(p, text) for p in patterns):
            return cuisine
    return "Other dining"


def restaurant_name(description: str) -> str:
    text = _clean(description)

    # Delivery platforms (opaque) stay as the platform
    if re.search(r"UBER\s*EATS", text):
        return "Uber Eats"
    if re.search(r"DOORDASH|\bDD\s*\*DOORDASH", text):
        # DD *DOORDASH CHICK-FIL → prefer chain if present
        for pat, name in _CHAIN_ALIASES:
            if name in {"DoorDash", "Uber Eats"}:
                continue
            if re.search(pat, text):
                return f"{name} (DoorDash)"
        return "DoorDash"
    if re.search(r"SHAREBITE", text):
        return "Sharebite"
    m = re.search(r"GRUBHUB\*([A-Z0-9]+)", text)
    if m:
        embedded = m.group(1)
        for pat, name in _CHAIN_ALIASES:
            if re.search(pat, embedded):
                return f"{name} (Grubhub)"
        pretty = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", embedded.title())
        return f"{pretty} (Grubhub)"

    for pat, name in _CHAIN_ALIASES:
        if re.search(pat, text):
            return name

    # Generic cleanup for unknowns
    s = text
    s = re.sub(r"^APLPAY\s+", "", s)
    s = re.sub(r"^(TST\*|BT\*|CPI\*|INKD\s*GRATUITY|INKD)\s*", "", s)
    s = re.sub(r"\b\d{5,}(?:\.\d+)?\b", " ", s)
    s = re.sub(r"#\d+", " ", s)
    s = re.sub(r"\+?\d[\d\-]{6,}", " ", s)
    s = re.sub(
        r"\b(FAST\s*FOOD\s*)?RESTAURANT\b|\bGROCERY\s*STORE\b|\bGOODS/SERVICES\b|"
        r"\bMISC\s*FOOD\s*STORE\b|\bSQUAREUP\.COM\S*|\bHELP\.UBER\.COM\b",
        " ",
        s,
    )
    # Drop trailing city/state crumbs (best-effort)
    s = re.sub(
        r"\b(CHICAGO|SAN\s*FRANCISCO|AUSTIN|SCHAUMBURG|HOFFMAN\s*ESTATES|"
        r"NAPERVILLE|AURORA|CHARLOTTE|PINEVILLE|FORT\s*MILL|LAKE\s*GENEVA|"
        r"ELMHURST|CICERO|BROOMFIELD|HUNT\s*VALLEY|NEW\s*YORK|DOVER|"
        r"CAMPBELL|SANTA\s*MONICA|PALO\s*ALTO|FREMONT|PFLUGERVILLE)\b.*$",
        " ",
        s,
    )
    s = re.sub(r"\b[A-Z]{2}\b\s*$", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -*")
    if not s:
        return "Unknown restaurant"
    return s.title()


def enrich_dining_tx(t: dict) -> dict:
    out = dict(t)
    desc = str(t.get("description") or "")
    out["restaurant"] = restaurant_name(desc)
    out["cuisine"] = cuisine_for(desc)
    return out


def dining_breakdown(transactions: list[dict]) -> dict[str, Any]:
    """Cuisine + distinct restaurant rollups for Dining Out charges."""
    dining = [
        enrich_dining_tx(t)
        for t in transactions
        if t.get("category") == "Dining Out" and float(t.get("amount") or 0) > 0
    ]

    by_cuisine: dict[str, dict[str, float | int | set]] = {}
    by_restaurant: dict[str, dict[str, Any]] = {}

    for t in dining:
        cuisine = t["cuisine"]
        restaurant = t["restaurant"]
        amt = float(t["amount"])

        if cuisine not in by_cuisine:
            by_cuisine[cuisine] = {"cuisine": cuisine, "total": 0.0, "count": 0, "restaurants": set()}
        c = by_cuisine[cuisine]
        c["total"] = float(c["total"]) + amt
        c["count"] = int(c["count"]) + 1
        c["restaurants"].add(restaurant)  # type: ignore[union-attr]

        key = f"{restaurant}|{cuisine}"
        if key not in by_restaurant:
            by_restaurant[key] = {
                "restaurant": restaurant,
                "cuisine": cuisine,
                "total": 0.0,
                "count": 0,
                "last_date": t.get("date") or "",
            }
        r = by_restaurant[key]
        r["total"] = float(r["total"]) + amt
        r["count"] = int(r["count"]) + 1
        if (t.get("date") or "") > (r.get("last_date") or ""):
            r["last_date"] = t.get("date") or ""

    cuisine_rows = sorted(
        [
            {
                "cuisine": row["cuisine"],
                "total": round(float(row["total"]), 2),
                "count": int(row["count"]),
                "restaurant_count": len(row["restaurants"]),  # type: ignore[arg-type]
            }
            for row in by_cuisine.values()
        ],
        key=lambda x: (-x["total"], x["cuisine"]),
    )
    restaurant_rows = sorted(
        [
            {
                "restaurant": row["restaurant"],
                "cuisine": row["cuisine"],
                "total": round(float(row["total"]), 2),
                "count": int(row["count"]),
                "last_date": row["last_date"],
            }
            for row in by_restaurant.values()
        ],
        key=lambda x: (-x["count"], -x["total"], x["restaurant"]),
    )

    total = round(sum(float(t["amount"]) for t in dining), 2)
    return {
        "dining_total": total,
        "dining_count": len(dining),
        "dining_cuisine_count": len(cuisine_rows),
        "dining_restaurant_count": len(restaurant_rows),
        "dining_by_cuisine": cuisine_rows,
        "dining_restaurants": restaurant_rows,
        "dining_transactions": sorted(
            dining, key=lambda t: (t.get("date") or "", t.get("restaurant") or "")
        ),
    }
