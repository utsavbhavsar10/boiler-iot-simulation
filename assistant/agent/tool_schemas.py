"""
Defines the function schemas sent to Gemini so it knows
what tools exist, what they do, and what arguments they take.
"""
from vertexai.generative_models import FunctionDeclaration , Tool

# Tool 1
fetch_realtime_sensors_schema = FunctionDeclaration(
    name="fetch_realtime_sensors",
    description=(
        "Fetches the current real-time values of ALL boiler, turbine and chimney "
        "sensors from the last 5 minutes. "
        "Boiler (BOILER_001): main_steam_flow, main_steam_temp_boiler, "
        "main_steam_pressure_boiler, reheat_steam_temp_boiler, "
        "superheater_desup_flow, reheater_desup_flow, feedwater_temp, "
        "feedwater_flow, feedwater_pressure, flue_gas_temp, oxygen_level. "
        "Turbine: main_steam_temp_turbine, main_steam_pressure_turbine, "
        "reheat_steam_temp_turbine, reheat_steam_pressure_turbine, "
        "control_stage_pressure, high_exhaust_pressure, condenser_vacuum, "
        "circ_water_outlet_temp. "
        "Chimney (CHIMNEY_001): flue_temp, co2, o2, co, draft, stack_velocity. "
        "Each reading includes a NORMAL / WARNING / CRITICAL status. "
        "ALWAYS call this tool first when the user asks about current conditions, "
        "safety, or any question that requires knowing present sensor values."
    ),
    parameters={
        "type": "object",
        "properties": {},   #No parameters needed to fetch all sensors
        "required": [],
    },
)
# Tool 2
search_knowledge_base_schema = FunctionDeclaration(
    name="search_knowledge_base",
    description=(
        "Semantic search over the boiler / turbine / chimney engineering "
        "knowledge base (ChromaDB). Returns the top matching documents — "
        "fault guides, multi-sensor diagnostic guides, sensor interpretation "
        "guides, IBR concepts, root causes, action steps and prevention "
        "measures. "
        "Use this tool when the user asks WHY something is happening, HOW to "
        "fix or prevent a fault, WHAT a fault code or sensor means, or any "
        "question whose answer is engineering knowledge rather than a live "
        "sensor reading, a past fault event, or a future trend. Combine with "
        "fetch_realtime_sensors when grounding the explanation in current "
        "data, or with get_fault_history when interpreting a past incident."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query to search the knowledge base for. "
                    "Use the same wording the user used, or a paraphrase that "
                    "captures the engineering intent (e.g. 'why is CO high in "
                    "chimney', 'high pressure plus low water level', "
                    "'how to interpret draft pressure')."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": (
                    "How many top documents to return. Default 3. "
                    "Use 1 for a tightly focused single-doc lookup, "
                    "5 for broader multi-doc context."
                ),
            },
        },
        "required": ["query"],
    },
)

# Tool 3
get_fault_history_schema = FunctionDeclaration(
    name="get_fault_history",
    description=(
        "Retrieves the history of fault events from the boiler and chimney "
        "monitoring system for the last N minutes. "
        "Returns fault code, severity (CRITICAL/WARNING), affected sensor, "
        "timestamp, and fault message for each event. "
        "Use this tool when: the user asks about recent faults, you want to "
        "check if a current out-of-range reading is part of an ongoing fault, "
        "or you need to provide historical context in your answer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "description": (
                    "Number of minutes of fault history to retrieve. "
                    "Use 30 for very recent faults, "
                    "60 for the last hour (default), "
                    "1440 for the last 24 hours."
                ),
            }
        },
        "required": [],
    },
)

# Tool 4
predict_trend_schema = FunctionDeclaration(
    name="predict_trend",
    description=(
        "Analyses the historical trend of a specific sensor over the last "
        "N minutes and predicts whether it will reach a dangerous threshold, "
        "and how many minutes until it does. "
        "Use this tool when: the user asks if something will get worse, "
        "wants to know how long before a fault occurs, or when you notice "
        "a sensor is moving toward its threshold and want to give a "
        "proactive warning. "
        "This tool performs linear trend analysis and time-to-threshold prediction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sensor_name": {
                "type": "string",
                "description": (
                    "Name of the sensor to analyse. "
                    "Boiler: 'main_steam_flow', 'main_steam_temp_boiler', "
                    "'main_steam_pressure_boiler', 'reheat_steam_temp_boiler', "
                    "'superheater_desup_flow', 'reheater_desup_flow', "
                    "'feedwater_temp', 'feedwater_flow', 'feedwater_pressure', "
                    "'flue_gas_temp', 'oxygen_level'. "
                    "Turbine: 'main_steam_temp_turbine', "
                    "'main_steam_pressure_turbine', 'reheat_steam_temp_turbine', "
                    "'reheat_steam_pressure_turbine', 'control_stage_pressure', "
                    "'high_exhaust_pressure', 'condenser_vacuum', "
                    "'circ_water_outlet_temp'. "
                    "Chimney: 'flue_temp', 'co2', 'o2', 'co', 'draft', "
                    "'stack_velocity'."
                ),
            },
            "window_minutes": {
                "type": "integer",
                "description": (
                    "How many minutes of history to use for trend analysis. "
                    "30 minutes is good for detecting recent changes. "
                    "60 minutes is better for slower-changing trends."
                ),
            },
        },
        "required": ["sensor_name"],
    },
)

# ── Bundle all tools ────────────────────────────────────────────────────
# Tool 5 — Phase 4d
get_chronos_forecast_schema = FunctionDeclaration(
    name="get_chronos_forecast",
    description=(
        "Returns a PROBABILISTIC time-series forecast from the Chronos-T5 AI model "
        "for one specific sensor or for ALL sensors at once. "
        "Includes: point forecast values, 10th/90th percentile confidence bands, "
        "minutes-to-warning-threshold, minutes-to-critical-threshold, and anomaly score. "
        "The cache is refreshed every 30 seconds in the background — this tool reads "
        "from the cache instantly with no inference delay. "
        "USE THIS TOOL when: "
        "(1) User asks PREDICTIVE questions implying uncertainty or risk: "
        "'Will there be a fault?', 'How long until overheat?', 'Is anything about to fail?', "
        "'What is the risk in the next 30 minutes?', 'Scan all sensors for upcoming problems'. "
        "(2) You need confidence bands — not just a point estimate. "
        "(3) User asks about anomaly detection: 'Is anything statistically unusual?'. "
        "(4) Multi-sensor risk ranking: use sensor_name='all'. "
        "PREFER predict_trend for simple single-sensor rising/falling direction questions. "
        "PREFER get_chronos_forecast for multi-sensor risk scan or uncertainty questions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sensor_name": {
                "type": "string",
                "description": (
                    "Sensor name to forecast, OR 'all' to scan every sensor at once. "
                    "Boiler: 'main_steam_flow', 'main_steam_temp_boiler', "
                    "'main_steam_pressure_boiler', 'reheat_steam_temp_boiler', "
                    "'superheater_desup_flow', 'reheater_desup_flow', "
                    "'feedwater_temp', 'feedwater_flow', 'feedwater_pressure', "
                    "'flue_gas_temp', 'oxygen_level'. "
                    "Turbine: 'main_steam_temp_turbine', 'main_steam_pressure_turbine', "
                    "'reheat_steam_temp_turbine', 'reheat_steam_pressure_turbine', "
                    "'control_stage_pressure', 'high_exhaust_pressure', "
                    "'condenser_vacuum', 'circ_water_outlet_temp'. "
                    "Chimney: 'flue_temp', 'co2', 'o2', 'co', 'draft', 'stack_velocity'. "
                    "Use 'all' when user asks about the whole system or multi-sensor risk."
                ),
            },
        },
        "required": [],
    },
)

BOILER_AGENT_TOOLS = Tool(
    function_declarations=[
        fetch_realtime_sensors_schema,
        search_knowledge_base_schema,
        get_fault_history_schema,
        predict_trend_schema,
        get_chronos_forecast_schema,   # Phase 4d
    ]
)