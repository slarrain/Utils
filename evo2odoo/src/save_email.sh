#!/bin/bash
# Define a directory to save .eml files, or use the current directory
SAVE_DIR="/home/santiago/github/Utils/evo2odoo/mails"
mkdir -p "$SAVE_DIR"

# Generate a unique filename based on the current date and time
FILENAME="${SAVE_DIR}/email_$(date +'%Y%m%d_%H%M%S').eml"

notify-send "e-mail from Evolution" "Email being saved to $FILENAME"

# Read the email content from stdin and save it to the file
cat > "$FILENAME"

# Output the saved file name
echo "Email saved to $FILENAME"
