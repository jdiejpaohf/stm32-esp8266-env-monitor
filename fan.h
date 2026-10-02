#ifndef __FAN_H	// 判断当前文件是否被定义
#define __FAN_H	// 定义

#include "stm32f10x.h" 
#include "sys.h" 

// 函数声明
void fan_init(void);
void fan_zz(void);
void fan_fz(void);
void fan_tz(void);

#endif
