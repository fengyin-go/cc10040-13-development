/** 下钻透视预览接口封装：只读/动作都走跨模块数据流路由。 */
import { request } from './client'
import type {
  DrillRead,
  ParentInfo,
  PivotPreview,
  PivotSlice,
  ReadComparison,
  ReadSummary,
  RegisterMemberForm,
} from '@/domain/drillPreview'

const BASE = '/api/cross/drill-preview'

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

export async function fetchParents(): Promise<{ parents: ParentInfo[]; metrics: Record<string, string> }> {
  return getJson(`${BASE}/parents`)
}

export async function readDrillParent(parent: string): Promise<DrillRead> {
  return postJson(`${BASE}/${encodeURIComponent(parent)}/read`)
}

export async function registerMember(
  parent: string,
  form: RegisterMemberForm,
): Promise<{ ok?: boolean; message?: string; error?: string }> {
  return postJson(`${BASE}/${encodeURIComponent(parent)}/members`, form)
}

export async function fetchReads(parent: string): Promise<{ parent: string; current_member_version: number; reads: ReadSummary[] }> {
  return getJson(`${BASE}/${encodeURIComponent(parent)}/reads`)
}

export async function fetchSlice(readId: number): Promise<PivotSlice> {
  return getJson(`${BASE}/slice/${readId}`)
}

export async function fetchPreview(readId: number): Promise<PivotPreview> {
  return getJson(`${BASE}/preview/${readId}`)
}

export async function compareReads(baseReadId: number, targetReadId: number): Promise<ReadComparison> {
  return postJson(`${BASE}/compare`, { base_read_id: baseReadId, target_read_id: targetReadId })
}
