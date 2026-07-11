"""ShanheqiNameResolver 单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from shq.scanner.name_resolver import ShanheqiNameResolver, _name_score


class TestNameResolver(unittest.TestCase):
    def setUp(self):
        self.master = {
            "version": "1.0",
            "qualities": {
                "朴素": ["缤铁雪花", "螭尾凤头", "竹节锏", "恶来双戟"],
                "精巧": ["吟秋扇", "烟烬斧"],
                "瑰丽": ["恶来双戟", "落晖扇"],
                "绝世": {
                    "普通": ["摇光环"],
                    "卓异": ["镂月扇"],
                    "玄枢": ["空山寂"],
                },
            },
        }
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        json.dump(self.master, self.tmp)
        self.tmp.close()
        self.resolver = ShanheqiNameResolver(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_exact_match(self):
        name, quality, sub_tag = self.resolver.resolve("缤铁雪花", "朴素")
        self.assertEqual(name, "缤铁雪花")
        self.assertEqual(quality, "朴素")
        self.assertIsNone(sub_tag)

    def test_known_alias(self):
        # 铁雪花 应通过别名表直接映射为 缤铁雪花
        name, quality, sub_tag = self.resolver.resolve("铁雪花", "朴素")
        self.assertEqual(name, "缤铁雪花")
        self.assertEqual(quality, "朴素")

    def test_fuzzy_resolution(self):
        # 尾凤头 -> 螭尾凤头
        name, quality, sub_tag = self.resolver.resolve("尾凤头", "朴素")
        self.assertEqual(name, "螭尾凤头")
        self.assertEqual(quality, "朴素")

    def test_quality_scoped_matching(self):
        # 恶来双戟 同时存在于 朴素 和 瑰丽，必须按 expected_quality 区分
        name_simple, quality_simple, _ = self.resolver.resolve("恶来双戟", "朴素")
        self.assertEqual(quality_simple, "朴素")

        name_magnificent, quality_magnificent, _ = self.resolver.resolve("恶来双戟", "瑰丽")
        self.assertEqual(quality_magnificent, "瑰丽")

    def test_peerless_sub_tag(self):
        name, quality, sub_tag = self.resolver.resolve("空山寂", "绝世")
        self.assertEqual(quality, "绝世")
        self.assertEqual(sub_tag, "玄枢")

    def test_unresolved_below_threshold(self):
        # 随机字符串不应匹配任何名字
        name, quality, sub_tag = self.resolver.resolve("完全不相关", "朴素")
        self.assertEqual(name, "完全不相关")
        self.assertIsNone(quality)
        self.assertIsNone(sub_tag)

    def test_name_score_hybrid(self):
        # 相同字符串满分
        self.assertEqual(_name_score("缤铁雪花", "缤铁雪花"), 1.0)
        # 丢字应仍有较高分
        self.assertGreater(_name_score("铁雪花", "缤铁雪花"), 0.5)
        # 完全不同的字符串分数应很低
        self.assertLess(_name_score("abc", " xyz "), 0.3)


if __name__ == "__main__":
    unittest.main()
