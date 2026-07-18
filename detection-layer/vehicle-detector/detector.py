import cv2
import json
import signal
import sys
import math
import time
import threading
import numpy as np
import supervision as sv
from collections import defaultdict, deque
from datetime import datetime
from ultralytics import YOLO
from confluent_kafka import Producer

CAMERAS_CONFIG = [
    {
        "source_id": "cam_01",
        "video_path": "https://restreamer3.kotabogor.go.id/memfs/31970416-64db-400c-af8b-b929b673f7a5.m3u8",
        "roi_coordinates": np.array([[844, 267], [1106, 272], [1361, 521], [857, 538]], dtype=np.int32),
        "target_width": 6,
        "target_height": 20
    },
    {
        "source_id": "cam_02",
        "video_path": "https://restreamer3.kotabogor.go.id/memfs/e7d14e54-b9bd-474a-8976-dd08baec4498.m3u8",
        "roi_coordinates": np.array([[443, 187], [875, 211], [809, 558], [10, 423]], dtype=np.int32),
        "target_width": 14,
        "target_height": 20
    }

    # {
    #     "source_id": "cam_01",
    #     "video_path": "video/cctv-1.mp4",
    #     "roi_coordinates": np.array([[844, 267], [1106, 272], [1361, 521], [857, 538]], dtype=np.int32),
    #     "target_width": 6,
    #     "target_height": 20
    # },
    # {
    #     "source_id": "cam_02",
    #     "video_path": "video/cctv-2.mp4",
    #     "roi_coordinates": np.array([[443, 187], [875, 211], [809, 558], [10, 423]], dtype=np.int32),
    #     "target_width": 14,
    #     "target_height": 20
    # }
]

CLASS_MAP = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
TARGET_CLASSES = list(CLASS_MAP.keys())
OUTPUT_JSONL = "vehicle_speed_data.jsonl"

DEFAULT_FPS = 25.0
CONNECT_RETRIES = 5 
CONNECT_RETRY_DELAY = 3
MAX_CONSECUTIVE_READ_FAILS = 30
READ_FAIL_SLEEP = 0.5

KAFKA_BATCH_SIZE = 50
conf = {
    'bootstrap.servers': 'localhost:9092',
    'client.id': 'python-producer',
    'linger.ms': 5,
    'batch.size': 16384
}
producer = Producer(conf)
KAFKA_TOPIC = 'traffic-data-topic'

class ViewTransformer:
    def __init__(self, source: np.ndarray, target: np.ndarray) -> None:
        self.m = cv2.getPerspectiveTransform(
            source.astype(np.float32), target.astype(np.float32)
        )

    def transform_points(self, points: np.ndarray) -> np.ndarray:
        if points.size == 0:
            return np.array([]).reshape(0, 2)
        transformed = cv2.perspectiveTransform(
            points.reshape(-1, 1, 2).astype(np.float32), self.m
        )
        return transformed.reshape(-1, 2)


class RobustVideoCapture:
    def __init__(self, video_path: str, source_id: str):
        self.video_path = video_path
        self.source_id = source_id
        self.cap = None
        self.fps = DEFAULT_FPS
        self._open_with_retry(initial=True)

    def _open_with_retry(self, initial: bool = False) -> bool:
        for attempt in range(1, CONNECT_RETRIES + 1):
            if not is_running:
                return False
            print(f"[{self.source_id}] {'Membuka' if initial else 'Reconnect'} stream "
                  f"(percobaan {attempt}/{CONNECT_RETRIES})...")
            cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                self.fps = fps if fps and 1 <= fps <= 60 else DEFAULT_FPS
                self.cap = cap
                print(f"[{self.source_id}] Stream terbuka. FPS terdeteksi: {self.fps}")
                return True

            cap.release()
            time.sleep(CONNECT_RETRY_DELAY)

        print(f"[{self.source_id}] Gagal membuka stream setelah {CONNECT_RETRIES} percobaan.")
        return False

    def read(self):
        if self.cap is None:
            return None

        consecutive_fails = 0
        while is_running:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame

            consecutive_fails += 1
            if consecutive_fails >= MAX_CONSECUTIVE_READ_FAILS:
                print(f"[{self.source_id}] {consecutive_fails} gagal baca beruntun. Mencoba reconnect...")
                self.cap.release()
                if not self._open_with_retry(initial=False):
                    return None
                consecutive_fails = 0
            else:
                time.sleep(READ_FAIL_SLEEP)

        return None

    def release(self):
        if self.cap is not None:
            self.cap.release()


outfile = open(OUTPUT_JSONL, "w", encoding="utf-8")
file_lock = threading.Lock()
total_written = 0
PROCESS_START = datetime.now()
is_running = True


def write_record(record: dict) -> None:
    global total_written
    with file_lock:
        outfile.write(json.dumps(record, ensure_ascii=False) + "\n")
        outfile.flush()
        total_written += 1


def shutdown(reason: str = "") -> None:
    global is_running
    if not is_running:
        return
    is_running = False

    print("\n[INFO] Menunggu sisa pesan Kafka terkirim...")
    producer.flush(timeout=5)

    outfile.close()
    cv2.destroyAllWindows()
    process_end = datetime.now()
    duration = process_end - PROCESS_START

    msg = f"\nSistem Dihentikan{' (' + reason + ')' if reason else ''}.\n"
    msg += f"{total_written} record tersimpan di '{OUTPUT_JSONL}'\n"
    msg += f"Start: {PROCESS_START.strftime('%Y-%m-%d %H:%M:%S')}\n"
    msg += f"End:   {process_end.strftime('%Y-%m-%d %H:%M:%S')}\n"
    msg += f"Durasi : {duration}"
    print(msg)


def handle_sigint(sig, frame):
    shutdown("Ctrl+C ditekan")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_sigint)


def process_camera(config):
    source_id = config["source_id"]
    video_path = config["video_path"]
    roi_coords = config["roi_coordinates"]
    tw, th = config["target_width"], config["target_height"]

    target_coords = np.array([[0, 0], [tw - 1, 0], [tw - 1, th - 1], [0, th - 1]])

    kafka_buffer = []

    print(f"[START] Memulai stream untuk {source_id} -> {video_path}")
    model = YOLO("yolov8n.pt")

    capture = RobustVideoCapture(video_path, source_id)
    if capture.cap is None:
        print(f"[ERROR] {source_id}: tidak bisa memulai, worker dihentikan.")
        return

    fps = capture.fps

    tracker = sv.ByteTrack()
    smoother = sv.DetectionsSmoother()
    polygon_zone = sv.PolygonZone(polygon=roi_coords)
    view_transformer = ViewTransformer(source=roi_coords, target=target_coords)

    coordinates = defaultdict(lambda: deque(maxlen=max(int(fps), 1)))
    tracker_class = {}

    frame_idx = 0
    while is_running:
        frame = capture.read()
        if frame is None:
            print(f"[ERROR] {source_id}: stream tidak bisa dipulihkan, worker berhenti.")
            break

        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        results = model(frame, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(results)

        detections = detections[np.isin(detections.class_id, TARGET_CLASSES)]
        detections = detections[detections.confidence > 0.5]

        roi_mask = polygon_zone.trigger(detections)
        detections = detections[roi_mask]

        detections = tracker.update_with_detections(detections)
        detections = detections.with_nms(threshold=0.7)
        detections = smoother.update_with_detections(detections)

        center_points = detections.get_anchors_coordinates(anchor=sv.Position.CENTER)
        if len(center_points) > 0:
            points = view_transformer.transform_points(points=center_points)
            tracker_ids_list = list(detections.tracker_id)
            for tracker_id, (x, y) in zip(detections.tracker_id, points):
                coordinates[tracker_id].append((x, y))
                if tracker_id not in tracker_class:
                    idx = tracker_ids_list.index(tracker_id)
                    tracker_class[tracker_id] = int(detections.class_id[idx])

        for tracker_id, confidence in zip(detections.tracker_id, detections.confidence):
            trajectory = coordinates[tracker_id]
            if len(trajectory) < 2:
                continue

            x_end, y_end = trajectory[-1]
            x_start, y_start = trajectory[0]

            distance = math.hypot(x_end - x_start, y_end - y_start)
            time_span = len(trajectory) / fps
            if time_span <= 0:
                continue
            speed_kmh = (distance / time_span) * 3.6

            class_id = tracker_class.get(tracker_id, -1)
            class_name = CLASS_MAP.get(class_id, "unknown")

            record = {
                "source_id": source_id,
                "tracker_id": int(tracker_id),
                "vehicle_type": class_name,
                "speed_kmh": round(speed_kmh, 2),
                "confidence": round(float(confidence), 4),
                "timestamp": timestamp,
                "processing_time": now.isoformat(),
                "frame": frame_idx,
                "position_meters": {
                    "x": round(float(x_end), 2),
                    "y": round(float(y_end), 2)
                },
                "trajectory_length": len(trajectory)
            }

            write_record(record)
            kafka_buffer.append(record)

            if len(kafka_buffer) >= KAFKA_BATCH_SIZE:
                for msg in kafka_buffer:
                    producer.produce(KAFKA_TOPIC, value=json.dumps(msg, ensure_ascii=False))
                producer.poll(0)
                kafka_buffer.clear()

        frame_idx += 1

    if kafka_buffer:
        for msg in kafka_buffer:
            producer.produce(KAFKA_TOPIC, value=json.dumps(msg, ensure_ascii=False))
        producer.poll(0)
        kafka_buffer.clear()

    capture.release()
    print(f"[DONE] Proses stream {source_id} selesai.")


if __name__ == "__main__":
    print(f"Output File: {OUTPUT_JSONL}")
    print(f"Kafka Topic: {KAFKA_TOPIC} (Dikirim per batch: {KAFKA_BATCH_SIZE} data)")
    print("Mulai memproses semua kamera (Tekan Ctrl+C untuk berhenti)\n")

    threads = []

    for cam_cfg in CAMERAS_CONFIG:
        t = threading.Thread(target=process_camera, args=(cam_cfg,))
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown("semua video selesai atau dihentikan manual")