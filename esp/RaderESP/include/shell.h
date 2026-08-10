#pragma once
#include "env.h"
#include "config.h"

// Minishell 실행
// - 3초 안에 입력 없으면 자동으로 리턴 (main 진행)
// - 'run' 명령 또는 타임아웃 시 리턴
// netMode    : DIP SW 판독 결과 (NetworkMode: 0~3)
// sensorMode : 3-state 센서 감지 결과 (SENSOR_TFMINI / SENSOR_VL53 / SENSOR_NONE)
void shell_run(Env &e, int netMode, SensorMode sensorMode);
