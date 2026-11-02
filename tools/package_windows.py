"""Create and verify a folder-based Windows release with per-file hashes."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from windows import __version__


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package(source, report_path, destination):
    executable = source / "LumaSense.exe"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["exe_sha256"] == digest(executable), "EXE changed since verification"
    assert {r["case"] for r in report["checks"] if r["pass"]} == {"gui", "watchdog", "lease_guard"}
    assert not (source / "_internal/icuuc.dll").exists(), "Unexpected non-system ICU in package"
    destination.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(source, destination / "LumaSense")
    shutil.copytree(repo / "docs", destination / "docs", ignore=shutil.ignore_patterns("reference", "validation"))
    shutil.copy2(repo / "README.md", destination / "README.md")
    shutil.copy2(repo / "docs/third-party-notices.md", destination / "THIRD_PARTY.md")
    (destination / "firmware").mkdir()
    shutil.copy2(repo / "firmware/README.md", destination / "firmware/README.md")
    verification = {"exe_sha256": report["exe_sha256"], "physical_validation": report["physical_validation"],
                    "checks": [{k: v for k, v in check.items() if k != "screenshot"} for check in report["checks"]]}
    (destination / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    versions = {}
    for name in ("PySide6", "PySide6_Essentials", "shiboken6", "pyserial", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        for file in distribution.files or []:
            if any(term in file.name.lower() for term in ("license", "copying")) and ".dist-info" in str(file):
                target = destination / "licenses" / name / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(file), target)
    files = [{"path": path.relative_to(destination).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}
             for path in sorted(destination.rglob("*")) if path.is_file()]
    manifest = {"version": __version__, "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True)),
                "dependencies": versions, "files": files, "physical_validation": "not_run"}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = destination.parent / (destination.name + ".zip")
    assert not archive.exists(), "ZIP already exists"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(destination.parent).as_posix())
    with zipfile.ZipFile(archive) as output:
        assert output.testzip() is None
        for item in files:
            value = output.read(destination.name + "/" + item["path"])
            assert hashlib.sha256(value).hexdigest() == item["sha256"]
    return {"archive": str(archive), "sha256": digest(archive), "files": len(files), "version": __version__}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(".local/windows-dist/LumaSense"))
    parser.add_argument("--check-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source.resolve(), args.check_report.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
