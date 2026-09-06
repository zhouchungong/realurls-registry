"""Categories and labels in build_entities are pure functions of what we know about the entity."""

from src.build_entities import _categories, choose_label, fallback_category


def test_topics_win_over_item_type():
    assert _categories(["cms"], "github", {"isOrg": True, "isGame": True}) == ["saas"]


def test_fallback_follows_the_item_type_not_the_seed_source():
    assert fallback_category("github", {"isOrg": True, "isGov": True}) == "government"
    assert fallback_category("github", {"isOrg": True, "isGame": True, "isMedia": True}) == "games"
    assert fallback_category("github", {"isOrg": True, "isMedia": True}) == "media"
    assert fallback_category("github", {"isOrg": True, "isSoftwareCo": True}) == "saas"
    assert fallback_category("github", {"isOrg": True}) == "other"            # NetEase, Apple: a company, not a project
    assert fallback_category("github", {"isOrg": True, "isEdu": True}) == "other"
    assert fallback_category("github", {"isSoftware": True}) == "open-source"
    assert fallback_category("github", None) == "open-source"
    assert fallback_category("wikidata", None) == "saas"
    assert fallback_category("github", None, "irs.gov") == "government"


def test_label_prefers_the_organizations_own_name_over_a_non_organization_item():
    label, source = choose_label(wikidata="Q3568028", wikidata_label="Wikimedia movement", github_org="wikimedia",
                                 gh_display="Wikimedia", org_name="", repo_label="", domain="wikimedia.org",
                                 wikidata_names_primary=True, wikidata_is_org=False)
    assert label == "Wikimedia" and source.startswith("github_org_display_name")
    label, _ = choose_label(wikidata="Q7128508", wikidata_label="Palo Alto Networks", github_org="bridgecrewio",
                            gh_display="PANW AppSec", org_name="", repo_label="", domain="paloaltonetworks.com",
                            wikidata_names_primary=True, wikidata_is_org=True)
    assert label == "Palo Alto Networks"
