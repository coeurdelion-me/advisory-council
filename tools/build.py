#!/usr/bin/env python3
"""Validate both skills and build the release files into dist/.

  dist/advisory-council.zip           the council skill folder, for assistants that install skills

The skill folder is the only source.
Run from the repository root:  python3 tools/build.py
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SKILLS = {"advisory-council": ROOT / "skills" / "advisory-council"}
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
failures = []


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    fm = {}
    for line in m.group(1).split("\n"):
        if re.match(r"^[a-z-]+:", line):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def check(name, folder):
    skill = folder / "SKILL.md"
    if not skill.exists():
        failures.append(f"{name}: no SKILL.md")
        return None
    fm, body = frontmatter(skill.read_text(encoding="utf-8"))
    if fm is None:
        failures.append(f"{name}: SKILL.md has no frontmatter")
        return None
    for k in fm:
        if k not in ALLOWED:
            failures.append(f"{name}: frontmatter field not in the portable spec: {k}")
    if fm.get("name") != name:
        failures.append(f"{name}: frontmatter name is {fm.get('name')!r}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm.get("name", "")) or len(fm.get("name", "")) > 64:
        failures.append(f"{name}: invalid name")
    d = fm.get("description", "")
    if not d or len(d) > 1024 or "<" in d or ">" in d:
        failures.append(f"{name}: description missing, over 1024 characters or has angle brackets ({len(d)})")
    if len(fm.get("compatibility", "")) > 500:
        failures.append(f"{name}: compatibility over 500 characters")
    if len(skill.read_text(encoding="utf-8").splitlines()) > 500:
        failures.append(f"{name}: SKILL.md over 500 lines")
    # every relative link in SKILL.md must resolve
    for target in re.findall(r"\]\(([^)#]+)\)", body):
        if "://" in target:
            continue
        if not (folder / target).exists():
            failures.append(f"{name}: SKILL.md links to {target}, which does not exist")
    return body


def zip_skill(name, folder):
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and "evals" not in p.parts:
                z.write(p, Path(name) / p.relative_to(folder))
        # the licence terms travel with every copy; the code licence only where there is code
        z.write(ROOT / "LICENSE", Path(name) / "LICENSE")
        if (folder / "scripts").exists():
            z.write(ROOT / "LICENSE-CODE", Path(name) / "LICENSE-CODE")
    return out


def main():
    bodies = {n: check(n, f) for n, f in SKILLS.items()}
    if failures:
        print("BUILD FAILED")
        for f in failures:
            print("  -", f)
        return 1
    for n, f in SKILLS.items():
        print(f"built {zip_skill(n, f).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
