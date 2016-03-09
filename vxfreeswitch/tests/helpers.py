""" Test helpers for vxfreeswitch. """

from uuid import uuid4

from zope.interface import implements

import time

from twisted.internet import reactor
from twisted.internet.defer import (
    inlineCallbacks, returnValue, DeferredQueue, Deferred)
from twisted.internet.endpoints import TCP4ServerEndpoint
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.protocols.basic import LineReceiver
from twisted.test.proto_helpers import StringTransport

from vumi.tests.helpers import IHelper, proxyable


class EslCommand(object):
    """
    An object representing an ESL command.
    """
    def __init__(self, cmd_type, params=None):
        self.cmd_type = cmd_type
        self.params = params if params is not None else {}

    def __repr__(self):
        return "<%s cmd_type=%r params=%r>" % (
            self.__class__.__name__, self.cmd_type, self.params)

    def __eq__(self, other):
        if not isinstance(other, EslCommand):
            return NotImplemented
        return (self.cmd_type == other.cmd_type and
                self.params == other.params)

    def __getitem__(self, name):
        return self.params.get(name)

    def __setitem__(self, name, value):
        self.params[name] = value

    @classmethod
    def from_dict(cls, d):
        """
        Convert a dict to an :class:`EslCommand`.
        """
        cmd_type = d.get("type")
        params = {
            "call-command": d.get("call-command", "execute"),
            "event-lock": d.get("event-lock", "true"),
        }
        if "name" in d:
            params["execute-app-name"] = d.get("name")
        if "arg" in d:
            params["execute-app-arg"] = d.get("arg")
        return cls(cmd_type, params)


class EslParser(object):
    """
    Simple in-efficient parser for the FreeSwitch eventsocket protocol.
    """

    def __init__(self):
        self.data = ""

    def parse(self, new_data):
        data = self.data + new_data
        cmds = []
        while "\n\n" in data:
            cmd_data, data = data.split("\n\n", 1)
            command = EslCommand("unknown")
            first_line = True
            for line in cmd_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                if first_line:
                    command.cmd_type = line.strip()
                    first_line = False
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    command[key] = value.strip()
            cmds.append(command)
        self.data = data
        return cmds


class EslTransport(StringTransport):

    def __init__(self):
        StringTransport.__init__(self)
        self.cmds = DeferredQueue()
        self.esl_parser = EslParser()

    def write(self, data):
        StringTransport.write(self, data)
        for cmd in self.esl_parser.parse(data):
            self.cmds.put(cmd)


class RecordingServer(Protocol):
    def __init__(self):
        self.command_parser = EslParser()

    def connectionMade(self):
        self.factory.clients.append(self)

    def _send_event(self, content):
        self.transport.write(
            'Content-Length: %s\n' % len(content) +
            'Content-Type: text/event-plain\n\n' +
            content)

    def dataReceived(self, line):
        commands = self.command_parser.parse(line)
        for cmd in commands:
            response = self.factory.get_response(cmd)
            self.transport.write(response.to_bytes())

    def hangup(self):
        content = (
            'Event-Name: CHANNEL_HANGUP\n')
        self._send_event(content)


class FixtureResponse(object):
    """ A response to an ESL command. """

    AUTH_REQUEST = 'auth/request'
    API_RESPONSE = 'api/response'
    REPLY = 'command/reply'
    EVENT = 'text/event-plain'

    def __init__(self, content_type, content=None, headers=()):
        self.content_type = content_type
        self.content = content
        self.headers = headers

    def to_bytes(self):
        lines = []
        lines.append("Content-Type: %s\n" % self.content_type)
        if self.content is not None:
            lines.append("Content-Length: %d\n" % len(self.content))
        lines.extend("%s: %s\n" % (k, v) for k, v in self.headers)
        lines.append("\n")
        if self.content is not None:
            lines.append(self.content)
        return "".join(lines)


class FixtureReply(FixtureResponse):
    """ A reply to an ESL command. """

    def __init__(self, *args):
        headers = [("Reply-Text", " ".join(args))]
        super(FixtureReply, self).__init__(self.REPLY, headers=headers)


class FixtureAuthResponse(FixtureResponse):
    """ A response to an auth request. """

    def __init__(self, *args):
        headers = [("Reply-Text", " ".join(args))]
        super(FixtureAuthResponse, self).__init__(
            self.AUTH_REQUEST, headers=headers)


class FixtureApiResponse(FixtureResponse):
    """ A reply to an ESL command. """

    def __init__(self, *args):
        content = " ".join(args)
        super(FixtureApiResponse, self).__init__(self.API_RESPONSE, content)


class FixtureNotFound(Exception):
    """ Raise when a recording server has no matching fixture. """


class RecordingServerFactory(Factory):
    """ Factory for RecordingServer protocols. """

    protocol = RecordingServer

    def __init__(self, fail_connect=False, uuid=uuid4):
        self.fixtures = []
        self.clients = []

    def add_fixture(self, cmd, response):
        self.fixtures.append((cmd, response))

    def get_response(self, received_cmd):
        for i, (cmd, response) in enumerate(self.fixtures):
            if received_cmd == cmd:
                del self.fixtures[i]
                return response
        raise FixtureNotFound(received_cmd)


class FakeFreeSwitchProtocol(LineReceiver):
    """ A fake connection from FreeSwitch. """

    def __init__(self, call_uuid):
        self.call_uuid = call_uuid
        self.esl_parser = EslParser()
        self.queue = DeferredQueue()
        self.connect_d = Deferred()
        self.disconnect_d = Deferred()
        self.setRawMode()

    def connectionMade(self):
        self.connected = True
        self.connect_d.callback(None)

    def sendPlainEvent(self, name, params=None):
        params = {} if params is None else params
        params['Event-Name'] = name
        data = "\n".join("%s: %s" % (k, v) for k, v in params.items()) + "\n"
        self.sendLine(
            'Content-Length: %d\nContent-Type: text/event-plain\n\n%s' %
            (len(data), data))

    def sendCommandReply(self, params=""):
        self.sendLine('Content-Type: command/reply\nReply-Text: +OK\n%s\n\n' %
                      params)

    def sendChannelHangupCompleteEvent(self, duration):
        """
        Sends a hangup complete event. Duration = duration of call in ms
        """
        hangup_time = int(time.time() * 1000)
        answer_time = int(hangup_time - duration)
        self.sendPlainEvent('Channel_Hangup_Complete', {
            'Caller-Channel-Answered-Time': answer_time,
            'Caller-Channel-Hangup-Time': hangup_time
        })

    def sendDtmfEvent(self, digit):
        self.sendPlainEvent('DTMF', {
            'DTMF-Digit': digit,
        })

    def sendDisconnectEvent(self):
        self.sendLine('Content-Type: text/disconnect-notice\n\n')

    def sendChannelAnswerEvent(self):
        self.sendPlainEvent('Channel_Answer', {
            'Variable-Caller-ID': self.call_uuid
        })

    def rawDataReceived(self, data):
        for cmd in self.esl_parser.parse(data):
            if cmd.cmd_type == "connect":
                self.sendCommandReply(
                    'variable-call-uuid: %s' % self.call_uuid)
            elif cmd.cmd_type == "myevents":
                self.sendCommandReply()
            elif cmd.cmd_type == "sendmsg":
                self.sendCommandReply()
                cmd_name = cmd.params.get('execute-app-name')
                if cmd_name == "speak":
                    self.queue.put(cmd)
                elif cmd_name == "playback":
                    self.queue.put(cmd)
                elif cmd_name == "play_and_get_digits":
                    self.queue.put(cmd)

    def connectionLost(self, reason):
        self.connected = False
        self.disconnect_d.callback(None)


class EslHelper(object):
    """
    Test helper for working with ESL servers.
    """

    implements(IHelper)

    def __init__(self):
        self._recorders = []
        self._clients = []

    def setup(self):
        pass

    @inlineCallbacks
    def cleanup(self):
        for server, factory in self._recorders:
            yield server.stopListening()
            for client in factory.clients:
                yield client.transport.loseConnection()
        for client in self._clients:
            if client.transport and client.transport.connected:
                client.sendDisconnectEvent()
                yield client.transport.loseConnection()
                yield client.disconnect_d

    @proxyable
    @inlineCallbacks
    def mk_server(self, port=1337, fail_connect=False, uuid=uuid4):
        endpoint = TCP4ServerEndpoint(reactor, port)
        factory = RecordingServerFactory(fail_connect=fail_connect, uuid=uuid)
        server = yield endpoint.listen(factory)
        self._recorders.append((server, factory))
        returnValue(factory)

    @proxyable
    @inlineCallbacks
    def mk_client(self, worker, call_uuid="test-uuid"):
        addr = worker.voice_server.getHost()
        client = FakeFreeSwitchProtocol(call_uuid)
        self._clients.append(client)
        factory = ClientFactory.forProtocol(lambda: client)
        yield reactor.connectTCP("127.0.0.1", addr.port, factory)
        yield client.connect_d
        returnValue(client)
