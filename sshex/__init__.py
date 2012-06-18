import re
import time
import logging

import paramiko


PROMPT = '___PROMPT___'
SUDO_PROMPT = '___SUDOPROMPT___'
RE_SUDO_PROMPT = re.compile(r'%s$' % SUDO_PROMPT)
CONNECTION_TIMEOUT = 10
TERM_WIDTH = 1024
BUFFER_SIZE = 1024


logger = logging.getLogger(__name__)


class Ssh(object):
    def __init__(self, host, username, password=None, port=22, key_filename=None, timeout=CONNECTION_TIMEOUT, log_errors=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.shell = None

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

    def _get_return_code(self):
        res = self.run('echo $?', get_return_code=False)[0]
        try:
            return int(res[0])
        except Exception:
            logger.error('failed to get return code from %s: %s', res, self.buffer)

    def _get_expects(self, expects):
        res = []
        for expect, msg in expects:
            if isinstance(expect, str):
                expect = re.compile(expect)
            res.append((expect, msg))
        return res

    def _get_shell(self):
        self.shell = self.client.invoke_shell()
        self.shell.resize_pty(width=TERM_WIDTH)
        self.shell.set_combine_stderr(True)
        self.buffer = ''
        self.run('PS1="%s"' % PROMPT, get_return_code=False)

    def _send(self, cmd):
        logger.debug('send %s on %s@%s', repr(cmd), self.username, self.host)
        self.shell.send('%s\n' % cmd)

    def _recv(self):
        '''Receive data until the buffer is empty.
        '''
        res = ''
        while self.shell.recv_ready():
            res += self.shell.recv(BUFFER_SIZE)

        if res:
            logger.debug('recv %s on %s@%s', repr(res), self.username, self.host)
            self.buffer += res
            return res

    def _strip_last_line(self, data):
        if '\r\n' in data:
            return data.rsplit('\r\n', 1)[0]
        return ''

    def run(self, cmd, expects=None, use_sudo=False, timeout=10, split_output=True, get_return_code=True):
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
            cmd = 'sudo -p %s %s' % (SUDO_PROMPT, cmd)
            if self.password:
                expects.insert(0, (RE_SUDO_PROMPT, self.password))

        if expects:
            expects = self._get_expects(expects)
        if not self.shell:
            self._get_shell()

        stdout = None
        return_code = None
        strip_first_line = True
        started = time.time()
        buf = ''

        self._send(cmd)
        while True:
            res = self._recv()
            if not res:
                if time.time() - started > timeout:
                    logger.error('cmd "%s" timed out: %s', cmd, buf)
                    break
                time.sleep(.1)

            else:
                if strip_first_line:
                    res = res.split('\r\n', 1)[-1]
                    strip_first_line = False

                buf += res

                if buf.endswith(PROMPT):
                    stdout = re.sub(r'%s(\r\n)*' % PROMPT, '', buf)
                    if split_output:
                        stdout = stdout.splitlines()
                    if get_return_code:
                        return_code = self._get_return_code()
                    break

                elif expects:
                    for expect, msg in expects[:]:
                        if expect.search(buf):
                            logger.debug('expect match: %s', repr(expect.pattern))
                            expects.remove((expect, msg))
                            self._send(msg)
                            strip_first_line = True     # for sent message removal
                            buf = self._strip_last_line(buf)     # remove the matched expect
                            break

        return stdout, return_code
