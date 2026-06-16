"""All configuration for the Boiler Agentic RAG system.
Every other file imports from here.
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Force stdout/stderr to UTF-8 on Windows so emoji prints (✅ 🚨 ⚠️ …)
# don't crash with UnicodeEncodeError under the cp1252 default console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Vertex AI(Fine-Tuned model Gemini 2.5- flash)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_REGION = os.getenv("GCP_REGION")

# Fine-tuned model endpoint 
FINE_TUNED_MODEL_ENDPOINT = os.getenv("TUNED_MODEL_ENDPOINT_v4")

#Model generation settings
GEMINI_TEMPERATURE=0.1  #low = factual ans , not creative
GEMINI_MAX_TOKENS=8192  # thinking tokens + full structured answer need room
GEMINI_TOP_P=0.8
GEMINI_THINKING_BUDGET=2048  # cap reasoning so the written answer always has room

#Agent Settings
MAX_AGENT_STEPS=6   #max tool calls 

# ── InfluxDB ───────────────────────────────────────────────────────────
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "my-super-secret-token-123")
INFLUX_ORG = os.getenv("INFLUX_ORG", "boiler_org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "boiler_data")

#CHROMADB Settings
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = "boiler-knowledge"
TOP_K_DOCS = 3  #how many docs to retrieve per query

#Embedding model for chromaDB (OpenAI)
EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI embedding model, fast and cost-effective

#Sensor metadata
SENSOR_UNITS = {
    "main_stream_flow" : "t/h",
    "main_steam_temp_boiler": "°C",
    "main_steam_pressure_boiler": "MPa",
    "reheat_steam_temp_boiler": "°C",
    "superheater_desup_flow": "t/h",
    "reheater_desup_flow": "t/h",
    "feedwater_temp": "°C",
    "feedwater_flow": "t/h",
    "feedwater_pressure": "MPa",
    "flue_gas_temp": "°C",
    "oxygen_level": "%",

    # Turbine side (device_id: BOILER_001, MQTT prefix: turbine/)
    "main_steam_temp_turbine": "°C",
    "main_steam_pressure_turbine": "MPa",
    "reheat_steam_temp_turbine": "°C",
    "reheat_steam_pressure_turbine": "MPa",
    "control_stage_pressure": "MPa",
    "high_exhaust_pressure": "MPa",
    "condenser_vacuum": "kPa",
    "circ_water_outlet_temp": "°C",


    # Chimney side (device_id: CHIMNEY_001, MQTT prefix: chimney/)
    "flue_temp": "°C",
    "co2": "%",
    "o2": "%",
    "co": "ppm",
    "draft": "Pa",
    "stack_velocity": "m/s"
}


# (low, high) = normal operating band. Outside this band but inside the
# critical band = WARNING. Outside the critical band = CRITICAL.
# Values lifted directly from the simulators' NORMAL dict.
SENSOR_NORMAL_RANGE = {
     # Boiler
    "main_steam_flow":              (800,   1000),
    "main_steam_temp_boiler":       (535,   545),
    "main_steam_pressure_boiler":   (16.0,  17.5),
    "reheat_steam_temp_boiler":     (535,   545),
    "superheater_desup_flow":       (10,    40),
    "reheater_desup_flow":          (0,     15),
    "feedwater_temp":               (270,   285),
    "feedwater_flow":               (800,   1000),
    "feedwater_pressure":           (18.0,  20.0),
    "flue_gas_temp":                (120,   140),
    "oxygen_level":                 (3,     5),

    # Turbine
    "main_steam_temp_turbine":      (530,   540),
    "main_steam_pressure_turbine":  (15.5,  17.0),
    "reheat_steam_temp_turbine":    (530,   540),
    "reheat_steam_pressure_turbine":(3.0,   4.0),
    "control_stage_pressure":       (10.0,  13.0),
    "high_exhaust_pressure":        (3.0,   4.0),
    "condenser_vacuum":             (4.0,   7.0),
    "circ_water_outlet_temp":       (25,    35),

    # Chimney  (note: draft is negative — closer to 0 = worse)
    "flue_temp":                    (150,   250),
    "co2":                          (8,     14),
    "o2":                           (3,     8),
    "co":                           (0,     50),
    "draft":                        (-5,    -2),
    "stack_velocity":               (3,     8),

}

# Critical alarm bands (outside these = CRITICAL severity).
# Mirrors crit_low/crit_high from the simulators so the agent can
# distinguish CRITICAL from WARNING.
SENSOR_CRITICAL_RANGE = {
    "main_steam_flow":              (700,   1100),
    "main_steam_temp_boiler":       (520,   565),
    "main_steam_pressure_boiler":   (15.0,  18.5),
    "reheat_steam_temp_boiler":     (520,   565),
    "superheater_desup_flow":       (0,     70),
    "reheater_desup_flow":          (0,     35),
    "feedwater_temp":               (250,   305),
    "feedwater_flow":               (700,   1100),
    "feedwater_pressure":           (16.0,  22.0),
    "flue_gas_temp":                (100,   175),
    "oxygen_level":                 (1.5,   8),
    "main_steam_temp_turbine":      (515,   560),
    "main_steam_pressure_turbine":  (14.5,  18.0),
    "reheat_steam_temp_turbine":    (515,   560),
    "reheat_steam_pressure_turbine":(2.5,   4.5),
    "control_stage_pressure":       (8.0,   15.0),
    "high_exhaust_pressure":        (2.5,   4.5),
    "condenser_vacuum":             (2.0,   13.0),
    "circ_water_outlet_temp":       (15,    42),
    "flue_temp":                    (100,   300),
    "co2":                          (5,     18),
    "o2":                           (1.5,   12),
    "co":                           (0,     150),
    "draft":                        (-9,    -0.5),
    "stack_velocity":               (1,     12),
}

# Logical grouping used by the tools. `device` matches the device_id
# sent in the MQTT payload. `measurement` is the InfluxDB measurement
# that the consumer writes these sensors into.
SENSOR_MEASUREMENTS = {
    "boiler_sensors": {
        "device": "BOILER_001",
        "measurement": "boiler_sensors",
        "sensors": [
            "main_steam_flow",
            "main_steam_temp_boiler",
            "main_steam_pressure_boiler",
            "reheat_steam_temp_boiler",
            "superheater_desup_flow",
            "reheater_desup_flow",
            "feedwater_temp",
            "feedwater_flow",
            "feedwater_pressure",
            "flue_gas_temp",
            "oxygen_level",
        ],
    },
    "turbine_sensors": {
        "device": "BOILER_001",
        "measurement": "turbine_sensors",
        "sensors": [
            "main_steam_temp_turbine",
            "main_steam_pressure_turbine",
            "reheat_steam_temp_turbine",
            "reheat_steam_pressure_turbine",
            "control_stage_pressure",
            "high_exhaust_pressure",
            "condenser_vacuum",
            "circ_water_outlet_temp",
        ],
    },
    "chimney_sensors": {
        "device": "CHIMNEY_001",
        "measurement": "chimney_sensors",
        "sensors": [
            "flue_temp",
            "co2",
            "o2",
            "co",
            "draft",
            "stack_velocity",
        ],
    },
}

# Fault codes raised by the simulators (publisher/simulators/*).
# Keep this in sync with FAULT_TYPES (boiler_simulator.py) and
# CHIMNEY_FAULTS (chimney_simulator.py).
FAULT_CATALOG = {
    # Boiler / turbine
    "HIGH_MAIN_STEAM_PRESSURE": {"sensor": "main_steam_pressure_boiler", "severity": "CRITICAL"},
    "LOW_FEEDWATER_FLOW":       {"sensor": "feedwater_flow",             "severity": "CRITICAL"},
    "LOW_FEEDWATER_PRESSURE":   {"sensor": "feedwater_pressure",         "severity": "CRITICAL"},
    "HIGH_FLUE_GAS_TEMP":       {"sensor": "flue_gas_temp",              "severity": "WARNING"},
    "LOW_OXYGEN":               {"sensor": "oxygen_level",               "severity": "WARNING"},
    "HIGH_OXYGEN":              {"sensor": "oxygen_level",               "severity": "WARNING"},
    "HIGH_REHEAT_TEMP":         {"sensor": "reheat_steam_temp_boiler",   "severity": "WARNING"},
    "CONDENSER_VACUUM_LOSS":    {"sensor": "condenser_vacuum",           "severity": "CRITICAL"},
    "HIGH_CIRC_WATER_TEMP":     {"sensor": "circ_water_outlet_temp",     "severity": "WARNING"},
    "EXCESSIVE_DESUP_SPRAY":    {"sensor": "superheater_desup_flow",     "severity": "WARNING"},
    # Chimney
    "BLOCKED_FLUE":             {"sensor": "draft",     "severity": "CRITICAL"},
    "HIGH_CO":                  {"sensor": "co",        "severity": "CRITICAL"},
    "LOW_DRAFT":                {"sensor": "draft",     "severity": "WARNING"},
    "HIGH_FLUE_TEMP":           {"sensor": "flue_temp", "severity": "WARNING"},
}