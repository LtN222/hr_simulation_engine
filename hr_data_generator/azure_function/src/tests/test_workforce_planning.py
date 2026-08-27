from src.application.allocation import (
    allocate_headcount,
    role_capacity,
    role_is_active,
    role_target_ratio,
    scope_headcount,
    team_lead_requirement,
    team_lead_role_name,
)


def test_initial_allocation_excludes_roles_not_staffed_at_start():
    structure = {
        "Productie": {
            "Operator": {"target_weight": 3, "initially_staffed": True},
            "Plant Manager": {
                "target_weight": 1,
                "leidinggevend": True,
                "initially_staffed": False,
                "active_from_headcount": 20,
            },
        }
    }

    allocations = allocate_headcount(
        structure,
        10,
        workforce_planning={"department_target_weights": {"Productie": 1}},
    )

    assert allocations == [{
        "Afdeling_Naam": "Productie",
        "Functie_Naam": "Operator",
        "count": 10,
        "remainder": 0.0,
    }]


def test_department_target_weights_control_the_long_term_mix():
    structure = {
        "Productie": {"Operator": {"target_weight": 1}},
        "Directie": {"Managing Director": {"target_weight": 1}},
    }
    planning = {"department_target_weights": {"Productie": 52, "Directie": 1}}

    assert role_target_ratio(structure, "Productie", "Operator", planning) == 52 / 53
    assert role_target_ratio(structure, "Directie", "Managing Director", planning) == 1 / 53


def test_role_is_active_defaults_to_company_headcount():
    role_config = {"active_from_headcount": 100}

    assert role_is_active(role_config, company_headcount=99) is False
    assert role_is_active(role_config, company_headcount=100) is True


def test_role_is_active_can_scope_to_department_headcount():
    role_config = {"active_from_headcount": 5, "active_from_scope": "department"}

    # A department-scoped role must not unlock merely because the company as
    # a whole is large; only its own department's headcount matters.
    assert role_is_active(
        role_config, company_headcount=500, department_headcount=4
    ) is False
    assert role_is_active(
        role_config, company_headcount=6, department_headcount=5
    ) is True


def test_role_is_active_with_no_threshold_is_always_active():
    assert role_is_active({}, company_headcount=0) is True


def test_initial_allocation_includes_a_role_once_its_headcount_threshold_is_met():
    """A large starting headcount must produce the richer structure that
    size would actually have grown into, not the small-headcount role mix
    stretched thin over more people. `initially_staffed` alone must not be
    able to keep a role out once its own activation threshold is cleared."""
    structure = {
        "Productie": {
            "Operator": {"target_weight": 3, "initially_staffed": True},
            "Plant Manager": {
                "target_weight": 1,
                "leidinggevend": True,
                "initially_staffed": False,
                "active_from_headcount": 20,
            },
        }
    }

    small = allocate_headcount(
        structure,
        10,
        staffing_rules={"minimum_count_for_manager_role": 1},
        workforce_planning={"department_target_weights": {"Productie": 1}},
    )
    large = allocate_headcount(
        structure,
        200,
        staffing_rules={"minimum_count_for_manager_role": 1},
        workforce_planning={"department_target_weights": {"Productie": 1}},
    )

    assert "Plant Manager" not in {a["Functie_Naam"] for a in small if a["count"] > 0}
    assert "Plant Manager" in {a["Functie_Naam"] for a in large if a["count"] > 0}


def test_initial_allocation_gates_department_scoped_roles_by_estimated_department_share():
    """Department-scoped activation must key off that department's own
    estimated share of the total, not merely a large total headcount."""
    structure = {
        "Productie": {"Operator": {"target_weight": 98, "initially_staffed": True}},
        "Directie": {
            "CEO": {"target_weight": 1, "initially_staffed": True},
            "COO": {
                "target_weight": 1,
                "leidinggevend": True,
                "initially_staffed": False,
                "active_from_headcount": 5,
                "active_from_scope": "department",
            },
        },
    }
    planning = {"department_target_weights": {"Productie": 98, "Directie": 2}}

    small = allocate_headcount(structure, 100, workforce_planning=planning)
    large = allocate_headcount(structure, 1000, workforce_planning=planning)

    assert "COO" not in {a["Functie_Naam"] for a in small if a["count"] > 0}
    assert "COO" in {a["Functie_Naam"] for a in large if a["count"] > 0}


def test_role_capacity_reads_the_configured_max_count():
    assert role_capacity({"max_count": 1}) == 1
    assert role_capacity({}) is None


def test_scope_headcount_sums_a_department_group():
    role_config = {
        "active_from_scope": "department_group",
        "active_from_departments": ["Sales", "Marketing"],
    }
    department_headcounts = {"Sales": 20, "Marketing": 8, "Finance": 100}

    assert scope_headcount(role_config, "Directie", department_headcounts) == 28


def test_scope_headcount_uses_the_roles_own_department_otherwise():
    role_config = {"active_from_scope": "department"}
    department_headcounts = {"IT": 4, "HR": 12}

    assert scope_headcount(role_config, "IT", department_headcounts) == 4


def test_allocate_headcount_never_exceeds_a_roles_max_count():
    """Even a very large starting headcount must not allocate more than one
    seat to a role that's a single fixed seat regardless of company size."""
    structure = {
        "Directie": {
            "Staff": {"target_weight": 1, "initially_staffed": True},
            "CEO": {
                "target_weight": 1,
                "leidinggevend": True,
                "initially_staffed": True,
                "max_count": 1,
            },
        },
    }
    planning = {"department_target_weights": {"Directie": 1}}

    allocations = allocate_headcount(structure, 1000, workforce_planning=planning)

    ceo_count = next(a["count"] for a in allocations if a["Functie_Naam"] == "CEO")
    assert ceo_count == 1
    assert sum(a["count"] for a in allocations) == 1000


def test_team_lead_role_name_picks_the_lowest_salaried_manager_role():
    """Regression guard: the sector config stores a role's pay range as
    `salaris_range`, not `salaris_max` - a lookup keyed on the wrong field
    always misses and silently falls back to dict order instead of genuinely
    ordering by salary."""
    manager_roles = [
        ("Manager", {"salaris_range": [80000, 110000]}),
        ("Teamleider", {"salaris_range": [45000, 60000]}),
    ]

    assert team_lead_role_name(manager_roles) == "Teamleider"


def test_team_lead_role_name_is_none_without_any_manager_roles():
    assert team_lead_role_name([]) is None


def test_team_lead_requirement_scales_with_non_manager_headcount():
    assert team_lead_requirement(84, max_team_size=10) == 9
    assert team_lead_requirement(0, max_team_size=10) == 0


def test_team_lead_requirement_is_none_when_unconfigured():
    assert team_lead_requirement(84, max_team_size=0) is None
