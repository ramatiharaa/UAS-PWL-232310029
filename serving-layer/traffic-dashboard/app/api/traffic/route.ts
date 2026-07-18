import { NextResponse } from "next/server";
import { pool } from "@/lib/postgres";

type CameraSnapshot = {
  sourceId: string;
  totalVehicles: number;
  avgSpeed: number;
  maxSpeed: number;
  trafficStatus: string;
  lastUpdate: string | null;
};

export async function GET() {
  try {
    const client = await pool.connect();

    try {
      const result = await client.query(`
        SELECT
          source_id,
          total_count AS total_vehicles,
          avg_speed,
          max_speed,
          traffic_status,
          updated_at AS last_update
        FROM public.traffic_real_time_aggregated
        ORDER BY source_id
      `);

      const cameras: CameraSnapshot[] = result.rows.map((row) => ({
        sourceId: row.source_id,
        totalVehicles: Number(row.total_vehicles || 0),
        avgSpeed: Number(row.avg_speed || 0),
        maxSpeed: Number(row.max_speed || 0),
        trafficStatus: row.traffic_status || "LANCAR",
        lastUpdate: row.last_update ? new Date(row.last_update).toISOString() : null,
      }));

      const totalVehicles = cameras.reduce((sum, camera) => sum + camera.totalVehicles, 0);
      const avgSpeed =
        cameras.length > 0
          ? cameras.reduce((sum, camera) => sum + camera.avgSpeed, 0) / cameras.length
          : 0;
      const incidents = cameras.filter((camera) => camera.trafficStatus !== "LANCAR").length;

      return NextResponse.json({
        success: true,
        data: {
          totalVehicles,
          avgSpeed: Number(avgSpeed.toFixed(1)),
          incidents,
          cameras,
        },
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Failed to fetch traffic data", error);
    return NextResponse.json(
      {
        success: false,
        message: "Unable to load traffic data from PostgreSQL",
        data: {
          totalVehicles: 0,
          avgSpeed: 0,
          incidents: 0,
          cameras: [],
        },
      },
      { status: 500 }
    );
  }
}
