# -*- test-case-name: vxfreeswitch.tests.test_voice -*-

"""
Transport that sends text as voice to a standard SIP client via
the Freeswitch ESL interface. Keypad input from the phone is sent
through as a vumi message
"""

import md5
import os

from twisted.internet.protocol import ServerFactory, ClientFactory
from twisted.internet.defer import (
        inlineCallbacks, Deferred, gatherResults, returnValue)
from twisted.internet.utils import getProcessOutput
from twisted.python import log

from eventsocket import EventProtocol

from vumi.transports import Transport
from vumi.message import TransportUserMessage
from vumi.config import ConfigClientEndpoint, ConfigServerEndpoint, ConfigText
from vumi.errors import VumiError


class VoiceError(VumiError):
    """Raised when errors occur while processing voice messages."""


class FreeSwitchESLProtocol(EventProtocol):

    def __init__(self, vumi_transport):
        EventProtocol.__init__(self)
        self.vumi_transport = vumi_transport
        self.request_hang_up = False
        self.current_input = ''
        self.input_type = None
        self.uniquecallid = None

    @inlineCallbacks
    def connectionMade(self):
        yield self.connect().addCallback(self.on_connect)
        yield self.myevents()
        yield self.answer()
        yield self.vumi_transport.register_client(self)

    def on_connect(self, ctx):
        self.uniquecallid = ctx.variable_call_uuid

    def onDtmf(self, ev):
        if self.input_type is None:
            return self.vumi_transport.handle_input(self, ev.DTMF_Digit)
        else:
            if ev.DTMF_Digit == self.input_type:
                ret_value = self.current_input
                self.current_input = ''
                return self.vumi_transport.handle_input(self, ret_value)
            else:
                self.current_input += ev.DTMF_Digit

    def create_tts_command(self, command_template, filename, message):
        params = {"filename": filename, "text": message}
        args = command_template.strip().split()
        cmd, args = args[0], args[1:]
        args = [arg.format(**params) for arg in args]
        return cmd, args

    @inlineCallbacks
    def create_and_stream_text_as_speech(self, folder, command, ext, message):
        key = md5.md5(message).hexdigest()
        filename = os.path.join(folder, "voice-%s.%s" % (key, ext))
        if not os.path.exists(filename):
            log.msg("Generating voice file %r" % (filename,))
            cmd, args = self.create_tts_command(command, filename, message)
            yield getProcessOutput(cmd, args=args)
        else:
            log.msg("Using cached voice file %r" % (filename,))

        yield self.playback(filename)

    @inlineCallbacks
    def send_text_as_speech(self, engine, voice, message):
        yield self.set("tts_engine=" + engine)
        yield self.set("tts_voice=" + voice)
        yield self.execute("speak", message)

    @inlineCallbacks
    def stream_text_as_speech(self, message):
        finalmessage = message.replace("\n", " . ")
        log.msg("TTS: " + finalmessage)
        cfg = self.vumi_transport.config
        if cfg.tts_type == "local":
            yield self.create_and_stream_text_as_speech(
                cfg.tts_local_cache, cfg.tts_local_command,
                cfg.tts_local_ext, finalmessage)
        elif cfg.tts_type == "freeswitch":
            yield self.send_text_as_speech(
                cfg.tts_fs_engine, cfg.tts_fs_voice, finalmessage)
        else:
            raise VoiceError("Unknown tts_type %r" % (
                cfg.tts_type,))

    def get_address(self):
        return self.uniquecallid

    def output_message(self, text):
        return self.stream_text_as_speech(text)

    def output_stream(self, url):
        return self.playback(url)

    def set_input_type(self, input_type):
        self.input_type = input_type

    def close_call(self):
        self.request_hang_up = True

    def onChannelExecuteComplete(self, ev):
        log.msg("execute complete " + ev.variable_call_uuid)
        if self.request_hang_up:
            return self.hangup()

    def onChannelHangup(self, ev):
        log.msg("Channel HangUp")
        self.vumi_transport.deregister_client(self)

    def onDisconnect(self, ev):
        log.msg("Channel disconnect received")
        self.vumi_transport.deregister_client(self)

    def unboundEvent(self, evdata, evname):
        log.msg("Unbound event %r" % (evname,))


class ClientConnectError(Exception):
    """Error for when a call could not be established."""


class FreeSwitchESLClientProtocol(FreeSwitchESLProtocol):
    def __init__(self, vumi_transport, number):
        FreeSwitchESLProtocol.__init__(self, vumi_transport)
        self.uniquecallid = number
        self.job_queue = {}
        self.ready = Deferred()

    @inlineCallbacks
    def connectionMade(self):
        yield self.eventplain("BACKGROUND_JOB CHANNEL_HANGUP")
        yield self.vumi_transport.register_client(self, send_inbound=False)
        self.ready.callback(self)

    def make_call(self):
        def _success(ev):
            response = Deferred()
            self.job_queue[ev.Job_UUID] = response
            return response

        def _error(err):
            raise ClientConnectError(err.value)

        profile = self.vumi_transport.config.sofia_profile
        call_url = "sofia/%s/%s" % (profile, self.uniquecallid)
        d = self.bgapi("originate %s" % (call_url))
        d.addCallback(_success)
        d.addErrback(_error)
        return d

    def onBackgroundJob(self, ev):
        d = self.job_queue.pop(ev.Job_UUID, None)
        if d:
            response, content = ev.rawresponse.split()
            if response == "+OK":
                d.callback(content)
            else:
                d.errback(ev)

    @inlineCallbacks
    def onChannelHangup(self, ev):
        self.vumi_transport.deregister_client(self)
        yield self.transport.loseConnection()


class DialerFactory(ClientFactory):
    def __init__(self, vumi_transport, number):
        self.vumi_transport = vumi_transport
        self.number = number

    def protocol(self):
        return FreeSwitchESLClientProtocol(self.vumi_transport, self.number)


class VoiceServerTransportConfig(Transport.CONFIG_CLASS):
    """
    Configuration parameters for the voice transport
    """

    to_addr = ConfigText(
        "The ``to_addr`` to use for inbound messages.",
        default="freeswitchvoice", static=True)

    tts_type = ConfigText(
        "Either 'freeswitch' or 'local' to specify where TTS is executed.",
        default="freeswitch", static=True)

    tts_fs_engine = ConfigText(
        "Specify Freeswitch TTS engine to use (only affects tts_type"
        " 'freeswitch').",
        default="flite", static=True)

    tts_fs_voice = ConfigText(
        "Specify Freeswitch TTS voice to use (only affects tts_type"
        " 'freeswitch').",
        default="kal", static=True)

    tts_local_command = ConfigText(
        "Specify command template to use for generating voice files (only"
        " affects tts_type 'local'). E.g. 'flite -o {filename} -t {text}'."
        " Command parameters are split on whitespace (no shell-like escape"
        " processing is performed on the command).",
        default=None, static=True)

    tts_local_cache = ConfigText(
        "Specify folder to cache voice files (only affects tts_type"
        " 'local').", default=".", static=True)

    tts_local_ext = ConfigText(
        "Specify the file extension used for cached voice files (only affects"
        " tts_type 'local').", default="wav", static=True)

    twisted_endpoint = ConfigServerEndpoint(
        "The endpoint the voice transport will listen on (and that Freeswitch"
        " will connect to).",
        required=True, default="tcp:port=8084", static=True)

    twisted_client_endpoint = ConfigClientEndpoint(
        "The endpoint the voice transport will send commands to (and that "
        "Freeswitch will listen to).",
        required=True, default=None, static=True)

    sofia_profile = ConfigText(
        "The name of the sofia profile defined in sofia.conf.xml in "
        "FreeSwitch.",
        default="$${profile}", static=True)


class VoiceServerTransport(Transport):
    """
    Transport for Freeswitch Voice Service.

    Voice transports may receive additional hints for how to handle
    outbound messages the ``voice`` section of ``helper_metadata``.
    The ``voice`` section may contain the following keys:

    * ``speech_url``: An HTTP URL from which a custom sound file to
      use for this message. If absent or ``None`` a text-to-speech
      engine will be used to generate suitable sound to play.
      Sound formats supported are: ``.wav``, ``.ogg`` and ``.mp3``.
      The format will be determined by the ``Content-Type`` returned
      by the URL, or by the file extension if the ``Content-Type``
      header is absent. The preferred format is ``.ogg``.

    * ``wait_for``: Gather response characters until the given
      DTMF character is encountered. Commonly either ``#`` or ``*``.
      If absent or ``None``, an inbound message is sent as soon as
      a single DTMF character arrives.

      If no input is seen for some time (configurable in the
      transport config) the voice transport will timeout the wait
      and send the characters entered so far.

      .. todo:

         Maybe ``wait_for`` should default to ``#``? It's not
         discoverable but at least it makes it possible to enter
         multi-digit numbers by default and it's probably simpler
         to add a bit of help text to an application that to
         update it to send ``helper_metadata``.

    Example ``helper_metadata``::

      "helper_metadata": {
          "voice": {
              "speech_url": "http://www.example.com/voice/ab34f611cdee.ogg",
              "wait_for": "#",
          },
      }
    """

    CONFIG_CLASS = VoiceServerTransportConfig

    @inlineCallbacks
    def setup_transport(self):
        log.msg("TRACE: Set Up Transport")
        self._clients = {}

        self.config = self.get_static_config()
        self._to_addr = self.config.to_addr
        self._transport_type = "voice"

        def protocol():
            return FreeSwitchESLProtocol(self)

        factory = ServerFactory()
        factory.protocol = protocol
        self.voice_server = yield self.config.twisted_endpoint.listen(factory)

    @inlineCallbacks
    def create_dialer_client(self, number):
        factory = DialerFactory(self, number)
        voice_client = yield (
            self.config.twisted_client_endpoint.connect(factory))
        yield voice_client.ready
        returnValue(voice_client)

    @inlineCallbacks
    def teardown_transport(self):
        log.msg("TRACE: Tear Down Transport Start")
        if hasattr(self, 'voice_server'):
            # We need to wait for all the client connections to be closed (and
            # their deregistration messages sent) before tearing down the rest
            # of the transport.
            log.msg("TRACE: self._clients=%s" % (self._clients,))
            wait_for_closed = gatherResults([
                client.registration_d for client in self._clients.values()])
            self.voice_server.loseConnection()
            yield wait_for_closed

    def register_client(self, client, send_inbound=True):
        # We add our own Deferred to the client here because we only want to
        # fire it after we're finished with our own deregistration process.
        client.registration_d = Deferred()
        client_addr = client.get_address()
        log.msg("Registering client connected from %r" % client_addr)
        self._clients[client_addr] = client
        if send_inbound:
            self.send_inbound_message(
                client, None, TransportUserMessage.SESSION_NEW)
        log.msg("Register completed")

    def deregister_client(self, client):
        log.msg("TRACE: Deregistering client.")
        client_addr = client.get_address()
        if client_addr in self._clients:
            del self._clients[client_addr]
            self.send_inbound_message(
                client, None, TransportUserMessage.SESSION_CLOSE)
            client.registration_d.callback(None)

    def handle_input(self, client, text):
        self.send_inbound_message(client, text,
                                  TransportUserMessage.SESSION_RESUME)

    def send_inbound_message(self, client, text, session_event):
        self.publish_message(
            from_addr=client.get_address(),
            to_addr=self._to_addr,
            session_event=session_event,
            content=text,
            transport_name=self.transport_name,
            transport_type=self._transport_type,
        )

    @inlineCallbacks
    def handle_outbound_message(self, message):
        text = message['content']
        if text is None:
            text = u''
        text = u"\n".join(text.splitlines())

        client_addr = message['to_addr']
        client = self._clients.get(client_addr)

        if (client is None and message.get('session_event') ==
                TransportUserMessage.SESSION_NEW):
            try:
                client = yield self.create_dialer_client(message['to_addr'])
                yield client.make_call()
            except ClientConnectError:
                yield self.publish_nack(
                    message["message_id"],
                    "Could not make call to client %r" % (client_addr,))
                self.deregister_client(client)
                return

        if client is None:
            yield self.publish_nack(
                message["message_id"],
                "Client %r no longer connected" % (client_addr,))
            return

        text = text.encode('utf-8')
        overrideURL = None
        client.set_input_type(None)
        if 'helper_metadata' in message:
            meta = message['helper_metadata']
            if 'voice' in meta:
                voicemeta = meta['voice']
                client.set_input_type(voicemeta.get('wait_for', None))
                overrideURL = voicemeta.get('speech_url', None)

        if overrideURL is None:
            yield client.output_message("%s\n" % text)
        else:
            yield client.output_stream(overrideURL)

        if message['session_event'] == TransportUserMessage.SESSION_CLOSE:
            client.close_call()

        yield self.publish_ack(message["message_id"], message["message_id"])
