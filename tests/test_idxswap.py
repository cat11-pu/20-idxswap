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

    def test_rollback_returns_previous_generation(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha"})
        store.rebuild({"d2": "beta"})
        self.assertEqual(store.generation, 2)
        self.assertEqual(store.search("alpha"), [])
        self.assertEqual(store.rollback(), 1)
        self.assertEqual(store.generation, 1)
        self.assertEqual(store.search("alpha"), ["d1"])
        self.assertEqual(store.search("beta"), [])

    def test_rollback_without_history_raises(self):
        from indexbuild import RollbackError
        store = IndexStore()
        with self.assertRaises(RollbackError):
            store.rollback()

    def test_old_index_visible_during_side_build(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha beta"})
        original_build = IndexStore._build
        seen = []

        def observing_build(docs):
            seen.append(list(store.search("alpha")))
            return original_build(docs)

        IndexStore._build = staticmethod(observing_build)
        try:
            store.rebuild({"d9": "zzz"})
        finally:
            IndexStore._build = staticmethod(original_build)
        self.assertEqual(seen, [["d1"]])
        self.assertEqual(store.search("alpha"), [])
        self.assertEqual(store.search("zzz"), ["d9"])

    def test_duplicate_term_in_doc_counts_once(self):
        store = IndexStore()
        store.rebuild({"d3": "alpha alpha"})
        self.assertEqual(store.search("alpha"), ["d3"])

    def test_rollback_restores_empty_initial_generation(self):
        store = IndexStore()
        store.rebuild({"d1": "alpha"})
        self.assertEqual(store.rollback(), 0)
        self.assertEqual(store.search("alpha"), [])
        with self.assertRaises(Exception):
            store.rollback()


class TestHttpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from indexbuild import IndexStore
        server.STORE = IndexStore()
        cls.server_module = server
        cls.httpd = server.serve(0)
        cls.base = "http://%s:%d" % cls.httpd.server_address
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def _request(self, method, path, payload=None):
        import json as _json
        data = _json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, _json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, _json.loads(exc.read().decode())

    def test_search_shape_preserved(self):
        status, body = self._request("GET", "/search?q=alpha")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"term", "hits", "generation"})
        self.assertEqual(body["term"], "alpha")

    def test_rebuild_rollback_over_http(self):
        status, body = self._request("POST", "/rebuild", {"docs": {"d1": "alpha beta"}})
        self.assertEqual((status, body["generation"]), (200, 1))
        _, body = self._request("GET", "/search?q=alpha")
        self.assertEqual(body["hits"], ["d1"])
        self.assertEqual(body["generation"], 1)

        status, body = self._request("POST", "/rebuild", {"docs": {"d3": "alpha alpha"}})
        self.assertEqual((status, body["generation"]), (200, 2))
        _, body = self._request("GET", "/search?q=alpha")
        self.assertEqual(body["hits"], ["d3"])

        status, body = self._request("POST", "/rollback")
        self.assertEqual((status, body["generation"]), (200, 1))
        _, body = self._request("GET", "/search?q=alpha")
        self.assertEqual(body["hits"], ["d1"])

    def test_rollback_conflict_when_no_history(self):
        import server
        from indexbuild import IndexStore
        self.server_module.STORE = IndexStore()
        status, body = self._request("POST", "/rollback")
        self.assertEqual(status, 409)
        self.assertIn("error", body)
        self.server_module.STORE = IndexStore()
