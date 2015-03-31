""" Tests for vxfreeswitch.client. """

from twisted.internet.defer import inlineCallbacks
from twisted.trial.unittest import TestCase

from vxfreeswitch.client import FreeSwitchClient


class TestFreeSwitchClient(TestCase):
    def mk_client(self, auth=None):
        endpoint = "XXX"
        return FreeSwitchClient(endpoint, auth)

    @inlineCallbacks
    def test_with_connection(self):
        def f(conn):
            return conn.do_something()

        client = self.mk_client()
        result = yield client.with_connection(f)
        self.assertEqual(result, "XXX")

    @inlineCallbacks
    def test_api(self):
        client = self.mk_client()
        result = yield client.api("foo")
        self.assertEqual(result, "XXX")

    @inlineCallbacks
    def test_auth(self):
        def f(conn):
            return

        client = self.mk_client(auth="kenny")
        result = yield client.with_connection(f)
        self.assertEqual(result, "XXX")
        self.assertTrue(authenticated)
