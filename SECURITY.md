# Security

Jirafe handles a JIRA personal access token: a flaw can expose the user's JIRA data, or even let
someone write on their behalf.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting: the repository's *Security* tab >
*Report a vulnerability*. Describe the problem, its impact and, if possible, how to reproduce it.

You will get a first answer within a week. The fix is released before public disclosure, and the
reporter is credited if they wish.

## Scope

This includes any way for a third-party page, another user of the machine or a JIRA response to obtain
the PAT, to read JIRA through the relay outside the allow-list, or to trigger a JIRA write other than the
rank change the user asked for. The security model is described in the [README](README.md#security).

## Supported versions

Only the latest release receives security fixes.
