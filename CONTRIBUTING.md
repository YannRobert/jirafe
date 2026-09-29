# Contributing to Jirafe

Thanks for your interest! Issues and pull requests are welcome.

## Before starting

- For a significant change, open an issue first to discuss it.
- Read [AGENTS.md](AGENTS.md): it lists the project's non-negotiable constraints (standard library only,
  Windows / Linux / macOS portability, saving JIRA requests, security rules) and its conventions. They
  apply to humans as much as to coding agents.

## Running in development

```bash
export JIRA_PAT="the-token"
cd src && python3 -m jirafe --port 9101
```

The page is re-read on every request: a change to `src/jirafe/static/index.html` shows up on the next
reload, without restarting the server.

## Checking

From the repository root, with nothing to install:

```bash
python3 -m compileall -q src tests
python3 -m unittest
```

The tests never call JIRA. For a change to the page or to the sync, also check the board, the detail
panel and the `GET /stats` counter by hand in the browser.

## Pull requests

- One pull request per topic, with a description of the why. Its title ends up in the release notes:
  make it meaningful to a user.
- Never include a token, an internal instance URL or real issue data (screenshots included).

By contributing, you agree that your contribution is published under the project's
[MIT license](LICENSE), and you commit to following the [code of conduct](CODE_OF_CONDUCT.md).
