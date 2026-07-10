"""数据采集扫描器。"""

from .input_simulator import InputSimulator
from .interface import Scanner
from .manual_importer import ManualImporter
from .navigation_controller import NavigationController, auto_navigate_to_wuku
from .ocr_scanner import EasyOCRBackend, OCRBackend, PlaceholderOCRBackend, RapidOCRBackend, ShanheqiOCR
from .process_finder import ProcessFinder, ProcessInfo, ProcessMatchRule
from .window_capture import WindowCapture, capture_game_window

__all__ = [
    "Scanner",
    "ManualImporter",
    "ShanheqiOCR",
    "OCRBackend",
    "EasyOCRBackend",
    "RapidOCRBackend",
    "PlaceholderOCRBackend",
    "WindowCapture",
    "capture_game_window",
    "InputSimulator",
    "NavigationController",
    "auto_navigate_to_wuku",
    "ProcessFinder",
    "ProcessInfo",
    "ProcessMatchRule",
]
