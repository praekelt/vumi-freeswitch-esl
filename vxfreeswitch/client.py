# -*- test-case-name: vxfreeswitch.tests.test_client -*-

"""
FreeSwitch ESL API client.
"""

from twisted.internet.protocol import ClientFactory
from twisted.internet.defer import inlineCallbacks, returnValue, Deferred

from eventsocket import EventProtocol, EventError


class FreeSwitchClientProtocol(EventProtocol):
    """ Freeswitch ESL client.

    :param str auth:
        Authentication string to send to FreeSwitch.
    """

    def __init__(self, auth):
        EventProtocol.__init__(self)
        self._auth = auth
        self._connected = Deferred()

    @inlineCallbacks
    def connectionMade(self):
        if self._auth:
            yield self.auth(self._auth)
        self._connected.callback(self)


class FreeSwitchClientFactory(ClientFactory):
    """ FreeSwitch ESL client factory. """
    def __init__(self, auth=None, noisy=False):
        self.noisy = noisy
        self.auth = auth

    def protocol(self):
        return FreeSwitchClientProtocol(self.auth)


class FreeSwitchClientError(Exception):
    """ Raised when a FreeSwitch ESL command fails. """


class FreeSwitchClientReply(object):
    """ A successful reply to a FreeSwitch ESL command. """
    def __init__(self, *args):
        self.args = args

    def __repr__(self):
        return "<%s args=%r>" % (self.__class__.__name__, self.args)

    def __eq__(self, other):
        if isinstance(other, FreeSwitchClientReply):
            return self.args == other.args
        return NotImplemented


class FreeSwitchClient(object):
    """ Helper class for making simple API calls to the FreeSwitch ESL
    server.

    :type endpoint:
        Twisted client endpoint.
    :param endpoint:
        Endpoint for connecting to FreeSwitch over.

    :param str auth:
        Authentication string to send to FreeSwitch on connect.
    """
    def __init__(self, endpoint, auth=None, noisy=False):
        self.endpoint = endpoint
        self.factory = FreeSwitchClientFactory(auth=auth, noisy=noisy)

    def fallback_error_handler(self, failure):
        if failure.check(FreeSwitchClientError):
            return failure
        raise FreeSwitchClientError(str(failure.value))

    def event_error_handler(self, failure):
        if failure.check(EventError):
            err = failure.value
            ev = err.args[0]
            msg = ev.get('Reply_Text') or str(err)
            raise FreeSwitchClientError(msg)
        return failure

    def request_callback(self, ev):
        args = ev.get('Reply_Text', '').split()
        return FreeSwitchClientReply(*args)

    def api_request_callback(self, ev):
        rawresponse = ev.get('data', {}).get('rawresponse', '')
        args = rawresponse.split()
        if not (args and args[0] == "+OK"):
            msg = rawresponse or str(ev)
            raise FreeSwitchClientError(msg)
        return FreeSwitchClientReply(*args)

    @inlineCallbacks
    def _raw_with_connection(self, client, f):
        yield client._connected
        try:
            result = yield f(client)
        finally:
            yield client.transport.loseConnection()
        returnValue(result)

    def with_connection(self, f):
        """ Run a function with a connect client and then disconnect.

        :param function f:
            f(client) - the function that makes calls to the client.
        """
        d = self.endpoint.connect(self.factory)
        d.addCallback(lambda client: client._connected)
        d.addCallback(self._raw_with_connection, f)
        d.addErrback(self.event_error_handler)
        d.addErrback(self.fallback_error_handler)
        return d

    def api(self, api_call):
        def mk_call(client):
            d = client.api(api_call)
            d.addCallbacks(self.api_request_callback)
            return d
        return self.with_connection(mk_call)
