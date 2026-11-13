import pytest
from autokaggle import lite
from autokaggle.tests.test_lite import contract


def test_project_required_for_new_and_saved_contracts():
    value = contract()
    assert lite.ready(value)
    del value["bold_project_url"]
    assert not lite.ready(value)
    assert "bold_project_url" in lite.checklist(value)[0]["missing"]
    assert "Which BOLD OS project" in lite.initial()["messages"][0]["content"]


@pytest.mark.parametrize("value", ["Project name", "https://github.com/example/repo", "https://bold-lab-ai.github.io.evil.invalid/bold-os/project.html#id=ok", "https://bold-lab-ai.github.io/bold-os/project.html#id=../bad", "https://bold-lab-ai.github.io/bold-os/project.html#id=x&id=y"])
def test_invalid_project_link_rejected(value):
    with pytest.raises(ValueError, match="BOLD OS project"):
        lite.clean_contract({"bold_project_url": value})


def test_project_link_with_board_and_tab():
    link = "https://bold-lab-ai.github.io/bold-os/project.html#id=card-123&board=neurips&tab=work"
    assert lite.bold_project_id(link) == "card-123"
    assert lite.clean_contract({"bold_project_url": link})["bold_project_url"] == link
