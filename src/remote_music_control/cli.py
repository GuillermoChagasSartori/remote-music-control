"""The `music` command-line client.

A thin HTTP client: it parses the command, sends one request to the server,
and prints the result. It contains no media logic of its own, so the CLI and
the web UI can never disagree about behaviour.
"""

import argparse
import sys

import httpx

from .config import load_client_settings

# Generous enough for a slow Wi-Fi hop, short enough that a dead server is
# reported quickly instead of the terminal appearing to hang.
REQUEST_TIMEOUT_SECONDS = 3.0


def build_parser(default_url: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music", description="Control music on the studio PC.")
    parser.add_argument(
        "--url",
        default=default_url,
        help=f"server address (default: $RMC_SERVER_URL or {default_url})",
    )
    # Subcommands, like `git commit` / `git push`: each gets its own help text.
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("health", help="check that the server is reachable")
    return parser


def run_health(client: httpx.Client) -> None:
    response = client.get("/health")
    response.raise_for_status()
    data = response.json()
    print(f"server ok — controller: {data['controller']}")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code (0 = success, 1 = failure).

    `argv` defaults to the real command-line arguments; tests can pass a list.
    """
    settings = load_client_settings()
    args = build_parser(settings.server_url).parse_args(argv)

    try:
        with httpx.Client(base_url=args.url, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            if args.command == "health":
                run_health(client)
    # Order matters: specific errors first, the general HTTPError last.
    except httpx.ConnectError:
        print(f"music: cannot connect to server at {args.url} — is it running?", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print(f"music: server at {args.url} did not answer in time", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as error:
        print(f"music: server returned HTTP {error.response.status_code}", file=sys.stderr)
        return 1
    except httpx.HTTPError as error:
        print(f"music: request failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
