#!/usr/bin/env python3
"""Extract usable code tables from official credit-report PDF specs."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader


DOC_FILES = [
    "人民银行征信系统产品说明_个人信用报告（二代试行）202007修订.pdf",
    "征信系统数据查询接口规格说明（信用报告）2019-09.pdf",
    "征信系统数据查询接口规格说明（本机构数据）.pdf",
    "征信系统数据查询接口规格说明（相关还款责任人及抵（质）押物信息）2019-09.pdf",
    "征信系统数据查询接口规格说明（通用要求）2019-09.pdf",
]

# Fixes for known PDF line-wrap merge artifacts in extracted code tables.
MANUAL_TABLE_CODE_FIXES: dict[str, dict[str, str]] = {
    "A.2": {
        "10": "身份证",
    },
    "A.7": {
        "0": "国家机关、党群组织、企业、事业单位负责人",
    },
    "A.20": {
        "81": "贷记卡",
    },
}

# Field coverage for current individual-report V1.
FIELD_TABLE_REFS: dict[str, list[str]] = {
    "PA01BD01": ["A.2", "8.1"],
    "PA01BD02": ["A.4"],
    "PA01CD01": ["A.2", "8.1"],
    "PB01AD01": ["A.60"],
    "PB01AD02": ["A.61"],
    "PB01AD03": ["A.62"],
    "PB01AD04": ["A.63"],
    "PB01AD05": ["A.57"],  # 标题存在，但可能是外部标准引用，常见为无细项行
    "PB020D01": ["A.64"],
    "PB020D02": ["A.2", "8.1"],
    "PB030D01": ["A.5"],
    "PB040D01": ["A.63"],
    "PB040D02": ["A.6"],
    "PB040D03": ["A.65"],
    "PB040D04": ["A.7"],
    "PB040D05": ["A.8"],
    "PB040D06": ["A.9"],
    "PC05AD01": ["A.18"],
    "PC05AQ01": ["A.4"],
    "PD01AD01": ["A.19"],
    "PD01AD02": ["A.18"],
    "PD01AD03": ["A.20"],
    "PD01AD05": ["A.21"],
    "PD01AD06": ["A.22"],
    "PD01AD07": ["A.24"],
    "PD01AD08": ["A.23"],
    "PD01AD10": ["A.26"],
    "PD01BD01": ["A.27", "A.28", "A.29", "A.30", "A.31"],
    "PD01BD03": ["A.32"],
    "PD01BD04": ["A.33", "A.34", "A.35", "A.36"],
    "PF03AD01": ["A.50", "A.51"],
    "PG010D03": ["A.39"],
    "PH010D01": ["A.18"],
    "PH010Q03": ["A.4"],
}

SECTION_RE = re.compile(
    r"^((?:[A-Z]\.[0-9]+)|(?:D\.[0-9]+)|(?:[0-9]+\.[0-9]+))\s+(.+?(?:代码表(?:（[^）]+）)?|代码))\s*$"
)
CODE_TOKEN_RE = re.compile(r"^[A-Z0-9#\*]{1,8}$")


@dataclass
class CodeRow:
    code: str
    label: str
    description: str = ""


@dataclass
class CodeTable:
    table_id: str
    title: str
    source_doc: str
    source_page: int
    rows: list[CodeRow] = field(default_factory=list)

    def add_row(self, row: CodeRow) -> None:
        self.rows.append(row)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "title": self.title,
            "source_doc": self.source_doc,
            "source_page": self.source_page,
            "row_count": len(self.rows),
            "rows": [
                {"code": r.code, "label": r.label, "description": r.description}
                for r in self.rows
            ],
        }


def norm_line(text: str) -> str:
    return " ".join(text.replace("\u3000", " ").strip().split())


def should_skip_line(line: str) -> bool:
    if not line:
        return True
    # Common headers/footers/page noise
    if line.startswith("Q/PBCCRC"):
        return True
    if line.startswith("2020-07 最新修订"):
        return True
    if line.startswith("附 录"):
        return True
    if line.startswith("表 "):
        return True
    if line.startswith("目次"):
        return True
    if line in {"代码 中文名称 说明", "代码 内容", "代码 中文名称", "代码 说明"}:
        return True
    return False


def try_parse_row(line: str) -> CodeRow | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    code = parts[0]
    if not CODE_TOKEN_RE.fullmatch(code):
        return None
    if code in {"XML", "Tag"}:
        return None
    label = parts[1]
    if label in {"中文名称", "内容", "说明", "代码"}:
        return None
    desc = " ".join(parts[2:]) if len(parts) > 2 else ""
    return CodeRow(code=code, label=label, description=desc)


def extract_tables_from_pdf(pdf_path: Path) -> list[CodeTable]:
    reader = PdfReader(str(pdf_path))
    tables: list[CodeTable] = []
    current: CodeTable | None = None

    for page_idx, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        for raw_line in raw_text.splitlines():
            line = norm_line(raw_line)
            if should_skip_line(line):
                continue
            sec = SECTION_RE.match(line)
            if sec:
                if current is not None:
                    tables.append(current)
                current = CodeTable(
                    table_id=sec.group(1),
                    title=sec.group(2),
                    source_doc=pdf_path.name,
                    source_page=page_idx,
                )
                continue
            if current is None:
                continue
            row = try_parse_row(line)
            if row is not None:
                current.add_row(row)

    if current is not None:
        tables.append(current)
    return tables


def dedupe_rows(rows: list[CodeRow]) -> list[CodeRow]:
    seen: set[tuple[str, str, str]] = set()
    out: list[CodeRow] = []
    for row in rows:
        key = (row.code, row.label, row.description)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def merge_tables(tables: list[CodeTable]) -> list[CodeTable]:
    merged: dict[tuple[str, str], CodeTable] = {}
    for tb in tables:
        k = (tb.table_id, tb.title)
        if k not in merged:
            merged[k] = CodeTable(
                table_id=tb.table_id,
                title=tb.title,
                source_doc=tb.source_doc,
                source_page=tb.source_page,
                rows=list(tb.rows),
            )
            continue
        merged[k].rows.extend(tb.rows)
    out = []
    for tb in merged.values():
        tb.rows = dedupe_rows(tb.rows)
        out.append(tb)
    out.sort(key=lambda x: (x.table_id, x.title))
    return out


def apply_manual_fixes(tables: list[CodeTable]) -> None:
    for tb in tables:
        fixes = MANUAL_TABLE_CODE_FIXES.get(tb.table_id)
        if not fixes:
            continue
        existing = {row.code for row in tb.rows}
        for code, label in fixes.items():
            if code in existing:
                continue
            tb.add_row(CodeRow(code=code, label=label, description="manual_fix_from_official_appendix"))


def build_index_by_id(tables: list[CodeTable]) -> dict[str, list[CodeTable]]:
    by_id: dict[str, list[CodeTable]] = {}
    for tb in tables:
        by_id.setdefault(tb.table_id, []).append(tb)
    return by_id


def build_field_mapping(
    tables: list[CodeTable],
    standard_json_path: Path | None = None,
) -> dict[str, Any]:
    by_id = build_index_by_id(tables)
    field_map: dict[str, Any] = {}
    observed_codes: dict[str, set[str]] = {}

    if standard_json_path and standard_json_path.exists():
        obj = json.loads(standard_json_path.read_text(encoding="utf-8"))

        def collect_field(field_code: str, field_obj: dict[str, Any]) -> None:
            if "code" not in field_obj:
                return
            c = str(field_obj.get("code") or "").strip()
            if c:
                observed_codes.setdefault(field_code, set()).add(c)

        for table in (obj.get("tables") or {}).values():
            for field_code, f in (table.get("fields") or {}).items():
                if isinstance(f, dict):
                    collect_field(field_code, f)
                    if isinstance(f.get("value"), list):
                        for item in f["value"]:
                            if isinstance(item, dict):
                                for n_code, n_obj in (item.get("fields") or {}).items():
                                    if isinstance(n_obj, dict):
                                        collect_field(n_code, n_obj)
            for rec in (table.get("records") or []):
                for field_code, f in (rec.get("fields") or {}).items():
                    if isinstance(f, dict):
                        collect_field(field_code, f)

    for field_code, refs in FIELD_TABLE_REFS.items():
        code_labels: dict[str, list[str]] = {}
        table_hits: list[dict[str, Any]] = []
        for ref in refs:
            for tb in by_id.get(ref, []):
                table_hits.append(
                    {
                        "table_id": tb.table_id,
                        "title": tb.title,
                        "source_doc": tb.source_doc,
                        "row_count": len(tb.rows),
                    }
                )
                for row in tb.rows:
                    code_labels.setdefault(row.code, [])
                    if row.label not in code_labels[row.code]:
                        code_labels[row.code].append(row.label)

        observed = sorted(observed_codes.get(field_code, set()))
        unresolved = [c for c in observed if c not in code_labels]
        field_map[field_code] = {
            "table_refs": refs,
            "matched_tables": table_hits,
            "code_labels": code_labels,
            "observed_codes_in_sample": observed,
            "unresolved_observed_codes": unresolved,
        }
    return field_map


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract official code tables from spec PDFs.")
    parser.add_argument(
        "--codebook-dir",
        type=Path,
        default=Path("data_recource/码表"),
        help="Directory that contains official codebook PDFs.",
    )
    parser.add_argument(
        "--standard-json",
        type=Path,
        default=Path("output/individual.standard.json"),
        help="Optional standard JSON for observed-code coverage.",
    )
    parser.add_argument(
        "--out-all",
        type=Path,
        default=Path("mapping/official_code_tables.extracted.json"),
        help="Output JSON path for all extracted code tables.",
    )
    parser.add_argument(
        "--out-field",
        type=Path,
        default=Path("mapping/official_code_tables.by_field.individual_v1.json"),
        help="Output JSON path for field-to-code-table mapping.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    codebook_dir: Path = args.codebook_dir
    if not codebook_dir.exists():
        raise FileNotFoundError(f"Codebook directory not found: {codebook_dir}")

    all_tables: list[CodeTable] = []
    doc_stats: list[dict[str, Any]] = []

    for name in DOC_FILES:
        pdf_path = codebook_dir / name
        if not pdf_path.exists():
            doc_stats.append(
                {
                    "doc": name,
                    "exists": False,
                    "tables_extracted": 0,
                    "rows_extracted": 0,
                }
            )
            continue
        tables = extract_tables_from_pdf(pdf_path)
        all_tables.extend(tables)
        doc_stats.append(
            {
                "doc": name,
                "exists": True,
                "tables_extracted": len(tables),
                "rows_extracted": sum(len(t.rows) for t in tables),
            }
        )

    merged = merge_tables(all_tables)
    apply_manual_fixes(merged)

    all_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source_dir": str(codebook_dir),
        "documents": doc_stats,
        "table_count": len(merged),
        "row_count": sum(len(t.rows) for t in merged),
        "tables": [t.to_dict() for t in merged],
    }

    field_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source_tables_file": str(args.out_all),
        "field_count": len(FIELD_TABLE_REFS),
        "fields": build_field_mapping(merged, args.standard_json),
    }

    args.out_all.parent.mkdir(parents=True, exist_ok=True)
    args.out_field.parent.mkdir(parents=True, exist_ok=True)
    args.out_all.write_text(json.dumps(all_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out_field.write_text(json.dumps(field_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[ok] all tables: {args.out_all}")
    print(f"[ok] field mapping: {args.out_field}")
    print(f"[summary] tables={all_payload['table_count']} rows={all_payload['row_count']}")
    for ds in doc_stats:
        print(
            f"  - {ds['doc']}: exists={ds['exists']} tables={ds['tables_extracted']} rows={ds['rows_extracted']}"
        )


if __name__ == "__main__":
    main()
