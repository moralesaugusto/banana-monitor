from app.llm.agent_tools import ALL_TOOL_NAMES, TOOL_SCHEMAS
from app.llm.tool_guide import RUNS_ON_LABELS, TOOL_GUIDES


def test_every_tool_the_model_can_be_given_has_a_guide() -> None:
    schema_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert schema_names == set(ALL_TOOL_NAMES)
    assert set(TOOL_GUIDES) == schema_names


def test_each_guide_says_where_it_runs_and_what_limits_it() -> None:
    for name, guide in TOOL_GUIDES.items():
        assert guide.runs_on in RUNS_ON_LABELS, name
        assert guide.where and guide.safeguards, name


def test_numbers_in_the_text_come_from_the_handlers_constants() -> None:
    from app.llm.agent_tools import NMAP_TIMEOUT_SECONDS

    assert f"{NMAP_TIMEOUT_SECONDS:.0f} seconds" in " ".join(TOOL_GUIDES["run_nmap"].safeguards)
