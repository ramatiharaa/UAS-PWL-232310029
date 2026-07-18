import cv2

video_path = "video/cctv-1.mp4"
cap = cv2.VideoCapture(video_path)

fps = cap.get(cv2.CAP_PROP_FPS)
print("FPS:", fps)

cap.release()