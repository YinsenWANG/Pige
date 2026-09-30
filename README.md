# Pige

This repository preserves the [Pige Product Requirements](docs/PRD.md). It is a
preserved requirements snapshot with this reading guide and documentation checks.
No application, product tests, build system, or release infrastructure is included.
The Alpha has not been released.

The PRD's original contract metadata and requirements are retained. Its
`v0.1 Public Alpha` is a specified target, not a release status. Read the
non-normative repository reading-boundary note before section 0 for the status of
historical owner references.

Run `python3 -B .github/scripts/check_docs.py` locally. The Documentation CI
workflow runs this documentation-only check and its stdlib unit tests on pushes
and pull requests. It checks the complete original PRD bytes and approved reading
boundary, basic Markdown encoding and fences, local Markdown links, and this
guide's repository status. Missing historical PRD links are reported as
acknowledged unavailable references; network links are not visited.

Run the checker tests with
`python3 -B -m unittest discover -s .github/scripts -p 'test_check_docs.py' -v`.
