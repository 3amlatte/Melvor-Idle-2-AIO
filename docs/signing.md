# Code signing

Signing is independent of **portable vs installer**. Windows checks the
Authenticode signature on the executables themselves, not on the zip. Keep the
portable zip: sign the files after PyInstaller finishes, then zip them.

## What to sign

Sign these files inside `dist\MI2 AIO` **before** `package_app.ps1` creates the
zip:

- `MI2 AIO.exe` (the launcher users double-click)
- `_internal\tools\bin\SaveTool.exe` (the self-contained .NET helper)

Optionally sign bundled DLLs as well, but that is rarely necessary and makes
updates larger. If you later ship an installer, sign the installer executable
too.

Do **not** sign the zip; a zip has no Authenticode signature. Publish a SHA256
alongside it (the release workflow does this).

## Certificate options

| Option | Best for | Notes |
| --- | --- | --- |
| **SignPath Foundation** | Open-source projects | Free signing service for OSS, HSM-backed. Apply at signpath.org/foundation. Recommended first step for this project. |
| **Azure Trusted Signing** | CI signing | Microsoft's managed signing. Requires an Azure subscription and identity validation; integrates with GitHub Actions. |
| **OV/EV certificate** | Commercial/local signing | Buy from a CA (SSL.com, DigiCert, Sectigo, Certum). Since 2023 the private key must live on a hardware token or cloud HSM. |
| **USB hardware token** | Local builds | Sign on the build PC with `signtool /sha1 <thumbprint>`. The certificate must be in the Windows certificate store. |
| **Self-signed certificate** | Testing only | Produces a signature but **no trust**; SmartScreen still warns. Never distribute a self-signed release. |

OV and EV certificates reduce "Unknown publisher" warnings. Reputation is still
built over downloads; signing does not guarantee that SmartScreen or antivirus
will be silent. A PyInstaller build can still trigger heuristic detections.

## Local signing (USB token / certificate store)

Install the Windows SDK signing tools (Visual Studio Build Tools or the Windows
SDK), then sign the build with the certificate thumbprint:

```powershell
# Find the certificate thumbprint.
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Format-Table Subject, Thumbprint, NotAfter

# Sign the app and the save helper, then verify.
.\scripts\sign_app.ps1 -Thumbprint "ABCDEF..." -TimestampUrl "http://timestamp.digicert.com"

# Create the portable zip after signing.
.\scripts\package_app.ps1
```

`sign_app.ps1` uses SHA-256 and an RFC3161 timestamp, signs both executables, and
runs `signtool verify /pa /v`.

For a test certificate only, a PFX can be passed:

```powershell
.\scripts\sign_app.ps1 -PfxPath .\test-signing.pfx -PfxPassword "..."
```

Never commit a PFX or password. Public releases should use a CA-issued
certificate on hardware/cloud storage, not a PFX.

## CI signing

The release workflow is unsigned by default. Once a signing provider is set up,
sign the files **before** the zip step:

- **SignPath Foundation**: connect the GitHub repository in SignPath, add their
  signing action to `.github/workflows/release.yml`, and request the two
  executables. SignPath returns signed artifacts; zip those.
- **Azure Trusted Signing**: add federated credentials and use
  `azure/trusted-signing-action` with the account/profile/endpoint secrets, then
  run `package_app.ps1` to zip the signed output.
- **CA cloud HSM (SSL.com eSigner, DigiCert KeyLocker, Certum)**: use the
  provider's CLI/action, then zip the signed `dist\MI2 AIO` folder.

If signing happens in CI, do not run `package_app.ps1` before signing: the zip
must contain the signed executables. Either sign the files in `dist\MI2 AIO`
then zip, or have the provider sign and return the artifacts before the packaging
step.

## Verifying a release

```powershell
Get-FileHash .\MI2-AIO-0.66-win64.zip -Algorithm SHA256
Get-AuthenticodeSignature .\MI2 AIO\MI2 AIO.exe
Get-AuthenticodeSignature .\MI2 AIO\_internal\tools\bin\SaveTool.exe
```

`Get-AuthenticodeSignature` should report `Status = Valid` and the expected
publisher. Users can do the same after extracting the zip.
