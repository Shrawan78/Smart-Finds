import os
import cvzone
import cv2
import numpy as np
from cvzone.PoseModule import PoseDetector

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

detector = PoseDetector()

# ── Shirts folder — points to Django's static shirts directory ────────
BASE_DIR        = r"F:\SmartFinds"
shirtFolderPath = os.path.join(BASE_DIR, "static", "tryon", "shirts")
listShirts      = sorted([f for f in os.listdir(shirtFolderPath) if f.lower().endswith(".png")])

if not listShirts:
    print("No shirts found in:", shirtFolderPath)
    exit()

fixedRatio   = 262 / 190
imageNumber  = 0

imgButtonRight = cv2.imread(os.path.join(BASE_DIR, "static", "tryon", "button.png"), cv2.IMREAD_UNCHANGED)
if imgButtonRight is not None:
    imgButtonLeft = cv2.flip(imgButtonRight, 1)
else:
    imgButtonRight = None
    imgButtonLeft  = None

counterRight   = 0
counterLeft    = 0
selectionSpeed = 10


def rotate_image(image, angle):
    h, w  = image.shape[:2]
    cx, cy = w // 2, h // 2
    M     = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    cos   = abs(M[0, 0])
    sin   = abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w / 2) - cx
    M[1, 2] += (new_h / 2) - cy
    return cv2.warpAffine(image, M, (new_w, new_h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(0, 0, 0, 0))


while True:
    success, img = cap.read()
    if not success:
        break

    img = cv2.flip(img, 1)
    frameH, frameW, _ = img.shape

    img = detector.findPose(img, draw=False)
    lmList, bboxInfo = detector.findPosition(img, bboxWithHands=False, draw=False)

    if lmList:
        if hasattr(detector, 'results') and detector.results and detector.results.pose_landmarks:
            landmarks = detector.results.pose_landmarks.landmark

            # ── Shoulders ─────────────────────────────────────────────
            lm11_x = int(landmarks[11].x * frameW)
            lm11_y = int(landmarks[11].y * frameH)
            lm12_x = int(landmarks[12].x * frameW)
            lm12_y = int(landmarks[12].y * frameH)

            # ── Wrists ────────────────────────────────────────────────
            lm15_y = int(landmarks[15].y * frameH)
            lm16_y = int(landmarks[16].y * frameH)

            shoulderY = min(lm11_y, lm12_y)

            leftHandRaised  = lm15_y < shoulderY
            rightHandRaised = lm16_y < shoulderY

            dx    = lm11_x - lm12_x
            dy    = lm11_y - lm12_y
            angle = -np.degrees(np.arctan2(dy, dx))

            imgShirt = cv2.imread(
                os.path.join(shirtFolderPath, listShirts[imageNumber]),
                cv2.IMREAD_UNCHANGED
            )

            if imgShirt is not None:
                shoulderDist  = abs(lm11_x - lm12_x)
                widthOfShirt  = int(shoulderDist * fixedRatio)
                shirtImgH, shirtImgW = imgShirt.shape[:2]
                originalRatio = shirtImgH / shirtImgW
                heightOfShirt = int(widthOfShirt * originalRatio)

                if widthOfShirt >= 10 and heightOfShirt >= 10:
                    imgShirt = cv2.resize(imgShirt, (widthOfShirt, heightOfShirt))
                    imgShirt = rotate_image(imgShirt, angle)
                    rotH, rotW = imgShirt.shape[:2]

                    currentScale = shoulderDist / 190
                    offsetX = int(44 * currentScale)
                    offsetY = int(48 * currentScale)

                    placeX = min(lm11_x, lm12_x) - offsetX - (rotW - widthOfShirt) // 2
                    placeY = shoulderY - offsetY - (rotH - heightOfShirt) // 2

                    try:
                        img = cvzone.overlayPNG(img, imgShirt, (placeX, placeY))
                    except Exception as e:
                        print("Overlay error:", e)

            # ── Navigation buttons ────────────────────────────────────
            if imgButtonRight is not None:
                try:
                    img = cvzone.overlayPNG(img, imgButtonRight, (1074, 293))
                    img = cvzone.overlayPNG(img, imgButtonLeft,  (72,   293))
                except:
                    pass

            # ── Gesture → shirt selection ─────────────────────────────
            if leftHandRaised and rightHandRaised:
                counterRight = 0
                counterLeft  = 0

            elif leftHandRaised and not rightHandRaised:
                counterLeft += 1
                cv2.ellipse(img, (1138, 360), (66, 66), 0, 0,
                            counterLeft * selectionSpeed, (0, 255, 0), 20)
                if counterLeft * selectionSpeed > 360:
                    counterLeft  = 0
                    imageNumber  = (imageNumber + 1) % len(listShirts)

            elif rightHandRaised and not leftHandRaised:
                counterRight += 1
                cv2.ellipse(img, (139, 360), (66, 66), 0, 0,
                            counterRight * selectionSpeed, (0, 255, 0), 20)
                if counterRight * selectionSpeed > 360:
                    counterRight = 0
                    imageNumber  = (imageNumber - 1) % len(listShirts)

            else:
                counterRight = 0
                counterLeft  = 0

    # ── Current shirt name overlay (top-left HUD) ─────────────────────
    cv2.putText(img,
                f"Shirt: {os.path.splitext(listShirts[imageNumber])[0]}  ({imageNumber+1}/{len(listShirts)})",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    cv2.imshow("Virtual Try-On  |  Q to quit", img)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
