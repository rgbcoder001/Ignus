#!/usr/bin/env bash
# Turns on Tailscale, which Bazzite already ships but leaves switched off.
#
# Bazzite's own `ujust tailscale enable` runs `sudo systemctl enable`, which
# cannot work from Ignis: there is no terminal for sudo to ask for a password
# on. This uses pkexec instead, which asks with a normal desktop dialog -
# the same approach Bazzite itself uses for its other privileged recipes.
#
# Signing in is deliberately left to the user. Authenticating a device means
# approving it in a browser, and no installer can do that on someone's
# behalf.
#
# Safe to run more than once.
set -euo pipefail

SERVICE="tailscaled.service"
CURRENT_USER="${USER:-$(id -un)}"

if ! systemctl list-unit-files "$SERVICE" >/dev/null 2>&1 \
    || [ -z "$(systemctl list-unit-files --no-legend "$SERVICE" 2>/dev/null)" ]; then
    echo "Tailscale does not appear to be part of this system image." >&2
    echo "It normally ships with Bazzite - check that this is a current image." >&2
    exit 1
fi

if systemctl is-enabled --quiet "$SERVICE" 2>/dev/null; then
    echo "The Tailscale service is already switched on."
else
    echo "Switching on Tailscale. A password box will appear - this needs"
    echo "administrator rights to enable a system service."
    # One prompt for both steps. Setting the operator is what lets you run
    # 'tailscale up' later without needing a password again; it is not
    # essential, so it must not fail the whole install.
    pkexec /usr/bin/bash -lc \
        "systemctl enable --now ${SERVICE} && { tailscale set --operator='${CURRENT_USER}' || true; }"
fi

if ! systemctl is-enabled --quiet "$SERVICE" 2>/dev/null; then
    echo "Tailscale could not be switched on." >&2
    exit 1
fi

echo
echo "Tailscale is running. One step is left, and it has to be done by you:"
echo
echo "    tailscale up"
echo
echo "Run that in a terminal and open the link it prints to sign in. Signing"
echo "in has to happen in a browser, so it cannot be automated. You only ever"
echo "do this once for this computer."
echo
echo "After that, install Tailscale on your phone or laptop, sign in with the"
echo "same account, and they will be able to reach this machine from anywhere."
