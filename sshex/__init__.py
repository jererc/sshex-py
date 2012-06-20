import re
import time
import logging

import paramiko


PROMPT = '___PROMPT___'
SUDO_PROMPT = '___SUDOPROMPT___'
RE_SUDO_PROMPT = re.compile(r'%s$' % SUDO_PROMPT)
TERM_WIDTH = 1024
BUFFER_SIZE = 1024
MAX_BUFFER_SIZE = 10000


logger = logging.getLogger(__name__)


class Ssh(object):
    def __init__(self, host, username, password=None, port=22,
                key_filename=None, timeout=10, log_errors=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.chan = None

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(host,
                    port=port,
                    username=username,
                    password=password,
                    key_filename=key_filename,
                    timeout=timeout)
            self.logged = True
        except Exception, e:
            self.logged = False
            if log_errors:
                logger.error('failed to connect to %s@%s: %s', username, host, e)

    def _get_chan(self):
        self.chan = self.client.invoke_shell(width=TERM_WIDTH)
        self.chan.set_combine_stderr(True)
        self.buffer = ''
        self.strip_sent = False
        self.run('PS1="%s"' % PROMPT, get_return_code=False)

    def _send(self, cmd):
        cmd = '%s\n' % cmd
        if self.chan.send_ready():
            res = self.chan.send(cmd)
            if res == len(cmd):
                self.strip_sent = True
                logger.debug('send %s on %s@%s', repr(cmd), self.username, self.host)
                return True

        logger.error('failed to send %s on %s@%s', repr(cmd), self.username, self.host)

    def _recv(self):
        res = ''
        while self.chan.recv_ready():
            res += self.chan.recv(BUFFER_SIZE)
            time.sleep(.01)

        if res:
            logger.debug('recv %s on %s@%s', repr(res), self.username, self.host)
            self.buffer = str(self.buffer + res)[-MAX_BUFFER_SIZE:]
            self.output += res
            if self.strip_sent and '\r\n' in self.output:    # strip sent data from the output
                self.output = self.output.split('\r\n', 1)[-1]
                self.strip_sent = False
            return True

    def _get_return_code(self):
        res = self.run('echo $?', get_return_code=False)[0]
        try:
            return int(res[0])
        except Exception:
            logger.error('failed to get return code from %s: %s', res, repr(self.buffer))

    def _get_expects(self, expects):
        res = []
        for expect, msg in expects:
            if isinstance(expect, str):
                expect = re.compile(expect)
            res.append((expect, msg))
        return res

    def _expect(self, expects):
        for re_, msg in expects[:]:
            if re_.search(self.output):
                expects.remove((re_, msg))
                logger.debug('expect match: %s', repr(re_.pattern))
                return msg

    def run(self, cmd, expects=None, use_sudo=False, timeout=10,
                split_output=True, get_return_code=True):
        '''Run a command on the host and handle prompts.

        :param cmd: command to run
        :param expects: list of tuples (pattern or compiled regex, message to send)
            e.g.: [('\(yes/no\)', 'yes')]
        :param use_sudo: True to run the command with sudo (using the username password)
        :param timeout: timeout in seconds
        :param split_output: True to split the output into lines
        :param get_return_code: True to get the return code

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
        if not self.chan:
            self._get_chan()

        stdout = None
        return_code = None
        started = time.time()
        self.output = ''

        if not self._send(cmd):
            return None, None

        while True:
            if not self._recv():
                if time.time() - started > timeout:
                    logger.error('cmd "%s" timed out: %s', repr(cmd), repr(self.output))
                    break
                time.sleep(.1)
                continue

            if self.output.endswith(PROMPT):
                stdout = self.output.rstrip(PROMPT)
                if split_output:
                    stdout = stdout.splitlines()
                if get_return_code:
                    return_code = self._get_return_code()
                break

            elif expects:
                msg = self._expect(expects)
                if msg:
                    if not self._send(msg):
                        return None, None
                    self.output = ''

        return stdout, return_code
