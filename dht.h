//条件编译，防止重复调用
#ifndef __DHT_H	// 判断当前文件是否被定义
#define __DHT_H	// 定义

#include "stm32f10x.h"
#include "delay.h"

// 函数声明
void DHT_SetoutputMode(void);
void DHT_SetInputMode(void);
void DHT_Start(void);
uint32_t DHT_Check(void);
uint32_t DHT_ReadBit(void);
uint8_t DHT_ReadByte(void);
uint32_t  DHT_GetData(uint8_t *buf);

#endif
