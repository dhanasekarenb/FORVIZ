"""Package only reviewed CAD/runtime deliverables, with verified STL checksums."""
import csv
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "3d_models" / "v3"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = json.loads((OUT / "validation.json").read_text(encoding="utf-8"))
    if any(report[key] for key in ("mesh_failures", "assembly_overlaps", "nominal_hardware_overlaps")):
        raise SystemExit("CAD report contains failures; refusing to package")
    if report["motion_checks"]["failures"]:
        raise SystemExit("Motion/path checks failed; refusing to package")
    if report["generator_sha256"] != digest(ROOT / "generate_3d_models_v3.py"):
        raise SystemExit("Generator changed since validation; regenerate the CAD first")
    expected = {p["name"] + ".stl" for p in report["parts"]}
    actual = {p.name for p in (OUT / "stl").glob("*.stl")}
    if actual != expected:
        raise SystemExit(f"STL inventory differs from validation: {actual ^ expected}")
    for part in report["parts"]:
        if digest(OUT / "stl" / (part["name"] + ".stl")) != part["stl_sha256"]:
            raise SystemExit("STL changed after validation: " + part["name"])

    with (OUT / "PRINT_MANIFEST.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "quantity", "group", "print_x_mm", "print_y_mm", "print_z_mm", "solid_volume_mass_g", "print_note"])
        for p in report["parts"]:
            writer.writerow([p["name"] + ".stl", p["quantity"], p["group"], *p["print_size_mm"], p["estimated_solid_mass_g"], p["print_note"]])

    paths = [ROOT / name for name in (
        "README.md", "requirements.txt", "requirements-cad.txt", "generate_3d_models_v3.py", "robot_body.scad",
        "pi_tracker.py", "servos.py", "oled_face.py", "test_servos.py", "test_oled.py", "test_vision.py",
        "setup_pi.sh", "enable_dual_oled.sh", "run_pc_test.bat", "cad/v3_fit.json",
        "docs/MECHANICAL_V3.md", "docs/RUNTIME.md", "docs/robot_preview.html", "docs/robot_v3.png",
        "docs/robot_preview_template.html", "tools/build_robot_preview.py", "tools/package_robot_v3.py",
        "tests/test_runtime.py", "3d_models/v3/FORVIZ_V3.scad", "3d_models/v3/FORVIZ_V3_assembly.glb",
        "3d_models/v3/assembly_meshes.json", "3d_models/v3/validation.json", "3d_models/v3/PRINT_MANIFEST.csv")]
    paths += sorted((OUT / "stl").glob("*.stl"))
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("Missing deliverables: " + ", ".join(missing))
    checksum = OUT / "SHA256SUMS.txt"
    checksum.write_text("\n".join(f"{digest(p)}  {p.relative_to(ROOT).as_posix()}" for p in paths) + "\n", encoding="utf-8")
    paths.append(checksum)
    archive = ROOT / "3d_models" / "FORVIZ_V3_bundle.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in paths:
            package.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise SystemExit("Archive verification failed")
    print(f"Packaged {len(paths)} verified files: {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
