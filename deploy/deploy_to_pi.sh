#!/bin/bash

TARGET="pi@pi01.local"
DEST_DIR="~/mempi"

echo "=== Deploying mempi project to $TARGET ==="

# We use rsync to efficiently copy the files over SSH
# We exclude the 'build' directory so we don't copy x86/host binaries to the ARM Pi
# (The Pi will need to compile its own binary)
rsync -avz --exclude 'build' --exclude '.git' ./ "$TARGET:$DEST_DIR"

if [ $? -eq 0 ]; then
    echo ""
    echo "Deployment successful!"
    echo ""
    echo "To run the benchmark on the Pi, simply execute:"
    echo "  ssh $TARGET 'cd $DEST_DIR && ./run_on_pi.sh'"
else
    echo ""
    echo "Deployment failed. Did you run ./setup_ssh.sh first?"
fi

