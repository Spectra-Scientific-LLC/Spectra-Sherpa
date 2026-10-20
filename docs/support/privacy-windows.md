# Spectra Sherpa for Windows: Privacy Summary

*Derived from the canonical [Spectra Sherpa (open source) Privacy
Statement](privacy.md), Parts A and B. If the two differ, the canonical
statement governs.*

"We" means Spectra Scientific. "You" means the person using Spectra Sherpa.

1. **Your data stays on your PC.** Your datasets, projects, workflows, models,
   results, logs and backups are stored in `%USERPROFILE%\.spectra_sherpa`.
   You don't need an account.
2. **We collect nothing.** No telemetry, analytics, crash reports, update
   checks, license checks or cloud sync. The app contains no code that
   connects to our hosted services.
3. **The app goes online only for features you turn on:**
   - **AI assistant, with your own key.** Your typed message, the workflow name
     and a short hint about which part of the app is in view go directly to
     the provider you chose. Basic chat includes data you type or paste. A separately requested Data
     Story sends a bounded parsed-dataset summary and your supplied context.
   - **HITRAN.** Bundled clients acquire requested line data only after you
     configure your key and enable queries. The frozen desktop build excludes
     the optional NIST client.
   - **Eigenvector.** The app does not download these datasets.
     Eigenvector files you download yourself are checked by SHA-256 when you
     import them.
4. **Your saved API keys** are encrypted and protected by Windows Data
   Protection for your Windows account. If you copy your profile to another PC
   or account, you enter them again. If Windows credential protection is
   unavailable, the app doesn't store or use API keys at all; your analysis
   keeps working.
5. **Logs** stay on your PC, with secrets removed, and are capped at about
   60 MB.
6. **You decide what to share.** Exports you save, the diagnostics file
   (versions and OS only, saved on your PC), and support emails you send us.
7. **Crash reports.** The app has none. Windows Error Reporting and Microsoft
   Store statistics follow Microsoft's privacy statement.
8. **Deleting your data:**
   - **Application → Delete all local data…** permanently erases everything
     Spectra Sherpa stored, including your saved keys. Anything it can't
     confirm it created, and any linked file or folder, is kept, and the app
     lists it for you.
   - The uninstaller asks whether to delete your data, and the default answer
     keeps it.
   - We hold none of your data, so we can't access, recover or delete it for
     you.
9. **Security.**
   - The app's window and its calculation engine communicate only inside your
     PC over an authenticated loopback channel protected by a launch token.
     This does not protect against a compromised operating-system account.
   - We digitally sign our installer and application files so you can confirm
     they come from us and haven't been altered.

**Contact:** Spectra Scientific LLC · [privacy@spectrascientific.ai](mailto:privacy@spectrascientific.ai)
