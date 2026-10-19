"""SEP-2640 on the wire, and the security rules it imposes on us as the server.

The extension is hand-built on `MethodBinding` because `mcp 2.1.1` has no skills module, so these
tests carry more weight than usual: nothing in the SDK is enforcing the shapes for us.
"""

import hashlib
from pathlib import Path

import pytest

from lifepilot.extensions.skills import (
    IDENTIFIER,
    SCHEME,
    SKILL_ROOT,
    GetSkillParams,
    ListSkillsParams,
    Skills,
    digest_of,
    load_skills,
    parse_frontmatter,
)


@pytest.fixture(scope="module")
def ext() -> Skills:
    return Skills()


def test_the_extension_identifier_is_the_one_the_sep_defines(ext):
    assert IDENTIFIER == "io.modelcontextprotocol/skills"
    assert ext.identifier == IDENTIFIER


def test_it_binds_only_the_two_methods_the_sep_requires(ext):
    assert [m.method for m in ext.methods()] == ["skills/list", "skills/get"]


def test_binding_a_spec_method_would_be_refused():
    """The framework rejects a binding that shadows a spec method. Ours pass because `skills/list`
    and `skills/get` are not spec methods -- which is the whole reason this is legal."""
    from mcp.server.extension import MethodBinding

    with pytest.raises(ValueError, match="cannot bind spec method"):
        MethodBinding("tools/list", ListSkillsParams, lambda ctx, params: None)


def test_directory_read_is_advertised_false_because_it_is_not_implemented(ext):
    """`resources/directory/read` is optional. Claiming it would be a lie on the wire."""
    assert ext.settings() == {"directoryRead": False}


async def test_skills_list_returns_a_complete_catalogue(ext):
    result = await ext._list(None, ListSkillsParams())
    assert result["resultType"] == "complete"
    assert result["skills"], "the server serves at least the LifePilot skill"

    entry = result["skills"][0]
    assert set(entry) == {"uri", "frontmatter", "resources"}
    assert entry["uri"].startswith(f"{SCHEME}://")
    assert entry["uri"].endswith("/SKILL.md")


async def test_every_listed_file_carries_a_digest_and_a_byte_size(ext):
    """A host must verify content against the digest, so a wrong one breaks the skill."""
    result = await ext._list(None, ListSkillsParams())
    for entry in result["skills"]:
        for file in entry["resources"]:
            assert set(file) == {"uri", "digest", "size"}
            assert file["digest"].startswith("sha256:")
            assert file["size"] > 0


async def test_the_digests_match_the_bytes_actually_served(ext):
    """The test that would catch a stale catalogue: a listing whose digests disagree with the
    files served beside them fails a host's verification and the skill never loads."""
    served = {str(b.resource.uri): b.resource.text for b in ext.resources()}
    result = await ext._list(None, ListSkillsParams())

    for entry in result["skills"]:
        for file in entry["resources"]:
            assert file["uri"] in served
            assert digest_of(served[file["uri"]].encode("utf-8")) == file["digest"]
            assert len(served[file["uri"]].encode("utf-8")) == file["size"]


async def test_skills_get_returns_the_same_entry_shape_as_the_listing(ext):
    listed = (await ext._list(None, ListSkillsParams()))["skills"][0]
    got = await ext._get(None, GetSkillParams(uri=listed["uri"]))

    assert got["resultType"] == "complete"
    assert got["skill"] == listed, "the SEP says identical in shape and meaning"


async def test_skills_get_errors_for_a_skill_this_server_does_not_serve(ext):
    """Erroring is the point: it is how a host confirms a URI it was handed elsewhere really is a
    skill this server publishes."""
    with pytest.raises(ValueError, match="serves no skill"):
        await ext._get(None, GetSkillParams(uri="skill://not-ours/SKILL.md"))


def test_the_frontmatter_reported_is_exactly_what_the_file_says(ext):
    """A host compares this field by field against the file it parses itself, and any discrepancy
    means the skill is not loaded. So nothing here may be normalised or inferred."""
    card = SKILL_ROOT / "lifepilot" / "SKILL.md"
    from_file = parse_frontmatter(card.read_text(encoding="utf-8"))
    reported = ext.catalog[0].frontmatter
    assert reported == from_file
    assert reported["name"] == "lifepilot"
    assert reported["description"]


def test_the_skill_declares_no_allowed_tools():
    """The SEP's security rule, kept on our side of the wire. A host must ignore `allowed-tools`
    from an MCP-origin skill without explicit approval, because a remote server populating it is
    requesting elevated access on someone else's machine rather than describing its own. Shipping
    it would be asking for a permission we have no business asking for.
    """
    for card in SKILL_ROOT.rglob("SKILL.md"):
        text = card.read_text(encoding="utf-8")
        assert "allowed-tools" not in text, card
        assert "allowedTools" not in text, card


def test_resources_is_complete_not_only_the_files_skill_md_mentions(tmp_path):
    """A host treats a read of an unlisted file as a verification failure, so every file in the
    directory has to be listed."""
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n", encoding="utf-8")
    (skill / "reference.md").write_text("never mentioned anywhere\n", encoding="utf-8")
    (skill / "scripts").mkdir()
    (skill / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")

    skills = load_skills(tmp_path)
    assert len(skills) == 1
    assert {f.uri for f in skills[0].resources} == {
        "skill://demo/SKILL.md",
        "skill://demo/reference.md",
        "skill://demo/scripts/run.py",
    }


def test_a_directory_without_a_skill_md_is_not_a_skill(tmp_path):
    (tmp_path / "notaskill").mkdir()
    (tmp_path / "notaskill" / "README.md").write_text("hello\n", encoding="utf-8")
    assert load_skills(tmp_path) == []


def test_a_uri_cannot_escape_the_skill_root(ext):
    """The catalogue is built from the filesystem so traversal cannot arrive through it today.
    The guard is where a URI becomes a path, which is the one place it would stop mattering
    quietly."""
    assert ext._path_for("skill://../../etc/passwd") is None
    assert ext._path_for("https://example.com/SKILL.md") is None
    assert ext._path_for("skill://lifepilot/SKILL.md") is not None


def test_the_digest_helper_is_plain_sha256():
    assert digest_of(b"abc") == f"sha256:{hashlib.sha256(b'abc').hexdigest()}"


def test_frontmatter_parsing_ignores_a_file_without_any():
    assert parse_frontmatter("# just a heading\n") == {}


def test_the_skill_root_ships_with_the_repo():
    """A judge running from a fresh clone must get the skill, so it is committed, not generated."""
    assert (Path(SKILL_ROOT) / "lifepilot" / "SKILL.md").is_file()
