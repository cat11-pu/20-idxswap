"""indexbuild.py：索引构建与切换（基线：删了再建，无世代、无回滚）。"""
from __future__ import annotations


class IndexStore:
    def __init__(self):
        self.current = {}
        self.generation = 0
        self.builds = 0
        self.queries = 0
        self.empty_during_build = 0

    def search(self, term: str) -> list:
        self.queries += 1
        return sorted(self.current.get(term, []))

    def rebuild(self, docs) -> int:
        self.builds += 1
        self.current = {}
        for name, text in docs.items():
            for term in text.split():
                self.current.setdefault(term, []).append(name)
        self.generation += 1
        return self.generation

    def rollback(self) -> int:
        raise NotImplementedError("回滚还没实现")
