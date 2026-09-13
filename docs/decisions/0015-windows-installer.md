# 0015 — A Windows installer built with PyInstaller and Inno Setup

**Status:** Accepted · 2026-09-13 · Follows 0014

## Context

The app (ADR 0014) must reach customers as one download from a website:
download, install, done. They don't have Python, uv or git, and must not need
them. The distribution has no budget, so every tool must be free, including for
commercial use. Code signing is left for later.

## Decision

- **PyInstaller** bundles the app with a private copy of Python and every
  package into one folder (`RemoteMusicControl.exe` plus `_internal\`). It is
  the most widely used tool for this, understands pywebview, pythonnet and
  pywinrt through its community hooks, and its licence (GPL with an exception
  for bundled programs) allows distributing the result under any licence.
  - **A folder ("onedir"), not a single file ("onefile")**: a onefile app
    unpacks itself to a temporary folder on every start — slower, and typical
    of malware, so antivirus programs flag unsigned onefile apps more often.
  - **No UPX compression**, for the same reason; and **version details** in the
    .exe (publisher, product, version), which Windows shows in Properties.
- **Inno Setup 7** turns the folder into `RemoteMusicControl-Setup-<version>.exe`.
  Free for any use, including commercial; long established; English and
  Brazilian Portuguese wizard texts included. The installer:
  - installs to **Program Files for all users** and so asks for administrator
    rights once (owner's choice), which also lets it create the firewall rule;
  - adds a **Start menu** entry, an optional desktop shortcut, and an
    **uninstaller** listed in Windows' "Apps";
  - **starts the app at logon** in the tray (`--minimized`) through the
    machine-wide `Run` registry key — a checkbox, ticked by default;
  - adds a **firewall rule for the program**, allowing TCP from the **local
    subnet only**, on private and domain networks. Tied to the program rather
    than the port, so a changed `RMC_PORT` still works;
  - installs **WebView2 if missing**, with Microsoft's small bootstrapper
    (downloaded at build time, its Microsoft signature checked), which
    Microsoft allows applications to redistribute;
  - **refuses to update or uninstall while the app runs** (`AppMutex`, the
    mutex the app holds for its single-instance check) instead of replacing
    files in use;
  - **updates in place**: a newer installer with the same `AppId` replaces the
    program and keeps the user's settings, token (paired phones) and YouTube
    Music sign-in, which live in the user's profile, not in Program Files;
  - on uninstall **asks whether to delete that user data**, defaulting to No.
- **One build script, `packaging/build.ps1`**, used both on a developer PC and
  in CI, so the two can't drift apart.
- **CI builds the installer** on `main`, on version tags and on request, after
  the tests pass. The installer is kept as a workflow artifact; on a `v*` tag it
  is also published as a **GitHub Release**, a stable public download link the
  website can point to.
- The build tools are a separate uv dependency group, `build`, so the normal
  development environment and the test jobs don't install PyInstaller.

## Verified on the studio PC (Windows 10)

Silent install; the installed app served the LAN through the installer's
firewall rule alone (the old Phase 7 rule removed first); search, playback,
queue and volume from the Ubuntu PC. Update while the app ran: refused (exit
code 5); after closing it: updated in place, one firewall rule, sign-in kept.
Uninstall: program, Run entry, firewall rule, Start menu entry and
uninstall entry removed; user data kept. Reinstall: working at once.

## Consequences

- One 21 MB download; nothing else to install on Windows 10 1809+ or 11.
- **Unsigned**: Windows SmartScreen warns "Windows protected your PC" on the
  first downloads, until the file builds reputation or is signed. Signing is a
  later decision (e.g. SignPath's free signing for open-source projects).
- **Firewall on "Public" networks:** the rule covers private and domain
  networks. On a network Windows marks as public, other devices can't connect
  until the network is switched to private (or Windows' own prompt is accepted).
- Updates are manual — download and run the new installer — until an update
  check is added.
- Building needs Windows (PyInstaller doesn't cross-compile); CI provides it.
