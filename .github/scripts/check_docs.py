"""Small, offline documentation checks; no Markdown renderer or product checks."""

import hashlib
import html
import os
from pathlib import Path
import posixpath
import re
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).absolute().parents[2]
BASELINE_COMMIT = "0c8fde312947455d9d6687ce2740976b73a74907"
BASELINE_SIZE = 99711
BASELINE_SHA256 = "f853b42308ecdc7a260dd4a3b82b409124f600e946d279bbbf81422739b96314"
BOUNDARY = b"""## Repository Reading Boundary (Non-Normative)

This repository is a PRD-only preserved snapshot. The original `Status: Active
product contract`, `Baseline date`, and `Last reviewed` metadata describe the
preserved PRD contract, not current implementation or readiness. `v0.1 Public
Alpha` is the specified product target, not the repository's release status.

The following retained references are historical, unavailable owner references
in this snapshot:

- `docs/START_HERE_FOR_AI_AGENTS.md`
- `resources/traceability/p0-coverage.manifest.json`
- `docs/SPEC_TRACEABILITY.md`
- `docs/V0_1_IMPLEMENTATION_PLAYBOOK.md`
- `resources/traceability/acceptance.manifest.json`
- `AGENTS.md`
- `docs/AI_DEVELOPMENT_GUIDE.md`

The same availability boundary applies throughout this PRD to all other absent
owner documents, manifests, schemas, tools, tests, build systems, CI workflows,
and release infrastructure. Retained references do not establish their presence,
implementation evidence, or release readiness, or authorize reconstruction. This
note describes repository availability only; it does not change the preserved
requirements, normative language, stable IDs, or P0/P1/P2 scope.

"""
HISTORICAL_LINKS = frozenset({
    "docs/DATA_ARCHITECTURE.md",
    "docs/JOB_OPERATION_AND_RECOVERY.md",
    "docs/DECISION_LOG.md",
    "docs/START_HERE_FOR_AI_AGENTS.md",
})


class DocsError(ValueError):
    pass


def git(root, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1")
    return subprocess.check_output(["git", "-C", str(root), *args], env=env)


def safe_path(root, relative):
    """Inspect only paths within root, rejecting symlinks before any file read."""
    if relative.startswith("/") or "\\" in relative or "\x00" in relative:
        raise DocsError(f"unsafe repository path: {relative!r}")
    normalized = posixpath.normpath(relative)
    if normalized == ".." or normalized.startswith("../"):
        raise DocsError(f"path escapes repository: {relative!r}")
    current = root
    for part in Path(normalized).parts:
        if part in {".git", ".aws", ".codex", ".agents", "secrets", "credentials"} or part == ".env" or part.startswith(".env."):
            raise DocsError(f"protected path: {relative!r}")
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            # Do not continue through a missing intermediate directory.
            raise FileNotFoundError(relative) from None
        if stat.S_ISLNK(mode):
            raise DocsError(f"symlink is not followed: {relative!r}")
    return current


def check_prd(data, baseline):
    if len(baseline) != BASELINE_SIZE or hashlib.sha256(baseline).hexdigest() != BASELINE_SHA256:
        raise DocsError("unexpected original PRD baseline")
    section = b"## 0. Contract Authority And AI Use\n"
    offset = baseline.index(section)
    expected = baseline[:offset] + BOUNDARY + baseline[offset:]
    if data != expected:
        raise DocsError("PRD must contain exactly the original bytes plus the approved 25-line boundary and seven historical entries")


def markdown_body(data, name):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DocsError(f"{name}: invalid UTF-8") from error
    if "\x00" in text or text.startswith("\ufeff"):
        raise DocsError(f"{name}: NUL or byte-order mark")
    body = []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= fence[1] and not match[2].strip():
                fence = None
            continue
        if match:
            if match[1][0] == "`" and "`" in match[2]:
                raise DocsError(f"{name}:{number}: malformed fence info")
            fence = (match[1][0], len(match[1]), number)
        else:
            body.append(line)
    if fence:
        raise DocsError(f"{name}:{fence[2]}: unclosed Markdown fence")
    # Inline code is not a link. Use equal-length backtick delimiters.
    return re.sub(r"(`+)(?!`)(.*?)\1(?!`)", "", "\n".join(body), flags=re.S)


def link_targets(body, name):
    """Inline links/images and reference links, including balanced URL parentheses."""
    definitions = {}
    normalize = lambda label: " ".join(label.split()).casefold()
    for match in re.finditer(r'^ {0,3}\[([^]\n]+)\]:\s*(<[^>\n]+>|\S+)', body, re.M):
        definitions[normalize(match[1])] = match[2].strip("<>")
    body = re.sub(r'^ {0,3}\[[^]\n]+\]:[^\n]*', "", body, flags=re.M)
    yield from definitions.values()
    # Consume labels separately so nested brackets in an image label are harmless.
    for match in re.finditer(r"\[([^]\n]*)\](\(|\[([^]\n]*)\])", body):
        if match[2] != "(":
            label = normalize(match[3] or match[1])
            if label not in definitions:
                raise DocsError(f"{name}: undefined Markdown reference: {label}")
            yield definitions[label]
            continue
        start = match.end()
        depth, end = 1, start
        while end < len(body) and depth:
            char = body[end]
            if char == "\\":
                end += 2
                continue
            depth += (char == "(") - (char == ")")
            end += 1
        if depth:
            raise DocsError(f"{name}: unclosed Markdown link")
        content = body[start:end - 1].strip()
        destination = re.match(r'<([^>\n]*)>|((?:\\.|[^\s])+)', content)
        if destination:
            yield destination[1] if destination[1] is not None else destination[2]
    # Shortcut references are links only if a matching definition exists.
    for match in re.finditer(r"\[([^]\n]+)\](?![\[(])", body):
        label = normalize(match[1])
        if label in definitions:
            yield definitions[label]


def check_links(root, name, body):
    acknowledged = set()
    for target in link_targets(body, name):
        target = html.unescape(re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", target))
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue  # No network access; same-document fragments need no file lookup.
        path = unquote(url.path)
        if path.startswith("/"):
            raise DocsError(f"{name}: absolute local link: {target}")
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
        try:
            safe_path(root, relative)
        except FileNotFoundError:
            if name == "docs/PRD.md" and relative in HISTORICAL_LINKS:
                acknowledged.add(relative)
            else:
                raise DocsError(f"{name}: broken local link: {target}") from None
    return acknowledged


def check_readme(data, body):
    text = " ".join(data.decode("utf-8").split())
    required = (
        "preserved requirements snapshot", "No application, product tests, build system, or release infrastructure is included.",
        "The Alpha has not been released.", "documentation-only check", "Documentation CI",
    )
    if any(phrase not in text for phrase in required):
        raise DocsError("README must describe the snapshot, documentation checks, absent product infrastructure, and unreleased Alpha")
    if "docs/PRD.md" not in set(link_targets(body, "README.md")):
        raise DocsError("README must link to docs/PRD.md")
    if re.search(r"\b(?:production[ -]ready|release[ -]ready|ready for (?:release|production)|Alpha (?:is )?(?:released|available)|no (?:tests|(?:GitHub Actions )?workflows?))\b", text, re.I):
        raise DocsError("README contains a readiness/release claim or outdated check status")


def check_repository(root):
    baseline = git(root, "show", f"{BASELINE_COMMIT}:docs/PRD.md")
    names = {os.fsdecode(name) for name in git(root, "ls-files", "-z").split(b"\x00") if name}
    # Required documents are checked even before a local first staging.
    names = {name for name in names if name.lower().endswith(".md")} | {"README.md", "docs/PRD.md"}
    acknowledged = set()
    for name in sorted(names):
        path = safe_path(root, name)
        if not path.is_file():
            raise DocsError(f"{name}: Markdown source is not a file")
        data = path.read_bytes()
        body = markdown_body(data, name)
        if name == "docs/PRD.md":
            check_prd(data, baseline)
        elif name == "README.md":
            check_readme(data, body)
        acknowledged.update(check_links(root, name, body))
    return len(names), acknowledged


def main():
    try:
        count, acknowledged = check_repository(ROOT)
    except (DocsError, OSError, subprocess.CalledProcessError) as error:
        print(f"Documentation check FAILED: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {count} Markdown files; original PRD {BASELINE_SIZE} bytes preserved exactly; approved 25-line boundary and seven historical entries present.")
    for name in sorted(acknowledged):
        print(f"ACKNOWLEDGED UNAVAILABLE (historical PRD link): {name}")
    print("PASS: README status, UTF-8, Markdown fences, and local links; network URLs not visited.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
