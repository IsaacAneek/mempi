# Deployment Scripts

This directory contains utility scripts for host machines (like an x86 laptop or desktop) to automate the deployment of the `mempi` project to a remote Raspberry Pi.

If you are already logged into the Raspberry Pi natively, you do **not** need these scripts.

## Scripts

### `setup_ssh.sh`
Automates the creation and installation of an SSH key to the remote Raspberry Pi (`pi@pi01.local` by default). This allows for passwordless SSH, which is required for the deployment script to run smoothly.
*   **Usage**: `./setup_ssh.sh`

### `deploy_to_pi.sh`
Uses `rsync` to push the entire codebase to the remote Raspberry Pi. It automatically excludes the `build/` directory so you don't accidentally copy incompatible host binaries to the ARM-based Pi.
*   **Usage**: `./deploy_to_pi.sh`

