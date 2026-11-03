"""Onboarding question catalog, served to the client and used to validate answers.

Questions whose id matches a BusinessProfile column are stored on that column; all
others (industry-specific follow-ups) are stored in BusinessProfile.answers.
A question with `show_if` is asked only when another answer matches, e.g.
{"field": "industry", "in": ["retail"]}.
"""
from app.research.schemas import BUSINESS_MODELS, GEOGRAPHIES, INDUSTRIES, SCALES


def _options(values: list[str], labels: dict[str, str] | None = None) -> list[dict]:
    labels = labels or {}
    return [{"value": v, "label": labels.get(v, v.replace("_", " ").capitalize())} for v in values]


INDUSTRY_LABELS = {
    "ecommerce": "E-commerce", "food_beverage": "Food & beverage", "professional_services": "Professional services",
    "real_estate": "Real estate",
}
SCALE_LABELS = {
    "solo": "Solo founder", "small": "Small business (2–20 people)",
    "growing": "Growing company (20–200)", "enterprise": "Enterprise (200+)",
}
GEOGRAPHY_LABELS = {
    "local": "Local (one city or area)", "regional": "Regional", "national": "National", "international": "International",
}
RETAIL_LIKE = ["retail", "ecommerce", "food_beverage"]
SERVICES_LIKE = ["professional_services", "technology", "education", "finance"]

STEPS: list[dict] = [
    {
        "id": "identity",
        "title": "Your business",
        "description": "The basics. Research uses these to find public information about you.",
        "questions": [
            {"id": "name", "label": "Business name", "type": "text", "required": True},
            {"id": "website", "label": "Website", "type": "url", "placeholder": "example.com",
             "help": "Optional. If you have one, research reads it."},
            {"id": "address", "label": "Business address", "type": "text", "placeholder": "Shop 4, S.V. Road, Andheri West",
             "help": "Optional, but makes the search for nearby competitors much more accurate."},
            {"id": "location", "label": "City and country", "type": "text", "required": True, "placeholder": "Mumbai, India",
             "help": "Used to find local competitors and market information."},
            {"id": "country", "label": "Country code", "type": "text", "placeholder": "IN",
             "help": "Two letters, used to localize web search."},
        ],
    },
    {
        "id": "business",
        "title": "What you do",
        "questions": [
            {"id": "industry", "label": "Industry", "type": "select", "required": True,
             "options": _options(INDUSTRIES, INDUSTRY_LABELS)},
            {"id": "business_model", "label": "Business model", "type": "multiselect",
             "options": _options(BUSINESS_MODELS, {"B2B": "B2B", "B2C": "B2C", "D2C": "D2C"})},
            {"id": "scale", "label": "Size", "type": "select", "options": _options(SCALES, SCALE_LABELS)},
            {"id": "geography", "label": "Market reach", "type": "select", "options": _options(GEOGRAPHIES, GEOGRAPHY_LABELS)},
            {"id": "description", "label": "Describe the business in a sentence or two", "type": "textarea"},
        ],
    },
    {
        "id": "operations",
        "title": "How you operate",
        "description": "A few questions specific to your kind of business.",
        "questions": [
            {"id": "sales_channels", "label": "Where do you sell?", "type": "multiselect",
             "show_if": {"field": "industry", "in": RETAIL_LIKE},
             "options": _options(["in_store", "own_website", "marketplaces", "social_media", "wholesale", "delivery_apps"],
                                 {"in_store": "In store", "own_website": "Own website", "social_media": "Social media",
                                  "delivery_apps": "Delivery apps"})},
            {"id": "location_count", "label": "How many locations or outlets?", "type": "number",
             "show_if": {"field": "industry", "in": RETAIL_LIKE + ["hospitality", "healthcare"]}},
            {"id": "tracks_inventory", "label": "Do you track inventory today?", "type": "select",
             "show_if": {"field": "industry", "in": RETAIL_LIKE + ["manufacturing"]},
             "options": _options(["yes_system", "yes_spreadsheet", "no"],
                                 {"yes_system": "Yes, in a system", "yes_spreadsheet": "Yes, in spreadsheets", "no": "No"})},
            {"id": "production_model", "label": "How do you produce?", "type": "select",
             "show_if": {"field": "industry", "in": ["manufacturing"]},
             "options": _options(["make_to_order", "make_to_stock", "mixed"],
                                 {"make_to_order": "Make to order", "make_to_stock": "Make to stock"})},
            {"id": "billing_model", "label": "How do you bill clients?", "type": "multiselect",
             "show_if": {"field": "industry", "in": SERVICES_LIKE},
             "options": _options(["hourly", "fixed_project", "retainer", "subscription"],
                                 {"fixed_project": "Fixed price per project"})},
            {"id": "team_size", "label": "Team size", "type": "number",
             "show_if": {"field": "industry", "in": SERVICES_LIKE + ["healthcare", "construction"]}},
            {"id": "appointment_based", "label": "Do customers book appointments?", "type": "select",
             "show_if": {"field": "industry", "in": ["healthcare", "hospitality", "professional_services"]},
             "options": _options(["yes", "no"])},
            {"id": "sales_cycle", "label": "Typical B2B sales cycle", "type": "select",
             "show_if": {"field": "business_model", "in": ["B2B"]},
             "options": _options(["days", "weeks", "months"],
                                 {"days": "Days", "weeks": "Weeks", "months": "Months or longer"})},
        ],
    },
    {
        "id": "offering",
        "title": "Offering and customers",
        "questions": [
            {"id": "products_services", "label": "Main products or services", "type": "tags",
             "placeholder": "Type one and press Enter"},
            {"id": "customer_segments", "label": "Who are your customers?", "type": "tags",
             "placeholder": "e.g. families in Andheri, small clinics"},
        ],
    },
    {
        "id": "goals",
        "title": "Goals and challenges",
        "questions": [
            {"id": "goals", "label": "What are you trying to achieve?", "type": "multiselect",
             "options": _options(["increase_revenue", "reduce_costs", "expand_markets", "improve_operations",
                                  "improve_retention", "launch_products", "raise_funding"],
                                 {"increase_revenue": "Increase revenue", "reduce_costs": "Reduce costs",
                                  "expand_markets": "Expand to new markets", "improve_operations": "Improve operations",
                                  "improve_retention": "Keep customers coming back", "launch_products": "Launch new products",
                                  "raise_funding": "Raise funding"})},
            {"id": "challenges", "label": "Where do you struggle most?", "type": "multiselect",
             "options": _options(["sales", "marketing", "inventory", "finance", "customer_retention", "hiring",
                                  "operations", "competition"],
                                 {"finance": "Finance and cash flow", "customer_retention": "Customer retention",
                                  "operations": "Operational efficiency"})},
        ],
    },
    {
        "id": "tools",
        "title": "Tools and what to watch",
        "questions": [
            {"id": "existing_tools", "label": "Tools you use today", "type": "multiselect", "allow_other": True,
             "options": _options(["google_sheets", "excel", "google_workspace", "tally", "quickbooks", "zoho",
                                  "shopify", "crm", "whatsapp_business"],
                                 {"google_sheets": "Google Sheets", "google_workspace": "Google Workspace (Gmail, Calendar)",
                                  "quickbooks": "QuickBooks", "zoho": "Zoho", "shopify": "Shopify",
                                  "crm": "A CRM (HubSpot, Salesforce…)", "whatsapp_business": "WhatsApp Business"})},
            {"id": "monitoring_preferences", "label": "What should BizAssist keep an eye on?", "type": "multiselect",
             "options": _options(["sales_revenue", "expenses_profitability", "competitors", "customer_retention",
                                  "inventory_supply", "marketing", "team_productivity", "market_news"],
                                 {"sales_revenue": "Sales and revenue", "expenses_profitability": "Expenses and profitability",
                                  "competitors": "Competitor pricing and activity", "customer_retention": "Customer retention",
                                  "inventory_supply": "Inventory and supply chain", "marketing": "Marketing performance",
                                  "team_productivity": "Team productivity", "market_news": "Market and industry news"})},
        ],
    },
]

QUESTIONS = {q["id"]: q for step in STEPS for q in step["questions"]}

PROFILE_COLUMNS = {
    "name", "website", "location", "industry", "business_model", "scale", "geography", "description",
    "products_services", "customer_segments", "goals", "challenges", "existing_tools", "monitoring_preferences",
}


class AnswerError(ValueError):
    pass


def normalize_answers(raw: dict) -> dict:
    """Validate answers against the catalog. Unknown keys are dropped; option values are checked."""
    clean: dict = {}
    for key, value in (raw or {}).items():
        question = QUESTIONS.get(key)
        if question is None or value in (None, "", []):
            continue
        qtype = question["type"]
        allowed = {o["value"] for o in question.get("options", [])}
        if qtype in ("text", "url", "textarea"):
            if not isinstance(value, str):
                raise AnswerError(f"{question['label']} must be text.")
            value = value.strip()[:2000]
        elif qtype == "number":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise AnswerError(f"{question['label']} must be a number.") from exc
            if value < 0:
                raise AnswerError(f"{question['label']} can't be negative.")
        elif qtype == "select":
            if value not in allowed:
                raise AnswerError(f"'{value}' is not a valid option for {question['label']}.")
        elif qtype in ("multiselect", "tags"):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise AnswerError(f"{question['label']} must be a list.")
            value = [v.strip()[:200] for v in value if v.strip()]
            if qtype == "multiselect" and not question.get("allow_other"):
                bad = [v for v in value if v not in allowed]
                if bad:
                    raise AnswerError(f"Invalid option(s) for {question['label']}: {', '.join(bad)}.")
            value = list(dict.fromkeys(value))[:30]
        if value not in ("", []):
            clean[key] = value
    if "country" in clean and len(clean["country"]) != 2:
        raise AnswerError("Country code must be two letters, e.g. IN or US.")
    return clean
