import re
import time
import logging

import paramiko


CONNECTION_TIMEOUT = 10
PROMPT = '###PROMPT###'
BUFFER_SIZE = 1024


logger = logging.getLogger(__name__)


class Ssh(object):
    def __init__(self, host, username, password=None, port=22, key_filename=None, timeout=CONNECTION_TIMEOUT, log_errors=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(host,
                    port=port,
                    username=username,
                    password=password,
                    key_filename=key_filename,
                    timeout=CONNECTION_TIMEOUT)
            self.logged = True
        except Exception, e:
            self.logged = False
            if log_errors:
                logger.error('failed to connect to %s@%s: %s', username, host, e)

    def _get_output(self, cmd):
        '''Get command output as a list of lines.
        '''
        logger.debug('running cmd "%s" on %s@%s', cmd, self.username, self.host)
        self.shell.send('%s\n' % cmd)

        buf = ''
        for i in range(30):
            if self.shell.recv_ready():
                res = self.shell.recv(BUFFER_SIZE)
                res = res.split('\n', 1)[-1]     # strip the command
                buf += res
                if res.endswith(PROMPT):
                    return buf.splitlines()[:-1]    # # strip the prompt line
            time.sleep(.1)

    def _get_return_code(self):
        res = self._get_output('echo $?')
        if res:
            try:
                return int(res[0])
            except Exception:
                logger.error('failed to get return code from "%s"', res)

    def _get_expects(self, expects):
        res = []
        for expect, msg in expects:
            if isinstance(expect, str):
                expect = re.compile(expect)
            res.append((expect, msg))
        return res

    def _get_shell(self):
        self.shell = self.client.invoke_shell()
        self.shell.set_combine_stderr(True)
        self._get_output('PS1="%s"' % PROMPT)

    def run(self, cmd, expects=None, use_sudo=False, timeout=10, split_output=True):
        '''Run a command on the host and handle prompts.

        :param cmd: command to run
        :param expects: list of tuples (expect pattern or compiled regex, msg to send)
            e.g.: [('\(yes/no\)', 'yes')]
        :param use_sudo: True to run the command with sudo (using the username password)
        :param timeout: timeout in seconds
        :param split_output: True to split the output into lines

        :return: tuple (stdout, return code)
        '''
        if not expects:
            expects = []
        if use_sudo:
            cmd = 'sudo %s' % cmd
            if self.password:
                expects.insert(0, (r'(?i)\bpassword\b', self.password))

        expects = self._get_expects(expects)

        self._get_shell()

        logger.debug('running cmd "%s" on %s@%s', cmd, self.username, self.host)
        self.shell.send('%s\n' % cmd)

        stdout = None
        return_code = None
        buf = ''
        lstrip_line = True
        started = time.time()

        while True:
            if self.shell.recv_ready():
                res = self.shell.recv(BUFFER_SIZE)
                if lstrip_line:
                    res = res.split('\n', 1)[-1]     # strip the command
                    lstrip_line = False

                buf += res

                if buf.endswith(PROMPT):
                    stdout = buf.rsplit('\n', 1)[0]  # strip the prompt line
                    if split_output:
                        stdout = stdout.splitlines()

                    return_code = self._get_return_code()
                    break

                else:
                    for expect, msg in expects[:]:
                        if expect.search(buf):
                            expects.remove((expect, msg))
                            self.shell.send('%s\n' % msg)
                            lstrip_line = True
                            buf = ''
                            break

            if time.time() - started > timeout:
                logger.error('cmd "%s" timed out: %s', cmd, buf)
                break

            time.sleep(.1)

        return stdout, return_code
