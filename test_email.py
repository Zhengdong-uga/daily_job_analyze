from email.message import EmailMessage
msg = EmailMessage()
msg.add_attachment(b'data', maintype='image', subtype='png', filename='test.png', cid='<test.png>', disposition='inline')
print(msg.as_string())
