""" Tests for vxfreeswitch.client. """

from twisted.internet.defer import inlineCallbacks, Deferred
from twisted.internet.protocol import ClientFactory
from twisted.test.proto_helpers import StringTransportWithDisconnection
from twisted.python.failure import Failure
from twisted.trial.unittest import TestCase

from eventsocket import EventError

from vxfreeswitch.client import (
    FreeSwitchClientProtocol, FreeSwitchClientFactory,
    FreeSwitchClient, FreeSwitchClientReply, FreeSwitchClientError)


def connect_transport(protocol):
    """ Connect a StringTransport to a client protocol. """
    factory = ClientFactory()
    transport = StringTransportWithDisconnection()
    protocol.makeConnection(transport)
    transport.protocol = protocol
    protocol.factory = factory
    return transport


class TestFreeSwitchClientProtocol(TestCase):
    def test_connected(self):
        p = FreeSwitchClientProtocol(auth=None)
        self.assertTrue(isinstance(p._connected, Deferred))
        self.assertEqual(p._connected.called, False)
        connect_transport(p)
        self.assertEqual(p._connected.called, True)
        self.assertEqual(p._connected.result, p)

    def test_auth(self):
        p = FreeSwitchClientProtocol(auth="pw-12345")
        tr = connect_transport(p)
        self.assertEqual(tr.value(), "auth pw-12345\n\n")

    def test_no_auth(self):
        p = FreeSwitchClientProtocol(auth=None)
        tr = connect_transport(p)
        self.assertEqual(tr.value(), "")


class TestFreeSwitchClientFactory(TestCase):
    def test_subclasses_client_factory(self):
        f = FreeSwitchClientFactory()
        self.assertTrue(isinstance(f, ClientFactory))

    def test_protocol(self):
        f = FreeSwitchClientFactory()
        p = f.protocol()
        self.assertTrue(isinstance(p, FreeSwitchClientProtocol))

    def test_default_noisy(self):
        f = FreeSwitchClientFactory()
        self.assertEqual(f.noisy, False)

    def test_set_noisy(self):
        f = FreeSwitchClientFactory(noisy=True)
        self.assertEqual(f.noisy, True)

    def test_no_auth(self):
        f = FreeSwitchClientFactory()
        p = f.protocol()
        tr = connect_transport(p)
        self.assertEqual(tr.value(), "")

    def test_auth(self):
        f = FreeSwitchClientFactory(auth="pw-1234")
        p = f.protocol()
        tr = connect_transport(p)
        self.assertEqual(tr.value(), "auth pw-1234\n\n")


class TestFreeSwitchClientError(TestCase):
    def test_subclasses_exception(self):
        err = FreeSwitchClientError("foo")
        self.assertTrue(isinstance(err, Exception))

    def test_str(self):
        err = FreeSwitchClientError("reason")
        self.assertEqual(str(err), "reason")


class TestFreeSwitchClientReply(TestCase):
    def test_args(self):
        reply = FreeSwitchClientReply("a", "b")
        self.assertEqual(reply.args, ("a", "b"))

    def test_repr(self):
        self.assertEqual(
            repr(FreeSwitchClientReply("a", "c")),
            "<FreeSwitchClientReply args=('a', 'c')>")

    def test_equal(self):
        self.assertEqual(
            FreeSwitchClientReply("a", "b"),
            FreeSwitchClientReply("a", "b"))

    def test_not_equal(self):
        self.assertNotEqual(
            FreeSwitchClientReply("a", "b"),
            FreeSwitchClientReply("a", "c"))

    def test_not_equal_other_object(self):
        self.assertNotEqual(
            FreeSwitchClientReply("a", "b"),
            object())


class TestFreeSwitchClient(TestCase):
    def mk_client(self, auth=None):
        endpoint = "XXX"
        return FreeSwitchClient(endpoint, auth)

    def test_fallback_error_handler_client_error(self):
        client = self.mk_client()
        failure = Failure(FreeSwitchClientError("reason"))
        self.assertEqual(
            client.fallback_error_handler(failure), failure)

    def test_fallback_error_handler_other_error(self):
        client = self.mk_client()
        failure = Failure(Exception("reason"))
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.fallback_error_handler, failure)
        self.assertEqual(str(err), "reason")

    def test_event_error_handler_event_error_has_reply(self):
        client = self.mk_client()
        failure = Failure(EventError({"Reply_Text": "+ERROR eep"}))
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.event_error_handler, failure)
        self.assertEqual(str(err), "+ERROR eep")

    def test_event_error_handler_event_error_no_reply(self):
        client = self.mk_client()
        failure = Failure(EventError({"Not_Reply": "foo"}))
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.event_error_handler, failure)
        self.assertEqual(str(err), "{'Not_Reply': 'foo'}")

    def test_event_error_handler_other_error(self):
        client = self.mk_client()
        failure = Failure(Exception("reason"))
        self.assertEqual(
            client.event_error_handler(failure), failure)

    def test_request_callback_with_reply(self):
        client = self.mk_client()
        self.assertEqual(
            client.request_callback({'Reply_Text': 'a b'}),
            FreeSwitchClientReply('a', 'b'))

    def test_request_callback_without_reply(self):
        client = self.mk_client()
        self.assertEqual(
            client.request_callback({}),
            FreeSwitchClientReply())

    def test_api_request_callback_with_okay_response(self):
        client = self.mk_client()
        self.assertEqual(
            client.api_request_callback({
                'data': {
                    'rawresponse': '+OK meep moop'
                }
            }),
            FreeSwitchClientReply('+OK', 'meep', 'moop'))

    def test_api_request_callback_with_error_response(self):
        client = self.mk_client()
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.api_request_callback, {
                'data': {
                    'rawresponse': '+ERROR meep moop'
                }
            })
        self.assertEqual(str(err), "+ERROR meep moop")

    def test_api_request_callback_without_data(self):
        client = self.mk_client()
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.api_request_callback, {
                'foo': 'bar',
            })
        self.assertEqual(str(err), "{'foo': 'bar'}")

    def test_api_request_callback_without_rawresponse(self):
        client = self.mk_client()
        err = self.failUnlessRaises(
            FreeSwitchClientError,
            client.api_request_callback, {
                'data': {}
            })
        self.assertEqual(str(err), "{'data': {}}")

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
