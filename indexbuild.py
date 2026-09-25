"""indexbuild.py：索引构建与切换（旁路构建 + 世代原子替换 + 回滚）。"""
from __future__ import annotations

import threading


class RollbackError(RuntimeError):
    """没有可回滚的上一世代索引。"""


class IndexStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._history = []  # [(generation, index), ...]，栈顶是当前世代的上一版
        self.current = {}
        self.generation = 0
        self.builds = 0
        self.queries = 0
        self.empty_during_build = 0

    @staticmethod
    def _build(docs) -> dict:
        """在旁路构建新索引，构建过程中完全不触碰 current。"""
        built = {}
        for name, text in docs.items():
            for term in set(text.split()):
                built.setdefault(term, set()).add(name)
        return {term: sorted(names) for term, names in built.items()}

    def search(self, term: str) -> list:
        with self._lock:
            self.queries += 1
            return list(self.current.get(term, []))

    def rebuild(self, docs) -> int:
        new_index = self._build(docs)
        with self._lock:
            self._history.append((self.generation, self.current))
            self.current = new_index
            self.generation += 1
            self.builds += 1
            return self.generation

    def rollback(self) -> int:
        with self._lock:
            if not self._history:
                raise RollbackError("没有可回滚的上一版索引")
            self.generation, self.current = self._history.pop()
            return self.generation
