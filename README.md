# Jirafe

[![CI](https://github.com/YannRobert/jirafe/actions/workflows/ci.yml/badge.svg)](https://github.com/YannRobert/jirafe/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A blazing-fast alternative to the Jira web UI for your sprint board.** Jirafe shows the board of a
Jira Server / Data Center sprint — columns, issues, epics, and a detail panel with description, comments
and history — and every click answers instantly.

**How it works.** Jirafe is a small proxy that runs on your machine (Python, standard library only). It
keeps a local cache of the Jira data it shows and refreshes it regularly in the background, so the page
reads from the cache instead of waiting for Jira. Navigation is instant, without trading away freshness:
the board and open issues are kept up to date without you having to press F5.

**Mostly for reading, with a few edits.** Jirafe was designed for consulting the board, but it can
already move issues by dragging a card by its grip (⠿): within its column to reorder it, or to another
column to change its status (only columns a Jira transition leads to accept it). It can also change an
issue's assignee from the detail panel (click the assignee, or press `A`).

## Requirements

- **Python 3.8+** (nothing to install).
- **Jira Server or Data Center** (Jirafe relies on the board's `greenhopper` API, which Jira Cloud lacks).
- A **Jira personal access token** in the `JIRA_PAT` environment variable
  (Jira: avatar > Profile > Personal Access Tokens > Create token).

## Configuration

Copy [`jirafe.example.json`](jirafe.example.json) to the user configuration directory, then adapt it:

| System | Configuration file |
|---|---|
| Linux | `$XDG_CONFIG_HOME/jirafe/config.json` (defaults to `~/.config/jirafe/config.json`) |
| macOS | `~/Library/Application Support/jirafe/config.json` |
| Windows | `%APPDATA%\jirafe\config.json` |

Creating it takes a few minutes with a text editor:

1. **Copy the template** from the repository root:
   - Linux: `mkdir -p ~/.config/jirafe && cp jirafe.example.json ~/.config/jirafe/config.json`
   - macOS: `mkdir -p ~/Library/Application\ Support/jirafe && cp jirafe.example.json ~/Library/Application\ Support/jirafe/config.json`
   - Windows (`cmd`): `mkdir "%APPDATA%\jirafe"` then `copy jirafe.example.json "%APPDATA%\jirafe\config.json"`
2. **`jiraHost`**: the address of Jira, as in your browser before `/browse/…` or `/secure/…`.
3. **`boardId`**: open the board in Jira; it is the number after `rapidView=` in the address bar.
4. **`fields`**: while logged in to Jira, open `<jiraHost>/rest/api/2/field` in the browser. It lists
   every field as JSON: search (Ctrl+F) for the name shown on an issue, for instance `Story Points`, and
   copy its `"id"` (`customfield_…`). Remove the roles you do not need; `"fields": {}` is valid.
5. **`views`** (optional): see below.
6. **Start Jirafe.** If the file is missing, Jirafe prints the path it expects; if it is invalid, it names
   the faulty key and stops.

```json
{
  "jiraHost": "https://jira.example.com",
  "boardId": 42,
  "fields": {
    "storyPoints": "customfield_12345",
    "sprints": "customfield_12346"
  }
}
```

- `jiraHost`: URL of the Jira instance.
- `boardId`: id of the board, the `rapidView=` of its URL.
- `fields`: custom fields shown in the detail panel. Their id differs from one instance to another
  (step 4 above). A role left out is not shown.
  Known roles:

| Role | Expected content |
|---|---|
| `storyPoints` | number |
| `sprints` | sprints of the issue |
| `criticality` | select list |
| `developer`, `tester` | user |
| `environments` | multi-select |
| `deliveredAt`, `installedAt`, `acceptedAt` | date |

- `views` (optional): splits a board with many columns into views, for instance Dev and QA. Each view
  starts at column `from` (name as shown on the board, case-insensitive) and stops where the next view
  starts; a view showing the whole board is added, and keys 1, 2, 3… switch between them. The first view
  is the default one. Without `views`, the whole board is shown.

```json
"views": [
  { "label": "Dev", "from": "To Do" },
  { "label": "QA", "from": "Ready for QA" }
]
```

`--jira-host` and `--board` override the file; `--config` points to another one.

## Running

- **Windows**: double-click `jirafe.cmd` (after running `setx JIRA_PAT "the-token"` once). For a
  shortcut: right-click > Send to > Desktop.
- **Linux / macOS**: `./jirafe.sh` (after adding `export JIRA_PAT="the-token"` to `~/.profile` or
  `~/.zshrc`).

The launcher finds Python, starts the server and opens the browser; launching it again simply reopens
the board. Options are passed through (`./jirafe.sh --port 9101`). Without a launcher:

```bash
cd src && python3 -m jirafe --open
```

Then open <http://localhost:8766>.

### Options

| Option | Default | Purpose |
|---|---|---|
| `--config` | see [Configuration](#configuration) | configuration file |
| `--jira-host` | `jiraHost` from the configuration | URL of the Jira instance |
| `--board` | `boardId` from the configuration | Jira board id (`rapidView`) |
| `--port` | `8766` | local listening port |
| `--mirror-dir` | see [Local copy](#local-copy) | directory of the local copy of issues |
| `--sync-interval` | `300` | seconds between two incremental background syncs |
| `--quiet` | — | do not log every request |
| `--open` | — | open the browser once the server is ready |

## How it works

```
browser ──► http://localhost:8766 ──► Jira
            (src/jirafe)              (JIRA_PAT as Bearer)
```

| Route | Purpose |
|---|---|
| `GET /` | the page (`src/jirafe/static/index.html`, configuration injected) |
| `GET /jira/<path>` | relay to Jira, restricted to an allow-list of paths |
| `GET /issue/<key>` | local copy of the issue; `?sync=1` resyncs it (`&force=1` ignores freshness) |
| `GET /transitions/<key>` | transitions available from the issue's status |
| `PUT /rank` | reorders an issue on the board — one of the three possible writes |
| `PUT /assignee` | changes an issue's assignee (`null` unassigns) |
| `PUT /transition` | applies a transition to an issue (changes its status) |
| `GET /stats` | requests made to Jira over 1, 5 and 15 minutes |
| `GET /mirror/status` | state of the local copy |

- **Board in one call**: `allData.json`, the endpoint used by Jira's own board page.
- **Local copy**: one JSON file per issue. Full sweep at startup, then once a day; in between, only
  modified issues are resynced.

### Local copy

It is a cache: it can be deleted, and it rebuilds itself at the next launch.

| System | Directory |
|---|---|
| Linux | `$XDG_CACHE_HOME/jirafe` (defaults to `~/.cache/jirafe`) |
| macOS | `~/Library/Caches/jirafe` |
| Windows | `%LOCALAPPDATA%\jirafe\cache` |

## Security

- The server only listens on `127.0.0.1`; any other `Host` header is rejected (DNS rebinding).
- The PAT never leaves the server: the browser never sees it.
- Only `GET` is relayed, and only to the paths the page reads.
- The only three writes (`PUT /rank`, `PUT /assignee` and `PUT /transition`) require the same origin and
  a JSON body; the server builds the Jira request itself from validated values (issue keys, a user login,
  a transition id).

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Layout

```
jirafe.cmd, jirafe.sh     Windows and Linux / macOS launchers
jirafe.example.json       configuration template
src/jirafe/
  app.py                  entry point: options, configuration, startup
  handler.py              HTTP routes and security checks
  upstream.py             connections to Jira (proxy, reuse)
  jira.py                 JSON reads from Jira
  mirror.py               local copy of issues, background sync
  meter.py                counter of requests to Jira
  config.py, paths.py     configuration file, per-system locations
  constants.py            constants
  static/index.html       the page (HTML, CSS and JS in a single file)
tests/                    unittest tests, no network
```

## Roadmap

- **Ideas, not implemented and not committed to:**
  - more edits from the page, such as adding a comment or editing the description;
  - handing edits over to your own AI agent: rather than coding every possible change into Jirafe, the
    page would pass the request, written or spoken, to an agent that already has its own access to Jira
    (MCP server or REST API) and makes the change there.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short, from the repository root:

```bash
python3 -m unittest
```

## License

[MIT](LICENSE).

Jirafe is not affiliated with or endorsed by Atlassian. Jira is a registered trademark of Atlassian.
