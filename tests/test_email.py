"""ResendMailer tests. No real HTTP: the requests session is a Mock."""

from unittest.mock import Mock

import pytest
import requests

from investtrack.sources.email import RESEND_URL, Email, EmailUnavailableError, ResendMailer

EMAIL = Email(to="ana@example.com", subject="Oi", text="texto", html="<p>texto</p>")


def mailer_with(session: Mock) -> ResendMailer:
    session.headers = {}
    return ResendMailer("re_test_key", "InvestTrack <no-reply@example.com>", session=session)


def test_sends_through_resend_with_the_key_in_a_header():
    session = Mock(spec=requests.Session)
    response = requests.Response()
    response.status_code = 200
    session.post.return_value = response
    mailer = mailer_with(session)

    mailer.send(EMAIL)

    assert session.headers["Authorization"] == "Bearer re_test_key"
    url = session.post.call_args.args[0]
    payload = session.post.call_args.kwargs["json"]
    assert url == RESEND_URL
    assert payload == {
        "from": "InvestTrack <no-reply@example.com>",
        "to": ["ana@example.com"],
        "subject": "Oi",
        "text": "texto",
        "html": "<p>texto</p>",
    }
    assert session.post.call_args.kwargs["timeout"]  # never wait forever


@pytest.mark.parametrize("status", [401, 422, 500])
def test_provider_errors_become_one_exception(status):
    session = Mock(spec=requests.Session)
    response = requests.Response()
    response.status_code = status
    response.url = RESEND_URL
    session.post.return_value = response
    with pytest.raises(EmailUnavailableError):
        mailer_with(session).send(EMAIL)


def test_network_errors_become_one_exception():
    session = Mock(spec=requests.Session)
    session.post.side_effect = requests.ConnectionError("down")
    with pytest.raises(EmailUnavailableError):
        mailer_with(session).send(EMAIL)
