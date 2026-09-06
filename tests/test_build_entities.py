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



def test_write_refuses_to_overwrite_a_stored_entity_with_another_identity(tmp_path, monkeypatch):
    import pytest
    import yaml

    from src import build_entities as be
    monkeypatch.setattr(be, "ENTITIES", tmp_path)
    old = {"entity_id": "org:automattic", "names": {"en": "Automattic"}, "category": ["saas"],
           "canonical": {"wikidata": "Q2872634", "github_org": "Automattic", "sources": []},
           "domains": [{"domain": "automattic.com", "role": "primary", "status": "verified", "first_seen": "2026-01-01"}]}
    (tmp_path / "saas").mkdir()
    (tmp_path / "saas" / "automattic.yaml").write_text(yaml.safe_dump(old), encoding="utf-8")
    new = {"entity_id": "org:automattic", "names": {"en": "WordPress.com"}, "category": ["saas"],
           "canonical": {"wikidata": "Q2001888", "github_org": "Automattic", "sources": []},
           "domains": [{"domain": "wordpress.com", "role": "primary", "status": "verified", "first_seen": "2026-09-06"}]}
    with pytest.raises(be.IdentityConflict):
        be.write(new)
    assert yaml.safe_load((tmp_path / "saas" / "automattic.yaml").read_text(encoding="utf-8"))["names"]["en"] == "Automattic"
