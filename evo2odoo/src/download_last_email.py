#!/usr/bin/python3
import imaplib
import os
import email
from datetime import datetime
import time

# IMAP Server details
IMAP_SERVER = 'box5130.bluehost.com'  # e.g., imap.gmail.com
EMAIL = 'santiagolarrain@pacificlabs.cl'
PASSWORD = ''

def download_last_sent_email():
    try:
        # Connect to the IMAP server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL, PASSWORD)
        
        # Select the Sent Items folder
        # Note: Folder name may differ; use 'Sent', '[Gmail]/Sent Mail', or equivalent
        mail.select('INBOX.Sent')

        # Search for all emails in the folder
        status, email_ids = mail.search(None, 'ALL')
        if status != 'OK' or not email_ids[0]:
            print("No emails found.")
            return

        # Get the last email ID
        latest_email_id = email_ids[0].split()[-1]

        # Fetch the email by ID
        status, data = mail.fetch(latest_email_id, '(RFC822)')
        if status != 'OK':
            print("Failed to fetch email.")
            return

        # Extract the raw email content
        raw_email = data[0][1]
        filename = f'/home/santiago/github/Utils/evo2odoo/mails/email_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.eml'
        # Save the email in EML format
        with open(filename, 'wb') as eml_file:
            eml_file.write(raw_email)

        print("Last sent email saved")
        os.system(f'notify-send "Mail Downloaded" "{filename}"')

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        # Logout from the server
        try:
            mail.logout()
        except:
            pass

if __name__ == '__main__':
    # Run the function
    time.sleep(45)
    download_last_sent_email()
