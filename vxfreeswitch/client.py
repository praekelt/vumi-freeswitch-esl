# -*- test-case-name: vxfreeswitch.tests.test_client -*-

"""
FreeSwitch ESL API client.
"""

from twisted.internet.protocol import ClientFactory
from twisted.internet.defer import inlineCallbacks, Deferred

from eventsocket import EventProtocol


class FreeswitchClientError(Exception):
    """ Error raised while using the Freeswitch client. """


class FreeSwitchClientProtocol(EventProtocol):
    """ Freeswitch ESL client.

    :param str auth:
        Authentication string to send to FreeSwitch.
    """

    def __init__(self, auth):
        EventProtocol.__init__(self)
        self._auth = auth
        self.connected = Deferred()

    @inlineCallbacks
    def connectionMade(self):
        if self._auth_credentials:
            yield self.auth(self._auth_credentials)
        self.connected.callback(self)


class FreeSwitchClientFactory(ClientFactory):
    """ FreeSwitch ESL client factory. """
    def __init__(self, auth):
        ClientFactory.__init__(self)
        self.auth = auth

    def protocol(self):
        return FreeSwitchClientProtocol(self.auth)


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

    def _connect(self):
        """ Return a connected client or fail. """
        d = self.endpoint.connect(self.factory)
        d.addCallback(lambda client: client.connected)
        return d

    def api(self, api_call):
        d = self._connect()
        d.addCallback(lambda client: client.api(api_call))
        return d
