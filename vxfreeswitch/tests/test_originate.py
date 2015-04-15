""" Tests for vxfreeswitch.originate. """

from twisted.trial.unittest import TestCase

from vxfreeswitch.originate import (
    OriginateFormatter, OriginateMissingParameter)


class TestOriginateFormatter(TestCase):
    def mk_params(self, **kw):
        params = {
            'call_url': 'sofia/gateway/yogisip/{to_addr}',
            'exten': '100',
            'cid_name': 'elcid',
            'cid_num': '{from_addr}',
        }
        params.update(kw)
        params = dict((k, v) for k, v in params.items() if v is not None)
        return params

    def mk_template(self, **kw):
        return OriginateFormatter.format_template(**self.mk_params(**kw))

    def mk_formatter(self, **kw):
        return OriginateFormatter(**self.mk_params(**kw))

    def test_format_template(self):
        self.assertEqual(
            self.mk_template(),
            "originate sofia/gateway/yogisip/{to_addr}"
            " 100 XML default elcid {from_addr} 60")

    def test_format_template_missing_parameter(self):
        err = self.assertRaises(
            OriginateMissingParameter,
            self.mk_template, call_url=None)
        self.assertEqual(str(err), "Missing originate parameter 'call_url'")

    def test_init(self):
        formatter = self.mk_formatter()
        self.assertEqual(
            formatter.template,
            "originate sofia/gateway/yogisip/{to_addr}"
            " 100 XML default elcid {from_addr} 60")

    def test_init_missing_parameter(self):
        err = self.assertRaises(
            OriginateMissingParameter,
            self.mk_formatter, cid_name=None)
        self.assertEqual(str(err), "Missing originate parameter 'cid_name'")

    def test_format_call(self):
        formatter = self.mk_formatter()
        self.assertEqual(
            formatter.format_call(to_addr="+1234", from_addr="1099"),
            "originate sofia/gateway/yogisip/+1234"
            " 100 XML default elcid 1099 60")
