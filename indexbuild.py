"""indexbuild.py：索引构建与切换。

新索引在旁路构建完成后原子替换现役索引（世代号递增），
替换完成前旧索引一直可查；rollback 在现役与上一世代两个版本槽间交换。
初始空索引不算一个世代，没有上一版时 rollback 报错。
"""
from __future__ import annotations

import threading
import time


class IndexStore:
    def __init__(self):
        self.current = {}
        self.generation = 0
        self._previous_version = None  # (索引, 世代号)
        self.builds = 0
        self.queries = 0
        self.empty_during_build = 0
        self._lock = threading.RLock()

    def lookup(self, term: str):
        """返回 (命中列表, 当前世代号)，二者取自同一代索引。"""
        with self._lock:
            self.queries += 1
            return sorted(self.current.get(term, [])), self.generation

    def search(self, term: str) -> list:
        return self.lookup(term)[0]

    @property
    def has_previous(self) -> bool:
        with self._lock:
            return self._previous_version is not None

    def rebuild(self, docs, build_pause: float = 0) -> int:
        """在旁路构建新索引，完成后原子替换；旧索引在切换前一直可用。"""
        with self._lock:
            self.builds += 1
        new_index = {}
        for name, text in docs.items():
            for term in text.split():
                bucket = new_index.setdefault(term, [])
                if name not in bucket:
                    bucket.append(name)
            if build_pause:
                time.sleep(build_pause)
        with self._lock:
            if self.generation:
                self._previous_version = (self.current, self.generation)
            self.current = new_index
            self.generation += 1
            return self.generation

    def rollback(self) -> int:
        """退回上一世代（交换现役/上一世代两个版本槽），返回当前世代号。"""
        with self._lock:
            if self._previous_version is None:
                raise LookupError("没有可回滚的上一世代")
            previous_index, previous_generation = self._previous_version
            self._previous_version = (self.current, self.generation)
            self.current = previous_index
            self.generation = previous_generation
            return self.generation
