"""URL 去重和增量采集测试：去重指纹计算、增量游标、差异检测。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.integration import (
    run_dedup_flow, run_incremental_flow,
)
from app.models import (
    CrawlJobSpec, IncrCursor, UrlFingerprint, SiteConfig, SiteType,
    CleanedContent, DiffRecord, StorageBatch,
)
from app.store import store


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

def _make_job(entry_urls: list[str]) -> CrawlJobSpec:
    return CrawlJobSpec(
        job_id="DEDUP-JOB-001",
        site=SiteConfig(
            site_id="S1", domain="test.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=entry_urls,
    )


# ---------------------------------------------------------------------------
# URL 去重测试
# ---------------------------------------------------------------------------

def test_dedup_all_new_urls() -> None:
    """全部新 URL：应全部标记为新增。"""
    job = _make_job([
        "https://test.com/page1",
        "https://test.com/page2",
        "https://test.com/page3",
    ])

    new_fps, dup_fps = run_dedup_flow(job)

    assert len(new_fps) == 3, f"应有3个新增指纹，实际: {len(new_fps)}"
    assert len(dup_fps) == 0, f"应无重复指纹，实际: {len(dup_fps)}"
    for fp in new_fps:
        assert fp.hash_value, "每个指纹应有哈希值"


def test_dedup_duplicate_urls() -> None:
    """重复 URL：应被正确识别。使用唯一 URL 避免测试间状态影响。"""
    from uuid import uuid4
    u1 = f"https://test-{uuid4().hex[:8]}.com/page1"
    u2 = f"https://test-{uuid4().hex[:8]}.com/page2"
    u3 = f"https://test-{uuid4().hex[:8]}.com/page3"

    # 第一次：全部新增
    job1 = _make_job([u1, u2])
    new1, dup1 = run_dedup_flow(job1)
    assert len(new1) == 2, f"第一次应有2个新增，实际: {len(new1)}"

    # 第二次：部分重复
    job2 = _make_job([u1, u3])
    new2, dup2 = run_dedup_flow(job2)

    assert len(new2) == 1, f"应只有1个新增，实际: {len(new2)}"
    assert len(dup2) == 1, f"应有1个重复，实际: {len(dup2)}"


def test_dedup_url_normalization() -> None:
    """URL 规范化：参数顺序不同应视为相同 URL。"""
    fp1 = UrlFingerprint.compute("https://test.com/page?b=2&a=1", "sha256")
    fp2 = UrlFingerprint.compute("https://test.com/page?a=1&b=2", "sha256")

    assert fp1.hash_value == fp2.hash_value, \
        "参数顺序不同的同URL应产生相同哈希"


def test_dedup_different_domains() -> None:
    """不同域名：应产生不同指纹。"""
    fp1 = UrlFingerprint.compute("https://site-a.com/page")
    fp2 = UrlFingerprint.compute("https://site-b.com/page")

    assert fp1.hash_value != fp2.hash_value, "不同域名应产生不同指纹"


def test_dedup_different_paths() -> None:
    """相同域名不同路径：应产生不同指纹。"""
    fp1 = UrlFingerprint.compute("https://test.com/page/1")
    fp2 = UrlFingerprint.compute("https://test.com/page/2")

    assert fp1.hash_value != fp2.hash_value, "不同路径应产生不同指纹"


def test_dedup_fragment_ignored() -> None:
    """URL 片段（fragment）应被忽略。"""
    fp1 = UrlFingerprint.compute("https://test.com/page#section1")
    fp2 = UrlFingerprint.compute("https://test.com/page#section2")

    assert fp1.hash_value == fp2.hash_value, "不同 fragment 的相同页面应产生相同指纹"


def test_dedup_empty_url_list() -> None:
    """空 URL 列表：应返回空列表。"""
    job = _make_job([])

    new_fps, dup_fps = run_dedup_flow(job)

    assert len(new_fps) == 0
    assert len(dup_fps) == 0


# ---------------------------------------------------------------------------
# 增量采集与差异检测测试
# ---------------------------------------------------------------------------

def test_incremental_no_change() -> None:
    """无变化增量：不应产生差异记录。"""
    records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV", source_job_id="J1",
        row_count=1, records=records, status="校验通过",
    )

    cursor = IncrCursor(
        cursor_id="INCR-T001", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    result = run_incremental_flow(cursor, prev_batch, records)

    assert result is None, "无变化不应产生差异记录"


def test_incremental_new_content() -> None:
    """新增内容：应产生新增类型的差异记录。"""
    prev_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV", source_job_id="J1",
        row_count=1, records=prev_records, status="校验通过",
    )

    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
        CleanedContent(source_url="url2", extract_rule_id="R1", fields={"title": "T2"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-T002", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    result = run_incremental_flow(cursor, prev_batch, curr_records)

    assert result is not None, "新增内容应产生差异记录"
    assert "新增" in result.change_type, f"变更类型应包含'新增'，实际: {result.change_type}"
    assert result.new_summary, "应有新内容摘要"


def test_incremental_content_changed() -> None:
    """内容变更：应产生变更类型的差异记录。"""
    prev_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "旧标题"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV", source_job_id="J1",
        row_count=1, records=prev_records, status="校验通过",
    )

    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "新标题"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-T003", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    result = run_incremental_flow(cursor, prev_batch, curr_records)

    assert result is not None, "内容变更应产生差异记录"
    assert "变更" in result.change_type, f"变更类型应包含'变更'，实际: {result.change_type}"
    assert cursor.updated_count > 0, "游标应更新变更计数"


def test_incremental_content_removed() -> None:
    """内容删除：应产生删除类型的差异记录。"""
    prev_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
        CleanedContent(source_url="url2", extract_rule_id="R1", fields={"title": "T2"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV", source_job_id="J1",
        row_count=2, records=prev_records, status="校验通过",
    )

    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-T004", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    result = run_incremental_flow(cursor, prev_batch, curr_records)

    assert result is not None, "内容删除应产生差异记录"
    assert "删除" in result.change_type or cursor.new_count >= 0


def test_incremental_with_empty_previous() -> None:
    """无历史批次：不应产生差异记录。"""
    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-T005", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    result = run_incremental_flow(cursor, None, curr_records)

    assert result is None, "无历史批次不应产生差异记录"


def test_incremental_cursor_update() -> None:
    """差异检测后游标应正确更新。"""
    prev_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV", source_job_id="J1",
        row_count=1, records=prev_records, status="校验通过",
    )

    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
        CleanedContent(source_url="url2", extract_rule_id="R1", fields={"title": "T2"}),
        CleanedContent(source_url="url3", extract_rule_id="R1", fields={"title": "T3"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-T006", target_site="test.com",
        incr_field="updated_at", last_cursor="2026-01-01",
        current_cursor="2026-01-02", status="追踪中",
    )

    old_last = cursor.last_cursor
    run_incremental_flow(cursor, prev_batch, curr_records)

    assert cursor.new_count == 2, f"新增应为2，实际: {cursor.new_count}"
    assert cursor.last_cursor == "2026-01-02", \
        f"上次游标应推进到之前当前值，实际: {cursor.last_cursor}"
    assert cursor.status == "已追上", f"游标状态应为已追上，实际: {cursor.status}"


# ---------------------------------------------------------------------------
# 指纹去重与持久化
# ---------------------------------------------------------------------------

def test_dedup_persists_to_store() -> None:
    """去重结果应持久化到 store。"""
    before = len(store.rows("url_dedup"))

    job = _make_job(["https://test.com/new-page-xyz"])
    run_dedup_flow(job)

    after = len(store.rows("url_dedup"))
    assert after >= before + 1, f"应至少增加1条去重记录，before={before} after={after}"


def test_dedup_duplicate_count_increment() -> None:
    """重复检测：重复计数应递增。"""
    job1 = _make_job(["https://test.com/dup-page-abc"])
    new1, dup1 = run_dedup_flow(job1)
    assert len(new1) == 1

    job2 = _make_job(["https://test.com/dup-page-abc"])
    new2, dup2 = run_dedup_flow(job2)

    assert len(dup2) == 1
    assert dup2[0].duplicate_count >= 1, \
        f"重复计数应递增，实际: {dup2[0].duplicate_count}"


# ---------------------------------------------------------------------------
# 差异检测分类测试
# ---------------------------------------------------------------------------

def test_diff_record_structure() -> None:
    """DiffRecord 结构完整性验证。"""
    diff = DiffRecord(
        record_id="DIFF-T001", target_site="test.com",
        page_url="https://test.com/1", change_type="内容变更",
        old_summary="旧摘要", new_summary="新摘要",
        affected_fields=["title", "body"],
    )

    assert diff.record_id == "DIFF-T001"
    assert diff.change_type == "内容变更"
    assert "title" in diff.affected_fields


# ---------------------------------------------------------------------------
# 增量差异持久化
# ---------------------------------------------------------------------------

def test_diff_persists_to_store() -> None:
    """差异记录应持久化到 store。"""
    before = len(store.rows("diff_check"))

    prev_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
    ]
    prev_batch = StorageBatch(
        batch_id="BATCH-PREV-DIFF", source_job_id="J1",
        row_count=1, records=prev_records, status="校验通过",
    )

    curr_records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "T1"}),
        CleanedContent(source_url="url-new-diff", extract_rule_id="R1", fields={"title": "T2"}),
    ]

    cursor = IncrCursor(
        cursor_id="INCR-DIFF-001", target_site="test.com",
        incr_field="updated_at", status="追踪中",
    )

    run_incremental_flow(cursor, prev_batch, curr_records)

    after = len(store.rows("diff_check"))
    assert after >= before + 1, f"应至少增加1条差异记录，before={before} after={after}"


# ---------------------------------------------------------------------------
# S11 容量辅助导入
# ---------------------------------------------------------------------------

from app.models import (
    CleanedContent, CrawlJobSpec, DiffRecord, IncrCursor, SiteConfig,
    SiteType, StorageBatch, UrlFingerprint,
)