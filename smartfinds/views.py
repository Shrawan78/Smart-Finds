from django.shortcuts import render
from store.models import Product

import os
import cv2
import numpy as np
import base64
import json
import mediapipe as mp
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def home(request):
    products = Product.objects.all().filter(is_available=True)
    return render(request, "home.html", {'products': products})


# ── Constants ─────────────────────────────────────────────────────────
SHIRTS_DIR  = os.path.join(settings.BASE_DIR, 'smartfinds', 'static', 'tryon', 'shirts')
FIXED_RATIO = 262 / 190   # same as working desktop version

# ── MediaPipe pose singleton ──────────────────────────────────────────
_pose    = None
_mp_pose = mp.solutions.pose

def get_pose():
    global _pose
    if _pose is None:
        _pose = _mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    return _pose


# ── Helpers ───────────────────────────────────────────────────────────
def rotate_image(image, angle):
    h, w = image.shape[:2]
    cx, cy = w // 2, h // 2
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w / 2) - cx
    M[1, 2] += (new_h / 2) - cy
    return cv2.warpAffine(image, M, (new_w, new_h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(0, 0, 0, 0))


# ── Views ─────────────────────────────────────────────────────────────
def virtual_tryon(request):
    shirts = []
    if os.path.exists(SHIRTS_DIR):
        for fname in sorted(os.listdir(SHIRTS_DIR)):
            if fname.lower().endswith(('.png', '.jpg', '.jpeg')):
                shirts.append({
                    'filename':  fname,
                    'name':      os.path.splitext(fname)[0].replace('_', ' ').replace('-', ' ').title(),
                    'thumb_url': f'/static/tryon/shirts/{fname}',
                })
    return render(request, 'virtual_tryon.html', {'shirts': shirts})


@csrf_exempt
def tryon_process_frame(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        body       = json.loads(request.body)
        frame_b64  = body.get('frame', '')
        shirt_name = body.get('shirt', '')

        if not frame_b64:
            return JsonResponse({'success': False, 'error': 'No frame data'})
        if not shirt_name:
            return JsonResponse({'success': False, 'error': 'No shirt selected'})

        if ',' in frame_b64:
            frame_b64 = frame_b64.split(',', 1)[1]

        nparr = np.frombuffer(base64.b64decode(frame_b64), np.uint8)
        img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return JsonResponse({'success': False, 'error': 'Could not decode frame'})

        frameH, frameW = img.shape[:2]
        pose_detected  = False
        overlay_data   = None
        gesture        = 'none'  # ✅ send gesture back to frontend

        # ── Pose detection ──────────────────────────────────────────
        pose    = get_pose()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = pose.process(img_rgb)

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark

            # Shoulders
            lm11_x = int(lm[11].x * frameW);  lm11_y = int(lm[11].y * frameH)
            lm12_x = int(lm[12].x * frameW);  lm12_y = int(lm[12].y * frameH)

            # Wrists
            lm15_y = int(lm[15].y * frameH)   # left wrist
            lm16_y = int(lm[16].y * frameH)   # right wrist

            shoulderDist = abs(lm11_x - lm12_x)
            shoulderY    = min(lm11_y, lm12_y)

            # ✅ Gesture detection — same logic as desktop version
            leftHandRaised  = lm15_y < shoulderY
            rightHandRaised = lm16_y < shoulderY

            if leftHandRaised and rightHandRaised:
                gesture = 'both'
            elif leftHandRaised and not rightHandRaised:
                gesture = 'left'    # next shirt
            elif rightHandRaised and not leftHandRaised:
                gesture = 'right'   # prev shirt
            else:
                gesture = 'none'

            # ✅ Negative angle — correct tilt for mirrored frame
            angle = -np.degrees(np.arctan2(
                lm11_y - lm12_y,
                lm11_x - lm12_x
            ))

            shirt_path = os.path.join(SHIRTS_DIR, shirt_name)

            if shoulderDist >= 20 and os.path.exists(shirt_path):
                imgShirt = cv2.imread(shirt_path, cv2.IMREAD_UNCHANGED)

                if imgShirt is not None:
                    # ✅ Match exact sizing logic from working desktop code
                    widthOfShirt  = int(shoulderDist * FIXED_RATIO)
                    h, w          = imgShirt.shape[:2]
                    heightOfShirt = int(widthOfShirt * (h / w))

                    if widthOfShirt >= 10 and heightOfShirt >= 10:
                        imgShirt   = cv2.resize(imgShirt, (widthOfShirt, heightOfShirt))
                        imgShirt   = rotate_image(imgShirt, angle)
                        rotH, rotW = imgShirt.shape[:2]
                        scale      = shoulderDist / 190

                        # ✅ Exact placement from desktop version
                        placeX = min(lm11_x, lm12_x) - int(44 * scale) - (rotW - widthOfShirt) // 2
                        placeY = shoulderY            - int(48 * scale) - (rotH - heightOfShirt) // 2

                        _, shirt_buf = cv2.imencode('.png', imgShirt, [cv2.IMWRITE_PNG_COMPRESSION, 0])

                        overlay_data = {
                            'x':      placeX,
                            'y':      placeY,
                            'width':  rotW,
                            'height': rotH,
                            'img':    base64.b64encode(shirt_buf).decode('utf-8'),
                        }
                        pose_detected = True

        return JsonResponse({
            'success':       True,
            'pose_detected': pose_detected,
            'overlay':       overlay_data,
            'gesture':       gesture,   # ✅ send gesture to frontend
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def image_search(request):
    return render(request, 'image_search.html')
