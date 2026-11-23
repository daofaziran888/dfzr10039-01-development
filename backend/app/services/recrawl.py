"""缺页复采领域逻辑：解析日志缺页图、整组确认、复采清单与任务领取。

业务约束：
- 缺页图按采集作业汇总解析日志，失败原因和原始日志只读留存，不覆盖。
- 一次预览只对一组地址做整组确认；确认前复核中的地址不能执行复采。
- 同一作业同一地址只允许一条复采资格（并发确认也只产生一次）。
- 迟到成功回执一经核实，该地址必须排除复采。
- 每次纳入、延期、排除、领走都追加复采事件，原因可回查。
- 复采确认结果同步到采集任务清单，任务只能领真正有资格的入口。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from app.models import (
    MissingPreview, MissingPreviewItem, ParseReceipt, RecrawlClaim,
    RecrawlEntry, RecrawlEvent,
)
from app.store import store

# 复采资格状态
STATUS_WAITING = "等候确认"
STATUS_QUALIFIED = "有资格"
STATUS_CLAIMED = "已领走"
STATUS_VERIFYING = "核验中"
STATUS_EXCLUDED = "已排除"
STATUS_DEFERRED = "已延期"

# 预览条目状态（缺页看板直接展示这三类）
ITEM_WAITING = "等候整组确认"
ITEM_RETURNED = "单独退回核验"
ITEM_CONFIRMED = "已确认"
ITEM_CLAIMED = "已领走"
ITEM_EXCLUDED = "已排除"
ITEM_DEFERRED = "已延期"

# 缺页图 / 看板状态
STATE_PENDING = "待复采"
STATE_WAITING = "等候整组确认"
STATE_RETURNED = "单独退回核验"
STATE_CLAIMED = "已领走"
STATE_EXCLUDED = "已排除"
STATE_DEFERRED = "已延期"
STATE_UNVERIFIED = "待核验"

REASON_SUCCESS_VERIFIED = "迟到成功回执已核实，排除复采"
REASON_PENDING_RECEIPT = "成功回执待核验，暂不能执行复采"

_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(table: str) -> int:
    rows = store.rows(table)
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _seq(table: str, prefix: str, width: int = 3) -> str:
    return f"{prefix}-{len(store.rows(table)) + 1:0{width}d}"


def _job_row(job_id: str) -> dict[str, Any] | None:
    for row in store.rows("crawl_job"):
        if str(row.get("作业编号")) == job_id:
            return row
    return None


def _job_label(job_id: str) -> str:
    row = _job_row(job_id)
    if row is None:
        return job_id
    return f"{job_id} · {row.get('目标站点', '')}"


def _receipt_rows(job_id: str, url: str) -> list[dict[str, Any]]:
    return [
        row for row in store.rows("parse_receipt")
        if str(row.get("job_id")) == job_id and str(row.get("source_url")) == url
    ]


def _pending_receipt(job_id: str, url: str) -> dict[str, Any] | None:
    for row in _receipt_rows(job_id, url):
        if str(row.get("verification", "待核验")) == "待核验":
            return row
    return None


def _verified_success_receipt(job_id: str, url: str) -> dict[str, Any] | None:
    for row in _receipt_rows(job_id, url):
        if (str(row.get("verification")) == "已核实"
                and str(row.get("result")) == "成功"):
            return row
    return None


def _failure_reason(row: dict[str, Any]) -> str:
    reason = str(row.get("失败原因") or "").strip()
    if reason:
        return reason
    reason = str(row.get("异常类型") or "").strip()
    return reason or str(row.get("status") or "未知异常")


def _is_failure_log(row: dict[str, Any]) -> bool:
    """失败日志：有异常类型、状态非成功，或标记为异常。"""
    if str(row.get("异常类型") or "").strip():
        return True
    if bool(row.get("abnormal")):
        return True
    return str(row.get("status") or "") in ("格式异常", "内容缺失", "重试中")


def _append_event(
    *,
    job_id: str,
    source_url: str,
    action: str,
    reason: str = "",
    detail: str = "",
    operator: str = "",
    preview_id: str = "",
    receipt_id: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    event = RecrawlEvent(
        event_id=_seq("recrawl_event", "REVT"),
        job_id=job_id,
        source_url=source_url,
        action=action,
        reason=reason,
        detail=detail,
        operator=operator,
        preview_id=preview_id,
        receipt_id=receipt_id,
        task_id=task_id,
        created_at=_now(),
    )
    row = {
        "id": _next_id("recrawl_event"),
        "event_id": event.event_id,
        "job_id": event.job_id,
        "source_url": event.source_url,
        "action": event.action,
        "reason": event.reason,
        "detail": event.detail,
        "operator": event.operator,
        "preview_id": event.preview_id,
        "receipt_id": event.receipt_id,
        "task_id": event.task_id,
        "created_at": event.created_at,
        "status": event.action,
        "pending": False,
        "abnormal": event.action in ("排除", "延期"),
    }
    store.rows("recrawl_event").append(row)
    return row


def _parse_log_rows(job_id: str, url: str) -> list[dict[str, Any]]:
    return [
        row for row in store.rows("parse_log")
        if str(row.get("所属作业")) == job_id and str(row.get("来源URL")) == url
    ]


def _failure_logs(job_id: str, url: str) -> list[dict[str, Any]]:
    return [row for row in _parse_log_rows(job_id, url) if _is_failure_log(row)]


# ---------------------------------------------------------------------------
# 缺页图：按作业汇总解析日志缺页
# ---------------------------------------------------------------------------

def missing_board(job_id: str | None = None) -> dict[str, Any]:
    """缺页图：按采集作业汇总缺页地址、失败原因和原始解析日志。"""
    jobs: list[dict[str, Any]] = []
    seen_jobs: list[str] = []
    for row in store.rows("parse_log"):
        job = str(row.get("所属作业") or "")
        if not job:
            continue
        if job not in seen_jobs:
            seen_jobs.append(job)

    for job in seen_jobs:
        if job_id and job != job_id:
            continue
        urls: list[str] = []
        for row in store.rows("parse_log"):
            if str(row.get("所属作业")) != job:
                continue
            url = str(row.get("来源URL") or "")
            if url and url not in urls:
                urls.append(url)

        items: list[dict[str, Any]] = []
        reason_counts: dict[str, int] = {}
        for url in urls:
            logs = _failure_logs(job, url)
            if not logs:
                continue
            reasons: list[str] = []
            for log in logs:
                reason = _failure_reason(log)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if reason not in reasons:
                    reasons.append(reason)
            entry = _find_entry(job, url)
            receipt = _pending_receipt(job, url)
            verified = _verified_success_receipt(job, url)
            state = _item_state(entry, receipt, verified)
            items.append({
                "job_id": job,
                "source_url": url,
                "failure_reasons": reasons,
                "failure_count": len(logs),
                "log_ids": [str(log.get("记录编号")) for log in logs],
                "latest_log_time": str(logs[-1].get("记录时间") or ""),
                "logs": [_serialize_log(log) for log in logs],
                "receipt": _serialize_receipt(receipt or verified) if (receipt or verified) else None,
                "recrawl_status": out_status(entry, receipt, verified),
                "state": state,
                "reason": entry.get("reason") if entry else "",
            })

        items.sort(key=lambda item: (item["failure_reasons"][0], item["source_url"]))
        reasons = [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        jobs.append({
            "job_id": job,
            "job_label": _job_label(job),
            "missing_count": len(items),
            "reasons": reasons,
            "items": items,
            "pending_recrawl": sum(1 for item in items if item["state"] == STATE_PENDING),
            "awaiting_verify": sum(1 for item in items if item["state"] == STATE_UNVERIFIED),
        })

    return {"jobs": jobs, "total": sum(job["missing_count"] for job in jobs)}


def _serialize_log(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": str(row.get("记录编号") or ""),
        "source_url": str(row.get("来源URL") or ""),
        "parse_rule": str(row.get("解析规则") or ""),
        "parse_result": str(row.get("解析结果") or ""),
        "error_type": str(row.get("异常类型") or ""),
        "failure_reason": _failure_reason(row),
        "retry_count": row.get("重试次数", 0),
        "error_detail": str(row.get("错误详情") or ""),
        "recorded_at": str(row.get("记录时间") or ""),
        "evidence": str(row.get("证据留存") or "原始解析日志"),
    }


def _serialize_receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_id": str(row.get("receipt_id") or ""),
        "job_id": str(row.get("job_id") or ""),
        "source_url": str(row.get("source_url") or ""),
        "source_node": str(row.get("source_node") or ""),
        "result": str(row.get("result") or ""),
        "arrived_at": str(row.get("arrived_at") or ""),
        "failure_log_id": str(row.get("failure_log_id") or ""),
        "verification": str(row.get("verification") or "待核验"),
        "verification_note": str(row.get("verification_note") or ""),
        "verified_by": str(row.get("verified_by") or ""),
        "verified_at": str(row.get("verified_at") or ""),
    }


def _item_state(
    entry: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    verified: dict[str, Any] | None,
) -> str:
    """把复采资格状态映射成缺页图上的业务状态。"""
    if entry is not None:
        status = str(entry.get("status"))
        if status == STATUS_EXCLUDED:
            return STATE_EXCLUDED
        if status == STATUS_DEFERRED:
            return STATE_DEFERRED
        if status == STATUS_CLAIMED:
            return STATE_CLAIMED
        if status == STATUS_VERIFYING:
            return STATE_RETURNED
        if status == STATUS_QUALIFIED:
            return STATE_PENDING
        if status == STATUS_WAITING:
            return STATE_WAITING
    if receipt is not None:
        return STATE_UNVERIFIED
    if verified is not None:
        return STATE_EXCLUDED
    return STATE_PENDING


def out_status(
    entry: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    verified: dict[str, Any] | None,
) -> str:
    if entry is not None:
        return str(entry.get("status"))
    if receipt is not None:
        return "回执待核验"
    if verified is not None:
        return STATUS_EXCLUDED
    return "未纳入"


# ---------------------------------------------------------------------------
# 复采资格：同一作业同一地址只产生一次
# ---------------------------------------------------------------------------

def _find_entry(job_id: str, url: str) -> dict[str, Any] | None:
    for row in store.rows("recrawl_entry"):
        if str(row.get("job_id")) == job_id and str(row.get("source_url")) == url:
            return row
    return None


def _ensure_entry(job_id: str, url: str, log_ids: list[str],
                  failure_reason: str) -> tuple[dict[str, Any], bool]:
    """并发安全地取回复采资格：已存在则复用，绝不重复创建。"""
    existing = _find_entry(job_id, url)
    if existing is not None:
        # 补齐证据链，但不重置状态
        if log_ids and not existing.get("log_ids"):
            existing["log_ids"] = list(log_ids)
        return existing, False

    entry = RecrawlEntry(
        recrawl_id=_seq("recrawl_entry", "RCRAWL"),
        job_id=job_id,
        source_url=url,
        status=STATUS_WAITING,
        reason="等待整组确认",
        failure_reason=failure_reason,
        log_ids=list(log_ids),
        created_at=_now(),
        updated_at=_now(),
    )
    row = {
        "id": _next_id("recrawl_entry"),
        "recrawl_id": entry.recrawl_id,
        "job_id": entry.job_id,
        "source_url": entry.source_url,
        "status": entry.status,
        "reason": entry.reason,
        "failure_reason": entry.failure_reason,
        "log_ids": entry.log_ids,
        "receipt_id": "",
        "preview_id": "",
        "claim_count": 0,
        "claimed_by": "",
        "claimed_at": "",
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "pending": True,
        "abnormal": False,
    }
    store.rows("recrawl_entry").append(row)
    return row, True


# ---------------------------------------------------------------------------
# 预览：选一组地址生成缺页复采清单
# ---------------------------------------------------------------------------

def create_preview(job_id: str, urls: list[str], operator: str = "") -> tuple[dict[str, Any] | None, str]:
    if _job_row(job_id) is None:
        return None, f"采集作业 {job_id} 不存在"
    if not urls:
        return None, "请至少选择一个缺页地址"

    with _LOCK:
        normalized: list[str] = []
        for url in urls:
            url = str(url).strip()
            if url and url not in normalized:
                normalized.append(url)

        invalid: list[str] = []
        for url in normalized:
            if not _failure_logs(job_id, url):
                invalid.append(url)
        if invalid:
            return None, f"地址没有有效失败记录，不能进入缺页复采：{'、'.join(invalid)}"

        preview = MissingPreview(
            preview_id=_seq("missing_preview", "MPREV"),
            job_id=job_id,
            status="待确认",
            operator=operator,
            created_at=_now(),
            urls=list(normalized),
        )
        preview_row = {
            "id": _next_id("missing_preview"),
            "preview_id": preview.preview_id,
            "job_id": preview.job_id,
            "status": preview.status,
            "operator": preview.operator,
            "created_at": preview.created_at,
            "confirmed_at": "",
            "urls": preview.urls,
            "item_count": len(normalized),
            "pending": True,
            "abnormal": False,
        }
        store.rows("missing_preview").append(preview_row)

        item_rows: list[dict[str, Any]] = []
        for url in normalized:
            logs = _failure_logs(job_id, url)
            log_ids = [str(log.get("记录编号")) for log in logs]
            reason = _failure_reason(logs[0])
            entry, created = _ensure_entry(job_id, url, log_ids, reason)
            receipt = _pending_receipt(job_id, url)
            verified = _verified_success_receipt(job_id, url)

            if verified is not None:
                state, item_reason = ITEM_EXCLUDED, REASON_SUCCESS_VERIFIED
                if _can_transition(entry, STATUS_EXCLUDED):
                    entry["status"] = STATUS_EXCLUDED
                    entry["reason"] = REASON_SUCCESS_VERIFIED
                    entry["receipt_id"] = verified.get("receipt_id", "")
                else:
                    item_reason = str(entry.get("reason") or item_reason)
            elif receipt is not None:
                state, item_reason = ITEM_RETURNED, REASON_PENDING_RECEIPT
                if _can_transition(entry, STATUS_VERIFYING):
                    entry["status"] = STATUS_VERIFYING
                    entry["reason"] = REASON_PENDING_RECEIPT
                    entry["receipt_id"] = receipt.get("receipt_id", "")
                else:
                    state = _state_for_entry(entry)
                    item_reason = str(entry.get("reason") or item_reason)
                _append_event(
                    job_id=job_id, source_url=url, action="退回核验",
                    reason=REASON_PENDING_RECEIPT, operator=operator,
                    preview_id=preview.preview_id,
                    receipt_id=str(receipt.get("receipt_id") or ""),
                )
            elif str(entry.get("status")) in (STATUS_EXCLUDED, STATUS_DEFERRED):
                state = ITEM_EXCLUDED if entry["status"] == STATUS_EXCLUDED else ITEM_DEFERRED
                item_reason = str(entry.get("reason") or "")
            elif str(entry.get("status")) == STATUS_CLAIMED:
                # 已被任务领走的地址不因新预览回到可领取状态
                state, item_reason = ITEM_CLAIMED, str(entry.get("reason") or "任务已领取")
            else:
                state = ITEM_WAITING
                item_reason = "等候整组确认"
                entry["status"] = STATUS_WAITING
                entry["reason"] = item_reason

            entry["preview_id"] = preview.preview_id
            entry["updated_at"] = _now()
            entry["pending"] = entry["status"] in (STATUS_WAITING, STATUS_VERIFYING)
            entry["abnormal"] = entry["status"] in (STATUS_EXCLUDED, STATUS_DEFERRED)

            item_row = {
                "id": _next_id("missing_preview_item"),
                "preview_id": preview.preview_id,
                "job_id": job_id,
                "source_url": url,
                "failure_reason": reason,
                "log_ids": log_ids,
                "state": state,
                "reason": item_reason,
                "recrawl_id": entry.get("recrawl_id", ""),
                "updated_at": _now(),
                "status": state,
                "pending": state in (ITEM_WAITING, ITEM_RETURNED),
                "abnormal": state in (ITEM_EXCLUDED, ITEM_DEFERRED),
            }
            store.rows("missing_preview_item").append(item_row)
            item_rows.append(item_row)

            _append_event(
                job_id=job_id, source_url=url, action="生成预览",
                reason=item_reason, detail="; ".join(log_ids),
                operator=operator, preview_id=preview.preview_id,
            )

        preview_row["pending"] = True
        return _serialize_preview(preview_row, item_rows), ""


def _serialize_preview(preview_row: dict[str, Any],
                       item_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    preview_id = str(preview_row.get("preview_id"))
    if item_rows is None:
        item_rows = [
            row for row in store.rows("missing_preview_item")
            if str(row.get("preview_id")) == preview_id
        ]
    return {
        "preview_id": preview_id,
        "job_id": str(preview_row.get("job_id")),
        "job_label": _job_label(str(preview_row.get("job_id"))),
        "status": str(preview_row.get("status")),
        "operator": str(preview_row.get("operator") or ""),
        "created_at": str(preview_row.get("created_at") or ""),
        "confirmed_at": str(preview_row.get("confirmed_at") or ""),
        "items": [
            {
                "source_url": str(item.get("source_url")),
                "failure_reason": str(item.get("failure_reason") or ""),
                "log_ids": list(item.get("log_ids") or []),
                "state": str(item.get("state") or ""),
                "reason": str(item.get("reason") or ""),
                "recrawl_id": str(item.get("recrawl_id") or ""),
            }
            for item in item_rows
        ],
    }


def get_preview(preview_id: str) -> dict[str, Any] | None:
    for row in store.rows("missing_preview"):
        if str(row.get("preview_id")) == preview_id:
            return _serialize_preview(row)
    return None


# ---------------------------------------------------------------------------
# 回执核验：迟到成功回执必须核验来源
# ---------------------------------------------------------------------------

def verify_receipt(receipt_id: str, verdict: str,
                   note: str = "", operator: str = "") -> tuple[dict[str, Any] | None, str]:
    """核验迟到回执。verdict=success 表示回执来源核实为真，该地址排除复采。"""
    if verdict not in ("success", "reject"):
        return None, "核验结论只能是 success 或 reject"

    with _LOCK:
        receipt = None
        for row in store.rows("parse_receipt"):
            if str(row.get("receipt_id")) == receipt_id:
                receipt = row
                break
        if receipt is None:
            return None, f"回执 {receipt_id} 不存在"

        receipt["verification"] = "已核实" if verdict == "success" else "已驳回"
        receipt["verification_note"] = note
        receipt["verified_by"] = operator
        receipt["verified_at"] = _now()
        receipt["pending"] = False
        job_id = str(receipt.get("job_id"))
        url = str(receipt.get("source_url"))

        entry = _find_entry(job_id, url)
        if verdict == "success":
            if entry is not None:
                entry["status"] = STATUS_EXCLUDED
                entry["reason"] = REASON_SUCCESS_VERIFIED
                entry["receipt_id"] = receipt_id
                entry["updated_at"] = _now()
                entry["pending"] = False
                entry["abnormal"] = True
            _set_preview_items(
                job_id, url, ITEM_EXCLUDED, REASON_SUCCESS_VERIFIED,
                exclude_claimed=True,
            )
            _append_event(
                job_id=job_id, source_url=url, action="核验成功",
                reason=REASON_SUCCESS_VERIFIED, detail=note,
                operator=operator, receipt_id=receipt_id,
            )
            _sync_job_list(job_id)
        else:
            if entry is not None and str(entry.get("status")) == STATUS_VERIFYING:
                entry["status"] = STATUS_WAITING
                entry["reason"] = "回执已驳回，等待整组确认"
                entry["updated_at"] = _now()
                entry["pending"] = True
            _set_preview_items(
                job_id, url, ITEM_WAITING, "回执已驳回，等待整组确认",
            )
            _append_event(
                job_id=job_id, source_url=url, action="核验驳回",
                reason=note or "迟到回执来源无法确认",
                operator=operator, receipt_id=receipt_id,
            )
        return _serialize_receipt(receipt), ""


def _set_preview_items(job_id: str, url: str, state: str, reason: str,
                       *, exclude_claimed: bool = False) -> None:
    for item in store.rows("missing_preview_item"):
        if str(item.get("job_id")) != job_id or str(item.get("source_url")) != url:
            continue
        if str(item.get("state")) == ITEM_CLAIMED and not exclude_claimed:
            continue
        item["state"] = state
        item["reason"] = reason
        item["status"] = state
        item["updated_at"] = _now()
        item["pending"] = state in (ITEM_WAITING, ITEM_RETURNED)
        item["abnormal"] = state in (ITEM_EXCLUDED, ITEM_DEFERRED)


# ---------------------------------------------------------------------------
# 整组确认：一次确认只落一份资格，并发也幂等
# ---------------------------------------------------------------------------

def confirm_preview(preview_id: str, decisions: list[dict[str, str]],
                    operator: str = "") -> tuple[dict[str, Any] | None, str]:
    """提交整组选项。decision 取值：include / exclude / defer。

    复核中的地址即使选择纳入也只能退回核验；成功回执已核实的地址一律排除。
    """
    with _LOCK:
        preview = None
        for row in store.rows("missing_preview"):
            if str(row.get("preview_id")) == preview_id:
                preview = row
                break
        if preview is None:
            return None, f"缺页预览 {preview_id} 不存在"

        items = [
            row for row in store.rows("missing_preview_item")
            if str(row.get("preview_id")) == preview_id
        ]
        if str(preview.get("status")) == "已确认":
            return _serialize_preview(preview, items), "该组已确认，未重复生成复采资格"

        job_id = str(preview.get("job_id"))
        by_url = {str(item.get("source_url")): item for item in items}

        unknown = [d.get("url", "") for d in decisions if d.get("url") not in by_url]
        if unknown:
            return None, f"选项中的地址不属于本次缺页预览：{'、'.join(unknown)}"

        decision_map = {str(d.get("url")): d for d in decisions}
        for url, item in by_url.items():
            decision = str((decision_map.get(url) or {}).get("decision") or "include")
            reason = str((decision_map.get(url) or {}).get("reason") or "").strip()
            entry = _find_entry(job_id, url)
            if entry is None:
                # 理论不会发生：预览创建时已落资格；兜底仍保证唯一
                entry, _ = _ensure_entry(
                    job_id, url, list(item.get("log_ids") or []),
                    str(item.get("failure_reason") or ""))

            receipt = _pending_receipt(job_id, url)
            verified = _verified_success_receipt(job_id, url)

            if verified is not None:
                _apply_item(entry, item, STATUS_EXCLUDED, ITEM_EXCLUDED,
                            REASON_SUCCESS_VERIFIED, operator, preview_id)
                _append_event(
                    job_id=job_id, source_url=url, action="排除",
                    reason=REASON_SUCCESS_VERIFIED,
                    detail=verified.get("receipt_id", ""), operator=operator,
                    preview_id=preview_id,
                    receipt_id=str(verified.get("receipt_id") or ""),
                )
                continue

            if receipt is not None:
                _apply_item(entry, item, STATUS_VERIFYING, ITEM_RETURNED,
                            reason or REASON_PENDING_RECEIPT, operator, preview_id)
                _append_event(
                    job_id=job_id, source_url=url, action="退回核验",
                    reason=reason or REASON_PENDING_RECEIPT, operator=operator,
                    preview_id=preview_id,
                    receipt_id=str(receipt.get("receipt_id") or ""),
                )
                continue

            if decision == "exclude":
                final_reason = reason or "按整组选项排除复采"
                _apply_item(entry, item, STATUS_EXCLUDED, ITEM_EXCLUDED,
                            final_reason, operator, preview_id)
                _append_event(
                    job_id=job_id, source_url=url, action="排除",
                    reason=final_reason, operator=operator, preview_id=preview_id,
                )
            elif decision == "defer":
                final_reason = reason or "按整组选项延期复采"
                _apply_item(entry, item, STATUS_DEFERRED, ITEM_DEFERRED,
                            final_reason, operator, preview_id)
                _append_event(
                    job_id=job_id, source_url=url, action="延期",
                    reason=final_reason, operator=operator, preview_id=preview_id,
                )
            else:
                _apply_item(entry, item, STATUS_QUALIFIED, ITEM_CONFIRMED,
                            "整组确认通过", operator, preview_id)
                _append_event(
                    job_id=job_id, source_url=url, action="纳入复采",
                    reason="整组确认通过",
                    detail="; ".join(item.get("log_ids") or []),
                    operator=operator, preview_id=preview_id,
                )

        preview["status"] = "已确认"
        preview["confirmed_at"] = _now()
        preview["pending"] = False
        preview["abnormal"] = any(
            str(item.get("state")) in (ITEM_EXCLUDED, ITEM_DEFERRED) for item in items)
        _sync_job_list(job_id)
        return _serialize_preview(preview, items), ""


def _state_for_entry(entry: dict[str, Any]) -> str:
    return {
        STATUS_CLAIMED: ITEM_CLAIMED,
        STATUS_EXCLUDED: ITEM_EXCLUDED,
        STATUS_DEFERRED: ITEM_DEFERRED,
        STATUS_VERIFYING: ITEM_RETURNED,
        STATUS_QUALIFIED: ITEM_CONFIRMED,
        STATUS_WAITING: ITEM_WAITING,
    }.get(str(entry.get("status")), ITEM_WAITING)


def _can_transition(entry: dict[str, Any], target: str) -> bool:
    """保护已领走和已核实的资格：旧预览或重复确认不能把终态改回去。"""
    current = str(entry.get("status"))
    if current == STATUS_CLAIMED:
        return target == STATUS_CLAIMED
    if current == STATUS_EXCLUDED and entry.get("receipt_id"):
        return target == STATUS_EXCLUDED
    return True


def _apply_item(entry: dict[str, Any], item: dict[str, Any],
                entry_status: str, item_state: str, reason: str,
                operator: str, preview_id: str) -> None:
    if not _can_transition(entry, entry_status):
        # 资格已是终态（已领走 / 成功已排除），预览条目跟着真实状态走
        entry_status = str(entry.get("status"))
        item_state = _state_for_entry(entry)
        reason = str(entry.get("reason") or reason)
    entry["status"] = entry_status
    entry["reason"] = reason
    entry["preview_id"] = preview_id
    entry["updated_at"] = _now()
    entry["pending"] = entry_status in (STATUS_WAITING, STATUS_VERIFYING)
    entry["abnormal"] = entry_status in (STATUS_EXCLUDED, STATUS_DEFERRED)
    item["state"] = item_state
    item["reason"] = reason
    item["status"] = item_state
    item["updated_at"] = _now()
    item["pending"] = item_state in (ITEM_WAITING, ITEM_RETURNED)
    item["abnormal"] = item_state in (ITEM_EXCLUDED, ITEM_DEFERRED)


def _sync_job_list(job_id: str) -> None:
    """把复采确认结果同步到采集任务清单。"""
    job = _job_row(job_id)
    if job is None:
        return
    entries = [
        row for row in store.rows("recrawl_entry")
        if str(row.get("job_id")) == job_id
    ]
    eligible = [
        str(row.get("source_url")) for row in entries
        if str(row.get("status")) in (STATUS_QUALIFIED, STATUS_CLAIMED)
    ]
    job["复采清单"] = ",".join(eligible)
    if any(str(row.get("status")) == STATUS_CLAIMED for row in entries):
        job["复采状态"] = "已领取"
    elif eligible:
        job["复采状态"] = "待领取"
    elif any(str(row.get("status")) in (STATUS_WAITING, STATUS_VERIFYING) for row in entries):
        job["复采状态"] = "待确认"
    else:
        job["复采状态"] = "已同步"


# ---------------------------------------------------------------------------
# 任务领取：只领真正有资格的入口
# ---------------------------------------------------------------------------

def claim_next(task_id: str, job_id: str | None = None,
               limit: int | None = None) -> tuple[dict[str, Any] | None, str]:
    """采集任务按缺页复采清单领取入口。

    只领取状态为「有资格」且从未被领走的地址；返回实际所领、等候整组确认
    和单独退回核验的地址。
    """
    if not task_id.strip():
        return None, "请提供采集任务编号"

    with _LOCK:
        claimed: list[dict[str, Any]] = []
        pending_verification: list[dict[str, Any]] = []
        waiting_confirmation: list[dict[str, Any]] = []

        entries = [
            row for row in store.rows("recrawl_entry")
            if job_id is None or str(row.get("job_id")) == job_id
        ]
        for entry in entries:
            status = str(entry.get("status"))
            url = str(entry.get("source_url"))
            if status == STATUS_VERIFYING:
                pending_verification.append({
                    "job_id": str(entry.get("job_id")),
                    "source_url": url,
                    "recrawl_id": str(entry.get("recrawl_id")),
                    "failure_reason": str(entry.get("failure_reason") or ""),
                    "reason": str(entry.get("reason") or ""),
                })
            elif status == STATUS_WAITING:
                waiting_confirmation.append({
                    "job_id": str(entry.get("job_id")),
                    "source_url": url,
                    "recrawl_id": str(entry.get("recrawl_id")),
                    "failure_reason": str(entry.get("failure_reason") or ""),
                    "reason": str(entry.get("reason") or ""),
                })

        for entry in entries:
            if limit is not None and len(claimed) >= limit:
                break
            if str(entry.get("status")) != STATUS_QUALIFIED:
                continue
            if int(entry.get("claim_count") or 0) > 0:
                continue

            entry["status"] = STATUS_CLAIMED
            entry["claim_count"] = int(entry.get("claim_count") or 0) + 1
            entry["claimed_by"] = task_id
            entry["claimed_at"] = _now()
            entry["updated_at"] = _now()
            entry["pending"] = False
            entry["abnormal"] = False

            entry_job = str(entry.get("job_id"))
            url = str(entry.get("source_url"))
            claim = RecrawlClaim(
                claim_id=_seq("recrawl_claim", "RCLAIM"),
                task_id=task_id,
                job_id=entry_job,
                source_url=url,
                recrawl_id=str(entry.get("recrawl_id")),
                reason=str(entry.get("reason") or ""),
                created_at=_now(),
            )
            store.rows("recrawl_claim").append({
                "id": _next_id("recrawl_claim"),
                "claim_id": claim.claim_id,
                "task_id": claim.task_id,
                "job_id": claim.job_id,
                "source_url": claim.source_url,
                "recrawl_id": claim.recrawl_id,
                "reason": claim.reason,
                "created_at": claim.created_at,
                "status": "已领取",
                "pending": False,
                "abnormal": False,
            })
            _append_event(
                job_id=entry_job, source_url=url, action="任务领取",
                reason=str(entry.get("reason") or ""),
                detail=claim.claim_id, operator=task_id, task_id=task_id,
            )
            claimed.append({
                "job_id": entry_job,
                "source_url": url,
                "recrawl_id": str(entry.get("recrawl_id")),
                "claim_count": entry["claim_count"],
                "failure_reason": str(entry.get("failure_reason") or ""),
                "reason": str(entry.get("reason") or ""),
            })

        for job in {str(row.get("job_id")) for row in entries}:
            _sync_job_list(job)

        result = {
            "task_id": task_id,
            "claimed": claimed,
            "pending_verification": pending_verification,
            "waiting_confirmation": waiting_confirmation,
            "message": (
                f"任务{task_id}领取{len(claimed)}个入口"
                if claimed else f"任务{task_id}当前没有可领取的复采入口"
            ),
        }
        return result, ""


# ---------------------------------------------------------------------------
# 看板：已领走 / 等候整组确认 / 单独退回核验，按原因排列
# ---------------------------------------------------------------------------

def recrawl_board(job_id: str | None = None) -> dict[str, Any]:
    entries = [
        row for row in store.rows("recrawl_entry")
        if job_id is None or str(row.get("job_id")) == job_id
    ]

    def _item(entry: dict[str, Any]) -> dict[str, Any]:
        status = str(entry.get("status"))
        state = {
            STATUS_CLAIMED: STATE_CLAIMED,
            STATUS_WAITING: STATE_WAITING,
            STATUS_VERIFYING: STATE_RETURNED,
            STATUS_QUALIFIED: STATE_PENDING,
            STATUS_EXCLUDED: STATE_EXCLUDED,
            STATUS_DEFERRED: STATE_DEFERRED,
        }.get(status, status or STATE_PENDING)
        return {
            "job_id": str(entry.get("job_id")),
            "source_url": str(entry.get("source_url")),
            "recrawl_id": str(entry.get("recrawl_id")),
            "status": status,
            "state": state,
            "reason": str(entry.get("reason") or ""),
            "failure_reason": str(entry.get("failure_reason") or ""),
            "claim_count": int(entry.get("claim_count") or 0),
            "claimed_by": str(entry.get("claimed_by") or ""),
            "claimed_at": str(entry.get("claimed_at") or ""),
            "log_ids": list(entry.get("log_ids") or []),
            "receipt_id": str(entry.get("receipt_id") or ""),
            "preview_id": str(entry.get("preview_id") or ""),
        }

    items = [_item(entry) for entry in entries]
    groups: list[dict[str, Any]] = []
    for state in (STATE_CLAIMED, STATE_WAITING, STATE_RETURNED,
                  STATE_PENDING, STATE_DEFERRED, STATE_EXCLUDED):
        bucket = [item for item in items if item["state"] == state]
        if not bucket:
            continue
        bucket.sort(key=lambda item: (item["reason"], item["source_url"]))
        groups.append({
            "state": state,
            "count": len(bucket),
            "items": bucket,
        })

    return {
        "job_id": job_id or "",
        "groups": groups,
        "summary": {
            state: sum(1 for item in items if item["state"] == state)
            for state in (STATE_CLAIMED, STATE_WAITING, STATE_RETURNED,
                          STATE_PENDING, STATE_DEFERRED, STATE_EXCLUDED)
        },
    }


# ---------------------------------------------------------------------------
# 事件回查
# ---------------------------------------------------------------------------

def list_events(job_id: str | None = None,
                source_url: str | None = None) -> list[dict[str, Any]]:
    rows = list(store.rows("recrawl_event"))
    if job_id:
        rows = [row for row in rows if str(row.get("job_id")) == job_id]
    if source_url:
        rows = [row for row in rows if str(row.get("source_url")) == source_url]
    return [
        {
            "event_id": str(row.get("event_id") or ""),
            "job_id": str(row.get("job_id") or ""),
            "source_url": str(row.get("source_url") or ""),
            "action": str(row.get("action") or ""),
            "reason": str(row.get("reason") or ""),
            "detail": str(row.get("detail") or ""),
            "operator": str(row.get("operator") or ""),
            "preview_id": str(row.get("preview_id") or ""),
            "receipt_id": str(row.get("receipt_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "created_at": str(row.get("created_at") or ""),
        }
        for row in rows
    ]
