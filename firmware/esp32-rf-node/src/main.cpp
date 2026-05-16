#include <Arduino.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include <esp_err.h>
#include <esp_mac.h>
#include <esp_now.h>
#include <esp_wifi.h>

#ifndef NODE_WIFI_SSID
#define NODE_WIFI_SSID ""
#endif

#ifndef NODE_WIFI_PASSWORD
#define NODE_WIFI_PASSWORD ""
#endif

#ifndef NODE_TARGET_IP
#define NODE_TARGET_IP "192.168.88.10"
#endif

#ifndef NODE_TARGET_PORT
#define NODE_TARGET_PORT 5005
#endif

#ifndef NODE_NUM_ID
#define NODE_NUM_ID 1
#endif

#ifndef NODE_LABEL
#define NODE_LABEL "cctv-ruview-node"
#endif

#ifndef NODE_TDM_SLOT
#define NODE_TDM_SLOT 0
#endif

#ifndef NODE_TDM_TOTAL
#define NODE_TDM_TOTAL 6
#endif

#ifndef NODE_WIFI_CHANNEL
#define NODE_WIFI_CHANNEL 11
#endif

namespace {

constexpr uint32_t kAdrCsiMagic = 0xC5110001;
constexpr uint32_t kRfLinkMagic = 0xC5110101;
constexpr uint32_t kRfHealthMagic = 0xC5110102;
constexpr uint32_t kSoundingMagic = 0x43534E44;  // CSND
constexpr uint16_t kConfigPort = 80;
constexpr uint16_t kOtaCompatPort = 8032;
constexpr size_t kMaxCsiBytes = 384;
constexpr size_t kCsiQueueSize = 48;
constexpr uint32_t kTdmSlotMs = 160;
constexpr uint8_t kBurstPerSlot = 2;
constexpr uint32_t kEspNowCsiInferWindowMs = 320;
constexpr uint8_t kEspNowCsiInferBudget = 2;
constexpr uint32_t kHealthIntervalMs = 1000;
constexpr uint32_t kStatusLogIntervalMs = 10000;
constexpr uint8_t kBroadcastMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

enum LinkFlags : uint8_t {
  kFlagCsiPresent = 1 << 0,
  kFlagEspNow = 1 << 1,
  kFlagBroadcast = 1 << 2,
  kFlagUnknownPeer = 1 << 3,
  kFlagInferredTx = 1 << 4,
};

struct NodeConfig {
  uint8_t node_id = NODE_NUM_ID;
  uint8_t tdm_slot = NODE_TDM_SLOT;
  uint8_t tdm_total = NODE_TDM_TOTAL;
  uint8_t channel = NODE_WIFI_CHANNEL;
  uint16_t target_port = NODE_TARGET_PORT;
  String label = NODE_LABEL;
  String ssid = NODE_WIFI_SSID;
  String password = NODE_WIFI_PASSWORD;
  String target_ip = NODE_TARGET_IP;
};

struct CsiSample {
  uint8_t rx_node_id = 0;
  uint8_t tx_node_id = 0;
  uint8_t flags = 0;
  uint8_t channel = 0;
  uint32_t sequence = 0;
  uint32_t uptime_ms = 0;
  int8_t rssi = 0;
  int8_t noise_floor = 0;
  uint8_t tx_mac[6] = {};
  uint16_t csi_len = 0;
  int8_t csi[kMaxCsiBytes] = {};
};

struct SoundingPayload {
  uint32_t magic;
  uint8_t version;
  uint8_t tx_node_id;
  uint8_t target_node_id;
  uint8_t flags;
  uint32_t sequence;
  uint32_t uptime_ms;
} __attribute__((packed));

Preferences prefs;
WebServer server(kConfigPort);
WebServer compat_server(kOtaCompatPort);
WiFiUDP udp;
NodeConfig config;
IPAddress target_ip;
bool target_ip_ok = false;
bool esp_now_ready = false;
bool csi_ready = false;
uint32_t sequence_counter = 0;
uint32_t health_sequence = 0;
uint32_t dropped_csi_samples = 0;
uint32_t adr_csi_sent = 0;
uint32_t rf_link_sent = 0;
uint32_t last_health_ms = 0;
uint32_t last_log_ms = 0;
uint32_t last_slot_epoch = UINT32_MAX;
uint32_t esp_now_tx_submit_fail_count = 0;

portMUX_TYPE espnow_mux = portMUX_INITIALIZER_UNLOCKED;
uint32_t esp_now_rx_count = 0;
uint32_t esp_now_tx_ok_count = 0;
uint32_t esp_now_tx_fail_count = 0;
uint32_t last_esp_now_rx_ms = 0;
uint32_t last_esp_now_rx_sequence = 0;
uint8_t last_esp_now_rx_node_id = 0;
uint8_t last_esp_now_rx_pending_csi = 0;
uint8_t last_esp_now_rx_mac[6] = {};

portMUX_TYPE csi_mux = portMUX_INITIALIZER_UNLOCKED;
CsiSample csi_queue[kCsiQueueSize];
volatile size_t csi_head = 0;
volatile size_t csi_tail = 0;
volatile size_t csi_count = 0;

String jsonEscape(const String &value) {
  String escaped;
  escaped.reserve(value.length() + 8);
  for (size_t i = 0; i < value.length(); ++i) {
    const char c = value[i];
    switch (c) {
      case '\\':
        escaped += "\\\\";
        break;
      case '"':
        escaped += "\\\"";
        break;
      case '\n':
        escaped += "\\n";
        break;
      case '\r':
        escaped += "\\r";
        break;
      case '\t':
        escaped += "\\t";
        break;
      default:
        escaped += c;
        break;
    }
  }
  return escaped;
}

String q(const String &value) {
  return "\"" + jsonEscape(value) + "\"";
}

String wifiStatusText(wl_status_t status) {
  switch (status) {
    case WL_CONNECTED:
      return "connected";
    case WL_NO_SSID_AVAIL:
      return "no_ssid";
    case WL_CONNECT_FAILED:
      return "connect_failed";
    case WL_CONNECTION_LOST:
      return "connection_lost";
    case WL_DISCONNECTED:
      return "disconnected";
    case WL_IDLE_STATUS:
      return "idle";
    default:
      return String("status_") + static_cast<int>(status);
  }
}

String macToString(const uint8_t mac[6]) {
  char buffer[18];
  snprintf(buffer, sizeof(buffer), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(buffer);
}

String macAddress() {
  return WiFi.macAddress();
}

String ipAddress() {
  return WiFi.isConnected() ? WiFi.localIP().toString() : "";
}

String hostname() {
  char buffer[40];
  snprintf(buffer, sizeof(buffer), "cctv-ruview-node-%02u", config.node_id);
  return String(buffer);
}

void loadConfig() {
  prefs.begin("cctv_rf", true);
  config.node_id = prefs.getUChar("node_id", NODE_NUM_ID);
  config.tdm_slot = prefs.getUChar("tdm_slot", NODE_TDM_SLOT);
  config.tdm_total = prefs.getUChar("tdm_total", NODE_TDM_TOTAL);
  config.channel = prefs.getUChar("channel", NODE_WIFI_CHANNEL);
  config.target_port = prefs.getUShort("target_port", NODE_TARGET_PORT);
  config.label = prefs.isKey("label") ? prefs.getString("label", NODE_LABEL) : NODE_LABEL;
  config.ssid = prefs.isKey("ssid") ? prefs.getString("ssid", NODE_WIFI_SSID) : NODE_WIFI_SSID;
  config.password = prefs.isKey("password") ? prefs.getString("password", NODE_WIFI_PASSWORD) : NODE_WIFI_PASSWORD;
  config.target_ip = prefs.isKey("target_ip") ? prefs.getString("target_ip", NODE_TARGET_IP) : NODE_TARGET_IP;
  prefs.end();

  if (config.node_id == 0) {
    config.node_id = 1;
  }
  if (config.tdm_total == 0) {
    config.tdm_total = 1;
  }
  config.tdm_slot = config.tdm_slot % config.tdm_total;
  target_ip_ok = target_ip.fromString(config.target_ip);
}

void saveConfigValue(const String &key, const String &value) {
  prefs.begin("cctv_rf", false);
  if (key == "node_id") {
    prefs.putUChar("node_id", static_cast<uint8_t>(value.toInt()));
  } else if (key == "tdm_slot") {
    prefs.putUChar("tdm_slot", static_cast<uint8_t>(value.toInt()));
  } else if (key == "tdm_total") {
    prefs.putUChar("tdm_total", static_cast<uint8_t>(value.toInt()));
  } else if (key == "channel") {
    prefs.putUChar("channel", static_cast<uint8_t>(value.toInt()));
  } else if (key == "target_port") {
    prefs.putUShort("target_port", static_cast<uint16_t>(value.toInt()));
  } else if (key == "label") {
    prefs.putString("label", value);
  } else if (key == "ssid") {
    prefs.putString("ssid", value);
  } else if (key == "password") {
    prefs.putString("password", value);
  } else if (key == "target_ip") {
    prefs.putString("target_ip", value);
  }
  prefs.end();
}

void clearConfig() {
  prefs.begin("cctv_rf", false);
  prefs.clear();
  prefs.end();
}

String configJson(bool include_secret = false) {
  String body;
  body.reserve(900);
  body += "{";
  body += "\"firmware\":\"cctv-ruview-broadcast-csi-node\"";
  body += ",\"version\":\"0.3.0\"";
  body += ",\"node_id\":" + String(config.node_id);
  body += ",\"label\":" + q(config.label);
  body += ",\"hostname\":" + q(hostname());
  body += ",\"tdm_slot\":" + String(config.tdm_slot);
  body += ",\"tdm_total\":" + String(config.tdm_total);
  body += ",\"channel\":" + String(config.channel);
  body += ",\"target_ip\":" + q(config.target_ip);
  body += ",\"target_port\":" + String(config.target_port);
  body += ",\"ssid\":" + q(config.ssid);
  body += ",\"has_password\":" + String(config.password.length() ? "true" : "false");
  if (include_secret) {
    body += ",\"password\":" + q(config.password);
  }
  body += ",\"sounding\":\"esp-now-broadcast\"";
  body += "}";
  return body;
}

String healthJson() {
  uint32_t espnow_rx = 0;
  uint32_t espnow_tx_ok = 0;
  uint32_t espnow_tx_fail = 0;
  uint32_t espnow_last_rx_ms = 0;
  uint32_t espnow_last_rx_sequence = 0;
  uint8_t espnow_last_rx_node_id = 0;
  uint8_t espnow_last_rx_pending_csi = 0;
  uint8_t espnow_last_rx_mac[6] = {};
  portENTER_CRITICAL(&espnow_mux);
  espnow_rx = esp_now_rx_count;
  espnow_tx_ok = esp_now_tx_ok_count;
  espnow_tx_fail = esp_now_tx_fail_count;
  espnow_last_rx_ms = last_esp_now_rx_ms;
  espnow_last_rx_sequence = last_esp_now_rx_sequence;
  espnow_last_rx_node_id = last_esp_now_rx_node_id;
  espnow_last_rx_pending_csi = last_esp_now_rx_pending_csi;
  memcpy(espnow_last_rx_mac, last_esp_now_rx_mac, sizeof(espnow_last_rx_mac));
  portEXIT_CRITICAL(&espnow_mux);

  String body;
  body.reserve(1800);
  body += "{";
  body += "\"node_id\":" + String(config.node_id);
  body += ",\"node_label\":" + q(config.label);
  body += ",\"hostname\":" + q(hostname());
  body += ",\"mac\":" + q(macAddress());
  body += ",\"ip\":" + q(ipAddress());
  body += ",\"wifi_status\":" + q(wifiStatusText(WiFi.status()));
  body += ",\"ssid\":" + q(WiFi.SSID());
  body += ",\"bssid\":" + q(WiFi.BSSIDstr());
  body += ",\"channel\":" + String(WiFi.channel());
  body += ",\"configured_channel\":" + String(config.channel);
  body += ",\"rssi\":" + String(WiFi.isConnected() ? WiFi.RSSI() : 0);
  body += ",\"target_ip\":" + q(config.target_ip);
  body += ",\"target_port\":" + String(config.target_port);
  body += ",\"tdm_slot\":" + String(config.tdm_slot);
  body += ",\"tdm_total\":" + String(config.tdm_total);
  body += ",\"esp_now_ready\":" + String(esp_now_ready ? "true" : "false");
  body += ",\"esp_now_rx_count\":" + String(espnow_rx);
  body += ",\"esp_now_tx_ok_count\":" + String(espnow_tx_ok);
  body += ",\"esp_now_tx_fail_count\":" + String(espnow_tx_fail);
  body += ",\"esp_now_tx_submit_fail_count\":" + String(esp_now_tx_submit_fail_count);
  body += ",\"esp_now_last_rx_node_id\":" + String(espnow_last_rx_node_id);
  body += ",\"esp_now_last_rx_mac\":" + q(macToString(espnow_last_rx_mac));
  body += ",\"esp_now_last_rx_sequence\":" + String(espnow_last_rx_sequence);
  body += ",\"esp_now_last_rx_pending_csi\":" + String(espnow_last_rx_pending_csi);
  body += ",\"esp_now_last_rx_age_ms\":";
  body += espnow_last_rx_ms > 0 ? String(millis() - espnow_last_rx_ms) : String("null");
  body += ",\"csi_ready\":" + String(csi_ready ? "true" : "false");
  body += ",\"dropped_csi_samples\":" + String(dropped_csi_samples);
  body += ",\"adr_csi_sent\":" + String(adr_csi_sent);
  body += ",\"rf_link_sent\":" + String(rf_link_sent);
  body += ",\"uptime_ms\":" + String(millis());
  body += ",\"free_heap\":" + String(ESP.getFreeHeap());
  body += ",\"flash_size\":" + String(ESP.getFlashChipSize());
  body += ",\"psram_size\":" + String(ESP.getPsramSize());
  body += "}";
  return body;
}

void connectWifi() {
  if (config.ssid.length() == 0) {
    Serial.println("[wifi] ssid is empty; use serial SET ssid/password");
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setHostname(hostname().c_str());
  if (config.channel > 0) {
    esp_wifi_set_channel(config.channel, WIFI_SECOND_CHAN_NONE);
  }
  Serial.printf("[wifi] connecting ssid=%s node=%u host=%s\n",
                config.ssid.c_str(), config.node_id, hostname().c_str());
  WiFi.begin(config.ssid.c_str(), config.password.c_str());
}

void ensureWifi() {
  static uint32_t last_attempt_ms = 0;
  if (config.ssid.length() == 0 || WiFi.isConnected()) {
    return;
  }
  const uint32_t now = millis();
  if (now - last_attempt_ms > 10000) {
    Serial.printf("[wifi] retry status=%s\n", wifiStatusText(WiFi.status()).c_str());
    WiFi.disconnect();
    WiFi.begin(config.ssid.c_str(), config.password.c_str());
    last_attempt_ms = now;
  }
}

void setupMdns() {
  if (!WiFi.isConnected()) {
    return;
  }
  if (MDNS.begin(hostname().c_str())) {
    MDNS.addService("http", "tcp", kConfigPort);
    Serial.printf("[mdns] http://%s.local/\n", hostname().c_str());
  } else {
    Serial.println("[mdns] failed");
  }
}

bool enqueueCsiSample(const CsiSample &sample) {
  bool ok = false;
  portENTER_CRITICAL_ISR(&csi_mux);
  if (csi_count < kCsiQueueSize) {
    csi_queue[csi_head] = sample;
    csi_head = (csi_head + 1) % kCsiQueueSize;
    ++csi_count;
    ok = true;
  } else {
    ++dropped_csi_samples;
  }
  portEXIT_CRITICAL_ISR(&csi_mux);
  return ok;
}

bool dequeueCsiSample(CsiSample &sample) {
  bool ok = false;
  portENTER_CRITICAL(&csi_mux);
  if (csi_count > 0) {
    sample = csi_queue[csi_tail];
    csi_tail = (csi_tail + 1) % kCsiQueueSize;
    --csi_count;
    ok = true;
  }
  portEXIT_CRITICAL(&csi_mux);
  return ok;
}

bool takeRecentEspNowRxForCsi(uint8_t &node_id, uint8_t mac[6], uint32_t now_ms) {
  bool ok = false;
  portENTER_CRITICAL_ISR(&espnow_mux);
  if (last_esp_now_rx_node_id != 0 &&
      last_esp_now_rx_pending_csi > 0 &&
      last_esp_now_rx_ms > 0 &&
      now_ms >= last_esp_now_rx_ms &&
      now_ms - last_esp_now_rx_ms <= kEspNowCsiInferWindowMs) {
    node_id = last_esp_now_rx_node_id;
    memcpy(mac, last_esp_now_rx_mac, 6);
    --last_esp_now_rx_pending_csi;
    ok = true;
  }
  portEXIT_CRITICAL_ISR(&espnow_mux);
  return ok;
}

void IRAM_ATTR onCsi(void *, wifi_csi_info_t *info) {
  if (!info || !info->buf || info->len <= 0) {
    return;
  }

  CsiSample sample;
  const uint32_t now_ms = millis();
  sample.rx_node_id = config.node_id;
  sample.tx_node_id = 0;
  sample.flags = kFlagCsiPresent | kFlagBroadcast;
  sample.sequence = ++sequence_counter;
  sample.uptime_ms = now_ms;
  sample.rssi = static_cast<int8_t>(info->rx_ctrl.rssi);
  sample.noise_floor = static_cast<int8_t>(info->rx_ctrl.noise_floor);
  sample.channel = static_cast<uint8_t>(info->rx_ctrl.channel);
  memcpy(sample.tx_mac, info->mac, 6);

  uint8_t recent_node_id = 0;
  uint8_t recent_mac[6] = {};
  if (!takeRecentEspNowRxForCsi(recent_node_id, recent_mac, now_ms)) {
    return;
  }
  sample.tx_node_id = recent_node_id;
  memcpy(sample.tx_mac, recent_mac, sizeof(sample.tx_mac));
  sample.flags |= kFlagEspNow | kFlagInferredTx;

  sample.csi_len = min(static_cast<size_t>(info->len), kMaxCsiBytes);
  memcpy(sample.csi, info->buf, sample.csi_len);
  enqueueCsiSample(sample);
}

void setupCsi() {
  wifi_csi_config_t csi_config = {};
  csi_config.lltf_en = true;
  csi_config.htltf_en = true;
  csi_config.stbc_htltf2_en = true;
  csi_config.ltf_merge_en = true;
  csi_config.channel_filter_en = false;
  csi_config.manu_scale = false;
  csi_config.shift = false;

  esp_err_t err = esp_wifi_set_csi_config(&csi_config);
  if (err != ESP_OK) {
    Serial.printf("[csi] config failed: %s\n", esp_err_to_name(err));
    return;
  }
  err = esp_wifi_set_csi_rx_cb(onCsi, nullptr);
  if (err != ESP_OK) {
    Serial.printf("[csi] callback failed: %s\n", esp_err_to_name(err));
    return;
  }
  err = esp_wifi_set_csi(true);
  if (err != ESP_OK) {
    Serial.printf("[csi] enable failed: %s\n", esp_err_to_name(err));
    return;
  }
  esp_wifi_set_promiscuous(true);
  csi_ready = true;
  Serial.println("[csi] enabled with promiscuous RX");
}

void addEspNowPeer(const uint8_t mac[6]) {
  if (esp_now_is_peer_exist(mac)) {
    return;
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac, 6);
  peer.channel = WiFi.channel() > 0 ? WiFi.channel() : config.channel;
  peer.encrypt = false;
  esp_err_t err = esp_now_add_peer(&peer);
  if (err != ESP_OK) {
    Serial.printf("[espnow] add peer %s failed: %s\n", macToString(mac).c_str(), esp_err_to_name(err));
  }
}

void onEspNowSent(const uint8_t *, esp_now_send_status_t status) {
  portENTER_CRITICAL(&espnow_mux);
  if (status == ESP_NOW_SEND_SUCCESS) {
    ++esp_now_tx_ok_count;
  } else {
    ++esp_now_tx_fail_count;
  }
  portEXIT_CRITICAL(&espnow_mux);
}

void onEspNowRecv(const uint8_t *mac_addr, const uint8_t *data, int data_len) {
  if (!mac_addr || !data || data_len <= 0) {
    return;
  }

  uint8_t tx_node_id = 0;
  uint32_t rx_sequence = 0;
  if (static_cast<size_t>(data_len) >= sizeof(SoundingPayload)) {
    SoundingPayload payload;
    memcpy(&payload, data, sizeof(payload));
    if (payload.magic == kSoundingMagic && payload.tx_node_id != config.node_id) {
      tx_node_id = payload.tx_node_id;
      rx_sequence = payload.sequence;
    }
  }

  portENTER_CRITICAL(&espnow_mux);
  ++esp_now_rx_count;
  if (tx_node_id != 0) {
    last_esp_now_rx_node_id = tx_node_id;
    last_esp_now_rx_ms = millis();
    last_esp_now_rx_sequence = rx_sequence;
    last_esp_now_rx_pending_csi = kEspNowCsiInferBudget;
    memcpy(last_esp_now_rx_mac, mac_addr, 6);
  }
  portEXIT_CRITICAL(&espnow_mux);
}

void setupEspNow() {
  esp_err_t err = esp_now_init();
  if (err != ESP_OK && err != ESP_ERR_ESPNOW_INTERNAL) {
    Serial.printf("[espnow] init failed: %s\n", esp_err_to_name(err));
    return;
  }
  esp_now_register_send_cb(onEspNowSent);
  esp_now_register_recv_cb(onEspNowRecv);
  addEspNowPeer(kBroadcastMac);
  esp_now_ready = true;
  Serial.printf("[espnow] ready broadcast channel=%u\n", WiFi.channel() > 0 ? WiFi.channel() : config.channel);
}

void writeU16(uint8_t *buffer, size_t offset, uint16_t value) {
  buffer[offset] = static_cast<uint8_t>(value & 0xFF);
  buffer[offset + 1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}

void writeU32(uint8_t *buffer, size_t offset, uint32_t value) {
  buffer[offset] = static_cast<uint8_t>(value & 0xFF);
  buffer[offset + 1] = static_cast<uint8_t>((value >> 8) & 0xFF);
  buffer[offset + 2] = static_cast<uint8_t>((value >> 16) & 0xFF);
  buffer[offset + 3] = static_cast<uint8_t>((value >> 24) & 0xFF);
}

uint16_t frequencyMhz(uint8_t channel) {
  return channel > 0 ? static_cast<uint16_t>(2407 + channel * 5) : 2462;
}

void sendAdrCsiPacket(const CsiSample &sample) {
  constexpr uint16_t header_len = 20;
  uint8_t packet[header_len + kMaxCsiBytes];
  writeU32(packet, 0, kAdrCsiMagic);
  packet[4] = sample.rx_node_id;
  packet[5] = 1;
  writeU16(packet, 6, sample.csi_len / 2);
  writeU32(packet, 8, frequencyMhz(sample.channel));
  writeU32(packet, 12, sample.sequence);
  packet[16] = static_cast<uint8_t>(sample.rssi);
  packet[17] = static_cast<uint8_t>(sample.noise_floor);
  packet[18] = 0;
  packet[19] = 0;
  memcpy(packet + header_len, sample.csi, sample.csi_len);

  udp.beginPacket(target_ip, config.target_port);
  udp.write(packet, header_len + sample.csi_len);
  udp.endPacket();
  ++adr_csi_sent;
}

void sendRfLinkPacket(const CsiSample &sample) {
  constexpr uint16_t header_len = 32;
  uint8_t packet[header_len + kMaxCsiBytes];
  writeU32(packet, 0, kRfLinkMagic);
  packet[4] = 2;
  packet[5] = sample.rx_node_id;
  packet[6] = sample.tx_node_id;
  packet[7] = sample.flags;
  writeU32(packet, 8, sample.sequence);
  writeU32(packet, 12, sample.uptime_ms);
  packet[16] = static_cast<uint8_t>(sample.rssi);
  packet[17] = static_cast<uint8_t>(sample.noise_floor);
  packet[18] = sample.channel;
  packet[19] = 0;
  writeU16(packet, 20, sample.csi_len);
  writeU16(packet, 22, header_len);
  memcpy(packet + 24, sample.tx_mac, sizeof(sample.tx_mac));
  packet[30] = 0;
  packet[31] = 0;
  memcpy(packet + header_len, sample.csi, sample.csi_len);

  udp.beginPacket(target_ip, config.target_port);
  udp.write(packet, header_len + sample.csi_len);
  udp.endPacket();
  ++rf_link_sent;
}

void flushCsiQueue() {
  if (!target_ip_ok || !WiFi.isConnected()) {
    return;
  }
  CsiSample sample;
  while (dequeueCsiSample(sample)) {
    sendAdrCsiPacket(sample);
    sendRfLinkPacket(sample);
  }
}

void sendHealthPacket() {
  if (!target_ip_ok || !WiFi.isConnected()) {
    return;
  }
  uint8_t packet[32] = {};
  writeU32(packet, 0, kRfHealthMagic);
  packet[4] = 1;
  packet[5] = config.node_id;
  packet[6] = config.tdm_slot;
  packet[7] = config.tdm_total;
  writeU32(packet, 8, ++health_sequence);
  writeU32(packet, 12, millis());
  packet[16] = static_cast<uint8_t>(WiFi.RSSI());
  packet[17] = static_cast<uint8_t>(WiFi.channel());
  packet[18] = config.tdm_total > 0 ? config.tdm_total - 1 : 0;
  packet[19] = static_cast<uint8_t>(dropped_csi_samples > 255 ? 255 : dropped_csi_samples);

  udp.beginPacket(target_ip, config.target_port);
  udp.write(packet, sizeof(packet));
  udp.endPacket();
}

void sendBroadcastSounding() {
  if (!esp_now_ready) {
    return;
  }
  SoundingPayload payload = {
      kSoundingMagic,
      2,
      config.node_id,
      0,
      kFlagBroadcast,
      ++sequence_counter,
      millis(),
  };
  for (uint8_t i = 0; i < kBurstPerSlot; ++i) {
    const esp_err_t err = esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t *>(&payload), sizeof(payload));
    if (err != ESP_OK) {
      ++esp_now_tx_submit_fail_count;
    }
    delay(2);
  }
}

void runTdmSounding() {
  if (!esp_now_ready || config.tdm_total == 0) {
    return;
  }
  const uint32_t now = millis();
  const uint32_t slot_index = (now / kTdmSlotMs) % config.tdm_total;
  const uint32_t slot_epoch = now / kTdmSlotMs;
  if (slot_index != config.tdm_slot || slot_epoch == last_slot_epoch) {
    return;
  }
  last_slot_epoch = slot_epoch;
  sendBroadcastSounding();
}

void handleRoot() {
  server.send(200, "text/plain", "CCTV/RuView ESP32 CSI node. Use /health, /config, /scan, /sound.\n");
}

void handleHealth() {
  server.send(200, "application/json", healthJson());
}

void handleConfigGet() {
  server.send(200, "application/json", configJson(false));
}

void handleConfigUpdate() {
  for (uint8_t i = 0; i < server.args(); ++i) {
    saveConfigValue(server.argName(i), server.arg(i));
  }
  loadConfig();
  server.send(200, "application/json", configJson(false));
}

void handleFactoryReset() {
  clearConfig();
  server.send(200, "application/json", "{\"status\":\"resetting\"}");
  delay(250);
  ESP.restart();
}

void handleReboot() {
  server.send(200, "application/json", "{\"status\":\"rebooting\"}");
  delay(250);
  ESP.restart();
}

void handleSound() {
  sendBroadcastSounding();
  server.send(200, "application/json", "{\"status\":\"broadcast_sound_sent\"}");
}

void handleScan() {
  const int count = WiFi.scanNetworks(false, true);
  String body;
  body.reserve(256 + max(count, 0) * 96);
  body += "{";
  body += "\"node_id\":" + String(config.node_id);
  body += ",\"count\":" + String(count);
  body += ",\"networks\":[";
  for (int i = 0; i < count; ++i) {
    if (i > 0) {
      body += ",";
    }
    body += "{";
    body += "\"ssid\":" + q(WiFi.SSID(i));
    body += ",\"bssid\":" + q(WiFi.BSSIDstr(i));
    body += ",\"rssi\":" + String(WiFi.RSSI(i));
    body += ",\"channel\":" + String(WiFi.channel(i));
    body += ",\"encryption\":" + String(WiFi.encryptionType(i));
    body += "}";
  }
  body += "]}";
  WiFi.scanDelete();
  server.send(200, "application/json", body);
}

void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"not_found\"}");
}

void setupHttp() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/health", HTTP_GET, handleHealth);
  server.on("/config", HTTP_GET, handleConfigGet);
  server.on("/config", HTTP_POST, handleConfigUpdate);
  server.on("/config", HTTP_PUT, handleConfigUpdate);
  server.on("/config/update", HTTP_GET, handleConfigUpdate);
  server.on("/factory-reset", HTTP_POST, handleFactoryReset);
  server.on("/reboot", HTTP_POST, handleReboot);
  server.on("/sound", HTTP_GET, handleSound);
  server.on("/scan", HTTP_GET, handleScan);
  server.onNotFound(handleNotFound);
  server.begin();

  compat_server.on("/ota/status", HTTP_GET, []() {
    compat_server.send(200, "application/json", healthJson());
  });
  compat_server.on("/sound", HTTP_GET, []() {
    sendBroadcastSounding();
    compat_server.send(200, "application/json", "{\"status\":\"broadcast_sound_sent\"}");
  });
  compat_server.begin();
  Serial.printf("[http] config=%u compat=%u\n", kConfigPort, kOtaCompatPort);
}

void handleSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) {
    return;
  }
  if (line == "SHOW") {
    Serial.println(configJson(false));
    return;
  }
  if (line == "SECRET_SHOW") {
    Serial.println(configJson(true));
    return;
  }
  if (line == "HEALTH") {
    Serial.println(healthJson());
    return;
  }
  if (line == "SOUND") {
    sendBroadcastSounding();
    Serial.println("{\"status\":\"broadcast_sound_sent\"}");
    return;
  }
  if (line == "REBOOT") {
    Serial.println("{\"status\":\"rebooting\"}");
    delay(200);
    ESP.restart();
    return;
  }
  if (line == "FACTORY_RESET") {
    clearConfig();
    Serial.println("{\"status\":\"factory_reset\"}");
    delay(200);
    ESP.restart();
    return;
  }
  if (line.startsWith("SET ")) {
    const int key_start = 4;
    const int space = line.indexOf(' ', key_start);
    if (space < 0) {
      Serial.println("{\"error\":\"usage: SET key value\"}");
      return;
    }
    const String key = line.substring(key_start, space);
    const String value = line.substring(space + 1);
    saveConfigValue(key, value);
    loadConfig();
    Serial.printf("{\"status\":\"ok\",\"key\":\"%s\"}\n", key.c_str());
    return;
  }
  Serial.println("{\"error\":\"unknown_command\"}");
}

void pollSerial() {
  static String line;
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\n') {
      handleSerialCommand(line);
      line = "";
    } else if (ch != '\r') {
      line += ch;
      if (line.length() > 900) {
        line = "";
        Serial.println("{\"error\":\"line_too_long\"}");
      }
    }
  }
}

void logStatus() {
  const uint32_t now = millis();
  if (now - last_log_ms < kStatusLogIntervalMs) {
    return;
  }
  last_log_ms = now;
  uint32_t espnow_rx = 0;
  uint32_t espnow_tx_ok = 0;
  uint32_t espnow_tx_fail = 0;
  portENTER_CRITICAL(&espnow_mux);
  espnow_rx = esp_now_rx_count;
  espnow_tx_ok = esp_now_tx_ok_count;
  espnow_tx_fail = esp_now_tx_fail_count;
  portEXIT_CRITICAL(&espnow_mux);
  Serial.printf("[status] node=%u ip=%s rssi=%d ch=%d csi=%d adr=%lu rf=%lu espnow=%d rx=%lu tx_ok=%lu tx_fail=%lu tx_submit_fail=%lu dropped=%lu heap=%u\n",
                config.node_id,
                ipAddress().c_str(),
                WiFi.isConnected() ? WiFi.RSSI() : 0,
                WiFi.channel(),
                csi_ready ? 1 : 0,
                static_cast<unsigned long>(adr_csi_sent),
                static_cast<unsigned long>(rf_link_sent),
                esp_now_ready ? 1 : 0,
                static_cast<unsigned long>(espnow_rx),
                static_cast<unsigned long>(espnow_tx_ok),
                static_cast<unsigned long>(espnow_tx_fail),
                static_cast<unsigned long>(esp_now_tx_submit_fail_count),
                static_cast<unsigned long>(dropped_csi_samples),
                ESP.getFreeHeap());
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  loadConfig();

  Serial.printf("[boot] cctv-ruview-broadcast-csi-node version=0.3.0 node=%u label=%s mac=%s\n",
                config.node_id,
                config.label.c_str(),
                macAddress().c_str());
  Serial.printf("[boot] tdm=%u/%u target=%s:%u flash=%u psram=%u\n",
                config.tdm_slot,
                config.tdm_total,
                config.target_ip.c_str(),
                config.target_port,
                ESP.getFlashChipSize(),
                ESP.getPsramSize());

  connectWifi();
  const uint32_t started = millis();
  while (!WiFi.isConnected() && millis() - started < 15000) {
    pollSerial();
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.isConnected()) {
    Serial.printf("[wifi] connected ip=%s rssi=%d channel=%d\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.channel());
    setupMdns();
    udp.begin(0);
    setupEspNow();
    setupCsi();
  } else {
    Serial.printf("[wifi] not connected status=%s\n", wifiStatusText(WiFi.status()).c_str());
  }

  setupHttp();
  Serial.println("[serial] commands: SHOW, SECRET_SHOW, HEALTH, SOUND, SET key value, REBOOT, FACTORY_RESET");
}

void loop() {
  pollSerial();
  ensureWifi();
  server.handleClient();
  compat_server.handleClient();

  if (WiFi.isConnected()) {
    if (!esp_now_ready) {
      setupEspNow();
    }
    if (!csi_ready) {
      setupCsi();
    }
    runTdmSounding();
    flushCsiQueue();
    const uint32_t now = millis();
    if (now - last_health_ms >= kHealthIntervalMs) {
      last_health_ms = now;
      sendHealthPacket();
    }
  }

  logStatus();
  delay(2);
}
