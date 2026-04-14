import os
import sys
import cv2
import numpy as np
import mediapipe as mp
import cvzone
from cvzone.PoseModule import PoseDetector

GLASSES_FOLDER = r"F:\SmartFinds\smartfinds\static\glasses"

# ── Face mesh (glasses overlay) ───────────────────────────────────────
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

# ── Pose detector (hand gestures) ────────────────────────────────────
pose_detector = PoseDetector()

# ── Load glasses ──────────────────────────────────────────────────────
def _load_glasses(folder: str) -> dict:
    images, names = {}, {}
    for i in range(1, 11):
        candidates = [
            f"glass{i}.png",  f"glass{i}.jpg",  f"glass{i}.jpeg",
            f"glasses{i}.png", f"glasses{i}.jpg",
            f"style{i}.png",  f"{i}.png",
        ]
        for fname in candidates:
            path = os.path.join(folder, fname)
            if not os.path.exists(path):
                continue
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
            elif img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            images[i - 1] = img
            names[i - 1]  = os.path.splitext(fname)[0]
            print(f"[glasses] Loaded slot {i}: {fname}")
            break
    print(f"[glasses] Total loaded: {len(images)}")
    return images, names


glasses_images, glasses_names = _load_glasses(GLASSES_FOLDER)

if not glasses_images:
    print(
        "[glasses] ERROR: No glasses PNG files found.\n"
        f"          Add glass1.png … glass10.png to:\n"
        f"          {GLASSES_FOLDER}"
    )
    sys.exit(1)

current_idx    = min(glasses_images.keys())
SCALE          = 2.5
selectionSpeed = 20   # degrees per frame, same as shirts


# ── Core overlay ──────────────────────────────────────────────────────
def _overlay(frame, glasses, eye_l, eye_r, nose, angle_z):
    h, w = frame.shape[:2]
    eye_dist = float(np.linalg.norm(eye_r - eye_l))
    if eye_dist < 10:
        return frame

    gw = int(eye_dist * SCALE)
    gh = int(gw * glasses.shape[0] / glasses.shape[1])
    if gw < 4 or gh < 4:
        return frame

    g_resized = cv2.resize(glasses, (gw, gh))
    center    = (eye_l + eye_r) / 2.0
    cx, cy    = center

    nose_l = float(np.linalg.norm(eye_l - nose))
    nose_r = float(np.linalg.norm(eye_r - nose))
    yaw    = float(np.degrees(np.arctan2(nose_r - nose_l, eye_dist))) * 2.0
    pitch  = float(np.degrees(np.arctan2(
        nose[1] - cy, abs(nose[0] - cx) + 1e-6
    )))

    yf = float(np.clip(yaw   / 45.0, -0.5, 0.5))
    pf = float(np.clip(pitch / 30.0, -0.3, 0.3))

    offset_y = -gh * 0.25
    hw, hh   = gw / 2.0, gh / 2.0

    tl = [cx - hw + yf * hw * 0.3, cy + offset_y - pf * hh * 0.3]
    tr = [cx + hw + yf * hw * 0.3, cy + offset_y - pf * hh * 0.3]
    bl = [cx - hw - yf * hw * 0.2, cy + offset_y + hh + pf * hh * 0.2]
    br = [cx + hw - yf * hw * 0.2, cy + offset_y + hh + pf * hh * 0.2]

    cos_z  = float(np.cos(np.radians(angle_z)))
    sin_z  = float(np.sin(np.radians(angle_z)))
    rot_cy = cy + offset_y

    def rot(pt):
        dx, dy = pt[0] - cx, pt[1] - rot_cy
        return [cx + dx * cos_z - dy * sin_z,
                rot_cy + dx * sin_z + dy * cos_z]

    tl, tr, bl, br = rot(tl), rot(tr), rot(bl), rot(br)

    src    = np.float32([[0, 0], [gw, 0], [gw, gh], [0, gh]])
    dst    = np.float32([tl, tr, br, bl])
    M      = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(g_resized, M, (w, h))

    if g_resized.shape[2] == 4:
        alpha = cv2.warpPerspective(g_resized[:, :, 3], M, (w, h)) / 255.0
        alpha = np.stack([alpha] * 3, axis=2)
        frame = (frame * (1 - alpha) + warped[:, :, :3] * alpha).astype(np.uint8)
    else:
        mask  = cv2.warpPerspective(
            np.ones((gh, gw), np.uint8) * 255, M, (w, h)
        ) / 255.0
        mask  = np.stack([mask] * 3, axis=2)
        frame = (frame * (1 - mask) + warped[:, :, :3] * mask).astype(np.uint8)

    return frame


def _apply_glasses(frame):
    """Run face mesh and overlay the current glasses."""
    if current_idx not in glasses_images:
        return frame

    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return frame

    fh, fw = frame.shape[:2]
    lm     = results.multi_face_landmarks[0].landmark

    def pt(idx):
        return np.array([lm[idx].x * fw, lm[idx].y * fh])

    eye_l   = (pt(33)  + pt(133))  / 2.0
    eye_r   = (pt(263) + pt(362))  / 2.0
    nose    = pt(6)
    angle_z = float(np.degrees(np.arctan2(
        eye_r[1] - eye_l[1], eye_r[0] - eye_l[0]
    )))

    return _overlay(frame, glasses_images[current_idx], eye_l, eye_r, nose, angle_z)


# ── HUD ───────────────────────────────────────────────────────────────
def _draw_hud(img):
    name   = glasses_names.get(current_idx, f"Style {current_idx + 1}")
    loaded = sorted(glasses_images.keys())
    pos    = loaded.index(current_idx) + 1

    cv2.putText(img,
                f"Glasses: {name}  ({pos}/{len(loaded)})",
                (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.putText(img,
                "Raise LEFT hand = next   Raise RIGHT hand = prev   A/D keys also work   Q = quit",
                (16, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200, 200, 200), 1)


# ── Main loop ─────────────────────────────────────────────────────────
def main():
    global current_idx

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[glasses] ERROR: Could not open webcam.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)

    loaded_keys  = sorted(glasses_images.keys())
    counterLeft  = 0
    counterRight = 0

    # Button sprites for the gesture arc — same positions as shirts
    BASE_DIR        = r"F:\SmartFinds"
    btn_path        = os.path.join(BASE_DIR, "static", "tryon", "button.png")
    imgButtonRight  = cv2.imread(btn_path, cv2.IMREAD_UNCHANGED)
    imgButtonLeft   = cv2.flip(imgButtonRight, 1) if imgButtonRight is not None else None

    print("[glasses] Running — raise hand or press A/D to switch, Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        frameH, frameW = frame.shape[:2]

        # ── Step 1: pose detection (gesture logic) ────────────────────
        frame = pose_detector.findPose(frame, draw=False)
        lmList, _ = pose_detector.findPosition(frame, bboxWithHands=False, draw=False)

        leftHandRaised  = False
        rightHandRaised = False

        if lmList:
            if (hasattr(pose_detector, 'results')
                    and pose_detector.results
                    and pose_detector.results.pose_landmarks):

                landmarks = pose_detector.results.pose_landmarks.landmark

                lm11_y = int(landmarks[11].y * frameH)   # left shoulder
                lm12_y = int(landmarks[12].y * frameH)   # right shoulder
                lm15_y = int(landmarks[15].y * frameH)   # left wrist
                lm16_y = int(landmarks[16].y * frameH)   # right wrist

                shoulderY       = min(lm11_y, lm12_y)
                leftHandRaised  = lm15_y < shoulderY
                rightHandRaised = lm16_y < shoulderY

        # ── Step 2: draw button sprites ───────────────────────────────
        if imgButtonRight is not None:
            try:
                frame = cvzone.overlayPNG(frame, imgButtonRight, (1074, 293))
                frame = cvzone.overlayPNG(frame, imgButtonLeft,  (72,   293))
            except Exception:
                pass

        # ── Step 3: gesture → glasses selection ──────────────────────
        if leftHandRaised and rightHandRaised:
            counterLeft  = 0
            counterRight = 0

        elif leftHandRaised and not rightHandRaised:
            # Left hand raised → advance to next style
            counterLeft += 1
            cv2.ellipse(frame, (1138, 360), (66, 66), 0, 0,
                        counterLeft * selectionSpeed, (0, 255, 0), 20)
            if counterLeft * selectionSpeed > 360:
                counterLeft = 0
                idx         = loaded_keys.index(current_idx)
                current_idx = loaded_keys[(idx + 1) % len(loaded_keys)]

        elif rightHandRaised and not leftHandRaised:
            # Right hand raised → go to previous style
            counterRight += 1
            cv2.ellipse(frame, (139, 360), (66, 66), 0, 0,
                        counterRight * selectionSpeed, (0, 255, 0), 20)
            if counterRight * selectionSpeed > 360:
                counterRight = 0
                idx          = loaded_keys.index(current_idx)
                current_idx  = loaded_keys[(idx - 1) % len(loaded_keys)]

        else:
            counterLeft  = 0
            counterRight = 0

        # ── Step 4: face mesh + glasses overlay ───────────────────────
        frame = _apply_glasses(frame)

        # ── Step 5: HUD + display ─────────────────────────────────────
        _draw_hud(frame)
        cv2.imshow("Virtual Glasses Try-On  |  Raise hand or A/D  |  Q = quit", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('d'):
            idx         = loaded_keys.index(current_idx)
            current_idx = loaded_keys[(idx + 1) % len(loaded_keys)]
        elif key == ord('a'):
            idx         = loaded_keys.index(current_idx)
            current_idx = loaded_keys[(idx - 1) % len(loaded_keys)]

    cap.release()
    cv2.destroyAllWindows()
    face_mesh.close()


if __name__ == "__main__":
    main()
