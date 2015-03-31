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
    def __init__(self, auth, noisy=False):
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
    def __init__(self, endpoint, auth=None):
        self.endpoint = endpoint
        self.factory = FreeSwitchClientFactory(auth)

    @inlineCallbacks
    def with_connection(self, f):
        """ Run a function with a connect client and then disconnect. """
        try:
            client = yield self.endpoint.connect(self.factory)
            yield client._connected
            result = yield f(client)
            yield client.transport.loseConnection()
        except EventError as err:
            msg = err.args[0].get('Reply_Text') or str(err)
            raise FreeSwitchClientError(msg)
        except Exception as err:
            raise FreeSwitchClientError(str(err))
        reply = FreeSwitchClientReply(*result.get('Reply_Text', '').split())
        returnValue(reply)

    def api(self, api_call):
        def mk_call(client):
            return client.api(api_call)
        return self.with_connection(mk_call)
