"""
Boiler Simulator - generates realistic boiler sensor data and published via 
MQTT
Simulates normal operation + gradual drift + sudden faults
"""

import paho.mqtt.client as mqtt
import json
import time
import math
import random
from datetime import UTC, datetime

# MQTT Configuration
BROKER_HOST = "localhost"
BROKER_PORT = 1883
CLIENT_ID = "boiler_simulator"

# TOPIC DEFINITION
TOPICS = {
    # Boiler side
 "main_steam_flow": "boiler/main_steam_flow",
 "main_steam_temp_boiler": "boiler/main_steam_temp",
 "main_steam_pressure_boiler": "boiler/main_steam_pressure",
 "reheat_steam_temp_boiler": "boiler/reheat_steam_temp",
 "superheater_desup_flow": "boiler/superheater_desup_water_flow",
 "reheater_desup_flow": "boiler/reheater_desup_water_flow",
 "feedwater_temp": "boiler/feedwater_temp",
 "feedwater_flow": "boiler/feedwater_flow",
 "feedwater_pressure": "boiler/feedwater_pressure",
 "flue_gas_temp": "boiler/flue_gas_temp",
 "oxygen_level": "boiler/oxygen_level",
 
 # Turbine side
 "main_steam_temp_turbine": "turbine/main_steam_temp",
 "main_steam_pressure_turbine": "turbine/main_steam_pressure",
 "reheat_steam_temp_turbine": "turbine/reheat_steam_temp",
 "reheat_steam_pressure_turbine": "turbine/reheat_steam_pressure",
 "control_stage_pressure": "turbine/control_stage_pressure",
 "high_exhaust_pressure": "turbine/high_exhaust_pressure",
 "condenser_vacuum": "turbine/condenser_vacuum",
 "circ_water_outlet_temp": "turbine/circ_water_outlet_temp",

 # Meta
 "status": "boiler/status",
 "fault": "system/faults",
}

# Normal Operating RANGES
# Typical values for a subcritical 300-600 MW utility boiler
NORMAL = {
"main_steam_flow": {"min": 800, "max": 1000, "mean": 900,
"unit": "t/h"},
 "main_steam_temp_boiler": {"min": 535, "max": 545, "mean": 540,
"unit": "C"},
 "main_steam_pressure_boiler": {"min": 16.0, "max": 17.5, "mean": 16.7,
"unit": "MPa"},
 "reheat_steam_temp_boiler": {"min": 535, "max": 545, "mean": 540,
"unit": "C"},
 "superheater_desup_flow": {"min": 10, "max": 40, "mean": 25,
"unit": "t/h"},
 "reheater_desup_flow": {"min": 0, "max": 15, "mean": 5,
"unit": "t/h"},
 "feedwater_temp": {"min": 270, "max": 285, "mean": 278,
"unit": "C"},
 "feedwater_flow": {"min": 800, "max": 1000, "mean": 900,
"unit": "t/h"},
 "feedwater_pressure": {"min": 18.0, "max": 20.0, "mean": 19.0,
"unit": "MPa"},
 "flue_gas_temp": {"min": 120, "max": 140, "mean": 130,
"unit": "C"},
 "oxygen_level": {"min": 3, "max": 5, "mean": 4,
"unit": "%"},
 "main_steam_temp_turbine": {"min": 530, "max": 540, "mean": 535,
"unit": "C"},
 "main_steam_pressure_turbine": {"min": 15.5, "max": 17.0, "mean": 16.2,
"unit": "MPa"},
 "reheat_steam_temp_turbine": {"min": 530, "max": 540, "mean": 535,
"unit": "C"},
 "reheat_steam_pressure_turbine": {"min": 3.0, "max": 4.0, "mean": 3.5,
"unit": "MPa"},
 "control_stage_pressure": {"min": 10.0, "max": 13.0, "mean": 11.5,
"unit": "MPa"},
 "high_exhaust_pressure": {"min": 3.0, "max": 4.0, "mean": 3.5, 
"unit": "MPa"},
    "condenser_vacuum" : {"min": 4.0 , "max": 7.0 , "mean": 5.0,
"unit": "kPa"},
    "circ_water_outlet_temp": {"min": 25, "max": 35, "mean": 30,
"unit": "C"},
}

# FAULT DEFINITIONS
FAULT_TYPES = {
 "HIGH_MAIN_STEAM_PRESSURE": {"sensor": "main_steam_pressure_boiler",
"multiplier": 1.15, "severity": "CRITICAL"},
 "LOW_FEEDWATER_FLOW": {"sensor": "feedwater_flow",
"multiplier": 0.5, "severity": "CRITICAL"},
 "LOW_FEEDWATER_PRESSURE": {"sensor": "feedwater_pressure",
"multiplier": 0.6, "severity": "CRITICAL"},
 "HIGH_FLUE_GAS_TEMP": {"sensor": "flue_gas_temp",
"multiplier": 1.35, "severity": "WARNING"},
 "LOW_OXYGEN": {"sensor": "oxygen_level",
"multiplier": 0.3, "severity": "WARNING"},
 "HIGH_OXYGEN": {"sensor": "oxygen_level",
"multiplier": 2.0, "severity": "WARNING"},
 "HIGH_REHEAT_TEMP": {"sensor": "reheat_steam_temp_boiler",
"multiplier": 1.08, "severity": "WARNING"},
 "CONDENSER_VACUUM_LOSS": {"sensor": "condenser_vacuum",
"multiplier": 3.0, "severity": "CRITICAL"},
 "HIGH_CIRC_WATER_TEMP": {"sensor": "circ_water_outlet_temp",
"multiplier": 1.3, "severity": "WARNING"},
 "EXCESSIVE_DESUP_SPRAY": {"sensor": "superheater_desup_flow",
"multiplier": 2.5, "severity": "WARNING"},
}

class BoilerSimulator:
    def __init__(self):
        #Start every sensor at its mean value
        self.state = {name: cfg["mean"] for name , cfg in NORMAL.items()}
        self.active_fault = None
        self.fault_duration = 0
        self.tick = 0 #Count simulation steps

    def _add_noise(self , value , noise_pct=0.01):
        """Add small random noise to simualate sensor jtter"""
        noise = value * noise_pct * random.gauss(0,1)
        return value + noise

    def _drift_value(self , sensor_name):
        """Make values drift slowly and realistically using sine wave"""
        cfg = NORMAL[sensor_name]
        #Slow oscillation around mean (5% of the sensor's range)
        drift = math.sin(self.tick * 0.05) * (cfg["max"] - cfg["min"]) * 0.05
        return self._add_noise(cfg["mean"] + drift)

    def _inject_fault(self):
        """Randomly decide to start a fault (5% chance per tick)"""
        if self.active_fault is None and random.random() < 0.05:
            fault_name = random.choice(list(FAULT_TYPES.keys()))
            self.active_fault = fault_name
            self.fault_duration = random.randint(10,30)   #lasts 10-30 ticks
            return fault_name
        return None
    
    def update(self):
        """Update all sensor values for this tick"""
        self.tick += 1

        #Normal drift for every sensor in Normal
        for sensor in NORMAL:
            self.state[sensor] = round(self._drift_value(sensor) , 3)

        # Fault Logic   
        new_fault = self._inject_fault()

        if self.active_fault:
            fault = FAULT_TYPES[self.active_fault]
            sensor = fault["sensor"]
            normal_val = NORMAL[sensor]["mean"]
            self.state[sensor] = round(normal_val * fault["multiplier"] , 3)

            self.fault_duration -= 1
            if self.fault_duration <= 0:
                self.active_fault = None  #Fault resolved

        return new_fault # Return fault name if new fault just started
    
    
    def get_status(self):
        """Return overall health status."""
        if self.active_fault:
            fault = FAULT_TYPES[self.active_fault]
            return fault["severity"]
        return "NORMAL"
    
def on_connect(client, userdata , flags , rc):
    if rc == 0:
        print("Boiler Simulator connected to MQTT broker")
    else:
        print(f"connection failed: {rc}")
    
# Main Simulation Loop
def main():
    simulator = BoilerSimulator()
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1, 
        client_id=CLIENT_ID
    )
    client.on_connect = on_connect
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    time.sleep(1) #Wait for connection
    print("Boiler Simulator started. Publishing every 500ms..")
    while True:
        #Update simulation state
        new_fault = simulator.update()

        #Timestampe for all messages this tick
        timestamp = datetime.now(UTC).isoformat()+ "Z"
    
        # Publish each sensor to its own topic
        for sensor_name, topic in TOPICS.items():
            if sensor_name in ("status" , "fault"):
                continue #Handle separately
            value = simulator.state.get(sensor_name)
            
            if value is None:
                continue
            payload = {
                "device_id": "BOILER_001",
                "sensor": sensor_name,
                "value": value,
                "unit": NORMAL.get(sensor_name, {}).get("unit", ""),
                "timestamp": timestamp,
                "status": simulator.get_status(),
            }
            client.publish(topic, json.dumps(payload), qos=1)
        
        # Publish status summary
        status_payload = {
            "device_id": "BOILER_001",
            "overall_status": simulator.get_status(),
            "active_fault": simulator.active_fault,
            "timestamp": timestamp,
        }
        client.publish(TOPICS["status"], json.dumps(status_payload), qos=1)

        # If a new fault just started, publish fault details
        if new_fault:
            fault_payload = {
                "device_id": "BOILER_001",
                "fault_code": new_fault,
                "severity": FAULT_TYPES[new_fault]["severity"],
                "affected_sensor": FAULT_TYPES[new_fault]["sensor"],
                "message": f"Fault detected: {new_fault} on boiler BOILER_001",
                "timestamp": timestamp,
                }
            client.publish(TOPICS["fault"], json.dumps(fault_payload), qos=2) #Use qos=2 for critical fault messages
            print(f"FAULT: {new_fault} - severity :{FAULT_TYPES[new_fault]['severity']}")
        time.sleep(0.5) #Update every 500ms = 2 updates per second

if __name__ == "__main__":
    main()