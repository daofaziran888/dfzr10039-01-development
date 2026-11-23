"""缺页复采测试：缺页图、整组确认、迟到回执核验、领取与原因回查。"""
from __future__ import annotations

import copy
import threading

import pytest

from app.services import recrawl
from app.store import store

J12 = "J12"
J13 = "J13"
URL_A = "https://news.j12.example.com/article/a"
URL_B = "https://news.j12.example.com/article/b"
URL_C = "https://news.j12.example.com/article/c"
URL_D = "https://news.j13.example.com/article/d"

RECRAWL_TABLES = (
    "parse_log", "parse_receipt", "missing_preview", "missing_preview_item",
    "recrawl_entry", "recrawl_event", "recrawl_claim", "crawl_job",
)


@pytest.fixture(autouse=True)
def _restore_store():
    """每个用例从种子状态开始，避免复采资格和事件互相污染。"""
    snapshot = {name: copy.deepcopy(store.rows(name)) for name in RECRAWL_TABLES}
    yield
    for name, rows in snapshot.items():
        table = store.rows(name)
        table[:] = copy.deepcopy(rows)


def _preview(urls: list[str] = [URL_A, URL_B, URL_C], job_id: str = J12) -> dict:
    preview, error = recrawl.create_preview(job_id, urls, "值班员")
    assert preview is not None, error
    return preview


def _confirm(preview_id: str, urls: list[str], decision: str = "include",
             reason: str = "") -> dict:
    preview, error = recrawl.confirm_preview(
        preview_id,
        [{"url": url, "decision": decision, "reason": reason} for url in urls],
        "值班员",
    )
    assert preview is not None, error
    return preview


# ---------------------------------------------------------------------------
# 缺页图
# ---------------------------------------------------------------------------

def test_missing_board_groups_by_job_and_reason() -> None:
    board = recrawl.missing_board()
    by_job = {job["job_id"]: job for job in board["jobs"]}

    assert set(by_job) >= {J12, J13}, "缺页图应按采集作业汇总"
    assert by_job[J12]["missing_count"] == 3, "J12 应有 A、B、C 三个缺页地址"
    assert by_job[J13]["missing_count"] == 1, "J13 应有 1 个缺页地址"

    reasons = {item["reason"]: item["count"] for item in by_job[J12]["reasons"]}
    assert reasons == {"字段缺失": 2, "格式异常": 2}, f"失败原因统计不符: {reasons}"

    a = next(item for item in by_job[J12]["items"] if item["source_url"] == URL_A)
    assert a["failure_reasons"] == ["字段缺失", "格式异常"], "A 的失败原因应保留两类"
    assert a["log_ids"] == ["PLOG-J12-A-F1", "PLOG-J12-A-F2"], "原始解析日志编号必须留存"
    assert all(log["evidence"] == "原始解析日志" for log in a["logs"]), "原始日志不得被覆盖"


def test_missing_board_filters_by_job() -> None:
    board = recrawl.missing_board(J13)
    assert len(board["jobs"]) == 1
    assert board["jobs"][0]["job_id"] == J13
    assert board["jobs"][0]["items"][0]["source_url"] == URL_D


# ---------------------------------------------------------------------------
# 预览与整组确认
# ---------------------------------------------------------------------------

def test_preview_marks_pending_receipt_as_returned_verification() -> None:
    preview = _preview()
    states = {item["source_url"]: item["state"] for item in preview["items"]}

    assert states[URL_A] == "单独退回核验", "A 有迟到成功回执待核验，应单独退回核验"
    assert states[URL_B] == "等候整组确认"
    assert states[URL_C] == "等候整组确认"


def test_claim_before_verification_and_confirmation_takes_nothing() -> None:
    """核实 A 的回执、提交整组选项之前，任务领不到任何入口。"""
    _preview()

    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert result["claimed"] == [], "整组未确认时不能领取"
    assert [item["source_url"] for item in result["pending_verification"]] == [URL_A]
    assert {item["source_url"] for item in result["waiting_confirmation"]} == {URL_B, URL_C}

    entry_a = recrawl._find_entry(J12, URL_A)
    assert entry_a is not None
    assert entry_a["status"] == recrawl.STATUS_VERIFYING, "复核中的 A 不能获得复采资格"
    assert entry_a["claim_count"] == 0


def test_confirm_before_verification_does_not_grant_a() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])

    entry_a = recrawl._find_entry(J12, URL_A)
    assert entry_a is not None
    assert entry_a["status"] == recrawl.STATUS_VERIFYING, "复核中的 A 不能获得复采资格"
    assert entry_a["claim_count"] == 0

    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert [item["source_url"] for item in result["claimed"]] == [URL_B, URL_C]
    assert [item["source_url"] for item in result["pending_verification"]] == [URL_A]
    assert result["waiting_confirmation"] == []


def test_rejecting_receipt_returns_address_to_group_confirmation() -> None:
    preview = _preview()
    recrawl.verify_receipt("RCPT-J12-A-01", "reject", "来源节点不可信", "值班员")
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])

    entry_a = recrawl._find_entry(J12, URL_A)
    assert entry_a["status"] == recrawl.STATUS_QUALIFIED, "回执驳回后 A 可正常纳入复采"


def test_verified_success_receipt_excludes_address() -> None:
    preview = _preview()
    receipt, error = recrawl.verify_receipt(
        "RCPT-J12-A-01", "success", "worker-07 回执与抓取日志一致", "值班员")
    assert receipt is not None, error

    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])
    entry_a = recrawl._find_entry(J12, URL_A)
    assert entry_a["status"] == recrawl.STATUS_EXCLUDED, "成功一经核实必须排除"
    assert entry_a["reason"] == recrawl.REASON_SUCCESS_VERIFIED

    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    claimed = [item["source_url"] for item in result["claimed"]]
    assert claimed == [URL_B, URL_C], f"只应领取 B、C，实际: {claimed}"


def test_preview_rejects_address_without_failure_log() -> None:
    preview, error = recrawl.create_preview(
        J12, ["https://news.j12.example.com/article/a", "https://news.j12.example.com/ok"],
        "值班员")
    assert preview is None
    assert "没有有效失败记录" in error


def test_confirm_is_idempotent_and_never_double_grants() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])
    first_count = len(store.rows("recrawl_entry"))

    again = _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])
    assert len(store.rows("recrawl_entry")) == first_count, "重复确认不得重复生成资格"
    assert again["status"] == "已确认"
    entry_b = recrawl._find_entry(J12, URL_B)
    assert entry_b["status"] == recrawl.STATUS_QUALIFIED
    assert entry_b["claim_count"] == 0


def test_concurrent_confirm_yields_single_qualification_per_address() -> None:
    p1 = _preview([URL_B, URL_C])
    p2 = _preview([URL_B, URL_C])

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def _run(preview_id: str) -> None:
        barrier.wait()
        _, error = recrawl.confirm_preview(
            preview_id,
            [{"url": URL_B, "decision": "include"},
             {"url": URL_C, "decision": "include"}],
            "并发值班",
        )
        if error:
            errors.append(error)

    threads = [threading.Thread(target=_run, args=(pid,)) for pid in (p1["preview_id"], p2["preview_id"])]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    entries = [row for row in store.rows("recrawl_entry")
               if row["job_id"] == J12 and row["source_url"] in (URL_B, URL_C)]
    assert len(entries) == 2, "同一地址并发确认只能有一条复采资格"
    assert all(row["status"] == recrawl.STATUS_QUALIFIED for row in entries)

    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert len(result["claimed"]) == 2
    assert all(row["claim_count"] == 1 for row in entries), "每个地址只能被认领一次"


# ---------------------------------------------------------------------------
# 领取与看板
# ---------------------------------------------------------------------------

def test_claim_lists_claimed_waiting_and_returned_by_reason() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])

    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert [item["source_url"] for item in result["claimed"]] == [URL_B, URL_C]
    assert [item["source_url"] for item in result["waiting_confirmation"]] == []
    assert [item["source_url"] for item in result["pending_verification"]] == [URL_A]

    second, _ = recrawl.claim_next("TASK-J12-02", J12)
    assert second["claimed"] == [], "已被领走的地址不能再次领取"
    assert all(row["claim_count"] == 1 for row in store.rows("recrawl_entry")
               if row["source_url"] in (URL_B, URL_C))


def test_board_groups_claimed_waiting_and_returned_sorted_by_reason() -> None:
    _preview()
    board = recrawl.recrawl_board(J12)
    states = {group["state"]: group for group in board["groups"]}

    assert states["单独退回核验"]["count"] == 1
    assert states["等候整组确认"]["count"] == 2
    for group in board["groups"]:
        reasons = [item["reason"] for item in group["items"]]
        assert reasons == sorted(reasons), f"{group['state']} 分组应按原因排列"


def test_board_shows_claimed_and_reason_after_claim() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])
    recrawl.claim_next("TASK-J12-01", J12)

    board = recrawl.recrawl_board(J12)
    states = {group["state"]: group for group in board["groups"]}
    assert states["已领走"]["count"] == 2
    assert states["单独退回核验"]["count"] == 1
    claimed = {item["source_url"] for item in states["已领走"]["items"]}
    assert claimed == {URL_B, URL_C}
    assert all(item["claim_count"] == 1 for item in states["已领走"]["items"])


def test_confirmation_syncs_to_crawl_job_list() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])

    job = next(row for row in store.rows("crawl_job") if row["作业编号"] == J12)
    assert job["复采状态"] == "待领取"
    assert set(job["复采清单"].split(",")) == {URL_B, URL_C}, "任务清单只同步真正有资格的入口"

    recrawl.claim_next("TASK-J12-01", J12)
    assert job["复采状态"] == "已领取"


def test_deferred_and_excluded_reasons_are_queryable() -> None:
    preview = _preview()
    recrawl.confirm_preview(
        preview["preview_id"],
        [
            {"url": URL_A, "decision": "exclude", "reason": "回执来源不可信，转入人工"},
            {"url": URL_B, "decision": "defer", "reason": "站点维护窗口，延期到次日"},
            {"url": URL_C, "decision": "include", "reason": ""},
        ],
        "值班员",
    )

    entry_b = recrawl._find_entry(J12, URL_B)
    entry_c = recrawl._find_entry(J12, URL_C)
    assert entry_b["status"] == recrawl.STATUS_DEFERRED
    assert entry_c["status"] == recrawl.STATUS_QUALIFIED

    events_b = recrawl.list_events(J12, URL_B)
    assert any(event["action"] == "延期" and "维护窗口" in event["reason"]
               for event in events_b), "延期原因必须可回查"
    events_c = recrawl.list_events(J12, URL_C)
    assert any(event["action"] == "纳入复采" for event in events_c)


def test_failure_logs_and_source_are_retained_after_confirm() -> None:
    preview = _preview()
    _confirm(preview["preview_id"], [URL_A, URL_B, URL_C])
    recrawl.verify_receipt("RCPT-J12-A-01", "success", "来源一致", "值班员")

    logs = [row for row in store.rows("parse_log")
            if row.get("所属作业") == J12 and row.get("来源URL") == URL_A]
    assert len(logs) == 2, "原失败日志不得删除"
    assert {log["记录编号"] for log in logs} == {"PLOG-J12-A-F1", "PLOG-J12-A-F2"}

    board = recrawl.missing_board(J12)["jobs"][0]
    item_a = next(item for item in board["items"] if item["source_url"] == URL_A)
    assert item_a["state"] == "已排除"
    assert {log["record_id"] for log in item_a["logs"]} == {"PLOG-J12-A-F1", "PLOG-J12-A-F2"}


def test_stale_preview_cannot_reopen_claimed_address() -> None:
    """旧预览晚确认时，不能把已领走的地址重新变回可领取。"""
    first = _preview([URL_B])
    _confirm(first["preview_id"], [URL_B])
    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert [item["source_url"] for item in result["claimed"]] == [URL_B]

    stale = _preview([URL_B])
    late = _confirm(stale["preview_id"], [URL_B])

    entry = recrawl._find_entry(J12, URL_B)
    assert entry["status"] == recrawl.STATUS_CLAIMED, "已领走的资格不能被旧预览改回有资格"
    assert entry["claim_count"] == 1, "认领次数不能被旧预览重置"
    stale_item = next(item for item in late["items"] if item["source_url"] == URL_B)
    assert stale_item["state"] == "已领走", "旧预览应显示地址的真实状态"


def test_verified_exclusion_survives_late_confirmation() -> None:
    """成功回执核实后，任何晚到的整组确认都只能保持排除。"""
    _preview([URL_A])
    recrawl.verify_receipt("RCPT-J12-A-01", "success", "来源一致", "值班员")

    late = _preview([URL_A])
    _confirm(late["preview_id"], [URL_A])

    entry = recrawl._find_entry(J12, URL_A)
    assert entry["status"] == recrawl.STATUS_EXCLUDED
    result, _ = recrawl.claim_next("TASK-J12-01", J12)
    assert result["claimed"] == []
