from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader


MODULE_LABELS = {
    "report_header": "报告首页摘要",
    "identity_info": "身份信息",
    "residence_info": "居住信息",
    "occupation_info": "职业信息",
    "overview_summary": "信息概要",
    "query_summary": "查询记录概要",
}


def _slice_between(text: str, start_patterns: List[str], end_patterns: List[str]) -> str:
    start_idx = -1
    for pat in start_patterns:
        m = re.search(pat, text, flags=re.MULTILINE)
        if m:
            start_idx = m.start()
            break
    if start_idx < 0:
        return ""
    end_idx = len(text)
    for pat in end_patterns:
        m = re.search(pat, text[start_idx + 1 :], flags=re.MULTILINE)
        if m:
            end_idx = start_idx + 1 + m.start()
            break
    return text[start_idx:end_idx].strip()


@lru_cache(maxsize=16)
def load_pdf_modules(pdf_path: str, max_pages: int = 4) -> Dict[str, str]:
    reader = PdfReader(pdf_path)
    page_texts: List[str] = []
    for i in range(min(max_pages, len(reader.pages))):
        txt = reader.pages[i].extract_text() or ""
        page_texts.append(txt)
    full_text = "\n".join(page_texts)

    modules: Dict[str, str] = {}
    modules["report_header"] = _slice_between(
        full_text,
        [r"个人信用报告", r"报告编号："],
        [r"\n一\s+个人基本信息", r"\n一 个人基本信息"],
    )
    modules["identity_info"] = _slice_between(
        full_text,
        [r"[\(（]一[\)）]\s*身份信息"],
        [r"[\(（]二[\)）]\s*配偶信息", r"[\(（]三[\)）]\s*居住信息"],
    )
    modules["residence_info"] = _slice_between(
        full_text,
        [r"[\(（]三[\)）]\s*居住信息"],
        [r"[\(（]四[\)）]\s*职业信息"],
    )
    modules["occupation_info"] = _slice_between(
        full_text,
        [r"[\(（]四[\)）]\s*职业信息"],
        [r"\n二\s+信息概要", r"\n二 信息概要"],
    )
    modules["overview_summary"] = _slice_between(
        full_text,
        [r"\n二\s+信息概要", r"\n二 信息概要"],
        [r"\n三\s+信贷交易信息明细", r"\n三 信贷交易信息明细"],
    )
    modules["query_summary"] = _slice_between(
        full_text,
        [r"[\(（]七[\)）]\s*查询记录概要"],
        [r"\n三\s+信贷交易信息明细", r"\n三 信贷交易信息明细"],
    )

    modules["basic_info_bundle"] = "\n\n".join(
        filter(
            None,
            [
                modules.get("report_header", ""),
                modules.get("identity_info", ""),
                modules.get("residence_info", ""),
                modules.get("occupation_info", ""),
            ],
        )
    ).strip()
    return modules


def build_extraction_snippets(modules: Dict[str, str], target_modules: List[str]) -> List[Dict[str, str]]:
    snippets: List[Dict[str, str]] = []
    for module in target_modules:
        text = str(modules.get(module) or "").strip()
        if not text:
            continue
        snippets.append(
            {
                "module": module,
                "module_name_cn": MODULE_LABELS.get(module, module),
                "text": text,
            }
        )
    return snippets

