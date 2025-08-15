from datetime import datetime
import uuid, os, io, base64
from flask import Flask, request, render_template, redirect, url_for, session, flash
from botocore.config import Config
import boto3

import base64, io, numpy as np, cv2
import mediapipe as mp
from PIL import Image
import mediapipe as mp



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

# Cross-platform tmp directory:
if os.environ.get("RENDER"):     # running on Render/Linux
    TMP_DIR = "/tmp"
else:                            # local dev (Windows/macOS/Linux)
    # use a project-local tmp folder so it's predictable
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TMP_DIR = os.path.join(BASE_DIR, "tmp")

os.makedirs(TMP_DIR, exist_ok=True)
print(f"[INIT] Using TMP_DIR: {TMP_DIR}")


mp_face_mesh = mp.solutions.face_mesh

# Landmark indices (FaceMesh 468 topology)
LM_LEFT_EYE  = [33, 133, 160, 159, 158, 157, 173, 246, 163, 144, 145, 153]
LM_RIGHT_EYE = [362, 263, 387, 386, 385, 384, 398, 466, 373, 380, 381, 382]
LM_NOSE      = [1, 2, 4, 5, 98, 327, 94, 331, 168, 197, 419, 188, 236]
LM_MOUTH     = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308]

# Helper: strip EXIF metadata
def strip_exif(image_stream):
    image = Image.open(image_stream).convert("RGB")  # force RGB
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    buf.seek(0)
    return buf

# Helper: anonymize face using MediaPipe FaceMesh
def _px_points(lms, idxs, w, h):
    pts = []
    for i in idxs:
        xi = int(lms[i].x * w); yi = int(lms[i].y * h)
        pts.append([max(0, min(xi, w-1)), max(0, min(yi, h-1))])
    return np.array(pts, dtype=np.int32)

# Helper: anonymize face using MediaPipe FaceMesh
def _expanded_rect_from_points(points, w, h, pad=0.30):
    # tight bbox
    x_min = int(points[:,0].min()); x_max = int(points[:,0].max())
    y_min = int(points[:,1].min()); y_max = int(points[:,1].max())
    # expand proportionally
    bw = x_max - x_min; bh = y_max - y_min
    x_min = max(0, int(x_min - pad * bw))
    x_max = min(w-1, int(x_max + pad * bw))
    y_min = max(0, int(y_min - pad * bh))
    y_max = min(h-1, int(y_max + pad * bh))
    return x_min, y_min, x_max, y_max

def build_mask_preview_and_final(pil_image: Image.Image):
    """Returns (preview_pil, final_masked_pil). Uses MediaPipe; falls back gracefully."""
    img_rgb = np.array(pil_image.convert("RGB"))
    h, w = img_rgb.shape[:2]
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

    with mp_face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5
    ) as fm:
        res = fm.process(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

    # Fallback if no face
    if not res.multi_face_landmarks:
        # central band as safety: covers eyes–nose–mouth for most portraits
        x1, y1 = int(0.10*w), int(0.25*h)
        x2, y2 = int(0.90*w), int(0.80*h)
    else:
        lms = res.multi_face_landmarks[0].landmark
        pts = np.vstack([
            _px_points(lms, LM_LEFT_EYE,  w, h),
            _px_points(lms, LM_RIGHT_EYE, w, h),
            _px_points(lms, LM_NOSE,      w, h),
            _px_points(lms, LM_MOUTH,     w, h),
        ])
        # Build a single big rectangle over mid-face, with generous padding
        x1, y1, x2, y2 = _expanded_rect_from_points(pts, w, h, pad=0.35)

    # ---- Build PREVIEW: semi-transparent red overlay
    overlay = img_bgr.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0,0,255), thickness=-1)  # red in BGR
    alpha = 0.65  # transparency
    preview_bgr = cv2.addWeighted(overlay, alpha, img_bgr, 1 - alpha, 0)

    # ---- Build FINAL: solid black rectangle
    final_bgr = img_bgr.copy()
    cv2.rectangle(final_bgr, (x1, y1), (x2, y2), (0,0,0), thickness=-1)

    # Convert back to PIL
    preview_pil = Image.fromarray(cv2.cvtColor(preview_bgr, cv2.COLOR_BGR2RGB))
    final_pil   = Image.fromarray(cv2.cvtColor(final_bgr,   cv2.COLOR_BGR2RGB))
    return preview_pil, final_pil

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/<lang>")
def landing(lang):
    if lang not in ["en", "fr", "nl"]:
        lang = "en"
    return render_template(f"index_{lang}.html")

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

@app.route("/upload", methods=["GET"])
def upload_file():
    return render_template("upload.html")


@app.route("/preview", methods=["POST"])
def preview():
    file = request.files.get("file")
    length_mm = request.form.get("length_mm", "")
    zone = request.form.get("zone", "")
    treatment = request.form.get("treatment", "")

    if not file:
        flash("Please select an image.", "error")
        return redirect(url_for("upload_file"))

    original = Image.open(file.stream)
    preview_img, final_img = build_mask_preview_and_final(original)

    # save PREVIEW (for display) as base64 (small-ish) 
    buf_prev = io.BytesIO(); preview_img.save(buf_prev, format="JPEG", quality=85)
    preview_b64 = base64.b64encode(buf_prev.getvalue()).decode("utf-8")
    print(f"[PREVIEW] Generated preview image, size: {preview_img.size}, mode: {preview_img.mode}")
    
    # save FINAL to /tmp, reference by token (no base64 in form)
    token = uuid.uuid4().hex
    tmp_path = os.path.join(TMP_DIR, f"{token}.jpg")
    final_img.save(tmp_path, format="JPEG", quality=92)

    return render_template(
        "preview.html",
        preview_b64=preview_b64,
        token=token,
        length_mm=length_mm,
        zone=zone,
        treatment=treatment,
    )

@app.route("/confirm", methods=["POST"])
def confirm_upload():
    token = request.form.get("token")
    length_mm = request.form.get("length_mm", "")
    zone = request.form.get("zone", "")
    treatment = request.form.get("treatment", "")

    if not token:
        flash("Preview token missing. Please try again.", "error")
        return redirect(url_for("upload_file"))

    tmp_path = os.path.join(TMP_DIR, f"{token}.jpg")
    if not os.path.exists(tmp_path):
        flash("Preview expired. Please try again.", "error")
        return redirect(url_for("upload_file"))

    with open(tmp_path, "rb") as f:
        buf = io.BytesIO(f.read())

    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{zone}_{length_mm}mm_{treatment.replace(' ', '-')}.jpg"
    b2.upload_fileobj(buf, B2_BUCKET, filename)

    # cleanup
    try: os.remove(tmp_path)
    except: pass

    flash("Upload successful! Thank you for contributing.", "success")
    return redirect(url_for("upload_file"))

# Upload route for participants
# @app.route("/upload", methods=["GET", "POST"])
# def upload_file():
#     if request.method == "POST":
#         file = request.files.get("file")
#         length_mm = request.form.get("length_mm")
#         zone = request.form.get("zone")
#         treatment = request.form.get("treatment", "")

#         if file:

#             # Read image into PIL
#             image = Image.open(file.stream)
            
#             # === TEMPORARY: Extract EXIF if present ===
#             try:
#                 exif_data = image._getexif()
#                 if exif_data:
#                     readable_exif = {
#                         ExifTags.TAGS.get(tag, tag): value
#                         for tag, value in exif_data.items()
#                     }
#                     print("=== EXIF DATA FROM UPLOAD ===")
#                     for k, v in readable_exif.items():
#                         print(f"{k}: {v}")
#                 else:
#                     print("No EXIF data found in uploaded image.")
#             except Exception as e:
#                 print("Error reading EXIF:", e)

#             # Strip EXIF before saving
#             rgb_image = image.convert("RGB")
#             buf = io.BytesIO()
#             rgb_image.save(buf, format="JPEG")
#             buf.seek(0)

#             # Upload to B2
#             clean_img = strip_exif(file.stream)
#             filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{zone}_{length_mm}mm_{treatment.replace(' ', '-')}.jpg"
#             b2.upload_fileobj(clean_img, B2_BUCKET, filename)
#             flash("Upload successful! Thank you for participating.", "success")
#             return redirect(url_for("upload_file"))

#     return render_template("upload.html")


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
