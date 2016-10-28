"""
Connection to hardware authentication device.

It is used for getting SSH public keys and ECDSA signing of server requests.
"""
import io
import logging

from . import formats, util

log = logging.getLogger(__name__)


class Client(object):
    """Client wrapper for SSH authentication device."""

    def __init__(self, device):
        """Connect to hardware device."""
        device.identity_dict['proto'] = 'ssh'
        self.device = device

    def get_public_key(self):
        """Get SSH public key from the device."""
        with self.device:
            pubkey = self.device.pubkey()

        vk = formats.decompress_pubkey(pubkey=pubkey,
                                       curve_name=self.device.curve_name)
        return formats.export_public_key(vk=vk,
                                         label=self.device.identity_str())

    def sign_ssh_challenge(self, blob):
        """Sign given blob using a private key on the device."""
        msg = _parse_ssh_blob(blob)
        log.debug('%s: user %r via %r (%r)',
                  msg['conn'], msg['user'], msg['auth'], msg['key_type'])
        log.debug('nonce: %r', msg['nonce'])
        log.debug('fingerprint: %s', msg['public_key']['fingerprint'])
        log.debug('hidden challenge size: %d bytes', len(blob))

        log.info('please confirm user "%s" login to "%s" using %s...',
                 msg['user'].decode('ascii'), self.device.identity_str(),
                 self.device)

        with self.device:
            return self.device.sign(blob=blob)


def _parse_ssh_blob(data):
    res = {}
    i = io.BytesIO(data)
    res['nonce'] = util.read_frame(i)
    i.read(1)  # SSH2_MSG_USERAUTH_REQUEST == 50 (from ssh2.h, line 108)
    res['user'] = util.read_frame(i)
    res['conn'] = util.read_frame(i)
    res['auth'] = util.read_frame(i)
    i.read(1)  # have_sig == 1 (from sshconnect2.c, line 1056)
    res['key_type'] = util.read_frame(i)
    public_key = util.read_frame(i)
    res['public_key'] = formats.parse_pubkey(public_key)
    assert not i.read()
    return res
