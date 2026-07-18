import cv2

# Ganti dengan nama file video kamu
video_path = "video/cctv-2.mp4" 

def click_event(event, x, y, flags, params):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"Koordinat: [{x}, {y}]")
        # Menggambar titik merah di lokasi yang diklik
        cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
        cv2.imshow("Cari ROI (Klik 4 Titik)", img)

cap = cv2.readFrame = cv2.VideoCapture(video_path)
success, img = cap.read()

if success:
    cv2.imshow("Cari ROI (Klik 4 Titik)", img)
    cv2.setMouseCallback("Cari ROI (Klik 4 Titik)", click_event)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("Video tidak bisa dibuka.")
cap.release()