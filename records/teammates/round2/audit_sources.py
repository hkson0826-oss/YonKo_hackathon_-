"""Read pinned Git objects and record teammate source comparisons; no bot execution."""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
OLD = "351c32e027b5598ddb53c49b6e7f2d7c9c6c6a4e"
TEAM = "7148f5d7e60bfa5eae34694743cc1c5275869748"
MAIN = "a3c810bfa58472d89396928e0fb6e34e945f20e9"


def read_git(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def digest(data):
    return sha256(data).hexdigest()


def preserve(path, data):
    target = OUTPUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != data:
            raise RuntimeError(f"Refusing to replace existing record: {target}")
    else:
        target.write_bytes(data)
    return str(target.relative_to(ROOT))


def main():
    if (OUTPUT / "source-audit.json").exists():
        raise SystemExit("Audit already exists; use a separate directory for a new audit.")
    old_data = read_git(OLD, "submissions/delineate-v1.zip")
    new_data = read_git(MAIN, "yk-development-tools/out/submission-python.zip")
    old = zipfile.ZipFile(BytesIO(old_data))
    new = zipfile.ZipFile(BytesIO(new_data))
    identical = []
    for name in old.namelist():
        source = read_git(TEAM, "bots/delineate_v1/" + name)
        identical.append({"file": name, "old_zip_sha256": digest(old.read(name)),
                          "team_source_sha256": digest(source),
                          "identical": old.read(name) == source})
    template = []
    for name in new.namelist():
        sample = (ROOT / "yk-python-sample" / name).read_bytes()
        template.append({"file": name, "zip_bytes": len(new.read(name)),
                         "zip_sha256": digest(new.read(name)),
                         "sample_sha256": digest(sample),
                         "identical": sample == new.read(name)})
    paths = ["bots/delineate_v1/main.py", "bots/delineate_v1/STRATEGY.md",
             "docs/rule.md", "docs/operation_rule.md", "docs/instructure.md",
             "docs/development_log.md", "docs/llm_usage_log.md",
             "test-results/delineate-v1/results.json", "bots/test_delineate_v1.py"]
    snapshots = []
    for path in paths:
        data = read_git(TEAM, path)
        local = preserve("team-7148f5d/" + path, data)
        snapshots.append({"commit": TEAM, "source_path": path,
                          "sha256": digest(data), "local_path": local})
    zip_path = preserve("main-a3c810b/submission-python.zip", new_data)
    main_source = preserve("main-a3c810b/main.py", new.read("main.py"))
    results = json.loads(read_git(TEAM, "test-results/delineate-v1/results.json"))
    anchors = ["submissions/tuned/main.cpp", "artifacts/submission-v2.zip",
               "yk-development-tools/docs/rulebook.md",
               "yk-development-tools/bots/dist/starter/limits.json",
               "yk-development-tools/config/balance.json"]
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "static_source_audit_no_new_matches",
        "old_teammate_commit": OLD, "team_commit": TEAM, "main_commit": MAIN,
        "old_zip_sha256": digest(old_data),
        "main_zip": {"sha256": digest(new_data), "bytes": len(new_data),
                     "local_path": zip_path, "main_source_path": main_source},
        "teammate_comparison": identical, "main_template_comparison": template,
        "snapshots": snapshots,
        "local_anchors": [{"path": p, "sha256": digest((ROOT / p).read_bytes())}
                          for p in anchors],
        "teammate_recorded_results": {
            "rerun": False, "matches": len(results),
            "wins": sum(r["winner"] == r["team"] for r in results),
            "seeds": sorted({r["seed"] for r in results}),
            "opponents": sorted({r["opponent"] for r in results}),
            "max_first_decision_ms": max(r["first_decision_ms"] for r in results),
            "max_later_decision_ms": max(r["max_later_decision_ms"] for r in results),
            "subprocess_transcripts_ok": all(r["subprocess_transcript_ok"] for r in results),
            "timing_scope": "decision function only, not server turn latency"
        },
        "decision": {
            "team_code": "keep existing frozen opponent; no new algorithm or rerun",
            "main_zip": "starter template; do not replace v2",
            "operation_rules": "pending verification against official current source"
        },
        "audit_script_sha256": digest(Path(__file__).read_bytes())
    }
    (OUTPUT / "source-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert all(row["identical"] for row in identical)
    assert all(row["identical"] for row in template)
    print(json.dumps({"team_files_identical": len(identical),
                      "main_files_identical_to_template": len(template),
                      "new_matches": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
