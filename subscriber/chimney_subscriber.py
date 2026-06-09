"""Listens on chimney topics and prints what arrives."""

import paho.mqtt.client as mqtt
import json

BROKER_HOST = "localhost"
BROKER_PORT = 1883
CLIENT_ID = "chimney_subscriber_001"

# chimney/#       — every chimney sensor (flue_temp, co2, o2, co, draft, stack_velocity, status)
# system/faults   — fault events from chimney + boiler share this topic (QoS 2)
SUBSCRIPTIONS = [
    ("chimney/#", 1),
    ("system/faults", 2),
]


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Chimney subscriber connected")
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
            print(f"Subscribed to {topic} (qos={qos})")
    else:
        print(f"Connection failed: {rc}")


def on_message(client, userdata, message):
    payload = json.loads(message.payload.decode("utf-8"))

    # Highlight faults so they don't get lost in the sensor stream
    if message.topic == "system/faults":
        print(f"FAULT [{payload.get('device_id')}] {payload.get('fault_code')} "
              f"({payload.get('severity')}) — {payload.get('message')}")
    else:
        print(f"[{message.topic}] {payload}")


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    client_id=CLIENT_ID,
)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
client.loop_forever()
