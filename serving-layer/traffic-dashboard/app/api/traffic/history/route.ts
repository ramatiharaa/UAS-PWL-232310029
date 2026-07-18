import { NextResponse } from "next/server";
import { pool } from "@/lib/postgres";

function getLocalDayRange(timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

  const parts = formatter.formatToParts(new Date());
  const year = Number(parts.find((part) => part.type === "year")?.value ?? "0");
  const month = Number(parts.find((part) => part.type === "month")?.value ?? "0");
  const day = Number(parts.find((part) => part.type === "day")?.value ?? "0");

  const startUtc = new Date(Date.UTC(year, month - 1, day) - 7 * 60 * 60 * 1000);
  const endUtc = new Date(startUtc);
  endUtc.setUTCDate(endUtc.getUTCDate() + 1);

  return { startUtc, endUtc };
}

export async function GET() {
  try {
    const client = await pool.connect();

    try {
      const { startUtc, endUtc } = getLocalDayRange("Asia/Jakarta");

      const historyResult = await client.query(
        `
          SELECT
            window_end AS recorded_at,
            SUM(total_vehicles) AS total_vehicles,
            ROUND(COALESCE(AVG(avg_speed_kmh), 0)::numeric, 1) AS avg_speed_kmh
          FROM public.rep_traffic_summary_5min
          WHERE window_end >= $1 AND window_end < $2
          GROUP BY window_end
          ORDER BY window_end ASC
        `,
        [startUtc, endUtc]
      );

      const breakdownResult = await client.query(
        `
          SELECT
            b.window_start,
            b.window_end,
            b.source_id,
            b.vehicle_type,
            b.vehicle_count,
            ROUND(COALESCE(b.avg_speed_kmh, 0)::numeric, 1) AS avg_speed_kmh
          FROM public.rep_traffic_summary_5min_by_type AS b
          WHERE b.window_end >= $1 AND b.window_end < $2
          ORDER BY b.window_end ASC, b.source_id, b.vehicle_type
        `,
        [startUtc, endUtc]
      );

      const points = historyResult.rows.map((row) => ({
        recordedAt: row.recorded_at,
        vehicleCount: Number(row.total_vehicles || 0),
        speedKmh: Number(row.avg_speed_kmh || 0),
        incidentCount: 0,
      }));

      return NextResponse.json({
        success: true,
        data: {
          points,
          byType: breakdownResult.rows.map((row) => ({
            recordedAt: row.window_end,
            windowEnd: row.window_end,
            sourceId: row.source_id,
            vehicleType: row.vehicle_type,
            vehicleCount: Number(row.vehicle_count || 0),
            avgSpeedKmh: Number(row.avg_speed_kmh || 0),
          })),
        },
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Failed to fetch traffic history", error);
    return NextResponse.json(
      {
        success: false,
        message: "Unable to load traffic history from PostgreSQL",
        data: {
          points: [],
          byType: [],
        },
      },
      { status: 500 }
    );
  }
}
