Vumi Freeswitch
===============

A Freeswitch eventsocket transport for `Vumi`_.

.. _Vumi: http://github.com/praekelt/vumi

|vfs-ci|_ |vfs-cover|_

.. |vfs-ci| image:: https://travis-ci.org/praekelt/vumi-freeswitch-esl.png?branch=develop
.. _vfs-ci: https://travis-ci.org/praekelt/vumi-freeswitch-esl

.. |vfs-cover| image:: https://coveralls.io/repos/praekelt/vumi-freeswitch-esl/badge.png?branch=develop
.. _vfs-cover: https://coveralls.io/r/praekelt/vumi-freeswitch-esl

You can contact the Vumi development team in the following ways:

* via *email* by joining the the `vumi-dev@googlegroups.com`_ mailing list
* on *irc* in *#vumi* on the `Freenode IRC network`_

.. _vumi-dev@googlegroups.com: https://groups.google.com/forum/?fromgroups#!forum/vumi-dev
.. _Freenode IRC network: https://webchat.freenode.net/?channels=#vumi

Issues can be filed in the GitHub issue tracker. Please don't use the issue
tracker for general support queries.

Usage
-----

Voice transports may receive additional hints for how to handle outbound
messages in the ``voice`` section of ``helper_metadata``. The ``voice`` section
may contain the following keys:

:``speech_url``:
    The URL where the voice file to be played can be found. If this field is
    absent or ``None``, a text-to-speech engine will be used to generate a
    suitable sound from the message ``content``, otherwise this voice file
    will be played.

    This can either be a string containing the URL, or a list of strings
    containing URLs to sound files that should be joined to form the message.
:``wait_for``:
    Gather response characters until the given DTMF character is encountered.
    Commonly either ``#`` or ``*``. If absent or ``None``, an inbound message
    is sent as soon as a single DTMF character arrives.
:``barge_in``:
    A boolean value that if ``True``, stops the playback of the message when
    a DTMF character arrives. This allows the response to the input to be
    played immediately, rather than waiting for the first message to finish
    playing before hearing the response message. Defaults to ``False``.
:``tries``:
   If ``barge_in`` is ``True``, this will set the number of times a message is
   played if no input is received. Defaults to ``1``.
:``time_gap``:
   If ``barge_in`` is ``True`` and ``tries`` is greater than ``1``, this
   specifies the length of the pause (in ms) that is given before repeating
   the message, if no DTMF characters are received. Defaults to ``3000``.

Example:

::

    "helper_metadata": {
        "voice": {
            "speech_url": [
                "http://www.example.com/voice/ab34f611cdee.ogg",
                "http://www.example.com/voice/cd43f622dcef.ogg"
            ],
            "wait_for": "#",
            "barge_in": True,
            "tries": 3,
            "time_gap": 5000,
        },
    }
