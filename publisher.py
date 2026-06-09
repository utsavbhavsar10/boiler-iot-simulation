"""sends a test message every second"""
import paho.mqtt.client as mqtt
import json
import time

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC = "test/hello"
CLIENT_ID = "publisher_001"

def on_connect(client, userdata , flags , rc):
    if rc == 0:
        print("Connected to MQTT Broker!")
    else:
        print("Failed to connect, return code %d\n", rc)

client = mqtt.Client(
   callback_api_version=mqtt.CallbackAPIVersion.VERSION1, 
   client_id=CLIENT_ID
)
client.on_connect = on_connect  #Opens TCP Connection to the broker and returns a result code
client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
client.loop_start()
time.sleep(1)  # wait for connection to establish

message_count  = 0
while True:
    message_count += 1
    payload = {
        "message_id": message_count,
        "text":"Hello from Boiler system!",
        "timestamp": time.time(),
    }
    ## qos - quality of service
    ## qos=0: At most once delivery (fire and forget) messages can be lost
    ## qos=1: At least once delivery (message will be delivered at least once
    # , but duplicates may occur)
    # qos=2: Exactly once delivery (message will be delivered exactly once)
    # slowest used for critical messages like faults alerts
    client.publish(TOPIC, json.dumps(payload) , qos=1)
    print(f"Published message {message_count} to topic {TOPIC}")
    time.sleep(1)  # publish every second
