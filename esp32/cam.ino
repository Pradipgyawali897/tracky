#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>

#define PWDN     32
#define RESET    -1
#define XCLK      0
#define SIOD     26
#define SIOC     27
#define D7       35
#define D6       34
#define D5       39
#define D4       36
#define D3       21
#define D2       19
#define D1       18
#define D0        5
#define VSYNC    25
#define HREF     23
#define PCLK     22
#define FLASH     4
#define LED      33

const char* SSID = "Polymorphism";
const char* PASS = "RishiDhamala";

httpd_handle_t server = NULL;

bool setupCamera() {
    camera_config_t cfg = {};
    cfg.pin_d0       = D0;
    cfg.pin_d1       = D1;
    cfg.pin_d2       = D2;
    cfg.pin_d3       = D3;
    cfg.pin_d4       = D4;
    cfg.pin_d5       = D5;
    cfg.pin_d6       = D6;
    cfg.pin_d7       = D7;
    cfg.pin_xclk     = XCLK;
    cfg.pin_pclk     = PCLK;
    cfg.pin_vsync    = VSYNC;
    cfg.pin_href     = HREF;
    cfg.pin_sccb_sda = SIOD;
    cfg.pin_sccb_scl = SIOC;
    cfg.pin_pwdn     = PWDN;
    cfg.pin_reset    = RESET;
    cfg.ledc_channel = LEDC_CHANNEL_0;
    cfg.ledc_timer   = LEDC_TIMER_0;
    cfg.xclk_freq_hz = 20000000;
    cfg.pixel_format = PIXFORMAT_JPEG;

    if (psramFound()) {
        cfg.frame_size   = FRAMESIZE_VGA;
        cfg.jpeg_quality = 12;
        cfg.fb_count     = 2;
        cfg.fb_location  = CAMERA_FB_IN_PSRAM;
        cfg.grab_mode    = CAMERA_GRAB_LATEST;
    } else {
        cfg.frame_size   = FRAMESIZE_QVGA;
        cfg.jpeg_quality = 15;
        cfg.fb_count     = 1;
        cfg.fb_location  = CAMERA_FB_IN_DRAM;
        cfg.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
    }

    if (esp_camera_init(&cfg) != ESP_OK) return false;

    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s->set_brightness(s, 1);
        s->set_saturation(s, -1);
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        s->set_aec2(s, 1);
    }

    return true;
}

static esp_err_t streamHandler(httpd_req_t* req) {
    esp_err_t res = httpd_resp_set_type(req,
        "multipart/x-mixed-replace;boundary=frame");
    if (res != ESP_OK) return res;

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(req, "Cache-Control", "no-cache");

    while (true) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) {
            res = ESP_FAIL;
            break;
        }

        char hdr[80];
        int hlen = snprintf(hdr, sizeof(hdr),
            "--frame\r\n"
            "Content-Type: image/jpeg\r\n"
            "Content-Length: %u\r\n\r\n",
            fb->len);

        res = httpd_resp_send_chunk(req, hdr, hlen);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, (const char*)fb->buf, fb->len);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, "\r\n", 2);

        esp_camera_fb_return(fb);
        if (res != ESP_OK) break;
    }

    return res;
}

static esp_err_t snapHandler(httpd_req_t* req) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    esp_err_t res = httpd_resp_send(req, (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    return res;
}

void startServer() {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port      = 81;
    cfg.ctrl_port        = 32768;
    cfg.max_open_sockets = 4;
    cfg.stack_size       = 8192;

    if (httpd_start(&server, &cfg) != ESP_OK) return;

    httpd_uri_t streamUri = {};
    streamUri.uri     = "/stream";
    streamUri.method  = HTTP_GET;
    streamUri.handler = streamHandler;
    httpd_register_uri_handler(server, &streamUri);

    httpd_uri_t snapUri = {};
    snapUri.uri     = "/snap";
    snapUri.method  = HTTP_GET;
    snapUri.handler = snapHandler;
    httpd_register_uri_handler(server, &snapUri);
}

void setup() {
    Serial.begin(115200);

    pinMode(FLASH, OUTPUT);
    digitalWrite(FLASH, LOW);
    pinMode(LED, OUTPUT);

    if (!setupCamera()) {
        Serial.println("CAMERA FAILED");
        ESP.restart();
    }

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(true);
    WiFi.begin(SSID, PASS);

    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        if (millis() - t0 > 20000) ESP.restart();
    }

    startServer();

    Serial.printf("STREAM: http://%s:81/stream\n",
                  WiFi.localIP().toString().c_str());
    Serial.printf("SNAP:   http://%s:81/snap\n",
                  WiFi.localIP().toString().c_str());
}

void loop() {
    static bool led = false;
    static uint32_t lt = 0;
    uint32_t now = millis();

    uint32_t rate = (WiFi.status() == WL_CONNECTED) ? 1000 : 200;
    if (now - lt >= rate) {
        led = !led;
        digitalWrite(LED, led);
        lt = now;
    }

    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
    delay(100);
}