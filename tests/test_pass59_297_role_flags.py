"""PASS-59-297: base.html tells page scripts whether the user is an editor.

toast-controller.js polls /api/ai-fill-bulk/status (editor_required) only
when window.IS_EDITOR is true, so a viewer's pages stop logging 403s.
The flag must let through exactly the roles editor_required does.
"""
import pytest


@pytest.mark.parametrize('role, editor, admin', [
    ('viewer', 'false', 'false'),
    ('player', 'false', 'false'),
    ('editor', 'true', 'false'),
    ('admin', 'true', 'true'),
])
def test_role_flags_match_the_route_guards(admin_test_client, role, editor, admin):
    client, _csrf = admin_test_client(
        user={'id': 1, 'username': f'{role}-stub', 'role': role})
    html = client.get('/help').get_data(as_text=True)
    assert f'window.IS_EDITOR = {editor};' in html
    assert f'window.IS_ADMIN = {admin};' in html
