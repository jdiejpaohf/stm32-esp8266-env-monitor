//条件编译，防止重复调用
#ifndef __PWM_H	// 判断当前文件是否被定义
#define __PWM_H	// 定义

#include "stm32f10x.h"

// 函数声明
void LEDPWM_TIM1CH1_Init(uint16_t arr, uint16_t psc);

#endif
