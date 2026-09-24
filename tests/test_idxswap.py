import json
import threading
import unittest
import urllib.error
import urllib.request

from indexbuild import IndexStore

class TestIndexStore(unittest.TestCase):
    def test_search_after_build(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha beta"})
        self.assertEqual(store.search("alpha"), ["d1"])

    def test_generation_advances(self):
        store = IndexStore()
        store.rebuild({"d1": "a"})
        store.rebuild({"d2": "a"})
        self.assertEqual(store.generation, 2)

    def test_empty_term(self):
        self.assertEqual(IndexStore().search("zzz"), [])

    def test_query_counter(self):
        store = IndexStore()
        store.search("a")
        self.assertEqual(store.queries, 1)

    def test_build_counter(self):
        store = IndexStore()
        store.rebuild({})
        self.assertEqual(store.builds, 1)
