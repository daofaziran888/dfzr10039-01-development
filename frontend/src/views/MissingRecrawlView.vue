<template>
  <section class="page" data-module="missing_recrawl">
    <header class="page-head">
      <div>
        <h2>缺页复采</h2>
        <p class="page-desc">
          按采集作业汇总解析日志缺页，列出失败原因；勾选一组地址生成缺页复采清单，
          整组确认后同步到采集任务，任务只能领取真正有资格的入口。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" data-testid="refresh" @click="reloadAll">
          刷新缺页图
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text" data-testid="error">{{ errorMessage }}</p>
    <p v-if="notice" class="notice-text" data-testid="notice">{{ notice }}</p>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">缺页地址</span>
        <strong class="stat-value" data-testid="stat-missing">{{ board.total }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待复采</span>
        <strong class="stat-value" data-testid="stat-pending">{{ summary['待复采'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已领走</span>
        <strong class="stat-value" data-testid="stat-claimed">{{ summary['已领走'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">单独退回核验</span>
        <strong class="stat-value" data-testid="stat-returned">{{ summary['单独退回核验'] ?? 0 }}</strong>
      </article>
    </div>

    <div class="filter-bar">
      <label class="filter-item">
        <span>采集作业</span>
        <select v-model="jobFilter" data-testid="job-filter" @change="reloadAll">
          <option value="">全部作业</option>
          <option v-for="job in jobOptions" :key="job.job_id" :value="job.job_id">
            {{ job.job_label }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>采集任务编号</span>
        <input v-model="taskId" data-testid="task-id" placeholder="例如 TASK-J12-01" />
      </label>
      <button class="btn" type="button" data-testid="claim" @click="claimEntries">
        任务领取入口
      </button>
    </div>

    <!-- 缺页图：按作业分组，列出失败原因 -->
    <article
      v-for="job in board.jobs"
      :key="job.job_id"
      class="panel"
      :data-testid="`job-${job.job_id}`"
    >
      <header class="panel-head">
        <div>
          <h3>{{ job.job_label }}</h3>
          <p class="panel-sub">
            缺页 {{ job.missing_count }} · 待复采 {{ job.pending_recrawl }} · 待核验 {{ job.awaiting_verify }}
          </p>
        </div>
        <div class="reason-tags">
          <span
            v-for="reason in job.reasons"
            :key="reason.reason"
            class="reason-tag"
            :data-testid="`reason-${job.job_id}-${reason.reason}`"
          >
            {{ reason.reason }}：{{ reason.count }}
          </span>
        </div>
      </header>

      <table class="data-table">
        <thead>
          <tr>
            <th class="check-cell">
              <input
                type="checkbox"
                :data-testid="`select-all-${job.job_id}`"
                :checked="allSelected(job)"
                @change="toggleAll(job, ($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>来源 URL</th>
            <th>失败原因</th>
            <th>原始解析日志</th>
            <th>迟到回执</th>
            <th>复采状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in job.items"
            :key="item.source_url"
            :data-testid="`missing-${item.source_url}`"
            :data-state="item.state"
          >
            <td class="check-cell">
              <input
                v-model="selected[job.job_id]"
                type="checkbox"
                :value="item.source_url"
                :data-testid="`select-${item.source_url}`"
              />
            </td>
            <td class="url-cell">{{ item.source_url }}</td>
            <td>
              <span
                v-for="reason in item.failure_reasons"
                :key="reason"
                class="reason-chip"
              >{{ reason }}</span>
            </td>
            <td>
              <details>
                <summary>{{ item.log_ids.join('、') }}</summary>
                <div class="log-detail">
                  <p v-for="log in item.logs" :key="log.record_id" class="log-line">
                    <strong>{{ log.record_id }}</strong>
                    <span>{{ log.failure_reason }}</span>
                    <span class="muted">{{ log.error_detail }}</span>
                    <span class="muted">{{ log.recorded_at }}</span>
                    <em>{{ log.evidence }}</em>
                  </p>
                </div>
              </details>
            </td>
            <td>
              <div v-if="item.receipt" class="receipt-box">
                <span :data-testid="`receipt-state-${item.source_url}`">
                  {{ item.receipt.verification }}
                </span>
                <span class="muted">{{ item.receipt.source_node }} · {{ item.receipt.result }}</span>
                <button
                  v-if="item.receipt.verification === '待核验'"
                  class="link"
                  type="button"
                  :data-testid="`verify-${item.source_url}`"
                  @click="verify(item.receipt.receipt_id, 'success')"
                >
                  核实成功
                </button>
                <button
                  v-if="item.receipt.verification === '待核验'"
                  class="link"
                  type="button"
                  :data-testid="`reject-${item.source_url}`"
                  @click="verify(item.receipt.receipt_id, 'reject')"
                >
                  驳回回执
                </button>
              </div>
              <span v-else class="muted">—</span>
            </td>
            <td>
              <span class="state-chip" :data-testid="`state-${item.source_url}`">{{ item.state }}</span>
              <span v-if="item.reason" class="muted block">{{ item.reason }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="panel-foot">
        <span class="muted">已选 {{ (selected[job.job_id] ?? []).length }} 个地址</span>
        <button
          class="btn primary"
          type="button"
          :data-testid="`create-preview-${job.job_id}`"
          @click="createPreviewFor(job)"
        >
          生成缺页复采清单
        </button>
      </div>
    </article>

    <p v-if="!board.jobs.length" class="empty-state">当前没有缺页记录</p>

    <!-- 缺页预览：整组确认 -->
    <article v-if="preview" class="panel" data-testid="preview-panel">
      <header class="panel-head">
        <div>
          <h3>缺页预览 · {{ preview.preview_id }}</h3>
          <p class="panel-sub">
            {{ preview.job_label }} · 状态 {{ preview.status }}
            <span v-if="preview.confirmed_at">· 确认于 {{ preview.confirmed_at }}</span>
          </p>
        </div>
      </header>

      <table class="data-table">
        <thead>
          <tr>
            <th>来源 URL</th>
            <th>失败原因</th>
            <th>预览状态</th>
            <th>整组选项</th>
            <th>选项原因</th>
            <th>原因回查</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in preview.items"
            :key="item.source_url"
            :data-testid="`preview-item-${item.source_url}`"
          >
            <td class="url-cell">{{ item.source_url }}</td>
            <td>
              <span class="reason-chip">{{ item.failure_reason }}</span>
            </td>
            <td>
              <span class="state-chip">{{ item.state }}</span>
              <span class="muted block">{{ item.reason }}</span>
            </td>
            <td>
              <select
                v-model="decisions[item.source_url].decision"
                :data-testid="`decision-${item.source_url}`"
                :disabled="preview.status === '已确认'"
              >
                <option value="include">纳入复采</option>
                <option value="defer">延期</option>
                <option value="exclude">排除</option>
              </select>
            </td>
            <td>
              <input
                v-model="decisions[item.source_url].reason"
                :data-testid="`decision-reason-${item.source_url}`"
                placeholder="填写延期/排除原因"
                :disabled="preview.status === '已确认'"
              />
            </td>
            <td>
              <button
                class="link"
                type="button"
                :data-testid="`events-${item.source_url}`"
                @click="openEvents(item.source_url)"
              >
                查看事件
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="panel-foot">
        <span class="muted">
          整组确认只生成一次复采资格；复核中的地址只能退回核验，成功回执一经核实立即排除。
        </span>
        <button
          class="btn primary"
          type="button"
          data-testid="confirm-preview"
          :disabled="preview.status === '已确认'"
          @click="submitConfirm"
        >
          提交整组选项
        </button>
      </div>
    </article>

    <!-- 任务领取结果 -->
    <article v-if="claimResult" class="panel" data-testid="claim-panel">
      <header class="panel-head">
        <div>
          <h3>任务领取结果 · {{ claimResult.task_id }}</h3>
          <p class="panel-sub">{{ claimResult.message }}</p>
        </div>
      </header>
      <div class="claim-grid">
        <section>
          <h4>实际所领（{{ claimResult.claimed.length }}）</h4>
          <ul class="claim-list" data-testid="claimed-list">
            <li v-for="item in claimResult.claimed" :key="item.source_url">
              <span class="url-cell">{{ item.source_url }}</span>
              <span class="muted">{{ item.reason }} · 认领 {{ item.claim_count }} 次</span>
            </li>
            <li v-if="!claimResult.claimed.length" class="muted">没有可领取的入口</li>
          </ul>
        </section>
        <section>
          <h4>等候整组确认（{{ claimResult.waiting_confirmation.length }}）</h4>
          <ul class="claim-list" data-testid="waiting-list">
            <li v-for="item in claimResult.waiting_confirmation" :key="item.source_url">
              <span class="url-cell">{{ item.source_url }}</span>
              <span class="muted">{{ item.reason }}</span>
            </li>
            <li v-if="!claimResult.waiting_confirmation.length" class="muted">无</li>
          </ul>
        </section>
        <section>
          <h4>单独退回核验（{{ claimResult.pending_verification.length }}）</h4>
          <ul class="claim-list" data-testid="verification-list">
            <li v-for="item in claimResult.pending_verification" :key="item.source_url">
              <span class="url-cell">{{ item.source_url }}</span>
              <span class="muted">{{ item.reason }}</span>
            </li>
            <li v-if="!claimResult.pending_verification.length" class="muted">无</li>
          </ul>
        </section>
      </div>
    </article>

    <!-- 缺页看板：已领走 / 等候整组确认 / 单独退回核验 -->
    <article v-if="recrawlBoard.groups.length" class="panel" data-testid="recrawl-board">
      <header class="panel-head">
        <div>
          <h3>缺页看板</h3>
          <p class="panel-sub">按原因排列，展示已领走、等候整组确认和单独退回核验的地址。</p>
        </div>
      </header>
      <section
        v-for="group in recrawlBoard.groups"
        :key="group.state"
        class="board-group"
        :data-testid="`group-${group.state}`"
      >
        <h4>{{ group.state }}（{{ group.count }}）</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>来源 URL</th>
              <th>原因</th>
              <th>失败原因</th>
              <th>认领次数</th>
              <th>原始解析日志</th>
              <th>回查</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in group.items" :key="item.source_url">
              <td class="url-cell">{{ item.source_url }}</td>
              <td>{{ item.reason || '—' }}</td>
              <td>{{ item.failure_reason || '—' }}</td>
              <td :data-testid="`claim-count-${item.source_url}`">{{ item.claim_count }}</td>
              <td class="muted">{{ item.log_ids.join('、') || '—' }}</td>
              <td>
                <button
                  class="link"
                  type="button"
                  :data-testid="`board-events-${item.source_url}`"
                  @click="openEvents(item.source_url)"
                >
                  查看事件
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </article>

    <!-- 事件回查 -->
    <article v-if="eventUrl" class="panel" data-testid="events-panel">
      <header class="panel-head">
        <div>
          <h3>原因回查 · {{ eventUrl }}</h3>
          <p class="panel-sub">每次纳入、延期、排除、核验和领走都留痕。</p>
        </div>
        <button class="btn ghost" type="button" data-testid="close-events" @click="eventUrl = ''">
          关闭
        </button>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>时间</th><th>动作</th><th>原因</th><th>操作人</th><th>关联</th></tr>
        </thead>
        <tbody>
          <tr v-for="event in events" :key="event.event_id">
            <td class="muted">{{ event.created_at }}</td>
            <td>{{ event.action }}</td>
            <td>{{ event.reason || '—' }}</td>
            <td>{{ event.operator || '—' }}</td>
            <td class="muted">{{ event.preview_id || event.receipt_id || event.task_id || '—' }}</td>
          </tr>
          <tr v-if="!events.length">
            <td colspan="5" class="empty-state">该地址暂无事件</td>
          </tr>
        </tbody>
      </table>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  claimNext,
  confirmPreview,
  createPreview,
  getPreview,
  loadMissingBoard,
  loadRecrawlBoard,
  loadRecrawlEvents,
  verifyReceipt,
} from '@/api/recrawl-service'
import type {
  ClaimResult,
  MissingBoard,
  MissingJob,
  Preview,
  RecrawlBoard,
  RecrawlEvent,
} from '@/api/recrawl-service'

const board = ref<MissingBoard>({ jobs: [], total: 0 })
const recrawlBoard = ref<RecrawlBoard>({ job_id: '', groups: [], summary: {} })
const preview = ref<Preview | null>(null)
const claimResult = ref<ClaimResult | null>(null)
const events = ref<RecrawlEvent[]>([])
const eventUrl = ref('')
const jobFilter = ref('')
const jobOptions = ref<{ job_id: string; job_label: string }[]>([])
const taskId = ref('TASK-J12-01')
const selected = reactive<Record<string, string[]>>({})
const decisions = reactive<Record<string, { decision: string; reason: string }>>({})
const errorMessage = ref('')
const notice = ref('')

const summary = computed(() => {
  const totals: Record<string, number> = {}
  for (const job of board.value.jobs) {
    for (const item of job.items) {
      totals[item.state] = (totals[item.state] ?? 0) + 1
    }
  }
  return totals
})

function allSelected(job: MissingJob): boolean {
  const picked = selected[job.job_id] ?? []
  return job.items.length > 0 && job.items.every((item) => picked.includes(item.source_url))
}

function toggleAll(job: MissingJob, checked: boolean) {
  selected[job.job_id] = checked ? job.items.map((item) => item.source_url) : []
}

function resetDecisions(items: { source_url: string }[]) {
  for (const item of items) {
    if (!decisions[item.source_url]) {
      decisions[item.source_url] = { decision: 'include', reason: '' }
    }
  }
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    const [missing, boardData] = await Promise.all([
      loadMissingBoard(jobFilter.value || undefined),
      loadRecrawlBoard(jobFilter.value || undefined),
    ])
    board.value = missing
    recrawlBoard.value = boardData
    // 作业下拉始终保留全部缺页作业，筛选后也能切回去
    const known = new Set(jobOptions.value.map((job) => job.job_id))
    for (const job of missing.jobs) {
      if (!known.has(job.job_id)) {
        jobOptions.value.push({ job_id: job.job_id, job_label: job.job_label })
        known.add(job.job_id)
      }
    }
    jobOptions.value.sort((a, b) => a.job_id.localeCompare(b.job_id))
    for (const job of missing.jobs) {
      if (!selected[job.job_id]) selected[job.job_id] = []
      resetDecisions(job.items)
    }
    if (preview.value) {
      resetDecisions(preview.value.items)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺页数据读取失败'
  }
}

async function createPreviewFor(job: MissingJob) {
  errorMessage.value = ''
  notice.value = ''
  const urls = selected[job.job_id] ?? []
  if (!urls.length) {
    errorMessage.value = '请先勾选至少一个缺页地址'
    return
  }
  try {
    const result = await createPreview(job.job_id, urls)
    if (!result.ok || !result.preview) throw new Error(result.message)
    preview.value = result.preview
    resetDecisions(result.preview.items)
    notice.value = `已生成缺页预览 ${result.preview.preview_id}`
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成缺页复采清单失败'
  }
}

async function verify(receiptId: string, verdict: 'success' | 'reject') {
  errorMessage.value = ''
  notice.value = ''
  const note = verdict === 'success'
    ? '核实来源节点回执与抓取日志一致'
    : '回执来源无法确认'
  try {
    const result = await verifyReceipt(receiptId, verdict, note)
    if (!result.ok) throw new Error(result.message)
    notice.value = verdict === 'success'
      ? '迟到成功回执已核实，该地址排除复采'
      : '回执已驳回，地址回到整组确认'
    if (preview.value) {
      const fresh = await getPreview(preview.value.preview_id)
      if (fresh) preview.value = fresh
    }
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回执核验失败'
  }
}

async function submitConfirm() {
  errorMessage.value = ''
  notice.value = ''
  if (!preview.value) return
  const payload = preview.value.items.map((item) => ({
    url: item.source_url,
    decision: decisions[item.source_url]?.decision ?? 'include',
    reason: decisions[item.source_url]?.reason ?? '',
  }))
  try {
    const result = await confirmPreview(preview.value.preview_id, payload)
    if (!result.ok || !result.preview) throw new Error(result.message)
    preview.value = result.preview
    notice.value = result.message
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整组确认提交失败'
  }
}

async function claimEntries() {
  errorMessage.value = ''
  notice.value = ''
  if (!taskId.value.trim()) {
    errorMessage.value = '请填写采集任务编号'
    return
  }
  try {
    const result = await claimNext(taskId.value.trim(), jobFilter.value || undefined)
    if (!result.result) throw new Error(result.message)
    claimResult.value = result.result
    notice.value = result.message
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '任务领取失败'
  }
}

async function openEvents(sourceUrl: string) {
  errorMessage.value = ''
  eventUrl.value = sourceUrl
  try {
    events.value = await loadRecrawlEvents(jobFilter.value || undefined, sourceUrl)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原因回查失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
.panel-head h3 { margin: 0; font-size: 15px; }
.panel-sub { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.panel-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; font-size: 12px; }
.reason-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.reason-tag { background: #eef4ff; color: var(--brand); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.reason-chip { display: inline-block; background: #fdecea; color: #b42318; border-radius: 4px; padding: 1px 8px; margin-right: 6px; font-size: 12px; }
.state-chip { display: inline-block; background: #eef2f7; border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.check-cell { width: 34px; }
.url-cell { word-break: break-all; }
.muted { color: var(--muted); }
.block { display: block; margin-top: 4px; font-size: 12px; }
.notice-text { color: #12805c; font-size: 13px; }
.select select, select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.receipt-box { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.log-detail { margin-top: 6px; }
.log-line { display: flex; gap: 8px; flex-wrap: wrap; margin: 2px 0; font-size: 12px; }
.log-line em { color: #12805c; font-style: normal; }
.claim-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.claim-grid h4 { margin: 0 0 6px; font-size: 13px; }
.claim-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.claim-list li { border: 1px dashed var(--border); border-radius: 6px; padding: 6px 8px; }
.board-group { margin-top: 14px; }
.board-group h4 { margin: 0 0 6px; font-size: 13px; }
.filter-item select { min-width: 220px; }
</style>
