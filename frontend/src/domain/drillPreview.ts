/** 下钻透视预览领域类型：与后端 app/services/drill_down.py 的返回结构对齐。 */

export interface MetricDef {
  metric: string
  aggregation: string
}

export interface ParentInfo {
  parent: string
  member_version: number
  member_version_hash: string
  member_count: number
  store_count: number
  channel_count: number
  available_metrics: MetricDef[]
}

export interface MemberScope {
  member_code: string
  member_name: string
  member_type: string
  /** 度量值；null 表示缺失，聚合时不得按 0 累计 */
  metrics: Record<string, number | null>
}

export interface DrillRead {
  read_id: number
  parent: string
  read_at: string
  member_version: number
  member_version_hash: string
  members: MemberScope[]
  metric_defs: Record<string, string>
  current_member_version: number
  stale: boolean
  member_count: number
}

export interface TotalStat {
  aggregation: string
  value: number | null
  present_count: number
  missing_count: number
  missing_members: string[]
}

export interface PivotSlice {
  read_id: number
  parent: string
  read_at: string
  member_version: number
  member_version_hash: string
  current_member_version: number
  current_member_version_hash: string
  stale: boolean
  stale_reason: string
  member_scope: MemberScope[]
  member_count: number
  available_metrics: MetricDef[]
  totals: Record<string, TotalStat>
}

export interface PivotSourceMember {
  member_code: string
  member_name: string
  value: number | null
}

export interface PivotCell {
  row: string
  metric: string
  value: number | null
  aggregation: string
  present_count: number
  missing_count: number
  missing_members: string[]
  source_members: PivotSourceMember[]
  difference: number | null
}

export interface ConsistencyCheck {
  code: string
  label: string
  passed: boolean
  detail: string
}

export interface PivotPreview {
  read_id: number
  parent: string
  config_name: string
  row_dimension: string
  column_dimension: string
  aggregation: Record<string, string>
  member_version: number
  member_version_hash: string
  current_member_version: number
  stale: boolean
  stale_reason: string
  member_scope: MemberScope[]
  available_metrics: MetricDef[]
  grid: PivotCell[]
  grouped_totals: Record<string, Record<string, number | null>>
  grand_totals: Record<string, number | null>
  slice_totals: Record<string, TotalStat>
  consistency_checks: ConsistencyCheck[]
  all_checks_passed: boolean
}

export interface ReadSummary {
  read_id: number
  read_at: string
  member_version: number
  member_version_hash: string
  member_count: number
  stale: boolean
}

export interface MetricDifference {
  base_value: number | null
  target_value: number | null
  difference: number | null
}

export interface ReadComparison {
  parent: string
  base_read: {
    read_id: number
    read_at: string
    member_version: number
    member_version_hash: string
    member_count: number
  }
  target_read: {
    read_id: number
    read_at: string
    member_version: number
    member_version_hash: string
    member_count: number
  }
  added_members: MemberScope[]
  removed_members: string[]
  metric_differences: Record<string, MetricDifference>
  explanation: string
}

export interface RegisterMemberForm {
  member_code: string
  member_name: string
  member_type: string
  metrics: Record<string, string>
}
