import os
from flask import Flask, request, render_template, redirect, url_for
from datetime import datetime

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure uploads folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        # Get form data
        region = request.form.get("region")
        lighting = request.form.get("lighting")
        hair_length = request.form.get("hair_length")

        # Get image file
        file = request.files.get("file")
        if file and allowed_file(file.filename):
            # Generate safe filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{region}_{lighting}_{hair_length}.jpg"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

            # Save image
            file.save(filepath)

            return redirect(url_for("upload_file"))

    return render_template("upload.html")

if __name__ == "__main__":
    app.run(debug=True)