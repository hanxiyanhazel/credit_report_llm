from __future__ import annotations

import json
from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_loop import run_agent_turn
from config import SETTINGS
from models import ChatRequest, ChatResponse, ReportsListResponse, UploadResponse
from parse_pipeline import PipelineError, run_individual_pipeline
from qwen_client import QwenClient
from report_store import ReportStore

APP_DIR = SETTINGS.app_dir

app = FastAPI(title="Credit Demo 2 - SQL Query", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/web", StaticFiles(directory=str(APP_DIR / "web")), name="web")


@app.middleware("http")
async def disable_cache_middleware(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

store = ReportStore(SETTINGS.data_root)
qwen_client = QwenClient(SETTINGS)

try:
    import multipart  # type: ignore # noqa: F401

    HAS_MULTIPART = True
except Exception:
    HAS_MULTIPART = False


@app.on_event("startup")
async def on_startup() -> None:
    store.ensure_dirs()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(APP_DIR / "web" / "index.html"))


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "qwen_configured": qwen_client.configured,
        "data_root": str(SETTINGS.data_root),
    }


@app.get("/api/reports/list", response_model=ReportsListResponse)
async def list_reports(report_type: str = "individual") -> ReportsListResponse:
    reports = store.list_reports(report_type=report_type)
    return ReportsListResponse(report_type=report_type, reports=reports)


@app.get("/api/reports/{report_id}/status")
async def report_status(report_id: str) -> Dict[str, Any]:
    try:
        meta = store.get_report_meta(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta


if HAS_MULTIPART:

    @app.post("/api/reports/upload", response_model=UploadResponse)
    async def upload_report(
        report_type: str = Form("individual"),
        customer_name: str = Form(""),
        xml_file: UploadFile = File(...),
        pdf_file: UploadFile = File(...),
    ) -> UploadResponse:
        if report_type != "individual":
            raise HTTPException(status_code=400, detail="当前版本仅支持个人报告（individual）")

        if not xml_file.filename.lower().endswith(".xml"):
            raise HTTPException(status_code=400, detail="xml_file 必须是 .xml")
        if not pdf_file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="pdf_file 必须是 .pdf")

        meta = store.create_upload_report(report_type=report_type, customer_name=customer_name or "")
        report_id = str(meta["report_id"])
        report_dir = store.upload_dir(report_id)
        raw_dir = report_dir / "raw"
        artifacts_dir = report_dir / "artifacts"

        xml_target = raw_dir / "uploaded.xml"
        pdf_target = raw_dir / "uploaded.pdf"

        xml_target.write_bytes(await xml_file.read())
        pdf_target.write_bytes(await pdf_file.read())
        store.update_meta(
            report_id,
            status="parsing",
            error="",
            raw_files={"xml": f"raw/{xml_target.name}", "pdf": f"raw/{pdf_target.name}"},
        )

        try:
            artifacts = run_individual_pipeline(
                workspace_dir=APP_DIR,
                scripts_dir=APP_DIR / "scripts",
                xml_path=xml_target,
                pdf_path=pdf_target,
                artifacts_dir=artifacts_dir,
                report_id=report_id,
            )
            meta = store.update_meta(report_id, status="ready", error="", artifacts=artifacts)
        except PipelineError as exc:
            meta = store.update_meta(report_id, status="failed", error=str(exc))
            return UploadResponse(
                report_id=report_id,
                status="failed",
                report_type=report_type,
                customer_name=str(meta.get("customer_name") or report_id),
                error=str(exc),
            )

        return UploadResponse(
            report_id=report_id,
            status=str(meta.get("status") or "ready"),  # type: ignore[arg-type]
            report_type=report_type,
            customer_name=str(meta.get("customer_name") or report_id),
            error=str(meta.get("error") or ""),
        )

else:

    @app.post("/api/reports/upload", response_model=UploadResponse)
    async def upload_report_disabled() -> UploadResponse:
        raise HTTPException(
            status_code=503,
            detail="当前环境缺少 python-multipart，暂不可用上传接口。请先安装依赖后重启。",
        )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    report_id = (request.report_id or "").strip()
    if not report_id:
        builtin = store.list_reports(report_type=request.report_type)
        if not builtin:
            raise HTTPException(status_code=400, detail="未找到可用报告，请先上传文件")
        report_id = str(builtin[0]["report_id"])

    try:
        meta = store.get_report_meta(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if meta.get("status") != "ready":
        raise HTTPException(status_code=400, detail=f"报告尚未就绪，当前状态: {meta.get('status')}")

    enriched_path = store.get_enriched_json_path(report_id)
    report_json = json.loads(enriched_path.read_text(encoding="utf-8"))
    raw_pdf_path = None
    try:
        raw_pdf_path = str(store.get_raw_pdf_path(report_id))
    except Exception:
        raw_pdf_path = None
    raw_xml_path = None
    try:
        raw_xml_path = str(store.get_raw_xml_path(report_id))
    except Exception:
        raw_xml_path = None
    core_tables_json = None
    try:
        core_tables_path = store.get_core_tables_path(report_id)
        core_tables_json = json.loads(core_tables_path.read_text(encoding="utf-8"))
    except Exception:
        core_tables_json = None

    messages = [m.model_dump() for m in request.messages]
    if not request.session_id.strip():
        session_id = str(uuid4())
    else:
        session_id = request.session_id.strip()

    result = await run_agent_turn(
        messages=messages,
        report_json=report_json,
        core_tables_json=core_tables_json,
        raw_pdf_path=raw_pdf_path,
        raw_xml_path=raw_xml_path,
        report_id=report_id,
        session_id=session_id,
        qwen_client=qwen_client,
        debug=request.debug,
    )

    return ChatResponse(
        answer=str(result.get("answer") or ""),
        answer_mode=str(result.get("answer_mode") or "report_grounded"),  # type: ignore[arg-type]
        confidence=str(result.get("confidence") or "medium"),  # type: ignore[arg-type]
        evidence_paths=list(result.get("evidence_paths") or []),
        verifier_status=str(result.get("verifier_status") or "answerable"),  # type: ignore[arg-type]
        cannot_answer_reason=str(result.get("cannot_answer_reason") or ""),
        question_type=str(result.get("question_type") or ""),
        report_id=report_id,
        session_id=session_id,
        query_plan=result.get("query_plan"),
        query_result=result.get("query_result"),
        prompt_trace=result.get("prompt_trace"),
        debug=result.get("debug") if request.debug else None,
    )
