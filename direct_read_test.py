import boto3
import os
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url="https://s3.eu-central-003.backblazeb2.com",
    aws_access_key_id=os.environ["B2_KEY_ID"],
    aws_secret_access_key=os.environ["B2_APP_KEY"]
)

bucket = os.environ["B2_BUCKET"]
file_key = "20250810_111920_a6d0dff35749411f8e9f60736171524e.jpg"

try:
    s3.download_file(bucket, file_key, "test_download.jpg")
    print("✅ File downloaded successfully")
except Exception as e:
    print("❌ Error:", e)