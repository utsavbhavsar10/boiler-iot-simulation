"""
Chimney Simulator — generates flue gas and draft sensor data.
"""
import paho.mqtt.client as mqtt
import json, time, random, math
from datetime import UTC, datetime
BROKER_HOST = "localhost"
BROKER_PORT = 1883
CLIENT_ID = "chimney_simulator"
TOPICS = {
 "flue_temp": "chimney/flue_temp",
 "co2": "chimney/co2_percentage",
 "o2": "chimney/o2_percentage",
 "co": "chimney/co_ppm",
 "draft": "chimney/draft_pressure",
 "stack_velocity": "chimney/stack_velocity",
 "status": "chimney/status",
 "fault": "system/faults",
}
NORMAL = {
 "flue_temp": {"min": 150, "max": 250, "mean": 200, "unit": "C"},
 "co2": {"min": 8, "max": 14, "mean": 11, "unit": "%"},
 "o2": {"min": 3, "max": 8, "mean": 5, "unit": "%"},
 "co": {"min": 0, "max": 50, "mean": 20, "unit": "ppm"},
 "draft": {"min": -5, "max": -2, "mean": -3.5,"unit": "Pa"},
 "stack_velocity": {"min": 3, "max": 8, "mean": 5, "unit": "m/s"},
}
CHIMNEY_FAULTS = {
 "BLOCKED_FLUE": {"sensor": "draft", "effect": "reduce", "factor": 0.3,
"severity": "CRITICAL"},
 "HIGH_CO": {"sensor": "co", "effect": "spike", "factor": 5.0,
"severity": "CRITICAL"},
 "LOW_DRAFT": {"sensor": "draft", "effect": "reduce", "factor": 0.5,
"severity": "WARNING"},
 "HIGH_FLUE_TEMP": {"sensor": "flue_temp","effect": "spike", "factor": 1.4,
"severity": "WARNING"},
}

class ChimneySimulator:
    def __init__(self):
        self.tick = 0
        self.active_fault = None
        self.fault_duration = 0
        self.state = {k: NORMAL[k]["mean"] for k in NORMAL}

    def update(self):
        self.tick += 1
        for sensor in NORMAL:
            cfg = NORMAL[sensor]
            drift = math.sin(self.tick * 0.04 + 1.5) * (cfg["max"] - cfg["min"]) * 0.05
            noise = random.gauss(0, 1) * cfg["mean"] * 0.015
            self.state[sensor] = round(cfg["mean"] + drift + noise, 2)

        new_fault = None
        if self.active_fault is None and random.random() < 0.04:
            new_fault = random.choice(list(CHIMNEY_FAULTS.keys()))
            self.active_fault = new_fault
            self.fault_duration = random.randint(8, 20)

        if self.active_fault:
            fault = CHIMNEY_FAULTS[self.active_fault]
            sensor = fault["sensor"]
            base = NORMAL[sensor]["mean"]
            if fault["effect"] == "spike":
                self.state[sensor] = round(base * fault["factor"], 2)
            elif fault["effect"] == "reduce":
                self.state[sensor] = round(base * fault["factor"], 2)
            self.fault_duration -= 1
            if self.fault_duration <= 0:
                self.active_fault = None

        return new_fault

    def get_status(self):
        if self.active_fault:
            return CHIMNEY_FAULTS[self.active_fault]["severity"]
        return "NORMAL"


def main():
    sim = ChimneySimulator()
    client = mqtt.Client(client_id=CLIENT_ID)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()
    time.sleep(1)
    print("🏭 Chimney simulator started...")

    while True:
        new_fault = sim.update()
        ts = datetime.now(UTC).isoformat()+ "Z"

        for sensor_name, topic in TOPICS.items():
            if sensor_name in ("status", "fault"):
                continue
            payload = {
                "device_id": "CHIMNEY_001",
                "sensor": sensor_name,
                "value": sim.state.get(sensor_name),
                "unit": NORMAL.get(sensor_name, {}).get("unit", ""),
                "timestamp": ts,
                "status": sim.get_status(),
            }
            client.publish(topic, json.dumps(payload), qos=1)

        if new_fault:
            fault_payload = {
                "device_id": "CHIMNEY_001",
                "fault_code": new_fault,
                "severity": CHIMNEY_FAULTS[new_fault]["severity"],
                "timestamp": ts,
                "message": f"Chimney fault: {new_fault}",
            }
            client.publish(TOPICS["fault"], json.dumps(fault_payload), qos=2)
            print(f"⚠️  CHIMNEY FAULT: {new_fault}")

        time.sleep(0.5)


if __name__ == "__main__":
    main()