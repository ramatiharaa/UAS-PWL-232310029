"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchTrafficDashboardData,
  type CameraSnapshot,
  type TrafficHistoryBreakdown,
  type TrafficHistoryPoint,
  type TrafficSummary,
} from "@/lib/traffic-service";

type VehicleTypeSeries = {
  key: string;
  name: string;
  color: string;
  metric: "count" | "speed";
  data: Array<{ timestamp: string; value: number }>;
};

type VehicleTypeTimelineCamera = {
  label: string;
  data: Array<Record<string, string | number>>;
  series: VehicleTypeSeries[];
  latestByType: Array<{
    vehicleType: string;
    vehicleCount: number;
    avgSpeedKmh: number;
  }>;
};

type VehicleTypeChartCardProps = {
  camera: VehicleTypeTimelineCamera;
};

type AnimatedCameraCardProps = {
  camera: {
    sourceId: string;
    totalVehicles: number;
    avgSpeed: number;
    maxSpeed: number;
    trafficStatus: string;
    lastUpdate: string | null;
    label: string;
    badgeClass: string;
    lastUpdateText: string;
  };
  onClick?: () => void;
};

type RevealOnScrollProps = {
  children: ReactNode;
};

const getCameraLabel = (sourceId: string) => {
  if (sourceId === "cam_01") return "Kamera 1";
  if (sourceId === "cam_02") return "Kamera 2";
  return sourceId;
};

const CAMERA_VIDEO_SOURCES: Record<string, string> = {
  cam_01:
    "https://restreamer3.kotabogor.go.id/memfs/31970416-64db-400c-af8b-b929b673f7a5.m3u8",
  cam_02:
    "https://restreamer3.kotabogor.go.id/memfs/e7d14e54-b9bd-474a-8976-dd08baec4498.m3u8",
};

const getTrafficBadgeClasses = (status: string) => {
  switch (status) {
    case "MACET":
      return "bg-[#3D1D19] text-[#F2897A]";
    case "PADAT":
      return "bg-[#3A2C10] text-[#F0C368]";
    case "MENUNGGU":
      return "bg-[#2A272D] text-[#9C96A0]";
    default:
      return "bg-[#16332A] text-[#58D89A]";
  }
};

type CameraVideoModalProps = {
  sourceId: string;
  label: string;
  onClose: () => void;
};

function CameraVideoModal({ sourceId, label, onClose }: CameraVideoModalProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const src = CAMERA_VIDEO_SOURCES[sourceId];

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;

    setError(null);
    let hlsInstance: any = null;
    const isM3u8 = src.toLowerCase().includes(".m3u8");

    if (isM3u8 && !video.canPlayType("application/vnd.apple.mpegurl")) {
      import("hls.js")
        .then(({ default: Hls }) => {
          if (Hls.isSupported()) {
            hlsInstance = new Hls();
            hlsInstance.loadSource(src);
            hlsInstance.attachMedia(video);
          } else {
            setError("Browser ini tidak mendukung pemutaran stream HLS.");
          }
        })
        .catch(() => {
          setError(
            "Paket hls.js belum terpasang. Jalankan: npm install hls.js",
          );
        });
    } else {
      video.src = src;
    }

    return () => {
      if (hlsInstance) hlsInstance.destroy();
    };
  }, [src]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-2xl border border-[#322F38] bg-[#1E1D22]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#322F38] px-4 py-3">
          <p className="font-semibold text-[#ECE9E3]">{label}</p>
          <button
            type="button"
            onClick={onClose}
            aria-label="Tutup video"
            className="rounded-full p-1.5 text-[#9C96A0] transition hover:bg-[#2A272D] hover:text-[#ECE9E3]"
          >
            ✕
          </button>
        </div>
        <div className="aspect-video bg-black">
          {src ? (
            <video
              ref={videoRef}
              controls
              autoPlay
              muted
              playsInline
              className="h-full w-full"
            />
          ) : (
            <div className="flex h-full items-center justify-center px-4 text-center text-sm text-[#9C96A0]">
              Sumber video untuk {sourceId} belum diatur. Isi
              CAMERA_VIDEO_SOURCES dengan path file atau URL.
            </div>
          )}
        </div>
        {error && (
          <p className="border-t border-[#322F38] px-4 py-2 text-xs text-[#F2897A]">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

function AnimatedCameraCard({ camera, onClick }: AnimatedCameraCardProps) {
  const [isHighlighting, setIsHighlighting] = useState(false);
  const previousRef = useRef(camera);

  useEffect(() => {
    const changed =
      previousRef.current.totalVehicles !== camera.totalVehicles ||
      previousRef.current.avgSpeed !== camera.avgSpeed ||
      previousRef.current.maxSpeed !== camera.maxSpeed ||
      previousRef.current.trafficStatus !== camera.trafficStatus ||
      previousRef.current.lastUpdate !== camera.lastUpdate;

    if (changed) {
      setIsHighlighting(true);
      const timeout = window.setTimeout(() => setIsHighlighting(false), 900);
      previousRef.current = camera;
      return () => window.clearTimeout(timeout);
    }

    previousRef.current = camera;
    return undefined;
  }, [camera]);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onClick?.();
      }}
      className={`cursor-pointer rounded-2xl border p-4 transition-all duration-700 ${
        isHighlighting
          ? "border-[#E8A93D]/60 bg-[#2A2410]"
          : "border-[#322F38] bg-[#1E1D22] hover:border-[#E8A93D]/40"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-[#ECE9E3]">{camera.label}</p>
          <p className="mt-1 text-sm text-[#9C96A0]">
            {camera.sourceId === "cam_01"
              ? "Simpang Ciawi"
              : "Depan Balaikota Bogor"}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium tracking-wide ${camera.badgeClass}`}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {camera.trafficStatus}
        </span>
      </div>
      <dl className="mt-4 space-y-3 text-sm">
        <div className="flex items-center justify-between">
          <dt className="text-[#9C96A0]">Rata-rata kecepatan</dt>
          <dd className="font-medium text-[#ECE9E3]">
            {camera.avgSpeed.toFixed(1)} km/h
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-[#9C96A0]">Total vehicle</dt>
          <dd className="font-medium text-[#ECE9E3]">{camera.totalVehicles}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-[#9C96A0]">Max speed</dt>
          <dd className="font-medium text-[#ECE9E3]">
            {camera.maxSpeed.toFixed(2)} km/h
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-[#9C96A0]">Last update</dt>
          <dd className="text-right font-medium text-[#ECE9E3]">
            {camera.lastUpdateText}
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-[#8B8690]">
        Klik kartu untuk lihat video kamera ▸
      </p>
    </div>
  );
}

function RevealOnScroll({ children }: RevealOnScrollProps) {
  const [isVisible, setIsVisible] = useState(false);
  const elementRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.2 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={elementRef} className="transition-all duration-700">
      {isVisible ? children : <div className="min-h-[18rem]" />}
    </div>
  );
}

function VehicleTypeChartCard({ camera }: VehicleTypeChartCardProps) {
  const [selectedVehicleType, setSelectedVehicleType] = useState("");
  const [selectedPoint, setSelectedPoint] = useState<{
    label: string;
    vehicleCount: number;
    avgSpeedKmh: number;
  } | null>(null);

  useEffect(() => {
    if (camera.latestByType.length === 0) return;

    const exists = camera.latestByType.some(
      (item) => item.vehicleType === selectedVehicleType,
    );
    if (!exists) {
      setSelectedVehicleType(camera.latestByType[0].vehicleType);
    }
  }, [camera.latestByType, selectedVehicleType]);

  const selectedSeries = useMemo(() => {
    if (!selectedVehicleType) return [];
    return camera.series.filter((item) =>
      item.name.startsWith(`${selectedVehicleType} (`),
    );
  }, [camera.series, selectedVehicleType]);

  const selectedDetails = useMemo(() => {
    const countSeries = selectedSeries.find((item) => item.metric === "count");
    const speedSeries = selectedSeries.find((item) => item.metric === "speed");

    return camera.data.map((row) => ({
      label: String(row.label),
      vehicleCount: countSeries ? Number(row[countSeries.key] ?? 0) : 0,
      avgSpeedKmh: speedSeries ? Number(row[speedSeries.key] ?? 0) : 0,
    }));
  }, [camera.data, selectedSeries]);

  const selectedSummary = useMemo(() => {
    if (selectedPoint) return selectedPoint;
    const latest = selectedDetails[selectedDetails.length - 1];
    return latest ?? { label: "", vehicleCount: 0, avgSpeedKmh: 0 };
  }, [selectedDetails, selectedPoint]);

  const selectPointFromRow = (row: Record<string, string | number>) => {
    const countSeries = selectedSeries.find((item) => item.metric === "count");
    const speedSeries = selectedSeries.find((item) => item.metric === "speed");

    setSelectedPoint({
      label: String(row.label ?? row.timestamp ?? ""),
      vehicleCount: countSeries ? Number(row[countSeries.key] ?? 0) : 0,
      avgSpeedKmh: speedSeries ? Number(row[speedSeries.key] ?? 0) : 0,
    });
  };

  const handleChartClick = (event: unknown) => {
    const payload = (
      event as { activePayload?: Array<{ payload?: Record<string, unknown> }> }
    ).activePayload;
    const point = payload?.[0]?.payload;
    if (!point) return;
    selectPointFromRow(point as Record<string, string | number>);
  };

  useEffect(() => {
    if (selectedDetails.length > 0 && !selectedPoint) {
      setSelectedPoint(selectedDetails[selectedDetails.length - 1]);
    }
  }, [selectedDetails, selectedPoint]);

  if (camera.latestByType.length === 0) return null;

  return (
    <RevealOnScroll>
      <div className="rounded-2xl border border-[#322F38] bg-[#1E1D22] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#ECE9E3]">
            {camera.label} — tren jenis kendaraan
          </h3>
          <span className="text-xs text-[#9C96A0]">
            Klik jenis untuk melihat detail
          </span>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          {camera.latestByType.map((item) => {
            const active = selectedVehicleType === item.vehicleType;
            return (
              <button
                key={item.vehicleType}
                type="button"
                onClick={() => setSelectedVehicleType(item.vehicleType)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  active
                    ? "border border-[#58D89A]/30 bg-[#16332A] text-[#58D89A]"
                    : "border border-[#322F38] bg-[#1E1D22] text-[#9C96A0] hover:border-[#E8A93D]/40 hover:text-[#E8A93D]"
                }`}
              >
                {item.vehicleType}
              </button>
            );
          })}
        </div>

        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={camera.data} onClick={handleChartClick}>
              <CartesianGrid stroke="#2E2B31" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fill: "#8B8690", fontSize: 12 }} />
              <YAxis tick={{ fill: "#8B8690", fontSize: 12 }} />
              <YAxis
                yAxisId="speed"
                orientation="right"
                tick={{ fill: "#8B8690", fontSize: 12 }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1E1D22",
                  border: "1px solid #E8A93D",
                  borderRadius: "0.75rem",
                  color: "#ECE9E3",
                }}
                labelStyle={{ color: "#ECE9E3", fontWeight: 600 }}
                itemStyle={{ color: "#ECE9E3" }}
                cursor={{ stroke: "#E8A93D", strokeWidth: 1 }}
              />
              <Legend />
              {selectedSeries.map((seriesItem) => (
                <Line
                  key={seriesItem.key}
                  type="monotone"
                  dataKey={seriesItem.key}
                  stroke={seriesItem.color}
                  strokeWidth={seriesItem.metric === "speed" ? 2 : 2.5}
                  strokeDasharray={
                    seriesItem.metric === "speed" ? "5 5" : undefined
                  }
                  yAxisId={seriesItem.metric === "speed" ? "speed" : undefined}
                  dot={{ r: seriesItem.metric === "speed" ? 2 : 2.5 }}
                  activeDot={{ r: 6 }}
                  name={seriesItem.name}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-3 rounded-xl border border-[#322F38] bg-[#26242B] p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[#ECE9E3]">
              {selectedVehicleType || camera.latestByType[0]?.vehicleType}
            </p>
            <p className="text-sm font-semibold text-[#58D89A]">
              {selectedSummary.vehicleCount} unit
            </p>
          </div>
          <p className="mt-1 text-xs text-[#9C96A0]">
            Interval dipilih: {selectedSummary.label || "-"}
          </p>
          <p className="mt-1 text-xs text-[#9C96A0]">
            Avg speed {selectedSummary.avgSpeedKmh.toFixed(1)} km/h pada
            interval ini
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {camera.data.slice(-24).map((row) => (
              <button
                key={String(row.label)}
                type="button"
                onClick={() => selectPointFromRow(row)}
                className="rounded-full border border-[#322F38] bg-[#1E1D22] px-2.5 py-1 text-[11px] text-[#9C96A0] hover:border-[#E8A93D]/40 hover:text-[#E8A93D]"
              >
                {String(row.label)}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-[#726C77]">
            Klik titik di chart atau pilih interval di bawah untuk melihat
            detail.
          </p>
        </div>
      </div>
    </RevealOnScroll>
  );
}

type AnimatedStatCardProps = {
  label: string;
  value: string | number;
  detail: string;
  tone: string;
};

function AnimatedStatCard({
  label,
  value,
  detail,
  tone,
}: AnimatedStatCardProps) {
  const [isHighlighting, setIsHighlighting] = useState(false);
  const previousRef = useRef({ value: String(value), detail });

  useEffect(() => {
    const changed =
      String(previousRef.current.value) !== String(value) ||
      previousRef.current.detail !== detail;

    if (changed) {
      setIsHighlighting(true);
      const timeout = window.setTimeout(() => setIsHighlighting(false), 900);
      previousRef.current = { value: String(value), detail };
      return () => window.clearTimeout(timeout);
    }

    previousRef.current = { value: String(value), detail };
    return undefined;
  }, [value, detail]);

  return (
    <article
      className={`rounded-2xl border p-5 transition-all duration-700 ${
        isHighlighting
          ? "border-[#E8A93D]/60 bg-[#2A2410]"
          : "border-[#322F38] bg-[#1E1D22]"
      }`}
    >
      <p className="text-sm text-[#9C96A0]">{label}</p>
      <div className="mt-3 flex items-end justify-between">
        <p
          className={`text-3xl font-semibold transition-all duration-700 ${
            isHighlighting ? "text-[#F0C368]" : "text-[#ECE9E3]"
          }`}
        >
          {value}
        </p>
        <span className={`text-sm font-medium ${tone}`}>{detail}</span>
      </div>
    </article>
  );
}

type AnimatedAlertCardProps = {
  title: string;
  time: string;
  severity: string;
};

function AnimatedAlertCard({ title, time, severity }: AnimatedAlertCardProps) {
  const [isHighlighting, setIsHighlighting] = useState(false);
  const previousRef = useRef({ title, time, severity });

  useEffect(() => {
    const changed =
      previousRef.current.title !== title ||
      previousRef.current.time !== time ||
      previousRef.current.severity !== severity;

    if (changed) {
      setIsHighlighting(true);
      const timeout = window.setTimeout(() => setIsHighlighting(false), 900);
      previousRef.current = { title, time, severity };
      return () => window.clearTimeout(timeout);
    }

    previousRef.current = { title, time, severity };
    return undefined;
  }, [title, time, severity]);

  const severityColors = {
    Tinggi: "bg-[#3D1D19] text-[#F2897A]",
    Sedang: "bg-[#3A2C10] text-[#F0C368]",
    Info: "bg-[#16283A] text-[#8EC6F0]",
  };

  return (
    <div
      className={`rounded-2xl border p-4 transition-all duration-700 ${
        isHighlighting
          ? "border-[#E8A93D]/60 bg-[#2A2410]"
          : "border-[#322F38] bg-[#1E1D22]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-[#ECE9E3]">{title}</p>
          <p className="mt-1 text-sm text-[#9C96A0]">{time}</p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium tracking-wide ${
            severityColors[severity as keyof typeof severityColors] ||
            "bg-[#2A272D] text-[#9C96A0]"
          }`}
        >
          {severity}
        </span>
      </div>
    </div>
  );
}

export default function Home() {
  const [summary, setSummary] = useState<TrafficSummary>({
    totalVehicles: 0,
    avgSpeed: 0,
    incidents: 0,
    cameras: [],
  });
  const [historyBreakdown, setHistoryBreakdown] = useState<
    TrafficHistoryBreakdown[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [activeCameraId, setActiveCameraId] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async (isInitial = false) => {
      try {
        if (isInitial) setLoading(true);

        const { summary: summaryData, history: historyData } =
          await fetchTrafficDashboardData();
        setSummary(summaryData);
        setHistoryBreakdown(historyData.byType ?? []);
      } catch (error) {
        console.error("Failed to load traffic dashboard data", error);
      } finally {
        if (isInitial) setLoading(false);
      }
    };

    void loadData(true);
    const interval = window.setInterval(() => {
      void loadData(false);
    }, 4000);

    return () => window.clearInterval(interval);
  }, []);

  const stats = useMemo(
    () => [
      {
        label: "Lalu lintas saat ini",
        value: `${summary.totalVehicles}`,
        detail:
          summary.totalVehicles > 0 ? "kendaraan tercatat" : "Menunggu data",
        tone: "text-[#58D89A]",
      },
      {
        label: "Kepadatan rata-rata",
        value: `${Math.round(summary.avgSpeed)} km/h`,
        detail:
          summary.cameras.length > 0 ? "dari sumber kamera" : "Belum ada data",
        tone: "text-[#8EC6F0]",
      },
      {
        label: "Area bermasalah",
        value: `${summary.incidents}`,
        detail:
          summary.incidents > 0
            ? "kamera dalam status padat/macet"
            : "Semua lancar",
        tone: "text-[#F0C368]",
      },
    ],
    [summary],
  );

  const cameraDetails = useMemo(() => {
    const fallback = [
      {
        sourceId: "cam_01",
        totalVehicles: 0,
        avgSpeed: 0,
        maxSpeed: 0,
        trafficStatus: "MENUNGGU",
        lastUpdate: null,
      },
      {
        sourceId: "cam_02",
        totalVehicles: 0,
        avgSpeed: 0,
        maxSpeed: 0,
        trafficStatus: "MENUNGGU",
        lastUpdate: null,
      },
    ];

    return (summary.cameras.length > 0 ? summary.cameras : fallback)
      .slice(0, 2)
      .map((camera) => ({
        ...camera,
        label: getCameraLabel(camera.sourceId),
        badgeClass: getTrafficBadgeClasses(camera.trafficStatus),
        lastUpdateText: camera.lastUpdate
          ? new Date(camera.lastUpdate).toLocaleString("id-ID", {
              dateStyle: "medium",
              timeStyle: "medium",
            })
          : "Belum ada data",
      }));
  }, [summary.cameras]);

  const alerts = useMemo(() => {
    if (summary.cameras.length === 0) {
      return [
        {
          title: "Belum ada data realtime",
          time: "Menunggu sinkronisasi",
          severity: "Info",
        },
      ];
    }

    return summary.cameras
      .filter((camera) => camera.trafficStatus !== "LANCAR")
      .slice(0, 3)
      .map((camera) => ({
        title: `${camera.sourceId} ${camera.trafficStatus.toLowerCase()}`,
        time: camera.lastUpdate
          ? new Date(camera.lastUpdate).toLocaleTimeString("id-ID", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : "baru saja",
        severity: camera.trafficStatus === "MACET" ? "Tinggi" : "Sedang",
      }));
  }, [summary.cameras]);

  const routeCards = useMemo(() => {
    if (summary.cameras.length === 0) {
      return [
        { name: "Camera-01", load: 72, status: "PADAT" },
        { name: "Camera-02", load: 58, status: "LANCAR" },
      ];
    }

    return summary.cameras.slice(0, 3).map((camera) => ({
      name: camera.sourceId,
      load: Math.min(
        100,
        Math.max(
          25,
          Math.round(100 - camera.avgSpeed * 2 + camera.totalVehicles / 2),
        ),
      ),
      status: camera.trafficStatus,
    }));
  }, [summary.cameras]);

  const cameraHistory = useMemo(() => {
    const cameraOne = historyBreakdown
      .filter((item) => item.sourceId === "cam_01")
      .reduce<Record<string, number>>((acc, item) => {
        acc[item.recordedAt] = (acc[item.recordedAt] ?? 0) + item.vehicleCount;
        return acc;
      }, {});

    const cameraTwo = historyBreakdown
      .filter((item) => item.sourceId === "cam_02")
      .reduce<Record<string, number>>((acc, item) => {
        acc[item.recordedAt] = (acc[item.recordedAt] ?? 0) + item.vehicleCount;
        return acc;
      }, {});

    const labels = Array.from(
      new Set([...Object.keys(cameraOne), ...Object.keys(cameraTwo)]),
    ).sort();

    return labels.map((timestamp) => ({
      label: new Date(timestamp).toLocaleTimeString("id-ID", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
      camera1: cameraOne[timestamp] ?? 0,
      camera2: cameraTwo[timestamp] ?? 0,
    }));
  }, [historyBreakdown]);

  const vehicleTypeTimeline = useMemo(() => {
    const colors = [
      "#7EB6E8",
      "#58D89A",
      "#E8A93D",
      "#E8825A",
      "#B79EE8",
      "#4FC8C0",
    ];

    const buildCameraTimeline = (cameraId: string) => {
      const groupedByType = new Map<
        string,
        Array<{ recordedAt: string; vehicleCount: number; avgSpeedKmh: number }>
      >();

      for (const item of historyBreakdown.filter(
        (entry) => entry.sourceId === cameraId,
      )) {
        const existing = groupedByType.get(item.vehicleType) ?? [];
        existing.push({
          recordedAt: item.recordedAt,
          vehicleCount: item.vehicleCount,
          avgSpeedKmh: item.avgSpeedKmh,
        });
        groupedByType.set(item.vehicleType, existing);
      }

      const timestamps = Array.from(
        new Set(
          historyBreakdown
            .filter((entry) => entry.sourceId === cameraId)
            .map((item) => item.recordedAt),
        ),
      ).sort();

      const series: Array<{
        key: string;
        name: string;
        color: string;
        metric: "count" | "speed";
        data: Array<{ timestamp: string; value: number }>;
      }> = [];

      Array.from(groupedByType.entries()).forEach(
        ([vehicleType, points], index) => {
          const byTime = new Map(
            points.map((point) => [point.recordedAt, point]),
          );
          const color = colors[index % colors.length];

          series.push({
            key: `${cameraId}-${vehicleType}-count`,
            name: `${vehicleType} (count)`,
            color,
            metric: "count",
            data: timestamps.map((timestamp) => ({
              timestamp,
              value: byTime.get(timestamp)?.vehicleCount ?? 0,
            })),
          });

          series.push({
            key: `${cameraId}-${vehicleType}-speed`,
            name: `${vehicleType} (avg speed)`,
            color,
            metric: "speed",
            data: timestamps.map((timestamp) => ({
              timestamp,
              value: byTime.get(timestamp)?.avgSpeedKmh ?? 0,
            })),
          });
        },
      );

      const latestByType = Array.from(groupedByType.entries())
        .map(([vehicleType, points]) => {
          const latestPoint = points[points.length - 1];
          return {
            vehicleType,
            vehicleCount: latestPoint?.vehicleCount ?? 0,
            avgSpeedKmh: latestPoint?.avgSpeedKmh ?? 0,
          };
        })
        .sort((a, b) => b.vehicleCount - a.vehicleCount);

      return {
        label: cameraId === "cam_01" ? "Kamera 1" : "Kamera 2",
        data: timestamps.map((timestamp) => {
          const row: Record<string, string | number> = {
            label: new Date(timestamp).toLocaleTimeString("id-ID", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }),
          };

          series.forEach((item) => {
            const point = item.data.find(
              (entry) => entry.timestamp === timestamp,
            );
            row[item.key] = point?.value ?? 0;
          });

          return row;
        }),
        series,
        latestByType,
      };
    };

    return {
      camera1: buildCameraTimeline("cam_01"),
      camera2: buildCameraTimeline("cam_02"),
    };
  }, [historyBreakdown]);

  return (
    <main className="min-h-screen bg-[#15141A] px-4 py-6 text-[#ECE9E3] sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 rounded-3xl border border-[#322F38] bg-[#1E1D22] p-6 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="mb-2 text-sm font-medium uppercase tracking-[0.3em] text-[#E8A93D]">
              Traffic Intelligence
            </p>
            <h1 className="text-3xl font-semibold sm:text-4xl">
              Dashboard analitik lalu lintas
            </h1>
          </div>
        </header>

        <section className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
          <article className="rounded-3xl border border-[#322F38] bg-[#1E1D22] p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold">Detail sumber kamera</h2>
                <p className="text-sm text-[#9C96A0]">
                  Informasi tiap kamera: kecepatan, volume, status, dan update
                  terakhir
                </p>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {cameraDetails.map((camera) => (
                <AnimatedCameraCard
                  key={camera.sourceId}
                  camera={camera}
                  onClick={() => setActiveCameraId(camera.sourceId)}
                />
              ))}
            </div>
          </article>

          <article className="rounded-3xl border border-[#322F38] bg-[#1E1D22] p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold">Alert hotspot</h2>
                <p className="text-sm text-[#9C96A0]">
                  Area yang memerlukan perhatian
                </p>
              </div>
            </div>
            <div className="space-y-3">
              {alerts.map((alert, index) => (
                <AnimatedAlertCard
                  key={`${alert.title}-${index}`}
                  title={alert.title}
                  time={alert.time}
                  severity={alert.severity}
                />
              ))}
            </div>
          </article>
        </section>

        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.3em] text-[#E8A93D]">
                History
              </p>
              <h2 className="text-xl font-semibold">
                Tren dan perbandingan data historis
              </h2>
            </div>
          </div>
          <div className="space-y-6">
            <RevealOnScroll>
              <article className="rounded-3xl border border-[#322F38] bg-[#1E1D22] p-6">
                <div className="mb-5 flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-semibold">
                      History per kamera
                    </h2>
                    <p className="text-sm text-[#9C96A0]">
                      Perbandingan volume kamera 1 dan 2
                    </p>
                  </div>
                </div>
                <div className="h-72 rounded-2xl border border-[#322F38] bg-[#26242B] p-4">
                  {loading && historyBreakdown.length === 0 ? (
                    <p className="text-sm text-[#9C96A0]">
                      Memuat data history kamera...
                    </p>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={cameraHistory}>
                        <CartesianGrid stroke="#2E2B31" strokeDasharray="3 3" />
                        <XAxis
                          dataKey="label"
                          tick={{ fill: "#8B8690", fontSize: 12 }}
                        />
                        <YAxis tick={{ fill: "#8B8690", fontSize: 12 }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "#1E1D22",
                            border: "1px solid #E8A93D",
                            borderRadius: "0.75rem",
                            color: "#ECE9E3",
                          }}
                          labelStyle={{ color: "#ECE9E3", fontWeight: 600 }}
                          itemStyle={{ color: "#ECE9E3" }}
                        />
                        <Legend />
                        <Line
                          type="monotone"
                          dataKey="camera1"
                          stroke="#58D89A"
                          strokeWidth={2.5}
                          dot={{ r: 3 }}
                          name="Kamera 1"
                        />
                        <Line
                          type="monotone"
                          dataKey="camera2"
                          stroke="#E8825A"
                          strokeWidth={2.5}
                          dot={{ r: 3 }}
                          name="Kamera 2"
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </article>
            </RevealOnScroll>

            <article className="rounded-3xl border border-[#322F38] bg-[#1E1D22] p-6">
              <div className="mt-6 space-y-4">
                {[vehicleTypeTimeline.camera1, vehicleTypeTimeline.camera2].map(
                  (camera) => (
                    <VehicleTypeChartCard key={camera.label} camera={camera} />
                  ),
                )}
              </div>
            </article>
          </div>
        </section>
      </div>

      {activeCameraId && (
        <CameraVideoModal
          sourceId={activeCameraId}
          label={getCameraLabel(activeCameraId)}
          onClose={() => setActiveCameraId(null)}
        />
      )}
    </main>
  );
}
