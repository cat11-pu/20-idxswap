import json
import threading
import time
import unittest
import urllib.error
import urllib.request

import server
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

    def test_rollback_returns_previous_generation(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha"})
        store.rebuild({"d2": "alpha"})
        self.assertEqual(store.rollback(), 1)
        self.assertEqual(store.generation, 1)
        self.assertEqual(store.search("alpha"), ["d1"])

    def test_rollback_then_rollforward_again(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha"})
        store.rebuild({"d2": "alpha"})
        store.rollback()
        self.assertEqual(store.rollback(), 2)
        self.assertEqual(store.search("alpha"), ["d2"])

    def test_rollback_without_previous_raises(self):
        store = IndexStore()
        with self.assertRaises(LookupError):
            store.rollback()
        store.rebuild({"d1": "alpha"})
        with self.assertRaises(LookupError):
            store.rollback()

    def test_duplicate_term_in_one_doc_counts_once(self):
        store = IndexStore()
        store.rebuild({"d3": "alpha alpha"})
        self.assertEqual(store.search("alpha"), ["d3"])

    def test_old_index_stays_searchable_during_offline_build(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha"})
        seen = []

        def rebuild():
            store.rebuild({"d2": "alpha"}, build_pause=0.3)

        worker = threading.Thread(target=rebuild)
        worker.start()
        time.sleep(0.1)
        seen.append(store.lookup("alpha"))
        worker.join()
        self.assertEqual(seen, [(["d1"], 1)])
        self.assertEqual(store.lookup("alpha"), (["d2"], 2))


class TestHttpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve(0)
        cls.base = "http://%s:%d" % cls.httpd.server_address
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        server.STORE = IndexStore()

    def _call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode())

    def test_search_shape_compatible(self):
        self._call("POST", "/rebuild", {"docs": {"d1": "alpha beta"}})
        status, body = self._call("GET", "/search?q=alpha")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"term", "hits", "generation"})
        self.assertEqual(body, {"term": "alpha", "hits": ["d1"], "generation": 1})

    def test_rebuild_and_rollback_over_http(self):
        self._call("POST", "/rebuild", {"docs": {"d1": "alpha"}})
        status, body = self._call("POST", "/rebuild", {"docs": {"d3": "alpha alpha"}})
        self.assertEqual(body["generation"], 2)
        _, after = self._call("GET", "/search?q=alpha")
        self.assertEqual(after["hits"], ["d3"])
        status, body = self._call("POST", "/rollback")
        self.assertEqual((status, body["generation"]), (200, 1))
        _, back = self._call("GET", "/search?q=alpha")
        self.assertEqual(back["hits"], ["d1"])

    def test_rollback_without_previous_is_error(self):
        status, body = self._call("POST", "/rollback")
        self.assertEqual(status, 409)
        self.assertIn("error", body)

    def test_queries_during_rebuild_see_old_generation(self):
        self._call("POST", "/rebuild", {"docs": {"d1": "alpha"}})
        results = []

        def rebuild():
            self._call("POST", "/rebuild", {"docs": {"d3": "alpha"}, "build_pause": 0.3})

        worker = threading.Thread(target=rebuild)
        worker.start()
        time.sleep(0.1)
        for _ in range(3):
            results.append(self._call("GET", "/search?q=alpha"))
        worker.join()
        self.assertTrue(results)
        for status, body in results:
            self.assertEqual(status, 200)
            self.assertEqual(body["generation"], 1)
            self.assertEqual(body["hits"], ["d1"])

    def test_status_and_index_page(self):
        status, body = self._call("GET", "/status")
        self.assertEqual(status, 200)
        self.assertIn("generation", body)
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
