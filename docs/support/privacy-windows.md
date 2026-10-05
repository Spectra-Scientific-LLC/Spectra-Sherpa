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
     the provider you chose. Your data is sent only if you type or paste it.
   - **NIST WebBook.** Used only after you enable it and request data.
   - **Nothing else.** The app never downloads HITRAN or Eigenvector data.
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
     PC. Other devices and other programs can't use that channel.
   - We digitally sign our installer and application files so you can confirm
     they come from us and haven't been altered.

**Contact:** [LEGAL ENTITY NAME] · [privacy@spectrascientific.ai]
