# -*- test-case-name: vxfreeswitch.tests.test_originate -*-

"""
Utilities for creating originate FreeSwitch API calls.
"""


class OriginateMissingParameter(Exception):
    """ Raised if required originate parameters are missing. """


class OriginateFormatter(object):
    """Helper for constructing originate calls.

    This formatter uses a set of parameters to construct a template. The
    template itself is then used to construct the API call from the to and
    from addresses used by the call. The example lower down should make this
    clearer.

    :param str call_url:
        The Freeswitch sofia 'url' to originate the call to.
        Example: 'sofia/gateway/yogisip/{to_addr}'.

    :param str exten:
        The Freeswitch extension to link the call to. Example: '{from_addr}'.

    :param str cid_name:
        The caller ID name the call should appear from.  Sometimes
        required to be set by external SIP gateways such as Twilio.
        Example: 'yourapp'.

    :param str cid_num:
        The caller ID number the call should appear from.  Sometimes
        required to be set by external SIP gateways such as
        Twilio. Example: '{from_addr}'.

    :param str dialplan:
        The Freeswitch dialplan to use. Default: 'XML'.

    :param str context:
        The Freeswitch context to use. Default: 'default'.

    :param int timeout:
        The seconds to wait before timing out the dialing attempt.

    :raises OriginateParamsError:
        If required format parameters are not supplied.

    The Freeswitch originate API call format is:

      Usage: originate <call_url> <exten>|&<application_name>(<app_args>)
             [<dialplan>] [<context>] [<cid_name>] [<cid_num>] [<timeout>]

    It's rather complex and the details of each value are dependent on
    the Freeswitch configuration.

    E.g. ::

        formatter = OriginateFormatter(
            call_url='sofia/gateway/yogisip/{to_addr}',
            exten='{from_addr}',
            cid_name='vxfreeswitch',
            cid_id='{from_addr}',
        })

        api_call = formatter.format_call(
            to_addr="+1234", from_addr="+100")

        # api_call == (
        #     "originate sofia/gateway/yogisip/+1234 +100 XML default"
        #     " vxfreeswitch +100 60"
    """

    PROTO_TEMPLATE = (
        "originate %(call_url)s %(exten)s %(dialplan)s %(context)s"
        " %(cid_name)s %(cid_num)s %(timeout)s"
    )

    DEFAULT_PARAMS = {
        'dialplan': 'XML',
        'context': 'default',
        'timeout': 60,
    }

    def __init__(self, **kw):
        self.template = self.format_template(**kw)

    def format_call(self, from_addr, to_addr):
        """ Return a formatted originate call.

        :param str from_addr:
            The address the call is from.

        :param str to_addr:
            The address the call is to.

        :returns str:
            A formatted originate call for passing to Freeswitch.
        """
        return self.template.format(
            from_addr=from_addr, to_addr=to_addr)

    @classmethod
    def format_template(cls, **kw):
        """ Format a template for constructing originate calls.

        Parameters are as for the :class:`OriginateFormatter` class.
        """
        d = cls.DEFAULT_PARAMS.copy()
        d.update(kw)
        try:
            return cls.PROTO_TEMPLATE % d
        except KeyError as err:
            raise OriginateMissingParameter(
                "Missing originate parameter %s" % err)
