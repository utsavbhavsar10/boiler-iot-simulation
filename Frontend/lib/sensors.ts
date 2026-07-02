// Mirror of assistant/config.py sensor metadata.

export const SENSOR_UNITS: Record<string, string> = {
  main_steam_flow: "t/h", main_steam_temp_boiler: "°C", main_steam_pressure_boiler: "MPa",
  reheat_steam_temp_boiler: "°C", superheater_desup_flow: "t/h", reheater_desup_flow: "t/h",
  feedwater_temp: "°C", feedwater_flow: "t/h", feedwater_pressure: "MPa",
  flue_gas_temp: "°C", oxygen_level: "%",
  main_steam_temp_turbine: "°C", main_steam_pressure_turbine: "MPa",
  reheat_steam_temp_turbine: "°C", reheat_steam_pressure_turbine: "MPa",
  control_stage_pressure: "MPa", high_exhaust_pressure: "MPa",
  condenser_vacuum: "kPa", circ_water_outlet_temp: "°C",
  flue_temp: "°C", co2: "%", o2: "%", co: "ppm", draft: "Pa", stack_velocity: "m/s",
};

export const SENSOR_NORMAL: Record<string, [number, number]> = {
  main_steam_flow: [800, 1000], main_steam_temp_boiler: [535, 545], main_steam_pressure_boiler: [16.0, 17.5],
  reheat_steam_temp_boiler: [535, 545], superheater_desup_flow: [10, 40], reheater_desup_flow: [0, 15],
  feedwater_temp: [270, 285], feedwater_flow: [800, 1000], feedwater_pressure: [18.0, 20.0],
  flue_gas_temp: [120, 140], oxygen_level: [3, 5],
  main_steam_temp_turbine: [530, 540], main_steam_pressure_turbine: [15.5, 17.0],
  reheat_steam_temp_turbine: [530, 540], reheat_steam_pressure_turbine: [3.0, 4.0],
  control_stage_pressure: [10.0, 13.0], high_exhaust_pressure: [3.0, 4.0],
  condenser_vacuum: [4.0, 7.0], circ_water_outlet_temp: [25, 35],
  flue_temp: [150, 250], co2: [8, 14], o2: [3, 8], co: [0, 50],
  draft: [-5, -2], stack_velocity: [3, 8],
};

export const SENSOR_CRITICAL: Record<string, [number, number]> = {
  main_steam_flow: [700, 1100], main_steam_temp_boiler: [520, 565], main_steam_pressure_boiler: [15.0, 18.5],
  reheat_steam_temp_boiler: [520, 565], superheater_desup_flow: [0, 70], reheater_desup_flow: [0, 35],
  feedwater_temp: [250, 305], feedwater_flow: [700, 1100], feedwater_pressure: [16.0, 22.0],
  flue_gas_temp: [100, 175], oxygen_level: [1.5, 8],
  main_steam_temp_turbine: [515, 560], main_steam_pressure_turbine: [14.5, 18.0],
  reheat_steam_temp_turbine: [515, 560], reheat_steam_pressure_turbine: [2.5, 4.5],
  control_stage_pressure: [8.0, 15.0], high_exhaust_pressure: [2.5, 4.5],
  condenser_vacuum: [2.0, 13.0], circ_water_outlet_temp: [15, 42],
  flue_temp: [100, 300], co2: [5, 18], o2: [1.5, 12], co: [0, 150],
  draft: [-9, -0.5], stack_velocity: [1, 12],
};

export const BOILER_SENSORS = [
  "main_steam_flow", "main_steam_temp_boiler", "main_steam_pressure_boiler",
  "reheat_steam_temp_boiler", "superheater_desup_flow", "reheater_desup_flow",
  "feedwater_temp", "feedwater_flow", "feedwater_pressure",
  "flue_gas_temp", "oxygen_level",
] as const;

export const TURBINE_SENSORS = [
  "main_steam_temp_turbine", "main_steam_pressure_turbine", "reheat_steam_temp_turbine",
  "reheat_steam_pressure_turbine", "control_stage_pressure", "high_exhaust_pressure",
  "condenser_vacuum", "circ_water_outlet_temp",
] as const;

export const CHIMNEY_SENSORS = [
  "flue_temp", "co2", "o2", "co", "draft", "stack_velocity",
] as const;

export type Severity = "good" | "warn" | "crit" | "unknown";

export function classify(name: string, value: number | null | undefined): Severity {
  if (value == null || Number.isNaN(value)) return "unknown";
  const crit = SENSOR_CRITICAL[name];
  const norm = SENSOR_NORMAL[name];
  if (crit && (value < crit[0] || value > crit[1])) return "crit";
  if (norm && (value < norm[0] || value > norm[1])) return "warn";
  return "good";
}

export function prettyName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function pctInRange(name: string, value: number | null | undefined): number {
  if (value == null || Number.isNaN(value)) return 0;
  const crit = SENSOR_CRITICAL[name];
  if (!crit) return 50;
  const [lo, hi] = crit;
  const v = Math.max(lo, Math.min(hi, value));
  return ((v - lo) / (hi - lo)) * 100;
}
