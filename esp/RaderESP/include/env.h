#pragma once
#include <Arduino.h>

struct Env {
    String mac;
    String ip;
    String gw;
    String mask;
    int    ipmode;   // 0=Static, 1=DHCP
    String ssid;
    String pwd;
    String brokerip;
};

void env_load(Env &e);
void env_save(const Env &e);
void env_print(const Env &e);
