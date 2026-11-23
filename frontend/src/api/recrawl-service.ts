import { request } from './client'

export type FailureLog = {
  record_id: string
  source_url: string
  parse_rule: string
  parse_result: string
  error_type: string
  failure_reason: string
  retry_count: number | string
  error_detail: string
  recorded_at: string
  evidence: string
}

export type Receipt = {
  receipt_id: string
  job_id: string
  source_url: string
  source_node: string
  result: string
  arrived_at: string
  failure_log_id: string
  verification: string
  verification_note: string
  verified_by: string
  verified_at: string
}

export type MissingItem = {
  job_id: string
  source_url: string
  failure_reasons: string[]
  failure_count: number
  log_ids: string[]
  latest_log_time: string
  logs: FailureLog[]
  receipt: Receipt | null
  recrawl_status: string
  state: string
  reason: string
}

export type MissingJob = {
  job_id: string
  job_label: string
  missing_count: number
  reasons: { reason: string; count: number }[]
  items: MissingItem[]
  pending_recrawl: number
  awaiting_verify: number
}

export type MissingBoard = { jobs: MissingJob[]; total: number }

export type PreviewItem = {
  source_url: string
  failure_reason: string
  log_ids: string[]
  state: string
  reason: string
  recrawl_id: string
}

export type Preview = {
  preview_id: string
  job_id: string
  job_label: string
  status: string
  operator: string
  created_at: string
  confirmed_at: string
  items: PreviewItem[]
}

export type ClaimedItem = {
  job_id: string
  source_url: string
  recrawl_id: string
  claim_count: number
  failure_reason: string
  reason: string
}

export type ClaimResult = {
  task_id: string
  claimed: ClaimedItem[]
  pending_verification: ClaimedItem[]
  waiting_confirmation: ClaimedItem[]
  message: string
}

export type BoardItem = {
  job_id: string
  source_url: string
  recrawl_id: string
  status: string
  state: string
  reason: string
  failure_reason: string
  claim_count: number
  claimed_by: string
  claimed_at: string
  log_ids: string[]
  receipt_id: string
  preview_id: string
}

export type BoardGroup = { state: string; count: number; items: BoardItem[] }

export type RecrawlBoard = {
  job_id: string
  groups: BoardGroup[]
  summary: Record<string, number>
}

export type RecrawlEvent = {
  event_id: string
  job_id: string
  source_url: string
  action: string
  reason: string
  detail: string
  operator: string
  preview_id: string
  receipt_id: string
  task_id: string
  created_at: string
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) throw new Error(`接口返回 ${response.status}，操作未生效`)
  return (await response.json()) as T
}

export async function loadMissingBoard(jobId?: string): Promise<MissingBoard> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''
  const response = await request(`/api/recrawl/missing-board${query}`)
  if (!response.ok) throw new Error('缺页图读取失败')
  return (await response.json()) as MissingBoard
}

export async function createPreview(
  jobId: string,
  urls: string[],
  operator = '值班员',
): Promise<{ ok: boolean; message: string; preview: Preview | null }> {
  return await postJson('/api/recrawl/previews', { job_id: jobId, urls, operator })
}

export async function getPreview(previewId: string): Promise<Preview | null> {
  const response = await request(`/api/recrawl/previews/${encodeURIComponent(previewId)}`)
  if (!response.ok) return null
  return (await response.json()) as Preview
}

export async function confirmPreview(
  previewId: string,
  decisions: { url: string; decision: string; reason: string }[],
  operator = '值班员',
): Promise<{ ok: boolean; message: string; preview: Preview | null }> {
  return await postJson(`/api/recrawl/previews/${previewId}/confirm`, { decisions, operator })
}

export async function verifyReceipt(
  receiptId: string,
  verdict: 'success' | 'reject',
  note: string,
  operator = '值班员',
): Promise<{ ok: boolean; message: string; receipt: Receipt | null }> {
  return await postJson(`/api/recrawl/receipts/${receiptId}/verify`, { verdict, note, operator })
}

export async function claimNext(
  taskId: string,
  jobId?: string,
): Promise<{ ok: boolean; message: string; result: ClaimResult | null }> {
  return await postJson('/api/recrawl/claims', { task_id: taskId, job_id: jobId ?? null })
}

export async function loadRecrawlBoard(jobId?: string): Promise<RecrawlBoard> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''
  const response = await request(`/api/recrawl/board${query}`)
  if (!response.ok) throw new Error('复采看板读取失败')
  return (await response.json()) as RecrawlBoard
}

export async function loadRecrawlEvents(
  jobId?: string,
  sourceUrl?: string,
): Promise<RecrawlEvent[]> {
  const params = new URLSearchParams()
  if (jobId) params.set('job_id', jobId)
  if (sourceUrl) params.set('source_url', sourceUrl)
  const query = params.toString()
  const response = await request(`/api/recrawl/events${query ? `?${query}` : ''}`)
  if (!response.ok) throw new Error('复采原因回查失败')
  const payload = (await response.json()) as { items: RecrawlEvent[] }
  return payload.items
}
