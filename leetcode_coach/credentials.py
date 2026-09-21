"""Local-only LeetCode credential setup through macOS Keychain, never MCP arguments."""

import argparse
import ctypes as ct
from dataclasses import dataclass, field
import getpass
import json
import re
import sys
import warnings


SERVICE = b'leetcode-coach.leetcode.com'
ACCOUNT = b'session'
NOT_FOUND = -25300


class CredentialError(ValueError):
    pass


@dataclass(frozen=True)
class Credentials:
    session: str = field(repr=False)
    csrf: str = field(repr=False)

    def __post_init__(self):
        for value in (self.session, self.csrf):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=\-]{1,8192}', value):
                raise CredentialError('Enter only the cookie value, without its name, separators, or whitespace.')


class MacKeychain:
    """Small native binding; secrets never enter a subprocess argument or temporary file."""

    def __init__(self):
        if sys.platform != 'darwin':
            raise CredentialError('Authenticated judging requires macOS Keychain. Public tools still work.')
        self.security = ct.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.core = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer, uint = ct.c_void_p, ct.c_uint32
        self.security.SecKeychainFindGenericPassword.argtypes = [pointer, uint, ct.c_char_p, uint, ct.c_char_p,
                                                               ct.POINTER(uint), ct.POINTER(pointer), ct.POINTER(pointer)]
        self.security.SecKeychainAddGenericPassword.argtypes = [pointer, uint, ct.c_char_p, uint, ct.c_char_p,
                                                              uint, pointer, ct.POINTER(pointer)]
        self.security.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, uint, pointer]
        self.security.SecKeychainItemDelete.argtypes = [pointer]
        self.security.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
        for name in ('SecKeychainFindGenericPassword', 'SecKeychainAddGenericPassword',
                     'SecKeychainItemModifyAttributesAndData', 'SecKeychainItemDelete', 'SecKeychainItemFreeContent'):
            getattr(self.security, name).restype = ct.c_int32
        self.core.CFRelease.argtypes = [pointer]
        self.core.CFRelease.restype = None

    def _find(self, length=None, data=None, item=None):
        return self.security.SecKeychainFindGenericPassword(None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT,
                                                            length, data, item)

    @staticmethod
    def _check(status):
        if status == NOT_FOUND:
            raise CredentialError('No LeetCode credential stored. Run python3 -m leetcode_coach.credentials login locally.')
        if status:
            raise CredentialError('Keychain access failed or was denied. Unlock Keychain and retry local login.')

    def read(self):
        size, data = ct.c_uint32(), ct.c_void_p()
        self._check(self._find(ct.byref(size), ct.byref(data)))
        try:
            if not data or not 0 < size.value <= 20_000:
                raise CredentialError('Stored credential has an invalid size. Run local login again.')
            return ct.string_at(data, size.value)
        finally:
            self.security.SecKeychainItemFreeContent(None, data)

    def write(self, value):
        item = ct.c_void_p()
        status = self._find(item=ct.byref(item))
        buffer = ct.create_string_buffer(value)
        try:
            if status == NOT_FOUND:
                status = self.security.SecKeychainAddGenericPassword(None, len(SERVICE), SERVICE, len(ACCOUNT),
                                                                    ACCOUNT, len(value), buffer, None)
            else:
                self._check(status)
                status = self.security.SecKeychainItemModifyAttributesAndData(item, None, len(value), buffer)
            self._check(status)
        finally:
            ct.memset(buffer, 0, len(buffer))
            if item:
                self.core.CFRelease(item)

    def exists(self):
        status = self._find()
        if status == NOT_FOUND:
            return False
        self._check(status)
        return True

    def delete(self):
        item = ct.c_void_p()
        status = self._find(item=ct.byref(item))
        if status == NOT_FOUND:
            return
        self._check(status)
        try:
            self._check(self.security.SecKeychainItemDelete(item))
        finally:
            self.core.CFRelease(item)


def load_credentials():
    raw = MacKeychain().read()
    try:
        values = json.loads(raw)
        return Credentials(values['session'], values['csrf'])
    except (ValueError, TypeError, KeyError):
        raise CredentialError('Stored credential is invalid. Run local login again.') from None


def save_credentials(credentials):
    MacKeychain().write(json.dumps({'session': credentials.session, 'csrf': credentials.csrf}).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('login', 'status', 'logout'))
    args = parser.parse_args()
    try:
        if args.action == 'login':
            if not sys.stdin.isatty():
                raise CredentialError('Run login in your own interactive terminal; do not pass credentials through chat or pipes.')
            print('From your signed-in leetcode.com browser cookies, copy the two values below. Input is hidden.')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                try:
                    credentials = Credentials(getpass.getpass('LEETCODE_SESSION: '), getpass.getpass('csrftoken: '))
                except getpass.GetPassWarning:
                    raise CredentialError('Cannot hide terminal input. Login cancelled; nothing was stored.') from None
            save_credentials(credentials)
            print('Saved in macOS Keychain. This stores credentials; it does not verify the session with LeetCode.')
        elif args.action == 'status':
            print('Credential stored (session validity not checked).' if MacKeychain().exists() else 'No credential stored.')
        else:
            MacKeychain().delete()
            print('Local LeetCode credential removed from Keychain.')
        return 0
    except (EOFError, KeyboardInterrupt):
        print('Login cancelled; nothing was stored.', file=sys.stderr)
        return 2
    except (CredentialError, OSError) as exc:
        message = str(exc) if isinstance(exc, CredentialError) else 'macOS Keychain could not be accessed.'
        print(message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
