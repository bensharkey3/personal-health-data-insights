"""Every Lambda zip in infra/*.tf contains the src modules its files import, so a missing file
fails here rather than as an import error in Lambda."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC_PACKAGES = ("common", "ingest", "transform")


def zips() -> dict[str, set[str]]:
    """archive_file name -> the src paths listed in its for_each."""
    found = {}
    for tf in (ROOT / "infra").glob("*.tf"):
        for name, body in re.findall(
            r'data "archive_file" "(\w+)" \{(.*?)\n\}', tf.read_text(), re.S
        ):
            if m := re.search(r"for_each = \[(.*?)\]", body, re.S):
                found[name] = set(re.findall(r'"([\w/]+\.py)"', m.group(1)))
    return found


def test_zips_contain_their_imports():
    assert zips(), "no archive_file lists found"
    for name, files in zips().items():
        for path in files:
            source = (ROOT / "src" / path).read_text()
            for pkg, names in re.findall(r"^from ([\w.]+) import (.+)$", source, re.M):
                if pkg.split(".")[0] not in SRC_PACKAGES:
                    continue
                base = pkg.replace(".", "/")
                for imported in (n.strip() for n in names.split(",")):
                    # `from pkg import mod` and `from pkg.mod import NAME` both need pkg/mod.py
                    need = f"{base}/{imported}.py"
                    if not (ROOT / "src" / need).exists():
                        need = f"{base}.py"
                    assert need in files, f"{name} zip: {path} imports {need}, not packaged"
