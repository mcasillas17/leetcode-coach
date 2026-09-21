import unittest
from unittest.mock import patch

from leetcode_coach.credentials import CredentialError, Credentials, load_credentials, save_credentials


class CredentialTests(unittest.TestCase):
    def test_credentials_validate_cookie_values_without_echoing_them(self):
        for session, csrf in [('secret; injected=value', 'valid'), ('secret\nvalue', 'valid'), ('', 'valid'), ('valid', '')]:
            with self.assertRaises(CredentialError) as error:
                Credentials(session, csrf)
            self.assertNotIn('secret', str(error.exception))
        self.assertNotIn('fixture-session', repr(Credentials('fixture-session', 'fixture-csrf')))

    def test_keychain_round_trip_and_bad_data_errors_do_not_expose_token(self):
        with patch('leetcode_coach.credentials.MacKeychain') as keychain:
            stored = []
            keychain.return_value.write.side_effect = stored.append
            save_credentials(Credentials('fixture-session', 'fixture-csrf'))
            keychain.return_value.read.return_value = stored[0]
            self.assertEqual(load_credentials().session, 'fixture-session')
            keychain.return_value.read.return_value = b'{invalid-secret'
            with self.assertRaises(CredentialError) as error:
                load_credentials()
            self.assertNotIn('invalid-secret', str(error.exception))

    def test_login_refuses_echo_fallback_without_storing_credentials(self):
        import getpass
        import io
        import warnings
        from leetcode_coach.credentials import main
        def fallback(prompt):
            warnings.warn('Password input may be echoed.', getpass.GetPassWarning)
            return 'fixture-token'
        with patch('sys.argv', ['credentials', 'login']), patch('sys.stdin.isatty', return_value=True), \
                patch('getpass.getpass', side_effect=fallback), patch('sys.stderr', io.StringIO()), \
                patch('sys.stdout', io.StringIO()), patch('leetcode_coach.credentials.save_credentials') as save:
            self.assertEqual(main(), 2)
            save.assert_not_called()
