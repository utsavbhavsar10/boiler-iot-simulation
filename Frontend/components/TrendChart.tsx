"use client";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";

interface Series {
  key: string;
  color: string;
  label: string;
  yAxisId?: "left" | "right";
}

const GRID = "#d8c9ad";
const AXIS = "#8a7355";

export function TrendChart({
  data, series, twoAxis,
}: { data: any[]; series: Series[]; twoAxis?: boolean }) {
  return (
    <div className="h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey="t" stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} />
          <YAxis yAxisId="left" stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} />
          {twoAxis && (
            <YAxis yAxisId="right" orientation="right" stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} />
          )}
          <Tooltip
            contentStyle={{
              background: "#f3eada",
              border: "1px solid #cdb994",
              borderRadius: 10,
              fontSize: 12,
              color: "#3b2c1c",
              boxShadow: "0 6px 24px rgba(80,50,20,0.15)",
            }}
            labelStyle={{ color: "#8a7355" }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: "#5a4528" }} />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2.2}
              dot={false}
              isAnimationActive={false}
              yAxisId={s.yAxisId ?? "left"}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
