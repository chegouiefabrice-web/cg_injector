/* =====================================================================
   CG Injector — Firmware ESP32 (exemple minimal)
   ---------------------------------------------------------------------
   Bibliothèques nécessaires (Library Manager Arduino IDE) :
     - WebSockets by Markus Sattler
     - ArduinoJson by Benoît Blanchon

   Crée un point d'accès WiFi "CG_INJECTOR" (mot de passe: cg12345678).
   L'app se connecte sur ws://192.168.4.1:81 puis envoie :
     {"cmd":"auth","password":"Poptroupe"}
   Le micro répond {"auth":true} si OK, sinon false.
   Il publie en continu : {"progression":x,"vol1":x,"vol2":x}
   ===================================================================== */

#include <WiFi.h>
#include <WebSocketsServer.h>
#include <ArduinoJson.h>

const char* AP_SSID = "CG_INJECTOR";
const char* AP_PASS = "cg12345678";
const char* APP_PASSWORD = "Poptroupe";

WebSocketsServer webSocket(81);

bool authenticated[8] = {false};
float progression = 0.0;
float vol1 = 0.0, vol2 = 0.0;
unsigned long lastPub = 0;

void sendJson(uint8_t num, JsonDocument& doc) {
  String out; serializeJson(doc, out);
  webSocket.sendTXT(num, out);
}

void onMessage(uint8_t num, uint8_t* payload, size_t length) {
  StaticJsonDocument<2048> doc;
  if (deserializeJson(doc, payload, length)) return;

  const char* cmd = doc["cmd"] | "";
  if (strcmp(cmd, "auth") == 0) {
    bool ok = strcmp(doc["password"] | "", APP_PASSWORD) == 0;
    authenticated[num] = ok;
    StaticJsonDocument<64> r; r["auth"] = ok; sendJson(num, r);
    return;
  }
  if (!authenticated[num]) {
    StaticJsonDocument<64> r; r["auth"] = false; sendJson(num, r);
    return;
  }
  if (strcmp(cmd, "start") == 0) {
    JsonArray m = doc["matrix"].as<JsonArray>();
    Serial.printf("Matrice reçue : %u lignes\n", m.size());
    // TODO: lancer le pilotage des seringues à partir de la matrice
    progression = 0;
  } else if (strcmp(cmd, "emergency_stop") == 0) {
    Serial.println("ARRÊT D'URGENCE !");
    // TODO: arrêter immédiatement les moteurs
  } else if (strcmp(cmd, "manual_load") == 0
          || strcmp(cmd, "manual_unload") == 0) {
    int sid = doc["syringe"] | 1;
    const char* state = doc["state"] | "stop";
    Serial.printf("Manuel S%d %s %s\n", sid, cmd, state);
    // TODO: piloter moteurs en continu pendant 'start' jusqu'à 'stop'
  }
}

void onEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  if (type == WStype_DISCONNECTED) authenticated[num] = false;
  else if (type == WStype_TEXT)    onMessage(num, payload, length);
}

void setup() {
  Serial.begin(115200);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("AP IP: "); Serial.println(WiFi.softAPIP());
  webSocket.begin();
  webSocket.onEvent(onEvent);
}

void loop() {
  webSocket.loop();
  if (millis() - lastPub > 1000) {
    lastPub = millis();
    StaticJsonDocument<128> doc;
    doc["progression"] = progression;
    doc["vol1"] = vol1;
    doc["vol2"] = vol2;
    String out; serializeJson(doc, out);
    webSocket.broadcastTXT(out);
    if (progression < 100) progression += 1;
  }
}
