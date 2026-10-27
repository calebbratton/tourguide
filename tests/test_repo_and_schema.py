import copy
import json
from pathlib import Path

import pytest

from tourguide.render import bundle, render_html
from tourguide.repo import Repo, RepoError
from tourguide.schema import referenced_files, validate

HERE = Path(__file__).parent
MINI = HERE / "fixtures" / "mini"


@pytest.fixture
def repo():
    return Repo(MINI)


@pytest.fixture
def wt():
    return json.loads((HERE / "fixtures" / "mini_walkthrough.json").read_text())


def test_read_file_numbers_lines(repo):
    out = repo.read_file("app/store.py", 6, 8)
    assert out.splitlines()[0] == "app/store.py (lines 6-8 of 16)"
    assert out.splitlines()[1].strip().startswith("6  def create")


def test_paths_cannot_escape_repo(repo):
    with pytest.raises(RepoError):
        repo.read_file("../mini_walkthrough.json")


def test_search_and_list(repo):
    assert "app/agent.py:7:" in repo.search(r"read\(")
    assert "store.py (16 lines)" in repo.list_dir(".", 2)


def test_valid_walkthrough_passes(repo, wt):
    assert validate(wt, repo) == []


def test_bad_line_ranges_and_links_are_reported(repo, wt):
    bad = copy.deepcopy(wt)
    bad["steps"][1]["highlights"][0]["end"] = 99
    bad["steps"][2]["topic"] = "nope"
    bad["steps"][0]["explanation"]["deep"] = "See [x](app/missing.py#L1)."
    bad["steps"][1]["links"][0]["url"] = "docs/local.md"
    problems = "\n".join(validate(bad, repo))
    assert "outside app/store.py (1-16)" in problems
    assert "'nope' is not one of" in problems
    assert "app/missing.py" in problems
    assert "absolute http(s) URL" in problems


def test_referenced_files_include_inline_code_links(wt):
    assert referenced_files(wt) == ["app/agent.py", "app/store.py"]


def test_render_escapes_script_tags(repo, wt):
    page = render_html(bundle(wt, repo, name="mini", url=None, ref=None))
    assert "</script><script>alert(1)" not in page
    assert page.startswith("<!doctype html>")
    data = page.split('id="walkthrough-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["files"]["app/store.py"].startswith('"""A tiny CRUD store')
