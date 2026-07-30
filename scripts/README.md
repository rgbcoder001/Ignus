# Vetted setup scripts

Shell scripts referenced by `script` sources in `data/catalog.toml`. They are
bundled into the Flatpak at `/app/share/ignis/scripts` and executed on the
host through `HostBridge`.

Rules for anything added here:

- **Idempotent.** Running twice must be safe and produce the same result.
- **Non-interactive.** No prompts — there is no terminal for the user to
  answer in.
- **Loud on failure.** Exit nonzero so the progress view shows the error.
- **Readable.** A user should be able to open the file and understand what it
  does to their system; the detail view shows them the command that runs it.
- **Reviewed.** These run with the user's privileges on the host. Never fetch
  and execute remote code from within a script.
