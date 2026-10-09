#!/bin/bash

TARGET="pi@pi01.local"
PASSWORD="1234"

echo "=== Setting up passwordless SSH for $TARGET ==="

# Check for sshpass, install if missing
if ! command -v sshpass &> /dev/null; then
    echo "sshpass is required but not installed."
    echo "Attempting to install sshpass..."
    # We use sudo here. If it prompts for password, the script might hang unless the user has passwordless sudo.
    sudo apt-get update && sudo apt-get install -y sshpass
fi

# Generate an SSH key if one doesn't already exist
if [ ! -f ~/.ssh/id_rsa ] && [ ! -f ~/.ssh/id_ed25519 ]; then
    echo "No SSH key found. Generating a new ed25519 key..."
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
else
    echo "SSH key already exists. Skipping generation."
fi

# Copy the SSH key to the Raspberry Pi
echo "Copying SSH key to $TARGET..."
# StrictHostKeyChecking=no ensures it doesn't hang on the authenticity prompt
sshpass -p "$PASSWORD" ssh-copy-id -o StrictHostKeyChecking=no "$TARGET"

if [ $? -eq 0 ]; then
    echo "Passwordless SSH setup successful!"
    echo "You can now run './deploy.sh' to sync the code."
else
    echo "Failed to setup passwordless SSH. Please check your network connection and password."
fi

