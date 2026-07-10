"""Merchant categorization with focus on coffee and avoidable spend."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    category: str
    patterns: tuple[str, ...]
    avoidable: bool = False
    coffee: bool = False
    transfer: bool = False
    payment: bool = False
    credit: bool = False
    company_expense: bool = False


RULES: list[CategoryRule] = [
    # Starbucks gift cards = shopping impulse, not a coffee visit
    CategoryRule(
        "Shopping / Impulse",
        (r"STARBUCKS.*GIFT\s*CARD", r"GIFT\s*CARD"),
        avoidable=True,
        coffee=False,
    ),
    CategoryRule(
        "Coffee & Cafes",
        (
            r"STARBUCKS",
            r"FAIRGROUNDS",
            r"DISCOURSE",
            r"MOKA\s*AND",
            r"WOOD STREET",
            r"DUNKIN",
            r"DD/BR",
            r"PEET'?S",
            r"BLUE BOTTLE",
            r"INTELLIGENTSIA",
            r"TOUS LES JOUR",
            r"\bTLJ\b",
            r"SWEET BEAN",
            r"BRIOCHE\s*DOREE",
            r"LA\s*COLOMBE",
            r"\bBRU\b",
            r"CHAI\s*CORNER",
            r"COFFEE",
            r"CAFE\b",
            r"CAFÉ",
        ),
        avoidable=True,
        coffee=True,
    ),
    # Rideshare / transit before dining so "Uber Trip" ≠ Uber Eats
    CategoryRule(
        "Transport",
        (
            r"UBER\s*TRIP",
            r"\bLYFT\b",
            r"\bMETRA\b",
            r"VENTRA",
            r"SPOTHERO",
            r"PARKMOBILE",
            r"LAZ\s*PKG",
            r"CTLP\*INREACH",
            r"SFMTA",
            r"\bMUNI\b",
            r"IL TOLLWAY",
            r"IPASS",
            r"CHIPAY",
            r"PARK CHICAGO",
        ),
        avoidable=True,
    ),
    # Tesla FSD / Premium Connectivity subscription
    CategoryRule(
        "Tesla FSD",
        (r"TESLA.*SUBSCRIPTION", r"TESLA,\s*INC\.\s*SUBSCRIPTION"),
    ),
    # Tesla insurance
    CategoryRule(
        "Tesla Insurance",
        (r"TESLA\s*INSURANCE",),
    ),
    # EV charging: Supercharger + third-party networks
    CategoryRule(
        "EV Charging",
        (
            r"SUPERCHARGER",
            r"CHARGEPOINT",
            r"JOLT\s*EV",
            r"EVPASSPORT",
            r"EV\s*CHARGING",
        ),
    ),
    # Other Tesla charges (parts, service, misc)
    CategoryRule(
        "Tesla",
        (r"TESLA",),
    ),
    # Other Auto (rentals, gas) — non-EV
    CategoryRule(
        "Auto / EV",
        (
            r"SIXT\b",
            r"AUTOMOBILE\s*RENTAL",
            r"FILLING\s*STATION",
            r"CIRCLE\s*K",
        ),
    ),
    CategoryRule(
        "Dining Out",
        (
            r"RESTAURANT",
            r"TST\*",
            r"CHICK-FIL-A",
            r"PANDA EXPRESS",
            r"NOODLES AND COMPANY",
            r"ROTI\b",
            r"UBER EATS",
            r"DOORDASH",
            r"GRUBHUB",
            r"SHAREBITE",
            r"FAST FOOD",
            r"MCDONALD",
            r"SUBWAY",
            r"JERSEY\s*MIKE",
            r"RAISING\s*CANE",
            r"CULVER",
            r"COLD\s*STONE",
            r"FARMER'?S\s*FRIDGE",
            r"POPEYES",
            r"PORTILLO",
            r"ONI\s*MAKI",
            r"SUSHI",
            r"EGGHOLIC",
            r"DESI BOYS",
            r"JOY YEE",
            r"GANGNAM EXPRESS",
            r"BIKANERVALA",
            r"KEN KEE",
            r"PLANTA",
            r"TAWAKKUL",
            r"KARACHI CHAAT",
            r"SIRI CHICAGO",
            r"UIC SCW MARKET",
            r"GOT CHA",
            r"MARIOS ITALIAN",
            r"CANTEEN",
            r"INKD\b",
            r"BLUE SUSHI",
            r"SABAI\s*SABAI",
            r"AL-HALAL",
            r"SURGURU",
            r"CICCO\s*MIO",
            r"KOMOREBI",
            r"T'?S INDIAN",
            r"FRANK N FRIES",
            r"CHOWBUS",
            r"O2 LOUNGE",
            r"HING KEE",
            r"HONS WUN",
            r"MOSCONE\s*CENTER\s*F&B",
        ),
        avoidable=True,
    ),
    CategoryRule(
        "Sweets & Bakery",
        (
            r"MANGO MANGO",
            r"DESSERT",
            r"BAKERY",
            r"DONUT",
            r"ICE CREAM",
            r"JENIS",
            r"GHIRARDELLI",
            r"KURIMU",
            r"MOLLY'?S\s*CUPCAKE",
            r"LEMONADE",
        ),
        avoidable=True,
    ),
    CategoryRule(
        "Entertainment",
        (
            r"\bAMC\b",
            r"CINEMA",
            r"MOVIE",
            r"TICKETMASTER",
            r"CONCERT",
            r"ACEBOUNCE",
            r"SPORT HOUSE",
            r"BOOK\s*MY\s*SHOW",
        ),
        avoidable=True,
    ),
    CategoryRule(
        "Shopping / Impulse",
        (
            r"MARSHALLS",
            r"ROSS\b",
            r"NORDSTROM",
            r"BURLINGTON",
            r"LULULEMON",
            r"GROUPON",
            r"FLIPKART",
            r"AMAZON",
            r"\bAMZ\*",
            r"SAKS",
            r"TARGET",
            r"WAL[\s-]?MART",
            r"WALMART",
            r"\bWMT\b",
            r"HOMEGOODS",
            r"UNIQLO",
            r"\bZARA\b",
            r"KOHL'?S",
            r"FIVE\s*BELOW",
            r"DOLLAR\s*TREE",
            r"CROMA\b",
            r"KOREA\s*BEAUTY",
            r"DOCKSIDE\s*GIFTS",
            r"QATAR\s*DUTY",
            r"DEPARTURES\s*@SFO",
            r"GOOGLE\*GOOGLE\s*STORE",
            r"\bTEMU\b",
            r"GIFTS?\s+AND\s+SOUVEN",
            r"TRIP\s*ADVISOR\s*SHOP",
        ),
        avoidable=True,
    ),
    # Other Auto (rentals, gas) — EV charging handled above
    CategoryRule(
        "Auto / EV",
        (
            r"SIXT\b",
            r"AUTOMOBILE\s*RENTAL",
            r"FILLING\s*STATION",
            r"CIRCLE\s*K",
        ),
    ),
    CategoryRule(
        "Phone & Internet",
        (
            r"\bVISIBLE\b",
            r"AT&T",
            r"\bATT\b",
            r"ATT\.COM",
            r"ATT\*",
            r"VERIZON",
            r"T-?MOBILE",
            r"COMCAST",
            r"XFINITY",
            r"SPECTRUM",
        ),
    ),
    CategoryRule(
        "Subscriptions",
        (
            r"HULU",
            r"NETFLIX",
            r"SPOTIFY",
            r"PEACOCK",
            r"PRIME\s*VIDEO",
            r"OPENAI",
            r"CHATGPT",
            r"CURSOR",
            r"UBER ONE",
            r"WALMART\+",
            r"SUBSCRIPTION",
            r"VERCEL",
            r"GOOGLE\s*\*CLOUD",
            r"MICROSOFT",
            r"UDEMY",
            r"THELIVEN",
            r"ANARA\s*LABS",
            r"APARTMENTS\.COM",
        ),
        avoidable=True,
    ),
    CategoryRule(
        "Insurance",
        (r"ERENTERPLAN", r"RENTER.?S?\s*INSUR", r"SPRINTAX"),
    ),
    # Card-linked transfers (Add Money / Transfer to Card / plan fee) — not personal spend
    CategoryRule(
        "Transfers",
        (
            r"AMEX SEND",
            r"ADD MONEY",
            r"TRANSFER TO CARD",
            r"PLAN FEE\s*-\s*AMEX SEND",
        ),
        transfer=True,
    ),
    CategoryRule(
        "Payments",
        (
            r"MOBILE PAYMENT",
            r"AUTOPAY",
            r"ONLINE PAYMENT",
            r"PAYMENT - THANK YOU",
            r"ELECTRONIC PAYMENT",
            r"PAYMENT RECEIVED",
            r"ACH PAYMENT",
        ),
        payment=True,
    ),
    CategoryRule(
        "Credits & Refunds",
        (
            r"CREDIT",
            r"REFUND",
            r"GOODWILL",
            r"BENEFIT",
            r"AMEX OFFER",
            r"PROMOTIONAL",
            r"ADJUSTMENT",
        ),
        credit=True,
    ),
    CategoryRule("Rent", (r"BILT RENT", r"\bRENT\b")),
    CategoryRule(
        "Groceries",
        (
            r"TRADER JOE",
            r"JEWEL",
            r"PATEL BROTHER",
            r"MEIJER",
            r"MARIANO",
            r"PETE'?S FRESH",
            r"H MART",
            r"METRO SPICE",
            r"GROCERY",
            r"WHOLEFDS",
            r"WHOLE\s*FOODS",
            r"INSTACART",
            r"\bALDI\b",
            r"COSTCO",
            r"TRIVENI",
            r"365\s*MARKET",
            r"SRI\s*VENKATESWARA",
            r"HARRIS\s*TEETER",
            r"MINI\s*MART",
        ),
    ),
    # Metropolis parking is reimbursed / expensed through company
    CategoryRule(
        "Parking & Transit",
        (r"METROPOLIS\s*PARKING",),
        company_expense=True,
    ),
    CategoryRule(
        "Parking & Transit",
        (r"PARKING",),
    ),
    CategoryRule("Auto / EV", (r"INSURANCE",)),
    CategoryRule(
        "Personal Care",
        (r"GREAT\s*CLIPS", r"LENSCRAFTERS", r"WALGREENS", r"PHARMAC"),
    ),
    CategoryRule("Fitness", (r"MUAY THAI", r"KICKBOX", r"GYM", r"FITNESS")),
    CategoryRule("Pets", (r"CHEWY", r"PAW NATURALS", r"RAINWALK", r"PET\b")),
    CategoryRule("Utilities", (r"COMMONWEALTH EDISON", r"COMED", r"GAS COMPANY")),
    CategoryRule(
        "Travel",
        (
            r"HOTEL",
            r"AMEXTRAVEL",
            r"AIRLINE",
            r"LODGING",
            r"\bCLEAR\b",
            r"CLEARME",
            r"DUTY\s*FREE",
        ),
    ),
    CategoryRule(
        "Shipping & Services",
        (r"UPS\s*STORE", r"USPS", r"FEDEX", r"IMPRINT\s*ENGINE", r"PRINTWITHME"),
    ),
    CategoryRule("Laundry", (r"WE WASH", r"CSC SERVICE", r"CSCSW", r"LAUNDRY")),
    CategoryRule("Fees", (r"PLAN FEE", r"LATE FEE", r"ANNUAL FEE", r"\bFEE\b")),
    CategoryRule(
        "Government / Immigration",
        (
            r"IMMIGRATION",
            r"USCIS",
            r"GOVERNMENT",
            r"SECRETARY OF STATE",
            r"CITY\s*COURT",
        ),
    ),
    CategoryRule(
        "Donations",
        (r"ANTICRUELTY", r"DONATION", r"GO FUND", r"CHARITY"),
        avoidable=True,
    ),
    # Leftover merchants that used to land in Other
    CategoryRule(
        "Parking & Transit",
        (r"\bSPRK\b", r"SPARK\s*PARKING"),
        company_expense=False,
    ),
    CategoryRule(
        "Dining Out",
        (r"SFORD\s*-\s*FB", r"HYATT.*F&B", r"F&B\s*-\s*HYATT"),
        avoidable=True,
    ),
    CategoryRule(
        "Shopping / Impulse",
        (r"IMPORTEXPO", r"MARKETPLACE\s*MAIN"),
        avoidable=True,
    ),
    CategoryRule(
        "Digital / Apps",
        (r"BT\*ATI", r"\bATI\*"),
        avoidable=True,
    ),
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().upper()


_TESLA_CATEGORIES = {"Tesla", "Tesla Insurance", "Tesla FSD", "EV Charging"}


def build_tags(category: str, *, description: str = "", coffee: bool = False,
               avoidable: bool = False, company_expense: bool = False,
               transfer: bool = False, payment: bool = False, credit: bool = False,
               kind: str = "") -> list[str]:
    """Stable tags for filtering — every charge gets at least its category."""
    tags: list[str] = []
    cat = (category or "Misc").strip() or "Misc"
    tags.append(cat)
    if coffee and "Coffee" not in tags:
        tags.append("Coffee")
    if avoidable and "Avoidable" not in tags:
        tags.append("Avoidable")
    if company_expense and "Company" not in tags:
        tags.append("Company")
    if transfer and "Transfers" not in tags:
        tags.append("Transfers")
    if payment or kind == "payment":
        if "Payment" not in tags:
            tags.append("Payment")
    if credit or kind == "credit":
        if "Credit" not in tags and cat != "Credits & Refunds":
            tags.append("Credit")
    desc_upper = _clean(description)
    # Tesla tab set: vehicle, insurance, FSD, and all EV charging (Supercharger + ChargePoint/Jolt/etc.)
    if cat in _TESLA_CATEGORIES and "Tesla" not in tags:
        tags.append("Tesla")
    if "STARBUCKS" in desc_upper and "Starbucks" not in tags:
        tags.append("Starbucks")
    return tags


def categorize(description: str, amount: float) -> dict:
    text = _clean(description)

    for rule in RULES:
        if any(re.search(p, text) for p in rule.patterns):
            # Credits/refunds that match shopping brands should stay credits when amount < 0
            if amount < 0 and rule.category not in {"Payments", "Transfers", "Credits & Refunds"}:
                if any(
                    re.search(p, text)
                    for p in (
                        r"CREDIT",
                        r"REFUND",
                        r"GOODWILL",
                        r"BENEFIT",
                        r"AMEX OFFER",
                        r"PROMOTIONAL",
                        r"ADJUSTMENT",
                        r"TO C\b",
                    )
                ):
                    return {
                        "category": "Credits & Refunds",
                        "avoidable": False,
                        "coffee": False,
                        "transfer": False,
                        "payment": False,
                        "credit": True,
                        "company_expense": False,
                    }
            return {
                "category": rule.category,
                "avoidable": rule.avoidable and amount > 0 and not rule.company_expense,
                "coffee": rule.coffee and amount > 0,
                "transfer": rule.transfer,
                "payment": rule.payment,
                "credit": rule.credit or amount < 0,
                "company_expense": rule.company_expense and amount > 0,
            }

    if amount < 0:
        return {
            "category": "Credits & Refunds",
            "avoidable": False,
            "coffee": False,
            "transfer": False,
            "payment": False,
            "credit": True,
            "company_expense": False,
        }

    return {
        "category": "Misc",
        "avoidable": False,
        "coffee": False,
        "transfer": False,
        "payment": False,
        "credit": False,
        "company_expense": False,
    }
