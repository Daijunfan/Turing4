# MORPH-GEN Push Status

Status: **VERIFIED — repository is public and anonymous acceptance passed.**

## Published Git objects

- Remote URL: `git@github.com:Daijunfan/Turing4.git`
- HTTPS URL: `https://github.com/Daijunfan/Turing4.git`
- Branch: `main`
- Verified research-artifact commit:
  `0d820730858fb66510ece85e4d24116b8f527ddd`
- Tagged phase/release metadata commit:
  `91bd59962dc194b62518a244f28192b37a8931d4`
- Public pre-status-update `main` commit:
  `342501f4bfdd19db10496abdcb52873bbfa1bdcd`
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

## Anonymous verification — passed

Command:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN \
  git -c credential.helper= \
  ls-remote https://github.com/Daijunfan/Turing4.git
```

Result after the repository was made public:

```text
342501f4bfdd19db10496abdcb52873bbfa1bdcd HEAD
342501f4bfdd19db10496abdcb52873bbfa1bdcd refs/heads/main
778c9211cf65171419e2328a80778d0435906d67 refs/tags/morph-gen-v0.1
repository_http=200
visibility=public
private=False
default_branch=main
html_url=https://github.com/Daijunfan/Turing4
```

The command ran with `GH_TOKEN` and `GITHUB_TOKEN` removed and Git's credential
helper disabled. GitHub's unauthenticated API and repository page independently
confirm public visibility.

## Visibility

- Repository visibility: `public`
- Default branch: `main`
- Public URL: `https://github.com/Daijunfan/Turing4`
- SSH authentication continues to support publishing; it was not used for the
  anonymous acceptance check.

## Public artifacts

No file approaches GitHub's 100 MB limit, so no Release upload is required.
Paths and SHA-256 hashes are recorded in `PUBLIC_ARTIFACTS.json`. Code, summaries,
raw evidence and representative certificates are all in the Git tree.

## Final acceptance checklist

- [x] code, experiments and documents committed;
- [x] `main` pushed without force;
- [x] annotated tag `morph-gen-v0.1` pushed;
- [x] anonymous HTTPS Git access succeeds;
- [x] anonymous repository page returns HTTP 200;
- [x] unauthenticated API reports public visibility and default branch `main`;
- [x] no Release required because every artifact is below the single-file limit;
- [x] local worktree was clean before this status-only update.

After committing this verification update, `main` is pushed once more and the
same anonymous `ls-remote` check is repeated against that latest commit.
