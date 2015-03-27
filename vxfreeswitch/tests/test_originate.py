""" Tests for vxfreeswitch.originate. """

from twisted.trial.unittest import TestCase

from vxfreeswitch.originate import (
    OriginateFormatter, OriginateMissingParameter)


class TestOriginateFormatter(TestCase):
    def mk_template(self, **kw):
        params = {
            'call_url': 'sofia/gateway/yogisip/{to_addr}',
            'exten': '100',
            'cid_name': 'elcid',
            'cid_num': '1099',
        }
        params.update(kw)
        params = dict((k, v) for k, v in params.items() if v is not None)
        return OriginateFormatter.format_template(**params)

    def test_format_template(self):
        self.assertEqual(
            self.mk_template(),
            "originate sofia/gateway/yogisip/{to_addr}"
            " 100 XML default elcid 1099 60"
        )

    def test_format_template_missing_parameters(self):
        err = self.assertRaises(
            OriginateMissingParameter,
            self.mk_template, call_url=None,
        )
        self.assertEqual(str(err), "Missing originate parameter 'call_url'")
