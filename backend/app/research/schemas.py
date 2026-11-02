"""Structured outputs of the business research workflow.

The LLM fills these models; app.research.workflow then enforces provenance rules in
code (citations must be real sources, "verified" needs a source, user answers win).
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Basis = Literal["user_provided", "verified", "estimated", "unknown"]

INDUSTRIES = [
    "retail", "ecommerce", "food_beverage", "manufacturing", "professional_services",
    "technology", "healthcare", "education", "hospitality", "real_estate",
    "construction", "logistics", "agriculture", "finance", "other",
]
BUSINESS_MODELS = ["B2B", "B2C", "D2C", "marketplace", "services", "subscription"]
SCALES = ["solo", "small", "growing", "enterprise"]
GEOGRAPHIES = ["local", "regional", "national", "international"]


class SourcedValue(BaseModel):
    value: Optional[str] = Field(description="The value, or null when the evidence does not support one.")
    basis: Basis = Field(description="verified = stated by a cited source; estimated = inferred from evidence; unknown = no evidence.")
    sources: list[str] = Field(default_factory=list, description="URLs from the evidence list that support the value.")
    note: str = Field(default="", description="For estimates: which evidence the estimate rests on.")


class SourcedList(BaseModel):
    values: list[str] = Field(default_factory=list)
    basis: Basis
    sources: list[str] = Field(default_factory=list)
    note: str = ""


class PublicFact(BaseModel):
    fact: str = Field(description="A specific fact stated by a source, e.g. founding year or number of outlets.")
    sources: list[str] = Field(default_factory=list)


class ProfileProposal(BaseModel):
    description: SourcedValue = Field(description="Two or three sentences on what the business does.")
    industry: SourcedValue = Field(description=f"One of: {', '.join(INDUSTRIES)}.")
    subdomain: SourcedValue = Field(description="Specific niche, e.g. 'grocery', 'B2B SaaS for clinics'.")
    business_model: SourcedList = Field(description=f"Any of: {', '.join(BUSINESS_MODELS)}.")
    scale: SourcedValue = Field(description=f"One of: {', '.join(SCALES)}. Usually an estimate; explain the evidence in note.")
    geography: SourcedValue = Field(description=f"Market reach, one of: {', '.join(GEOGRAPHIES)}.")
    location: SourcedValue = Field(description="Headquarters or primary location, e.g. 'Andheri, Mumbai, India'.")
    products_services: SourcedList
    customer_segments: SourcedList
    public_facts: list[PublicFact] = Field(default_factory=list)


class SearchPlan(BaseModel):
    queries: list[str] = Field(description="2-4 web search queries.")


class Competitor(BaseModel):
    name: str
    website: Optional[str] = None
    competition: Literal["direct", "indirect"]
    relative_scale: Literal["similar", "smaller", "larger", "much_larger", "unknown"]
    rationale: str = Field(description="Why this competes for the same customers in the same area.")
    sources: list[str] = Field(default_factory=list)


class CompetitorAnalysis(BaseModel):
    competitors: list[Competitor] = Field(default_factory=list)
    notes: str = ""


class Trend(BaseModel):
    summary: str
    sources: list[str] = Field(default_factory=list)


class Opportunity(BaseModel):
    title: str
    area: str = Field(description="e.g. sales, expenses, inventory, customer retention, marketing, operations, pricing.")
    rationale: str
    basis: Literal["evidence", "general_practice"] = Field(
        description="evidence = grounded in the cited sources or the user's answers; general_practice = common advice for this kind of business."
    )
    sources: list[str] = Field(default_factory=list)


class OpportunityAnalysis(BaseModel):
    industry_trends: list[Trend] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
