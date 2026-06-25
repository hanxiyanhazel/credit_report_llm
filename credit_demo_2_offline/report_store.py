from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class ReportStore:
    data_root: Path

    @property
    def data_dir(self) -> Path:
        return self.data_root

    @property
    def builtin_root(self) -> Path:
        return self.data_dir / "builtin"

    @property
    def uploads_root(self) -> Path:
        return self.data_dir / "uploads" / "reports"

    def ensure_dirs(self) -> None:
        self.builtin_root.mkdir(parents=True, exist_ok=True)
        self.uploads_root.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, obj: Dict[str, Any]) -> None:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def _meta_path(self, report_id: str) -> Optional[Path]:
        builtin = self.builtin_root / report_id / "meta.json"
        if builtin.exists():
            return builtin
        upload = self.uploads_root / report_id / "meta.json"
        if upload.exists():
            return upload
        return None

    def list_reports(self, report_type: str = "individual") -> List[Dict[str, Any]]:
        reports: List[Dict[str, Any]] = []

        for meta_path in self.builtin_root.glob("*/meta.json"):
            try:
                meta = self._read_json(meta_path)
            except Exception:
                continue
            if meta.get("report_type") != report_type:
                continue
            reports.append(meta)

        for meta_path in self.uploads_root.glob("*/meta.json"):
            try:
                meta = self._read_json(meta_path)
            except Exception:
                continue
            if meta.get("report_type") != report_type:
                continue
            reports.append(meta)

        reports.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True)
        return reports

    def get_report_meta(self, report_id: str) -> Dict[str, Any]:
        path = self._meta_path(report_id)
        if path is None:
            raise FileNotFoundError(f"report_id not found: {report_id}")
        return self._read_json(path)

    def get_enriched_json_path(self, report_id: str) -> Path:
        meta = self.get_report_meta(report_id)
        rel = meta.get("artifacts", {}).get("enriched_standard")
        if not rel:
            raise FileNotFoundError(f"enriched artifact missing for report_id={report_id}")
        if meta.get("source") == "builtin":
            root = self.builtin_root / report_id
        else:
            root = self.uploads_root / report_id
        path = (root / rel).resolve()
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {path}")
        return path

    def get_core_tables_path(self, report_id: str) -> Path:
        meta = self.get_report_meta(report_id)
        rel = meta.get("artifacts", {}).get("core_tables")
        if not rel:
            raise FileNotFoundError(f"core_tables artifact missing for report_id={report_id}")
        if meta.get("source") == "builtin":
            root = self.builtin_root / report_id
        else:
            root = self.uploads_root / report_id
        path = (root / rel).resolve()
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {path}")
        return path

    def get_raw_pdf_path(self, report_id: str) -> Path:
        meta = self.get_report_meta(report_id)
        if meta.get("source") == "builtin":
            root = self.builtin_root / report_id
        else:
            root = self.uploads_root / report_id
        raw_files = meta.get("raw_files") or {}
        rel = raw_files.get("pdf")
        candidates: List[Path] = []
        if rel:
            candidates.append((root / rel).resolve())
        candidates.extend(sorted((root / "raw").glob("*.pdf")))
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(f"raw pdf missing for report_id={report_id}")

    def get_raw_xml_path(self, report_id: str) -> Path:
        meta = self.get_report_meta(report_id)
        if meta.get("source") == "builtin":
            root = self.builtin_root / report_id
        else:
            root = self.uploads_root / report_id
        raw_files = meta.get("raw_files") or {}
        rel = raw_files.get("xml")
        candidates: List[Path] = []
        if rel:
            candidates.append((root / rel).resolve())
        candidates.extend(sorted((root / "raw").glob("*.xml")))
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(f"raw xml missing for report_id={report_id}")

    def create_upload_report(self, report_type: str, customer_name: str) -> Dict[str, Any]:
        report_id = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        report_dir = self.uploads_root / report_id
        (report_dir / "raw").mkdir(parents=True, exist_ok=True)
        (report_dir / "artifacts").mkdir(parents=True, exist_ok=True)

        meta = {
            "report_id": report_id,
            "customer_name": customer_name or report_id,
            "report_type": report_type,
            "status": "uploaded",
            "source": "upload",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "error": "",
            "artifacts": {
                "xml_standard": "artifacts/individual.standard.json",
                "pdf_standard": "artifacts/individual.pdf.standard.json",
                "enriched_standard": "artifacts/individual.standard.enriched_labels.json",
                "core_tables": "artifacts/individual.core_tables.json",
            },
        }
        self._write_json(report_dir / "meta.json", meta)
        return meta

    def update_meta(
        self,
        report_id: str,
        *,
        status: Optional[str] = None,
        error: Optional[str] = None,
        raw_files: Optional[Dict[str, str]] = None,
        artifacts: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        path = self._meta_path(report_id)
        if path is None:
            raise FileNotFoundError(f"report_id not found: {report_id}")
        meta = self._read_json(path)
        if status:
            meta["status"] = status
        if error is not None:
            meta["error"] = error
        if raw_files:
            meta["raw_files"] = raw_files
        if artifacts:
            meta["artifacts"] = artifacts
        meta["updated_at"] = now_iso()
        self._write_json(path, meta)
        return meta

    def upload_dir(self, report_id: str) -> Path:
        d = self.uploads_root / report_id
        if not d.exists():
            raise FileNotFoundError(f"upload report dir not found: {report_id}")
        return d
