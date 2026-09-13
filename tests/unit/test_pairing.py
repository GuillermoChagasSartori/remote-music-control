"""Unit tests for pairing.py: network details and the pairing page content."""

import socket
from types import SimpleNamespace

import pytest

from remote_music_control import pairing
from remote_music_control.pairing import NetworkDetails

TOKEN = "pairing-test-token-0123456789-abcdefghijklmnop"
HOME = NetworkDetails(hostname="studio-pc", ip_address="192.168.1.16", mac_address="AA:BB:CC:DD:EE:FF")


@pytest.fixture
def encoded_texts(monkeypatch):
    """Replace QR generation with a stand-in that records what was encoded.

    The token only appears inside the QR images, which tests can't read back,
    so this is how we check the codes contain the right links.
    """
    texts = []

    def fake_qr(text):
        texts.append(text)
        return f'<svg data-test="qr{len(texts)}"></svg>'

    monkeypatch.setattr(pairing, "qr_code_svg", fake_qr)
    return texts


# --- The page ----------------------------------------------------------------------


def test_qr_codes_contain_the_ip_and_name_pairing_links(encoded_texts):
    pairing.render_pairing_page(TOKEN, 8000, HOME)
    assert encoded_texts == [
        f"http://192.168.1.16:8000/#token={TOKEN}",
        f"http://studio-pc.local:8000/#token={TOKEN}",
    ]


def test_page_shows_the_details_needed_for_a_dhcp_reservation(encoded_texts):
    page = pairing.render_pairing_page(TOKEN, 8000, HOME)
    assert "STUDIO-PC" in page
    assert "AA:BB:CC:DD:EE:FF" in page
    assert "192.168.1.16" in page
    assert "http://192.168.1.1" in page  # router address guess
    assert "http://127.0.0.1:8000/pair" in page


def test_token_is_not_shown_as_text(encoded_texts):
    # Only inside the QR codes, never readable on the page itself.
    assert TOKEN not in pairing.render_pairing_page(TOKEN, 8000, HOME)


def test_uses_the_port_it_was_given(encoded_texts):
    pairing.render_pairing_page(TOKEN, 9123, HOME)
    assert all(":9123/" in text for text in encoded_texts)


def test_page_without_a_network_says_so(encoded_texts):
    offline = NetworkDetails(hostname="studio-pc", ip_address=None, mac_address=None)
    page = pairing.render_pairing_page(TOKEN, 8000, offline)
    assert "doesn't seem to be connected" in page
    assert encoded_texts == [f"http://studio-pc.local:8000/#token={TOKEN}"]  # only the name link


def test_values_are_escaped_so_they_cannot_inject_markup(encoded_texts):
    hostile = NetworkDetails(hostname="<script>x</script>", ip_address="192.168.1.16", mac_address="<b>")
    page = pairing.render_pairing_page(TOKEN, 8000, hostile)
    assert "<script>" not in page
    assert "&lt;SCRIPT&gt;" in page
    assert "<b>" not in page


def test_real_qr_code_is_inline_svg():
    assert pairing.qr_code_svg("http://example").startswith("<svg")


# --- Network details -------------------------------------------------------------------


def address(family, value):
    return SimpleNamespace(family=family, address=value)


def test_mac_address_is_taken_from_the_card_that_has_the_ip(monkeypatch):
    cards = {
        "lo": [address(socket.AF_INET, "127.0.0.1"), address(pairing.psutil.AF_LINK, "00:00:00:00:00:00")],
        "Wi-Fi": [address(pairing.psutil.AF_LINK, "aa-bb-cc-dd-ee-ff"), address(socket.AF_INET, "192.168.1.16")],
    }
    monkeypatch.setattr(pairing.psutil, "net_if_addrs", lambda: cards)
    # Windows reports dashes and lowercase; the page shows the usual AA:BB:... form.
    assert pairing.mac_address_of("192.168.1.16") == "AA:BB:CC:DD:EE:FF"


def test_mac_address_is_none_when_no_card_has_the_ip(monkeypatch):
    monkeypatch.setattr(pairing.psutil, "net_if_addrs", lambda: {"lo": [address(socket.AF_INET, "127.0.0.1")]})
    assert pairing.mac_address_of("192.168.1.16") is None


def test_router_address_guess():
    assert pairing.router_address_guess("192.168.1.16") == "192.168.1.1"
    assert pairing.router_address_guess("10.0.0.57") == "10.0.0.1"


def test_lan_ip_address_is_none_without_a_network(monkeypatch):
    def unreachable(self, target):
        raise OSError("network is unreachable")

    monkeypatch.setattr(socket.socket, "connect", unreachable)
    assert pairing.lan_ip_address() is None
