#!/usr/bin/env python3
"""
translator.py

CLI:
  python translator.py poetry2uv path/to/pyproject.toml > pyproject.uv.toml
  python translator.py uv2poetry path/to/pyproject.toml > pyproject.poetry.toml

What it does:
- Poetry -> uv: [tool.poetry] -> [project], deps -> project.dependencies,
  groups -> [dependency-groups.<name>], extras -> project.optional-dependencies
- uv -> Poetry: reverse mapping (best-effort)
"""

import re
import sys
import tomllib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# TOML minimal writer (no deps)
# -----------------------------

def _toml_escape(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _is_primitive(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None


def _toml_value(x: Any) -> str:
    if x is None:
        # TOML has no null; we omit keys with None upstream
        raise ValueError("None is not representable in TOML. Omit the key instead.")
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, str):
        return _toml_escape(x)
    if isinstance(x, list):
        return "[" + ", ".join(_toml_value(v) for v in x) + "]"
    if isinstance(x, dict):
        # inline table
        items = []
        for k, v in x.items():
            if v is None:
                continue
            items.append(f"{k} = {_toml_value(v)}")
        return "{ " + ", ".join(items) + " }"
    raise TypeError(f"Unsupported type for TOML serialization: {type(x)}")


def dump_toml(data: Dict[str, Any]) -> str:
    """
    Minimal TOML serializer:
    - Writes top-level keys and tables
    - Nested dicts become [a.b] sections
    - Lists of primitives supported
    - Dict values are emitted as tables (not arrays-of-tables)
    """
    lines: List[str] = []

    def emit_table(path: List[str], table: Dict[str, Any]) -> None:
        # Write scalars first
        scalar_items: List[Tuple[str, Any]] = []
        nested_items: List[Tuple[str, Dict[str, Any]]] = []

        for k, v in table.items():
            if v is None:
                continue
            if isinstance(v, dict):
                nested_items.append((k, v))
            else:
                scalar_items.append((k, v))

        if path:
            lines.append(f"[{'.'.join(path)}]")

        for k, v in scalar_items:
            lines.append(f"{k} = {_toml_value(v)}")

        if scalar_items and nested_items:
            lines.append("")

        for k, v in nested_items:
            # blank line between nested tables
            if lines and lines[-1] != "":
                lines.append("")
            emit_table(path + [k], v)

    emit_table([], data)
    # final newline
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------
# Version constraint translation (basic)
# ---------------------------------------

SEMVER_RE = re.compile(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[.-].*)?\s*$")


def _parse_semver(v: str) -> Optional[Tuple[int, int, int]]:
    m = SEMVER_RE.match(v)
    if not m:
        return None
    major = int(m.group(1) or 0)
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return major, minor, patch


def poetry_caret_to_pep440(v: str) -> Optional[str]:
    """
    ^1.2.3 -> >=1.2.3,<2.0.0
    ^0.2.3 -> >=0.2.3,<0.3.0
    ^0.0.3 -> >=0.0.3,<0.0.4
    """
    base = _parse_semver(v)
    if not base:
        return None
    major, minor, patch = base

    if major > 0:
        upper = (major + 1, 0, 0)
    elif minor > 0:
        upper = (major, minor + 1, 0)
    else:
        upper = (major, minor, patch + 1)

    return f">={major}.{minor}.{patch},<{upper[0]}.{upper[1]}.{upper[2]}"


def poetry_tilde_to_pep440(v: str) -> Optional[str]:
    """
    ~1.2.3 -> >=1.2.3,<1.3.0
    ~1.2   -> >=1.2,<1.3
    """
    parts = v.strip().split(".")
    base = _parse_semver(v)
    if not base:
        return None
    major, minor, patch = base

    # If user wrote "~1.2" (no patch), upper is major.(minor+1)
    if len(parts) == 2:
        upper_major, upper_minor = major, minor + 1
        return f">={major}.{minor},<{upper_major}.{upper_minor}"
    # "~1.2.3"
    upper = (major, minor + 1, 0)
    return f">={major}.{minor}.{patch},<{upper[0]}.{upper[1]}.{upper[2]}"


def poetry_version_to_pep508(version: str) -> str:
    """
    Converts Poetry-ish version strings into something acceptable as PEP 440/508.
    Best-effort:
      - ^ and ~ translated to range
      - "*" or "" becomes no spec
      - other strings kept as-is
    """
    s = version.strip()
    if s in ("*", ""):
        return ""
    if s.startswith("^"):
        conv = poetry_caret_to_pep440(s[1:])
        return conv or s
    if s.startswith("~"):
        conv = poetry_tilde_to_pep440(s[1:])
        return conv or s
    return s


# ---------------------------------------
# Dependency parsing / formatting (PEP508)
# ---------------------------------------

@dataclass
class Pep508Dep:
    name: str
    spec: str = ""           # e.g. ">=1,<2"
    extras: List[str] = None # e.g. ["socks"]
    marker: str = ""         # e.g. 'python_version < "3.12"'
    url: str = ""            # e.g. "git+https://...@rev" or "https://..."
    direct_ref: str = ""     # left for future

    def to_pep508(self) -> str:
        extras = ""
        if self.extras:
            extras = "[" + ",".join(self.extras) + "]"
        spec = ""
        if self.spec:
            # ensure commas are kept
            spec = self.spec
        marker = ""
        if self.marker:
            marker = f" ; {self.marker}"
        if self.url:
            return f"{self.name}{extras} @ {self.url}{marker}"
        if spec:
            return f"{self.name}{extras} {spec}{marker}".strip()
        return f"{self.name}{extras}{marker}".strip()


PEP508_SIMPLE_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)\s*"
    r"(?:\[(.*?)\])?\s*"
    r"(?:@\s*([^;]+))?\s*"
    r"(?:([<>=!~].*?))?\s*"
    r"(?:;\s*(.+))?\s*$"
)


def parse_pep508_best_effort(s: str) -> Pep508Dep:
    """
    Very lightweight parser. Keeps markers/spec/url in rough form.
    """
    m = PEP508_SIMPLE_RE.match(s.strip())
    if not m:
        # fallback: whole string treated as name (won't be valid, but we preserve)
        return Pep508Dep(name=s.strip(), spec="")
    name = m.group(1)
    extras = [e.strip() for e in (m.group(2) or "").split(",") if e.strip()] or []
    url = (m.group(3) or "").strip()
    spec = (m.group(4) or "").strip()
    marker = (m.group(5) or "").strip()
    return Pep508Dep(name=name, extras=extras, url=url, spec=spec, marker=marker)


# ---------------------------------------
# Poetry <-> uv transformations
# ---------------------------------------

def poetry_dep_to_pep508(name: str, val: Any) -> Optional[str]:
    """
    Poetry dependencies can be:
      - "requests" = "^2.31"
      - "requests" = {version="^2.31", extras=["socks"], markers="..."}
      - "pkg" = {git="...", rev="..."} or {path="...", develop=true} or {url="..."}
      - "python" = "^3.11"  (we skip, mapped to requires-python)
    """
    if name.lower() == "python":
        return None

    dep = Pep508Dep(name=name, extras=[])

    if isinstance(val, str):
        spec = poetry_version_to_pep508(val)
        dep.spec = spec
        return dep.to_pep508()

    if isinstance(val, dict):
        # extras
        extras = val.get("extras")
        if isinstance(extras, list):
            dep.extras = [str(x) for x in extras]

        # markers
        markers = val.get("markers") or val.get("marker")
        if isinstance(markers, str):
            dep.marker = markers.strip()

        # version
        version = val.get("version")
        if isinstance(version, str):
            dep.spec = poetry_version_to_pep508(version).strip()

        # direct references
        if "git" in val:
            git = str(val["git"]).strip()
            rev = val.get("rev") or val.get("tag") or val.get("branch")
            if rev:
                dep.url = f"git+{git}@{str(rev).strip()}"
            else:
                dep.url = f"git+{git}"
        elif "url" in val:
            dep.url = str(val["url"]).strip()
        elif "path" in val:
            # PEP508 local paths: name @ file:///abs or name @ ./rel (tools vary).
            # We'll keep relative path with "file:" to be explicit if possible.
            path = str(val["path"]).strip()
            if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:\\", path):
                dep.url = f"file://{path}"
            else:
                dep.url = f"file:{path}"

        # If optional=true in Poetry, that's typically handled via extras;
        # we'll keep it as normal dep here and wire extras separately via tool.poetry.extras.
        return dep.to_pep508()

    # unknown type
    return f"{name} {str(val)}"


def poetry_to_uv(pyproject: Dict[str, Any]) -> Dict[str, Any]:
    tool = pyproject.get("tool", {})
    poetry = (tool or {}).get("poetry", {})
    if not isinstance(poetry, dict) or not poetry:
        raise ValueError("No [tool.poetry] section found. This doesn't look like a Poetry pyproject.toml")

    out: Dict[str, Any] = {}
    out["build-system"] = pyproject.get("build-system", {})

    project: Dict[str, Any] = {}
    # basic metadata
    for k_poetry, k_proj in [
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("readme", "readme"),
        ("license", "license"),
        ("keywords", "keywords"),
    ]:
        v = poetry.get(k_poetry)
        if v is not None:
            project[k_proj] = v

    # authors: Poetry uses list of "Name <mail>"
    authors = poetry.get("authors")
    if isinstance(authors, list):
        project["authors"] = [{"name": a.split("<")[0].strip(), "email": a.split("<")[1].strip(" >")} if "<" in a and ">" in a else {"name": a} for a in authors]

    # requires-python from poetry.dependencies.python
    deps = poetry.get("dependencies", {})
    if isinstance(deps, dict):
        py_req = deps.get("python")
        if isinstance(py_req, str):
            project["requires-python"] = poetry_version_to_pep508(py_req).replace(",", ", ")
        elif isinstance(py_req, dict) and isinstance(py_req.get("version"), str):
            project["requires-python"] = poetry_version_to_pep508(py_req["version"]).replace(",", ", ")

    # project.urls from homepage/repository/documentation
    urls: Dict[str, Any] = {}
    for pk, uk in [("homepage", "Homepage"), ("repository", "Repository"), ("documentation", "Documentation")]:
        v = poetry.get(pk)
        if isinstance(v, str) and v.strip():
            urls[uk] = v.strip()
    if urls:
        project["urls"] = urls

    # main dependencies
    project_deps: List[str] = []
    if isinstance(deps, dict):
        for name, val in deps.items():
            pep = poetry_dep_to_pep508(name, val)
            if pep:
                project_deps.append(pep)
    if project_deps:
        project["dependencies"] = project_deps

    # extras -> project.optional-dependencies
    # Poetry extras: [tool.poetry.extras] extra = ["depname", "depname2"]
    poetry_extras = poetry.get("extras", {})
    optional_deps: Dict[str, List[str]] = {}
    if isinstance(poetry_extras, dict):
        for extra_name, extra_list in poetry_extras.items():
            if not isinstance(extra_list, list):
                continue
            # find the matching dependency specs for each dep in extra
            resolved: List[str] = []
            for depname in extra_list:
                if not isinstance(depname, str):
                    continue
                # look up in dependencies dict
                if isinstance(deps, dict) and depname in deps:
                    pep = poetry_dep_to_pep508(depname, deps[depname])
                    if pep:
                        resolved.append(pep)
                else:
                    # fallback: just name
                    resolved.append(depname)
            if resolved:
                optional_deps[str(extra_name)] = resolved
    if optional_deps:
        project["optional-dependencies"] = optional_deps

    out["project"] = project

    # groups -> dependency-groups
    dep_groups: Dict[str, Any] = {}
    group = poetry.get("group", {})
    if isinstance(group, dict):
        for gname, gbody in group.items():
            if not isinstance(gbody, dict):
                continue
            gdeps = gbody.get("dependencies", {})
            if not isinstance(gdeps, dict):
                continue
            items: List[str] = []
            for name, val in gdeps.items():
                pep = poetry_dep_to_pep508(name, val)
                if pep:
                    items.append(pep)
            if items:
                dep_groups[str(gname)] = items
    if dep_groups:
        out["dependency-groups"] = dep_groups

    # carry tool.uv if present (keep user config)
    if isinstance(tool, dict) and "uv" in tool and isinstance(tool["uv"], dict):
        out.setdefault("tool", {})
        out["tool"]["uv"] = tool["uv"]

    return out


def pep508_to_poetry_dep(s: str) -> Tuple[str, Any]:
    """
    Best-effort: "requests[socks] >=2.0 ; python_version<'3.12'"
      -> ("requests", {version=">=2.0", extras=["socks"], markers="python_version<'3.12'"})
    Direct refs:
      -> ("pkg", {url="..."} or {git="..."} when possible)
    """
    dep = parse_pep508_best_effort(s)
    name = dep.name

    # if direct ref
    if dep.url:
        url = dep.url.strip()
        # try detect git+ scheme
        if url.startswith("git+"):
            git_url = url[4:]
            rev = None
            if "@" in git_url:
                git_url, rev = git_url.split("@", 1)
            d: Dict[str, Any] = {"git": git_url}
            if rev:
                d["rev"] = rev
            if dep.extras:
                d["extras"] = dep.extras
            if dep.marker:
                d["markers"] = dep.marker
            return name, d
        if url.startswith("file:") or url.startswith("file://"):
            # map to path if looks relative; otherwise keep url
            # poetry path expects plain path, without file:
            p = url.replace("file://", "").replace("file:", "")
            d2: Dict[str, Any] = {"path": p}
            if dep.marker:
                d2["markers"] = dep.marker
            if dep.extras:
                d2["extras"] = dep.extras
            return name, d2
        d3: Dict[str, Any] = {"url": url}
        if dep.marker:
            d3["markers"] = dep.marker
        if dep.extras:
            d3["extras"] = dep.extras
        return name, d3

    # normal spec
    if not dep.spec and not dep.marker and not dep.extras:
        return name, "*"

    d: Dict[str, Any] = {}
    if dep.spec:
        d["version"] = dep.spec
    else:
        d["version"] = "*"
    if dep.extras:
        d["extras"] = dep.extras
    if dep.marker:
        d["markers"] = dep.marker
    return name, d


def uv_to_poetry(pyproject: Dict[str, Any]) -> Dict[str, Any]:
    project = pyproject.get("project", {})
    if not isinstance(project, dict) or not project:
        raise ValueError("No [project] section found. This doesn't look like a uv/PEP621-style pyproject.toml")

    out: Dict[str, Any] = {}
    out["build-system"] = pyproject.get("build-system", {})

    tool: Dict[str, Any] = {}
    poetry: Dict[str, Any] = {}

    # basic metadata
    for k_proj, k_poetry in [
        ("name", "name"),
        ("version", "version"),
        ("description", "description"),
        ("readme", "readme"),
        ("license", "license"),
        ("keywords", "keywords"),
    ]:
        v = project.get(k_proj)
        if v is not None:
            poetry[k_poetry] = v

    # authors back to "Name <email>"
    authors = project.get("authors")
    if isinstance(authors, list):
        out_authors = []
        for a in authors:
            if isinstance(a, dict):
                nm = str(a.get("name", "")).strip()
                em = str(a.get("email", "")).strip()
                if nm and em:
                    out_authors.append(f"{nm} <{em}>")
                elif nm:
                    out_authors.append(nm)
            elif isinstance(a, str):
                out_authors.append(a)
        if out_authors:
            poetry["authors"] = out_authors

    # urls -> homepage/repository/documentation if match keys
    urls = project.get("urls")
    if isinstance(urls, dict):
        # common keys
        if "Homepage" in urls:
            poetry["homepage"] = urls["Homepage"]
        if "Repository" in urls:
            poetry["repository"] = urls["Repository"]
        if "Documentation" in urls:
            poetry["documentation"] = urls["Documentation"]

    # dependencies
    poetry_deps: Dict[str, Any] = {}
    # python requirement
    req_py = project.get("requires-python")
    if isinstance(req_py, str) and req_py.strip():
        # poetry uses python key in dependencies
        poetry_deps["python"] = req_py.strip()

    deps = project.get("dependencies", [])
    if isinstance(deps, list):
        for s in deps:
            if not isinstance(s, str):
                continue
            name, val = pep508_to_poetry_dep(s)
            poetry_deps[name] = val

    poetry["dependencies"] = poetry_deps

    # optional-dependencies -> tool.poetry.extras + optional deps (Poetry typically has deps + extras list)
    opt = project.get("optional-dependencies")
    extras_table: Dict[str, List[str]] = {}
    if isinstance(opt, dict):
        for extra_name, dep_list in opt.items():
            if not isinstance(dep_list, list):
                continue
            dep_names: List[str] = []
            for dep_str in dep_list:
                if isinstance(dep_str, str):
                    dep_names.append(parse_pep508_best_effort(dep_str).name)
            if dep_names:
                extras_table[str(extra_name)] = dep_names

            # also ensure those deps exist in main dependencies with version info
            for dep_str in dep_list:
                if isinstance(dep_str, str):
                    n, v = pep508_to_poetry_dep(dep_str)
                    # mark optional by keeping in deps; poetry extras references them
                    if n not in poetry_deps:
                        poetry_deps[n] = v

    if extras_table:
        poetry["extras"] = extras_table

    tool["poetry"] = poetry

    # dependency-groups -> tool.poetry.group.<name>.dependencies
    dep_groups = pyproject.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        grp_out: Dict[str, Any] = {}
        for gname, gdeps in dep_groups.items():
            if not isinstance(gdeps, list):
                continue
            gd: Dict[str, Any] = {}
            for s in gdeps:
                if isinstance(s, str):
                    n, v = pep508_to_poetry_dep(s)
                    gd[n] = v
            if gd:
                grp_out[str(gname)] = {"dependencies": gd}
        if grp_out:
            poetry["group"] = grp_out

    # carry tool.uv if present
    existing_tool = pyproject.get("tool", {})
    if isinstance(existing_tool, dict) and "uv" in existing_tool and isinstance(existing_tool["uv"], dict):
        tool["uv"] = existing_tool["uv"]

    out["tool"] = tool
    return out


# ---------------------------------------
# CLI
# ---------------------------------------

def load_toml(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def main(argv: List[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("poetry2uv", "uv2poetry"):
        print(
            "Usage:\n"
            "  python translator.py poetry2uv path/to/pyproject.toml\n"
            "  python translator.py uv2poetry path/to/pyproject.toml\n",
            file=sys.stderr,
        )
        return 2

    mode = argv[1]
    path = argv[2]

    data = load_toml(path)

    if mode == "poetry2uv":
        out = poetry_to_uv(data)
    else:
        out = uv_to_poetry(data)

    sys.stdout.write(dump_toml(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
