import re
import time
import socket
import logging

import paramiko


PROMPT = '__PROMPT__'
SUDO_PROMPT = '__SUDOPROMPT__'
RE_SUDO_PROMPT = re.compile(r'%s$' % SUDO_PROMPT)
RE_EOL = re.compile(r'\r?\n')
TERM_WIDTH = 1024
BUFFER_SIZE = 1024

logger = logging.getLogger(__name__)


class AuthenticationError(Exception): pass
class TimeoutError(Exception): pass
class SshError(Exception): pass


class Ssh(object):

    def __init__(self, host, username, password=None, port=22, timeout=10,
            max_attempts=3, **kwargs):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.chan = None
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        for i in range(max_attempts):
            try:
                self.client.connect(host, port=port, username=username,
                        password=password, timeout=timeout, **kwargs)
                return
            except (paramiko.BadHostKeyException, paramiko.AuthenticationException), e:
                raise AuthenticationError(str(e))
            except socket.timeout, e:
                raise TimeoutError(str(e))
            except Exception, e:
                if i == max_attempts - 1:
                    raise SshError(str(e))

    def _get_chan(self):
        self.chan = self.client.invoke_shell(width=TERM_WIDTH)
        self.chan.set_combine_stderr(True)
        self.output = ''
        self.strip_sent = False
        self.run('PS1="%s"' % PROMPT, get_return_code=False)

    def _send(self, cmd):
        cmd = '%s\n' % cmd
        if self.chan.send_ready():
            res = self.chan.send(cmd)
            if res == len(cmd):
                self.output = ''
                self.strip_sent = True
                logger.debug('send "%s" on %s@%s' % (repr(cmd), self.username, self.host))
                return True

        logger.error('failed to send "%s" on %s@%s' % (repr(cmd), self.username, self.host))

    def _recv(self, callback=None):
        res = ''
        while self.chan.recv_ready():
            res += self.chan.recv(BUFFER_SIZE)

        if res:
            if callback:
                callback(res)
            logger.debug('recv "%s" on %s@%s' % (repr(res), self.username, self.host))
            self.output += res
            if self.strip_sent and RE_EOL.search(self.output):    # strip sent data from the output
                self.output = RE_EOL.split(self.output, 1)[-1]
                self.strip_sent = False
            return True

    def _get_return_code(self):
        res = self.run('echo $?', get_return_code=False)[0]
        try:
            return int(res[0])
        except Exception:
            logger.error('failed to get return code from "%s": %s' % (repr(res), repr(self.output)))

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
                logger.debug('expect match: "%s"' % repr(re_.pattern))
                return msg

    def run(self, cmd, expects=None, use_sudo=False, timeout=10,
            split_output=True, get_return_code=True, callback=None):
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

        if not self._send(cmd):
            return None, None

        while True:
            if not self._recv(callback=callback):
                if time.time() - started > timeout:
                    logger.error('cmd "%s" timed out on %s@%s: %s' % (cmd, self.username, self.host, repr(self.output)))
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
                if msg and not self._send(msg):
                    break

        return stdout, return_code
