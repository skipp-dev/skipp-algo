# Windows installation

## Supported system

- 64-bit Windows.
- Google Chrome or Microsoft Edge.

The Windows package contains its own Node.js runtime and dependencies. Do not run
`npm install`; npm is not required.

## Install and start

1. Download `SMC-Onboarding-Windows-x64.zip`.
2. Right-click the ZIP file and select **Extract All**. Do not start onboarding
   from inside the ZIP preview.
3. Open the extracted `SMC-Onboarding-Windows-x64` folder.
4. Double-click `Start SMC Onboarding.cmd`.
5. If Windows displays a security prompt, confirm that the package came from the
   expected SMC release before allowing it to run.
6. Paste the full TradingView chart URL when prompted and press Enter.
7. Complete TradingView sign-in in the opened Chrome or Edge window if requested.
8. Leave the terminal and browser windows open until the result appears.

## Browser selection

Chrome is selected first when both supported browsers are installed. To use a
specific Chromium-based executable, start Command Prompt in the package folder:

```text
"Start SMC Onboarding.cmd" --browser-path "C:\Path\To\browser.exe"
```

Only use a trusted local Chrome or Edge executable.

## Non-interactive chart selection

The chart URL can be supplied directly:

```text
"Start SMC Onboarding.cmd" --chart-url "https://www.tradingview.com/chart/.../"
```

## Run onboarding again

Close any previous SMC Onboarding browser window, then start the command file
again. The dedicated login profile is reused. Add any missing consumers to the
same chart before rerunning if the previous result was `partial`.

## Uninstall

1. Close all SMC Onboarding windows.
2. Delete the extracted application folder.
3. To remove the dedicated TradingView login and local reports, delete
   `%LOCALAPPDATA%\SMC Onboarding`.

Deleting the application-data folder signs the onboarding profile out. It does
not remove indicators from TradingView or delete the TradingView chart.
