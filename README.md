# VV Jailbreak Repository

Configured for GitHub repository `fatekingcsr/VV`.

Repository:
https://github.com/fatekingcsr/VV

Public APT source:
https://fatekingcsr.github.io/VV/

## How to publish a tweak

1. Put your `.deb` file into `debs/`.
2. Commit and push to GitHub.
3. GitHub Actions validates the package, builds APT metadata, and publishes GitHub Pages.
4. Add `https://fatekingcsr.github.io/VV/` to Sileo/Zebra/Cydia.

The repository accepts rootful/rootless/roothide packages as long as their Debian metadata is valid.

## Optional GPG signing

Add these GitHub Actions secrets:
- `GPG_PRIVATE_KEY`
- `GPG_PASSPHRASE`
- `GPG_KEY_ID`

The workflow will generate `Release.gpg` and `InRelease`.
