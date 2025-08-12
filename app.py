import os
from datetime import datetime
import uuid
import io
from PIL import Image
from flask import Flask, request, render_template, redirect, url_for, session, flash
from botocore.config import Config
import boto3

# Load environment variables from .env if running locally
if os.environ.get("RENDER") is None:  # RENDER env var exists on Render
    from dotenv import load_dotenv
    load_dotenv()

# Flask setup
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_KEY")  # for sessions

# Environment variables
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APP_KEY = os.environ["B2_APP_KEY"]
B2_BUCKET = os.environ["B2_BUCKET"]
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "testpass")
SIGNED_URL_EXPIRY = int(os.environ.get("SIGNED_URL_EXPIRY", 86400))  # 24h

# B2 S3-compatible client
B2_ENDPOINT = "https://s3.eu-central-003.backblazeb2.com"
b2 = boto3.client(
    "s3",
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY,
    region_name="eu-central-003",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"}
    ),
)

# Helper: strip EXIF metadata
def strip_exif(image_stream):
    image = Image.open(image_stream).convert("RGB")  # force RGB
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    buf.seek(0)
    return buf

@app.route("/")
def index():
    return render_template("index.html")

# Login route for admin
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid password", "error")
    return render_template("login.html")


# Upload route for participants
@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        file = request.files.get("file")
        length_mm = request.form.get("length_mm")
        zone = request.form.get("zone")
        treatment = request.form.get("treatment", "")

        if file:

            # Read image into PIL
            image = Image.open(file.stream)
            
            # === TEMPORARY: Extract EXIF if present ===
            try:
                exif_data = image._getexif()
                if exif_data:
                    readable_exif = {
                        ExifTags.TAGS.get(tag, tag): value
                        for tag, value in exif_data.items()
                    }
                    print("=== EXIF DATA FROM UPLOAD ===")
                    for k, v in readable_exif.items():
                        print(f"{k}: {v}")
                else:
                    print("No EXIF data found in uploaded image.")
            except Exception as e:
                print("Error reading EXIF:", e)

            # Strip EXIF before saving
            rgb_image = image.convert("RGB")
            buf = io.BytesIO()
            rgb_image.save(buf, format="JPEG")
            buf.seek(0)

            # Upload to B2
            clean_img = strip_exif(file.stream)
            filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{zone}_{length_mm}mm_{treatment.replace(' ', '-')}.jpg"
            b2.upload_fileobj(clean_img, B2_BUCKET, filename)
            flash("Upload successful! Thank you for participating.", "success")
            return redirect(url_for("upload_file"))

    return render_template("upload.html")


# Admin dashboard (hidden)
@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        abort(404)

    resp = b2.list_objects_v2(Bucket=B2_BUCKET)
    files = []

    if "Contents" in resp:
        for obj in resp["Contents"]:
            file_key = obj["Key"]

            parts = file_key.split("_", 3)
            date_taken = parts[0]
            zone = parts[1] if len(parts) > 1 else ""
            length_mm = parts[2] if len(parts) > 2 else ""
            treatment = parts[3].rsplit(".", 1)[0] if len(parts) > 3 else ""

            url = b2.generate_presigned_url(
                "get_object",
                Params={"Bucket": B2_BUCKET, "Key": file_key},
                ExpiresIn=SIGNED_URL_EXPIRY
            )

            files.append({
                "key": file_key,
                "url": url,
                "date": date_taken,
                "zone": zone,
                "length_mm": length_mm,
                "treatment": treatment
            })

    return render_template("dashboard.html", files=files)


if __name__ == "__main__":
    app.run(debug=True)
