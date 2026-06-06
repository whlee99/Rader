#pragma once
#include "env.h"

// Minishell 실행
// - 3초 안에 입력 없으면 자동으로 리턴 (main 진행)
// - 'run' 명령 또는 타임아웃 시 리턴
void shell_run(Env &e);
