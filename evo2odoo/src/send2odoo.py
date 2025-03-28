from loguru import logger
import email
from email import policy
from email.parser import BytesParser

from glob import glob
import argparse
import re
import xmlrpc.client
import json
import requests
from datetime import datetime
from pathlib import Path


def process_email(file_path):
    
    # TODO: Remove creds
    url = 'http://192.168.1.50:8069'
    db = 'pacificlabs'
    username = 'santiagolarrain@pacificlabs.cl'
    password = ''
    common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
    common.version()

    models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

    uid = common.authenticate(db, username, password, {})
    logger.info(f"Processing {file_path}")
    msg = load_email_file(file_path)

    # Extracting basic information from the email
    subject = msg['subject']
    from_email = msg['from']
    to_email = msg['to']
    date = msg['date']
    body = extract_body(msg)
    contenido = f"Subject:{subject}\nFrom:{from_email}\nTo:{to_email}\nDate:{date}\n\n{body}".replace('\n', '<br>')
    try:
        direcciones = extract_emails(to_email)
        if 'cc' in msg:
            direcciones.extend(extract_emails(msg['cc']))
    except TypeError:
        logger.error("No Data on Direcciones. Probably an answer to a Meeting. Deleting.")
        delete_file(file_path)
        return
    date2 = datetime.strptime(date, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d %H:%M:%S")

    for direccion in direcciones:
        logger.info(f"Sarching for {direccion} in the CRM DB...")
        lead_ids = models.execute_kw(db, uid, password, 'crm.lead', 'search', [[['email_from', '=', direccion]]])
        if len(lead_ids) == 0:
            logger.info("No Lead found!")
            continue
        for lead_id in lead_ids:
            logger.warning(f"Posting on {lead_id} in the CRM...")
            print (contenido)

            models.execute_kw(
                    db, 
                    uid, 
                    password, 
                    'mail.message', 
                    'create', 
                    [
                        { 
                         'model': 'crm.lead', 
                         'res_id': lead_id, 
                         'body': contenido, 
                         'author_id': uid, 
                         'create_date': date2, 
                         'date': date2, 
                         'write_date': date2, 
                         'attachment_ids':[]
                         }
                        ]
                    )

    delete_file(file_path)
    # # Display the extracted information
    # print("Subject:", subject)
    # print("From:", from_email)
    # print("To:", to_email)
    # print("Date:", date)
    # print("Body:", body)
    # print (direcciones)

def delete_file(file_path):

    file_path = Path(file_path)

    try:
        file_path.unlink()  # Delete the file
        logger.info(f"{file_path} was deleted successfully.")
    except FileNotFoundError:
        logger.info(f"{file_path} does not exist.")
    except PermissionError:
        logger.info(f"Permission denied to delete {file_path}.")

def extract_body(msg):

    # # Extract the body of the email
    # if msg.is_multipart():
        # # If the email has multiple parts (attachments, text, etc.), iterate over the parts
        # for part in msg.iter_parts():

            # # If it is a multipart in itself
            # if part.is_multipart():
                # for sub_part in part.iter_parts():
                    # if sub_part.get_content_type() == 'text/plain':
                        # body = sub_part.get_payload(decode=True).decode(sub_part.get_content_charset())        
            # else:
                # # Look for the plain text part
                # if part.get_content_type() == 'text/plain':
                    # body = part.get_payload(decode=True).decode(part.get_content_charset())
    # else:
        # try:
            # # If the email is not multipart, get the payload directly
            # body = msg.get_payload(decode=True).decode(msg.get_content_charset())
        # except TypeError:
            # body = "No Body: Probably a Meeting."

    body = get_body(msg)
    body = body.split('--')[0]
    return body


def get_body(msg):
    if not msg.is_multipart() and msg.get_content_type() == 'text/plain':
        try:
            return msg.get_payload(decode=True).decode(msg.get_content_charset())
        except TypeError:
            return "No Body. Probably a Meeting."
    elif msg.is_multipart():
        for part in msg.iter_parts():
            return get_body(part)


def load_email_file(file_path):
    # Open and read the .eml file
    with open(file_path, 'rb') as file:
        # Parse the .eml file using BytesParser
        msg = BytesParser(policy=policy.default).parse(file)
    return msg


def extract_emails(text):
    # Regular expression to find email addresses
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    # Find all email addresses in the text
    emails = re.findall(email_pattern, text)
    return [x.lower() for x in emails]


def main(parser):
    if parser.file_path:
        email_files = [parser.file-path]
    else:
        email_files = glob('../mails/*.eml')
    if len(email_files) == 0:
        logger.error('No email files found!')
    for file_path in email_files:
        process_email(file_path)



if __name__ == '__main__':
	
    parser = argparse.ArgumentParser()
    parser.add_argument('--file-path', type=str, help = "Archivo de correo individual a procesar")
    # parser.add_argument('--data-threshold', type=int, default=40, help='Cantidad mínima de datos que debe tener una serie de tiempo')
    # parser.add_argument('--unique-clients', default=200, help='Tamaño del subconjunto de clientes unicos. None para usar el conjunto completo.')
    # parser.add_argument('--nb-clusters', type = int, default=8, help='Cantidad de clusters a utilizar en algoritmo K-Means.')
    # parser.add_argument('--img-folder', type = str, default = '/home/user/Pictures', help= 'Carpeta en donde se guardará el gráfico generado.')
    # parser.add_argument('--img-name', type = str, default='cluster-example.pdf', help= 'Nombre de la imagen a guardar, debe contener el formato.')
    # parser.add_argument('--nb-jobs', type=int, default=-2, help = 'número de núcleos para ejecutar k-means.')
    # parser.add_argument('--csv-folder', type = str, default='../data/', help="Carpeta en donde se guardara el archivop .csv")
    # parser.add_argument('--csv-name',type=str, default='clients_labels.csv', help="Nombre del archivo .csv de los ids clientes con sus clusters")
    parser = parser.parse_args() 
    main(parser) 
