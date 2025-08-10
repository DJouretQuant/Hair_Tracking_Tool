import boto3
import os
from dotenv import load_dotenv

# Load your .env so we can use your existing credentials
load_dotenv()

B2_BUCKET = os.environ.get("B2_BUCKET")
B2_KEY_ID = os.environ.get("B2_KEY_ID")
B2_APP_KEY = os.environ.get("B2_APP_KEY")
SIGNED_URL_EXPIRY = 60  # 1 minute for testing

# Create an S3 client for Backblaze
s3 = boto3.client(
    "s3",
    endpoint_url="https://s3.eu-central-003.backblazeb2.com",  # adjust if your bucket region differs
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY
)

# 1️⃣ List objects in the bucket
print(f"Listing objects in bucket '{B2_BUCKET}'...")
resp = s3.list_objects_v2(Bucket=B2_BUCKET)

if "Contents" not in resp:
    print("❌ No files found OR no read permission.")
    exit()

for obj in resp["Contents"]:
    print(f" - {obj['Key']}")

# 2️⃣ Pick the first file and generate a signed URL
file_key = resp["Contents"][0]["Key"]
print(f"\nGenerating signed URL for: {file_key}")

url = s3.generate_presigned_url(
    ClientMethod="get_object",
    Params={"Bucket": B2_BUCKET, "Key": file_key},
    ExpiresIn=SIGNED_URL_EXPIRY
)

print(f"\n✅ Signed URL (valid {SIGNED_URL_EXPIRY} sec):\n{url}")
print("\nOpen this in your browser right now to test.")