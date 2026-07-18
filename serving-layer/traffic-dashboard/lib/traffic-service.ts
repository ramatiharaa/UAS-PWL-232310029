export type CameraSnapshot = {
  sourceId: string;
  totalVehicles: number;
  avgSpeed: number;
  maxSpeed: number;
  trafficStatus: string;
  lastUpdate: string | null;
};

export type TrafficSummary = {
  totalVehicles: number;
  avgSpeed: number;
  incidents: number;
  cameras: CameraSnapshot[];
};

export type TrafficHistoryPoint = {
  recordedAt: string;
  vehicleCount: number;
  speedKmh: number;
  incidentCount: number;
};

export type TrafficHistoryBreakdown = {
  recordedAt: string;
  windowEnd?: string | null;
  sourceId: string;
  vehicleType: string;
  vehicleCount: number;
  avgSpeedKmh: number;
};

export type TrafficHistoryPayload = {
  points: TrafficHistoryPoint[];
  byType: TrafficHistoryBreakdown[];
};

export async function fetchTrafficDashboardData() {
  const [summaryResponse, historyResponse] = await Promise.all([
    fetch("/api/traffic"),
    fetch("/api/traffic/history"),
  ]);

  const summaryJson = await summaryResponse.json();
  const historyJson = await historyResponse.json();

  return {
    summary: summaryJson.success
      ? (summaryJson.data as TrafficSummary)
      : ({ totalVehicles: 0, avgSpeed: 0, incidents: 0, cameras: [] } as TrafficSummary),
    history: historyJson.success
      ? ({
          points: (historyJson.data?.points ?? []) as TrafficHistoryPoint[],
          byType: (historyJson.data?.byType ?? []) as TrafficHistoryBreakdown[],
        } as TrafficHistoryPayload)
      : ({ points: [], byType: [] } as TrafficHistoryPayload),
  };
}
