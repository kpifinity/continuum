# Push Continuum to GitHub + turn on auto-built installers

This is a **one-time** setup. After it, every time you push a version tag, GitHub
builds `Continuum-Setup.exe` on a Windows runner and attaches it to the release —
no manual uploads, and the Download button on skiframework.org/continuum starts
serving the real installer automatically.

The `kpifinity/continuum` repo already exists (currently just a placeholder
README). These commands push your actual source (and the CI workflow) over it.

## 1. Push the source (one time)

Open a terminal in this folder and run:

```bash
cd "C:\Users\rahul\OneDrive\Documents\Claude\Projects\SKI Memory\ski-memory"

git init -b main
git remote add origin https://github.com/kpifinity/continuum.git
git add .
git commit -m "Continuum app source + CI (auto-build Windows installer)"
git push -u origin main --force
```

`--force` replaces the placeholder README with your real repo. The build binaries
(`dist/`, `build/`, `packaging/Output/`) are git-ignored, so only source is pushed.

## 2. Cut the first release

```bash
git tag v0.1.0
git push origin v0.1.0
```

That tag triggers **.github/workflows/build-release.yml**. Watch it on the repo's
**Actions** tab (~5–8 min). When it's green, the release **v0.1.0** will have
`Continuum-Setup.exe` attached, and:

- `github.com/kpifinity/continuum/releases` shows the installer
- the **Download** button on `skiframework.org/continuum/` leads straight to it

## Future releases

1. Bump the version in two places: `ski_memory/__init__.py` (`__version__`) and
   `packaging/installer.iss` (`MyAppVersion`).
2. Also bump `"version"` in the site's `continuum/latest.json` so existing users
   get the in-app "update available" banner.
3. Commit, then:
   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```
   The installer rebuilds and publishes itself.

## What the workflow does

Runs on `windows-latest`: installs Python deps, runs the test suite, builds
`Continuum.exe` with PyInstaller (`packaging/build.py`), compiles the installer
with Inno Setup (`packaging/installer.iss`), and uploads
`packaging/Output/Continuum-Setup.exe` to the tag's Release. No secrets or tokens
needed — it uses the built-in `GITHUB_TOKEN`.
