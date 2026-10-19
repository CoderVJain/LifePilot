"""`io.modelcontextprotocol/skills` (SEP-2640), served on the SDK's Extension framework.

SEP-2640 went Final and the hackathon points at Agent Skills, but `mcp 2.1.1` has no skills module
-- checked, not assumed: there is no `mcp/server/skills.py` in the installed wheel, and the pin
`mcp>=2.1,<2.2` is forced by `strands-agents`. A newer SDK does ship one.

`skills/list` and `skills/get` are not spec request methods, so they are legal `MethodBinding`s: the
framework rejects any binding that would shadow a spec method, and these pass. The files themselves
ride on the ordinary Resources primitive, which is exactly what the SEP asks for -- it defines only
a transport binding and delegates the skill format to the Agent Skills specification.

Two things are deliberately **not** done, both security requirements of the SEP rather than
oversights:

* `SKILL.md` carries no `allowed-tools`. For an MCP-origin skill a host must ignore that field
  unless the user explicitly approved the grant, because a remote server populating it is asking
  for elevated access on someone else's machine rather than describing its own. Shipping it would
  be requesting a permission we have no business requesting.
* `directoryRead` is advertised `false`. `resources/directory/read` is optional and unimplemented,
  and claiming it would be a lie on the wire.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp_types import RequestParams

IDENTIFIER = "io.modelcontextprotocol/skills"

#: The conventional scheme for skill files. The SEP privileges no scheme, but names this one.
SCHEME = "skill"

#: Where the skill packages live, one directory per skill, each holding a SKILL.md.
SKILL_ROOT = Path(__file__).resolve().parent.parent.parent / "skill"


class ListSkillsParams(RequestParams):
    """`skills/list` takes an optional pagination cursor and nothing else."""

    cursor: str | None = None


class GetSkillParams(RequestParams):
    """`skills/get` names one skill by the URI of its `SKILL.md`."""

    uri: str


@dataclass(frozen=True)
class SkillFile:
    """One file in a skill, with the digest a host must verify it against."""

    uri: str
    digest: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"uri": self.uri, "digest": self.digest, "size": self.size}


@dataclass(frozen=True)
class Skill:
    """One skill entry, the same shape in `skills/list` and `skills/get`."""

    uri: str
    frontmatter: dict[str, Any]
    resources: tuple[SkillFile, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "frontmatter": self.frontmatter,
            "resources": [file.as_dict() for file in self.resources],
        }


def digest_of(data: bytes) -> str:
    """`sha256:` plus the hex digest, the form the SEP's `digest` field takes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def parse_frontmatter(text: str) -> dict[str, Any]:
    """The YAML frontmatter of a `SKILL.md`, as a flat mapping.

    Hand-parsed rather than pulled in with PyYAML: the fields a skill needs are flat strings, the
    project has no YAML dependency, and adding one for three keys is not worth the wheel. A host
    compares this field by field against the frontmatter it parses from the file itself, so what it
    reports has to be exactly what the file says -- which is why nothing is normalised or inferred.
    """
    if not text.startswith("---"):
        return {}
    _, _, rest = text.partition("---\n")
    body, _, _ = rest.partition("\n---")
    found: dict[str, Any] = {}
    for line in body.splitlines():
        if not line.strip() or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key != key.strip():  # an indented continuation; flat fields only
            continue
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def load_skills(root: Path = SKILL_ROOT) -> list[Skill]:
    """Every skill under `root`: a directory holding a `SKILL.md`, plus its supporting files.

    `resources` is complete by the SEP's rules -- a host treats a read of an unlisted file as a
    verification failure -- so every file in the directory is listed, not only the ones `SKILL.md`
    happens to mention.
    """
    if not root.is_dir():
        return []

    skills = []
    for entry in sorted(root.iterdir()):
        card = entry / "SKILL.md"
        if not entry.is_dir() or not card.is_file():
            continue

        files = []
        for path in sorted(p for p in entry.rglob("*") if p.is_file()):
            data = path.read_bytes()
            files.append(
                SkillFile(
                    uri=_uri(entry.name, path.relative_to(entry).as_posix()),
                    digest=digest_of(data),
                    size=len(data),
                )
            )

        skills.append(
            Skill(
                uri=_uri(entry.name, "SKILL.md"),
                frontmatter=parse_frontmatter(card.read_text(encoding="utf-8")),
                resources=tuple(files),
            )
        )
    return skills


def _uri(skill_name: str, relative: str) -> str:
    return f"{SCHEME}://{skill_name}/{relative}"


class Skills(Extension):
    """Serves this server's skills over SEP-2640.

    The catalog is read once at construction. It is small, it ships with the server, and a listing
    whose digests disagree with the files served alongside them would fail a host's verification --
    so one read is both cheaper and safer than re-reading per request.
    """

    identifier = IDENTIFIER

    def __init__(self, root: Path = SKILL_ROOT):
        self.root = root
        self.catalog = load_skills(root)
        self._by_uri = {skill.uri: skill for skill in self.catalog}

    def settings(self) -> dict[str, Any]:
        # `resources/directory/read` is optional and not implemented; saying otherwise would be a
        # lie on the wire.
        return {"directoryRead": False}

    def resources(self) -> list[ResourceBinding]:
        """Every skill file, as an ordinary MCP resource under its `skill://` URI.

        This is the baseline the SEP rests on: a host that treats resources as a virtual filesystem
        can read an MCP-served skill exactly as it reads a local one.
        """
        bindings = []
        for skill in self.catalog:
            for file in skill.resources:
                path = self._path_for(file.uri)
                if path is None:
                    continue
                bindings.append(
                    ResourceBinding(
                        resource=TextResource(
                            uri=file.uri,
                            name=path.name,
                            description=f"{skill.frontmatter.get('name', 'skill')} / {path.name}",
                            mime_type="text/markdown" if path.suffix == ".md" else "text/plain",
                            text=path.read_text(encoding="utf-8"),
                        )
                    )
                )
        return bindings

    def methods(self) -> list[MethodBinding]:
        return [
            MethodBinding("skills/list", ListSkillsParams, self._list),
            MethodBinding("skills/get", GetSkillParams, self._get),
        ]

    async def _list(self, ctx: Any, params: ListSkillsParams) -> dict[str, Any]:
        """The whole catalog. Small enough that a partial listing would be a pretence."""
        return {
            "resultType": "complete",
            "skills": [skill.as_dict() for skill in self.catalog],
        }

    async def _get(self, ctx: Any, params: GetSkillParams) -> dict[str, Any]:
        """One skill by the URI of its `SKILL.md`.

        A server must answer for every skill it serves, listed or not, and error for one it does
        not. Erroring is the point: it is how a host confirms that a URI it was handed somewhere
        else really is a skill this server publishes.
        """
        skill = self._by_uri.get(params.uri)
        if skill is None:
            raise ValueError(f"this server serves no skill at {params.uri!r}")
        return {"resultType": "complete", "skill": skill.as_dict()}

    def _path_for(self, uri: str) -> Path | None:
        """The file a `skill://` URI names, or None if it escapes the skill root.

        The catalog is built from the filesystem, so a traversal cannot arrive through it today.
        The check is here because this resolves a URI to a path, and that is the one place where it
        would ever stop mattering quietly.
        """
        prefix = f"{SCHEME}://"
        if not uri.startswith(prefix):
            return None
        path = (self.root / uri[len(prefix):]).resolve()
        if not path.is_file() or self.root.resolve() not in path.parents:
            return None
        return path
