#include <WiFi.h>
#include <WiFiUdp.h>
#include <PubSubClient.h>


#define PROTOCOL 2

const char*    WIFI_SSID   = "Polymorphism";
const char*    WIFI_PASS   = "RishiDhamala";

const uint16_t UDP_PORT    = 4210;

const char*    MQTT_BROKER = "192.168.211.50";
const uint16_t MQTT_PORT   = 1883;
const char*    MQTT_TOPIC  = "robot/cmd";
const char*    MQTT_STATUS = "robot/status";
const char*    MQTT_CLIENT = "esp32-robot";


const uint8_t PIN_ENA = 14;    
const uint8_t PIN_IN1 = 26;    
const uint8_t PIN_IN2 = 27;    
const uint8_t PIN_ENB = 25;    
const uint8_t PIN_IN3 = 18;    
const uint8_t PIN_IN4 = 19;    
const uint8_t PIN_LED = 2;    

const uint32_t PWM_FREQ       = 5000;
const uint8_t  PWM_BITS       = 8;       

const uint8_t  DEFAULT_SPEED  = 200;
const uint8_t  TURN_FAST      = 200;
const uint8_t  TURN_SLOW      = 60;
const uint8_t  MIN_PWM        = 40;      

const uint8_t  RAMP_ACCEL     = 15;      
const uint8_t  RAMP_BRAKE     = 30;      
const uint32_t RAMP_TICK_MS   = 20;

const uint32_t WATCHDOG_MS    = 800;
const uint32_t WIFI_TIMEOUT   = 20000;
const uint32_t MQTT_RETRY_MIN = 1000;
const uint32_t MQTT_RETRY_MAX = 16000;

const uint32_t DIAG_MS        = 3000;
const uint32_t STATUS_PUB_MS  = 5000;


struct Motor {
    uint8_t pinEN, pinA, pinB;
    int     current, target;
    bool    dirA, dirB;

    void begin() {
        pinMode(pinA, OUTPUT);
        pinMode(pinB, OUTPUT);
        ledcAttach(pinEN, PWM_FREQ, PWM_BITS);
        hardStop();
    }

    void set(uint8_t speed, bool a, bool b) {
        target = speed;
        dirA = a;
        dirB = b;
        digitalWrite(pinA, dirA);
        digitalWrite(pinB, dirB);
    }

    void hardStop() {
        target = 0;
        current = 0;
        dirA = LOW;
        dirB = LOW;
        digitalWrite(pinA, LOW);
        digitalWrite(pinB, LOW);
        ledcWrite(pinEN, 0);
    }

    bool ramp() {
        bool changed = false;
        if (current < target) {
            current = min(current + (int)RAMP_ACCEL, (int)target);
            changed = true;
        } else if (current > target) {
            current = max(current - (int)RAMP_BRAKE, (int)target);
            changed = true;
        }
        if (changed) ledcWrite(pinEN, current);
        return changed;
    }
};

Motor leftMotor  = { PIN_ENA, PIN_IN1, PIN_IN2, 0, 0, LOW, LOW };
Motor rightMotor = { PIN_ENB, PIN_IN3, PIN_IN4, 0, 0, LOW, LOW };


struct RobotCommand {
    char    direction;     
    uint8_t speed;         
    bool    hasSpeed;      
};


WiFiUDP        udp;
WiFiClient     wifiClient;
PubSubClient   mqtt(wifiClient);

char     activeCmd      = 'S';
uint32_t lastCmdTime    = 0;
uint32_t lastRampTime   = 0;
uint32_t lastDiagTime   = 0;
uint32_t lastStatusTime = 0;
uint32_t lastMqttRetry  = 0;
uint32_t mqttRetryDelay = MQTT_RETRY_MIN;
uint32_t totalCmds      = 0;
uint32_t cmdPerSec      = 0;
uint32_t cmdSecCounter  = 0;
uint32_t cmdSecTimer    = 0;
bool     watchdogFired  = false;
bool     ledState       = false;
uint32_t ledTimer       = 0;
char     lastSource[5]  = "none";

RobotCommand parseCommand(const char* raw, int len) {
    RobotCommand cmd = { 'S', DEFAULT_SPEED, false };

    if (len <= 0) return cmd;

    char buf[32] = {0};
    int copyLen = min(len, 31);
    memcpy(buf, raw, copyLen);

    for (int i = 0; i < copyLen; i++) {
        if (buf[i] >= 'a' && buf[i] <= 'z')
            buf[i] -= 32;
    }

    char* colon = strchr(buf, ':');
    if (colon) {
        *colon = '\0';
        int spd = atoi(colon + 1);
        if (spd > 0 && spd <= 255) {
            cmd.speed = (uint8_t)spd;
            cmd.hasSpeed = true;
        }
    }

    if (buf[0] == 'F' || !strncmp(buf, "FORWARD", 7))
        cmd.direction = 'F';
    else if (buf[0] == 'B' || !strncmp(buf, "BACK", 4))
        cmd.direction = 'B';
    else if (buf[0] == 'L' || !strncmp(buf, "LEFT", 4))
        cmd.direction = 'L';
    else if (buf[0] == 'R' || !strncmp(buf, "RIGHT", 5))
        cmd.direction = 'R';
    else
        cmd.direction = 'S';

    return cmd;
}


void moveForward(uint8_t speed) {
    leftMotor.set(speed,  HIGH, LOW);
    rightMotor.set(speed, HIGH, LOW);
}

void moveBackward(uint8_t speed) {
    leftMotor.set(speed,  LOW, HIGH);
    rightMotor.set(speed, LOW, HIGH);
}

void turnLeft(uint8_t speed) {
    uint8_t slow = (speed * TURN_SLOW) / TURN_FAST;
    if (slow < MIN_PWM) slow = MIN_PWM;
    leftMotor.set(slow,  HIGH, LOW);
    rightMotor.set(speed, HIGH, LOW);
}

void turnRight(uint8_t speed) {
    uint8_t slow = (speed * TURN_SLOW) / TURN_FAST;
    if (slow < MIN_PWM) slow = MIN_PWM;
    leftMotor.set(speed, HIGH, LOW);
    rightMotor.set(slow,  HIGH, LOW);
}

void stopMotors() {
    leftMotor.hardStop();
    rightMotor.hardStop();
}

void executeCommand(RobotCommand& cmd, const char* source) {
    activeCmd = cmd.direction;
    lastCmdTime = millis();
    totalCmds++;
    cmdSecCounter++;
    watchdogFired = false;
    strncpy(lastSource, source, sizeof(lastSource) - 1);

    uint8_t spd = cmd.hasSpeed ? cmd.speed : DEFAULT_SPEED;

    switch (cmd.direction) {
        case 'F': moveForward(spd);  break;
        case 'B': moveBackward(spd); break;
        case 'L': turnLeft(spd);     break;
        case 'R': turnRight(spd);    break;
        default:  stopMotors();      break;
    }
}


#if PROTOCOL == 0 || PROTOCOL == 2

void setupUDP() {
    udp.begin(UDP_PORT);
    Serial.printf("[UDP] listening on port %d\n", UDP_PORT);
}

void pollUDP() {
    int packetSize = udp.parsePacket();
    if (packetSize <= 0) return;

    char buf[64];
    int len = udp.read(buf, sizeof(buf) - 1);
    if (len <= 0) return;
    buf[len] = '\0';

    while (len > 0 && (buf[len-1] == '\n' || buf[len-1] == '\r')) {
        buf[--len] = '\0';
    }

    RobotCommand cmd = parseCommand(buf, len);
    executeCommand(cmd, "UDP");
}

#endif


#if PROTOCOL == 1 || PROTOCOL == 2

void onMqttMessage(char* topic, byte* payload, unsigned int len) {
    if (len == 0 || len > 32) return;

    char buf[33] = {0};
    memcpy(buf, payload, len);

    RobotCommand cmd = parseCommand(buf, len);
    executeCommand(cmd, "MQTT");
}

void setupMQTT() {
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setCallback(onMqttMessage);
    mqtt.setKeepAlive(10);
    mqtt.setSocketTimeout(5);
    Serial.printf("[MQTT] broker %s:%d\n", MQTT_BROKER, MQTT_PORT);
}

void pollMQTT() {
    if (!mqtt.connected()) {
        if (WiFi.status() != WL_CONNECTED) return;

        uint32_t now = millis();
        if (now - lastMqttRetry < mqttRetryDelay) return;
        lastMqttRetry = now;

        if (mqtt.connect(MQTT_CLIENT)) {
            mqtt.subscribe(MQTT_TOPIC, 1);
            mqttRetryDelay = MQTT_RETRY_MIN;
            Serial.println("[MQTT] connected");
            mqtt.publish(MQTT_STATUS, "online", true);
        } else {
            Serial.printf("[MQTT] fail rc=%d retry %lums\n",
                          mqtt.state(), mqttRetryDelay);
            if (mqttRetryDelay < MQTT_RETRY_MAX)
                mqttRetryDelay *= 2;
        }
        return;
    }

    mqtt.loop();
}

void publishStatus() {
    if (!mqtt.connected()) return;

    uint32_t now = millis();
    if (now - lastStatusTime < STATUS_PUB_MS) return;
    lastStatusTime = now;

    char buf[128];
    snprintf(buf, sizeof(buf),
        "{\"cmd\":\"%c\",\"src\":\"%s\","
        "\"sL\":%d,\"sR\":%d,"
        "\"rssi\":%d,\"heap\":%u,"
        "\"up\":%lu,\"cmds\":%lu,\"cps\":%lu}",
        activeCmd, lastSource,
        leftMotor.current, rightMotor.current,
        WiFi.RSSI(), ESP.getFreeHeap(),
        now / 1000, totalCmds, cmdPerSec
    );

    mqtt.publish(MQTT_STATUS, buf, false);
}

#endif


void setupWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    Serial.print("[WiFi] connecting");
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print(".");
        if (millis() - t0 > WIFI_TIMEOUT) {
            Serial.println(" TIMEOUT");
            ESP.restart();
        }
    }

    Serial.printf("\n[WiFi] IP: %s  RSSI: %d dBm\n",
        WiFi.localIP().toString().c_str(), WiFi.RSSI());
}


void checkWatchdog() {
    if (activeCmd == 'S') return;

    if ((millis() - lastCmdTime) > WATCHDOG_MS) {
        if (!watchdogFired) {
            Serial.printf("[WDG] no cmd for %lums -> STOP\n",
                millis() - lastCmdTime);
            watchdogFired = true;
        }
        activeCmd = 'S';
        stopMotors();
    }
}


void updateRamp() {
    if (millis() - lastRampTime < RAMP_TICK_MS) return;
    lastRampTime = millis();

    leftMotor.ramp();
    rightMotor.ramp();
}


void updateLED() {
    uint32_t rate;
    bool mqttOk = true;

    #if PROTOCOL == 1 || PROTOCOL == 2
    mqttOk = mqtt.connected();
    #endif

    if (WiFi.status() != WL_CONNECTED)
        rate = 100;
    else if (!mqttOk && PROTOCOL != 0)
        rate = 250;
    else if (activeCmd != 'S')
        rate = 500;
    else
        rate = 1000;

    if (millis() - ledTimer >= rate) {
        ledState = !ledState;
        digitalWrite(PIN_LED, ledState);
        ledTimer = millis();
    }
}

/

void printDiag() {
    uint32_t now = millis();

    if (now - cmdSecTimer >= 1000) {
        cmdPerSec = cmdSecCounter;
        cmdSecCounter = 0;
        cmdSecTimer = now;
    }

    if (now - lastDiagTime < DIAG_MS) return;
    lastDiagTime = now;

    const char* proto;
    #if PROTOCOL == 0
    proto = "UDP";
    #elif PROTOCOL == 1
    proto = "MQTT";
    #else
    proto = "UDP+MQTT";
    #endif

    bool mqttOk = false;
    #if PROTOCOL == 1 || PROTOCOL == 2
    mqttOk = mqtt.connected();
    #endif

    Serial.println("--------------------------------------------");
    Serial.printf("  Proto  : %s\n", proto);
    Serial.printf("  Uptime : %lu s\n", now / 1000);
    Serial.printf("  Heap   : %u B\n", ESP.getFreeHeap());
    Serial.printf("  WiFi   : %s  RSSI %d dBm\n",
        WiFi.status() == WL_CONNECTED ? "OK" : "DOWN",
        WiFi.RSSI());

    #if PROTOCOL == 1 || PROTOCOL == 2
    Serial.printf("  MQTT   : %s\n", mqttOk ? "OK" : "DOWN");
    #endif

    Serial.printf("  Source : %s\n", lastSource);
    Serial.printf("  CMD    : '%c'  total: %lu  rate: %lu/s\n",
        activeCmd, totalCmds, cmdPerSec);
    Serial.printf("  Motor L: %3d → %3d   R: %3d → %3d\n",
        leftMotor.current, leftMotor.target,
        rightMotor.current, rightMotor.target);
    Serial.printf("  Cmd age: %lu ms  WDG: %s\n",
        now - lastCmdTime,
        watchdogFired ? "FIRED" : "ok");
    Serial.println("--------------------------------------------");
}


void setup() {
    Serial.begin(115200);
    delay(100);

    Serial.println();
    Serial.println("============================================");
    Serial.println("  ESP32 Robot Controller v3.0");

    #if PROTOCOL == 0
    Serial.println("  Protocol: UDP (low latency)");
    #elif PROTOCOL == 1
    Serial.println("  Protocol: MQTT (reliable)");
    #else
    Serial.println("  Protocol: UDP + MQTT (dual)");
    #endif

    Serial.println("============================================");

    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, LOW);

    leftMotor.begin();
    rightMotor.begin();
    Serial.println("[MOT] initialized");

    setupWiFi();

    #if PROTOCOL == 0 || PROTOCOL == 2
    setupUDP();
    #endif

    #if PROTOCOL == 1 || PROTOCOL == 2
    setupMQTT();
    #endif

    lastCmdTime = millis();
    cmdSecTimer = millis();

    Serial.println("============================================");

    #if PROTOCOL == 0 || PROTOCOL == 2
    Serial.printf("  UDP endpoint: %s:%d\n",
        WiFi.localIP().toString().c_str(), UDP_PORT);
    #endif

    #if PROTOCOL == 1 || PROTOCOL == 2
    Serial.printf("  MQTT topic:   %s\n", MQTT_TOPIC);
    #endif

    Serial.println("============================================\n");
}


void loop() {
    #if PROTOCOL == 0 || PROTOCOL == 2
    pollUDP();
    #endif

    #if PROTOCOL == 1 || PROTOCOL == 2
    pollMQTT();
    publishStatus();
    #endif

    updateRamp();
    checkWatchdog();
    updateLED();
    printDiag();
}