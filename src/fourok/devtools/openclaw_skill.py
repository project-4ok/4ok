from __future__ import annotations

import argparse
import gzip
import io
import json
import tarfile
from pathlib import Path

from fourok.retrieval.clients import cli as cli_client
from fourok.retrieval.clients import openclaw

ARCHIVE_NAME = "fourok-openclaw.tar.gz"
PACKAGE_DIR = "fourok-openclaw"
PACKAGE_PATH = Path("src/fourok/retrieval/clients/openclaw")
REQUIRED_FILES = ("README.md", "SKILL.md", "instructions.md", "openclaw-skill.json")


def validate_openclaw_skill_package() -> dict[str, object]:
    manifest = openclaw.skill_manifest()
    files = _artifact_files()
    checks = [
        _check_required_files(files),
        _check_manifest_schema(manifest),
        _check_client_capabilities(manifest),
        _check_client_only_scope(files, manifest),
    ]
    return {
        "status": "ok" if all(check["status"] == "ok" for check in checks) else "failed",
        "package_path": str(PACKAGE_PATH),
        "manifest": manifest,
        "checks": checks,
    }


def build_openclaw_skill_archive(*, output_dir: Path | str = Path("dist")) -> Path:
    report = validate_openclaw_skill_package()
    if report["status"] != "ok":
        raise ValueError("OpenClaw skill package is not valid")

    output_path = Path(output_dir) / ARCHIVE_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        for name, content in sorted(_artifact_files().items()):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"{PACKAGE_DIR}/{name}")
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(data))

    with output_path.open("wb") as raw_file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0) as gzip_file:
            gzip_file.write(tar_buffer.getvalue())
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m fourok.devtools.openclaw_skill")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()

    if args.command == "validate":
        report = validate_openclaw_skill_package()
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return

    if args.command == "build":
        archive_path = build_openclaw_skill_archive(output_dir=args.output_dir)
        print(json.dumps({"status": "ok", "archive": str(archive_path)}, indent=2))
        return

    raise SystemExit(f"unknown command: {args.command}")


def _artifact_files() -> dict[str, str]:
    return {
        **openclaw.package_files(),
        "openclaw-skill.json": json.dumps(openclaw.skill_manifest(), indent=2, sort_keys=True)
        + "\n",
    }


def _check_required_files(files: dict[str, str]) -> dict[str, str]:
    missing = sorted(set(REQUIRED_FILES) - set(files))
    return _check("required_files", not missing, f"missing files: {', '.join(missing)}")


def _check_manifest_schema(manifest: dict[str, object]) -> dict[str, str]:
    required = {
        "name",
        "display_name",
        "description",
        "version",
        "license",
        "transport",
        "entrypoint",
        "instructions",
        "capabilities",
        "required_commands",
        "recommended_commands",
    }
    missing = sorted(required - set(manifest))
    valid = not missing and manifest.get("transport") == "cli"
    reason = f"missing manifest keys: {', '.join(missing)}" if missing else ""
    if manifest.get("transport") != "cli":
        reason = "transport must be cli"
    return _check("manifest_schema", valid, reason)


def _check_client_capabilities(manifest: dict[str, object]) -> dict[str, str]:
    raw_capabilities = manifest.get("capabilities", ())
    capabilities = tuple(raw_capabilities) if isinstance(raw_capabilities, list) else ()
    expected = cli_client.client_capabilities()
    return _check(
        "client_capabilities",
        capabilities == expected == openclaw.client_capabilities(),
        f"expected capabilities {expected}, got {capabilities}",
    )


def _check_client_only_scope(files: dict[str, str], manifest: dict[str, object]) -> dict[str, str]:
    haystack = "\n".join([*files.values(), json.dumps(manifest, sort_keys=True)]).casefold()
    banned_terms = ("docker compose", "dagster", "database migration")
    banned = [term for term in banned_terms if term in haystack]
    return _check("client_only_scope", not banned, f"contains runtime terms: {', '.join(banned)}")


def _check(name: str, ok: bool, reason: str = "") -> dict[str, str]:
    result = {"name": name, "status": "ok" if ok else "failed"}
    if not ok:
        result["reason"] = reason
    return result


if __name__ == "__main__":
    main()
