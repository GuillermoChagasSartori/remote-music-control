"""The pairing page: how a new phone or computer gets the server's address and token.

The page shows QR codes of the pairing links, so a phone can connect by
scanning the screen of the server PC, plus the details needed to stop the PC's
address from changing (a DHCP reservation on the router).

It contains the token, so api.py only serves it to the server PC itself.
"""

import html
import socket
from dataclasses import dataclass
from pathlib import Path
from string import Template

import psutil
import segno

TEMPLATE_PATH = Path(__file__).parent / "web" / "pair.html"


@dataclass(frozen=True)
class NetworkDetails:
    hostname: str  # computer name, lowercase, as used in "<name>.local"
    ip_address: str | None  # None if the PC doesn't seem to be on a network
    mac_address: str | None  # the network card the IP belongs to


def lan_ip_address() -> str | None:
    """Best guess at this PC's address on the local network, or None.

    "Connecting" a UDP socket sends no packets; it only makes the operating
    system pick the network interface it would use to reach that address, and
    getsockname() then reports that interface's IP. The target is a reserved
    documentation address (TEST-NET-1), so nothing real is ever involved.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


def mac_address_of(ip_address: str) -> str | None:
    """The hardware (MAC) address of the network card that has `ip_address`.

    A router identifies devices by MAC address when reserving an IP for them.
    psutil lists each network card with all its addresses; we find the card
    holding our IP and return its hardware address, formatted AA:BB:CC:DD:EE:FF.
    """
    for card_addresses in psutil.net_if_addrs().values():
        has_our_ip = any(
            address.family == socket.AF_INET and address.address == ip_address for address in card_addresses
        )
        if has_our_ip:
            for address in card_addresses:
                if address.family == psutil.AF_LINK:
                    return address.address.replace("-", ":").upper()  # Windows uses dashes
    return None


def current_network() -> NetworkDetails:
    ip_address = lan_ip_address()
    return NetworkDetails(
        hostname=socket.gethostname().lower(),
        ip_address=ip_address,
        mac_address=mac_address_of(ip_address) if ip_address else None,
    )


def qr_code_svg(text: str) -> str:
    """An inline <svg> QR code for `text`.

    Black on white with a 4-module quiet zone (the blank border scanners need),
    set explicitly so the code stays scannable even when the page is dark.
    Error correction level M lets a phone read it despite screen glare.
    """
    return segno.make(text, error="m").svg_inline(scale=5, border=4, dark="#000000", light="#ffffff")


def router_address_guess(ip_address: str) -> str:
    """Home routers are almost always the first address of the network (x.x.x.1)."""
    return ip_address.rsplit(".", 1)[0] + ".1"


def render_pairing_page(token: str, port: int, network: NetworkDetails) -> str:
    """Fill the HTML template with this PC's links, QR codes and network details.

    string.Template (standard library) replaces $placeholders in the HTML file.
    Every value is passed through html.escape() first, so nothing can be
    interpreted as markup — except the QR <svg>, which segno generates itself.
    """
    name_link = f"http://{network.hostname}.local:{port}/#token={token}"

    if network.ip_address:
        ip_link = f"http://{network.ip_address}:{port}/#token={token}"
        ip_qr = qr_code_svg(ip_link)
        ip_address_text = network.ip_address
        router_text = f"http://{router_address_guess(network.ip_address)}"
    else:
        ip_qr = '<p class="warning">This PC doesn\'t seem to be connected to a network.</p>'
        ip_address_text = "unknown"
        router_text = "unknown"

    values = {
        "hostname": network.hostname.upper(),
        "ip_address": ip_address_text,
        "mac_address": network.mac_address or "unknown",
        "router_address": router_text,
        "port": str(port),
        "name_address": f"{network.hostname}.local:{port}",
    }
    escaped = {key: html.escape(value) for key, value in values.items()}
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(escaped, ip_qr=ip_qr, name_qr=qr_code_svg(name_link))
