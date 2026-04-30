"""Unit tests for topic classification."""

from docket.enrichment.topics import all_topics, classify_topic, classify_topics, get_topic_display_name


class TestClassifyTopic:
    """Tests for classify_topic() — returns primary topic."""

    def test_zoning(self):
        assert classify_topic("Consider rezoning property at 720 Museum Drive") == "zoning"

    def test_zoning_subdivision(self):
        assert classify_topic("Accept dedication of the subdivision plat") == "zoning"

    def test_public_safety_nuisance(self):
        assert classify_topic("Declare structure a public nuisance and order it demolished") == "public_safety"

    def test_public_safety_police(self):
        assert classify_topic("Approve purchase order for police department vehicles") == "public_safety"

    def test_public_works_drainage(self):
        assert classify_topic("5th Avenue South drainage improvements project") == "public_works"

    def test_public_works_resurfacing(self):
        assert classify_topic("2024 PAYGO Resurfacing Commission District 1") == "public_works"

    def test_budget_payment(self):
        assert classify_topic("Approving payment to Amazon Capital Services") == "budget"

    def test_budget_transfer(self):
        assert classify_topic("Transfer funds from District 7 to Grants Project") == "budget"

    def test_grants(self):
        assert classify_topic("Apply for Alabama Humanities Alliance grant funds") == "grants"

    def test_grants_doj(self):
        assert classify_topic("Grant from the U.S. Department of Justice") == "grants"

    def test_grants_safe_streets_also_public_works(self):
        """Safe Streets grant matches public_works first (has 'street'), grants second."""
        topics = classify_topics("Apply for FY 2026 Safe Streets and Roads for All Funding")
        assert "public_works" in topics
        assert "grants" in topics

    def test_contracts(self):
        assert classify_topic("Authorize contract with HCL Contracting, LLC") == "contracts"

    def test_legal_settlement(self):
        assert classify_topic("Authorize settlement in Justin Stallworth case") == "legal"

    def test_legal_general_code(self):
        assert classify_topic("Pursuant to provisions of the General Code") == "legal"

    def test_parks(self):
        assert classify_topic("Birmingham Folk Festival agreement") == "parks_culture"

    def test_library(self):
        assert classify_topic("Purchase of books for Birmingham Public Library") == "parks_culture"

    def test_licensing_liquor(self):
        assert classify_topic("Issuance of a Restaurant Retail Liquor License") == "licensing"

    def test_licensing_noise(self):
        assert classify_topic("Waiver of the Noise Ordinance at 2058 Airport Blvd") == "licensing"

    def test_appointments(self):
        assert classify_topic("Appointing the Employee of the Month") == "appointments"

    def test_appointments_library_board(self):
        """Library Board appointment matches parks_culture first (has 'library')."""
        topics = classify_topics("Appointing two members to the Library Board")
        assert "parks_culture" in topics
        assert "appointments" in topics

    def test_routine_roll_call(self):
        assert classify_topic("ROLL CALL") == "routine"

    def test_routine_adjournment(self):
        assert classify_topic("ADJOURNMENT") == "routine"

    def test_no_match(self):
        assert classify_topic("Miscellaneous item with no keywords") is None

    def test_empty(self):
        assert classify_topic("") is None

    def test_with_description(self):
        assert classify_topic("Item 5", "Approve sidewalk repairs on Main St") == "public_works"


class TestClassifyTopics:
    """Tests for classify_topics() — returns all matching topics."""

    def test_multiple_matches(self):
        topics = classify_topics("Grant for road resurfacing project")
        assert "grants" in topics
        assert "public_works" in topics

    def test_single_match(self):
        assert classify_topics("ROLL CALL") == ["routine"]

    def test_no_match(self):
        assert classify_topics("Generic item") == []


class TestTopicHelpers:
    """Tests for helper functions."""

    def test_get_display_name(self):
        assert get_topic_display_name("zoning") == "Zoning & Land Use"
        assert get_topic_display_name("budget") == "Budget & Finance"

    def test_get_display_name_unknown(self):
        assert get_topic_display_name("nonexistent") is None

    def test_all_topics(self):
        topics = all_topics()
        assert len(topics) > 0
        assert all("slug" in t and "name" in t for t in topics)
        slugs = [t["slug"] for t in topics]
        assert "zoning" in slugs
        assert "budget" in slugs
