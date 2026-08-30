# MORPH-GEN Push Status

Status: **BLOCKED — repository visibility is private; anonymous acceptance has
not passed.**

## Published Git objects

- Remote URL: `git@github.com:Daijunfan/Turing4.git`
- HTTPS URL: `https://github.com/Daijunfan/Turing4.git`
- Branch: `main`
- Verified research-artifact commit:
  `0d820730858fb66510ece85e4d24116b8f527ddd`
- Tagged phase/release metadata commit:
  `91bd59962dc194b62518a244f28192b37a8931d4`
- Tag: `morph-gen-v0.1`

Push output:

```text
To github.com:Daijunfan/Turing4.git
   9e1697c..91bd599  main -> main
To github.com:Daijunfan/Turing4.git
 * [new tag]         morph-gen-v0.1 -> morph-gen-v0.1
```

Remote authenticated verification:

```text
91bd59962dc194b62518a244f28192b37a8931d4 refs/heads/main
778c9211cf65171419e2328a80778d0435906d67 refs/tags/morph-gen-v0.1
91bd59962dc194b62518a244f28192b37a8931d4 refs/tags/morph-gen-v0.1^{}
```

## Anonymous verification — currently failed

Command:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN \
  git -c credential.helper= \
  ls-remote https://github.com/Daijunfan/Turing4.git
```

Current result:

```text
fatal: could not read Username for 'https://github.com': Device not configured
repository_http=404
```

The unauthenticated GitHub API returns no public repository metadata. This is
authoritative evidence that the repository is still private. The task is not
complete and this file does not claim otherwise.

## Visibility tooling

- SSH authentication succeeds as GitHub user `Daijunfan` and supports Git push.
- `gh` is installed but `gh auth status` reports no authenticated GitHub host.
- An existing signed-in browser session is available, but changing repository
  visibility is a cloud permission change and requires action-time confirmation
  before submission.

## Public artifacts

No file approaches GitHub's 100 MB limit, so no Release upload is required.
Paths and SHA-256 hashes are recorded in `PUBLIC_ARTIFACTS.json`. Code, summaries,
raw evidence and representative certificates are all in the Git tree.

## Required resolution

Change `Daijunfan/Turing4` visibility from private to public, then rerun:

1. anonymous HTTPS `git ls-remote` with credential helper disabled;
2. anonymous repository page HTTP status;
3. unauthenticated GitHub API visibility/default branch;
4. local/remote commit and tag equality;
5. `git status --porcelain`.

After those checks pass, update this file to `VERIFIED`, commit, push, and repeat
anonymous verification against the latest `main`.
