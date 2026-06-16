"""InfluxDB consumer - subscribes to all MQTT topics and writes
   every sensor reading into InfluxDB as a time-series data point.
   producer-consumer architecture
"""
import paho.mqtt.client as mqtt
import json
from datetime import UTC, datetime
from influxdb_client import InfluxDBClient, Point , WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

#Config
MQTT_HOST = "localhost"
MQTT_PORT = 1883
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-token-123"
INFLUX_ORG = "boiler_org"
INFLUX_BUCKET = "boiler_data"

#Connect to InfluxDB
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

print("Connected to InfluxDB")

def on_connect(client , userdata , flags , rc):
    if rc == 0:
       print("Influx consumer connected to MQTT broker")
       # Subcribe to all boiler and chimney topics
       client.subscribe("boiler/#", qos=1)
       client.subscribe("chimney/#", qos=1)
       client.subscribe("system/faults", qos=2)
       print("Subscribed to boiler/# , chimney/# , system/faults")
    
def on_message(client ,  userdata  , message):
    """Every MQTT message -> write a data point to InfluxDB"""
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        topic = message.topic

        # Determine measurement name from topic prefix
        if topic.startswith("boiler/"):
            measurement = "boiler_sensors"
        elif topic.startswith("chimney/"):
            measurement = "chimney_sensors"
        elif topic == "system/faults":
            measurement = "system_faults"
        else:
            return
        device_id = payload.get("device_id", "unknown_device")

        # Write sensor reading
        if "value" in payload:
            point = (
                Point(measurement)
                .tag("device_id", device_id)
                .tag("sensor", payload.get("sensor", topic.split("/")[-1]))
                .tag("unit", payload.get("unit", ""))
                .tag("status", payload.get("status", "NORMAL"))
                .field("value", float(payload["value"]))
                .time(payload.get("timestamp", datetime.now(UTC)))
                )
            write_api.write(bucket=INFLUX_BUCKET,org = INFLUX_ORG ,  record=point) 
            print(f"Stored: {device_id} / {payload.get('sensor')} = {payload['value']} ({payload.get('status')})")

            # Write fault event
        elif  "fault_code" in payload:
            point = (
                Point("fault_events")
                .tag("device_id", device_id)
                .tag("fault_code", payload["fault_code"])
                .tag("severity", payload.get("severity", "UNKNOWN"))
                .field("affected_sensor", payload.get("affected_sensor", ""))
                .time(payload.get("timestamp", datetime.now(UTC)))
            )
            write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            print(f"fault STORED: {payload['fault_code']} ({payload.get('severity')})")
    except Exception as e:
        print(f"Error processing message: {e}")


#Setup MQTT client
mqtt_client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    client_id="influx_consumer_001",
)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
print("Influx consumer connected to MQTT broker, waiting for messages...")
mqtt_client.loop_forever()