"""下钻分析领域服务：设计从汇总到明细的多层次下钻分析路径和联动规则。

跨模块数据流: dimension_model -> drill_down -> pivot_table -> report_template
下钻路径基于维度模型构建，结果可导出到透视表和报告模板。

本服务额外承载「下钻透视预览」能力：
- 下钻读取会把父级当前成员主数据固化为不可变快照（含成员版本号与版本指纹）；
- 透视切片只聚合该快照内的成员，父级以外的成员不会混入，缺失度量不按零累计；
- 透视表配置基于切片数据计算各格值，并给出每个格的来源成员和差额校验；
- 两次读取之间若补录了成员，版本指纹会变化，预览可辨明本次格值是否包含新成员。
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any

from app.store import store
from app.services.base import BaseModuleService

# 本次统计可用的度量及其聚合方式
DRILL_METRICS: dict[str, str] = {
    "销售额": "SUM",
    "订单量": "SUM",
}

# 种子成员主数据：父级 -> 成员列表。
# 「华北大区」初始只有两家门店，用于演示补录第三家后的读数对照。
_SEED_PARENTS: dict[str, list[dict[str, Any]]] = {
    "华东大区": [
        {"member_code": "S001", "member_name": "华东旗舰店", "member_type": "门店",
         "metrics": {"销售额": 1200.0, "订单量": 80.0}},
        {"member_code": "S002", "member_name": "华东社区店", "member_type": "门店",
         "metrics": {"销售额": 700.0, "订单量": 45.0}},
        {"member_code": "C001", "member_name": "华东直营渠道", "member_type": "渠道",
         "metrics": {"销售额": 500.0, "订单量": 30.0}},
    ],
    "华北大区": [
        {"member_code": "S101", "member_name": "北京中心店", "member_type": "门店",
         "metrics": {"销售额": 980.0, "订单量": 60.0}},
        {"member_code": "S102", "member_name": "天津滨海店", "member_type": "门店",
         "metrics": {"销售额": 620.0, "订单量": None}},
    ],
}


class DrillDownService(BaseModuleService):
    MODULE = "drill_down"
    ENTITY = "下钻路径"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["路径名称", "起始指标", "下钻维度序列", "跳转规则", "默认展示"]
    REQUIRED_FIELDS = ["路径名称", "起始指标", "下钻维度序列"]
    STATUS_ORDER = ["待生效", "已生效", "已停用"]
    ACTION_RULES = {"启用路径": "已生效", "停用路径": "已停用"}
    NEGATIVE_ACTIONS = ["停用路径"]

    # ── 成员主数据与成员版本 ──

    def _ensure_seed(self) -> None:
        """惰性写入下钻成员主数据，保证服务拿来即用且不依赖路由启动顺序。"""
        if store.drill_seeded:
            return
        with store.lock:
            if store.drill_seeded:
                return
            for parent, members in _SEED_PARENTS.items():
                store.drill_upsert_members(parent, members)
                store._drill_version_seq[parent] = 1
            store.drill_seeded = True

    @staticmethod
    def _member_version_hash(members: list[dict[str, Any]]) -> str:
        """成员版本指纹：成员编号、类型和度量值完全一致才是同一版本。

        缺失度量（None）与数值 0 是不同的状态，序列化时保留 None，避免误判。
        """
        canonical = [
            {
                "member_code": m.get("member_code"),
                "member_type": m.get("member_type"),
                "metrics": {
                    metric: m.get("metrics", {}).get(metric) for metric in DRILL_METRICS
                },
            }
            for m in sorted(members, key=lambda item: str(item.get("member_code", "")))
        ]
        payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]

    def list_drill_parents(self) -> dict[str, Any]:
        """列出可下钻父级及其当前成员范围和成员版本。"""
        self._ensure_seed()
        parents = []
        for parent in store.drill_parent_names():
            members = store.drill_members(parent) or []
            parents.append({
                "parent": parent,
                "member_version": store.drill_version_seq(parent),
                "member_version_hash": self._member_version_hash(members),
                "member_count": len(members),
                "store_count": sum(1 for m in members if m.get("member_type") == "门店"),
                "channel_count": sum(1 for m in members if m.get("member_type") == "渠道"),
                "available_metrics": [
                    {"metric": metric, "aggregation": agg}
                    for metric, agg in DRILL_METRICS.items()
                ],
            })
        return {"parents": parents, "metrics": dict(DRILL_METRICS)}

    def read_drill_parent(self, parent: str) -> dict[str, Any]:
        """下钻读取：把父级当前成员固化为一次不可变快照。

        同一父级后续补录成员不会改变已有快照，报表人员可以反复核对同一次读数。
        """
        self._ensure_seed()
        members = store.drill_members(parent)
        if members is None:
            return {"error": f"下钻父级「{parent}」不存在"}

        read_id = store.drill_next_read_id()
        snapshot_members = copy.deepcopy(members)
        version = store.drill_version_seq(parent)
        version_hash = self._member_version_hash(snapshot_members)
        snapshot = {
            "read_id": read_id,
            "parent": parent,
            "read_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "member_version": version,
            "member_version_hash": version_hash,
            "members": snapshot_members,
            "metric_defs": dict(DRILL_METRICS),
        }
        store.drill_save_snapshot(parent, snapshot)
        return {
            **snapshot,
            "current_member_version": version,
            "stale": False,
            "member_count": len(snapshot_members),
        }

    def register_member(
        self,
        parent: str,
        member_code: str,
        member_name: str,
        member_type: str,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """补录成员：追加到父级成员主数据并使成员版本递增。

        历史读取快照保持不变；再次下钻同一父级时会得到新版本的快照。
        """
        self._ensure_seed()
        existing = store.drill_members(parent)
        if existing is None:
            return {"error": f"下钻父级「{parent}」不存在"}
        if any(m.get("member_code") == member_code for m in existing):
            return {"error": f"成员编号「{member_code}」已存在，不能重复补录"}
        if member_type not in ("门店", "渠道"):
            return {"error": "成员类型只能是「门店」或「渠道」"}

        clean_metrics: dict[str, float | None] = {}
        for metric in DRILL_METRICS:
            raw = (metrics or {}).get(metric)
            if raw is None or str(raw).strip() == "":
                clean_metrics[metric] = None
                continue
            try:
                clean_metrics[metric] = float(raw)
            except (TypeError, ValueError):
                return {"error": f"度量「{metric}」的值「{raw}」不是有效数值"}

        member = {
            "member_code": member_code,
            "member_name": member_name,
            "member_type": member_type,
            "metrics": clean_metrics,
        }
        stored = store.drill_append_member(parent, member)
        current = store.drill_members(parent) or []
        return {
            "ok": True,
            "parent": parent,
            "member": stored,
            "member_version": store.drill_version_seq(parent),
            "member_version_hash": self._member_version_hash(current),
            "member_count": len(current),
            "message": f"父级「{parent}」已补录成员 {member_code}，成员版本递增",
        }

    # ── 透视切片与透视预览 ──

    @staticmethod
    def _slice_totals(members: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """按度量聚合切片成员；缺失值跳过，绝不按零累计。"""
        totals: dict[str, dict[str, Any]] = {}
        for metric, agg in DRILL_METRICS.items():
            present = [
                float(m["metrics"][metric])
                for m in members
                if m.get("metrics", {}).get(metric) is not None
            ]
            missing = [
                m["member_code"]
                for m in members
                if m.get("metrics", {}).get(metric) is None
            ]
            totals[metric] = {
                "aggregation": agg,
                "value": sum(present) if present else None,
                "present_count": len(present),
                "missing_count": len(missing),
                "missing_members": missing,
            }
        return totals

    def build_pivot_slice(self, read_id: int) -> dict[str, Any]:
        """聚合某次下钻读取的明细，生成透视切片数据。

        切片只包含该次读取快照里的成员，父级以外或之后补录的成员都不会混入。
        """
        self._ensure_seed()
        snapshot = store.drill_find_snapshot(read_id)
        if snapshot is None:
            return {"error": f"下钻读取 {read_id} 不存在，无法生成透视切片"}

        parent = snapshot["parent"]
        members = copy.deepcopy(snapshot["members"])
        current_members = store.drill_members(parent) or []
        current_hash = self._member_version_hash(current_members)
        current_version = store.drill_version_seq(parent)
        stale = snapshot["member_version_hash"] != current_hash

        totals = self._slice_totals(members)
        return {
            "read_id": read_id,
            "parent": parent,
            "read_at": snapshot["read_at"],
            "member_version": snapshot["member_version"],
            "member_version_hash": snapshot["member_version_hash"],
            "current_member_version": current_version,
            "current_member_version_hash": current_hash,
            "stale": stale,
            "stale_reason": (
                f"该读数采用成员版本 v{snapshot['member_version']}，"
                f"父级当前已到 v{current_version}，期间有成员补录"
                if stale else "该读数与父级当前成员版本一致"
            ),
            "member_scope": [
                {
                    "member_code": m["member_code"],
                    "member_name": m["member_name"],
                    "member_type": m["member_type"],
                    "metrics": m["metrics"],
                }
                for m in members
            ],
            "member_count": len(members),
            "available_metrics": [
                {"metric": metric, "aggregation": agg}
                for metric, agg in DRILL_METRICS.items()
            ],
            "totals": totals,
        }

    def preview_pivot(self, read_id: int) -> dict[str, Any]:
        """透视表配置根据透视切片数据计算各格值，并展示来源和差额。"""
        slice_data = self.build_pivot_slice(read_id)
        if "error" in slice_data:
            return slice_data

        members = slice_data["member_scope"]
        # 行维度固定为成员（按门店/渠道分组），列维度为本次统计可用的度量
        member_types = sorted({m["member_type"] for m in members})
        grid: list[dict[str, Any]] = []
        grouped_totals: dict[str, dict[str, Any]] = {}
        for member_type in member_types:
            grouped_totals[member_type] = {}
            type_members = [m for m in members if m["member_type"] == member_type]
            for metric in DRILL_METRICS:
                contributing = [
                    m for m in type_members if m["metrics"].get(metric) is not None
                ]
                value = (
                    sum(float(m["metrics"][metric]) for m in contributing)
                    if contributing else None
                )
                cell = {
                    "row": member_type,
                    "metric": metric,
                    "value": value,
                    "aggregation": DRILL_METRICS[metric],
                    "present_count": len(contributing),
                    "missing_count": len(type_members) - len(contributing),
                    "missing_members": [
                        m["member_code"]
                        for m in type_members if m["metrics"].get(metric) is None
                    ],
                    "source_members": [
                        {"member_code": m["member_code"], "member_name": m["member_name"],
                         "value": m["metrics"][metric]}
                        for m in contributing
                    ],
                }
                # 差额：格值重算结果与切片同口径合计之差；正常应为 0
                slice_total = slice_data["totals"][metric]["value"]
                if value is None:
                    cell["difference"] = None
                elif slice_total is None:
                    cell["difference"] = value
                else:
                    cell["difference"] = round(value - self._group_total(members, member_type, metric), 8)
                grid.append(cell)
                grouped_totals[member_type][metric] = value

        grand_totals: dict[str, Any] = {}
        for metric in DRILL_METRICS:
            grand_totals[metric] = slice_data["totals"][metric]["value"]

        # 一致性校验：各格与合计必须一致；父级以外成员不得混入；缺失不得按零累计
        checks = self._consistency_checks(slice_data, grid, grand_totals)
        return {
            "read_id": read_id,
            "parent": slice_data["parent"],
            "config_name": f"{slice_data['parent']}_下钻透视预览",
            "row_dimension": "成员类型",
            "column_dimension": "度量",
            "aggregation": dict(DRILL_METRICS),
            "member_version": slice_data["member_version"],
            "member_version_hash": slice_data["member_version_hash"],
            "current_member_version": slice_data["current_member_version"],
            "stale": slice_data["stale"],
            "stale_reason": slice_data["stale_reason"],
            "member_scope": members,
            "available_metrics": slice_data["available_metrics"],
            "grid": grid,
            "grouped_totals": grouped_totals,
            "grand_totals": grand_totals,
            "slice_totals": slice_data["totals"],
            "consistency_checks": checks,
            "all_checks_passed": all(item["passed"] for item in checks),
        }

    @staticmethod
    def _group_total(members: list[dict[str, Any]], member_type: str, metric: str) -> float:
        return sum(
            float(m["metrics"][metric])
            for m in members
            if m["member_type"] == member_type and m["metrics"].get(metric) is not None
        )

    def _consistency_checks(
        self,
        slice_data: dict[str, Any],
        grid: list[dict[str, Any]],
        grand_totals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        # 1. 分组格值之和等于切片合计（缺失值两边都跳过）
        for metric in DRILL_METRICS:
            cell_sum_parts = [
                cell["value"] for cell in grid
                if cell["metric"] == metric and cell["value"] is not None
            ]
            cell_sum = sum(cell_sum_parts) if cell_sum_parts else None
            slice_total = slice_data["totals"][metric]["value"]
            if cell_sum is None and slice_total is None:
                passed, detail = True, "格值与切片合计均无可用数值"
            elif cell_sum is None or slice_total is None:
                passed, detail = False, "格值与切片合计一边缺失一边有值，口径不一致"
            else:
                passed = abs(cell_sum - slice_total) < 1e-8
                detail = f"格值之和 {cell_sum} 与切片合计 {slice_total} 一致"
            checks.append({
                "code": f"cell_total_match_{metric}",
                "label": f"{metric}各格与合计一致",
                "passed": passed,
                "detail": detail,
            })

        # 2. 每个格的差额必须为 0（或因全缺失而无差额）
        bad_cells = [
            f"{cell['row']}/{cell['metric']}"
            for cell in grid
            if cell["difference"] is not None and abs(cell["difference"]) > 1e-8
        ]
        checks.append({
            "code": "cell_difference_zero",
            "label": "各格差额为零",
            "passed": not bad_cells,
            "detail": "全部格值差额为 0" if not bad_cells else f"差额异常格：{'、'.join(bad_cells)}",
        })

        # 3. 透视成员范围与切片快照完全一致，父级以外成员不得混入
        scope_codes = sorted(m["member_code"] for m in slice_data["member_scope"])
        grid_codes = sorted({
            s["member_code"]
            for cell in grid for s in cell["source_members"]
        } | {code for cell in grid for code in cell["missing_members"]})
        checks.append({
            "code": "member_scope_isolation",
            "label": "仅包含本次读取父级成员",
            "passed": scope_codes == grid_codes,
            "detail": f"成员范围 {len(scope_codes)} 个，与读取快照完全一致",
        })

        # 4. 缺失度量没有被按零累计
        bad_missing = []
        for metric in DRILL_METRICS:
            stat = slice_data["totals"][metric]
            if stat["missing_count"] and stat["present_count"]:
                recomputed = sum(
                    float(m["metrics"][metric])
                    for m in slice_data["member_scope"]
                    if m["metrics"].get(metric) is not None
                )
                if abs(recomputed - stat["value"]) > 1e-8:
                    bad_missing.append(metric)
        checks.append({
            "code": "missing_not_zero_filled",
            "label": "缺失数值不按零累计",
            "passed": not bad_missing,
            "detail": "缺失成员已单列，合计仅累加有值成员"
                      if not bad_missing else f"缺失被错误计入：{'、'.join(bad_missing)}",
        })

        # 5. 总计等于各分组之和
        for metric in DRILL_METRICS:
            parts = [
                cell["value"] for cell in grid
                if cell["metric"] == metric and cell["value"] is not None
            ]
            total = sum(parts) if parts else None
            grand = grand_totals[metric]
            if total is None and grand is None:
                passed, detail = True, "无可用数值，总计留空"
            elif total is None or grand is None:
                passed, detail = False, "总计与分组可用值状态不一致"
            else:
                passed = abs(total - grand) < 1e-8
                detail = f"总计 {grand} 等于各分组之和 {total}"
            checks.append({
                "code": f"grand_total_match_{metric}",
                "label": f"{metric}总计与分组一致",
                "passed": passed,
                "detail": detail,
            })
        return checks

    def compare_reads(self, base_read_id: int, target_read_id: int) -> dict[str, Any]:
        """对照同一父级的两次读取，说明补录成员导致的读数差异。"""
        self._ensure_seed()
        base = store.drill_find_snapshot(base_read_id)
        target = store.drill_find_snapshot(target_read_id)
        if base is None:
            return {"error": f"基准读取 {base_read_id} 不存在"}
        if target is None:
            return {"error": f"对照读取 {target_read_id} 不存在"}
        if base["parent"] != target["parent"]:
            return {"error": "两次读取不属于同一父级，无法对照"}

        base_codes = {m["member_code"] for m in base["members"]}
        target_codes = {m["member_code"] for m in target["members"]}
        added = sorted(target_codes - base_codes)
        removed = sorted(base_codes - target_codes)

        metric_diffs = {}
        for metric in DRILL_METRICS:
            base_total = self._slice_totals(base["members"])[metric]["value"]
            target_total = self._slice_totals(target["members"])[metric]["value"]
            if base_total is None and target_total is None:
                diff = None
            else:
                diff = (target_total or 0.0) - (base_total or 0.0)
            metric_diffs[metric] = {
                "base_value": base_total,
                "target_value": target_total,
                "difference": diff,
            }

        added_details = [
            m for m in target["members"] if m["member_code"] in added
        ]
        return {
            "parent": base["parent"],
            "base_read": {
                "read_id": base_read_id,
                "read_at": base["read_at"],
                "member_version": base["member_version"],
                "member_version_hash": base["member_version_hash"],
                "member_count": len(base["members"]),
            },
            "target_read": {
                "read_id": target_read_id,
                "read_at": target["read_at"],
                "member_version": target["member_version"],
                "member_version_hash": target["member_version_hash"],
                "member_count": len(target["members"]),
            },
            "added_members": added_details,
            "removed_members": removed,
            "metric_differences": metric_diffs,
            "explanation": (
                f"两次读取成员版本由 v{base['member_version']} 变为 v{target['member_version']}，"
                f"新增成员 {len(added)} 个（{('、'.join(added)) or '无'}），"
                "新读数的格值包含新成员，旧读数快照保持不变"
            ),
        }

    def list_reads(self, parent: str) -> dict[str, Any]:
        """列出同一父级的全部历史读取及其成员版本，便于回到下钻继续核对。"""
        self._ensure_seed()
        if store.drill_members(parent) is None:
            return {"error": f"下钻父级「{parent}」不存在"}
        current_hash = self._member_version_hash(store.drill_members(parent) or [])
        reads = []
        for snapshot in store.drill_list_snapshots(parent):
            reads.append({
                "read_id": snapshot["read_id"],
                "read_at": snapshot["read_at"],
                "member_version": snapshot["member_version"],
                "member_version_hash": snapshot["member_version_hash"],
                "member_count": len(snapshot["members"]),
                "stale": snapshot["member_version_hash"] != current_hash,
            })
        return {
            "parent": parent,
            "current_member_version": store.drill_version_seq(parent),
            "reads": reads,
        }

    # ── 既有下钻路径能力（保持兼容） ──

    def execute_drill_down(self, entry_id: int, current_level: int = 0) -> dict[str, Any] | None:
        """执行下钻分析，从当前层级钻取到下一级明细。

        跨模块数据流: drill_down -> dimension_model（获取维度结构）
                     drill_down -> pivot_table（透视汇总结果）
        """
        path = store.find(self.MODULE, entry_id)
        if path is None:
            return {"error": f"下钻路径 {entry_id} 不存在"}
        if path["status"] != "已生效":
            return {"error": f"下钻路径 {entry_id} 未生效"}

        metric_name = path.get("起始指标", "")
        dimension_seq = [d.strip() for d in path.get("下钻维度序列", "").split(",") if d.strip()]

        if current_level >= len(dimension_seq):
            return {"error": "已达到最细粒度，无法继续下钻"}

        current_dimension = dimension_seq[current_level]

        # 查找关联的维度模型获取上下文
        dim_models = store.find_by_field("dimension_model", "模型名称", metric_name)
        model_dimensions = []
        if dim_models:
            model_dimensions = [
                d.strip() for d in dim_models[0].get("维度列表", "").split(",") if d.strip()
            ]

        # 模拟下钻结果
        drill_result = {
            "path_name": path.get("路径名称"),
            "current_level": current_level + 1,
            "dimension": current_dimension,
            "total_levels": len(dimension_seq),
            "next_dimension": dimension_seq[current_level + 1] if current_level + 1 < len(dimension_seq) else None,
            "model_dimensions": model_dimensions,
            "jump_rule": path.get("跳转规则", ""),
            "rows": [
                {"dimension_value": f"{current_dimension}_值{i+1}",
                 "metric_value": 100 * (i + 1) * (current_level + 1),
                 "can_drill_further": current_level + 1 < len(dimension_seq)}
                for i in range(5)
            ],
        }
        return drill_result

    def get_drill_tree(self, entry_id: int) -> dict[str, Any] | None:
        """构建下钻路径的完整树状结构。"""
        path = store.find(self.MODULE, entry_id)
        if path is None:
            return None

        dimension_seq = [d.strip() for d in path.get("下钻维度序列", "").split(",") if d.strip()]

        nodes = []
        for i, dim in enumerate(dimension_seq):
            nodes.append({
                "level": i + 1,
                "dimension": dim,
                "has_children": i + 1 < len(dimension_seq),
                "children_dimension": dimension_seq[i + 1] if i + 1 < len(dimension_seq) else None,
            })

        return {
            "path_id": entry_id,
            "path_name": path.get("路径名称"),
            "metric": path.get("起始指标"),
            "node_count": len(nodes),
            "tree": nodes,
        }

    def export_to_pivot(self, entry_id: int) -> dict[str, Any] | None:
        """将下钻路径的维度结构导出为透视表配置推荐。

        跨模块数据流: drill_down -> pivot_table
        """
        path = store.find(self.MODULE, entry_id)
        if path is None:
            return None

        dimension_seq = [d.strip() for d in path.get("下钻维度序列", "").split(",") if d.strip()]

        if len(dimension_seq) < 2:
            return {"error": "下钻路径维度少于两个，无法生成透视配置"}

        pivot_suggestion = {
            "source_path": path.get("路径名称"),
            "metric": path.get("起始指标"),
            "row_dimension": dimension_seq[0] if dimension_seq else "",
            "column_dimension": dimension_seq[1] if len(dimension_seq) > 1 else "",
            "aggregation_method": "SUM",
            "suggested_name": f"{path.get('路径名称')}_透视",
        }
        return pivot_suggestion
