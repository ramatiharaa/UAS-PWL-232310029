"""
Visualisasi Video dengan ROI dan Kalibrasi
Menampilkan:
1. Video asli dengan ROI polygon
2. Deteksi kendaraan dengan bounding box
3. Kecepatan kendaraan
4. Area transformasi (pixel → meter)

FIX: mendukung path berupa URL/stream (http, https, rtsp, rtmp),
tidak hanya file lokal.
"""

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO
from collections import defaultdict, deque
from typing import Tuple, Optional
import time
import os
import re

# ==================== KONFIGURASI ====================
VIDEO_SOURCES = {
    "cam_01": {
        "path": "video/cctv-1.mp4",
        "roi": np.array([[846, 269], [1086, 271], [1327, 494], [861, 523]], dtype=np.int32),
        "target_width": 5.0,
        "target_height": 12.0,
    },
    "cam_02": {
        "path": "video/cctv-2.mp4",
        "roi": np.array([[443, 187], [875, 211], [809, 558], [10, 423]], dtype=np.int32),
        "target_width": 14.0,
        "target_height": 16.0,
    }
}

CLASS_MAP = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CLASS_COLORS = {
    2: (0, 255, 0),    # car - hijau
    3: (255, 255, 0),  # motorcycle - cyan
    5: (0, 165, 255),  # bus - orange
    7: (0, 0, 255),    # truck - merah
}

# ==================== HELPER: DETEKSI SUMBER URL/STREAM ====================
def is_stream_url(path: str) -> bool:
    """
    Cek apakah path adalah URL/stream (bukan file lokal).
    Mendukung http, https, rtsp, rtmp.
    """
    return bool(re.match(r"^(https?|rtsp|rtmp)://", path.strip(), re.IGNORECASE))

def get_frame_shape(video_path: str, max_retries: int = 5, retry_delay: float = 1.0):
    """
    Dapatkan (height, width) dari video/stream.
    Untuk stream (m3u8/rtsp), CAP_PROP_FRAME_WIDTH/HEIGHT sering bernilai 0
    saat koneksi baru dibuka, sehingga kita baca 1 frame asli sebagai fallback.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return None

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width <= 0 or height <= 0:
        # Fallback: coba baca frame asli (butuh beberapa percobaan untuk stream)
        frame = None
        for attempt in range(max_retries):
            ret, f = cap.read()
            if ret and f is not None:
                frame = f
                break
            time.sleep(retry_delay)
        cap.release()
        if frame is None:
            return None
        height, width = frame.shape[:2]
        return (height, width)

    cap.release()
    return (height, width)

# ==================== VALIDASI ROI (SAMA DENGAN MAIN.PY) ====================
def validate_roi(roi: np.ndarray, frame_shape: Tuple[int, int]) -> bool:
    """
    Validasi koordinat ROI terhadap ukuran frame
    SAMA PERSIS dengan fungsi di main.py
    """
    if len(roi) != 4:
        print(f"❌ ROI harus 4 titik, sekarang {len(roi)}")
        return False
        
    h, w = frame_shape[:2]
    for i, point in enumerate(roi):
        x, y = point
        if x < 0 or x >= w or y < 0 or y >= h:
            print(f"❌ Titik ROI {i}: ({x}, {y}) di luar frame ({w}x{h})")
            return False
    return True

def validate_target_size(target_width: float, target_height: float) -> bool:
    """
    Validasi ukuran target dalam meter
    SAMA PERSIS dengan fungsi di main.py
    """
    if target_width <= 0 or target_height <= 0:
        print(f"❌ Ukuran target tidak valid: {target_width}x{target_height}")
        return False
    return True

# ==================== UTILITY ====================
class ViewTransformer:
    """Transformasi perspektif untuk konversi pixel ke meter"""
    def __init__(self, source: np.ndarray, target: np.ndarray):
        self.matrix = cv2.getPerspectiveTransform(
            source.astype(np.float32), 
            target.astype(np.float32)
        )
        self.inv_matrix = cv2.getPerspectiveTransform(
            target.astype(np.float32),
            source.astype(np.float32)
        )
    
    def transform_points(self, points: np.ndarray) -> np.ndarray:
        if points is None or len(points) == 0:
            return np.array([]).reshape(0, 2)
        transformed = cv2.perspectiveTransform(
            points.reshape(-1, 1, 2).astype(np.float32), 
            self.matrix
        )
        return transformed.reshape(-1, 2)
    
    def inverse_transform(self, points: np.ndarray) -> np.ndarray:
        if points is None or len(points) == 0:
            return np.array([]).reshape(0, 2)
        transformed = cv2.perspectiveTransform(
            points.reshape(-1, 1, 2).astype(np.float32), 
            self.inv_matrix
        )
        return transformed.reshape(-1, 2)

# ==================== VEHICLE TRACKER ====================
class VehicleTracker:
    def __init__(self, fps: float):
        self.fps = fps
        self.trajectories = defaultdict(lambda: deque(maxlen=30))
        self.speeds = defaultdict(lambda: deque(maxlen=10))
        self.classes = {}
        self.last_seen = {}
    
    def update(self, tracker_id: int, position: Tuple[float, float], class_id: int):
        self.trajectories[tracker_id].append(position)
        self.classes[tracker_id] = class_id
        self.last_seen[tracker_id] = time.time()
    
    def get_speed(self, tracker_id: int) -> Optional[float]:
        traj = self.trajectories[tracker_id]
        if len(traj) < 3:
            return None
        
        total_dist = 0.0
        for i in range(1, len(traj)):
            dx = traj[i][0] - traj[i-1][0]
            dy = traj[i][1] - traj[i-1][1]
            total_dist += np.sqrt(dx*dx + dy*dy)
        
        time_elapsed = len(traj) / self.fps
        if time_elapsed == 0:
            return None
        
        speed_kmh = (total_dist / time_elapsed) * 3.6
        self.speeds[tracker_id].append(speed_kmh)
        
        if len(self.speeds[tracker_id]) >= 3:
            return float(np.mean(list(self.speeds[tracker_id])))
        return float(speed_kmh)
    
    def get_vehicle_type(self, tracker_id: int) -> str:
        return CLASS_MAP.get(self.classes.get(tracker_id, -1), "unknown")
    
    def get_position(self, tracker_id: int) -> Optional[Tuple[float, float]]:
        traj = self.trajectories.get(tracker_id)
        if traj and len(traj) > 0:
            return traj[-1]
        return None
    
    def get_trajectory(self, tracker_id: int) -> list:
        return list(self.trajectories.get(tracker_id, []))
    
    def cleanup(self, max_age: float = 5.0):
        now = time.time()
        stale = [tid for tid, last in self.last_seen.items() if now - last > max_age]
        for tid in stale:
            self.trajectories.pop(tid, None)
            self.speeds.pop(tid, None)
            self.classes.pop(tid, None)
            self.last_seen.pop(tid, None)

# ==================== VISUALIZATION ====================
def draw_info_panel(frame: np.ndarray, source_id: str, frame_count: int, 
                    total_vehicles: int, fps: float):
    """Draw information panel on frame"""
    h, w = frame.shape[:2]
    
    # Background panel
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (w//3, 120), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    
    # Text info
    y_pos = 35
    cv2.putText(frame, f"Source: {source_id}", (20, y_pos), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame, f"Frames: {frame_count}", (20, y_pos + 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame, f"Vehicles: {total_vehicles}", (20, y_pos + 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (20, y_pos + 75), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

def draw_roi(frame: np.ndarray, roi: np.ndarray):
    """Draw ROI polygon on frame"""
    cv2.polylines(frame, [roi], True, (0, 255, 255), 2)
    cv2.putText(frame, "ROI", (roi[0][0], roi[0][1] - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

def draw_vehicle(frame: np.ndarray, detections, vehicle_tracker: VehicleTracker,
                 transformer: ViewTransformer):
    """Draw vehicle detections with bounding boxes, speed, and trajectory"""
    
    if len(detections) == 0:
        return
    
    # Get bottom center points
    centers = detections.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)
    if len(centers) == 0:
        return
    
    # Transform to meters for speed calculation
    points_meters = transformer.transform_points(centers)
    
    for idx, (tid, center, point_m, class_id, conf, bbox) in enumerate(zip(
        detections.tracker_id, centers, points_meters, 
        detections.class_id, detections.confidence, detections.xyxy
    )):
        if tid is None:
            continue
        
        # Get color for vehicle type
        color = CLASS_COLORS.get(class_id, (255, 255, 255))
        
        # Update tracker
        pos = (float(point_m[0]), float(point_m[1]))
        vehicle_tracker.update(tid, pos, class_id)
        
        # Calculate speed
        speed = vehicle_tracker.get_speed(tid)
        vehicle_type = vehicle_tracker.get_vehicle_type(tid)
        
        # Draw bounding box
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        
        # Draw center point
        center_point = (int(center[0]), int(center[1]))
        cv2.circle(frame, center_point, 4, color, -1)
        
        # Draw trajectory
        traj = vehicle_tracker.get_trajectory(tid)
        if len(traj) > 1:
            # Convert trajectory points back to pixel coordinates
            traj_pixels = transformer.inverse_transform(np.array(traj))
            for i in range(1, len(traj_pixels)):
                pt1 = (int(traj_pixels[i-1][0]), int(traj_pixels[i-1][1]))
                pt2 = (int(traj_pixels[i][0]), int(traj_pixels[i][1]))
                cv2.line(frame, pt1, pt2, color, 2)
        
        # Draw label with speed and vehicle type
        label = f"{vehicle_type}"
        if speed is not None and 0 < speed < 300:
            label += f" {speed:.1f} km/h"
        else:
            label += " -- km/h"
        
        # Background for text
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(frame, (x1, y1 - text_h - 10), (x1 + text_w, y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

def draw_speed_heatmap(frame: np.ndarray, vehicle_tracker: VehicleTracker,
                       transformer: ViewTransformer):
    """Draw speed heatmap on frame"""
    max_speed = 80.0
    
    speed_data = []
    for tid in vehicle_tracker.trajectories.keys():
        speed = vehicle_tracker.get_speed(tid)
        if speed is not None and 0 < speed < 300:
            pos = vehicle_tracker.get_position(tid)
            if pos:
                speed_data.append((pos, speed))
    
    if not speed_data:
        return
    
    for pos, speed in speed_data:
        pixel_pos = transformer.inverse_transform(np.array([pos]))
        if len(pixel_pos) > 0:
            px, py = int(pixel_pos[0][0]), int(pixel_pos[0][1])
            
            norm_speed = min(speed / max_speed, 1.0)
            
            if norm_speed < 0.5:
                b = 255 - int(norm_speed * 2 * 255)
                g = int(norm_speed * 2 * 255)
                r = 0
            else:
                b = 0
                g = 255 - int((norm_speed - 0.5) * 2 * 255)
                r = int((norm_speed - 0.5) * 2 * 255)
            
            color = (b, g, r)
            cv2.circle(frame, (px, py), 15, color, -1)
            cv2.circle(frame, (px, py), 15, (255, 255, 255), 1)

def draw_calibration_info(frame: np.ndarray, roi: np.ndarray, 
                          target_width: float, target_height: float):
    """Draw calibration information"""
    h, w = frame.shape[:2]
    
    info_text = [
        "CALIBRATION INFO",
        f"ROI Points: {len(roi)}",
        f"Target Width: {target_width}m",
        f"Target Height: {target_height}m",
        "Press 'q' to quit",
        "Press 's' to save screenshot"
    ]
    
    y_pos = h - 150
    for i, text in enumerate(info_text):
        cv2.putText(frame, text, (10, y_pos + i * 25), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

# ==================== MAIN VISUALIZATION ====================
def visualize_video(source_id: str, config: dict, model: YOLO):
    """Visualisasi video dengan semua anotasi"""
    
    video_path = config["path"]
    roi = config["roi"]
    target_width = config["target_width"]
    target_height = config["target_height"]
    
    print(f"\n{'='*60}")
    print(f"Visualizing: {source_id}")
    print(f"Source: {video_path}")
    print(f"ROI Points: {roi}")
    print(f"Target: {target_width}m x {target_height}m")
    print(f"{'='*60}")
    
    # ===== VALIDASI SUMBER (FILE LOKAL ATAU STREAM URL) =====
    is_url = is_stream_url(video_path)

    if not is_url:
        # Hanya cek keberadaan file untuk path lokal
        if not os.path.exists(video_path):
            print(f"❌ Video tidak ditemukan: {video_path}")
            return
    else:
        print(f"ℹ️  Path terdeteksi sebagai stream URL, melewati pengecekan file lokal")

    # Dapatkan ukuran frame untuk validasi (support file & stream)
    frame_shape = get_frame_shape(video_path)
    if frame_shape is None:
        if is_url:
            print(f"❌ Gagal membuka/membaca stream: {video_path}")
            print("   Kemungkinan penyebab:")
            print("   - Build OpenCV tidak mendukung FFMPEG (butuh untuk .m3u8/rtsp)")
            print("   - Stream sedang offline atau URL tidak valid")
            print("   - Koneksi jaringan bermasalah")
        else:
            print(f"❌ Gagal membuka video: {video_path}")
        return

    frame_height, frame_width = frame_shape

    # Validasi ROI (SAMA PERSIS dengan main.py)
    if not validate_roi(roi, frame_shape):
        print(f"❌ ROI tidak valid untuk {source_id}")
        return
    
    if not validate_target_size(target_width, target_height):
        print(f"❌ Ukuran target tidak valid untuk {source_id}")
        return
    
    print(f"✅ ROI valid: {frame_width}x{frame_height}")
    print("="*60)
    print("Controls:")
    print("  'q' - Quit")
    print("  's' - Save screenshot")
    print("  'p' - Pause/Resume")
    print("  'h' - Toggle heatmap")
    print("="*60)
    
    # Setup transformer
    target = np.array([
        [0, 0],
        [target_width, 0],
        [target_width, target_height],
        [0, target_height]
    ])
    transformer = ViewTransformer(source=roi, target=target)
    roi_polygon = sv.PolygonZone(polygon=roi)
    
    # Setup tracker
    tracker = sv.ByteTrack(
        track_activation_threshold=0.2,
        lost_track_buffer=30,
        minimum_matching_threshold=0.8,
        frame_rate=30
    )
    smoother = sv.DetectionsSmoother()
    vehicle_tracker = VehicleTracker(30)
    
    # Open video (file lokal atau stream URL)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Error: Cannot open {video_path}")
        return
    
    # Get FPS
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30
    vehicle_tracker.fps = fps
    
    # Variables
    frame_count = 0
    total_vehicles = 0
    paused = False
    screenshot_count = 0
    show_heatmap = True
    consecutive_read_failures = 0
    max_read_failures = 10  # untuk stream: toleransi reconnect sebelum benar2 berhenti
    
    print(f"\n🎥 Playing: {source_id} (FPS: {fps:.2f})")
    print("Press 'q' to quit\n")
    
    try:
        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    if is_url:
                        # Stream bisa putus sementara -> coba reconnect beberapa kali
                        consecutive_read_failures += 1
                        print(f"⚠️  Gagal membaca frame dari stream ({consecutive_read_failures}/{max_read_failures})")
                        if consecutive_read_failures >= max_read_failures:
                            print(f"❌ Stream terputus: {source_id}")
                            break
                        cap.release()
                        time.sleep(1.0)
                        cap = cv2.VideoCapture(video_path)
                        continue
                    else:
                        print(f"End of video: {source_id}")
                        break
                else:
                    consecutive_read_failures = 0
            else:
                if 'frame' not in locals():
                    continue
                time.sleep(0.1)
            
            frame_count += 1
            
            # YOLO inference (skip every 2 frames for performance)
            if frame_count % 2 == 0:
                results = model(frame, verbose=False)[0]
                detections = sv.Detections.from_ultralytics(results)
                
                # Filter: only target classes
                target_classes = [2, 3, 5, 7]
                detections = detections[np.isin(detections.class_id, target_classes)]
                detections = detections[detections.confidence > 0.3]
                
                # Filter ROI
                detections = detections[roi_polygon.trigger(detections)]
                
                # Tracking
                if len(detections) > 0:
                    detections = tracker.update_with_detections(detections)
                    detections = smoother.update_with_detections(detections)
                    
                    # Update total vehicles count
                    total_vehicles += len(detections)
            
            # ===== DRAW ANNOTATIONS =====
            
            # 1. Draw ROI
            draw_roi(frame, roi)
            
            # 2. Draw vehicles
            if frame_count % 2 == 0:
                draw_vehicle(frame, detections, vehicle_tracker, transformer)
            
            # 3. Draw heatmap (optional)
            if show_heatmap and frame_count % 2 == 0:
                draw_speed_heatmap(frame, vehicle_tracker, transformer)
            
            # 4. Draw info panel
            display_fps = cap.get(cv2.CAP_PROP_FPS) if not paused else 0
            draw_info_panel(frame, source_id, frame_count, total_vehicles, display_fps)
            
            # 5. Draw calibration info
            draw_calibration_info(frame, roi, target_width, target_height)
            
            # 6. Draw legend
            legend_y = 150
            cv2.putText(frame, "LEGEND:", (20, legend_y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            for class_id, (name, color) in enumerate(zip(
                ["Car", "Motorcycle", "Bus", "Truck"],
                [CLASS_COLORS[2], CLASS_COLORS[3], CLASS_COLORS[5], CLASS_COLORS[7]]
            )):
                y_pos = legend_y + 30 + (class_id * 25)
                cv2.rectangle(frame, (20, y_pos - 10), (40, y_pos + 10), color, -1)
                cv2.putText(frame, name, (50, y_pos + 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Cleanup tracker
            if frame_count % 30 == 0:
                vehicle_tracker.cleanup()
            
            # Show frame
            cv2.imshow(f"Traffic Analysis - {source_id}", frame)
            
            # Handle key presses
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                print("Quitting...")
                break
            elif key == ord('s'):
                screenshot_path = f"screenshot_{source_id}_{screenshot_count}.jpg"
                cv2.imwrite(screenshot_path, frame)
                print(f"📸 Screenshot saved: {screenshot_path}")
                screenshot_count += 1
            elif key == ord('p'):
                paused = not paused
                print(f"{'Paused' if paused else 'Resumed'}")
            elif key == ord('h'):
                show_heatmap = not show_heatmap
                print(f"Heatmap: {'ON' if show_heatmap else 'OFF'}")
                
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print(f"\n✅ Done: {source_id}")
        print(f"   Total frames: {frame_count}")
        print(f"   Total vehicles detected: {total_vehicles}")

# ==================== MAIN ====================
def main():
    print("="*60)
    print("TRAFFIC ANALYSIS VISUALIZATION")
    print("Dengan ROI, Kalibrasi, dan Deteksi Kendaraan")
    print("="*60)
    
    # Load model
    print("\nLoading YOLO model...")
    try:
        model = YOLO("yolov8n.pt")
        print("✅ Model loaded successfully\n")
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return
    
    # Pilih source untuk divisualisasi
    print("Available sources:")
    for idx, (source_id, _) in enumerate(VIDEO_SOURCES.items(), 1):
        print(f"  {idx}. {source_id} -> {VIDEO_SOURCES[source_id]['path']}")
    print(f"  {len(VIDEO_SOURCES) + 1}. All sources (sequential)")
    
    try:
        choice = input(f"\nSelect source (1-{len(VIDEO_SOURCES) + 1}): ")
        choice = int(choice)
        
        if choice == len(VIDEO_SOURCES) + 1:
            for source_id, config in VIDEO_SOURCES.items():
                visualize_video(source_id, config, model)
        else:
            source_id = list(VIDEO_SOURCES.keys())[choice - 1]
            visualize_video(source_id, VIDEO_SOURCES[source_id], model)
            
    except (ValueError, IndexError):
        print("Invalid choice, using first source")
        source_id = list(VIDEO_SOURCES.keys())[0]
        visualize_video(source_id, VIDEO_SOURCES[source_id], model)
    
    print("\n" + "="*60)
    print("VISUALIZATION FINISHED")
    print("="*60)

if __name__ == "__main__":
    main()