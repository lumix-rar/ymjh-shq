"""进程查找器测试。"""

import os

import pytest

from shq.scanner.process_finder import ProcessFinder, ProcessInfo, ProcessMatchRule


def test_list_processes_returns_current_process():
    finder = ProcessFinder()
    processes = finder.list_processes()
    pids = [p.pid for p in processes]
    assert os.getpid() in pids


def test_find_by_name_matches_python():
    """用当前 Python 进程验证名称匹配逻辑。"""
    rule = ProcessMatchRule(names=["python.exe"])
    finder = ProcessFinder(rule)
    result = finder.find()
    assert isinstance(result, ProcessInfo)
    assert result.name.lower() == "python.exe"


def test_find_multiple_returns_list():
    rule = ProcessMatchRule(names=["python.exe"])
    finder = ProcessFinder(rule)
    results = finder.find(multiple=True)
    assert isinstance(results, list)
    assert any(p.pid == os.getpid() for p in results)


def test_empty_rule_raises():
    finder = ProcessFinder(ProcessMatchRule())
    with pytest.raises(ValueError):
        finder.find()


def test_ymjh_finder_handles_running_or_not():
    """验证一梦江湖查找器能正常返回 ProcessInfo 或 None，不抛出异常。"""
    finder = ProcessFinder.for_ymjh()
    result = finder.find_ymjh()
    assert result is None or isinstance(result, ProcessInfo)


def test_find_prioritizes_name_match():
    """验证进程名匹配的优先级高于窗口标题匹配。"""
    # 构造一个 title 匹配但 name 不匹配，以及一个 name 匹配的假 ProcessInfo
    python_info = next(
        (p for p in ProcessFinder().list_processes() if p.pid == os.getpid()),
        None,
    )
    assert python_info is not None

    fake_edge = ProcessInfo(
        pid=99999,
        name="msedge.exe",
        exe_path="C:\\Program Files\\edge.exe",
        window_titles=["一梦江湖攻略"],
    )

    rule = ProcessMatchRule(
        names=[python_info.name],
        window_titles=["一梦江湖"],
    )
    finder = ProcessFinder(rule)

    # 手动构造匹配列表验证优先级排序
    priorities = []
    for info in [fake_edge, python_info]:
        from shq.scanner.process_finder import _match_priority
        priorities.append(_match_priority(info, rule))

    assert priorities[1] > priorities[0]  # python name match > edge title match
