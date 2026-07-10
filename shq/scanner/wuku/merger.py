"""武库采集数据合并器。

将左卡 GridItem 与右侧面板 DetailData 合并为 shq.models.Shanheqi。
"""

from __future__ import annotations

from shq.models import Affix, AffixEffect, Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.wuku.detail_reader import DetailData
from shq.scanner.wuku.models import GridItem


class ShanheqiMerger:
    """合并左右两侧数据源。"""

    @staticmethod
    def merge(grid_item: GridItem, detail: DetailData) -> Shanheqi:
        """将 GridItem 与 DetailData 合并成 Shanheqi。

        合并规则：
        - 名称/元素/等级/主属性/评分/基础素蕴：以右侧面板为准
        - 派生素蕴：以左卡标签为准（如“起势”）
        - 特殊等级（玄枢/卓异）：以左卡右上角图标检测为准
        - 品质：当前右侧面板未直接显示，默认使用 SIMPLE，后续可补充颜色识别
        """
        element = _parse_element(detail.element)
        shq_type = _special_grade_to_type(grid_item.special_grade)
        quality = _infer_quality(grid_item, detail)

        affixes = [
            Affix(
                name=a.name,
                element=element,
                level=a.level,
                score=a.score,
                derived=False,
            )
            for a in detail.affixes
        ]

        # 派生素蕴
        if grid_item.derived_affix:
            affixes.append(
                Affix(
                    name=grid_item.derived_affix,
                    element=element,
                    level=1,
                    score=0.0,
                    derived=True,
                    effects=[AffixEffect(name=grid_item.derived_affix)],
                )
            )

        return Shanheqi(
            id=f"wuku_{grid_item.name}",
            name=detail.name or grid_item.name,
            quality=quality,
            element=element,
            shanheqi_type=shq_type,
            level=detail.level,
            gongguan_level=0,  # 武库右面板当前未显示共贯等级
            base_score=detail.score,
            affixes=affixes,
            stats=detail.main_stats,
        )


def _parse_element(text: str | None) -> Element:
    if not text:
        return Element.METAL
    mapping = {
        "金": Element.METAL,
        "木": Element.WOOD,
        "水": Element.WATER,
        "火": Element.FIRE,
        "土": Element.EARTH,
    }
    return mapping.get(text, Element.METAL)


def _special_grade_to_type(grade: str | None) -> ShanheqiType:
    if grade == "玄枢":
        return ShanheqiType.XUANSHU
    return ShanheqiType.NORMAL


def _infer_quality(grid_item: GridItem, detail: DetailData) -> Quality:
    """根据已有信息推断品质。

    当前右侧面板没有直接显示品质文字，因此默认返回 SIMPLE。
    TODO: 后续可根据 item 图标背景/边框颜色或评分区间进一步推断。
    """
    return Quality.SIMPLE
