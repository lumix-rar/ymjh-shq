"""优化求解器。"""

from .interface import Solver
from .brute_force import BruteForceSolver
from .greedy import GreedySolver

__all__ = ["Solver", "BruteForceSolver", "GreedySolver"]
