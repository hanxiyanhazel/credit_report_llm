from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(default="")


class ChatRequest(BaseModel):
    session_id: str = Field(default="")
    report_id: str = Field(default="")
    report_type: Literal["individual", "corporate"] = "individual"
    messages: List[ChatMessage] = Field(default_factory=list)
    debug: bool = False


class ChatResponse(BaseModel):
    answer: str
    answer_mode: Literal["report_grounded", "general_llm", "hybrid", "structured_query", "deterministic_handler", "sql_query", "direct_extract"] = (
        "report_grounded"
    )
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence_paths: List[str] = Field(default_factory=list)
    verifier_status: Literal["answerable", "partially_answerable", "not_answerable"] = "answerable"
    cannot_answer_reason: str = Field(default="")
    question_type: str = Field(default="")
    report_id: str = Field(default="")
    session_id: str = Field(default="")
    query_plan: Optional[Dict[str, Any]] = None
    query_result: Optional[Dict[str, Any]] = None
    prompt_trace: Optional[Dict[str, Any]] = None
    debug: Optional[Dict[str, Any]] = None


class ReportInfo(BaseModel):
    report_id: str
    customer_name: str
    report_type: Literal["individual", "corporate"] = "individual"
    status: Literal["uploaded", "parsing", "ready", "failed"] = "uploaded"
    source: Literal["builtin", "upload"] = "upload"
    created_at: str = Field(default="")
    updated_at: str = Field(default="")
    error: str = Field(default="")


class ReportsListResponse(BaseModel):
    report_type: Literal["individual", "corporate"] = "individual"
    reports: List[ReportInfo] = Field(default_factory=list)


class UploadResponse(BaseModel):
    report_id: str
    status: Literal["uploaded", "parsing", "ready", "failed"]
    report_type: Literal["individual", "corporate"] = "individual"
    customer_name: str
    error: str = Field(default="")


class ErrorResponse(BaseModel):
    error: str
