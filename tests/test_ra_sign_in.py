"""RetroAchievements sign-in: the password goes once to
retroachievements.org and only the token it returns is kept, per user. No test
reaches the network.
"""
import json

import pytest
import requests

from services import platform_tokens, ra_sign_in
from services.database import execute, query

_CSRF_TOKEN = 'tok'
PASSWORD = 'correct-horse-battery'
TOKEN = 'connect-token-abc'


class _Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError('not JSON')
        return self._body


@pytest.fixture
def users(setup_complete):
    ids = [execute("INSERT INTO users (username, password_hash, role) VALUES (?, 'x', 'viewer')",
                   (f'ra-sign-in-{n}',)) for n in (1, 2)]
    yield ids
    for uid in ids:
        execute("DELETE FROM user_platform_tokens WHERE user_id = ?", (uid,))
        execute("DELETE FROM users WHERE id = ?", (uid,))


@pytest.fixture
def ra(monkeypatch):
    """Records each request and answers with `ra['reply']`."""
    state = {'reply': _Reply(200, {'Success': True, 'User': 'Ants', 'Token': TOKEN}), 'calls': []}

    def post(url, data=None, headers=None, timeout=None, allow_redirects=True):
        state['calls'].append({'url': url, 'data': data, 'headers': headers,
                               'timeout': timeout, 'redirects': allow_redirects})
        if isinstance(state['reply'], Exception):
            raise state['reply']
        return state['reply']
    monkeypatch.setattr('services.ra_sign_in.requests.post', post)
    return state


def test_sign_in_sends_the_password_to_retroachievements_only(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    call = ra['calls'][0]
    assert call['url'] == 'https://retroachievements.org/dorequest.php'
    assert call['data'] == {'r': 'login2', 'u': 'ants', 'p': PASSWORD}
    assert PASSWORD not in call['url']
    assert 'RetroDB' in call['headers']['User-Agent']
    assert call['timeout'] and call['redirects'] is False


def test_only_the_token_is_kept(users, ra):
    assert ra_sign_in.sign_in(users[0], 'ants', PASSWORD) == {
        'signed_in': True, 'username': 'Ants', 'hardcore': False}
    assert platform_tokens.load_tokens(users[0], 'retroachievements') == {
        'username': 'Ants', 'token': TOKEN, 'hardcore': False}
    row = query("SELECT tokens FROM user_platform_tokens WHERE user_id = ?", (users[0],), one=True)
    assert PASSWORD not in row['tokens']


@pytest.mark.parametrize('reply, wanted', [
    (_Reply(401, {'Success': False, 'Error': 'Invalid user/password combination.'}),
     'Invalid user/password'),
    (_Reply(200, {'Success': False, 'Error': 'Account banned.'}), 'Account banned'),
    (_Reply(200, {'Success': True, 'User': 'Ants'}), 'did not sign you in'),
    (_Reply(200, {'Success': True, 'User': 'Ants', 'Token': 7}), 'did not sign you in'),
    (_Reply(500, None), 'did not sign you in'),
    (_Reply(301, None), 'did not sign you in'),
    (requests.ConnectionError('boom'), 'Could not reach'),
])
def test_failed_sign_in_keeps_nothing(users, ra, reply, wanted):
    ra['reply'] = reply
    with pytest.raises(ra_sign_in.SignInError, match=wanted):
        ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert platform_tokens.load_tokens(users[0], 'retroachievements') is None


def test_failed_sign_in_keeps_the_earlier_sign_in(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    ra['reply'] = _Reply(401, {'Success': False, 'Error': 'Invalid user/password combination.'})
    with pytest.raises(ra_sign_in.SignInError):
        ra_sign_in.sign_in(users[0], 'ants', 'wrong')
    assert ra_sign_in.status(users[0])['signed_in'] is True


@pytest.mark.parametrize('username, password', [('', PASSWORD), ('ants', ''), ('  ', PASSWORD)])
def test_empty_fields_send_nothing(users, ra, username, password):
    with pytest.raises(ra_sign_in.SignInError):
        ra_sign_in.sign_in(users[0], username, password)
    assert ra['calls'] == []


def test_the_password_is_never_logged(users, ra, caplog):
    caplog.set_level('DEBUG')
    ra['reply'] = requests.ConnectionError(f'failed with {PASSWORD}')
    with pytest.raises(ra_sign_in.SignInError) as e:
        ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert PASSWORD not in caplog.text and PASSWORD not in str(e.value)


def test_sign_out_forgets_the_token(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    ra_sign_in.sign_out(users[0])
    assert ra_sign_in.status(users[0]) == {'signed_in': False, 'username': '', 'hardcore': False}
    assert ra_sign_in.launch_keys(users[0]) == {}


def test_each_user_has_their_own_sign_in(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert ra_sign_in.status(users[1])['signed_in'] is False
    assert ra_sign_in.launch_keys(users[1]) == {}


def test_hardcore_is_off_until_chosen_and_survives_signing_in_again(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert ra_sign_in.launch_keys(users[0])['cheevos_hardcore_mode_enable'] == 'false'
    ra_sign_in.set_hardcore(users[0], True)
    assert ra_sign_in.launch_keys(users[0])['cheevos_hardcore_mode_enable'] == 'true'
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert ra_sign_in.status(users[0])['hardcore'] is True


def test_hardcore_needs_a_sign_in(users):
    with pytest.raises(ra_sign_in.SignInError):
        ra_sign_in.set_hardcore(users[0], True)


def test_launch_keys_are_what_retroarch_reads(users, ra):
    ra_sign_in.sign_in(users[0], 'ants', PASSWORD)
    assert ra_sign_in.launch_keys(users[0]) == {
        'cheevos_enable': 'true',
        'cheevos_username': 'Ants',
        'cheevos_token': TOKEN,
        'cheevos_hardcore_mode_enable': 'false',
    }


@pytest.mark.parametrize('user_id', [None, 0])
def test_no_user_no_keys(user_id):
    assert ra_sign_in.launch_keys(user_id) == {}


def test_a_bad_record_counts_as_signed_out(users):
    platform_tokens.save_tokens(users[0], 'retroachievements', {'username': 'Ants'})
    assert ra_sign_in.status(users[0])['signed_in'] is False
    assert ra_sign_in.launch_keys(users[0]) == {}


# -----------------------------------------------------------------------------
# The routes
# -----------------------------------------------------------------------------

def _client(monkeypatch, user_id, role='viewer'):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': user_id, 'username': 'tester', 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF_TOKEN
    return client


HEADERS = {'X-CSRF-Token': _CSRF_TOKEN}
URL = '/api/retroachievements/sign-in'


def test_any_signed_in_user_can_sign_in_for_themselves(monkeypatch, users, ra):
    client = _client(monkeypatch, users[0])
    rv = client.post(URL, json={'username': 'ants', 'password': PASSWORD}, headers=HEADERS)
    assert rv.status_code == 200, rv.data
    body = rv.get_json()
    assert body['signed_in'] is True and body['username'] == 'Ants'
    assert TOKEN not in json.dumps(body) and PASSWORD not in json.dumps(body)
    status = client.get(URL).get_json()
    assert status['signed_in'] is True and TOKEN not in json.dumps(status)


def test_a_refused_password_is_a_400_with_the_reason(monkeypatch, users, ra):
    ra['reply'] = _Reply(401, {'Success': False, 'Error': 'Invalid user/password combination.'})
    rv = _client(monkeypatch, users[0]).post(
        URL, json={'username': 'ants', 'password': 'nope'}, headers=HEADERS)
    assert rv.status_code == 400
    assert 'Invalid user/password' in rv.get_json()['error']


def test_routes_need_the_csrf_token(monkeypatch, users, ra):
    rv = _client(monkeypatch, users[0]).post(URL, json={'username': 'a', 'password': 'b'})
    assert rv.status_code == 403 and ra['calls'] == []


def test_signed_out_visitors_are_refused(monkeypatch, setup_complete, ra):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    assert app_module.app.test_client().get(URL).status_code in (302, 401, 403)


def test_sign_out_and_hardcore_routes(monkeypatch, users, ra):
    client = _client(monkeypatch, users[0])
    client.post(URL, json={'username': 'ants', 'password': PASSWORD}, headers=HEADERS)
    rv = client.put('/api/retroachievements/hardcore', json={'on': True}, headers=HEADERS)
    assert rv.status_code == 200 and rv.get_json()['hardcore'] is True
    rv = client.delete(URL, headers=HEADERS)
    assert rv.status_code == 200 and rv.get_json()['signed_in'] is False
    rv = client.put('/api/retroachievements/hardcore', json={'on': True}, headers=HEADERS)
    assert rv.status_code == 400
