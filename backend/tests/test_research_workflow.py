"""Business research workflow and website safety. No database or network needed."""
import pytest

from app.research.schemas import (
    Competitor, CompetitorAnalysis, Opportunity, OpportunityAnalysis, ProfileProposal, PublicFact,
    SearchPlan, SourcedList, SourcedValue, Trend,
)
from app.research.search import SearchError, SearchResult
from app.research.website import (
    WebPage, WebsiteFetchError, _ensure_public_host, extract_page, normalize_url, pick_interesting_links,
)
from app.research.workflow import ResearchWorkflow, _competitor_queries

pytestmark = pytest.mark.no_db

SHOP = "https://sharmagrocers.example"
NEWS = "https://news.example/sharma-grocers-opens-second-branch"
RIVAL = "https://patelprovisions.example"
GIANT = "https://bigbasket.example"
TREND = "https://trends.example/grocery-2026"


class FakeSearch:
    name = "fake"

    def __init__(self, fail_on: str | None = None):
        self.queries: list[str] = []
        self.fail_on = fail_on

    async def search(self, query, *, max_results=6, country=None):
        self.queries.append(query)
        if self.fail_on and self.fail_on in query:
            raise SearchError("quota exceeded")
        if "trends" in query:
            return [SearchResult("Grocery trends 2026", TREND, "Quick commerce growth in metros")]
        if query.startswith('"Sharma Grocers"'):
            return [SearchResult("Sharma Grocers opens second branch", NEWS, "Opened a second store in 2024")]
        return [SearchResult("Patel Provisions", RIVAL, "Kirana store in Andheri West"),
                SearchResult("BigBasket", GIANT, "Online grocery delivery"),
                SearchResult("Sharma Grocers", SHOP, "Our own site")]


def fake_structured(responses: dict):
    calls = []

    async def structured(schema, system, human):
        calls.append((schema, human))
        return responses[schema]

    structured.calls = calls
    return structured


def proposal(**overrides) -> ProfileProposal:
    base = dict(
        description=SourcedValue(value="Neighbourhood grocery store.", basis="verified", sources=[SHOP]),
        industry=SourcedValue(value="retail", basis="verified", sources=[SHOP]),
        subdomain=SourcedValue(value="grocery", basis="verified", sources=[SHOP]),
        business_model=SourcedList(values=["B2C", "not_a_model"], basis="verified", sources=[SHOP]),
        # Claims "verified" but cites a URL the workflow never saw: must become an estimate.
        scale=SourcedValue(value="small", basis="verified", sources=["https://made-up.example"], note="two stores"),
        geography=SourcedValue(value="planetary", basis="estimated"),
        location=SourcedValue(value="Andheri West, Mumbai", basis="verified", sources=[NEWS]),
        products_services=SourcedList(values=["groceries", "home delivery"], basis="verified", sources=[SHOP]),
        customer_segments=SourcedList(values=[], basis="unknown"),
        public_facts=[PublicFact(fact="Opened a second branch in 2024", sources=[NEWS]),
                      PublicFact(fact="Revenue of 10 crore", sources=["https://made-up.example"])],
    )
    base.update(overrides)
    return ProfileProposal(**base)


def responses(**overrides):
    data = {
        ProfileProposal: proposal(),
        SearchPlan: SearchPlan(queries=["kirana store Andheri West", "grocery delivery Andheri"]),
        CompetitorAnalysis: CompetitorAnalysis(competitors=[
            Competitor(name="Patel Provisions", website=RIVAL, competition="direct", relative_scale="similar",
                       rationale="Same area and customers", sources=[RIVAL]),
            Competitor(name="BigBasket", website=GIANT, competition="indirect", relative_scale="much_larger",
                       rationale="Online alternative", sources=[GIANT, "https://made-up.example"]),
            Competitor(name="Sharma Grocers", website=SHOP, competition="direct", relative_scale="similar",
                       rationale="itself", sources=[SHOP]),
        ]),
        OpportunityAnalysis: OpportunityAnalysis(
            industry_trends=[Trend(summary="Quick commerce growing", sources=[TREND]),
                             Trend(summary="Unsupported trend", sources=["https://made-up.example"])],
            opportunities=[
                Opportunity(title="Repeat-purchase analysis", area="customer retention", rationale="...",
                            basis="evidence", sources=[]),
                Opportunity(title="Match quick-commerce delivery times", area="operations", rationale="...",
                            basis="evidence", sources=["https://made-up.example"]),
            ],
        ),
    }
    data.update(overrides)
    return data


async def site_reader(url):
    return [WebPage(url=SHOP, title="Sharma Grocers - Home", text="Fresh groceries, delivered in Andheri.")]


async def test_workflow_produces_sourced_proposal_and_enforces_provenance():
    progress = []

    async def on_progress(message):
        progress.append(message)

    search = FakeSearch()
    workflow = ResearchWorkflow(
        structured=fake_structured(responses()), search=search, analyze_website=site_reader, progress=on_progress,
    )
    result = await workflow.run({"name": "Sharma Grocers", "website": SHOP, "location": "Andheri, Mumbai", "country": "IN",
                                 "industry": "retail", "goals": ["improve_retention"]})
    profile = result["profile"]

    assert profile["website"]["basis"] == "user_provided"
    assert progress[0] == "Reading sharmagrocers.example"

    # User answers win; differing research is kept as a suggestion.
    assert profile["location"]["value"] == "Andheri, Mumbai" and profile["location"]["basis"] == "user_provided"
    assert profile["location"]["suggested"]["value"] == "Andheri West, Mumbai"
    assert profile["industry"] == {"value": "retail", "basis": "user_provided", "sources": [], "note": ""}

    # Unknown citation stripped and "verified" downgraded; invalid enum values dropped.
    assert profile["scale"]["basis"] == "estimated" and profile["scale"]["sources"] == []
    assert profile["geography"] == {"value": None, "basis": "unknown", "sources": [], "note": ""}
    assert profile["business_model"]["value"] == ["B2C"]
    assert profile["customer_segments"]["basis"] == "unknown"

    # Facts only with real sources: the made-up revenue figure is gone.
    assert [f["fact"] for f in result["public_facts"]] == ["Opened a second branch in 2024"]

    # Competitors: the business itself is excluded; bogus sources removed.
    names = [c["name"] for c in result["competitors"]]
    assert names == ["Patel Provisions", "BigBasket"]
    assert result["competitors"][1]["sources"] == [GIANT]

    # Opportunities: evidence from user answers stays; evidence with only fake URLs is downgraded.
    bases = {o["title"]: o["basis"] for o in result["opportunities"]}
    assert bases == {"Repeat-purchase analysis": "evidence", "Match quick-commerce delivery times": "general_practice"}
    assert [t["summary"] for t in result["industry_trends"]] == ["Quick commerce growing"]

    assert {s["url"] for s in result["sources"]} >= {SHOP, NEWS, RIVAL, TREND}
    assert result["warnings"] == [] and result["search_provider"] == "fake"
    assert any("Andheri" in q for q in search.queries[3:])  # competitor queries are local


async def test_failures_become_warnings():
    async def broken_reader(url):
        raise WebsiteFetchError("timeout")

    workflow = ResearchWorkflow(
        structured=fake_structured(responses()),
        search=FakeSearch(fail_on="trends"),
        analyze_website=broken_reader,
    )
    result = await workflow.run({"name": "Sharma Grocers", "website": "sharmagrocers.example"})
    assert result["profile"]["website"]["basis"] == "user_provided"
    assert any("Could not read the website" in w for w in result["warnings"])
    assert any("quota exceeded" in w for w in result["warnings"])


async def test_no_website_means_no_website_search_and_competitors_without_sites_stay():
    reads = []

    async def reader(url):
        reads.append(url)
        return []

    search = FakeSearch()
    rival = Competitor(name="Corner Kirana", competition="direct", relative_scale="similar", rationale="Next door")
    workflow = ResearchWorkflow(
        structured=fake_structured({**responses(), CompetitorAnalysis: CompetitorAnalysis(competitors=[rival])}),
        search=search,
        analyze_website=reader,
    )
    result = await workflow.run({"name": "Sharma Grocers", "location": "Mumbai, India", "address": "S.V. Road, Andheri West"})
    assert reads == []
    assert not any("website" in q for q in search.queries)
    assert result["profile"]["website"] == {"value": None, "basis": "unknown", "sources": [], "note": ""}
    assert result["profile"]["address"]["value"] == "S.V. Road, Andheri West"
    assert [c["name"] for c in result["competitors"]] == ["Corner Kirana"]
    assert "grocery near S.V. Road, Andheri West, Mumbai, India" in search.queries


def test_competitor_queries_are_forced_local_unless_the_market_is_wider():
    args = dict(sector="food_beverage", address="S.V. Road", location="Mumbai, India", geography="local")
    assert _competitor_queries(["best cafes", "cafes in Mumbai", "tea shops"], **args) == [
        "food beverage near S.V. Road, Mumbai, India", "food beverage in Mumbai, India",
        "best cafes Mumbai, India", "cafes in Mumbai",
    ]
    assert _competitor_queries(["saas crm vendors"], **{**args, "geography": "international"}) == ["saas crm vendors"]
    assert _competitor_queries(["cafes"], sector=None, address="", location=None, geography=None) == ["cafes"]


async def test_workflow_requires_a_name():
    workflow = ResearchWorkflow(structured=fake_structured(responses()), search=FakeSearch(), analyze_website=site_reader)
    with pytest.raises(ValueError):
        await workflow.run({"location": "Mumbai"})


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/admin", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/", "http://192.168.1.1/", "https://example.com:8443/", "ftp://example.com/",
])
async def test_private_and_unusual_targets_are_refused(url):
    with pytest.raises(WebsiteFetchError):
        await _ensure_public_host(url)


def test_url_normalization_and_page_extraction():
    assert normalize_url("example.com") == "https://example.com"
    with pytest.raises(WebsiteFetchError):
        normalize_url("javascript:alert(1)")

    html = b"""<html><head><title> Sharma  Grocers </title><meta name="description" content="Fresh food">
    <script>secret()</script></head><body><h1>Welcome</h1><p>We sell groceries.</p>
    <a href="/about-us">About</a><a href="/products">Products</a><a href="https://other.example/x">x</a>
    <a href="/cart">Cart</a></body></html>"""
    page = extract_page("https://shop.example/", html)
    assert page.title == "Sharma Grocers" and page.description == "Fresh food"
    assert page.headings == ["Welcome"] and "secret" not in page.text and "We sell groceries." in page.text
    assert "https://other.example/x" not in page.links
    assert set(pick_interesting_links(page.links, 5)) == {"https://shop.example/products", "https://shop.example/about-us"}
