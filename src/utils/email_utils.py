import smtplib
import keyring
import getpass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(body, env, email, subject):
    password = keyring.get_password("email", email)
    if password is None:
        password = getpass.getpass("Enter your password: ")
        keyring.set_password("email", email, password)

    # Create email
    msg = MIMEMultipart()
    msg["From"] = email
    msg["To"] = email
    if env == "prod":
        msg["Subject"] = subject
    else:
        msg["Subject"] = f"[{env.upper()}] {subject}"
    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(email, password)
    text = msg.as_string()
    server.sendmail(email, email, text)
    server.quit()
