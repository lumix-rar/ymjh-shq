"""shq.cli 命令分发单元测试。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from shq.cli import build_arg_parser, main


class TestCliDispatch(unittest.TestCase):
    def test_scan_all_owned_flag_exists(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--scan-all-owned", "--ocr-backend", "rapidocr"])
        self.assertTrue(args.scan_all_owned)
        self.assertEqual(args.ocr_backend, "rapidocr")

    def test_scan_wuku_flag_exists(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--scan-wuku", "--ocr-backend", "rapidocr"])
        self.assertTrue(args.scan_wuku)

    @patch("shq.cli.cmd_scan_all_owned")
    @patch("shq.cli.cmd_scan_wuku")
    def test_scan_all_owned_dispatched(self, mock_scan_wuku, mock_scan_all_owned):
        with patch("sys.argv", ["shq", "--scan-all-owned", "--ocr-backend", "rapidocr"]):
            main()
        mock_scan_all_owned.assert_called_once()
        mock_scan_wuku.assert_not_called()

    @patch("shq.cli.cmd_scan_all_owned")
    @patch("shq.cli.cmd_scan_wuku")
    def test_scan_wuku_dispatched(self, mock_scan_wuku, mock_scan_all_owned):
        with patch("sys.argv", ["shq", "--scan-wuku", "--ocr-backend", "rapidocr"]):
            main()
        mock_scan_wuku.assert_called_once()
        mock_scan_all_owned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
