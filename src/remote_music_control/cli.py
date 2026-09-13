"""The `music` command-line client.

A thin HTTP client: it parses the command, sends requests to the server, and
prints the result. It contains no media logic of its own, so the CLI and the
web UI can never disagree about behaviour.
"""

import argparse
import sys
from typing import Any

import httpx2

from .config import ConfigError, default_config_path, load_client_settings
from .media_controller import MAX_VOLUME, MIN_VOLUME

# Two limits, because the two waits are different:
# - connecting: a PC that is off or unreachable should be reported quickly;
# - reading the answer: on the real player, commands wait until their effect is
#   visible (docs/decisions/0008) — measured up to ~2.3 s, and up to ~4.5 s if
#   pressed during Chrome's track-change gap. 10 s leaves a wide margin.
REQUEST_TIMEOUT = httpx2.Timeout(10.0, connect=3.0)

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


def format_song(song: dict[str, Any]) -> str:
    details = " · ".join(part for part in (song.get("artist"), song.get("duration")) if part)
    return f"{song['title']} — {details}" if details else song["title"]


def format_search_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "no songs or videos found"
    # The video id is what `music add` needs; numbers are just for reading.
    return "\n".join(f"{number:2}. {format_song(song)}  [{song['video_id']}]" for number, song in enumerate(results, 1))


def format_queue(queue: dict[str, Any]) -> str:
    if not queue["items"]:
        return "the queue is empty"
    lines = []
    autoplay_started = False
    for item in queue["items"]:
        if item["is_autoplay"] and not autoplay_started:
            lines.append("    --- autoplay ---")
            autoplay_started = True
        marker = "▶" if item["is_current"] else " "
        # Numbered from 1 for people; `music jump N` uses the same numbers.
        lines.append(f"{marker} {item['index'] + 1:3}. {format_song(item)}")
    return "\n".join(lines)


def format_volume(volume: dict[str, Any]) -> str:
    text = f"volume {volume['volume']}%"
    if volume["muted"]:
        text += " (muted)"
    return text


# --- Command handlers: each receives the HTTP client and the parsed arguments ---


def run_health(client: httpx2.Client, args: argparse.Namespace) -> None:
    request(client, "GET", "/health")  # public: is the server up at all?
    print(f"server ok at {args.url}")
    request(client, "GET", "/api/state")  # requires the token: is ours accepted?
    print("token accepted")


def run_now(client: httpx2.Client, args: argparse.Namespace) -> None:
    print(format_state(request(client, "GET", "/api/state")))


def run_transport(client: httpx2.Client, args: argparse.Namespace) -> None:
    request(client, "POST", args.path)
    # Show the result so `music next` tells you what is playing now.
    run_now(client, args)


def run_volume(client: httpx2.Client, args: argparse.Namespace) -> None:
    if args.level is None:
        data = request(client, "GET", "/api/volume")
    else:
        data = request(client, "PUT", "/api/volume", json={"level": args.level})
    print(format_volume(data))


def run_volume_step(client: httpx2.Client, args: argparse.Namespace) -> None:
    # Only send ?step= when the user gave one, so the server's default applies.
    params = {} if args.step is None else {"step": args.step}
    print(format_volume(request(client, "POST", args.path, params=params)))


def run_mute(client: httpx2.Client, args: argparse.Namespace) -> None:
    print(format_volume(request(client, "PUT", "/api/mute", json={"muted": args.muted})))


def run_search(client: httpx2.Client, args: argparse.Namespace) -> None:
    query = " ".join(args.query)
    print(format_search_results(request(client, "GET", "/api/library/search", params={"q": query})["results"]))


def run_queue(client: httpx2.Client, args: argparse.Namespace) -> None:
    print(format_queue(request(client, "GET", "/api/library/queue")))


def run_jump(client: httpx2.Client, args: argparse.Namespace) -> None:
    request(client, "POST", f"/api/library/queue/{args.number - 1}/play")
    run_now(client, args)


def run_add(client: httpx2.Client, args: argparse.Namespace) -> None:
    request(client, "POST", "/api/library/play", json={"video_id": args.video_id, "position": args.position})
    print({"now": "playing", "next": "will play next", "end": "added to the queue"}[args.position])


def request(client: httpx2.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Send one request; return the JSON body (or None for 204 No Content)."""
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    if response.status_code == httpx2.codes.NO_CONTENT:
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


def queue_number(text: str) -> int:
    """argparse converter for `music jump N`: queue positions start at 1."""
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError("queue positions start at 1")
    return number


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

    # Library commands (search and the queue, through the Chrome extension).
    search = commands.add_parser("search", help='search YouTube Music: music search aruarian dance')
    search.add_argument("query", nargs="+", help="words to search for")
    search.set_defaults(handler=run_search)

    commands.add_parser("queue", help="show the queue").set_defaults(handler=run_queue)

    jump = commands.add_parser("jump", help="play queue item N, as numbered by `music queue`")
    jump.add_argument("number", type=queue_number, help="queue position (from 1)")
    jump.set_defaults(handler=run_jump)

    add = commands.add_parser("add", help="play a song by id (from `music search`), or queue it")
    add.add_argument("video_id", help="the id shown in brackets by `music search`")
    # A *mutually exclusive group*: --next and --end can't be given together.
    where = add.add_mutually_exclusive_group()
    where.add_argument("--next", dest="position", action="store_const", const="next", help="play right after the current song")
    where.add_argument("--end", dest="position", action="store_const", const="end", help="add to the end of the queue")
    add.set_defaults(handler=run_add, position="now")

    commands.add_parser("mute", help="mute the player").set_defaults(handler=run_mute, muted=True)
    commands.add_parser("unmute", help="unmute the player").set_defaults(
        handler=run_mute, muted=False
    )
    return parser


def make_client(url: str, token: str | None) -> httpx2.Client:
    """Create the HTTP client every command uses.

    A separate function so tests can replace it with FastAPI's TestClient,
    which runs the real app in-process: the CLI is then tested end to end
    without starting a server or opening a network port.
    """
    # The token comes only from the config file or environment, never from a
    # command-line option: arguments are visible to other users in process
    # listings (`ps`) and are saved in shell history.
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.Client(base_url=url, headers=headers, timeout=REQUEST_TIMEOUT)


def server_error_message(response: httpx2.Response) -> str:
    """Prefer the server's own explanation ("detail") over a bare status code."""
    try:
        detail = response.json().get("detail")
    except ValueError:  # body wasn't JSON
        detail = None
    if isinstance(detail, str):
        return f"server returned HTTP {response.status_code}: {detail}"
    return f"server returned HTTP {response.status_code}"


def use_utf8_output() -> None:
    """Write output as UTF-8, whatever the terminal or redirection.

    The CLI prints characters like "▶" and "—". On Windows, when output is
    redirected (`music now > file.txt`, or a pipe), Python otherwise uses the
    legacy cp1252 encoding, which can't represent them, and crashes. Python
    3.15 makes UTF-8 the default everywhere (PEP 686); this does it now.
    """
    for stream in (sys.stdout, sys.stderr):
        # reconfigure() exists on normal text streams; replacement streams
        # (e.g. in some test tools) may not have it, and are left alone.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code (0 = success, 1 = failure).

    `argv` defaults to the real command-line arguments; tests can pass a list.
    """
    use_utf8_output()
    try:
        settings = load_client_settings()
    except ConfigError as error:
        print(f"music: configuration error: {error}", file=sys.stderr)
        return 1
    args = build_parser(settings.server_url).parse_args(argv)

    try:
        with make_client(args.url, settings.token) as client:
            args.handler(client, args)
    # Order matters: Python uses the first matching `except`, so specific errors
    # come first and the general HTTPError last.
    # ConnectError: nothing listening (server stopped). ConnectTimeout: no reply
    # at all (PC off or unreachable) — technically a timeout, but for the user
    # it's the same problem, so it gets the same message.
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        print(f"music: cannot connect to server at {args.url} — is it running and reachable?", file=sys.stderr)
        return 1
    except httpx2.TimeoutException:  # connected, but the answer took too long
        print(f"music: server at {args.url} did not answer in time", file=sys.stderr)
        return 1
    except httpx2.HTTPStatusError as error:
        if error.response.status_code == httpx2.codes.UNAUTHORIZED:
            where = "is not set" if settings.token is None else "was rejected by the server"
            print(
                f"music: the token {where}. Set RMC_TOKEN in {default_config_path()} "
                "to the token printed by `music-server init` on the server.",
                file=sys.stderr,
            )
        else:
            print(f"music: {server_error_message(error.response)}", file=sys.stderr)
        return 1
    except httpx2.HTTPError as error:
        print(f"music: request failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
