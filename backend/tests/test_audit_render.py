"""Rationale rendering (audit-log §7.4, AT16)."""

from app.audit.rationale import PLAN_TEMPLATES, SELECTION_TEMPLATES, render_codes


def test_AT16_unknown_code_renders_raw():
    assert render_codes([{"code": "brand_new_reason", "params": {}}], PLAN_TEMPLATES) == "brand_new_reason"


def test_known_codes_render_as_in_spec_example():
    codes = [
        {"code": "cheapest_complete", "params": {"marginEUR": "550.00"}},
        {"code": "single_product"},
        {"code": "only_deviation", "params": {"attributes": ["brand"]}},
    ]
    assert render_codes(codes, PLAN_TEMPLATES) == "cheapest complete plan (€550.00 below the next); from one product; only the brand differs"


def test_selection_codes():
    assert render_codes([{"code": "top_plan_allowed"}], SELECTION_TEMPLATES) == "the highest-ranked plan, and every guardrail rule passed"
