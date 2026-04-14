from django.shortcuts import render
from store.models import Product
from carts.models import Cart, CartItem

import os
import sys
import pickle
import subprocess
import cv2
import numpy as np
import base64
import json
import io, math
import traceback
from PIL import Image
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from numpy.linalg import norm
from tensorflow.keras.preprocessing import image
from tensorflow.keras.layers import GlobalMaxPool2D
from tensorflow.keras.applications.resnet50 import ResNet50, preprocess_input
from sklearn.neighbors import NearestNeighbors
import tensorflow
from django.core.files.storage import FileSystemStorage
import mediapipe as mp
from PIL import Image as PILImage
import base64, io, json


# ── Desktop Try-On subprocess — SHIRTS ───────────────────────────────
_tryon_process = None

@csrf_exempt
def launch_tryon_app(request):
    """Launch the desktop OpenCV shirt try-on app as a subprocess on Windows."""
    global _tryon_process
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    if _tryon_process and _tryon_process.poll() is None:
        _tryon_process.kill()
        _tryon_process = None

    try:
        script_path = r"F:\SmartFinds\virtual try-on\virtual_try-on.py"

        if not os.path.exists(script_path):
            return JsonResponse({
                "success": False,
                "error": f"Script not found at: {script_path}"
            })

        _tryon_process = subprocess.Popen(
            [sys.executable, script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return JsonResponse({"success": True, "pid": _tryon_process.pid})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)})


@csrf_exempt
def stop_tryon_app(request):
    """Kill the shirt try-on app."""
    global _tryon_process
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    if _tryon_process and _tryon_process.poll() is None:
        _tryon_process.kill()
        _tryon_process = None
        return JsonResponse({"success": True})

    _tryon_process = None
    return JsonResponse({"success": True, "message": "No process was running"})


@csrf_exempt
def tryon_status(request):
    """Poll whether the shirt desktop app is still running."""
    global _tryon_process
    running = _tryon_process is not None and _tryon_process.poll() is None
    return JsonResponse({"running": running})


# ── Desktop Try-On subprocess — GLASSES ──────────────────────────────
_glasses_process = None

@csrf_exempt
def launch_glasses_app(request):
    """Launch the desktop OpenCV glasses try-on app as a subprocess on Windows."""
    global _glasses_process
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    if _glasses_process and _glasses_process.poll() is None:
        _glasses_process.kill()
        _glasses_process = None

    try:
        # Place virtual_glasses_tryon.py next to the shirt script
        script_path = r"F:\SmartFinds\virtual try-on\virtual_glasses_tryon.py"

        if not os.path.exists(script_path):
            return JsonResponse({
                "success": False,
                "error": f"Glasses script not found at: {script_path}"
            })

        _glasses_process = subprocess.Popen(
            [sys.executable, script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return JsonResponse({"success": True, "pid": _glasses_process.pid})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)})


@csrf_exempt
def stop_glasses_app(request):
    """Kill the glasses try-on app."""
    global _glasses_process
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    if _glasses_process and _glasses_process.poll() is None:
        _glasses_process.kill()
        _glasses_process = None
        return JsonResponse({"success": True})

    _glasses_process = None
    return JsonResponse({"success": True, "message": "No process was running"})


@csrf_exempt
def glasses_status(request):
    """Poll whether the glasses desktop app is still running."""
    global _glasses_process
    running = _glasses_process is not None and _glasses_process.poll() is None
    return JsonResponse({"running": running})


# ── Home ──────────────────────────────────────────────────────────────
def home(request):
    products = Product.objects.all().filter(is_available=True)
    return render(request, "home.html", {'products': products})


# ── Virtual Try-On page ───────────────────────────────────────────────
_SHIRTS_DIR  = settings.BASE_DIR / "static" / "tryon" / "shirts"
_GLASSES_DIR = settings.BASE_DIR / "static" / "tryon" / "glasses"


def tryon_page(request):
    # Shirts
    shirts = []
    if _SHIRTS_DIR.is_dir():
        for fname in sorted(_SHIRTS_DIR.iterdir()):
            if fname.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                display = " ".join(
                    w.capitalize()
                    for w in fname.stem.replace("_", " ").replace("-", " ").split()
                )
                shirts.append({
                    "filename":  fname.name,
                    "name":      display,
                    "thumb_url": f"/static/tryon/shirts/{fname.name}",
                })

    # Glasses
    glasses_list = []
    if _GLASSES_DIR.is_dir():
        for fname in sorted(_GLASSES_DIR.iterdir()):
            if fname.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                display = " ".join(
                    w.capitalize()
                    for w in fname.stem.replace("_", " ").replace("-", " ").split()
                )
                glasses_list.append({
                    "filename":  fname.name,
                    "name":      display,
                    "thumb_url": f"/static/tryon/glasses/{fname.name}",
                })

    return render(request, "virtual_tryon.html", {
        "shirts":  shirts,
        "glasses": glasses_list,
    })


# ── ML Model Setup (Lazy Loading) ─────────────────────────────────────
ML_DIR = os.path.join(settings.BASE_DIR, 'ml')

feature_list = None
filenames    = None
ml_model     = None
neighbors    = None

# Model 2 — store (52 images)
store_feature_list = None
store_filenames    = None
store_neighbors    = None


def load_ml_model():
    global feature_list, filenames, ml_model, neighbors
    if ml_model is None:
        print("Loading ML model...")
        feature_list = np.array(pickle.load(open(os.path.join(ML_DIR, 'embeddings.pkl'), 'rb')))
        filenames    = pickle.load(open(os.path.join(ML_DIR, 'filenames.pkl'), 'rb'))
        ml_model     = ResNet50(weights="imagenet", include_top=False, input_shape=(224, 224, 3))
        ml_model.trainable = False
        ml_model     = tensorflow.keras.Sequential([ml_model, GlobalMaxPool2D()])
        neighbors    = NearestNeighbors(n_neighbors=5, algorithm="brute", metric="euclidean")
        neighbors.fit(feature_list)
        print("ML model loaded successfully!")

def load_store_model():
    global store_feature_list, store_filenames, store_neighbors, ml_model
    if ml_model is None:
        load_ml_model()
    if store_neighbors is None:
        print("Loading store model...")
        store_feature_list = np.array(pickle.load(open(os.path.join(ML_DIR, 'store_embeddings.pkl'), 'rb')))
        store_filenames    = pickle.load(open(os.path.join(ML_DIR, 'store_filenames.pkl'), 'rb'))
        store_neighbors    = NearestNeighbors(n_neighbors=3, algorithm="brute", metric="euclidean")
        store_neighbors.fit(store_feature_list)
        print("Store model loaded successfully!")


def extract_feature(img_path, model):
    img              = image.load_img(img_path, target_size=(224, 224))
    img_array        = image.img_to_array(img)
    expanded_img     = np.expand_dims(img_array, axis=0)
    preprocessed_img = preprocess_input(expanded_img)
    result           = model.predict(preprocessed_img, verbose=0).flatten()
    return result / norm(result)


# ── Image Search ──────────────────────────────────────────────────────
def image_search(request):
    results       = []
    store_results = []
    error         = None

    if request.method == 'POST' and request.FILES.get('image'):
        try:
            load_ml_model()
            load_store_model()

            uploaded_file = request.FILES['image']
            fs            = FileSystemStorage(location=os.path.join(settings.BASE_DIR, 'media', 'uploads'))
            filename      = fs.save(uploaded_file.name, uploaded_file)
            uploaded_path = fs.path(filename)

            features = extract_feature(uploaded_path, ml_model)

            # Model 1 — 5 results from ml/images/
            distances, indices = neighbors.kneighbors([features])
            for idx in indices[0]:
                img_name = os.path.basename(filenames[idx])
                results.append(f'/ml-images/{img_name}')

            # Model 2 — 3 results from ml/available/
            s_distances, s_indices = store_neighbors.kneighbors([features])
            for idx in s_indices[0]:
                img_name  = os.path.basename(store_filenames[idx])
                slug      = os.path.splitext(img_name)[0]
                product   = Product.objects.filter(slug=slug, is_available=True).first()
                store_results.append({
                    'img_url': f'/available-images/{img_name}',
                    'price':   product.price if product else None,
                    'name':    product.product_name if product else slug,
                })

            os.remove(uploaded_path)

        except Exception as e:
            error = f"Error processing image: {str(e)}"
            print(error)

    return render(request, 'image_search.html', {
        'results':       results,
        'store_results': store_results,
        'error':         error,
    })

@csrf_exempt
def photo_tryon(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    try:
        # ── Parse request ──────────────────────────────────────────
        body        = json.loads(request.body)
        image_b64   = body.get('image')          # base64 data URL
        shirt_path  = body.get('shirt')          # relative URL like /static/tryon/shirts/x.png
        glasses_path = body.get('glasses')       # relative URL like /static/tryon/glasses/x.png

        # Decode the uploaded photo
        header, encoded = image_b64.split(',', 1)
        img_bytes = base64.b64decode(encoded)
        pil_img   = PILImage.open(io.BytesIO(img_bytes)).convert('RGBA')
        frame     = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGBA2BGR)
        h, w      = frame.shape[:2]

        # ── MediaPipe Face Mesh (for glasses) ──────────────────────
        if glasses_path:
            static_path = str(settings.BASE_DIR) + glasses_path
            glasses_img = cv2.imread(static_path, cv2.IMREAD_UNCHANGED)  # keep alpha

            mp_face_mesh = mp.solutions.face_mesh
            with mp_face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5
            ) as face_mesh:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                if results.multi_face_landmarks:
                    lm = results.multi_face_landmarks[0].landmark

                    # Left eye outer(33) → Right eye outer(263)
                    left_eye  = lm[33]
                    right_eye = lm[263]
                    # Nose bridge top
                    nose_top  = lm[168]

                    lx = int(left_eye.x  * w)
                    rx = int(right_eye.x * w)
                    ny = int(nose_top.y  * h)

                    eye_width  = abs(rx - lx)
                    # Make glasses ~1.6x the eye span (covers temples)
                    gw = int(eye_width * 1.6)
                    if glasses_img is not None and gw > 0:
                        gh = int(gw * glasses_img.shape[0] / glasses_img.shape[1])
                        resized_g = cv2.resize(glasses_img, (gw, gh))

                        # Center horizontally between eyes, vertically at eye level
                        mid_x = (lx + rx) // 2
                        gx = mid_x - gw // 2
                        gy = ny - gh // 2

                        frame = overlay_transparent(frame, resized_g, gx, gy)

        # ── MediaPipe Pose (for shirt) ─────────────────────────────
        if shirt_path:
            static_path = str(settings.BASE_DIR) + shirt_path
            shirt_img   = cv2.imread(static_path, cv2.IMREAD_UNCHANGED)

            mp_pose = mp.solutions.pose
            with mp_pose.Pose(
                static_image_mode=True,
                model_complexity=1,
                min_detection_confidence=0.5
            ) as pose:
                rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = pose.process(rgb)

                if results.pose_landmarks:
                    lm = results.pose_landmarks.landmark
                    # Landmarks: LEFT_SHOULDER=11, RIGHT_SHOULDER=12, LEFT_HIP=23, RIGHT_HIP=24
                    ls = lm[11]; rs = lm[12]
                    lh = lm[23]; rh = lm[24]

                    lsx = int(ls.x * w); rsx = int(rs.x * w)
                    lsy = int(ls.y * h); rsy = int(rs.y * h)
                    lhx = int(lh.x * w); rhx = int(rh.x * w)
                    lhy = int(lh.y * h); rhy = int(rh.y * h)

                    shoulder_width = abs(rsx - lsx)
                    torso_height   = abs(((lhy + rhy) // 2) - ((lsy + rsy) // 2))

                    # Shirt width = 1.3× shoulder span; height from aspect ratio
                    sw = int(shoulder_width * 1.3)
                    if shirt_img is not None and sw > 0:
                        sh = int(sw * shirt_img.shape[0] / shirt_img.shape[1])
                        # Stretch to torso if needed
                        if torso_height > 0:
                            sh = max(sh, int(torso_height * 1.1))
                        resized_s = cv2.resize(shirt_img, (sw, sh))

                        mid_shoulder_x = (lsx + rsx) // 2
                        shoulder_y     = (lsy + rsy) // 2
                        sx = mid_shoulder_x - sw // 2
                        sy = shoulder_y - int(sh * 0.15)   # slight upward anchor at collar

                        frame = overlay_transparent(frame, resized_s, sx, sy)

        # ── Encode result ──────────────────────────────────────────
        result_pil = PILImage.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        buf = io.BytesIO()
        result_pil.save(buf, format='PNG')
        result_b64 = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

        return JsonResponse({'success': True, 'image': result_b64})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})


def overlay_transparent(background, overlay, x, y):
    """Paste an RGBA overlay onto a BGR background at (x, y), handling bounds."""
    bg = background.copy()
    bh, bw = bg.shape[:2]
    oh, ow = overlay.shape[:2]

    # Clip to canvas
    x1, y1 = max(x, 0), max(y, 0)
    x2, y2 = min(x + ow, bw), min(y + oh, bh)
    if x2 <= x1 or y2 <= y1:
        return bg

    ox1 = x1 - x; oy1 = y1 - y
    ox2 = ox1 + (x2 - x1); oy2 = oy1 + (y2 - y1)

    roi     = bg[y1:y2, x1:x2]
    ov_crop = overlay[oy1:oy2, ox1:ox2]

    if overlay.shape[2] == 4:
        alpha = ov_crop[:, :, 3:4].astype(np.float32) / 255.0
        ov_bgr = cv2.cvtColor(ov_crop, cv2.COLOR_BGRA2BGR)
        blended = (ov_bgr.astype(np.float32) * alpha + roi.astype(np.float32) * (1 - alpha))
        bg[y1:y2, x1:x2] = blended.astype(np.uint8)
    else:
        bg[y1:y2, x1:x2] = ov_crop

    return bg

@csrf_exempt
def add_tryon_item_to_cart(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    # Must be logged in (or handle guest cart below)
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'redirect_login': True})

    try:
        body     = json.loads(request.body)
        filename = body.get('filename', '')          # e.g. "blue_oxford_shirt.png"

        # Convert filename → display name → match Product
        stem         = os.path.splitext(filename)[0]  # "blue_oxford_shirt"
        display_name = ' '.join(
            w.capitalize()
            for w in stem.replace('_', ' ').replace('-', ' ').split()
        )  # "Blue Oxford Shirt"

        product = Product.objects.filter(
            product_name__iexact=display_name,
            is_available=True
        ).first()

        if not product:
            return JsonResponse({
                'success': False,
                'error': f'"{display_name}" was not found in the store.'
            })

        # Add to authenticated user's cart
        cart_item, created = CartItem.objects.get_or_create(
            product=product,
            user=request.user,
            defaults={'quantity': 0}
        )
        cart_item.quantity += 1
        cart_item.save()

        return JsonResponse({'success': True, 'product': display_name})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

def coming_soon(request):
    return HttpResponse("Coming Soon")
