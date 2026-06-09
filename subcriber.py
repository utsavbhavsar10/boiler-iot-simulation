"""Listens on boiler/chimney/system topics and prints what arrives."""

import paho.mqtt.client as mqtt
import json

BROKER_HOST = "localhost"
BROKER_PORT = 1883
CLIENT_ID = "subscriber_001"

# Subscribe to multiple wildcard topics:
#   boiler/#       — every boiler-side sensor
#   turbine/#      — every turbine-side sensor
#   system/faults  — fault events (use QoS 2 because losing a fault is bad)
SUBSCRIPTIONS = [
    ("boiler/#", 1),
    ("turbine/#", 1),
    ("system/faults", 2),
]


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Subscriber connected")
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
            print(f"Subscribed to {topic} (qos={qos})")
    else:
        print(f"Connection failed: {rc}")


def on_message(client, userdata, message):
    payload = json.loads(message.payload.decode("utf-8"))
    print(f"[{message.topic}] {payload}")


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    client_id=CLIENT_ID,
)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
client.loop_forever()
