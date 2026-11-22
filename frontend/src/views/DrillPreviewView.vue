<template>
  <section class="page drill-page">
    <header class="page-head">
      <div>
        <h2>下钻分析</h2>
        <p class="page-desc">
          设计从汇总到明细的下钻路径，并在透视预览中按刚选中的父级核对门店或渠道合计、成员范围与成员版本
        </p>
      </div>
    </header>

    <div class="tab-bar" role="tablist">
      <button
        type="button"
        class="tab"
        :class="{ active: tab === 'config' }"
        data-testid="tab-config"
        @click="tab = 'config'"
      >
        下钻路径配置
      </button>
      <button
        type="button"
        class="tab"
        :class="{ active: tab === 'preview' }"
        data-testid="tab-preview"
        @click="switchToPreview"
      >
        透视预览
      </button>
    </div>

    <WorkbenchView v-if="tab === 'config'" module-key="drill_down" />

    <div v-else class="preview-workbench" data-testid="preview-workbench">
      <p v-if="errorMessage" class="error-text" data-testid="preview-error">{{ errorMessage }}</p>

      <div class="preview-layout">
        <!-- 左栏：父级与读取历史 -->
        <div class="panel">
          <h3 class="panel-title">可下钻父级</h3>
          <ul class="parent-list">
            <li v-for="item in parents" :key="item.parent">
              <button
                type="button"
                class="parent-card"
                :class="{ selected: item.parent === selectedParent }"
                :data-testid="`parent-${item.parent}`"
                @click="selectParent(item.parent)"
              >
                <span class="parent-name">{{ item.parent }}</span>
                <span class="parent-meta">
                  门店 {{ item.store_count }} · 渠道 {{ item.channel_count }} · 共 {{ item.member_count }} 个成员
                </span>
                <span class="parent-version" :data-testid="`version-${item.parent}`">
                  成员版本 v{{ item.member_version }}（{{ item.member_version_hash }}）
                </span>
              </button>
            </li>
          </ul>

          <h3 class="panel-title">读取历史（同一父级）</h3>
          <p v-if="!selectedParent" class="muted-text">请先选择一个父级</p>
          <ul v-else class="read-list" data-testid="read-history">
            <li v-for="read in reads" :key="read.read_id" class="read-item">
              <button
                type="button"
                class="link"
                :data-testid="`history-read-${read.read_id}`"
                @click="openPreview(read.read_id)"
              >
                #{{ read.read_id }} {{ read.read_at }}
              </button>
              <span class="read-meta">
                v{{ read.member_version }} · {{ read.member_count }} 成员
                <em v-if="read.stale" class="stale-tag" :data-testid="`stale-${read.read_id}`">含补录前版本</em>
                <em v-else class="current-tag">当前版本</em>
              </span>
            </li>
            <li v-if="!reads.length" class="muted-text">暂无读取记录，先执行一次下钻读取</li>
          </ul>
        </div>

        <!-- 右栏：当前读取与操作 -->
        <div class="panel panel-main">
          <div class="panel-head">
            <h3 class="panel-title">
              下钻明细{{ selectedParent ? `：${selectedParent}` : '' }}
            </h3>
            <div class="panel-actions" v-if="selectedParent">
              <button
                type="button"
                class="btn primary"
                data-testid="do-read"
                :disabled="loading"
                @click="doRead"
              >
                {{ loading ? '读取中…' : '下钻读取（固化成员快照）' }}
              </button>
              <button
                type="button"
                class="btn"
                data-testid="open-register"
                :disabled="!selectedParent"
                @click="openRegister"
              >
                补录成员
              </button>
              <button
                type="button"
                class="btn"
                data-testid="open-compare"
                :disabled="reads.length < 2"
                @click="openCompare"
              >
                对照两次读数
              </button>
            </div>
          </div>

          <div v-if="!selectedParent" class="empty-state">请从左侧选择一个父级开始下钻</div>

          <template v-else>
            <div v-if="currentRead" class="read-summary" data-testid="current-read">
              <div class="summary-line">
                <strong>读取 #{{ currentRead.read_id }}</strong>
                <span>时间：{{ currentRead.read_at }}</span>
                <span data-testid="current-version">
                  采用成员版本 v{{ currentRead.member_version }}（{{ currentRead.member_version_hash }}）
                </span>
                <span v-if="currentReadStale" class="stale-tag" data-testid="current-stale">
                  父级已补录成员，该读数不含新成员
                </span>
                <span v-else class="current-tag">与父级当前成员版本一致</span>
              </div>
              <p class="muted-text">
                本次统计可用度量：
                <span v-for="metric in metricNames" :key="metric" class="metric-chip">{{ metric }}（SUM）</span>
              </p>

              <table class="data-table member-table">
                <thead>
                  <tr>
                    <th>成员编号</th>
                    <th>成员名称</th>
                    <th>成员类型</th>
                    <th v-for="metric in metricNames" :key="metric">{{ metric }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="member in currentRead.members" :key="member.member_code" :data-testid="`member-${member.member_code}`">
                    <td>{{ member.member_code }}</td>
                    <td>{{ member.member_name }}</td>
                    <td>{{ member.member_type }}</td>
                    <td v-for="metric in metricNames" :key="metric" :data-testid="`cell-${member.member_code}-${metric}`">
                      <span v-if="member.metrics[metric] !== null && member.metrics[metric] !== undefined">
                        {{ member.metrics[metric] }}
                      </span>
                      <span v-else class="missing-tag">缺失（不计零）</span>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div class="panel-actions">
                <button
                  type="button"
                  class="btn primary"
                  data-testid="open-preview"
                  @click="openPreview(currentRead.read_id)"
                >
                  查看透视预览
                </button>
              </div>
            </div>
            <div v-else class="empty-state">尚未读取，点击「下钻读取」固化当前成员快照</div>
          </template>
        </div>
      </div>
    </div>

    <!-- 补录成员弹窗 -->
    <div v-if="showRegister" class="modal-backdrop" data-testid="register-modal">
      <form class="modal" @submit.prevent="submitRegister">
        <h3>补录成员：{{ selectedParent }}</h3>
        <p class="muted-text">补录后成员版本递增，历史读取快照保持不变；度量留空表示缺失，不会按零累计。</p>
        <label class="create-field">
          <span>成员编号</span>
          <input v-model="registerForm.member_code" data-testid="register-code" required />
        </label>
        <label class="create-field">
          <span>成员名称</span>
          <input v-model="registerForm.member_name" data-testid="register-name" required />
        </label>
        <label class="create-field">
          <span>成员类型</span>
          <select v-model="registerForm.member_type" data-testid="register-type">
            <option value="门店">门店</option>
            <option value="渠道">渠道</option>
          </select>
        </label>
        <label v-for="metric in metricNames" :key="metric" class="create-field">
          <span>{{ metric }}（留空为缺失）</span>
          <input v-model="registerForm.metrics[metric]" :data-testid="`register-metric-${metric}`" placeholder="数值，可留空" />
        </label>
        <p v-if="registerError" class="error-text">{{ registerError }}</p>
        <div class="page-actions">
          <button type="button" class="btn" @click="showRegister = false">取消</button>
          <button type="submit" class="btn primary" data-testid="submit-register" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认补录' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 透视预览弹窗 -->
    <div v-if="preview" class="modal-backdrop modal-wide" data-testid="preview-modal">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ preview.config_name }}</h3>
          <button type="button" class="btn ghost" data-testid="close-preview" @click="preview = null">返回下钻</button>
        </div>

        <div v-if="preview.stale" class="banner banner-warn" data-testid="preview-stale-banner">
          <strong>成员版本已变化：</strong>{{ preview.stale_reason }}。本次格值不包含补录后的新成员，可与早些时候记下的明细直接核对。
        </div>
        <div v-else class="banner banner-ok" data-testid="preview-fresh-banner">
          该读数与父级当前成员版本一致，格值覆盖当前全部成员。
        </div>

        <p class="muted-text">
          读取 #{{ preview.read_id }} · 行维度：{{ preview.row_dimension }} · 列维度：{{ preview.column_dimension }}
          · 采用版本 v{{ preview.member_version }}（{{ preview.member_version_hash }}）
          <template v-if="preview.stale"> · 父级当前 v{{ preview.current_member_version }}</template>
        </p>

        <h4 class="section-title">本次统计可用的成员范围（{{ preview.member_scope.length }}）</h4>
        <table class="data-table compact-table">
          <thead>
            <tr>
              <th>成员编号</th>
              <th>成员名称</th>
              <th>类型</th>
              <th v-for="m in preview.available_metrics" :key="m.metric">{{ m.metric }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in preview.member_scope" :key="member.member_code">
              <td>{{ member.member_code }}</td>
              <td>{{ member.member_name }}</td>
              <td>{{ member.member_type }}</td>
              <td v-for="m in preview.available_metrics" :key="m.metric">
                <span v-if="member.metrics[m.metric] !== null && member.metrics[m.metric] !== undefined">
                  {{ member.metrics[m.metric] }}
                </span>
                <span v-else class="missing-tag">缺失</span>
              </td>
            </tr>
          </tbody>
        </table>

        <h4 class="section-title">可用度量</h4>
        <p class="muted-text">
          <span v-for="m in preview.available_metrics" :key="m.metric" class="metric-chip">
            {{ m.metric }} · {{ m.aggregation }}
          </span>
        </p>

        <h4 class="section-title">透视格值（含来源与差额）</h4>
        <table class="data-table compact-table" data-testid="preview-grid">
          <thead>
            <tr>
              <th>{{ preview.row_dimension }}</th>
              <th v-for="m in preview.available_metrics" :key="m.metric">{{ m.metric }}（格值 / 差额）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rowName in gridRows" :key="rowName" :data-testid="`grid-row-${rowName}`">
              <td>{{ rowName }}</td>
              <td v-for="m in preview.available_metrics" :key="m.metric">
                <template v-for="cell in cellsOf(rowName, m.metric)" :key="cell.metric">
                  <div class="cell-value">
                    <strong>{{ cell.value === null ? '无可用值' : cell.value }}</strong>
                    <span class="cell-diff" :data-testid="`diff-${cell.row}-${cell.metric}`">差额 {{ cell.difference ?? '—' }}</span>
                  </div>
                  <div class="cell-sources">
                    来源：
                    <span v-if="cell.source_members.length">
                      <span v-for="(src, idx) in cell.source_members" :key="src.member_code">
                        {{ src.member_name }}({{ src.value }})<span v-if="idx < cell.source_members.length - 1">、</span>
                      </span>
                    </span>
                    <span v-else>无</span>
                  </div>
                  <div v-if="cell.missing_members.length" class="cell-missing">
                    缺失未计零：{{ cell.missing_members.join('、') }}
                  </div>
                </template>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td>合计</td>
              <td v-for="m in preview.available_metrics" :key="m.metric" :data-testid="`grand-${m.metric}`">
                {{ preview.grand_totals[m.metric] === null ? '无可用值' : preview.grand_totals[m.metric] }}
                <span class="muted-text">（有值 {{ preview.slice_totals[m.metric].present_count }} / 缺失 {{ preview.slice_totals[m.metric].missing_count }}）</span>
              </td>
            </tr>
          </tfoot>
        </table>

        <h4 class="section-title">一致性校验</h4>
        <ul class="check-list" data-testid="check-list">
          <li v-for="check in preview.consistency_checks" :key="check.code" :data-testid="`check-${check.code}`">
            <span :class="check.passed ? 'check-pass' : 'check-fail'">
              {{ check.passed ? '✓' : '✗' }} {{ check.label }}
            </span>
            <span class="muted-text">{{ check.detail }}</span>
          </li>
        </ul>
        <p :class="preview.all_checks_passed ? 'check-pass' : 'check-fail'" data-testid="check-summary">
          {{ preview.all_checks_passed ? '全部校验通过：各格与合计一致，成员范围隔离，缺失未按零累计' : '存在未通过的校验，请核对' }}
        </p>
      </div>
    </div>

    <!-- 两次读数对照弹窗 -->
    <div v-if="showCompare" class="modal-backdrop" data-testid="compare-modal">
      <div class="modal">
        <h3>对照两次读数：{{ selectedParent }}</h3>
        <div class="compare-form">
          <label class="create-field">
            <span>基准读数（早先）</span>
            <select v-model="compareBaseId" data-testid="compare-base">
              <option v-for="read in reads" :key="read.read_id" :value="read.read_id">
                #{{ read.read_id }} v{{ read.member_version }}（{{ read.member_count }} 成员）
              </option>
            </select>
          </label>
          <label class="create-field">
            <span>对照读数（后来）</span>
            <select v-model="compareTargetId" data-testid="compare-target">
              <option v-for="read in reads" :key="read.read_id" :value="read.read_id">
                #{{ read.read_id }} v{{ read.member_version }}（{{ read.member_count }} 成员）
              </option>
            </select>
          </label>
          <button type="button" class="btn primary" data-testid="submit-compare" :disabled="comparing" @click="submitCompare">
            {{ comparing ? '对照中…' : '生成对照' }}
          </button>
        </div>

        <div v-if="comparison" class="compare-result" data-testid="compare-result">
          <p class="muted-text">{{ comparison.explanation }}</p>
          <h4 class="section-title">新增成员</h4>
          <table v-if="comparison.added_members.length" class="data-table compact-table">
            <thead>
              <tr><th>成员编号</th><th>成员名称</th><th>类型</th><th>销售额</th><th>订单量</th></tr>
            </thead>
            <tbody>
              <tr v-for="member in comparison.added_members" :key="member.member_code" :data-testid="`added-${member.member_code}`">
                <td>{{ member.member_code }}</td>
                <td>{{ member.member_name }}</td>
                <td>{{ member.member_type }}</td>
                <td>{{ formatValue(member.metrics['销售额']) }}</td>
                <td>{{ formatValue(member.metrics['订单量']) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted-text">两次读取之间没有新增成员</p>

          <h4 class="section-title">度量差额（对照读数 − 基准读数）</h4>
          <table class="data-table compact-table">
            <thead>
              <tr><th>度量</th><th>基准读数</th><th>对照读数</th><th>差额</th></tr>
            </thead>
            <tbody>
              <tr v-for="(diff, metric) in comparison.metric_differences" :key="metric" :data-testid="`diff-row-${metric}`">
                <td>{{ metric }}</td>
                <td>{{ formatValue(diff.base_value) }}</td>
                <td>{{ formatValue(diff.target_value) }}</td>
                <td>{{ formatValue(diff.difference) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="page-actions">
          <button type="button" class="btn" data-testid="close-compare" @click="closeCompare">返回下钻</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import WorkbenchView from '@/views/WorkbenchView.vue'
import {
  compareReads,
  fetchParents,
  fetchPreview,
  fetchReads,
  readDrillParent,
  registerMember,
} from '@/api/drill-preview'
import type {
  DrillRead,
  ParentInfo,
  PivotCell,
  PivotPreview,
  ReadComparison,
  ReadSummary,
  RegisterMemberForm,
} from '@/domain/drillPreview'

const tab = ref<'config' | 'preview'>('config')
const parents = ref<ParentInfo[]>([])
const selectedParent = ref('')
const reads = ref<ReadSummary[]>([])
const currentRead = ref<DrillRead | null>(null)
const preview = ref<PivotPreview | null>(null)
const comparison = ref<ReadComparison | null>(null)
const loading = ref(false)
const errorMessage = ref('')

const showRegister = ref(false)
const submitting = ref(false)
const registerError = ref('')
const registerForm = ref<RegisterMemberForm>({
  member_code: '',
  member_name: '',
  member_type: '门店',
  metrics: { 销售额: '', 订单量: '' },
})

const showCompare = ref(false)
const comparing = ref(false)
const compareBaseId = ref<number | null>(null)
const compareTargetId = ref<number | null>(null)

const metricNames = computed(() => {
  const first = parents.value[0]
  return first ? first.available_metrics.map((item) => item.metric) : ['销售额', '订单量']
})

const selectedParentInfo = computed(() =>
  parents.value.find((item) => item.parent === selectedParent.value) ?? null,
)

const currentReadStale = computed(() => {
  if (!currentRead.value || !selectedParentInfo.value) return false
  return currentRead.value.member_version_hash !== selectedParentInfo.value.member_version_hash
})

const gridRows = computed(() => {
  if (!preview.value) return []
  return [...new Set(preview.value.grid.map((cell: PivotCell) => cell.row))]
})

function formatValue(value: number | null | undefined): string {
  return value === null || value === undefined ? '缺失（不计零）' : String(value)
}

function cellsOf(rowName: string, metric: string): PivotCell[] {
  if (!preview.value) return []
  return preview.value.grid.filter((cell) => cell.row === rowName && cell.metric === metric)
}

async function switchToPreview() {
  tab.value = 'preview'
  if (!parents.value.length) {
    await loadParents()
  }
}

async function loadParents() {
  errorMessage.value = ''
  try {
    const data = await fetchParents()
    parents.value = data.parents
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '父级列表读取失败'
  }
}

async function selectParent(parent: string) {
  selectedParent.value = parent
  currentRead.value = null
  preview.value = null
  comparison.value = null
  errorMessage.value = ''
  try {
    const data = await fetchReads(parent)
    reads.value = data.reads
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读取历史加载失败'
    reads.value = []
  }
}

async function doRead() {
  if (!selectedParent.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const result = (await readDrillParent(selectedParent.value)) as DrillRead | { error: string }
    if ('error' in result) {
      errorMessage.value = result.error
      return
    }
    currentRead.value = result
    const [readData, parentData] = await Promise.all([
      fetchReads(selectedParent.value),
      fetchParents(),
    ])
    reads.value = readData.reads
    parents.value = parentData.parents
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下钻读取失败'
  } finally {
    loading.value = false
  }
}

function openRegister() {
  registerForm.value = {
    member_code: '',
    member_name: '',
    member_type: '门店',
    metrics: Object.fromEntries(metricNames.value.map((name) => [name, ''])),
  }
  registerError.value = ''
  showRegister.value = true
}

async function submitRegister() {
  if (!selectedParent.value) return
  submitting.value = true
  registerError.value = ''
  try {
    const result = await registerMember(selectedParent.value, registerForm.value)
    if (result.error) {
      registerError.value = result.error
      return
    }
    showRegister.value = false
    const [readData, parentData] = await Promise.all([
      fetchReads(selectedParent.value),
      fetchParents(),
    ])
    reads.value = readData.reads
    parents.value = parentData.parents
  } catch (error) {
    registerError.value = error instanceof Error ? error.message : '补录失败'
  } finally {
    submitting.value = false
  }
}

async function openPreview(readId: number) {
  errorMessage.value = ''
  try {
    const result = (await fetchPreview(readId)) as PivotPreview | { error: string }
    if ('error' in result) {
      errorMessage.value = result.error
      return
    }
    preview.value = result
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '透视预览加载失败'
  }
}

function openCompare() {
  comparison.value = null
  compareBaseId.value = reads.value.length ? reads.value[0].read_id : null
  compareTargetId.value = reads.value.length ? reads.value[reads.value.length - 1].read_id : null
  showCompare.value = true
}

function closeCompare() {
  showCompare.value = false
  comparison.value = null
}

async function submitCompare() {
  if (compareBaseId.value === null || compareTargetId.value === null) return
  comparing.value = true
  errorMessage.value = ''
  try {
    const result = (await compareReads(compareBaseId.value, compareTargetId.value)) as
      ReadComparison | { error: string }
    if ('error' in result) {
      errorMessage.value = result.error
      comparison.value = null
      return
    }
    comparison.value = result
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读数对照失败'
  } finally {
    comparing.value = false
  }
}
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.tab { border: 1px solid var(--border); background: #fff; border-radius: 6px 6px 0 0; padding: 8px 18px; cursor: pointer; font-size: 14px; }
.tab.active { background: var(--brand); color: #fff; border-color: var(--brand); }
.preview-layout { display: grid; grid-template-columns: 320px 1fr; gap: 12px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.panel-main { min-height: 320px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; }
.panel-title { margin: 4px 0 10px; font-size: 15px; }
.panel-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.parent-list, .read-list { list-style: none; padding: 0; margin: 0 0 16px; display: flex; flex-direction: column; gap: 8px; }
.parent-card { width: 100%; text-align: left; border: 1px solid var(--border); border-radius: 8px; background: #fafbfc; padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 4px; }
.parent-card.selected { border-color: var(--brand); background: #eff6ff; }
.parent-name { font-weight: 600; }
.parent-meta, .parent-version, .read-meta { font-size: 12px; color: var(--muted); }
.read-item { display: flex; justify-content: space-between; align-items: center; gap: 6px; border-bottom: 1px solid #f0f2f5; padding-bottom: 6px; }
.stale-tag { color: #b45309; font-style: normal; background: #fef3c7; border-radius: 4px; padding: 1px 6px; margin-left: 4px; }
.current-tag { color: #15803d; font-style: normal; background: #dcfce7; border-radius: 4px; padding: 1px 6px; margin-left: 4px; }
.missing-tag { color: #b42318; font-size: 12px; }
.muted-text { color: var(--muted); font-size: 12px; }
.metric-chip { display: inline-block; background: #f1f5f9; border-radius: 10px; padding: 2px 10px; margin: 2px 4px 2px 0; font-size: 12px; }
.read-summary .summary-line { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.member-table { margin: 8px 0; }
.modal-wide .modal { width: min(960px, 100%); }
.modal-head { display: flex; justify-content: space-between; align-items: center; }
.banner { border-radius: 8px; padding: 10px 12px; margin: 10px 0; font-size: 13px; }
.banner-warn { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
.banner-ok { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
.section-title { margin: 16px 0 8px; font-size: 14px; }
.compact-table th, .compact-table td { padding: 6px 8px; font-size: 12px; }
.cell-value { display: flex; gap: 8px; align-items: baseline; }
.cell-diff { color: var(--muted); font-size: 12px; }
.cell-sources, .cell-missing { font-size: 12px; color: var(--muted); margin-top: 2px; }
.cell-missing { color: #b42318; }
.check-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.check-pass { color: #15803d; }
.check-fail { color: #b42318; }
.compare-form { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.compare-form .create-field { flex: 1; min-width: 200px; }
.create-field select { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: #fff; }
.empty-state { padding: 24px; text-align: center; color: var(--muted); }
</style>
