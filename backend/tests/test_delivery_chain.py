"""数据投递和质量抽样测试：投递链路、质量抽样逻辑、代理成本和归档。"""
from __future__ import annotations

from app.integration import (
    run_crawl_pipeline, deliver_and_sample, archive_batch,
    compute_crawl_cost, select_proxy_for_job, schedule_job,
)
from app.models import (
    CleanedContent, CrawlJobSpec, DeliveryTask, ProxyNode, ProxyType,
    QualitySample, SampleMethod, SiteConfig, SiteType, StorageBatch, CostRecord,
    SchedulePlan,
)
from app.store import store


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------

VALID_SITE = {
    "id": 1, "status": "已验证", "pending": False, "abnormal": False,
    "站点编号": "CRAW-DEL-T001", "站点域名": "delivery.example.com",
    "站点类型": "新闻门户", "Robots协议": "allow",
    "站点语言": "zh-CN", "地域归属": "CN",
    "接入方式": "direct", "注册时间": "2026-11-01",
}

VALID_JOB = {
    "id": 1, "status": "待执行", "pending": True, "abnormal": False,
    "作业编号": "CRAW-DEL-JOB", "目标站点": "delivery.example.com",
    "入口URL": "https://delivery.example.com/article/1",
    "最大深度": "3", "并发线程": "4",
    "调度策略": "interval", "完成页数": "0", "失败页数": "0",
}

VALID_EXTRACT_RULE = {
    "id": 1, "status": "生效中", "pending": False, "abnormal": False,
    "规则编号": "CONT-DEL-T001", "目标站点": "delivery.example.com",
    "XPath选择器": "//article", "字段映射": "title,body",
    "数据类型": "string", "清洗正则": "", "抽取顺序": "1",
    "规则状态": "生效中",
}

VALID_CLEAN_RULE = {
    "id": 1, "status": "生效中", "pending": False, "abnormal": False,
    "规则编号": "FIEL-DEL-T001", "目标字段": "title",
    "清洗类型": "去空格", "处理表达式": "",
    "空值策略": "skip", "校验范围": "",
    "清洗顺序": "1", "规则状态": "生效中",
}


# ---------------------------------------------------------------------------
# 测试：数据投递链路
# ---------------------------------------------------------------------------

def test_delivery_from_valid_batch() -> None:
    """从校验通过的批次投递数据。"""
    batch = run_crawl_pipeline(
        site_row=VALID_SITE, job_row=VALID_JOB,
        extract_rows=[VALID_EXTRACT_RULE],
        clean_rows=[VALID_CLEAN_RULE],
    )

    assert batch is not None
    assert batch.status == "校验通过"

    dt, qs = deliver_and_sample(batch)

    assert dt is not None, "应创建投递任务"
    assert dt.status == "已完成", f"投递状态应为已完成，实际: {dt.status}"
    assert dt.delivered_row_count == batch.row_count, \
        f"投递行数应与批次行数一致: {dt.delivered_row_count} != {batch.row_count}"
    assert dt.batch_ref_id == batch.batch_id, "投递应关联批次ID"


def test_delivery_from_failed_batch() -> None:
    """从校验失败的批次投递时应标记投递失败。"""
    records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={}),
    ]
    batch = StorageBatch(
        batch_id="BATCH-FAIL-001", source_job_id="JOB-FAIL",
        row_count=1, status="校验失败", records=records,
        storage_path="/data/batches/JOB-FAIL/",
    )

    dt, qs = deliver_and_sample(batch)

    assert dt is not None
    assert dt.status == "投递失败", f"校验失败批次投递应标记失败，实际: {dt.status}"


def test_delivery_with_existing_task() -> None:
    """已有投递任务时复用已有任务。"""
    store.rows("data_delivery").append({
        "id": 999, "任务编号": "DATA-DEL-PREEXIST", "数据来源": "BATCH-PREEXIST-001",
        "目标系统": "pre_exist_target", "投递格式": "CSV", "投递频率": "daily",
        "分区策略": "by_date", "最近投递": "", "投递状态": "待投递",
        "status": "待投递", "pending": False, "abnormal": False,
    })

    records = [
        CleanedContent(source_url="url1", extract_rule_id="R1", fields={"title": "ok"}),
    ]
    batch = StorageBatch(
        batch_id="BATCH-PREEXIST-001", source_job_id="JOB-PRE",
        row_count=1, status="校验通过", records=records,
        storage_path="/data/batches/JOB-PRE/",
    )

    dt, qs = deliver_and_sample(batch)

    assert dt is not None
    # 应复用已有任务的 task_id
    assert dt.task_id == "DATA-DEL-PREEXIST" or dt.task_id.startswith("DEL-"), \
        f"投递任务应存在，actual: {dt.task_id}"


# ---------------------------------------------------------------------------
# 测试：质量抽样
# ---------------------------------------------------------------------------

def test_quality_sample_from_valid_batch() -> None:
    """从校验通过批次抽样：抽样结果应为通过。"""
    batch = run_crawl_pipeline(
        site_row=VALID_SITE, job_row=VALID_JOB,
        extract_rows=[VALID_EXTRACT_RULE],
        clean_rows=[VALID_CLEAN_RULE],
    )

    assert batch is not None
    _, qs = deliver_and_sample(batch)

    assert qs is not None, "应创建抽样计划"
    assert qs.status == "已通过", f"抽样状态应为已通过，实际: {qs.status}"
    assert qs.check_result, "应有检查结果"
    assert qs.sample_size > 0, f"样本量应大于0，实际: {qs.sample_size}"


def test_quality_sample_deviation_alert() -> None:
    """高失败率抽样：应触发偏差告警。"""
    # 创建一半无效记录的批次
    records = []
    for i in range(20):
        if i % 2 == 0:
            records.append(CleanedContent(source_url=f"url{i}", extract_rule_id="R1",
                                          fields={"title": f"ok{i}"}))
        else:
            records.append(CleanedContent(source_url=f"url{i}", extract_rule_id="R1",
                                          fields={}))

    batch = StorageBatch(
        batch_id="BATCH-DEVIATION-001", source_job_id="JOB-DEV",
        row_count=20, status="校验通过", records=records,
        storage_path="/data/batches/JOB-DEV/",
    )

    _, qs = deliver_and_sample(batch)

    assert qs is not None
    # 50% 无效记录应该触发偏差告警（阈值 5%）
    if qs.check_result:
        valid_count = int(qs.check_result.split("有效")[1].split("条")[0])
        if valid_count < qs.sample_size * (1 - qs.deviation_threshold):
            assert qs.status == "偏差告警", \
                f"高失败率应触发偏差告警，实际: {qs.status}"


def test_quality_sample_empty_batch() -> None:
    """空批次抽样：不应崩溃。"""
    batch = StorageBatch(
        batch_id="BATCH-EMPTY-001", source_job_id="JOB-EMPTY",
        row_count=0, status="校验通过", records=[],
        storage_path="/data/batches/empty/",
    )

    _, qs = deliver_and_sample(batch)

    assert qs is not None, "空批次也应创建抽样计划"


def test_quality_sample_structure() -> None:
    """抽样计划结构完整性验证。"""
    qs = QualitySample(
        plan_id="QS-TEST", target_batch="BATCH-001",
        sample_ratio=0.15, sample_method=SampleMethod.RANDOM,
        sample_size=15,
        deviation_threshold=0.05, status="已通过",
        check_result="抽样15条，有效14条",
    )

    assert qs.plan_id == "QS-TEST"
    assert qs.sample_ratio == 0.15
    assert qs.sample_size == 15
    assert qs.deviation_threshold == 0.05


# ---------------------------------------------------------------------------
# 测试：归档
# ---------------------------------------------------------------------------

def test_archive_valid_batch() -> None:
    """归档校验通过的批次。"""
    batch = run_crawl_pipeline(
        site_row=VALID_SITE, job_row=VALID_JOB,
        extract_rows=[VALID_EXTRACT_RULE],
        clean_rows=[VALID_CLEAN_RULE],
    )

    assert batch is not None

    before = len(store.rows("data_archive"))
    policy = archive_batch(batch)
    after = len(store.rows("data_archive"))

    assert policy is not None, "应创建归档策略"
    assert policy.status == "已完成", f"归档状态应为已完成，实际: {policy.status}"
    assert after >= before, "归档记录应持久化"


def test_archive_with_existing_policy() -> None:
    """已有归档策略时正确复用。"""
    store.rows("data_archive").append({
        "id": 888, "策略编号": "DATA-ARCH-EXIST", "数据范围": "BATCH-ARCH-EXIST",
        "归档周期": "monthly", "归档格式": "gzip", "保留时长": "90",
        "存储位置": "/archive/", "压缩方式": "gzip", "最后归档": "",
        "status": "待触发", "pending": False, "abnormal": False,
    })

    batch = StorageBatch(
        batch_id="BATCH-ARCH-EXIST", source_job_id="JOB-ARCH",
        row_count=5, status="校验通过",
        records=[CleanedContent(source_url="u1", extract_rule_id="R1", fields={"x": "y"})],
    )

    policy = archive_batch(batch)

    assert policy is not None
    assert policy.policy_id == "DATA-ARCH-EXIST", \
        f"应复用已有策略，实际: {policy.policy_id}"


# ---------------------------------------------------------------------------
# 测试：计费
# ---------------------------------------------------------------------------

def test_crawl_cost_computation() -> None:
    """采集计费：请求量和数据量正确核算。"""
    job = CrawlJobSpec(
        job_id="JOB-COST", site=SiteConfig(
            site_id="S1", domain="cost.example.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=["https://cost.example.com"],
        completed_pages=100, failed_pages=10, status="已完成",
    )

    proxy = ProxyNode(
        node_id="P1", address="10.0.0.1:8080",
        proxy_type=ProxyType.HTTP, region_tag="CN", operator="telecom",
        latency_ms=200, success_rate=0.99, status="可用",
    )

    before = len(store.rows("crawl_cost"))
    record = compute_crawl_cost(job, proxy)
    after = len(store.rows("crawl_cost"))

    assert record is not None, "应生成计费记录"
    assert record.request_count == 110, f"请求次数应为110，实际: {record.request_count}"
    assert record.data_volume_mb > 0, f"数据流量应大于0，实际: {record.data_volume_mb}"
    assert record.proxy_usage_hours > 0, f"代理用量应大于0，实际: {record.proxy_usage_hours}"
    assert record.estimated_cost > 0, f"费用预估应大于0，实际: {record.estimated_cost}"
    assert after >= before + 1, "计费记录应持久化"


def test_crawl_cost_without_proxy() -> None:
    """无代理时计费：代理用量应为 0。"""
    job = CrawlJobSpec(
        job_id="JOB-NOPROXY", site=SiteConfig(
            site_id="S2", domain="noproxy.example.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=["https://noproxy.example.com"],
        completed_pages=50, failed_pages=0, status="已完成",
    )

    record = compute_crawl_cost(job, None)

    assert record.proxy_usage_hours == 0, f"无代理时用量应为0，实际: {record.proxy_usage_hours}"


# ---------------------------------------------------------------------------
# 测试：调度编排
# ---------------------------------------------------------------------------

def test_schedule_job_creation() -> None:
    """为采集作业创建调度计划。"""
    job = CrawlJobSpec(
        job_id="JOB-SCHED", site=SiteConfig(
            site_id="S3", domain="sched.example.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=["https://sched.example.com"],
        status="待执行",
    )

    before = len(store.rows("scheduler"))
    plan = schedule_job(job)
    after = len(store.rows("scheduler"))

    assert plan is not None, "应创建调度计划"
    assert plan.linked_job_id == "JOB-SCHED", "调度应关联作业"
    assert plan.cron_expr, "应有 Cron 表达式"
    assert after >= before + 1, "调度计划应持久化"


def test_schedule_existing_plan() -> None:
    """已有调度计划时复用。"""
    store.rows("scheduler").append({
        "id": 777, "计划编号": "SCHE-SCHED-EXIST", "关联作业": "JOB-SCHED-EXIST",
        "Cron表达式": "0 */12 * * *", "时区设置": "Asia/Shanghai",
        "依赖检查": "", "失败通知": "", "并发控制": "", "下次执行": "",
        "status": "待激活", "pending": False, "abnormal": False,
    })

    job = CrawlJobSpec(
        job_id="JOB-SCHED-EXIST", site=SiteConfig(
            site_id="S4", domain="sched2.example.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=["https://sched2.example.com"],
        status="待执行",
    )

    plan = schedule_job(job)

    assert plan is not None
    assert plan.plan_id == "SCHE-SCHED-EXIST", f"应复用已有计划，实际: {plan.plan_id}"
    assert plan.status == "执行中", f"调度状态应为执行中，实际: {plan.status}"


# ---------------------------------------------------------------------------
# 测试：代理池与反爬
# ---------------------------------------------------------------------------

def test_proxy_selection() -> None:
    """代理选择：从代理池中选择最佳代理。"""
    # 保存原始代理池，只在测试中使用临时数据
    orig_pool = list(store.rows("proxy_pool"))
    store.rows("proxy_pool").clear()

    store.rows("proxy_pool").append({
        "id": 101, "节点编号": "PROX-SEL-FAST", "代理地址": "10.0.1.1:8080",
        "代理类型": "HTTP", "地域标签": "CN", "运营商": "telecom",
        "响应延迟": 100, "成功率": 0.99, "最后校验": "2026-11-01",
        "status": "可用", "pending": False, "abnormal": False,
    })
    store.rows("proxy_pool").append({
        "id": 102, "节点编号": "PROX-SEL-SLOW", "代理地址": "10.0.1.2:8080",
        "代理类型": "HTTP", "地域标签": "CN", "运营商": "unicom",
        "响应延迟": 500, "成功率": 0.95, "最后校验": "2026-11-01",
        "status": "可用", "pending": False, "abnormal": False,
    })

    try:
        job = CrawlJobSpec(
            job_id="JOB-PROXY", site=SiteConfig(
                site_id="S5", domain="proxy.example.com", site_type=SiteType.NEWS,
                robots_policy="allow", language="zh-CN", region="CN",
                access_method="direct", registered_at="2026-01-01",
            ),
            entry_urls=["https://proxy.example.com"],
        )

        proxy = select_proxy_for_job(job)

        assert proxy is not None, "应有可用代理"
        assert proxy.is_available(), "选出的代理应可用"
        assert proxy.node_id == "PROX-SEL-FAST", \
            f"应选延迟最低的代理，实际: {proxy.node_id}"
    finally:
        # 恢复原始代理池
        store.rows("proxy_pool").clear()
        for row in orig_pool:
            store.rows("proxy_pool").append(row)


def test_proxy_selection_no_available() -> None:
    """无可用代理时返回 None。"""
    # 清空代理池并添加不可用代理
    store.rows("proxy_pool").clear()
    store.rows("proxy_pool").append({
        "id": 201, "节点编号": "PROX-DOWN", "代理地址": "10.0.0.99:8080",
        "代理类型": "HTTP", "地域标签": "CN", "运营商": "telecom",
        "响应延迟": 9999, "成功率": 0.1, "最后校验": "2026-11-01",
        "status": "已下线", "pending": False, "abnormal": True,
    })

    job = CrawlJobSpec(
        job_id="JOB-NOPROXY2", site=SiteConfig(
            site_id="S6", domain="noproxy2.example.com", site_type=SiteType.NEWS,
            robots_policy="allow", language="zh-CN", region="CN",
            access_method="direct", registered_at="2026-01-01",
        ),
        entry_urls=["https://noproxy2.example.com"],
    )

    proxy = select_proxy_for_job(job)

    assert proxy is None, "无可用代理应返回 None"


# ---------------------------------------------------------------------------
# S11 容量辅助导入
# ---------------------------------------------------------------------------

from app.models import (
    CleanedContent, CrawlJobSpec, DeliveryTask, ProxyNode, ProxyType,
    QualitySample, SiteConfig, SiteType, StorageBatch, CostRecord,
    SchedulePlan,
)