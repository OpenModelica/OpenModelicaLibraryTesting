"""Servers that library examples expect to find on this machine, run for as
long as the tests do."""

import shutil, socketserver, subprocess, threading

# TestSerialPackager_TCPIP (Modelica_DeviceDrivers) and ExampleClientLoop
# (AixLib) are clients of the echo server their libraries ship as Windows code.
TCP_ECHO_PORT = 27015
# TestSerialPackager_MQTT (Modelica_DeviceDrivers) talks to test.mosquitto.org,
# which the job's container resolves to this machine.
MQTT_PORT = 1883

class EchoHandler(socketserver.BaseRequestHandler):
  def handle(self):
    while True:
      data = self.request.recv(4096)
      if not data:
        return
      self.request.sendall(data)

class EchoServer(socketserver.ThreadingTCPServer):
  allow_reuse_address = True
  daemon_threads = True

def startEchoServer():
  try:
    server = EchoServer(("127.0.0.1", TCP_ECHO_PORT), EchoHandler)
  except OSError as e:
    print("Not starting the TCP echo server on port %d: %s" % (TCP_ECHO_PORT, e))
    return None
  threading.Thread(target=server.serve_forever, daemon=True).start()
  return server

def startMqttBroker():
  mosquitto = shutil.which("mosquitto") or shutil.which("mosquitto", path="/usr/sbin:/usr/local/sbin")
  if not mosquitto:
    print("No mosquitto, so no local MQTT broker")
    return None
  return subprocess.Popen([mosquitto, "-p", str(MQTT_PORT)], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start():
  return (startEchoServer(), startMqttBroker())

def stop(services):
  (echo, mqtt) = services
  if echo is not None:
    echo.shutdown()
    echo.server_close()
  if mqtt is not None:
    mqtt.terminate()
    try:
      mqtt.wait(timeout=10)
    except subprocess.TimeoutExpired:
      mqtt.kill()
