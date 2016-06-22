# coding: utf-8

"""Tests for vxfreeswitch.voice."""

import logging
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

    @inlineCallbacks
    def assert_and_reply_tts(self, engine, voice, msg):
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "tts_engine=%s" % engine,
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "tts_voice=%s" % voice,
        }, "+OK")
        yield self.assert_and_reply_playback("say:'%s'" % msg)

    @inlineCallbacks
    def assert_and_reply_playback(self, url):
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "set",
            "arg": "playback_terminators=None",
        }, "+OK")
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "playback",
            "arg": url,
        }, "+OK")

    @inlineCallbacks
    def assert_and_reply_get_digits(self, msg, **kwargs):
        params = {
            'minimum': 1, 'maximum': 1, 'timeout': 3000, 'terminator': "''",
            'tries': 1, 'msg': msg,
        }
        params.update(kwargs)
        yield self.assert_and_reply({
            "type": "sendmsg", "name": "play_and_get_digits",
            "arg": ("%(minimum)d %(maximum)d %(tries)d %(timeout)d "
                    "%(terminator)s %(msg)s silence_stream://1") % params,
        }, "+OK")

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
        self.proto.uniquecallid = "abc-1234"
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
                "[abc-1234] Using cached voice file %r" % (voice_filename,),
                "[abc-1234] Playing back: %r" % (voice_filename,),
            ])

        yield self.assert_and_reply_playback(voice_filename)
        yield d

        with open(voice_filename) as f:
            self.assertEqual(f.read(), "Dummy voice file")

    @inlineCallbacks
    def test_create_and_stream_text_as_speech_file_not_found(self):
        self.proto.uniquecallid = "abc-1234"
        content = "Hello!"
        voice_key = md5.md5(content).hexdigest()
        voice_filename = os.path.join(
            self.voice_cache_folder, "voice-%s.wav" % voice_key)

        with LogCatcher() as lc:
            d = self.proto.create_and_stream_text_as_speech(
                self.voice_cache_folder, self.VOICE_CMD, "wav", content)
            self.assertEqual(lc.messages(), [
                "[abc-1234] Generating voice file %r" % (voice_filename,)
            ])

        yield self.assert_and_reply_playback(voice_filename)
        yield d

        with open(voice_filename) as f:
            self.assertEqual(f.read(), "Hello!")

    @inlineCallbacks
    def test_send_text_as_speech(self):
        d = self.proto.send_text_as_speech(
            "thomas", "his_masters_voice", "hi!")
        yield self.assert_and_reply_tts("thomas", "his_masters_voice", "hi!")
        yield d

    @inlineCallbacks
    def test_output_message(self):
        self.proto.uniquecallid = "abc-1234"
        with LogCatcher() as lc:
            d = self.proto.output_message("Foo!")
            yield self.assert_and_reply_tts("flite", "kal", "Foo!")
            yield d
            self.assertEqual(lc.messages(), [
                "[abc-1234] Playing back: \"say:'Foo!'\"",
            ])

    @inlineCallbacks
    def test_output_stream(self):
        self.proto.uniquecallid = "abc-1234"
        voice_filename = "http://example.com/foo.mp3"
        with LogCatcher() as lc:
            d = self.proto.output_stream(voice_filename)
            self.assertEqual(lc.messages(), [
                "[abc-1234] Playing back: 'http://example.com/foo.mp3'",
            ])
        yield self.assert_and_reply_playback(voice_filename)
        yield d

    def test_unboundEvent(self):
        self.proto.uniquecallid = "abc-1234"
        with LogCatcher() as lc:
            self.proto.unboundEvent({"some": "data"}, "custom_event")
            self.assertEqual(lc.messages(), [
                "[abc-1234] Unbound event 'custom_event'",
            ])

    @inlineCallbacks
    def test_output_stream_barge_in_defaults(self):
        self.proto.output_stream('foo', {'barge_in': True})
        yield self.assert_and_reply_get_digits('foo')

    @inlineCallbacks
    def test_output_stream_barge_in_non_defaults(self):
        self.proto.output_stream('foo', {
            'barge_in': True, 'wait_for': '#', 'tries': 2, 'time_gap': 5000})
        yield self.assert_and_reply_get_digits(
            'foo', minimum=0, maximum=128, tries=2, timeout=5000,
            terminator='#')

    @inlineCallbacks
    def test_send_text_as_speech_quote_escaping(self):
        '''If there are any single quotes in the text that we are converting
        to speech, we should escape those quotes before sending it to
        freeswitch, since we send the text string within single quotes.'''
        d = self.proto.send_text_as_speech(
            "thomas", "his_masters_voice", "text with single quote's")
        yield self.assert_and_reply_tts(
            "thomas", "his_masters_voice", "text with single quote\\'s")
        yield d


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

    def assert_get_digits_command(self, cmd, msg, **kwargs):
        params = {
            'minimum': 1, 'maximum': 1, 'timeout': 3000, 'terminator': "''",
            'tries': 1, 'msg': msg,
        }
        params.update(kwargs)
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'play_and_get_digits',
            "arg": ("%(minimum)d %(maximum)d %(tries)d %(timeout)d "
                    "%(terminator)s %(msg)s silence_stream://1") % params,
        }))

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
        duration = 20
        yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        self.client.sendChannelHangupCompleteEvent(duration)
        self.client.sendDisconnectEvent()
        self.client.transport.loseConnection()
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], None)
        self.assertEqual(msg['session_event'],
                         TransportUserMessage.SESSION_CLOSE)
        self.assertEqual(
            msg['helper_metadata']['voice']['call_duration'], duration)

    @inlineCallbacks
    def test_client_hangup_invalid_freeswitch_duration(self):
        yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        self.client.sendPlainEvent('Channel_Hangup_Complete', {
            'Caller-Channel-Answered-Time': 'foo',
            'Caller-Channel-Hangup-Time': 'bar'
        })
        self.client.transport.loseConnection()
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], None)
        self.assertEqual(msg['session_event'],
                         TransportUserMessage.SESSION_CLOSE)
        self.assertEqual(msg['helper_metadata'].get('voice'), None)

    @inlineCallbacks
    def test_simplemessage(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        msg = yield self.tx_helper.make_dispatch_reply(reg, "voice test")

        cmd = yield self.client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'playback', 'arg': "say:'voice test . '",
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
            'type': 'sendmsg', 'name': 'playback', 'arg': "say:'voice test . '",
        }))

        self.client.sendDtmfEvent('5')
        self.client.sendDtmfEvent('7')
        self.client.sendDtmfEvent('2')
        self.client.sendDtmfEvent('#')
        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], '572')

    @inlineCallbacks
    def test_speech_url_string(self):
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
    def test_speech_url_list(self):
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()
        urls = [
            'http://example.com/speech_url_test1.ogg',
            'http://example.com/speech_url_test2.ogg'
        ]

        msg = yield self.tx_helper.make_dispatch_reply(
            reg, 'speech url test', helper_metadata={
                'voice': {
                    'speech_url': urls,
                }
            })

        cmd = yield self.client.queue.get()
        urllist = 'file_string://%s' % '!'.join(urls)
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'playback',
            'arg': urllist,
        }))

        [ack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(ack['user_message_id'], msg['message_id'])
        self.assertEqual(ack['sent_message_id'], msg['message_id'])
        self.assertEqual(ack['event_type'], 'ack')

    @inlineCallbacks
    def test_speech_url_invalid_url(self):
        url = 7
        with LogCatcher(log_level=logging.WARN) as lc:
            [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
            self.tx_helper.clear_dispatched_inbound()

            msg = yield self.tx_helper.make_dispatch_reply(
                reg, 'speech url test', helper_metadata={
                    'voice': {
                        'speech_url': url
                    }
                })
        [warn_log] = lc.messages()
        self.assertEqual(warn_log, "Invalid URL %r" % url)

        [nack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(nack['user_message_id'], msg['message_id'])
        self.assertEqual(nack['event_type'], 'nack')
        self.assertEqual(nack['nack_reason'], 'Invalid URL %r' % url)

    @inlineCallbacks
    def test_speech_invalid_url_list(self):
        valid_url = u'http://example.com/speech_url_test1.ogg'
        invalid_url1 = 7
        invalid_url2 = 8
        with LogCatcher(log_level=logging.WARN) as lc:
            [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
            self.tx_helper.clear_dispatched_inbound()

            msg = yield self.tx_helper.make_dispatch_reply(
                reg, 'speech url test', helper_metadata={
                    'voice': {
                        'speech_url': [
                            invalid_url1,
                            valid_url,
                            invalid_url2,
                        ]
                    }
                })

        [log] = lc.messages()
        self.assertEqual(log, 'Invalid URL list %r' % (
            [invalid_url1, valid_url, invalid_url2], ))
        [nack] = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(nack['user_message_id'], msg['message_id'])
        self.assertEqual(nack['event_type'], 'nack')
        self.assertEqual(nack['nack_reason'], 'Invalid URL list %r' % (
            [invalid_url1, valid_url, invalid_url2], ))

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

    @inlineCallbacks
    def test_barge_in_defaults(self):
        '''Barge ins should use the play_and_get_digits command with certain
        default values.'''
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()

        yield self.tx_helper.make_dispatch_reply(
            reg, 'barge in test', helper_metadata={
                'voice': {
                    'barge_in': True,
                },
            })

        cmd = yield self.client.queue.get()
        self.assert_get_digits_command(cmd, "say:'barge in test . '")

    @inlineCallbacks
    def test_barge_in_non_defaults(self):
        '''When the correct fields are specified, these should override the
        defaults.'''
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()

        yield self.tx_helper.make_dispatch_reply(
            reg, 'barge in test', helper_metadata={
                'voice': {
                    'barge_in': True,
                    'wait_for': '#',
                    'tries': 2,
                    'time_gap': 5000,
                },
            })

        cmd = yield self.client.queue.get()
        self.assert_get_digits_command(
            cmd, "say:'barge in test . '", minimum=0, maximum=128,
            terminator='#', tries=2, timeout=5000)

    @inlineCallbacks
    def test_barge_in_collecting_digits(self):
        '''If we send a barge in message, we should collect the digits that
        the client has sent us.'''
        [reg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.tx_helper.clear_dispatched_inbound()

        yield self.tx_helper.make_dispatch_reply(
            reg, 'barge in test', helper_metadata={
                'voice': {
                    'barge_in': True,
                    'wait_for': '#',
                },
            })

        self.client.sendDtmfEvent('5')
        self.client.sendDtmfEvent('6')
        self.client.sendDtmfEvent('#')

        [msg] = yield self.tx_helper.wait_for_dispatched_inbound(1)
        self.assertEqual(msg['content'], '56')


class TestVoiceServerTransportOutboundCalls(VumiTestCase):

    transport_class = VoiceServerTransport

    def setUp(self):
        self.tx_helper = self.add_helper(TransportHelper(self.transport_class))
        self.esl_helper = self.add_helper(EslHelper())

    def create_worker(self, config={}):
        default = {
            'twisted_endpoint': 'tcp:port=0',
            'freeswitch_endpoint': 'tcp:127.0.0.1:port=1337',
            'originate_parameters': {
                'call_url': '/sofia/gateway/yogisip',
                'exten': '100',
                'cid_name': 'elcid',
                'cid_num': '+1234'
            },
        }
        default.update(config)
        return self.tx_helper.get_transport(default)

    @inlineCallbacks
    def test_create_call(self):
        self.worker = yield self.create_worker()
        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand("api originate /sofia/gateway/yogisip"
                       " 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK uuid-1234"))

        msg = self.tx_helper.make_outbound(
            'foobar', '12345', '54321', session_event='new')

        client = yield self.esl_helper.mk_client(self.worker, 'uuid-1234')

        with LogCatcher(log_level=logging.WARN) as lc:
            yield self.tx_helper.dispatch_outbound(msg)
        self.assertEqual(lc.messages(), [])

        events = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(events, [])

        client.sendChannelAnswerEvent()

        cmd = yield client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'playback', 'arg': "say:'foobar . '",
        }))

        [ack] = yield self.tx_helper.wait_for_dispatched_events(1)
        self.assertEqual(ack['event_type'], 'ack')
        self.assertEqual(ack['sent_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_connect_error(self):
        self.worker = yield self.create_worker()
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

    @inlineCallbacks
    def test_client_disconnect_without_answer(self):
        self.worker = yield self.create_worker()
        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand("api originate /sofia/gateway/yogisip"
                       " 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK uuid-1234"))

        msg = self.tx_helper.make_outbound(
            'foobar', '12345', '54321', session_event='new')

        client = yield self.esl_helper.mk_client(self.worker, 'uuid-1234')

        with LogCatcher(log_level=logging.WARN) as lc:
            yield self.tx_helper.dispatch_outbound(msg)

        self.assertEqual(lc.messages(), [])

        events = yield self.tx_helper.get_dispatched_events()
        self.assertEqual(events, [])

        client.sendDisconnectEvent()

        [nack] = yield self.tx_helper.wait_for_dispatched_events(1)
        self.assertEqual(nack['event_type'], 'nack')
        self.assertEqual(nack['nack_reason'], 'Unanswered Call')
        self.assertEqual(nack['user_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_wait_for_answer_false(self):
        '''If the wait_for_answer config field is False, then we shouldn't wait
        for a ChannelAnswer event before playing media.'''
        self.worker = yield self.create_worker({'wait_for_answer': False})
        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand("api originate /sofia/gateway/yogisip"
                       " 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK uuid-1234"))

        msg = self.tx_helper.make_outbound(
            'foobar', '12345', '54321', session_event='new')

        yield self.tx_helper.dispatch_outbound(msg)

        client = yield self.esl_helper.mk_client(self.worker, 'uuid-1234')

        # We are not sending a ChannelAnswer event, but we expect a sendmsg
        # command to be sent anyway, because wait_for_answer is False

        cmd = yield client.queue.get()
        self.assertEqual(cmd, EslCommand.from_dict({
            'type': 'sendmsg', 'name': 'playback', 'arg': "say:'foobar . '",
        }))

        [ack] = yield self.tx_helper.wait_for_dispatched_events(1)
        self.assertEqual(ack['event_type'], 'ack')
        self.assertEqual(ack['sent_message_id'], msg['message_id'])

    @inlineCallbacks
    def test_use_our_generated_uuid_if_in_originate_command(self):
        '''If our generated uuid is in the resulting originate command, we
        should use that uuid instead of the one provided by freeswitch.'''
        self.worker = yield self.create_worker({
            'originate_parameters': {
                'call_url': '{{origination_uuid={uuid}}}sofia/gateway/yogisip',
                'exten': '100',
                'cid_name': 'elcid',
                'cid_num': '+1234',
            },
        })

        def static_id():
            return 'test-uuid-1234'

        self.worker.generate_message_id = static_id

        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand(
                "api originate {origination_uuid=test-uuid-1234}sofia/gateway/"
                "yogisip 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK wrong-uuid-1234"))

        uuid = yield self.worker.dial_outbound("+4321")
        self.assertEqual(uuid, 'test-uuid-1234')

    @inlineCallbacks
    def test_use_freeswitch_uuid_if_not_in_originate_command(self):
        '''If the generated uuid is not in the resulting originate command, we
        should use the uuid from freeswitch instead.import'''
        self.worker = yield self.create_worker()

        def static_id():
            return 'wrong-uuid-1234'

        self.worker.generate_message_id = static_id

        factory = yield self.esl_helper.mk_server()
        factory.add_fixture(
            EslCommand(
                "api originate /sofia/gateway/"
                "yogisip 100 XML default elcid +1234 60"),
            FixtureApiResponse("+OK correct-uuid-1234"))

        uuid = yield self.worker.dial_outbound("+4321")
        self.assertEqual(uuid, 'correct-uuid-1234')
