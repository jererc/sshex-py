#!/usr/bin/env python
import os.path
import json
import unittest
import logging

from sshex import Ssh


logging.basicConfig(level=logging.DEBUG)
logging.getLogger('paramiko').setLevel(logging.CRITICAL)
logging.getLogger('sshex').setLevel(logging.INFO)

conf = {
    'host': 'localhost',
    'username': '',
    'password': '',
    }
try:
    conf_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
            'tests_config.json')
    with open(conf_file) as fd:
        conf.update(json.load(fd))
except Exception, e:
    logging.debug('failed to load tests config: %s' % str(e))


@unittest.skipIf(not conf['username'], 'missing username in config')
class RunTest(unittest.TestCase):

    def setUp(self):
        self.ssh = Ssh(conf['host'], conf['username'], conf['password'])

    def test_invalid_cmd(self):
        stdout, return_code = self.ssh.run('invalid', split_output=False)
        self.assertNotEqual(return_code, 0)

    def test_no_output(self):
        stdout, return_code = self.ssh.run('echo -n', split_output=False)
        self.assertEqual(stdout, '')
        self.assertEqual(return_code, 0)

    def test_cr_output(self):
        stdout, return_code = self.ssh.run('echo', split_output=False)
        self.assertEqual(stdout, '\r\n')
        self.assertEqual(return_code, 0)

    def test_raw_output(self):
        output = 'output'
        stdout, return_code = self.ssh.run('echo %s' % output, split_output=False)
        self.assertEqual(stdout, '%s\r\n' % output)
        self.assertEqual(return_code, 0)

    def test_split_output(self):
        output = 'output'
        stdout, return_code = self.ssh.run('echo %s' % output)
        self.assertEqual(stdout, [output])
        self.assertEqual(return_code, 0)

    def test_cmd_output(self):
        stdout, return_code = self.ssh.run('whoami')
        self.assertEqual(stdout, [conf['username']])
        self.assertEqual(return_code, 0)


@unittest.skipIf(not conf['username'], 'missing username in config')
class RunExpectTest(unittest.TestCase):

    def setUp(self):
        self.ssh = Ssh(conf['host'], conf['username'], conf['password'])

    def test_single_expect(self):
        expected = 'expected_string'
        msg = 'sent_string'
        output = 'output_string'

        cmd = 'echo -n %s; read pw; echo %s' % (expected, output)
        expects = [(expected, msg)]

        stdout, return_code = self.ssh.run(cmd, expects=expects)
        self.assertEqual(stdout, [output])
        self.assertEqual(return_code, 0)

    def test_multiple_expects(self):
        expected_list = ('expected_string0', 'expected_string1')
        msg_list = ('sent_string0', 'sent_string1')
        output = 'output_string'

        cmd = 'echo -n %s; read s1; echo -n %s; read s2; echo %s' % (expected_list[0], expected_list[1], output)
        expects = zip(expected_list, msg_list)

        stdout, return_code = self.ssh.run(cmd, expects=expects)
        self.assertEqual(stdout, [output])
        self.assertEqual(return_code, 0)

    def test_multiple_cmds_and_expects_same_session(self):
        expected_list = ('expected_string0', 'expected_string1')
        msg_list = ('sent_string0', 'sent_string1')
        output = 'output_string'

        cmd = 'echo -n %s; read s1; echo -n %s; read s2; echo %s' % (expected_list[0], expected_list[1], output)
        expects = zip(expected_list, msg_list)

        for i in range(3):
            stdout, return_code = self.ssh.run(cmd, expects=expects)
            self.assertEqual(stdout, [output])
            self.assertEqual(return_code, 0)


@unittest.skipIf(not conf['username'], 'missing username in config')
class RunSudoTest(unittest.TestCase):

    def setUp(self):
        self.ssh = Ssh(conf['host'], conf['username'], conf['password'])

    def test_no_output(self):
        stdout, return_code = self.ssh.run('sudo echo -n', use_sudo=True, split_output=False)
        self.assertEqual(stdout, '')
        self.assertEqual(return_code, 0)

    def test_cr_output(self):
        stdout, return_code = self.ssh.run('sudo echo', use_sudo=True, split_output=False)
        self.assertEqual(stdout, '\r\n')
        self.assertEqual(return_code, 0)

    def test_single_line_output(self):
        stdout, return_code = self.ssh.run('whoami', use_sudo=True)
        self.assertEqual(stdout, ['root'])
        self.assertEqual(return_code, 0)

    def test_same_session(self):
        for i in range(3):
            stdout, return_code = self.ssh.run('whoami', use_sudo=True)
            self.assertEqual(stdout, ['root'])
            self.assertEqual(return_code, 0)


if __name__ == '__main__':
    unittest.main()
