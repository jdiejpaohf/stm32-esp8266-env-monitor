//条件编译，防止重复调用
#ifndef __USART_H	// 判断当前文件是否被定义
#define __USART_H	// 定义

#include "stm32f10x.h"
#include <stdio.h>

// 函数声明
void usart1_init(uint32_t baud);
int fputc(int ch, FILE *f);

#endif
