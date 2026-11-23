"""缺页复采接口：缺页图、整组预览确认、回执核验、任务领用与看板。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import recrawl

router = APIRouter(prefix="/api/recrawl", tags=["缺页复采"])


class PreviewPayload(BaseModel):
    job_id: str
    urls: list[str] = Field(default_factory=list)
    operator: str = ""


class Decision(BaseModel):
    url: str
    decision: str = "include"
    reason: str = ""


class ConfirmPayload(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)
    operator: str = ""


class VerifyPayload(BaseModel):
    verdict: str
    note: str = ""
    operator: str = ""


class ClaimPayload(BaseModel):
    task_id: str
    job_id: str | None = None
    limit: int | None = None


@router.get("/missing-board")
def missing_board(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    return recrawl.missing_board(job_id)


@router.post("/previews")
def create_preview(payload: PreviewPayload) -> dict[str, Any]:
    preview, error = recrawl.create_preview(payload.job_id, payload.urls, payload.operator)
    if error:
        return {"ok": False, "message": error, "preview": None}
    return {"ok": True, "message": "缺页预览已生成", "preview": preview}


@router.get("/previews/{preview_id}")
def get_preview(preview_id: str) -> dict[str, Any]:
    preview = recrawl.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail=f"缺页预览 {preview_id} 不存在")
    return preview


@router.post("/previews/{preview_id}/confirm")
def confirm_preview(preview_id: str, payload: ConfirmPayload) -> dict[str, Any]:
    preview, error = recrawl.confirm_preview(
        preview_id, [d.model_dump() for d in payload.decisions], payload.operator)
    if error and preview is None:
        return {"ok": False, "message": error, "preview": None}
    return {"ok": True, "message": error or "整组确认已提交", "preview": preview}


@router.post("/receipts/{receipt_id}/verify")
def verify_receipt(receipt_id: str, payload: VerifyPayload) -> dict[str, Any]:
    receipt, error = recrawl.verify_receipt(
        receipt_id, payload.verdict, payload.note, payload.operator)
    if receipt is None:
        return {"ok": False, "message": error, "receipt": None}
    return {"ok": True, "message": "回执核验完成", "receipt": receipt}


@router.get("/board")
def recrawl_board(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    return recrawl.recrawl_board(job_id)


@router.post("/claims")
def claim_next(payload: ClaimPayload) -> dict[str, Any]:
    result, error = recrawl.claim_next(payload.task_id, payload.job_id, payload.limit)
    if result is None:
        return {"ok": False, "message": error, "result": None}
    return {"ok": True, "message": result["message"], "result": result}


@router.get("/events")
def list_events(
    job_id: str | None = Query(default=None),
    source_url: str | None = Query(default=None),
) -> dict[str, Any]:
    items = recrawl.list_events(job_id, source_url)
    return {"items": items, "total": len(items)}
