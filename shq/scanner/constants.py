"""扫描器常量与映射。

集中存放 UI 文本到模型枚举的映射，避免在扫描器逻辑里硬编码。
"""

from shq.models import Quality, ShanheqiType


QUALITY_NAME_TO_ENUM = {
    "朴素": Quality.SIMPLE,
    "精巧": Quality.EXQUISITE,
    "瑰丽": Quality.MAGNIFICENT,
    "绝世": Quality.PEERLESS,
}

SUB_TAG_TO_TYPE = {
    "普通": ShanheqiType.NORMAL,
    "卓异": ShanheqiType.ZHUOYI,
    "玄枢": ShanheqiType.XUANSHU,
}

TYPE_TO_SUB_TAG = {
    ShanheqiType.NORMAL: "普通",
    ShanheqiType.ZHUOYI: "卓异",
    ShanheqiType.XUANSHU: "玄枢",
}

VALID_QUALITIES = tuple(QUALITY_NAME_TO_ENUM.keys())
VALID_SUB_TAGS = tuple(SUB_TAG_TO_TYPE.keys())
