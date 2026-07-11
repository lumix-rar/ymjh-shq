"""TopologyLoader 单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from shq.models import Lingjian, SlotPosition
from shq.scanner.topology_loader import (
    RegionCalibration,
    SlotCalibration,
    Topology,
    TopologyLoader,
)
from shq.scanner.window_capture import ROI


class TestTopologyLoader(unittest.TestCase):
    def _sample_topology_dict(self):
        return {
            "regions": [
                {
                    "id": "yiji_meihua",
                    "name": "驿寄梅花",
                    "list_button": [120, 200],
                    "cultivation_button": [680, 680],
                    "panel_roi": {
                        "name": "yiji_panel",
                        "x": 400,
                        "y": 150,
                        "width": 540,
                        "height": 450,
                        "description": "",
                    },
                    "slots": [
                        {
                            "id": "yiji_s1",
                            "region_id": "yiji_meihua",
                            "number": 1,
                        }
                    ],
                },
                {
                    "id": "guanhe_daoyuan",
                    "name": "关河道远",
                    "list_button": None,
                    "cultivation_button": None,
                    "panel_roi": None,
                    "slots": [],
                },
            ]
        }

    def test_load_returns_lingjian_and_calibrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(json.dumps(self._sample_topology_dict(), ensure_ascii=False), encoding="utf-8")

            loader = TopologyLoader(path)
            topology = loader.load()

        self.assertIsInstance(topology, Topology)
        self.assertIsInstance(topology.lingjian, Lingjian)
        self.assertEqual(len(topology.lingjian.regions), 2)

        region = topology.lingjian.get_region("yiji_meihua")
        self.assertIsNotNone(region)
        self.assertEqual(region.name, "驿寄梅花")
        self.assertEqual(len(region.slots), 1)
        self.assertEqual(region.slots[0].position, SlotPosition.NORMAL)

    def test_load_calibration_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(json.dumps(self._sample_topology_dict(), ensure_ascii=False), encoding="utf-8")

            topology = TopologyLoader(path).load()

        rc = topology.get_region_calibration("yiji_meihua")
        self.assertIsInstance(rc, RegionCalibration)
        self.assertEqual(rc.list_button, (120, 200))
        self.assertEqual(rc.cultivation_button, (680, 680))
        self.assertIsInstance(rc.panel_roi, ROI)
        self.assertEqual(rc.panel_roi.x, 400)

        sc = topology.get_slot_calibration("yiji_meihua", "yiji_s1")
        self.assertIsInstance(sc, SlotCalibration)
        self.assertEqual(sc.number, 1)

    def test_load_missing_calibration_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(json.dumps(self._sample_topology_dict(), ensure_ascii=False), encoding="utf-8")

            topology = TopologyLoader(path).load()

        rc = topology.get_region_calibration("guanhe_daoyuan")
        self.assertIsNone(rc.list_button)
        self.assertIsNone(rc.panel_roi)
        self.assertEqual(rc.slots, [])

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(json.dumps(self._sample_topology_dict(), ensure_ascii=False), encoding="utf-8")

            loader = TopologyLoader(path)
            topology = loader.load()
            out_path = Path(tmp) / "topology_out.json"
            loader.save(topology, out_path)

            reloaded = TopologyLoader(out_path).load()

        self.assertEqual(reloaded.lingjian.regions[0].name, "驿寄梅花")
        rc = reloaded.get_region_calibration("yiji_meihua")
        self.assertEqual(rc.list_button, (120, 200))
        self.assertEqual(rc.panel_roi.width, 540)
        sc = reloaded.get_slot_calibration("yiji_meihua", "yiji_s1")
        self.assertEqual(sc.number, 1)


if __name__ == "__main__":
    unittest.main()
