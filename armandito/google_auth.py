import os, sys, json
sys.path.insert(0, "/root/armandito")
os.chdir("/root/armandito")

from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar"]

flow = Flow.from_client_secrets_file(
    "data/google_credentials.json",
    scopes=SCOPES,
    redirect_uri="urn:ietf:wg:oauth:2.0:oob"
)

auth_url, _ = flow.authorization_url(prompt="consent")

print("\n=== AUTENTICACION GOOGLE CALENDAR ===\n")
print("Abre este link en tu navegador:\n")
print(auth_url)
print("\nDespues de autorizar, Google te dara un codigo.")
code = input("Pega el codigo aqui: ")

flow.fetch_token(code=code)
creds = flow.credentials

with open("data/google_token.json", "w") as f:
    f.write(creds.to_json())

print("\nAutenticacion exitosa! Token guardado.")
