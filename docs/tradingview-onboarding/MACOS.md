# macOS installation

## Supported system

- Apple Silicon using `SMC-Onboarding-macOS-arm64`.
- Intel using `SMC-Onboarding-macOS-x64`.
- Google Chrome or Microsoft Edge.

The macOS package contains its own Node.js runtime and dependencies. Homebrew,
Node.js, npm, and a Playwright browser download are not required.

## Choose the correct package

Open **Apple menu → About This Mac**:

- Apple M-series chips use the `arm64` package.
- Intel processors use the `x64` package.

## Install and start

1. Download and extract the package matching the Mac.
2. Open the extracted folder.
3. Double-click `Start SMC Onboarding.command`.
4. If macOS blocks the first launch, open **System Settings → Privacy & Security**,
   verify that the package came from the expected SMC release, and allow that
   specific launch.
5. Paste the full TradingView chart URL when prompted and press Return.
6. Complete TradingView sign-in in the opened browser window if requested.
7. Leave the Terminal and browser windows open until the result appears.

The release process should sign and notarize public packages before general
distribution. Internal unsigned test packages can require the Privacy & Security
confirmation described above.

## Browser selection

Chrome is selected first when both supported browsers are installed. A specific
executable can be selected from Terminal:

```text
./Start\ SMC\ Onboarding.command \
  --browser-path "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
```

## Run onboarding again

Close the previous onboarding browser window and start the command file again.
The dedicated login profile is reused. If consumers were missing, add them to the
same chart before rerunning.

## Uninstall

1. Close all SMC Onboarding windows.
2. Delete the extracted application folder.
3. To remove the dedicated TradingView login and reports, delete
   `~/Library/Application Support/SMC Onboarding`.

Removing that application-data folder does not change the TradingView chart.
