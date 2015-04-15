# coding: utf-8

"""Tests for vxfreeswitch.voice."""

import md5
import os

from twisted.internet.defer import inlineCallbacks

from vumi.message import TransportUserMessage
from vumi.tests.helpers import VumiTestCase
from vumi.tests.utils import LogCatcher
from vumi.transports.tests.helpers import TransportHelper

from vxfreeswitch import VoiceServerTransport
from vxfreeswitch.voice import FreeSwitchESLProtocol
from vxfreeswitch.tests.helpers import (
    EslCommand, EslHelper, EslTransport, FixtureApiResponse)


class TestFreeSwitchESLProtocol(VumiTestCase):

    transport_class = VoiceServerTransport

    VOICE_CMD = """
        python -c open("{filename}","w").write("{text}")
    """

    @inlineCallbacks
    def setUp(self):
        self.esl_helper = self.add_helper(EslHelper())
        self.tx_helper = self.add_helper(
            TransportHelper(self.transport_class))
        self.worker = yield self.tx_helper.get_transport({
            'twisted_endpoint': 'tcp:port=0',
            'freeswitch_endpoint': 'tcp:127.0.0.1:1337',
            'originate_parameters': {
                'call_url': '/sofia/gateway/yogisip',
                'exten': '100',
                'cid_name': 'elcid',
                'cid_num': '+1234'
            },
        })
        self.tr = EslTransport()

        self.proto = FreeSwitchESLProtocol(self.worker)
        self.proto.transport = self.tr

        self.voice_cache_folder = self.mktemp()
        os.mkdir(self.voice_cache_folder)

    def send_event(self, params):
        for key, value in params:
            self.proto.dataReceived("%s:%s\n" % (key, value))
        self.proto.dataReceived("\n")

    def send_command_reply(self, response):
        self.send_event([
            ("Content_Type", "command/reply"),
            ("Reply_Text", response),
        ])

    @inlineCallbacks
    def assert_and_reply(self, expected, response):
        cmd = yield self.tr.cmds.get()
        expected_cmd = EslCommand.from_dict(expected)
        self.assertEqual(cmd, expected_cmd)
        self.send_command_reply(response)

    def test_create_tts_command(self):
        self.assertEqual(
            self.proto.create_tts_command("foo", "myfile", "hi!"),
            ("foo", []))
        self.assertEqual(
            self.proto.create_tts_command(
                "foo -f {filename} -t {text}", "myfile", "hi!"),
            ("foo", ["-f", "myfile", "-t", "hi!"]))

    @inlineCallbacks
    def test_create_and_stream_text_as_speech_file_found(self):
        content = "Hello!"
        voice_key = md5.md5(content).hexdigest()
        voice_filename = os.path.join(
            self.voice_cache_folder, "voice-%s.wav" % voice_key)
        with open(voice_filename, "w") as f:
            f.write("Dummy voice file")

        with LogCatcher() as lc:
            d = self.proto.create_and_stream_text_as_speech(
                self.voice_cache_folder, self.VOICE_CMD, "wav", content)
            self.assertEqual(lc.messages(), [
                "Using cached voice file %r" % (voice_filename,)
            ])

        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "playback_terminators=None",
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "playback",
            "arg": voice_filename,
        }, "+OK")

        yield d

        with open(voice_filename) as f:
            self.assertEqual(f.read(), "Dummy voice file")

    @inlineCallbacks
    def test_create_and_stream_text_as_speech_file_not_found(self):
        content = "Hello!"
        voice_key = md5.md5(content).hexdigest()
        voice_filename = os.path.join(
            self.voice_cache_folder, "voice-%s.wav" % voice_key)

        with LogCatcher() as lc:
            d = self.proto.create_and_stream_text_as_speech(
                self.voice_cache_folder, self.VOICE_CMD, "wav", content)
            self.assertEqual(lc.messages(), [
                "Generating voice file %r" % (voice_filename,)
            ])

        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "playback_terminators=None",
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "playback",
            "arg": voice_filename,
        }, "+OK")

        yield d

        with open(voice_filename) as f:
            self.assertEqual(f.read(), "Hello!")

    @inlineCallbacks
    def test_send_text_as_speech(self):
        d = self.proto.send_text_as_speech(
            "thomas", "his_masters_voice", "hi!")

        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "tts_engine=thomas",
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "tts_voice=his_masters_voice",
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "speak",
            "arg": "hi!",
        }, "+OK")

        yield d

    def test_unboundEvent(self):
        with LogCatcher() as lc:
            self.proto.unboundEvent({"some": "data"}, "custom_event")
            self.assertEqual(lc.messages(), [
                "Unbound event 'custom_event'",
            ])


class TestVoiceServerTransportInboundCalls(VumiTestCase):

    transport_class = VoiceServerTransport
    transport_type = 'voice'

    @inlineCallbacks
    def setUp(self):
        self.tx_helper = self.add_helper(TransportHelper(self.transport_class))
        self.esl_helper = self.add_helper(EslHelper())
        self.worker = yield self.tx_helper.get_transport({
            'twisted_endpoint': 'tcp:port=0',
            'freeswitch_endpoint': 'tcp:127.0.0.1:1337',
            'originate_parameters': {
                'call_url': '/sofia/gateway/yogisip',
                'exten': '100',
                'cid_name': 'elcid',
                'cid_num': '+1234'
            },
        })
        self.client = yield self.esl_helper.mk_client(self.worker)

    @inlineCallbacks
    def test_client_register(self):
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], None)
        self.assertEqual(msg['session_event'],
                         TransportUserMessage.SESSION_NEW)

    @inlineCallbacks
    def test_client_deregister(self):
        # wait for registration message
        yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        self.client.sendDisconnectEvent()
        self.client.transport.loseConnection()
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], None)
        self.assertEqual(msg['session_event'],
                         TransportUserMessage.SESSION_CLOSE)

    @inlineCallbacks
    def test_client_hangup_and_disconnect(self):
        yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        self.client.sendChannelHangupEvent()
        self.client.sendDisconnectEvent()
        self.client.transport.loseConnection()
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], None)
        self.assertEqual(msg['session_event'],
                         TransportUserMessage.SESSION_CLOSE)

    @inlineCallbacks
    def test_simplemessage(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        msg = yield self.tx_helper.make_dispatch_reply(reg, "voice test")

        cmd = yield self.client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'speak', 'arg': 'voice test .',
        }))

        [ack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(ack['user_message_id'], msg['message_id'])
        self.assertEqual(ack['sent_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_simpledigitcapture(self):
        yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        self.client.sendDtmfEvent('5')
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], '5')

    @inlineCallbacks
    def test_multidigitcapture(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()

        yield self.tx_helper.make_dispatch_reply(
            reg, 'voice test', helper_metadata={'voice': {'wait_for': '#'}})

        cmd = yield self.client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'speak', 'arg': 'voice test .',
        }))

        self.client.sendDtmfEvent('5')
        self.client.sendDtmfEvent('7')
        self.client.sendDtmfEvent('2')
        self.client.sendDtmfEvent('#')
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], '572')

    @inlineCallbacks
    def test_speech_url(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()

        msg = yield self.tx_helper.make_dispatch_reply(
            reg, 'speech url test', helper_metadata={
                'voice': {
                    'speech_url': 'http://example.com/speech_url_test.ogg'
                }
            })

        cmd = yield self.client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'playback',
            'arg': 'http://example.com/speech_url_test.ogg',
        }))

        [ack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(ack['user_message_id'], msg['message_id'])
        self.assertEqual(ack['sent_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_reply_to_client_that_has_hung_up(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        [client] = self.worker._clients.values()
        self.worker.deregister_client(client)

        msg = yield self.tx_helper.make_dispatch_reply(
            reg, 'speech url test', helper_metadata={
                'voice': {
                    'speech_url': 'http://example.com/speech_url_test.ogg'
                }
            })

        [nack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(nack['user_message_id'], msg['message_id'])
        self.assertEqual(nack['nack_reason'],
                         "Client u'test-uuid' no longer connected")


class TestVoiceServerTransportOutboundCalls(VumiTestCase):

    transport_class = VoiceServerTransport

    @inlineCallbacks
    def setUp(self):
        self.tx_helper = self.add_helper(TransportHelper(self.transport_class))
        self.esl_helper = self.add_helper(EslHelper())
        self.worker = yield self.tx_helper.get_transport({
            'twisted_endpoint': 'tcp:port=0',
            'freeswitch_endpoint': 'tcp:127.0.0.1:port=1337',
            'originate_parameters': {
                'call_url': '/sofia/gateway/yogisip',
                'exten': '100',
                'cid_name': 'elcid',
                'cid_num': '+1234'
            },
        })

    @inlineCallbacks
    def test_create_call(self):
        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand("api originate /sofia/gateway/yogisip"
                       " 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK uuid-1234"))

        msg = self.tx_helper.make_outbound(
            'foobar', '12345', '54321', session_event='new')

        with LogCatcher() as lc:
            yield self.tx_helper.dispatch_outbound(msg)
        self.assertEqual(lc.messages(), [])

        events = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(events, [])

        client = yield self.esl_helper.mk_client(self.worker, 'uuid-1234')
        cmd = yield client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'speak', 'arg': 'foobar .',
        }))

        [ack] = yield self.tx_helper.wait_for_dispatched_events(1)
        self.assertEqual(ack['event_type'], 'ack')
        self.assertEqual(ack['sent_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_connect_error(self):
        factory = yield self.esl_helper.mk_server(
            fail_connect=True, uuid=lambda: 'uuid-1234')
        factory.add_fixture(
            EslCommand("api originate /sofia/gateway/yogisip"
                       " 100 XML default elcid +1234 60"),
            FixtureApiResponse("+ERROR Bad horse."))

        msg = self.tx_helper.make_outbound(
            'foobar', '12345', '54321', session_event='new')
        with LogCatcher(message='Error connecting') as lc:
            yield self.tx_helper.dispatch_outbound(msg)
        self.assertEqual(lc.messages(), [
            "Error connecting to client u'54321':"
            " +ERROR Bad horse.",
        ])
        [nack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(nack['user_message_id'], msg['message_id'])
        self.assertEqual(nack['nack_reason'],
                         "Could not make call to client u'54321'")
