from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict


class PipelineError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PipelineError(
            "Command failed:\n"
            f"{' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return (proc.stdout or "") + (proc.stderr or "")


def run_individual_pipeline(
    *,
    workspace_dir: Path,
    scripts_dir: Path,
    xml_path: Path,
    pdf_path: Path,
    artifacts_dir: Path,
    report_id: str | None = None,
    python_bin: str | None = None,
) -> Dict[str, str]:
    py = python_bin or sys.executable
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    xml_standard = artifacts_dir / "individual.standard.json"
    pdf_standard = artifacts_dir / "individual.pdf.standard.json"
    enriched = artifacts_dir / "individual.standard.enriched_labels.json"
    core_tables = artifacts_dir / "individual.core_tables.json"

    parse_xml = scripts_dir / "parse_individual_report.py"
    parse_pdf = scripts_dir / "parse_individual_pdf_report.py"
    enrich = scripts_dir / "enrich_individual_code_labels_from_pdf.py"
    derive_core = scripts_dir / "derive_individual_core_tables.py"

    _run([py, str(parse_xml), str(xml_path), "-o", str(xml_standard)], cwd=workspace_dir)
    _run([py, str(parse_pdf), str(pdf_path), "-o", str(pdf_standard)], cwd=workspace_dir)
    _run(
        [
            py,
            str(enrich),
            "--xml",
            str(xml_standard),
            "--pdf",
            str(pdf_standard),
            "--pdf-file",
            str(pdf_path),
            "-o",
            str(enriched),
        ],
        cwd=workspace_dir,
    )
    derive_cmd = [
        py,
        str(derive_core),
        "--enriched",
        str(enriched),
        "-o",
        str(core_tables),
    ]
    if report_id:
        derive_cmd.extend(["--report-id", report_id])
    _run(derive_cmd, cwd=workspace_dir)

    return {
        "xml_standard": f"artifacts/{xml_standard.name}",
        "pdf_standard": f"artifacts/{pdf_standard.name}",
        "enriched_standard": f"artifacts/{enriched.name}",
        "core_tables": f"artifacts/{core_tables.name}",
    }
