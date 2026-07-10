"""输入模拟器测试。

注意：本模块涉及 SendInput 模拟鼠标/键盘，测试中仅验证坐标解析与结构体，
不实际触发输入事件。
"""

import pytest

from shq.scanner.input_simulator import InputSimulator


def test_parse_click_coord():
    """测试坐标字符串解析辅助函数（通过私有方法间接测试）。"""
    from shq.cli import _parse_click_coord

    assert _parse_click_coord("1200,400") == (1200, 400)
    assert _parse_click_coord(" 1200 , 400 ") == (1200, 400)


def test_parse_click_coord_invalid():
    from shq.cli import _parse_click_coord

    with pytest.raises(SystemExit):
        _parse_click_coord("1200")


def test_input_simulator_init():
    sim = InputSimulator(default_delay=0.3)
    assert sim.default_delay == 0.3


def test_diagnose_returns_dict():
    """diagnose 返回结构化结果，不触发真实输入也能通过结构校验。"""
    sim = InputSimulator(default_delay=0.05)
    result = sim.diagnose(timeout=0.05)
    assert isinstance(result, dict)
    assert "supported" in result
    assert "start_pos" in result
    assert "end_pos" in result
    if result["supported"]:
        assert result.get("reason") is None
    else:
        assert result.get("reason") is not None
