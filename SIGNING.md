# Code signing (optional) — how to remove the "unverified app" warnings

Continuum's installers build and work **unsigned** — macOS is ad-hoc signed so it
runs after the one-time "Open Anyway", and Windows runs after "More info → Run
anyway". To make those warnings disappear entirely, add the signing certificates
below as **GitHub repository secrets**. The build workflow detects them
automatically — no code changes, no manual steps. If a secret is absent, that
platform simply stays unsigned.

Add secrets at: repo → **Settings → Secrets and variables → Actions → New
repository secret**.

## Windows (Authenticode)

You need a code-signing certificate as a password-protected `.pfx`.
(An **EV** certificate is what makes SmartScreen stop warning immediately; an OV
cert builds reputation over time. Providers: DigiCert, Sectigo, SSL.com, etc.)

| Secret | Value |
| --- | --- |
| `WINDOWS_CERT_PFX_BASE64` | `base64 -w0 your-cert.pfx` (the whole .pfx, base64-encoded) |
| `WINDOWS_CERT_PASSWORD` | the .pfx password |

The workflow signs both `Continuum.exe` and `Continuum-Setup.exe` with a
timestamp.

## macOS (Developer ID + notarization)

Requires an **Apple Developer Program** membership ($99/yr).

1. In Xcode / Apple Developer, create a **"Developer ID Application"** certificate,
   export it from Keychain Access as a `.p12` with a password.
2. Create an **app-specific password** for your Apple ID at appleid.apple.com.
3. Find your **Team ID** in the Apple Developer membership page.

| Secret | Value |
| --- | --- |
| `MACOS_CERT_P12_BASE64` | `base64 -i DeveloperID.p12` (base64 of the .p12) |
| `MACOS_CERT_PASSWORD` | the .p12 password |
| `APPLE_ID` | your Apple ID email |
| `APPLE_TEAM_ID` | your 10-char Team ID |
| `APPLE_APP_PASSWORD` | the app-specific password |

With the `MACOS_CERT_*` secrets the app is signed with Developer ID + hardened
runtime; add the `APPLE_*` secrets and the `.dmg` is also **notarized and
stapled** — Gatekeeper then opens it with no warning.

## Verify

After adding secrets, cut a release (`git tag v0.1.3 && git push origin v0.1.3`)
and download the new installers — they should install with no security prompt.
