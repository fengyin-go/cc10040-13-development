"""下钻透视预览行为测试。

验收主线：
打开只有两家门店的父级 → 下钻读取并看预览（核对切片成员与合计）
→ 预览前补录第三家门店 → 旧读数预览明确提示不包含新成员
→ 返回下钻重新打开父级 → 对照两次读数，解释差额来自新成员。

每个用例通过 store 自建独立父级，避免共享内存仓库的补录状态互相污染。
"""
from __future__ import annotations

import pytest

from app.services.drill_down import DRILL_METRICS, DrillDownService
from app.store import store


def _make_parent(name: str, members: list[dict]) -> str:
    """在成员主数据中登记一个测试专用父级。"""
    store.drill_upsert_members(name, members)
    store._drill_version_seq[name] = 1
    return name


def _member(code: str, name: str, mtype: str, sales: float | None,
            orders: float | None) -> dict:
    return {
        "member_code": code, "member_name": name, "member_type": mtype,
        "metrics": {"销售额": sales, "订单量": orders},
    }


@pytest.fixture()
def svc() -> DrillDownService:
    service = DrillDownService()
    service._ensure_seed()
    return service


@pytest.fixture()
def two_store_parent() -> str:
    """只有两家门店的父级，其中一家订单量缺失。"""
    name = "测试大区_两店"
    _make_parent(name, [
        _member("T001", "测试中心店", "门店", 980.0, 60.0),
        _member("T002", "测试滨海店", "门店", 620.0, None),
    ])
    return name


class TestDrillMemberVersion:
    """成员主数据与成员版本。"""

    def test_seed_parents_list_member_scope_and_metrics(self, svc: DrillDownService):
        result = svc.list_drill_parents()
        parents = {item["parent"]: item for item in result["parents"]}
        north = parents["华北大区"]
        # 种子父级初始只有两家门店
        assert north["member_count"] == 2
        assert north["store_count"] == 2
        assert north["member_version"] >= 1
        assert len(north["member_version_hash"]) == 10
        # 预览需列出本次统计可用的成员范围和度量
        assert {m["metric"] for m in north["available_metrics"]} == set(DRILL_METRICS)

    def test_read_snapshot_is_immutable_after_register(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        first = svc.read_drill_parent(two_store_parent)
        assert first["member_count"] == 2
        first_hash = first["member_version_hash"]
        first_version = first["member_version"]

        registered = svc.register_member(
            two_store_parent, "T003", "测试新店", "门店",
            metrics={"销售额": 300, "订单量": 12},
        )
        assert registered["ok"] is True
        assert registered["member_version"] == first_version + 1
        assert registered["member_version_hash"] != first_hash

        # 旧快照保持原版本、仍是两个成员
        frozen = store.drill_find_snapshot(first["read_id"])
        assert frozen["member_version"] == first_version
        assert len(frozen["members"]) == 2
        assert frozen["member_version_hash"] == first_hash

        # 读取本身不递增成员版本，只有补录才递增；新读取包含 3 个成员
        again = svc.read_drill_parent(two_store_parent)
        assert again["member_version"] == first_version + 1
        assert again["member_count"] == 3

    def test_register_rejects_duplicate_bad_type_and_bad_number(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        dup = svc.register_member(
            two_store_parent, "T001", "重复门店", "门店", metrics={"销售额": 1},
        )
        assert "error" in dup
        bad_type = svc.register_member(
            two_store_parent, "T999", "类型错误", "仓库", metrics={},
        )
        assert "error" in bad_type
        bad_number = svc.register_member(
            two_store_parent, "T998", "数值错误", "门店", metrics={"销售额": "abc"},
        )
        assert "error" in bad_number


class TestPivotSliceAndPreview:
    """透视切片聚合与透视预览。"""

    def test_slice_matches_snapshot_members_and_totals(self, svc: DrillDownService):
        parent = _make_parent("测试大区_切片", [
            _member("P001", "切片旗舰店", "门店", 1200.0, 80.0),
            _member("P002", "切片社区店", "门店", 700.0, 45.0),
            _member("P101", "切片直营渠道", "渠道", 500.0, 30.0),
        ])
        read = svc.read_drill_parent(parent)
        slice_data = svc.build_pivot_slice(read["read_id"])

        # 切片成员范围与快照一致，父级以外成员不混入
        assert slice_data["member_count"] == 3
        assert {m["member_code"] for m in slice_data["member_scope"]} == {
            "P001", "P002", "P101",
        }
        # 销售额合计 1200 + 700 + 500 = 2400；订单量 80 + 45 + 30 = 155
        assert slice_data["totals"]["销售额"]["value"] == 2400.0
        assert slice_data["totals"]["订单量"]["value"] == 155.0
        assert slice_data["stale"] is False

    def test_missing_metric_is_not_counted_as_zero(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        read = svc.read_drill_parent(two_store_parent)
        slice_data = svc.build_pivot_slice(read["read_id"])
        order_stat = slice_data["totals"]["订单量"]
        # 只累加 T001 的 60，T002 缺失不按 0 计
        assert order_stat["value"] == 60.0
        assert order_stat["missing_count"] == 1
        assert order_stat["missing_members"] == ["T002"]
        assert order_stat["present_count"] == 1

        preview = svc.preview_pivot(read["read_id"])
        missing_cell = next(
            cell for cell in preview["grid"]
            if cell["row"] == "门店" and cell["metric"] == "订单量"
        )
        assert missing_cell["value"] == 60.0
        assert missing_cell["missing_members"] == ["T002"]
        assert missing_cell["source_members"][0]["member_code"] == "T001"
        assert preview["all_checks_passed"] is True

    def test_preview_cells_show_sources_difference_and_checks(
        self, svc: DrillDownService,
    ):
        parent = _make_parent("测试大区_预览", [
            _member("V001", "预览旗舰店", "门店", 1200.0, 80.0),
            _member("V002", "预览社区店", "门店", 700.0, 45.0),
            _member("V101", "预览直营渠道", "渠道", 500.0, 30.0),
        ])
        read = svc.read_drill_parent(parent)
        preview = svc.preview_pivot(read["read_id"])

        store_cell = next(
            cell for cell in preview["grid"]
            if cell["row"] == "门店" and cell["metric"] == "销售额"
        )
        # 门店销售额 1200 + 700 = 1900，来源成员逐格可查，差额为 0
        assert store_cell["value"] == 1900.0
        assert {s["member_code"] for s in store_cell["source_members"]} == {"V001", "V002"}
        assert store_cell["difference"] == 0
        channel_cell = next(
            cell for cell in preview["grid"]
            if cell["row"] == "渠道" and cell["metric"] == "销售额"
        )
        assert channel_cell["value"] == 500.0

        # 各格与合计一致，总计等于分组之和
        assert preview["grand_totals"]["销售额"] == 2400.0
        assert preview["grand_totals"]["订单量"] == 155.0
        codes = {check["code"] for check in preview["consistency_checks"]}
        assert {
            "cell_total_match_销售额", "cell_total_match_订单量",
            "cell_difference_zero", "member_scope_isolation",
            "missing_not_zero_filled",
            "grand_total_match_销售额", "grand_total_match_订单量",
        } <= codes
        assert preview["all_checks_passed"] is True

    def test_stale_preview_flags_new_member_not_included(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        # 第一次读取：只有两家门店，销售额 980 + 620 = 1600
        first = svc.read_drill_parent(two_store_parent)
        first_slice = svc.build_pivot_slice(first["read_id"])
        assert first_slice["member_count"] == 2
        assert first_slice["totals"]["销售额"]["value"] == 1600.0

        # 预览前补录第三家门店
        svc.register_member(
            two_store_parent, "T003", "测试新店", "门店",
            metrics={"销售额": 300, "订单量": 12},
        )

        # 旧读数的切片与预览必须标明：本次格值不包含新成员
        stale_slice = svc.build_pivot_slice(first["read_id"])
        assert stale_slice["stale"] is True
        assert stale_slice["member_version"] == first["member_version"]
        assert stale_slice["current_member_version"] == first["member_version"] + 1
        assert stale_slice["member_count"] == 2
        assert "T003" not in {m["member_code"] for m in stale_slice["member_scope"]}
        assert "补录" in stale_slice["stale_reason"]
        assert stale_slice["totals"]["销售额"]["value"] == 1600.0

        stale_preview = svc.preview_pivot(first["read_id"])
        assert stale_preview["stale"] is True
        assert all(
            "T003" not in {s["member_code"] for s in cell["source_members"]}
            for cell in stale_preview["grid"]
        )
        # 旧读数自身的各格与合计仍然保持一致
        assert stale_preview["all_checks_passed"] is True
        assert stale_preview["grand_totals"]["销售额"] == 1600.0

    def test_reread_after_register_includes_new_member(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        first = svc.read_drill_parent(two_store_parent)
        svc.register_member(
            two_store_parent, "T004", "测试长风店", "门店",
            metrics={"销售额": 260, "订单量": 9},
        )
        second = svc.read_drill_parent(two_store_parent)
        assert second["member_count"] == 3
        assert second["member_version"] == first["member_version"] + 1

        second_preview = svc.preview_pivot(second["read_id"])
        assert second_preview["stale"] is False
        # 新格值包含补录门店：980 + 620 + 260 = 1860
        assert second_preview["grand_totals"]["销售额"] == 1860.0
        assert {m["member_code"] for m in second_preview["member_scope"]} == {
            "T001", "T002", "T004",
        }


class TestReadComparison:
    """两次读取对照与错误防护。"""

    def test_compare_two_reads_explains_difference(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        first = svc.read_drill_parent(two_store_parent)
        svc.register_member(
            two_store_parent, "T005", "测试呼和浩特店", "门店",
            metrics={"销售额": 410, "订单量": 18},
        )
        second = svc.read_drill_parent(two_store_parent)

        comparison = svc.compare_reads(first["read_id"], second["read_id"])
        assert comparison["parent"] == two_store_parent
        assert [m["member_code"] for m in comparison["added_members"]] == ["T005"]
        assert comparison["removed_members"] == []
        assert comparison["metric_differences"]["销售额"]["difference"] == 410.0
        # 旧读数订单量只有 T001 的 60（T002 缺失），新读数再加 18
        assert comparison["metric_differences"]["订单量"]["difference"] == 18.0
        explanation = comparison["explanation"]
        assert f"v{first['member_version']}" in explanation
        assert f"v{second['member_version']}" in explanation

        # 返回下钻后仍能列出同一父级的历史读取并核对版本
        reads = svc.list_reads(two_store_parent)
        assert reads["current_member_version"] == second["member_version"]
        history = reads["reads"]
        assert [r["read_id"] for r in history[-2:]] == [
            first["read_id"], second["read_id"],
        ]
        assert history[-2]["stale"] is True
        assert history[-1]["stale"] is False

    def test_compare_rejects_different_parents_and_missing_reads(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        other = _make_parent("测试大区_对照", [
            _member("O001", "对照门店", "门店", 100.0, 5.0),
        ])
        north = svc.read_drill_parent(two_store_parent)
        east = svc.read_drill_parent(other)
        cross = svc.compare_reads(north["read_id"], east["read_id"])
        assert "error" in cross
        missing = svc.compare_reads(north["read_id"], 999999)
        assert "error" in missing

    def test_unknown_parent_and_read_are_rejected(
        self, svc: DrillDownService, two_store_parent: str,
    ):
        assert "error" in svc.read_drill_parent("不存在的大区")
        assert "error" in svc.build_pivot_slice(999999)
        assert "error" in svc.preview_pivot(999999)
        assert "error" in svc.list_reads("不存在的大区")
        assert "error" in svc.register_member(
            "不存在的大区", "X1", "X", "门店", metrics={},
        )
