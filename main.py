from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

kite = KiteConnect(api_key=API_KEY)

request_token = input("Enter Request Token: ")

data = kite.generate_session(
    request_token=request_token,
    api_secret=API_SECRET
)

access_token = data["access_token"]

print("\n✅ Login Successful!")
print("Access Token:")
print(access_token)