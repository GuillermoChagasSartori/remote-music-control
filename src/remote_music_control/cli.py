"""The `music` command-line client.

A thin HTTP client: it parses the command, sends requests to the server, and
prints the result. It contains no media logic of its own, so the CLI and the
web UI can never disagree about behaviour.
"""

import argparse
import sys
from typing import Any

import httpx

from .config import load_client_settings
from .media_controller import MAX_VOLUME, MIN_VOLUME

# Generous enough for a slow Wi-Fi hop, short enough that a dead server is
# reported quickly instead of the terminal appearing to hang.
REQUEST_TIMEOUT_SECONDS = 3.0

# (command name, API path, help text) for the actions that take no arguments.
TRANSPORT_COMMANDS = (
    ("play", "/api/play", "resume playback"),
    ("pause", "/api/pause", "pause playback"),
    ("toggle", "/api/play-pause", "play if paused, pause if playing"),
    ("next", "/api/next", "skip to the next track"),
    ("prev", "/api/previous", "go back to the previous track"),
)

STATUS_SYMBOLS = {"playing": "▶", "paused": "⏸", "stopped": "■"}


# --- Output formatting (pure functions: JSON in, text out) ---


def format_state(state: dict[str, Any]) -> str:
    track = state["now_playing"]
    if track is None:
        return "nothing playing (no media session — is the player open?)"
    symbol = STATUS_SYMBOLS.get(track["status"], "?")
    line = f"{symbol} {track['title']} — {track['artist']}"
    if track["album"]:
        line += f" ({track['album']})"
    return f"{line}\n{format_volume(state)}"


def format_volume(volume: dict[str, Any]) -> str:
    text = f"volume {volume['volume']}%"
    if volume["muted"]:
        text += " (muted)"
    return text


# --- Command handlers: each receives the HTTP client and the parsed arguments ---


def run_health(client: httpx.Client, args: argparse.Namespace) -> None:
    data = request(client, "GET", "/health")
    print(f"server ok — controller: {data['controller']}")


def run_now(client: httpx.Client, args: argparse.Namespace) -> None:
    print(format_state(request(client, "GET", "/api/state")))


def run_transport(client: httpx.Client, args: argparse.Namespace) -> None:
    request(client, "POST", args.path)
    # Show the result so `music next` tells you what is playing now.
    run_now(client, args)


def run_volume(client: httpx.Client, args: argparse.Namespace) -> None:
    if args.level is None:
        data = request(client, "GET", "/api/volume")
    else:
        data = request(client, "PUT", "/api/volume", json={"level": args.level})
    print(format_volume(data))


def run_volume_step(client: httpx.Client, args: argparse.Namespace) -> None:
    # Only send ?step= when the user gave one, so the server's default applies.
    params = {} if args.step is None else {"step": args.step}
    print(format_volume(request(client, "POST", args.path, params=params)))


def run_mute(client: httpx.Client, args: argparse.Namespace) -> None:
    print(format_volume(request(client, "PUT", "/api/mute", json={"muted": args.muted})))


def request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Send one request; return the JSON body (or None for 204 No Content)."""
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    if response.status_code == httpx.codes.NO_CONTENT:
        return None
    return response.json()


# --- Argument parsing ---


def volume_level(text: str) -> int:
    """argparse `type=` converter: reject bad input before any request is sent."""
    try:
        level = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if not MIN_VOLUME <= level <= MAX_VOLUME:
        raise argparse.ArgumentTypeError(f"must be between {MIN_VOLUME} and {MAX_VOLUME}")
    return level


def volume_step(text: str) -> int:
    step = volume_level(text)
    if step == 0:
        raise argparse.ArgumentTypeError("step must be at least 1")
    return step


def build_parser(default_url: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music", description="Control music on the studio PC.")
    parser.add_argument(
        "--url",
        default=default_url,
        help=f"server address (default: $RMC_SERVER_URL or {default_url})",
    )
    # Subcommands, like `git commit` / `git push`: each gets its own help text.
    # `set_defaults(handler=...)` attaches the function that runs the command,
    # so main() just calls args.handler(...) — a *dispatch table* built into
    # argparse, instead of a long if/elif chain.
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    commands.add_parser("health", help="check that the server is reachable").set_defaults(
        handler=run_health
    )
    commands.add_parser("now", help="show the current track and volume").set_defaults(
        handler=run_now
    )

    for name, path, help_text in TRANSPORT_COMMANDS:
        commands.add_parser(name, help=help_text).set_defaults(handler=run_transport, path=path)

    vol = commands.add_parser("vol", help="show the volume, or set it: music vol 40")
    vol.add_argument("level", nargs="?", type=volume_level, help="new volume, 0–100")
    vol.set_defaults(handler=run_volume)

    # Separate `up`/`down` commands instead of `vol +5`/`vol -5`, because
    # argparse would read "-5" as an unknown option flag.
    for name, path in (("up", "/api/volume/up"), ("down", "/api/volume/down")):
        step = commands.add_parser(name, help=f"turn the volume {name}: music {name} 10")
        step.add_argument("step", nargs="?", type=volume_step, help="points to move (default: 5)")
        step.set_defaults(handler=run_volume_step, path=path)

    commands.add_parser("mute", help="mute the player").set_defaults(handler=run_mute, muted=True)
    commands.add_parser("unmute", help="unmute the player").set_defaults(
        handler=run_mute, muted=False
    )
    return parser


def server_error_message(response: httpx.Response) -> str:
    """Prefer the server's own explanation ("detail") over a bare status code."""
    try:
        detail = response.json().get("detail")
    except ValueError:  # body wasn't JSON
        detail = None
    if isinstance(detail, str):
        return f"server returned HTTP {response.status_code}: {detail}"
    return f"server returned HTTP {response.status_code}"


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code (0 = success, 1 = failure).

    `argv` defaults to the real command-line arguments; tests can pass a list.
    """
    settings = load_client_settings()
    args = build_parser(settings.server_url).parse_args(argv)

    try:
        with httpx.Client(base_url=args.url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            args.handler(client, args)
    # Order matters: specific errors first, the general HTTPError last.
    except httpx.ConnectError:
        print(f"music: cannot connect to server at {args.url} — is it running?", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print(f"music: server at {args.url} did not answer in time", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as error:
        print(f"music: {server_error_message(error.response)}", file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"music: request failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
