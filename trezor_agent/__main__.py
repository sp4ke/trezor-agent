"""SSH-agent implementation using hardware authentication devices."""
import argparse
import functools
import logging
import re
import os
import subprocess
import sys
import time

from . import client, formats, protocol, server

log = logging.getLogger(__name__)


def ssh_args(label):
    """Create SSH command for connecting specified server."""
    identity = client.string_to_identity(label, identity_type=dict)

    args = []
    if 'port' in identity:
        args += ['-p', identity['port']]
    if 'user' in identity:
        args += ['-l', identity['user']]

    return ['ssh'] + args + [identity['host']]


def create_parser():
    """Create argparse.ArgumentParser for this tool."""
    p = argparse.ArgumentParser()
    p.add_argument('-v', '--verbose', default=0, action='count')

    curve_names = [name.decode('ascii') for name in formats.SUPPORTED_CURVES]
    curve_names = ', '.join(sorted(curve_names))
    p.add_argument('-e', '--ecdsa-curve-name', metavar='CURVE',
                   default=formats.CURVE_NIST256,
                   help='specify ECDSA curve name: ' + curve_names)
    p.add_argument('--timeout',
                   default=server.UNIX_SOCKET_TIMEOUT, type=float,
                   help='Timeout for accepting SSH client connections')
    p.add_argument('--debug', default=False, action='store_true',
                   help='Log SSH protocol messages for debugging.')
    p.add_argument('command', type=str, nargs='*', metavar='ARGUMENT',
                   help='command to run under the SSH agent')
    return p

def create_agent_parser():
    p = create_parser()
    p.add_argument('identity', type=str, default=None,
                   help='proto://[user@]host[:port][/path]')

    g = p.add_mutually_exclusive_group()
    g.add_argument('-s', '--shell', default=False, action='store_true',
                   help='run ${SHELL} as subprocess under SSH agent')
    g.add_argument('-c', '--connect', default=False, action='store_true',
                   help='connect to specified host via SSH')
    g.add_argument('-g', '--git', default=False, action='store_true',
                   help='run git using specified identity as remote name')
    return p


def setup_logging(verbosity):
    """Configure logging for this tool."""
    fmt = ('%(asctime)s %(levelname)-12s %(message)-100s '
           '[%(filename)s:%(lineno)d]')
    levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    level = levels[min(verbosity, len(levels) - 1)]
    logging.basicConfig(format=fmt, level=level)


def git_host(remote_name):
    """Extract git SSH host for specified remote name."""
    output = subprocess.check_output('git config --local --list'.split())
    pattern = r'remote\.{}\.url=(.*)'.format(remote_name)
    matches = re.findall(pattern, output)
    log.debug('git remote "%r": %r', remote_name, matches)
    if len(matches) != 1:
        raise ValueError('{:d} git remotes found: %s', matches)
    url = matches[0].strip()
    user, url = url.split('@', 1)
    host, path = url.split(':', 1)
    return 'ssh://{}@{}/{}'.format(user, host, path)


def ssh_sign(conn, label, blob):
    """Perform SSH signature using given hardware device connection."""
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    return conn.sign_ssh_challenge(label=label, blob=blob, visual=now)


def run_agent(client_factory):
    """Run ssh-agent using given hardware client factory."""
    args = create_agent_parser().parse_args()
    setup_logging(verbosity=args.verbose)

    with client_factory(curve=args.ecdsa_curve_name) as conn:
        label = args.identity
        command = args.command

        if args.git:
            label = git_host(remote_name=label)
            log.debug('Git identity: %r', label)
            if command:
                command = ['git'] + command
                log.debug('Git command: %r', command)

        public_key = conn.get_public_key(label=label)

        if args.connect:
            command = ssh_args(label) + args.command
            log.debug('SSH connect: %r', command)

        use_shell = bool(args.shell)
        if use_shell:
            command = os.environ['SHELL']
            log.debug('using shell: %r', command)

        if not command:
            sys.stdout.write(public_key)
            return

        try:
            signer = functools.partial(ssh_sign, conn=conn)
            public_keys = [formats.import_public_key(public_key)]
            handler = protocol.Handler(keys=public_keys, signer=signer,
                                       debug=args.debug)
            with server.serve(handler=handler, timeout=args.timeout) as env:
                return server.run_process(command=command,
                                          environ=env,
                                          use_shell=use_shell)
        except KeyboardInterrupt:
            log.info('server stopped')


def main():
    """Main entry point (see setup.py)."""
    run_agent(client.Client)
