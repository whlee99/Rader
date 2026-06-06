#include "env.h"
#include "config.h"
#include <Preferences.h>

static Preferences prefs;

void env_load(Env &e) {
    prefs.begin("rader", true);  // read-only
    e.mac      = prefs.getString("mac",      DEFAULT_MAC);
    e.ip       = prefs.getString("ip",       DEFAULT_IP);
    e.gw       = prefs.getString("gw",       DEFAULT_GW);
    e.mask     = prefs.getString("mask",     DEFAULT_MASK);
    e.ipmode   = prefs.getInt   ("ipmode",   DEFAULT_IPMODE);
    e.ssid     = prefs.getString("ssid",     DEFAULT_SSID);
    e.pwd      = prefs.getString("pwd",      DEFAULT_PWD);
    e.brokerip = prefs.getString("brokerip", DEFAULT_BROKER);
    prefs.end();
}

void env_save(const Env &e) {
    prefs.begin("rader", false);  // read-write
    prefs.putString("mac",      e.mac);
    prefs.putString("ip",       e.ip);
    prefs.putString("gw",       e.gw);
    prefs.putString("mask",     e.mask);
    prefs.putInt   ("ipmode",   e.ipmode);
    prefs.putString("ssid",     e.ssid);
    prefs.putString("pwd",      e.pwd);
    prefs.putString("brokerip", e.brokerip);
    prefs.end();
}

void env_print(const Env &e) {
    Serial.println("─────────────────────────────────");
    Serial.printf("  mac      : %s\n",   e.mac.isEmpty() ? "(default)" : e.mac.c_str());
    Serial.printf("  ip       : %s\n",   e.ip.c_str());
    Serial.printf("  gw       : %s\n",   e.gw.c_str());
    Serial.printf("  mask     : %s\n",   e.mask.c_str());
    Serial.printf("  ipmode   : %d (%s)\n", e.ipmode, e.ipmode == 0 ? "Static" : "DHCP");
    Serial.printf("  ssid     : %s\n",   e.ssid.c_str());
    Serial.printf("  pwd      : %s\n",   e.pwd.c_str());
    Serial.printf("  brokerip : %s\n",   e.brokerip.c_str());
    Serial.println("─────────────────────────────────");
}
