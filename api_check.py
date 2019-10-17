#!/usr/bin/env python

import argparse
import httplib
import json
import random
import threading
import string
import StringIO
import time
import unittest
import uuid

# Global variables set from options and used in unit tests
# (since it's hard to parameterize tests in Python 2)

SETTLE_MS_DEFAULT = 20
settle_ms = SETTLE_MS_DEFAULT

test_nodes = []

def parse_args():
    parser = argparse.ArgumentParser(prog="api_check", description="node API checker")

    parser.add_argument("--settle-ms", type=int,
            default=SETTLE_MS_DEFAULT,
            help="After a join/leave call, wait for the network to settle (default {} ms)"
                .format(SETTLE_MS_DEFAULT))

    parser.add_argument("nodes", type=str, nargs="+",
            help="addresses (host:port) of nodes to test")

    return parser.parse_args()

def describe_exception(e):
    return "%s: %s" % (type(e).__name__, e)

class Response(object): pass

def do_request(host_port, method, url, body=None, accept_statuses=[200]):
    def describe_request():
        return "%s %s%s" % (method, host_port, url)

    try:
        conn = httplib.HTTPConnection(host_port)
        conn.request(method, url, body)
        r = conn.getresponse()
    except Exception as e:
        raise Exception(describe_request()
                + " --- "
                + describe_exception(e))

    status = r.status
    if status not in accept_statuses:
        raise Exception(describe_request() + " --- unexpected status %d" % (r.status))

    headers = r.getheaders()
    body = r.read()

    conn.close()

    if ("content-type", "application/json") in headers:
        try:
            body = json.loads(body)
        except Exception as e:
            raise Exception(describe_request()
                    + " --- "
                    + describe_exception(e)
                    + " --- Body start: "
                    + body[:30])

    r2 = Response()
    r2.status = status
    r2.headers = headers
    r2.body = body

    return r2

class SimpleApiCheck(unittest.TestCase):

    def setUp(self):
        if len(test_nodes) < 1:
            raise unittest.SkipTest("Need at least one node")

        self.node = test_nodes[0]

    def test_get_nonexistent_value_404(self):
        key = "api-test-key-nonexistent-key-{}".format(uuid.uuid4())
        r = do_request(self.node, "GET", "/storage/"+key, accept_statuses=[404])

    def test_kv_put_and_get(self):
        key = "api-test-key-{}".format(uuid.uuid4())
        value = "api-test-value-{}".format(uuid.uuid4())

        r = do_request(self.node, "PUT", "/storage/"+key, value)
        r = do_request(self.node, "GET", "/storage/"+key)

        self.assertEqual(r.body, value)

    def test_node_info_json(self):
        r = do_request(self.node, "GET", "/node-info")
        self.assertIn(("content-type", "application/json"), r.headers,
                "Headers should specify Content-Type: application/json")

        self.assertIn("node_key", r.body)
        self.assertIn("successor", r.body)
        self.assertIn("others", r.body)
        self.assertIn("sim_crash", r.body)

        if not isinstance(r.body["node_key"], int):
            self.assertIsInstance(r.body["node_key"], unicode)

        self.assertIsInstance(r.body["successor"], unicode)
        self.assertIsInstance(r.body["others"], list)
        self.assertIsInstance(r.body["sim_crash"], bool)

class JoinLeaveApiCheck(unittest.TestCase):

    def setUp(self):
        if len(test_nodes) < 2:
            raise unittest.SkipTest("Need at least two nodes")

        self.nodeA = test_nodes[0]
        self.nodeB = test_nodes[1]

    def test_join_leave(self):
        # Make node A is not part of the network
        r = do_request(self.nodeA, "POST", "/leave")
        time.sleep(settle_ms / 1000.0)

        r = do_request(self.nodeA, "GET", "/node-info")
        # In a single-node network, the node should be its own successor
        self.assertEqual(r.body["successor"], self.nodeA)

        # Join one node to the other
        r = do_request(self.nodeA, "POST", "/join?nprime="+self.nodeB)
        time.sleep(settle_ms / 1000.0)

        r = do_request(self.nodeA, "GET", "/node-info")
        # In a two-node network, each should be their own successor
        # Here, we just check the first one, so that the dummy node can pass
        self.assertEqual(r.body["successor"], self.nodeB)

class SimCrashApiCheck(unittest.TestCase):

    def setUp(self):
        if len(test_nodes) < 1:
            raise unittest.SkipTest("Need at least one node")

        self.nodeA = test_nodes[0]

    def test_sim_crash_recover(self):
        # Make sure node A is not part of the network
        r = do_request(self.nodeA, "POST", "/leave")
        time.sleep(settle_ms / 1000.0)

        # --------------------------------------------------
        # Make sure node A is not crashed
        r = do_request(self.nodeA, "POST", "/sim-recover")
        time.sleep(settle_ms / 1000.0)

        r = do_request(self.nodeA, "GET", "/node-info")
        # Node state should be not crashed
        self.assertEqual(r.body["sim_crash"], False)

        # Node should respond to requests
        r = do_request(self.nodeA, "POST", "/leave")
        time.sleep(settle_ms / 1000.0)

        # --------------------------------------------------
        # Simulate crash
        r = do_request(self.nodeA, "POST", "/sim-crash")
        time.sleep(settle_ms / 1000.0)

        # Crashed node should not respond to requests
        self.assertRaises(Exception, lambda: do_request(self.nodeA, "POST", "/leave"))
        time.sleep(settle_ms / 1000.0)

        # Crashed node should still respond with info
        r = do_request(self.nodeA, "GET", "/node-info")
        # Node state should be crashed
        self.assertEqual(r.body["sim_crash"], True)

        # --------------------------------------------------
        # Simulate recovery
        r = do_request(self.nodeA, "POST", "/sim-recover")
        time.sleep(settle_ms / 1000.0)

        # Node should respond to requests
        r = do_request(self.nodeA, "POST", "/leave")
        time.sleep(settle_ms / 1000.0)

        r = do_request(self.nodeA, "GET", "/node-info")
        # Node state should be no-longer crashed
        self.assertEqual(r.body["sim_crash"], False)

if __name__ == "__main__":

    args = parse_args()

    test_nodes = args.nodes

    test_suite = unittest.TestSuite()
    test_loader = unittest.TestLoader()

    test_suite.addTests(test_loader.loadTestsFromTestCase(SimpleApiCheck))
    test_suite.addTests(test_loader.loadTestsFromTestCase(JoinLeaveApiCheck))
    test_suite.addTests(test_loader.loadTestsFromTestCase(SimCrashApiCheck))

    test_runner = unittest.TextTestRunner(verbosity=2)
    test_runner.run(test_suite)
