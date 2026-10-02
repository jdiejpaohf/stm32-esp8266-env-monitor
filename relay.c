#include "relay.h"

void relay_init(void)
{
	// 1.定义一个外设的结构体变量
	GPIO_InitTypeDef GPIO_InitStructure;

	// 2.打开外设时钟  PB2--GPIOB
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);

	// 3.对结构体变量的成员进行赋值
	GPIO_InitStructure.GPIO_Pin = GPIO_Pin_2;	// 引脚配置
	GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;	// 输出速率
	GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;	// 引脚模式   推挽输出
	
	// 4.初始化GPIO
	GPIO_Init(GPIOB, &GPIO_InitStructure);

}
